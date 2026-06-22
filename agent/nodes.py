from agent.state import VaultLearnState
from rag.fetcher import resolve_url,crawl_structure , generate_study_plan

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