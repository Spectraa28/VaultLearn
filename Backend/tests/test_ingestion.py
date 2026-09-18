import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from urllib.robotparser import RobotFileParser

import httpx

from schemas.models import Module, StudyPlan, Topic


def response(url: str, body: str, status: int = 200, content_type: str = "text/html"):
    return httpx.Response(status, text=body, headers={"content-type": content_type},
                          request=httpx.Request("GET", url))


DOC_HTML = "<html><main><h1>Documentation</h1><p>Installation and configuration examples for this API. " + ("This guide explains functions and parameters. " * 8) + "</p><pre>example()</pre></main></html>"


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_classifier_does_not_count_marketing_navigation(self):
        from rag.discovery import is_docs_page
        marketing = "<html><nav>Installation Guide API Reference</nav><main><h1>Pricing</h1><p>Contact sales today.</p></main></html>"
        self.assertFalse(is_docs_page(marketing, "https://vendor.example.com/"))
        self.assertTrue(is_docs_page(DOC_HTML, "https://docs.example.com/"))

    async def test_direct_homepage_follows_documentation_link(self):
        from rag.discovery import resolve_url
        homepage = '<html><main><h1>Product</h1><p>' + \
                   ('Installation examples and configuration functions are easy. ' * 5) + \
                   '</p><pre>example()</pre><a href="https://docs.vendor.dev/">Documentation</a></main></html>'
        async def fetch(_client, url):
            return (url, homepage) if url == "https://vendor.dev" else (url, DOC_HTML)
        with patch("rag.discovery.asyncio.to_thread", new_callable=AsyncMock), patch(
            "rag.discovery._get_html", new_callable=AsyncMock, side_effect=fetch
        ):
            self.assertEqual(await resolve_url("https://vendor.dev"), "https://docs.vendor.dev/")

    def test_brand_match_does_not_confuse_related_products(self):
        from rag.discovery import _brand_matches
        self.assertTrue(_brand_matches("React", "https://react.dev/learn"))
        self.assertFalse(_brand_matches("React", "https://reactrouter.com/home"))
        self.assertTrue(_brand_matches("Django", "https://docs.djangoproject.com/en/6.0/"))
        self.assertTrue(_brand_matches("OpenAI API", "https://platform.openai.com/docs"))
        self.assertTrue(_brand_matches("Google Cloud", "https://cloud.google.com/docs"))
        self.assertTrue(_brand_matches("Python 3 documentation", "https://docs.python.org/3/"))
        self.assertFalse(_brand_matches("React Router", "https://react.dev/learn"))

    async def test_search_verifies_brand_host_instead_of_model_guess(self):
        from rag.discovery import resolve_url
        results = [{"href": "https://unrelated.example.com/react-guide"},
                   {"href": "https://react.dev/learn"}]
        with patch("rag.discovery.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=lambda fn, *args: fn(*args)), patch("rag.discovery._search", return_value=results), patch(
            "rag.discovery._get_html", new_callable=AsyncMock,
            return_value=("https://react.dev/learn", DOC_HTML)
        ) as fetch:
            self.assertEqual(await resolve_url("React"), "https://react.dev/learn")
            self.assertEqual(fetch.await_count, 1)

    async def test_ambiguous_official_hosts_return_choices(self):
        from rag.discovery import DocumentationDiscoveryError, resolve_url
        results = [{"href": "https://example.dev/docs"}, {"href": "https://example.org/docs"}]
        async def fetch(_client, url):
            return url, DOC_HTML
        with patch("rag.discovery.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=lambda fn, *args: fn(*args)), patch("rag.discovery._search", return_value=results), patch(
            "rag.discovery._get_html", new_callable=AsyncMock, side_effect=fetch
        ):
            with self.assertRaises(DocumentationDiscoveryError) as caught:
                await resolve_url("example")
        self.assertEqual(caught.exception.code, "documentation_ambiguous")
        self.assertEqual(len(caught.exception.candidates), 2)

    async def test_homepage_fallback_follows_first_party_docs_link_across_hosts(self):
        from rag.discovery import resolve_url
        homepage = '<html><main><h1>Acme</h1><a href="https://manual.vendorhost.net/guide">Documentation</a></main></html>'

        async def fetch(_client, url):
            if url == "https://acme.dev/":
                return url, homepage
            return url, DOC_HTML

        with patch("rag.discovery.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=lambda fn, *args: fn(*args)), patch(
            "rag.discovery._search", return_value=[{"href": "https://unrelated.example.com/acme-guide"}]
        ), patch("rag.discovery._search_homepage", return_value=[{"href": "https://acme.dev/"}]), patch(
            "rag.discovery._get_html", new_callable=AsyncMock, side_effect=fetch
        ):
            self.assertEqual(await resolve_url("Acme"), "https://manual.vendorhost.net/guide")

    async def test_parent_vendor_product_page_verifies_same_site_docs(self):
        from rag.discovery import resolve_url
        product = '<html><head><title>LangGraph: Agent Orchestration</title></head><main>' \
                  '<h1>Build with LangGraph</h1><a href="https://docs.langchain.com/oss/python/langgraph/overview">Read the docs</a>' \
                  '</main></html>'
        docs_url = "https://docs.langchain.com/oss/python/langgraph/overview"

        async def fetch(_client, url):
            return url, product if url == "https://www.langchain.com/langgraph" else DOC_HTML

        with patch("rag.discovery.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=lambda fn, *args: fn(*args)), patch(
            "rag.discovery._search", return_value=[
                {"href": docs_url},
                {"href": "https://www.langchain.com/langgraph"},
                {"href": "https://unrelated.example.com/langgraph"},
            ]
        ), patch("rag.discovery._search_homepage", return_value=[]), patch(
            "rag.discovery._get_html", new_callable=AsyncMock, side_effect=fetch
        ):
            self.assertEqual(await resolve_url("LangGraph"), docs_url)


class CrawlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_docs_index_relative_links_expand_beyond_one_page(self):
        from rag.crawler import crawl_structure
        root = "https://docs.example.com/3"
        landing = '<html><main><h1>Documentation</h1><a href="tutorial/">Tutorial</a>' \
                  '<a href="library/">Library</a></main></html>'
        tutorial = '<html><main><h1>Tutorial</h1><a href="controlflow.html">Control flow</a></main></html>'

        async def fetch(_client, url):
            if url == root:
                return response(root + "/", landing)
            if url == root + "/tutorial":
                return response(root + "/tutorial/", tutorial)
            return response(url, DOC_HTML)

        with patch("rag.crawler.asyncio.to_thread", new_callable=AsyncMock), patch(
            "rag.crawler._sitemap_urls", new_callable=AsyncMock, return_value=[]
        ), patch("rag.crawler._request", new_callable=AsyncMock, side_effect=fetch):
            pages, report = await crawl_structure(root, with_report=True)
        self.assertEqual([page["url"] for page in pages], [
            root, root + "/tutorial", root + "/library", root + "/tutorial/controlflow.html"
        ])
        self.assertEqual(report["selected_pages"], 4)
        self.assertFalse(report["crawl_limited"])

    async def test_sitemap_index_keeps_only_selected_version(self):
        from rag.crawler import _sitemap_urls
        index = "<sitemapindex><sitemap><loc>https://docs.djangoproject.com/en-sitemap.xml</loc></sitemap></sitemapindex>"
        child = "<urlset><url><loc>https://docs.djangoproject.com/en/5.0/intro/</loc></url>" \
                "<url><loc>https://docs.djangoproject.com/en/6.0/intro/</loc></url></urlset>"
        async def fetch(_client, url):
            if url.endswith("robots.txt"):
                return None
            return response(url, index if url == "https://docs.djangoproject.com/sitemap.xml" else child,
                            content_type="application/xml")
        with patch("rag.crawler._request", new_callable=AsyncMock, side_effect=fetch):
            pages = await _sitemap_urls(None, "https://docs.djangoproject.com/en/6.0/", RobotFileParser())
        self.assertEqual([page["url"] for page in pages], ["https://docs.djangoproject.com/en/6.0/intro"])

    async def test_short_documentation_site_is_not_discarded(self):
        from rag.crawler import crawl_structure
        one_page = [{"url": "https://docs.example.com/guide", "title": "Guide", "lastmod": "unknown"}]
        with patch("rag.crawler.asyncio.to_thread", new_callable=AsyncMock), patch(
            "rag.crawler._sitemap_urls", new_callable=AsyncMock, return_value=one_page
        ), patch("rag.crawler._request", new_callable=AsyncMock,
                 return_value=response("https://docs.example.com/", DOC_HTML)):
            pages = await crawl_structure("https://docs.example.com/")
        self.assertEqual([page["url"] for page in pages], ["https://docs.example.com/", "https://docs.example.com/guide"])

    def test_section_scope_rejects_sibling_versions_and_blog(self):
        from rag.crawler import in_scope
        root = "https://docs.djangoproject.com/en/6.0/"
        self.assertTrue(in_scope("https://docs.djangoproject.com/en/6.0/intro/", root))
        self.assertFalse(in_scope("https://docs.djangoproject.com/en/5.0/intro/", root))
        self.assertFalse(in_scope("https://docs.djangoproject.com/en/6.0/blog/post", root))
        self.assertFalse(in_scope("https://docs.djangoproject.com/en/6.0/genindex.html", root))


