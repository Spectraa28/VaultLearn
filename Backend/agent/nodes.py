from agent.state import VaultLearnState
from rag.fetcher import resolve_url,crawl_structure , generate_study_plan
from rag.retriever import build_collection , retrieve
from rag.chunker import chunk_page
from schemas.models import QuizEvaluation, QuizQuestion, SessionDecision
from langchain_core.messages import SystemMessage,HumanMessage , AIMessage
from langchain_groq import ChatGroq
from memory.vault import generate_review_schedule,read_note, generate_session_note,generate_struggle_note , write_note, note_key
from observability import ANSWER_MODEL, URL_MODEL, traced_node, tracked_invoke, event
import asyncio
import math


class IndexCoverageError(ValueError):
    code = "insufficient_index_coverage"

@traced_node("resolve_url")
async def resolve_url_node(state:VaultLearnState) -> VaultLearnState:
    # REad from state
    user_input = state["user_input"]
    # do somethin 
    url = await resolve_url(user_input)
    #Return updated state
    return {"resolved_url":url}

@traced_node("crawl_structure")
async def crawl_structure_node(state:VaultLearnState) -> VaultLearnState:
    # Read url  from the state 
    url = state["resolved_url"]
    #do something
    struct, crawl_report = await crawl_structure(url, with_report=True)
    # in crawl_structure_node, add this:
    print(f"Crawling: {url}")
    # return the updated state 
    return {"pages":struct, "crawl_report": crawl_report}
    
@traced_node("generate_study_plan")
async def generate_study_plan_node(state:VaultLearnState) -> VaultLearnState:
    #read pages from the state
    pages = state["pages"]
    topic = state["user_input"]
    #do something
    study_plan = await generate_study_plan(pages,topic)
    #return the updated state
    return {"study_plan":study_plan}

@traced_node("build_collection")
async def build_collection_node(state:VaultLearnState) -> VaultLearnState:
    study_plan = state["study_plan"]
    all_chunks = []
    kept_modules = []
    failures = []
    total_topics = sum(len(module.topics) for module in study_plan.modules)
    current_topic = 0
    if not total_topics:
        raise IndexCoverageError("The study plan contains no documentation pages to index.")
    for module in study_plan.modules:
        kept_topics = []
        for topic in module.topics:
            current_topic += 1
            try:
                chunks = await chunk_page(
                    url=topic.source_url, module_number=module.module_number,
                    module_name=module.title, topic_number=topic.topic_number,
                )
            except Exception as exc:
                chunks = []
                event("index.page_failed", status="error", details={"url": topic.source_url, "error_type": type(exc).__name__})
            if chunks:
                kept_topics.append(topic)
                all_chunks.extend(chunks)
            else:
                failures.append(topic.source_url)
                event("index.page_skipped", status="error", details={"url": topic.source_url})
            queue = state.get("progress_queue")
            if queue:
                await queue.put({
                    "current": current_topic, "total": total_topics,
                    "page": topic.title, "module": module.title,
                    "status": "indexed" if chunks else "skipped",
                })
        if kept_topics:
            new_number = len(kept_modules) + 1
            for chunk in all_chunks:
                if chunk["module_number"] == module.module_number:
                    chunk["module_number"] = new_number
            kept_modules.append(module.model_copy(update={
                "module_number": new_number,
                "topics": [topic.model_copy(update={"topic_number": index + 1})
                           for index, topic in enumerate(kept_topics)],
            }))

    indexed = total_topics - len(failures)
    report = {**(state.get("crawl_report") or {}), "attempted_pages": total_topics, "indexed_pages": indexed,
              "skipped_pages": failures, "coverage": round(indexed / total_topics, 3),
              "chunks": len(all_chunks)}
    event("index.coverage", details=report)
    if indexed < max(1, math.ceil(total_topics * 0.6)):
        raise IndexCoverageError(
            f"Only {indexed}/{total_topics} documentation pages could be indexed. "
            "Check the source URL or try a different documentation section."
        )
    study_plan = study_plan.model_copy(update={"modules": kept_modules})
    collection_name = state.get("collection_name") or study_plan.title.lower().replace(" ","-")
    collection = await asyncio.to_thread(build_collection, chunks=all_chunks,
                                         collection_name=collection_name)
    return {"collection": collection, "study_plan": study_plan, "index_report": report}

