"""Tests for daemon/api/logs.py — generic Zeek/Suricata log search."""

import json
import unittest
from unittest.mock import MagicMock
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

    # ── Stats endpoint tests ──────────────────────────────────────────

    def _mock_stats_response(self, total=1234, unique_src=42, protocols=5, src_bytes=100000, dst_bytes=200000):
        """Helper to create a mock OpenSearch stats aggregation response."""
        return {
            "hits": {"total": {"value": total}, "hits": []},
            "aggregations": {
                "unique_sources": {"value": unique_src},
                "protocol_count": {"value": protocols},
                "src_bytes": {"value": src_bytes},
                "dst_bytes": {"value": dst_bytes},
            },
        }

    async def test_stats_returns_aggregates(self):
        """GET /api/logs/stats returns total_events, unique_sources, protocol_count, total_bytes."""
        self.mock_client.search.return_value = self._mock_stats_response(
            total=5000, unique_src=25, protocols=7, src_bytes=100000, dst_bytes=200000
        )
        resp = await self.client.request("GET", "/api/logs/stats")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total_events"], 5000)
        self.assertEqual(data["unique_sources"], 25)
        self.assertEqual(data["protocol_count"], 7)
        self.assertEqual(data["total_bytes"], 300000)
        self.assertIn("from", data)
        self.assertIn("to", data)

    async def test_stats_with_time_range(self):
        """Stats endpoint respects from/to params."""
        self.mock_client.search.return_value = self._mock_stats_response()
        resp = await self.client.request(
            "GET", "/api/logs/stats?from=2026-03-01T00:00:00Z&to=2026-03-05T00:00:00Z"
        )
        self.assertEqual(resp.status, 200)
        call_body = self.mock_client.search.call_args[1]["body"]
        time_filter = call_body["query"]["bool"]["filter"][0]
        self.assertIn("range", time_filter)
        self.assertEqual(
            time_filter["range"]["@timestamp"]["gte"], "2026-03-01T00:00:00Z"
        )

    async def test_stats_opensearch_error(self):
        """Stats endpoint returns 502 on OpenSearch error."""
        from opensearchpy import OpenSearchException
        self.mock_client.search.side_effect = OpenSearchException("timeout")
        resp = await self.client.request("GET", "/api/logs/stats")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    # ── Timeline endpoint tests ───────────────────────────────────────

    async def test_timeline_returns_buckets(self):
        """GET /api/logs/timeline returns time-series buckets by log type."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 100}, "hits": []},
            "aggregations": {
                "timeline": {
                    "buckets": [
                        {
                            "key_as_string": "2026-03-05T12:00:00Z",
                            "key": 1772928000000,
                            "doc_count": 50,
                            "by_type": {
                                "buckets": [
                                    {"key": "conn", "doc_count": 30},
                                    {"key": "dns", "doc_count": 20},
                                ]
                            },
                        }
                    ]
                }
            },
        }
        resp = await self.client.request("GET", "/api/logs/timeline")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["interval"], "1h")
        self.assertEqual(len(data["buckets"]), 1)
        bucket = data["buckets"][0]
        self.assertEqual(bucket["total"], 50)
        self.assertEqual(bucket["conn"], 30)
        self.assertEqual(bucket["dns"], 20)
        self.assertEqual(bucket["http"], 0)  # missing type defaults to 0

    async def test_timeline_validates_interval(self):
        """Invalid interval falls back to 1h."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []},
            "aggregations": {"timeline": {"buckets": []}},
        }
        resp = await self.client.request("GET", "/api/logs/timeline?interval=99x")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["interval"], "1h")
        # Verify the actual query used 1h
        call_body = self.mock_client.search.call_args[1]["body"]
        self.assertEqual(
            call_body["aggs"]["timeline"]["date_histogram"]["fixed_interval"], "1h"
        )

    # ── Top talkers endpoint tests ────────────────────────────────────

    async def test_top_talkers_returns_ips(self):
        """GET /api/logs/top-talkers returns source IP aggregation."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 500}, "hits": []},
            "aggregations": {
                "top_sources": {
                    "buckets": [
                        {"key": "192.168.1.100", "doc_count": 200},
                        {"key": "192.168.1.101", "doc_count": 150},
                    ]
                }
            },
        }
        resp = await self.client.request("GET", "/api/logs/top-talkers")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["talkers"]), 2)
        self.assertEqual(data["talkers"][0]["ip"], "192.168.1.100")
        self.assertEqual(data["talkers"][0]["count"], 200)

    # ── Protocol breakdown endpoint tests ─────────────────────────────

    async def test_protocol_breakdown_returns_protocols(self):
        """GET /api/logs/protocol-breakdown returns event.dataset aggregation."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 1000}, "hits": []},
            "aggregations": {
                "protocols": {
                    "buckets": [
                        {"key": "conn", "doc_count": 600},
                        {"key": "dns", "doc_count": 300},
                        {"key": "http", "doc_count": 100},
                    ]
                }
            },
        }
        resp = await self.client.request("GET", "/api/logs/protocol-breakdown")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["protocols"]), 3)
        self.assertEqual(data["protocols"][0]["protocol"], "conn")
        self.assertEqual(data["protocols"][0]["label"], "Connections")
        self.assertEqual(data["protocols"][0]["count"], 600)
        self.assertEqual(data["protocols"][1]["label"], "DNS")

    # ── Top destinations endpoint tests ───────────────────────────────

    async def test_top_destinations_returns_ips(self):
        """GET /api/logs/top-destinations returns destination IP aggregation."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 500}, "hits": []},
            "aggregations": {
                "top_destinations": {
                    "buckets": [
                        {"key": "8.8.8.8", "doc_count": 300},
                        {"key": "1.1.1.1", "doc_count": 100},
                    ]
                }
            },
        }
        resp = await self.client.request("GET", "/api/logs/top-destinations")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["destinations"]), 2)
        self.assertEqual(data["destinations"][0]["ip"], "8.8.8.8")
        self.assertEqual(data["destinations"][0]["count"], 300)

    # ── Top DNS endpoint tests ────────────────────────────────────────

    async def test_top_dns_returns_queries(self):
        """GET /api/logs/top-dns returns DNS query aggregation."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 200}, "hits": []},
            "aggregations": {
                "top_queries": {
                    "buckets": [
                        {"key": "google.com", "doc_count": 80},
                        {"key": "facebook.com", "doc_count": 40},
                    ]
                }
            },
        }
        resp = await self.client.request("GET", "/api/logs/top-dns")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["queries"]), 2)
        self.assertEqual(data["queries"][0]["domain"], "google.com")
        self.assertEqual(data["queries"][0]["count"], 80)
        # Verify DNS-specific filters in the query
        call_body = self.mock_client.search.call_args[1]["body"]
        filters = call_body["query"]["bool"]["filter"]
        providers = [f["term"]["event.provider"] for f in filters if "event.provider" in f.get("term", {})]
        datasets = [f["term"]["event.dataset"] for f in filters if "event.dataset" in f.get("term", {})]
        self.assertIn("zeek", providers)
        self.assertIn("dns", datasets)


if __name__ == "__main__":
    unittest.main()
