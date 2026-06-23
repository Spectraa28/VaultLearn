from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from markdownify import markdownify as md
import httpx
import re

async def fetch_page_content(url: str) -> str:
    jina_url = f"https://r.jina.ai/{url}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                jina_url,
                follow_redirects=True,
                timeout=30
            )
            content = response.text
            if "# " in content:
                content = content[content.index("# "):]
            return content
        except httpx.TimeoutException:
            return ""  # return empty, chunker will handle it


async def chunk_page(
    url: str,
    module_number: int,
    module_name: str,
    topic_number: int
) -> list[dict]:
    markdown = await fetch_page_content(url)

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
    