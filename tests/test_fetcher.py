import asyncio
from rag.fetcher import resolve_url
from rag.fetcher import crawl_structure , generate_study_plan

async def main():
    url = await resolve_url("claudecode")
    print(f"Resolved URL: {url}")
    pages = await crawl_structure(url)
    print(f"Found {len(pages)} pages")
    study_plan = await generate_study_plan(pages, "claudecode")
    print(study_plan)
    
asyncio.run(main())