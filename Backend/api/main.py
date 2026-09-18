"""VaultLearn API with durable sessions and inspectable runs."""

import asyncio
import json
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

from agent.graph import app as setup_graph
from agent.session_graph import session_app
from memory.vault import list_notes, read_note
from observability import event, run_context
from rag.retriever import client as chroma_client
from schemas.models import StudyPlan
from storage import (
    attach_run_to_session, create_session, finish_run, get_runs, get_session,
    get_trace, get_turns, get_usage, init_db, list_sessions, save_exchange,
    start_run, mark_abandoned_runs,
)


app = FastAPI(title="VaultLearn")
init_db()
mark_abandoned_runs()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SetupRequest(BaseModel):
    url: str


class SessionRequest(BaseModel):
    message: str = Field(min_length=1)
    current_module_number: int | None = None


def sse(event_type: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': event_type, **kwargs})}\n\n"


@app.post("/setup")
async def setup(request: SetupRequest):
    return StreamingResponse(
        setup_stream(request.url), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def setup_stream(url: str):
    run_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    collection_name = f"vaultlearn-{session_id}"
    start_run(run_id, "setup")
    queue = asyncio.Queue()
    graph_task = None
    try:
        yield sse("status", message="Resolving documentation URL...", run_id=run_id)

        async def run_setup():
            with run_context(run_id):
                return await setup_graph.ainvoke({
                    "user_input": url, "progress_queue": queue,
                    "collection_name": collection_name,
                })

        graph_task = asyncio.create_task(run_setup())
        yield sse("status", message="Crawling documentation structure...", run_id=run_id)
        while not graph_task.done():
            try:
                progress = await asyncio.wait_for(queue.get(), timeout=0.2)
                yield sse("progress", **progress, run_id=run_id)
            except asyncio.TimeoutError:
                pass
        result = await graph_task
        while not queue.empty():
            yield sse("progress", **queue.get_nowait(), run_id=run_id)
        plan = result["study_plan"]
        resolved_url = result.get("resolved_url", url)
        create_session(session_id, resolved_url, plan.title, collection_name, plan.model_dump_json(), result.get("index_report"))
        attach_run_to_session(run_id, session_id)
        finish_run(run_id, "completed", session_id=session_id)
        yield sse("done", session_id=session_id, run_id=run_id,
                  study_plan=plan.model_dump(), collection_name=collection_name,
                  resolved_url=resolved_url,
                  index_report=result.get("index_report", {}))
    except asyncio.CancelledError:
        if graph_task:
            graph_task.cancel()
        finish_run(run_id, "cancelled")
        raise
    except Exception as exc:
        finish_run(run_id, "failed", type(exc).__name__)
        yield sse("error", run_id=run_id, code=getattr(exc, "code", "setup_failed"),
                  message=str(exc), candidates=getattr(exc, "candidates", []))


@app.post("/session/{session_id}/message")
async def chat(session_id: str, request: SessionRequest):
    record = get_session(session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")
    plan = StudyPlan.model_validate_json(record["study_plan_json"])
    module_number = request.current_module_number or record["current_module_number"]
    if module_number not in {module.module_number for module in plan.modules}:
        raise HTTPException(status_code=422, detail="Unknown module number")
    try:
        collection = chroma_client.get_collection(record["collection_name"])
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Documentation index is unavailable; re-index this topic") from exc

    turns = get_turns(session_id)
    messages = [HumanMessage(t["content"]) if t["role"] == "user" else AIMessage(t["content"]) for t in turns]
    state = {
        "user_input": request.message, "collection": collection, "study_plan": plan,
        "session_id": session_id,
        "current_module_number": module_number, "messages": messages,
        "struggle_signals": json.loads(record["struggle_signals_json"] or "{}"),
        "pending_quiz": json.loads(record["pending_quiz_json"] or "{}"),
        "mastery_scores": json.loads(record["mastery_scores_json"] or "{}"),
        "anchor_urls": [], "notes_written": False,
    }
    run_id = str(uuid.uuid4())
    start_run(run_id, "session_turn", session_id)
    try:
        with run_context(run_id, session_id):
            result = await session_app.ainvoke(state)
            ended = request.message.lower().strip() == "end session"
            answer = "Session ended and notes saved." if ended else result["messages"][-1].content
            save_exchange(session_id, request.message, answer, result.get("anchor_urls", []),
                          module_number, result.get("struggle_signals"), result.get("notes_written", False),
                          result.get("pending_quiz"), result.get("mastery_scores"))
            event("session.persisted", details={"module_number": module_number, "notes_written": bool(result.get("notes_written"))})
        finish_run(run_id, "completed")
    except Exception as exc:
        finish_run(run_id, "failed", type(exc).__name__)
        raise
    return {
        "answer": answer, "citation": result.get("anchor_urls", []),
        "struggle_signals": result.get("struggle_signals", {}),
        "notes_written": result.get("notes_written", False), "run_id": run_id,
    }


@app.get("/sessions")
def sessions():
    return {"sessions": list_sessions()}


@app.post("/session/{session_id}/resume")
def resume(session_id: str):
    record = get_session(session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        chroma_client.get_collection(record["collection_name"])
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Documentation index is unavailable; re-index this topic") from exc
    plan = StudyPlan.model_validate_json(record["study_plan_json"])
    return {
        "resumed": True, "session_id": session_id, "study_plan": plan.model_dump(),
        "current_module_number": record["current_module_number"],
        "messages": get_turns(session_id),
        "struggle_signals": json.loads(record["struggle_signals_json"] or "{}"),
        "pending_quiz": bool(json.loads(record["pending_quiz_json"] or "{}")),
        "mastery_scores": json.loads(record["mastery_scores_json"] or "{}"),
        "index_report": json.loads(record["index_report_json"] or "{}"),
    }


@app.get("/runs/{run_id}/trace")
def trace(run_id: str):
    result = get_trace(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@app.get("/usage")
def usage():
    return get_usage()


@app.get("/session/{session_id}/usage")
def session_usage(session_id: str):
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return get_usage(session_id)


@app.get("/session/{session_id}/runs")
def session_runs(session_id: str):
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"runs": get_runs(session_id)}


@app.get("/vault")
def list_vault():
    return {"files": list_notes()}


@app.get("/vault/{filename}")
def get_note(filename: str):
    try:
        content = read_note(filename.removesuffix(".md"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not content:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"filename": filename, "content": content}
