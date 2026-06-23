"""
Fetcher layer

This layer's responsibility is to fetch the URL from the given input
and parse the HTML to extract data from it.
"""

import httpx
import json
import re
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from schemas.models import UrlResponse
from urllib.parse import urlparse
from pathlib import Path
from schemas.models import StudyPlan, Topic, Module,PlannedModule, PlannedStudyPlan
from langchain_core.messages import SystemMessage
from playwright.async_api import async_playwright
from typing import Literal



# Load environment variables from the .env file
load_dotenv()


async def resolve_url(input: str) -> str:
    """
    Fetches the documentation URL for the query.

    1. Try getting the link from the LLM.
    2. If that URL works, return it.
    3. If it fails or cannot resolve, fall back to DuckDuckGo search.
    """

    model = ChatGroq(model="qwen/qwen3-32b")
    url_model = model.with_structured_output(UrlResponse)

    response = await url_model.ainvoke(
        f"Provide the documentation link for the {input}"
    )

    url = response.url
    tech_name = input.lower().replace(" ", "")

    async with httpx.AsyncClient() as client:
        if await is_url_alive(client, url):
            return url

        with DDGS() as ddgs:
            result = ddgs.text(
                f"{input} official documentation",
                max_results=5
            )

            if not result:
                raise Exception(
                    "Could not resolve documentation URL, please try again"
                )

            doc_url = None

            for r in result:
                href = r["href"]

                if not any(keyword in href for keyword in ["docs", "github.io"]):
                    continue
                if tech_name not in href.lower():
                    continue
                
                try:
                    page_response = await client.get(href,follow_redirects=True)
                    if is_docs_page(page_response.text):
                        return href
                except (httpx.ConnectError,httpx.TimeoutException):
                    continue

            raise Exception("Could not find valid documentation URL, please try again")


async def crawl_structure(site_to_crawl: str) -> list[dict]:
    """
    Crawls the documentation structure of a given site.

    The function first attempts to read the site's sitemap.xml.
    If the sitemap is missing, too small, or not useful, it falls back to
    crawling the sidebar and then JavaScript-rendered links.
    """

    # Remove trailing slash to keep URL handling consistent
    site_to_crawl = site_to_crawl.rstrip("/")

    # Parse the provided URL
    parsed = urlparse(site_to_crawl)

    # Build the root URL and sitemap URL
    root = f"{parsed.scheme}://{parsed.netloc}"
    sitemap_url = f"{root}/sitemap.xml"

    async with httpx.AsyncClient() as client:
        response = await client.get(sitemap_url, follow_redirects=True)

    # Parse sitemap XML response
    soup = BeautifulSoup(response.text, "xml")

    # Extract all <url> entries from sitemap.xml
    urls = soup.find_all("url")

    # Create a prefix based on the current documentation path
    path = parsed.path.rstrip("/")
    if path:
        parent = str(Path(path).parent).rstrip("/")
        prefix = f"{parsed.scheme}://{parsed.netloc}{parent}/"
    else:
        prefix = f"{parsed.scheme}://{parsed.netloc}/"

    result = []

    # Extract URLs, titles, and last modified dates from the sitemap
    for url in urls:
        loc = url.find("loc").text
        lastmod = url.find("lastmod")
        lastmod = lastmod.text if lastmod else "unknown"

        # Only include URLs that belong to the same documentation section
        if not loc.startswith(prefix):
            continue

        # Generate a readable title from the URL path
        title = loc.replace(prefix, "").replace("-", " ").title()

        result.append({
            "url": loc,
            "title": title,
            "lastmod": lastmod
        })

    

    # Fallback to static sidebar crawling if sitemap data is not useful
    if response.status_code != 200 or len(result) < 5:
        result = await crawl_sidebar(site_to_crawl)

    # Fallback to JavaScript-rendered sidebar crawling if still insufficient
    if len(result) < 5:
        result = await crawl_js_sidebar(site_to_crawl)

    return result


async def crawl_sidebar(url: str) -> list[dict]:
    """
    Crawls links from a static HTML sidebar or navigation section.

    This is useful for documentation sites where navigation links are
    available in the initial HTML response.
    """

    async with httpx.AsyncClient() as client:
        response = await client.get(url, follow_redirects=True)


    # Ensure the page loaded successfully
    if response.status_code == 200:
        html_content = response.text
    else:
        raise Exception("Failed to load the html page")

    # Parse the HTML content
    soup = BeautifulSoup(html_content, "html.parser")

    # Try to find a semantic sidebar first
    sidebar = soup.find("aside")

    # If no <aside> exists, look for common navigation containers
    if not sidebar:
        sidebar = soup.find(
            ["nav", "div"],
            class_=lambda c: c and any(
                keyword in c.lower()
                for keyword in ["sidebar", "toc", "menu", "nav-list"]
            )
        )

    # Stop if no sidebar or navigation block is found
    if not sidebar:
        raise Exception("Could not find sidebar navigation on this page")


    links = sidebar.find_all("a")


    # Parse the root URL so relative links can be converted to absolute links
    parsed_root = urlparse(url)
    base = f"{parsed_root.scheme}://{parsed_root.netloc}"

    result = []

    links = sidebar.find_all("a")

    # Extract all sidebar links
    for a in links:
        href = a.get("href")


        if not href:
            continue

        # Convert relative links to absolute URLs
        if href.startswith("/"):
            href = base + href

        # Skip links outside the current domain
        if parsed_root.netloc not in href:
            continue

        # Generate a readable title from the last URL path segment
        title = href.split("/")[-1].replace("-", " ").title()

        if not title:
            continue

        result.append({
            "url": href,
            "title": title,
            "lastmod": "unknown"
        })

    if not result:
        return []
    return result


