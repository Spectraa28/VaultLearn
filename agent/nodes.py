from agent.state import VaultLearnState
from rag.fetcher import resolve_url,crawl_structure , generate_study_plan
from rag.retriever import build_collection
from rag.chunker import chunk_page

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