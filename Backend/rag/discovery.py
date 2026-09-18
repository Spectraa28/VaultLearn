"""Evidence-based documentation URL discovery.

Search provides candidates; fetched pages and first-party documentation links
provide evidence. A model is deliberately not asked to invent a URL.
"""

import asyncio
import re
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

from observability import event
from rag.security import safe_request, validate_public_url


class DocumentationDiscoveryError(ValueError):
    def __init__(self, message: str, *, candidates: list[str] | None = None):
        super().__init__(message)
        self.candidates = candidates or []
        self.code = "documentation_ambiguous" if candidates else "documentation_not_found"


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def _identity_words(topic: str) -> list[str]:
    # Search phrases often include a generic qualifier that is not part of
    # the vendor's domain ("OpenAI API", "Python 3 documentation"). Do not
    # discard product words such as "Router": React and React Router differ.
    words = re.findall(r"[a-z0-9]+", topic.lower())
    while len(words) > 1 and words[-1] in {
        "official", "docs", "documentation", "guide", "guides", "reference", "api", "sdk"
    }:
        words.pop()
    while len(words) > 1 and words[-1].isdigit():
        words.pop()
    return words


def _brand_matches(topic: str, url: str) -> bool:
    words = _identity_words(topic)
    brand = "".join(words)
    labels = [re.sub(r"[^a-z0-9]", "", label) for label in (urlparse(url).hostname or "").lower().split(".")]
    if len(brand) < 3:
        return False
    if any(label in {brand, brand + "project", brand + "lang"} for label in labels):
        return True
    # Some first-party domains reverse the words: cloud.google.com.
    return len(words) > 1 and all(len(word) >= 3 and word in labels for word in words)


def _path_matches(topic: str, url: str) -> bool:
    brand = "".join(_identity_words(topic))
    return len(brand) >= 3 and any(
        re.sub(r"[^a-z0-9]", "", segment.lower()) == brand
        for segment in urlparse(url).path.split("/")
    )


def _same_site(first: str, second: str) -> bool:
    left = (urlparse(first).hostname or "").removeprefix("www.")
    right = (urlparse(second).hostname or "").removeprefix("www.")
    return bool(left and right) and (left == right or left.endswith("." + right) or right.endswith("." + left))


def _product_title_matches(topic: str, html: str) -> bool:
    title = BeautifulSoup(html, "html.parser").title
    product = " ".join(_identity_words(topic))
    return bool(title and product and title.get_text(" ", strip=True).lower().startswith(product))


