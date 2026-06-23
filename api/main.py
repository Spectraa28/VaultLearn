from fastapi import FastAPI ,HTTPException
from pydantic import BaseModel
import uuid
from agent.graph import app as setup_graph
from agent.session_graph import session_app
from memory.vault import read_note,list_notes


app = FastAPI(title="VaultLearn")

session = {}

class SetupRequest(BaseModel):
    url: str

class SessionRequest(BaseModel):
    message: str
    
@app.post("/setup")
async def setup(request:SetupRequest):
    result = await setup_graph.ainvoke({"user_input":request.url})
    session_id = str(uuid.uuid4())
    session[session_id] = {
        **result,
        "messages":None,
        "struggle_signals":None,
        "anchor_urls":None,
        "notes_written":None,
        "session_active":True,
        "current_module_number":1,
    }
    return {
        "session_id":session_id,
        "study_plan":result["study_plan"].dict()
    }
    
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