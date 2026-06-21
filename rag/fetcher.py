import os 
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv()

def resolve_doc_url(query:str) -> str:
    query = query.strip()
    if query.startswith(("http://","https://")):
        return query
    
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response =  client.search(query=f"{query} official documentation", max_results=3)
    
    results =  response["results"]
    if not results:
        raise ValueError(f"No search result found for '{query}")
    
    return results[0]["url"]