@traced_node("study_session")
async def study_session_node(state: VaultLearnState) -> VaultLearnState:
    # Read from state
    input = state["user_input"]
    collection = state["collection"]
    module_number = state.get("current_module_number", 1)
    study_plan = state["study_plan"]
    message = state["messages"]
    struggle_signal = state["struggle_signals"]

    # Early exit for end session
    if input.lower().strip() == "end session":
        return {
            "messages": message or [],
            "struggle_signals": struggle_signal or {},
            "anchor_urls": [],
        }

    # Retrieve the chunks
    chunks = await asyncio.to_thread(retrieve, collection, input, module_number)
    event("retrieval.completed", details={"module_number": module_number, "chunks": len(chunks)})
    if not chunks:
        response_content = "I couldn't find relevant evidence in this module. Try another module or rephrase the question."
        return {"messages": (message or []) + [HumanMessage(input), AIMessage(response_content)], "anchor_urls": [], "struggle_signals": struggle_signal or {}}
    context_for_llm = "\n\n".join(chunk["text"] for chunk in chunks)
    recent = [m for m in (message or []) if isinstance(m, (HumanMessage, AIMessage))][-6:]
    history = "\n".join(f"{'Learner' if isinstance(m, HumanMessage) else 'Tutor'}: {str(m.content)[:600]}" for m in recent)

    sys_message = SystemMessage("You are an expert teacher. Teach using only the context provided. Always cite the source section")
    hum_message = HumanMessage(f"Previous learning notes (may be stale; documentation wins if they conflict):\n{state.get('vault_context') or 'None'}\n\nRecent conversation:\n{history}\n\nCurrent question: {input}\n\nDocumentation context:\n{context_for_llm}")

    model = ChatGroq(model=ANSWER_MODEL)
    response = await tracked_invoke(model, [sys_message, hum_message], model=ANSWER_MODEL, operation="answer")

    updated_messages = (message or []) + [HumanMessage(input), AIMessage(response.content)]
    anchor_urls = [chunk["metadata"]["anchor_url"] for chunk in chunks]

    return {
        "messages": updated_messages,
        "anchor_urls": anchor_urls,
        "struggle_signals": struggle_signal or {},
    }


@traced_node("choose_action")
async def choose_action_node(state: VaultLearnState) -> VaultLearnState:
    user_input = state["user_input"].strip()
    if user_input.lower() == "end session":
        action, reason = "end", "Learner ended the session"
    elif state.get("pending_quiz"):
        action, reason = "grade", "A quiz answer is pending"
    elif user_input.lower() in {"quiz me", "test me", "give me a quiz"}:
        action, reason = "quiz", "Learner requested a quiz"
    else:
        model = ChatGroq(model=URL_MODEL)
        routed = model.with_structured_output(SessionDecision, include_raw=True)
        recent = [m for m in (state.get("messages") or []) if isinstance(m, (HumanMessage, AIMessage))][-4:]
        history = "\n".join(f"{'Learner' if isinstance(m, HumanMessage) else 'Tutor'}: {str(m.content)[:350]}" for m in recent)
        decision = await tracked_invoke(routed, [
            SystemMessage("Choose whether to answer the learner's question or ask a short quiz to verify understanding. Prefer answer for questions. Choose quiz when the learner asks to be tested or repeatedly requests explanation of the same concept. Return a brief reason."),
            HumanMessage(f"Recent conversation:\n{history}\n\nCurrent input: {user_input}"),
        ], model=URL_MODEL, operation="choose_action")
        action, reason = decision.action, decision.reason
    event("agent.decision", details={"action": action, "reason": reason})
    return {"action": action}


