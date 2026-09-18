"""Bounded, section-scoped documentation discovery."""

import asyncio
import re
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from observability import event
from rag.discovery import normalize_url
from rag.security import safe_request, validate_public_url


MAX_PAGES = 30
MAX_SITEMAPS = 8
SKIP_SEGMENTS = {"blog", "news", "pricing", "login", "signup", "careers", "community", "changelog"}


class DocumentationCrawlError(ValueError):
    code = "documentation_crawl_failed"


def in_scope(candidate: str, root: str) -> bool:
    candidate_url, root_url = urlparse(candidate), urlparse(root)
    if candidate_url.scheme not in {"http", "https"} or candidate_url.hostname != root_url.hostname:
        return False
    root_path = root_url.path.rstrip("/") or "/"
    path = candidate_url.path.rstrip("/") or "/"
    if root_path != "/" and path != root_path and not path.startswith(root_path + "/"):
        return False
    if SKIP_SEGMENTS.intersection(part.lower() for part in path.split("/")):
        return False
    filename = path.rsplit("/", 1)[-1].lower()
    if filename in {"search.html", "py-modindex.html"} or filename.startswith("genindex"):
        return False
    return True


def _page(url: str, title: str = "", lastmod: str = "unknown") -> dict:
    parsed = urlparse(url)
    label = title.strip() or unquote(parsed.path.rstrip("/").split("/")[-1]).replace("-", " ").replace("_", " ").title()
    return {"url": normalize_url(url), "title": label or "Overview", "lastmod": lastmod}


