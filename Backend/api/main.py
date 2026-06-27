from fastapi import FastAPI ,HTTPException
from pydantic import BaseModel
import uuid
from agent.graph import app as setup_graph
from agent.session_graph import session_app
from memory.vault import read_note,list_notes
from fastapi.middleware.cors import CORSMiddleware
import json 
import asyncio
from fastapi.responses import StreamingResponse
import sqlite3 
from datetime import datetime


app = FastAPI(title="VaultLearn")
chunk_progress_queue: asyncio.Queue = None

session = {}

class SetupRequest(BaseModel):
    url: str

class SessionRequest(BaseModel):
    message: str
    
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/setup")
async def setup(request: SetupRequest):
    return StreamingResponse(
        setup_stream(request.url),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
    
@app.post("/session/{session_id}/message")
async def chat(session_id: str, request:SessionRequest):
    if session_id not in session:
        raise HTTPException(status_code=404,detail="Session not found")
    
    state = session[session_id]
    state["user_input"] = request.message
    
    result = await  session_app.ainvoke(state)
    session[session_id] = result
    
    answer = result["messages"][-1].content if result["messages"] else ""
    
    return {
        "answer":answer,
        "citation":result.get("anchor_urls",[]),
        "struggle_signals": result.get("struggle_signals",{}),
        "notes_written":result.get("notes_written",False)
    }
    
@app.get("/vault")
def list_vault():
    return {"files":list_notes()}

@app.get("/vault/{filename}")
def get_note(filename: str):
    content = read_note(filename.replace(".md",""))
    if not content:
        raise HTTPException(status_code=404,detail="Note not found")
    return {"filename":filename,"content":content}

def sse(type: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': type, **kwargs})}\n\n"


async def setup_stream(url: str):
    try:
        queue = asyncio.Queue()
        session_id = str(uuid.uuid4())

        yield sse(type="status", message="Resolving documentation URL...")

        graph_task = asyncio.create_task(
            setup_graph.ainvoke({
                "user_input": url,
                "progress_queue": queue
            })
        )

        yield sse(type="status", message="Crawling documentation structure...")

        while not graph_task.done():
            try:
                event = queue.get_nowait()
                yield sse(
                    type="progress",
                    current=event["current"],
                    total=event["total"],
                    page=event["page"],
                    module=event["module"]
                )
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.05)

        result = await graph_task

        session[session_id] = {
            **result,
            "messages": None,
            "struggle_signals": None,
            "anchor_urls": None,
            "notes_written": None,
            "session_active": True,
            "current_module_number": 1,
        }

        collection_name = result["study_plan"].title.lower().replace(" ", "-")

        save_session(
            session_id=session_id,
            url=url,
            title=result["study_plan"].title,
            collection_name=collection_name,
            study_plan_json=result["study_plan"].model_dump_json()
        )
        study_plan = result.get("study_plan")
        yield sse(
            type="done",
            session_id=session_id,
            study_plan=study_plan.dict() if study_plan else {},
            collection_name=result["study_plan"].title.lower().replace(" ", "-"),
            study_plan_json=result["study_plan"].model_dump_json()
        )

    except Exception as e:
        yield sse(type="error", message=str(e))
        
        
def init_db():
    conn = sqlite3.connect("sessions.db")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        url TEXT,
        title TEXT,
        created_at TEXT,
        collection_name TEXT,
        study_plan_json TEXT
    )
""")
    conn.commit()
    conn.close()

init_db()

def save_session(session_id, url, title,collection_name: str, study_plan_json: str):
    init_db()
    conn = sqlite3.connect("sessions.db")
    conn.execute("""
        INSERT OR REPLACE INTO sessions (session_id, url, title, created_at, collection_name, study_plan_json)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session_id, url, title, datetime.now().isoformat(), collection_name, study_plan_json))
    conn.commit()
    conn.close()
    
def list_session() -> list[dict]:
    init_db()
    conn = sqlite3.connect("sessions.db")
    rows = conn.execute(
        "SELECT session_id,url,title,created_at FROM sessions ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [
        {"session_id":r[0],"url":r[1], "title": r[2], "created_at": r[3]}
        for r in rows
    ]

@app.get("/sessions")
def get_sessions():
    return {"sessions": list_session()}

@app.post("/session/{session_id}/resume")
async def resume(session_id: str):
    conn = sqlite3.connect("sessions.db")
    row = conn.execute(
        "SELECT url, title, collection_name, study_plan_json FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    url, title, collection_name, study_plan_json = row

    try:
        # try loading existing ChromaDB collection
        from rag.retriever import client as chroma_client
        from schemas.models import StudyPlan
        
        collection = chroma_client.get_collection(collection_name)
        study_plan = StudyPlan.model_validate_json(study_plan_json)

        # restore session in memory
        session[session_id] = {
            "collection": collection,
            "study_plan": study_plan,
            "resolved_url": url,
            "pages": None,
            "messages": None,
            "struggle_signals": None,
            "anchor_urls": None,
            "notes_written": None,
            "session_active": True,
            "current_module_number": 1,
            "progress_queue": None,
            "module_ready": None,
        }

        return {
            "resumed": True,
            "session_id": session_id,
            "study_plan": study_plan.dict()
        }

    except Exception:
        # collection gone — re-crawl
        return StreamingResponse(
            setup_stream(url),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )