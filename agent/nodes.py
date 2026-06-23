from agent.state import VaultLearnState
from rag.fetcher import resolve_url,crawl_structure , generate_study_plan
from rag.retriever import build_collection , retrieve
from rag.chunker import chunk_page
from schemas.models import StruggleSignal
from langchain_core.messages import SystemMessage,HumanMessage , AIMessage
from langchain_groq import ChatGroq

async def resolve_url_node(state:VaultLearnState) -> VaultLearnState:
    # REad from state
    user_input = state["user_input"]
    # do somethin 
    url = await resolve_url(user_input)
    #Return updated state
    return {"resolved_url":url}

async def crawl_structure_node(state:VaultLearnState) -> VaultLearnState:
    # Read url  from the state 
    url = state["resolved_url"]
    #do something
    struct = await crawl_structure(url)
    # return the updated state 
    return {"pages":struct}
    
async def generate_study_plan_node(state:VaultLearnState) -> VaultLearnState:
    #read pages from the state
    pages = state["pages"]
    topic = state["user_input"]
    #do something
    study_plan = await generate_study_plan(pages,topic)
    #return the updated state
    return {"study_plan":study_plan}

async def build_collection_node(state:VaultLearnState) -> VaultLearnState:
    # read from state
    pages = state["pages"]
    study_plan = state["study_plan"]
    
    all_chunks = []
    
    total_topics = sum(
        len(module.topics)
        for module in study_plan.modules
    )

    current_topic = 0

    print(f"Starting collection build for {study_plan.title}", flush=True)
    print(f"Total topics/pages to chunk: {total_topics}", flush=True)
    
    
    for module in study_plan.modules:
        print(
            f"\nModule {module.module_number}: {module.title}",
            flush=True
        )
        for topic in module.topics:
            current_topic += 1

            print(
                f"[{current_topic}/{total_topics}] Chunking: {topic.title}",
                flush=True
            )

            chunks = await chunk_page(
                url=topic.source_url,
                module_number=module.module_number,
                module_name=module.title,
                topic_number=topic.topic_number
            )
            print(
                f"    Created {len(chunks)} chunks",
                flush=True
            )
            all_chunks.extend(chunks)
    print(f"\nFinished chunking. Total chunks: {len(all_chunks)}", flush=True)
    collection_name = study_plan.title.lower().replace(" ","-")
    
    collection= build_collection(
        chunks=all_chunks,
        collection_name=collection_name
    )
    
    
    return {"collection":collection}

async def study_session_node(state:VaultLearnState) -> VaultLearnState:
    #REad from state
    input = state["user_input"]
    collection = state["collection"]
    module_number = state["current_module_number"]
    study_plan = state["study_plan"]
    message = state["messages"]
    struggle_signal = state["struggle_signals"]
    anchor_url = state["anchor_urls"]
    
    # REtrieve the chunks 
    chunks = retrieve(collection,input,module_number)
    
    context_for_llm = "\n\n".join(chunk["text"] for chunk in chunks)
        
    sys_message =SystemMessage("You are an expert teacher. Teach using only the context provided. Always cite the source section")
    hum_message = HumanMessage(f"{input}   the given context is this {context_for_llm}")
    
    model = ChatGroq(model="llama-3.3-70b-versatile")
    
    response = await model.ainvoke([sys_message,hum_message])
    
    structured_llm = model.with_structured_output(StruggleSignal)
    struggle_response = await structured_llm.ainvoke([ HumanMessage(f"Did the user struggle? Question: {input} Answer: {response.content}")])
    updated_struggles = dict(struggle_signal or {})
    if struggle_response.struggled:
        updated_struggles[input] = struggle_response.reason
    updated_messages = (message or []) + [HumanMessage(input), AIMessage(response.content)]
    anchor_urls = [chunk["metadata"]["anchor_url"] for chunk in chunks]
    return {
        "messages": updated_messages,
        "anchor_urls":anchor_urls,
        "struggle_signals":updated_struggles
    }
    

async def end_session_node(state:VaultLearnState)  -> VaultLearnState:
    message = state["messages"]
    struggle_signal = state["struggle_signals"]