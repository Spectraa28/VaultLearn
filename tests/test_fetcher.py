import asyncio
from agent.graph import app

async def main():
    result = await app.ainvoke({
        "user_input": "LangGraph"
    })
    print(f"Resolved URL: {result['resolved_url']}")
    print(f"Found {len(result['pages'])} pages")
    print(result['study_plan'])

asyncio.run(main())