from langchain_text_splitters import MarkdownHeaderTextSplitter
from markdownify import markdownify as md
import httpx

async def fetch_page_content(url: str) -> str:
    jina_url = f"https://r.jina.ai/{url}"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            jina_url,
            follow_redirects=True,
            timeout=30
        )
    content = response.text
    # strip Jina metadata — content starts at first # header
    if "# " in content:
        content = content[content.index("# "):]
    return content


async def chunk_page(url:str,module_number:int,module_name:str,topic_number:int)->list[dict]:
    markdown = await fetch_page_content(url)
    headers_to_split_on = [
    ("#", "title"),
    ("##", "section"),
    ("###", "subsection"),
    ]
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    chunks= splitter.split_text(markdown)
    result = []
    for i , chunk in enumerate(chunks):
        metadata = chunk.metadata
        heading = metadata.get("section") or metadata.get("subsection") or metadata.get("title") or ""
        anchor_slug = heading.lower().replace(" ","-")
        
        result.append({
            "text":chunk.page_content,
            "doc_link":url,
            "title":metadata.get("title",""),
            "heading":heading,
            "anchor_url":f"{url}#{anchor_slug}",
            "module_number": module_number,
            "module_name": module_name,
            "topic_number":topic_number,
            "chunk_index": i
        })
        
    return result