async def crawl_js_sidebar(url: str) -> list[dict]:
    """
    Crawls links from a JavaScript-rendered page using Playwright.

    This is used as a fallback when the documentation navigation is not
    available in the static HTML response.
    """

    # Parse the root URL
    parsed_root = urlparse(url)
    base = f"{parsed_root.scheme}://{parsed_root.netloc}"

    result = []

    # Launch a browser to render JavaScript-driven documentation pages
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # Wait until the page has finished loading network resources
        await page.goto(url, wait_until="networkidle",timeout=15000)

        # Extract all anchor links from the rendered page
        links = await page.eval_on_selector_all(
            "a",
            "els => els.map(e => ({href: e.href, text: e.innerText.trim()}))"
        )

        await browser.close()

    # Process rendered links
    for link in links:
        href = link.get("href", "")
        text = link.get("text", "")

        if not href or not text:
            continue

        # Skip links outside the current documentation domain
        if parsed_root.netloc not in href:
            continue

        # Skip the current page itself
        if href == url:
            continue

        # Prefer visible link text as the title
        title = text.strip().replace("\n", " ")

        # Fallback to URL-based title if text is empty
        if not title:
            title = href.split("/")[-1].replace("-", " ").title()

        result.append({
            "url": href,
            "title": title,
            "lastmod": "unknown"
        })

    # Deduplicate results by URL
    seen = set()
    deduped = []

    for r in result:
        if r["url"] not in seen:
            seen.add(r["url"])
            deduped.append(r)

    return deduped


async def generate_study_plan(pages: list[dict], topic: str) -> StudyPlan:
    """
    Uses the LLM to generate the learning plan,
    but uses Python to safely attach exact source URLs.
    """

    if not pages:
        raise ValueError("Cannot generate study plan from empty pages")

    pages_for_llm = [
        {
            "index": i,
            "title": page.get("title", "")
        }
        for i, page in enumerate(pages)
    ]

    model = ChatGroq(model="llama-3.3-70b-versatile")

    planner_model = model.with_structured_output(PlannedStudyPlan)

    prompt = SystemMessage(f"""
You are a Principal Engineer creating a study plan for {topic}.

You are given documentation pages:
{pages_for_llm}

Create a structured learning plan.

Rules:
- Return modules with page_indexes.
- page_indexes must only use indexes from the input list.
- Do not invent URLs.
- Do not include source_url.
- Group related pages into meaningful modules.
- Priority must be RED, YELLOW, or BLUE.
- RED means core/must learn.
- YELLOW means important/intermediate.
- BLUE means optional/supporting.
""")

    planned = await planner_model.ainvoke([prompt])

    final_modules = []
    used_indexes = set()

    for module in planned.modules:
        topics = []

        for topic_number, page_index in enumerate(module.page_indexes, start=1):
            if page_index < 0 or page_index >= len(pages):
                continue

            page = pages[page_index]
            used_indexes.add(page_index)

            topics.append(
                Topic(
                    topic_number=topic_number,
                    title=page.get("title", ""),
                    source_url=page.get("url", ""),
                    skills_acquired=module.skills_acquired
                )
            )

        if not topics:
            continue

        final_modules.append(
            Module(
                module_number=module.module_number,
                title=module.title,
                estimated_hours=module.estimated_hours,
                priority=module.priority,
                estimated_refined=False,
                disclaimer="Estimate based on documentation page titles only",
                topics=topics
            )
        )

    missing_indexes = [
        i for i in range(len(pages))
        if i not in used_indexes
    ]

    if missing_indexes:
        fallback_topics = []

        for topic_number, page_index in enumerate(missing_indexes, start=1):
            page = pages[page_index]

            fallback_topics.append(
                Topic(
                    topic_number=topic_number,
                    title=page.get("title", ""),
                    source_url=page.get("url", ""),
                    skills_acquired=[topic]
                )
            )

        final_modules.append(
            Module(
                module_number=len(final_modules) + 1,
                title="Additional Documentation",
                estimated_hours=max(1, round(len(fallback_topics) * 0.5)),
                priority="BLUE",
                estimated_refined=False,
                disclaimer="Pages not assigned by LLM planner",
                topics=fallback_topics
            )
        )

    return StudyPlan(
        title=planned.title or topic,
        total_estimated_hours=planned.total_estimated_hours,
        skills_acquired=planned.skills_acquired,
        disclaimer=planned.disclaimer or "Estimates depend on learner speed.",
        modules=final_modules
    )

async def is_url_alive(client: httpx.AsyncClient, url: str) -> bool:
    """
    Checks whether a URL is reachable.

    Some sites block HEAD requests, so we try HEAD first
    and then fall back to GET if needed.
    """
    try:
        response = await client.head(url, follow_redirects=True, timeout=10)

        if response.status_code == 200:
            return True

        # Some documentation sites do not allow HEAD requests
        if response.status_code in [403, 405]:
            response = await client.get(url, follow_redirects=True, timeout=10)
            return response.status_code == 200

        return False

    except httpx.RequestError:
        # Covers DNS errors, connection errors, timeouts, invalid URLs, etc.
        return False
    
    
def is_docs_page(html: str) -> bool:
    soup = BeautifulSoup(html,"html.parser")
    doc_keywords = ["installation", "api reference", "parameters", "usage", "getting started", "module", "function", "class", "returns"]
    marketing_keywords = ["pricing", "enterprise", "sign up", "free trial", "contact sales"]
    
    doc_score = sum(1 for kw in doc_keywords 
        if soup.find(string=re.compile(kw, re.IGNORECASE)))
    marketing_score = sum(1 for kw in marketing_keywords 
        if soup.find(string=re.compile(kw, re.IGNORECASE)))
    return doc_score >= 2 and doc_score > marketing_score