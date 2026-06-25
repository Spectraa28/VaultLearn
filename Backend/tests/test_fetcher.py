import asyncio
from rag.chunker import chunk_page
from rag.retriever import build_collection
from rag.fetcher import crawl_structure,generate_study_plan

async def test():
    result = await app.ainvoke({"user_input": "FastAPI"})

    print("URL:", result["resolved_url"])
    print("Pages found:", len(result["pages"]))
    print("Study plan title:", result["study_plan"].title)
    print("Modules:", len(result["study_plan"].modules))
    print("Chunks:", len(result["chunks"]))
    print("Collection count:", result["collection"].count())

asyncio.run(test())