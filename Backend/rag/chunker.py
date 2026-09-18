from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from markdownify import markdownify as md
import httpx
import re
import asyncio
from bs4 import BeautifulSoup
from rag.security import safe_request, validate_public_url


def _usable_content(content: str) -> bool:
    text = re.sub(r"[#*`_>\[\]()]+", " ", content).strip()
    if len(text) < 120 or len(text.split()) < 20:
        return False
    start = text[:180].lower()
    return not any(marker in start for marker in ("404 not found", "page not found", "access denied", "enable javascript"))

async def fetch_page_content(url: str) -> str:
    await asyncio.to_thread(validate_public_url, url)
    async with httpx.AsyncClient() as client:
        try:
            response = await safe_request(client, "GET", url, timeout=15)
            content_type = response.headers.get("content-type", "text/html").lower()
            if response.status_code == 200 and len(response.content) <= 5_000_000:
                if "html" in content_type:
                    soup = BeautifulSoup(response.text, "html.parser")
                    for tag in soup.select("script, style, nav, header, footer, aside, noscript"):
                        tag.decompose()
                    content = md(str(soup.select_one("main, article, [role=main]") or soup.body or soup))
                elif "markdown" in content_type or "text/plain" in content_type:
                    content = response.text
                else:
                    content = ""
                if _usable_content(content):
                    return content
        except (httpx.HTTPError, ValueError):
            pass

        # A rendering proxy is a fallback, not the sole source of page content.
        try:
            response = await safe_request(client, "GET", f"https://r.jina.ai/{url}", timeout=30)
            if response.status_code == 200 and len(response.content) <= 5_000_000:
                content = response.text
                if "# " in content:
                    content = content[content.index("# "):]
                if _usable_content(content):
                    return content
        except (httpx.HTTPError, ValueError):
            pass
    return ""


async def chunk_page(
    url: str,
    module_number: int,
    module_name: str,
    topic_number: int
) -> list[dict]:
    markdown = await fetch_page_content(url)
    if not markdown.strip():
        return []

    headers_to_split_on = [
        ("#", "title"),
        ("##", "section"),
        ("###", "subsection"),
    ]

    # First split the markdown by headings
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    chunks = splitter.split_text(markdown)

    # This splitter is only used when a heading-based chunk is too large
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150
    )

    result = []
    chunk_index = 0

    for chunk in chunks:
        metadata = chunk.metadata

        heading = (
            metadata.get("section")
            or metadata.get("subsection")
            or metadata.get("title")
            or ""
        )

        anchor_slug = re.sub(
            r"[^\w\s-]",
            "",
            heading.lower()
        ).strip().replace(" ", "-")

        base_chunk = {
            "doc_link": url,
            "title": metadata.get("title", ""),
            "heading": heading,
            "anchor_url": f"{url}#{anchor_slug}",
            "module_number": module_number,
            "module_name": module_name,
            "topic_number": topic_number,
        }

        # If the chunk is too large, split it into smaller strings
        if len(chunk.page_content) > 1000:
            sub_texts = char_splitter.split_text(chunk.page_content)
        else:
            sub_texts = [chunk.page_content]

        # Preserve all metadata, only replace the text field
        for sub_text in sub_texts:
            new_chunk = base_chunk.copy()
            new_chunk["text"] = sub_text
            new_chunk["chunk_index"] = chunk_index

            result.append(new_chunk)
            chunk_index += 1

    if not chunks:
        # If MarkdownHeaderTextSplitter found no chunks, fallback to raw markdown
        if len(markdown) > 1000:
            sub_texts = char_splitter.split_text(markdown)
        else:
            sub_texts = [markdown]

        for sub_text in sub_texts:
            result.append({
                "text": sub_text,
                "doc_link": url,
                "title": "",
                "heading": "",
                "anchor_url": url,
                "module_number": module_number,
                "module_name": module_name,
                "topic_number": topic_number,
                "chunk_index": chunk_index
            })

            chunk_index += 1

    return result


def split_oversized_chunks(chunks: list[dict], splitter, max_chunk_size: int) -> list[dict]:
    """
    Splits oversized chunks into smaller chunks while preserving metadata.

    Each input chunk is expected to be a dict like:
    {
        "text": "...",
        "url": "...",
        "title": "...",
        ...
    }
    """

    final_chunks = []

    for chunk in chunks:
        text = chunk["text"]

        # If chunk is small enough, keep it as it is
        if len(text) <= max_chunk_size:
            final_chunks.append(chunk)
            continue

        # Split only oversized chunks
        sub_texts = splitter.split_text(text)

        # Create a new chunk for each split part
        for sub_text in sub_texts:
            new_chunk = chunk.copy()
            new_chunk["text"] = sub_text
            final_chunks.append(new_chunk)

    return final_chunks
