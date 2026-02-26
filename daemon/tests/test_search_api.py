"""
Tests for daemon/api/search.py

All tests use mocks -- no OpenSearch or external dependencies required.
Tests cover the natural language search API endpoints.
"""

import unittest
from unittest.mock import MagicMock

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.search import register_search_routes
from services.nl_search import NLSearchParser


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    storage = MagicMock()
    storage._client = MagicMock()
    return storage


def _make_search_result(hits=None, total=0):
    """Build a mock OpenSearch search result."""
    if hits is None:
        hits = []
    return {
        "hits": {
            "total": {"value": total},
            "hits": [{"_source": h} for h in hits],
        },
    }


class TestSearchEndpoint(AioHTTPTestCase):
    """Tests for GET /api/search."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.parser = NLSearchParser()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_search_routes(app, self.parser, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_search_empty_query(self):
        """GET /api/search with empty query returns results."""
        self.mock_storage._client.search.return_value = _make_search_result()
        resp = await self.client.request("GET", "/api/search")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("results", data)
        self.assertIn("description", data)
        self.assertIn("total", data)
        self.assertIn("count", data)

    @unittest_run_loop
    async def test_search_with_query(self):
        """GET /api/search?q=connections from 192.168.1.1 returns results."""
        hits = [{"id.orig_h": "192.168.1.1", "proto": "tcp"}]
        self.mock_storage._client.search.return_value = _make_search_result(
            hits=hits, total=1
        )
        resp = await self.client.request(
            "GET", "/api/search?q=connections+from+192.168.1.1"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["count"], 1)
        self.assertIn("192.168.1.1", data["description"])

    @unittest_run_loop
    async def test_search_with_size_param(self):
        """GET /api/search?q=test&size=10 respects size parameter."""
        self.mock_storage._client.search.return_value = _make_search_result()
        resp = await self.client.request("GET", "/api/search?q=test&size=10")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_search_opensearch_error(self):
        """OpenSearch failure returns 502."""
        from opensearchpy import OpenSearchException
        self.mock_storage._client.search.side_effect = OpenSearchException("timeout")
        resp = await self.client.request("GET", "/api/search?q=test")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_search_returns_query_text(self):
        """Response includes the original query text."""
        self.mock_storage._client.search.return_value = _make_search_result()
        resp = await self.client.request("GET", "/api/search?q=high+alerts")
        data = await resp.json()
        self.assertEqual(data["query"], "high alerts")

    @unittest_run_loop
    async def test_search_returns_index(self):
        """Response includes the index that was searched."""
        self.mock_storage._client.search.return_value = _make_search_result()
        resp = await self.client.request("GET", "/api/search?q=test")
        data = await resp.json()
        self.assertIn("index", data)

    @unittest_run_loop
    async def test_search_invalid_size_defaults(self):
        """Invalid size parameter defaults to 50."""
        self.mock_storage._client.search.return_value = _make_search_result()
        resp = await self.client.request("GET", "/api/search?q=test&size=abc")
        self.assertEqual(resp.status, 200)


class TestSearchSuggestEndpoint(AioHTTPTestCase):
    """Tests for GET /api/search/suggest."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.parser = NLSearchParser()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_search_routes(app, self.parser, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_suggest_empty_query(self):
        """GET /api/search/suggest with empty query returns defaults."""
        resp = await self.client.request("GET", "/api/search/suggest")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("suggestions", data)
        self.assertEqual(len(data["suggestions"]), 5)

    @unittest_run_loop
    async def test_suggest_with_partial(self):
        """GET /api/search/suggest?q=alert returns suggestions."""
        resp = await self.client.request("GET", "/api/search/suggest?q=alert")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("suggestions", data)
        self.assertTrue(len(data["suggestions"]) > 0)

    @unittest_run_loop
    async def test_suggest_returns_query(self):
        """Response includes the partial query text."""
        resp = await self.client.request("GET", "/api/search/suggest?q=dns")
        data = await resp.json()
        self.assertEqual(data["query"], "dns")


class TestSearchRouteRegistration(AioHTTPTestCase):
    """Tests for search route registration."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.parser = NLSearchParser()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_search_routes(app, self.parser, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_parser_stored_on_app(self):
        """The NLSearchParser should be stored on the app dict."""
        self.assertIs(self.app["nl_search_parser"], self.parser)

    @unittest_run_loop
    async def test_search_route_exists(self):
        """The /api/search route should be registered."""
        self.mock_storage._client.search.return_value = _make_search_result()
        resp = await self.client.request("GET", "/api/search")
        self.assertNotEqual(resp.status, 404)

    @unittest_run_loop
    async def test_suggest_route_exists(self):
        """The /api/search/suggest route should be registered."""
        resp = await self.client.request("GET", "/api/search/suggest")
        self.assertNotEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