class IndexFailureTests(unittest.IsolatedAsyncioTestCase):
    def plan(self, count: int):
        topics = [Topic(topic_number=index + 1, title=f"Page {index + 1}",
                        source_url=f"https://docs.example.com/{index + 1}", skills_acquired=[])
                  for index in range(count)]
        return StudyPlan(title="Example", total_estimated_hours=1, skills_acquired=[], disclaimer="",
                         modules=[Module(module_number=1, title="Basics", estimated_hours=1,
                                         priority="RED", disclaimer="", topics=topics)])

    async def test_low_coverage_fails_before_vector_index_is_created(self):
        from agent.nodes import IndexCoverageError, build_collection_node
        chunk = {"text": "Content", "module_number": 1}
        with patch("agent.nodes.chunk_page", new_callable=AsyncMock,
                   side_effect=[[chunk], [], [], [], []]), patch("agent.nodes.build_collection") as build:
            with self.assertRaises(IndexCoverageError) as caught:
                await build_collection_node({"study_plan": self.plan(5), "collection_name": "test"})
        self.assertIn("1/5", str(caught.exception))
        build.assert_not_called()

    async def test_successful_partial_index_prunes_failed_topics(self):
        from agent.nodes import build_collection_node
        chunks = [[{"text": "One", "module_number": 1}], [], [{"text": "Three", "module_number": 1}]]
        with patch("agent.nodes.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)), patch(
            "agent.nodes.chunk_page", new_callable=AsyncMock, side_effect=chunks), patch(
            "agent.nodes.build_collection", return_value=object()
        ):
            result = await build_collection_node({"study_plan": self.plan(3), "collection_name": "test"})
        self.assertEqual(result["index_report"]["indexed_pages"], 2)
        self.assertEqual(len(result["study_plan"].modules[0].topics), 2)
        self.assertEqual(result["study_plan"].modules[0].topics[1].topic_number, 2)


class ContentFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_html_fetch_removes_navigation_and_avoids_proxy(self):
        from rag.chunker import fetch_page_content
        html = "<html><nav>Pricing Sign up</nav><main><h1>Routing</h1><p>" + \
               ("A route connects a path and a handler with configuration examples. " * 6) + \
               "</p><pre>route('/')</pre></main></html>"
        with patch("rag.chunker.asyncio.to_thread", new_callable=AsyncMock), patch(
            "rag.chunker.safe_request", new_callable=AsyncMock,
            return_value=response("https://docs.example.com/routing", html)
        ) as fetch:
            content = await fetch_page_content("https://docs.example.com/routing")
        self.assertIn("Routing", content)
        self.assertNotIn("Pricing", content)
        self.assertEqual(fetch.await_count, 1)

    async def test_rendering_proxy_is_fallback_and_empty_failures_are_visible(self):
        from rag.chunker import fetch_page_content
        markdown = "# Routing\n\n" + ("A route connects a path and a handler. " * 8)
        with patch("rag.chunker.asyncio.to_thread", new_callable=AsyncMock), patch(
            "rag.chunker.safe_request", new_callable=AsyncMock,
            side_effect=[response("https://docs.example.com/routing", "Missing", 404),
                         response("https://r.jina.ai/https://docs.example.com/routing", markdown,
                                  content_type="text/plain")]
        ) as fetch:
            content = await fetch_page_content("https://docs.example.com/routing")
        self.assertTrue(content.startswith("# Routing"))
        self.assertEqual(fetch.await_count, 2)


if __name__ == "__main__":
    unittest.main()
