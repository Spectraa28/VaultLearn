import asyncio
from rag.chunker import chunk_page

async def main():
    chunks = await chunk_page(
        url="https://docs.langchain.com/oss/python/langgraph/quickstart",
        module_number=1,
        module_name="Introduction to LangGraph",
        topic_number=2
    )
    print(f"Total chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks[:4]):
        print(f"\nChunk {i}:")
        print(f"  heading: {chunk['heading']}")
        print(f"  anchor:  {chunk['anchor_url']}")
        print(f"  preview: {chunk['text'][:80]}")

asyncio.run(main())