@traced_node("generate_quiz")
async def generate_quiz_node(state: VaultLearnState) -> VaultLearnState:
    module_number = state["current_module_number"]
    module = next((m for m in state["study_plan"].modules if m.module_number == module_number), None)
    topic = module.title if module else state["study_plan"].title
    chunks = await asyncio.to_thread(retrieve, state["collection"], topic, module_number)
    event("retrieval.completed", details={"module_number": module_number, "chunks": len(chunks), "purpose": "quiz"})
    if not chunks:
        answer = "I couldn't find enough documentation in this module to make a fair quiz."
        return {"messages": (state.get("messages") or []) + [HumanMessage(state["user_input"]), AIMessage(answer)], "anchor_urls": []}
    context = "\n\n".join(chunk["text"] for chunk in chunks[:3])
    model = ChatGroq(model=URL_MODEL)
    structured = model.with_structured_output(QuizQuestion, include_raw=True)
    quiz = await tracked_invoke(structured, [
        SystemMessage("Write one concise question that tests understanding of the supplied documentation. Give a correct expected answer and a short concept label. Do not ask trivia about page titles."),
        HumanMessage(f"Module: {topic}\nDocumentation:\n{context}"),
    ], model=URL_MODEL, operation="generate_quiz")
    answer = f"Quick check on **{quiz.concept}**: {quiz.question}\n\nReply with your answer and I'll assess it."
    return {"messages": (state.get("messages") or []) + [HumanMessage(state["user_input"]), AIMessage(answer)],
            "pending_quiz": quiz.model_dump(), "anchor_urls": [chunk["metadata"]["anchor_url"] for chunk in chunks[:3]]}


@traced_node("grade_quiz")
async def grade_quiz_node(state: VaultLearnState) -> VaultLearnState:
    quiz = state["pending_quiz"]
    model = ChatGroq(model=URL_MODEL)
    structured = model.with_structured_output(QuizEvaluation, include_raw=True)
    evaluation = await tracked_invoke(structured, [
        SystemMessage("Grade the learner's answer fairly. Accept equivalent correct explanations. Give specific, constructive feedback and use the supplied concept label."),
        HumanMessage(f"Concept: {quiz['concept']}\nQuestion: {quiz['question']}\nExpected answer: {quiz['expected_answer']}\nLearner answer: {state['user_input']}"),
    ], model=URL_MODEL, operation="grade_quiz")
    mastery = dict(state.get("mastery_scores") or {})
    concept = quiz["concept"]
    old_score = float(mastery.get(concept, 0.5))
    mastery[concept] = round(min(1.0, max(0.0, old_score + (0.2 if evaluation.correct else -0.15))), 2)
    struggles = dict(state.get("struggle_signals") or {})
    if not evaluation.correct:
        struggles[quiz["question"]] = evaluation.feedback
    answer = f"{'Correct' if evaluation.correct else 'Not quite'}. {evaluation.feedback}\n\nMastery for **{concept}**: {mastery[concept]:.0%}."
    event("quiz.graded", details={"concept": concept, "correct": evaluation.correct, "mastery": mastery[concept]})
    return {"messages": (state.get("messages") or []) + [HumanMessage(state["user_input"]), AIMessage(answer)],
            "pending_quiz": {}, "mastery_scores": mastery, "struggle_signals": struggles, "anchor_urls": []}
    

@traced_node("write_notes")
async def write_notes_node(state:VaultLearnState) -> VaultLearnState:
    study_plan  = state["study_plan"]
    message = state["messages"]
    module_number = state["current_module_number"]
    struggle_signal = state["struggle_signals"]
    if not study_plan:
        return {"notes_written": False}
    session_content = await generate_session_note(study_plan, message, module_number)
    struggle_content = generate_struggle_note(struggle_signal or {}, study_plan.title)
    review_content = generate_review_schedule(struggle_signal or {}, study_plan.title)
   
    title_key = note_key(study_plan.title)
    write_note(f"{title_key}_session", session_content)
    write_note(f"{title_key}_struggles", struggle_content)
    write_note(f"{title_key}_review", review_content)
    if state.get("session_id"):
        archive_prefix = f"{title_key}_{state['session_id'][:8]}"
        write_note(f"{archive_prefix}_session", session_content)
        write_note(f"{archive_prefix}_struggles", struggle_content)
        write_note(f"{archive_prefix}_review", review_content)
    
    return {"notes_written": True}

def read_vault_node(state: VaultLearnState) -> VaultLearnState:
    title = note_key(state["study_plan"].title)
    context_session = read_note(f"{title}_session") or ""
    context_struggles = read_note(f"{title}_struggles") or ""
    context_review = read_note(f"{title}_review") or ""
    
    
    context = f"Session: {context_session[:2000]}\nStruggles: {context_struggles[:1000]}\nReview: {context_review[:500]}"
    return {"vault_context": context}
