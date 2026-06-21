"""
Fetcher layer

This layer's responsibility is to fetch the URL from the given input
and parse the HTML to extract data from it.
"""

import httpx
import json
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from schemas.models import UrlResponse
from urllib.parse import urlparse
from pathlib import Path
from schemas.models import StudyPlan, Topic, Module
from langchain.messages import SystemMessage
import requests
from playwright.async_api import async_playwright


# Load environment variables from the .env file
load_dotenv()


async def resolve_url(input: str) -> str:
    """
    Resolves the official documentation URL for a given technology or topic.

    Steps:
    1. Ask the LLM to provide the documentation URL.
    2. Check whether the returned URL is valid using an HTTP HEAD request.
    3. If the URL is invalid, fall back to DuckDuckGo search.
    4. Prefer links that look like official documentation pages.
    """

    # Initialize the LLM model
    model = ChatGroq(model="qwen/qwen3-32b")

    # Configure the model to return structured output matching UrlResponse
    url_model = model.with_structured_output(UrlResponse)

    # Ask the model to provide a documentation link for the given input
    response = await url_model.ainvoke(
        f"Provide the documentation link for the {input}"
    )

    url = response.url

    # Normalize the technology name for easier URL matching
    tech_name = input.lower().replace(" ", "")

    async with httpx.AsyncClient() as client:
        # First, check if the LLM-provided URL is reachable
        response_url = await client.head(url, follow_redirects=True)

        if response_url.status_code == 200:
            return url

        else:
            # If the LLM URL is invalid, search DuckDuckGo for official docs
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

                # Prefer documentation-like URLs containing docs or github.io
                for r in result:
                    href = r["href"]

                    if any(keyword in href for keyword in ["docs", "github.io"]):
                        if tech_name in href.lower():
                            doc_url = href
                            break

                # If no strongly matching docs URL is found, use the first result
                if not doc_url:
                    doc_url = result[0]["href"]

                url = doc_url

                # Validate the fallback URL
                response_url = await client.head(url, follow_redirects=True)

                print(f"DDGS URL status: {response_url.status_code}")  # debug

                if response_url.status_code == 200:
                    return url

                else:
                    raise Exception(
                        "Please check if there exist docs for this tech"
                    )


async def crawl_structure(site_to_crawl: str) -> str:
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
    path = Path(parsed.path)
    parent = str(path.parent).rstrip("/")
    prefix = f"{parsed.scheme}://{parsed.netloc}{parent}/"

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

    # Check if all URLs are index-like pages ending with "/"
    all_indexes = all(p["url"].endswith("/") for p in result)

    # Fallback to static sidebar crawling if sitemap data is not useful
    if response.status_code != 200 or len(result) < 5 or all_indexes:
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

    print(f"Crawling sidebar for: {url}")

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

    print(f"Sidebar found: {sidebar.name}, class: {sidebar.get('class')}")

    links = sidebar.find_all("a")

    print(f"Total links in sidebar: {len(links)}")

    # Parse the root URL so relative links can be converted to absolute links
    parsed_root = urlparse(url)
    base = f"{parsed_root.scheme}://{parsed_root.netloc}"

    result = []

    links = sidebar.find_all("a")

    # Extract all sidebar links
    for a in links:
        href = a.get("href")

        print(f"Raw href: {href}")  # add this

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
        await page.goto(url, wait_until="networkidle")

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
    Generates a structured study plan from documentation pages.

    The LLM receives page titles and URLs, then returns a JSON object
    matching the StudyPlan schema.
    """

    # Keep only the fields needed by the LLM
    pages_new = [
        {
            "title": p["title"],
            "url": p["url"]
        }
        for p in pages
    ]

    # Initialize the LLM model for study plan generation
    model = ChatGroq(model="llama-3.3-70b-versatile")

    # System prompt instructing the model to return strict JSON
    sys_message = SystemMessage(f"""You are a Principal engineer creating a study plan.

Given these documentation pages for {topic}:
{pages_new}

Return ONLY a JSON object with EXACTLY this structure, no backticks, no explanation:
{{
  "title": "{topic}",
  "total_estimated_hours": <number>,
  "skills_acquired": ["skill1", "skill2"],
  "disclaimer": "Estimates based on page titles only",
  "modules": [
    {{
      "module_number": 1,
      "title": "Module Title",
      "estimated_hours": <number>,
      "priority": "RED",
      "estimates_refined": false,
      "disclaimer": "Estimate based on title only",
      "topics": [
        {{
          "topic_number": 1,
          "title": "Topic Title",
          "source_url": "exact url from input",
          "skills_acquired": ["skill1"]
        }}
      ]
    }}
  ]
}}

Priority must be RED, YELLOW, or BLUE. Include ALL pages from input.""")

    # Invoke the model
    response = await model.ainvoke([sys_message])

    # Extract raw text response
    content = response.content.strip()

    # Strip markdown backticks if present
    if content.startswith("```"):
        content = content.split("```")[1]

        if content.startswith("json"):
            content = content[4:]

    content = content.strip()

    # Parse the JSON and validate it against the StudyPlan schema
    try:
        data = json.loads(content)
        return StudyPlan(**data)

    except json.JSONDecodeError as e:
        raise Exception(f"LLM returned invalid JSON: {e}\nResponse: {content}")
