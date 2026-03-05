"""Tests for daemon/api/logs.py — generic Zeek/Suricata log search."""

import json
import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web
from api.logs import register_log_routes


class TestLogSearchAPI(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        self.mock_storage = MagicMock()
        self.mock_client = MagicMock()
        self.mock_storage._client = self.mock_client
        register_log_routes(app, self.mock_storage)
        return app

    def _mock_search_response(self, hits=None, total=0):
        """Helper to create a mock OpenSearch search response."""
        return {
            "hits": {
                "hits": hits or [],
                "total": {"value": total},
            }
        }

    async def test_search_default_params(self):
        """GET /api/logs/search returns results with default params."""
        self.mock_client.search.return_value = self._mock_search_response()
        resp = await self.client.request("GET", "/api/logs/search")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("hits", data)
        self.assertIn("total", data)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["log_type"], "all")

    async def test_search_by_log_type(self):
        """GET /api/logs/search?log_type=zeek.dns filters correctly."""
        self.mock_client.search.return_value = self._mock_search_response()
        resp = await self.client.request("GET", "/api/logs/search?log_type=zeek.dns")
        self.assertEqual(resp.status, 200)
        call_args = self.mock_client.search.call_args
        call_body = call_args[1]["body"]
        filters = call_body["query"]["bool"]["filter"]
        datasets = [f["term"]["event.dataset"] for f in filters if "event.dataset" in f.get("term", {})]
        self.assertIn("dns", datasets)

    async def test_search_with_query_string(self):
        """GET /api/logs/search?query=google.com uses query_string."""
        self.mock_client.search.return_value = self._mock_search_response()
        resp = await self.client.request("GET", "/api/logs/search?query=google.com")
        self.assertEqual(resp.status, 200)
        call_body = self.mock_client.search.call_args[1]["body"]
        self.assertIn("query_string", json.dumps(call_body))

    async def test_search_pagination(self):
        """GET /api/logs/search?size=10 respects size param."""
        self.mock_client.search.return_value = self._mock_search_response()
        resp = await self.client.request("GET", "/api/logs/search?size=10")
        self.assertEqual(resp.status, 200)
        call_body = self.mock_client.search.call_args[1]["body"]
        self.assertEqual(call_body["size"], 10)

    async def test_search_max_size_capped(self):
        """Size param is capped at 500."""
        self.mock_client.search.return_value = self._mock_search_response()
        resp = await self.client.request("GET", "/api/logs/search?size=9999")
        self.assertEqual(resp.status, 200)
        call_body = self.mock_client.search.call_args[1]["body"]
        self.assertEqual(call_body["size"], 500)

    async def test_search_with_time_range(self):
        """Time range params are passed to OpenSearch."""
        self.mock_client.search.return_value = self._mock_search_response()
        resp = await self.client.request(
            "GET", "/api/logs/search?from=2026-03-01T00:00:00Z&to=2026-03-05T00:00:00Z"
        )
        self.assertEqual(resp.status, 200)
        call_body = self.mock_client.search.call_args[1]["body"]
        time_filter = call_body["query"]["bool"]["filter"][0]
        self.assertIn("range", time_filter)

    async def test_search_with_field_projection(self):
        """Fields param limits returned _source fields."""
        self.mock_client.search.return_value = self._mock_search_response()
        resp = await self.client.request("GET", "/api/logs/search?fields=source.ip,destination.ip")
        self.assertEqual(resp.status, 200)
        call_body = self.mock_client.search.call_args[1]["body"]
        self.assertEqual(call_body["_source"], ["source.ip", "destination.ip"])

    async def test_search_with_cursor(self):
        """search_after param enables cursor pagination."""
        self.mock_client.search.return_value = self._mock_search_response()
        cursor = json.dumps([1709596800000, "abc123"])
        resp = await self.client.request(
            "GET", f"/api/logs/search?search_after={cursor}"
        )
        self.assertEqual(resp.status, 200)
        call_body = self.mock_client.search.call_args[1]["body"]
        self.assertEqual(call_body["search_after"], [1709596800000, "abc123"])

    async def test_search_returns_documents(self):
        """Search results include _id and _index from hits."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "doc1",
                        "_index": "arkime_sessions3-260305",
                        "_source": {"source.ip": "192.168.1.1"},
                        "sort": [1709596800000, "doc1"],
                    }
                ],
                "total": {"value": 1},
            }
        }
        resp = await self.client.request("GET", "/api/logs/search")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["hits"]), 1)
        self.assertEqual(data["hits"][0]["_id"], "doc1")
        self.assertEqual(data["hits"][0]["_source"]["source.ip"], "192.168.1.1")
        self.assertEqual(data["hits"][0]["_index"], "arkime_sessions3-260305")
        self.assertIsNotNone(data["search_after"])

    async def test_fields_endpoint(self):
        """GET /api/logs/fields/zeek.conn returns field list."""
        resp = await self.client.request("GET", "/api/logs/fields/zeek.conn")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("fields", data)
        field_names = [f["name"] for f in data["fields"]]
        self.assertIn("source.ip", field_names)
        self.assertIn("destination.ip", field_names)

    async def test_fields_all_log_types(self):
        """All 8 log types have field definitions."""
        for log_type in ["zeek.conn", "zeek.dns", "zeek.http", "zeek.tls",
                         "zeek.files", "zeek.dhcp", "zeek.smtp", "suricata"]:
            resp = await self.client.request("GET", f"/api/logs/fields/{log_type}")
            self.assertEqual(resp.status, 200, f"Failed for {log_type}")
            data = await resp.json()
            self.assertGreater(len(data["fields"]), 0, f"No fields for {log_type}")

    async def test_fields_unknown_type(self):
        """Unknown log type returns 400 with available types."""
        resp = await self.client.request("GET", "/api/logs/fields/unknown.type")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("available", data)

    async def test_search_opensearch_error(self):
        """OpenSearch exception returns 500."""
        from opensearchpy import OpenSearchException
        self.mock_client.search.side_effect = OpenSearchException("connection refused")
        resp = await self.client.request("GET", "/api/logs/search")
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