def _is_product_homepage(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path in {"", "/"} and not (parsed.hostname or "").startswith(("docs.", "doc.", "developer."))


def documentation_score(html: str, url: str) -> int:
    """Score page structure and content, excluding navigation/marketing chrome."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("nav, header, footer, aside, script, style, noscript"):
        tag.decompose()
    main = soup.select_one("main, article, [role=main]") or soup.body or soup
    body = main.get_text(" ", strip=True).lower()
    heading = " ".join(tag.get_text(" ", strip=True).lower() for tag in main.select("h1, h2")[:5])
    parsed = urlparse(url)
    path = parsed.path.lower()
    host = (parsed.hostname or "").lower()
    score = 0
    if host.startswith(("docs.", "doc.", "developer.")):
        score += 3
    if re.search(r"/(docs?|documentation|manual|guide|guides|learn|reference|tutorial)(/|$)", path):
        score += 3
    if re.search(r"\b(documentation|api reference|user guide|developer guide|tutorial)\b", heading):
        score += 2
    if main.select_one("pre, code"):
        score += 1
    technical = ("installation", "configuration", "syntax", "parameters", "function", "example", "quickstart", "getting started")
    if sum(word in body for word in technical) >= 2:
        score += 1
    if len(body) >= 100 and main.name in {"main", "article"}:
        score += 1
    if re.search(r"\b(pricing|book a demo|contact sales|enterprise sales)\b", heading):
        score -= 3
    return score


def is_docs_page(html: str, url: str = "") -> bool:
    return documentation_score(html, url) >= 3


async def _get_html(client: httpx.AsyncClient, url: str) -> tuple[str, str] | None:
    try:
        response = await safe_request(client, "GET", url, timeout=12)
        content_type = response.headers.get("content-type", "text/html")
        if response.status_code != 200 or "html" not in content_type.lower():
            return None
        if len(response.content) > 5_000_000:
            return None
        return str(response.url), response.text
    except (httpx.HTTPError, ValueError):
        return None


def _link_candidates(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    ranked = []
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True).lower()
        target = urljoin(base_url, anchor["href"])
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"}:
            continue
        label = f"{text} {parsed.path.lower()} {parsed.hostname or ''}"
        if re.search(r"\b(pricing|blog|login|sign in|contact|careers)\b", label):
            continue
        score = 0
        if re.search(r"\b(docs?|documentation|developer|guide|learn|manual|reference|tutorial)\b", text):
            score += 3
        if re.search(r"/(docs?|documentation|manual|guide|learn|reference|tutorial)(/|$)", parsed.path.lower()):
            score += 2
        if (parsed.hostname or "").startswith(("docs.", "doc.")):
            score += 2
        if score:
            ranked.append((score, normalize_url(target)))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return list(dict.fromkeys(url for _, url in ranked))[:5]


async def find_docs_link(client: httpx.AsyncClient, base_url: str, html: str) -> str | None:
    """Follow an explicit docs link from a fetched first-party page."""
    for candidate in _link_candidates(html, base_url):
        fetched = await _get_html(client, candidate)
        if fetched and is_docs_page(fetched[1], fetched[0]):
            return normalize_url(fetched[0])
    return None


def _search(topic: str) -> list[dict]:
    with DDGS() as search:
        return list(search.text(f"{topic} official documentation", max_results=8) or [])


def _search_homepage(topic: str) -> list[dict]:
    with DDGS() as search:
        return list(search.text(f"{topic} official website", max_results=6) or [])


async def resolve_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise DocumentationDiscoveryError("Enter a product name or a public documentation URL.")
    if re.fullmatch(r"[\w.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?", value):
        value = f"https://{value}"
    async with httpx.AsyncClient() as client:
        if value.startswith(("https://", "http://")):
            await asyncio.to_thread(validate_public_url, value)
            fetched = await _get_html(client, value)
            if not fetched:
                raise DocumentationDiscoveryError("The supplied URL did not return a public HTML page. Try its documentation homepage.")
            final_url, html = fetched
            linked = await find_docs_link(client, final_url, html) if _is_product_homepage(final_url) else None
            if linked:
                resolved = linked
            elif is_docs_page(html, final_url):
                resolved = normalize_url(final_url)
            else:
                resolved = await find_docs_link(client, final_url, html)
            if not resolved:
                raise DocumentationDiscoveryError("This page does not look like documentation and has no verifiable docs link. Paste the documentation URL directly.")
            event("documentation.resolved", details={"source": "user_url", "resolved_url": resolved})
            return resolved

        try:
            results = await asyncio.wait_for(asyncio.to_thread(_search, value), timeout=20)
        except (Exception, asyncio.TimeoutError) as exc:
            raise DocumentationDiscoveryError("Documentation search failed. Paste the official documentation URL directly.") from exc

        semaphore = asyncio.Semaphore(3)

        async def verify(rank: int, url: str):
            async with semaphore:
                fetched = await _get_html(client, url)
                if not fetched:
                    return None
                final_url, html = fetched
                if _is_product_homepage(final_url):
                    linked = await find_docs_link(client, final_url, html)
                    if linked:
                        return (5, rank, linked)
                if is_docs_page(html, final_url):
                    return (documentation_score(html, final_url) + 2, rank, normalize_url(final_url))
                linked = await find_docs_link(client, final_url, html)
                if linked:
                    return (5, rank, linked)
                return None

        async def verify_results(search_results: list[dict]) -> list[tuple[int, int, str]]:
            candidates = []
            seen = set()
            for rank, result in enumerate(search_results):
                url = result.get("href") or result.get("url")
                if not url or urlparse(url).scheme not in {"http", "https"} or not _brand_matches(value, url):
                    continue
                url = normalize_url(url)
                if url not in seen:
                    seen.add(url)
                    candidates.append((rank, url))
            return [item for item in await asyncio.gather(*(verify(rank, url) for rank, url in candidates[:6])) if item]

        async def verify_product_page(rank: int, url: str):
            async with semaphore:
                fetched = await _get_html(client, url)
                if not fetched:
                    return None
                final_url, html = fetched
                if not _path_matches(value, final_url) or not _product_title_matches(value, html):
                    return None
                if is_docs_page(html, final_url):
                    return None
                # A parent vendor's product page is useful evidence only when
                # it links to docs on that same site, not to a random tutorial.
                links = [link for link in _link_candidates(html, final_url) if _same_site(final_url, link)]
                links.sort(key=lambda link: not _path_matches(value, link))
                for link in links:
                    docs = await _get_html(client, link)
                    if docs and _same_site(final_url, docs[0]) and is_docs_page(docs[1], docs[0]):
                        return (5, rank, normalize_url(docs[0]))
                return None

        verified = await verify_results(results)
        if not verified:
            # A docs-focused search may omit the product homepage even when it
            # links to docs on a different host. Try one bounded identity search.
            try:
                homepage_results = await asyncio.wait_for(
                    asyncio.to_thread(_search_homepage, value), timeout=20
                )
            except (Exception, asyncio.TimeoutError):
                homepage_results = []
            verified = await verify_results(homepage_results)
            if not verified:
                product_pages = []
                seen = set()
                for rank, result in enumerate([*results, *homepage_results]):
                    url = result.get("href") or result.get("url")
                    if url and urlparse(url).scheme in {"http", "https"} and _path_matches(value, url):
                        url = normalize_url(url)
                        if url not in seen:
                            seen.add(url)
                            product_pages.append((rank, url))
                verified = [item for item in await asyncio.gather(
                    *(verify_product_page(rank, url) for rank, url in product_pages[:4])
                ) if item]
        verified.sort(key=lambda item: (-item[0], item[1]))
        event("documentation.candidates", details={"searched": len(results), "verified": len(verified)})
        if not verified:
            raise DocumentationDiscoveryError("Could not verify an official documentation page. Paste its URL directly.")
        if len(verified) > 1 and verified[0][0] - verified[1][0] <= 1:
            first, second = verified[0][2], verified[1][2]
            if urlparse(first).hostname != urlparse(second).hostname:
                raise DocumentationDiscoveryError("Multiple plausible documentation sites were found. Choose one and paste its URL.", candidates=[first, second])
        resolved = verified[0][2]
        event("documentation.resolved", details={"source": "search_verified", "resolved_url": resolved})
        return resolved