async def _request(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        response = await safe_request(client, "GET", url, timeout=12)
        if response.status_code == 200 and len(response.content) <= 5_000_000:
            return response
    except (httpx.HTTPError, ValueError) as exc:
        event("crawl.fetch_failed", details={"url": url, "error_type": type(exc).__name__})
    return None


async def _sitemap_urls(client: httpx.AsyncClient, root: str, robots: RobotFileParser) -> list[dict]:
    parsed = urlparse(root)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    roots = [f"{origin}/sitemap.xml"]
    robots_response = await _request(client, f"{origin}/robots.txt")
    if robots_response:
        robots.parse(robots_response.text.splitlines())
        roots = [line.split(":", 1)[1].strip() for line in robots_response.text.splitlines()
                 if line.lower().startswith("sitemap:")] + roots
    else:
        robots.parse([])
    queue = list(dict.fromkeys(roots))
    visited = set()
    pages = []
    while queue and len(visited) < MAX_SITEMAPS and len(pages) < 500:
        sitemap = queue.pop(0)
        if sitemap in visited:
            continue
        visited.add(sitemap)
        if urlparse(sitemap).hostname != parsed.hostname:
            continue
        response = await _request(client, sitemap)
        if not response:
            continue
        soup = BeautifulSoup(response.content, "xml")
        if soup.find("sitemapindex"):
            children = [tag.get_text(strip=True) for tag in soup.select("sitemap > loc")]
            scope = parsed.path.strip("/").lower()
            children.sort(key=lambda item: (scope not in item.lower(), item))
            queue.extend(children[:MAX_SITEMAPS])
            continue
        for item in soup.find_all("url"):
            loc = item.find("loc")
            if not loc or not loc.text:
                continue
            url = normalize_url(loc.text)
            if in_scope(url, root) and robots.can_fetch("VaultLearnBot", url):
                lastmod = item.find("lastmod")
                pages.append(_page(url, lastmod=lastmod.text if lastmod else "unknown"))
    event("crawl.sitemaps", details={"sitemaps_checked": len(visited), "pages_found": len(pages)})
    return pages


def _navigation_pages(html: str, url: str, robots: RobotFileParser, scope_root: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select("aside, nav, [role=navigation], [class*=sidebar], [class*=toc]")
    ranked = []
    for container in containers:
        links = []
        for anchor in container.find_all("a", href=True):
            target = normalize_url(urljoin(url, anchor["href"]))
            if in_scope(target, scope_root or url) and robots.can_fetch("VaultLearnBot", target):
                links.append(_page(target, anchor.get_text(" ", strip=True)))
        ranked.append(links)
    return max(ranked, key=len, default=[])


def _content_pages(html: str, url: str, robots: RobotFileParser, scope_root: str) -> list[dict]:
    """Follow documentation-index links, which often sit outside sidebars."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("main, article, [role=main], .document, .body") or soup.body or soup
    pages = []
    for anchor in content.find_all("a", href=True):
        target = normalize_url(urljoin(url, anchor["href"]))
        if in_scope(target, scope_root) and robots.can_fetch("VaultLearnBot", target):
            path = urlparse(target).path.lower()
            if not path.endswith((".pdf", ".zip", ".xml", ".json", ".js", ".css")):
                pages.append(_page(target, anchor.get_text(" ", strip=True)))
    return pages


async def crawl_sidebar(url: str) -> list[dict]:
    robots = RobotFileParser()
    robots.parse([])
    async with httpx.AsyncClient() as client:
        response = await _request(client, url)
    return _navigation_pages(response.text, str(response.url), robots, url) if response else []


async def crawl_js_sidebar(url: str) -> list[dict]:
    await asyncio.to_thread(validate_public_url, url)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()

            async def guard(route):
                target = route.request.url
                if urlparse(target).scheme in {"http", "https"}:
                    try:
                        await asyncio.to_thread(validate_public_url, target)
                    except ValueError:
                        await route.abort()
                        return
                await route.continue_()

            await page.route("**/*", guard)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            html = await page.content()
        finally:
            await browser.close()
    robots = RobotFileParser()
    robots.parse([])
    return _navigation_pages(html, page.url, robots, url)


async def crawl_structure(site_to_crawl: str, *, with_report: bool = False) -> list[dict] | tuple[list[dict], dict]:
    root = normalize_url(site_to_crawl)
    await asyncio.to_thread(validate_public_url, root)
    robots = RobotFileParser()
    robots.parse([])
    async with httpx.AsyncClient() as client:
        sitemap_pages = await _sitemap_urls(client, root, robots)
        landing = await _request(client, root)
    if not landing:
        raise DocumentationCrawlError("Documentation homepage could not be fetched.")
    if not robots.can_fetch("VaultLearnBot", root):
        raise DocumentationCrawlError("The documentation site disallows crawling this section in robots.txt.")
    landing_url = str(landing.url)
    nav_pages = _navigation_pages(landing.text, landing_url, robots, root)
    content_pages = _content_pages(landing.text, landing_url, robots, root)
    if not nav_pages and not content_pages and not sitemap_pages:
        try:
            nav_pages = await crawl_js_sidebar(root)
        except Exception as exc:
            event("crawl.browser_failed", details={"error_type": type(exc).__name__})
    # Breadth-first discovery reaches pages beneath a documentation index.
    # Curated navigation leads, main-content links fill gaps, and sitemap
    # pages supplement both. Never broaden beyond the chosen URL path.
    sitemap_pages.sort(key=lambda page: (urlparse(page["url"]).path.count("/"), page["url"]))
    pages = [_page(root, "Overview")]
    seen = {pages[0]["url"]}
    queue = [*nav_pages, *content_pages, *sitemap_pages]
    queued = {page["url"] for page in queue}
    async with httpx.AsyncClient() as client:
        while queue and len(pages) < MAX_PAGES:
            page = queue.pop(0)
            if page["url"] in seen or not in_scope(page["url"], root):
                continue
            seen.add(page["url"])
            pages.append(page)
            # Only fetched HTML contributes further links; indexing handles
            # unavailable pages and reports them as skipped later.
            response = await _request(client, page["url"])
            if not response or "html" not in response.headers.get("content-type", "").lower():
                continue
            base = str(response.url)
            discovered = [*_navigation_pages(response.text, base, robots, root),
                          *_content_pages(response.text, base, robots, root)]
            for child in discovered:
                if child["url"] not in seen and child["url"] not in queued and len(queued) < 500:
                    queue.append(child)
                    queued.add(child["url"])
    if not pages:
        raise DocumentationCrawlError("No crawlable documentation pages were found in the selected section.")
    report = {"discovered_pages": len(queued | seen), "selected_pages": len(pages),
              "crawl_limited": any(page["url"] not in seen for page in queue),
              "page_limit": MAX_PAGES}
    event("crawl.completed", details={"root": root, **report,
                                       "navigation_pages": len(nav_pages), "content_pages": len(content_pages),
                                       "sitemap_pages": len(sitemap_pages)})
    return (pages, report) if with_report else pages
