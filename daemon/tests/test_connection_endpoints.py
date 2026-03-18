"""
Tests for connection stats/sankey/timeline/related endpoints in daemon/api/traffic.py

All tests use mocks -- no OpenSearch connection required.
"""

import unittest
from unittest.mock import MagicMock, patch

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.traffic import register_traffic_routes, NETWORK_INDEX
from storage.manager import StorageManager, RetentionConfig


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    config = RetentionConfig()
    with patch.object(StorageManager, "_create_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        storage = StorageManager(config, "http://localhost:9200")
    return storage, mock_client


class TestConnectionStats(AioHTTPTestCase):
    """Tests for GET /api/traffic/connections/stats"""

    async def get_application(self):
        self.storage, self.mock_client = _make_mock_storage()
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_stats_success(self):
        """Should return aggregated stats with protocols, sources, destinations."""
        self.mock_client.search.side_effect = [
            # First call: conn stats
            {
                "hits": {"total": {"value": 5000}},
                "aggregations": {
                    "bytes_in": {"value": 1000000},
                    "bytes_out": {"value": 3000000},
                    "protocols": {"buckets": [
                        {"key": "tcp", "doc_count": 3000},
                        {"key": "udp", "doc_count": 1500},
                    ]},
                    "top_sources": {"buckets": [
                        {"key": "192.168.1.10", "doc_count": 200,
                         "total_bytes": {"value": 500000}},
                    ]},
                    "top_destinations": {"buckets": [
                        {"key": "8.8.8.8", "doc_count": 100,
                         "total_bytes": {"value": 300000},
                         "asn": {"buckets": [{"key": "AS15169 Google LLC"}]},
                         "geo": {"buckets": [{"key": "US"}]}},
                    ]},
                },
            },
            # Second call: alert count
            {
                "hits": {"total": {"value": 42}},
            },
        ]

        resp = await self.client.request("GET", "/api/traffic/connections/stats")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["total_sessions"], 5000)
        self.assertEqual(data["bytes_in"], 1000000)
        self.assertEqual(data["bytes_out"], 3000000)
        self.assertEqual(data["alert_sessions"], 42)
        self.assertEqual(len(data["protocols"]), 2)
        self.assertEqual(data["protocols"][0]["name"], "tcp")
        self.assertEqual(len(data["top_sources"]), 1)
        self.assertEqual(data["top_sources"][0]["ip"], "192.168.1.10")
        self.assertEqual(len(data["top_destinations"]), 1)
        self.assertEqual(data["top_destinations"][0]["asn"], "AS15169 Google LLC")
        self.assertEqual(data["top_destinations"][0]["country"], "US")

    @unittest_run_loop
    async def test_stats_empty(self):
        """Should handle empty results gracefully."""
        self.mock_client.search.side_effect = [
            {
                "hits": {"total": {"value": 0}},
                "aggregations": {
                    "bytes_in": {"value": 0},
                    "bytes_out": {"value": 0},
                    "protocols": {"buckets": []},
                    "top_sources": {"buckets": []},
                    "top_destinations": {"buckets": []},
                },
            },
            {"hits": {"total": {"value": 0}}},
        ]

        resp = await self.client.request("GET", "/api/traffic/connections/stats")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total_sessions"], 0)
        self.assertEqual(data["alert_sessions"], 0)

    @unittest_run_loop
    async def test_stats_opensearch_error(self):
        """Should return 502 on OpenSearch error."""
        from opensearchpy import OpenSearchException
        self.mock_client.search.side_effect = OpenSearchException("connection timeout")

        resp = await self.client.request("GET", "/api/traffic/connections/stats")
        self.assertEqual(resp.status, 502)


class TestConnectionSankey(AioHTTPTestCase):
    """Tests for GET /api/traffic/connections/sankey"""

    async def get_application(self):
        self.storage, self.mock_client = _make_mock_storage()
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_sankey_success(self):
        """Should return nodes and links for Sankey visualization."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "by_source": {"buckets": [
                    {
                        "key": "192.168.1.10",
                        "total_bytes": {"value": 500000},
                        "by_proto": {"buckets": [
                            {
                                "key": "tcp",
                                "proto_bytes": {"value": 400000},
                                "by_dest": {"buckets": [
                                    {
                                        "key": "AS15169 Google LLC",
                                        "dest_bytes": {"value": 300000},
                                        "geo": {"buckets": [{"key": "US"}]},
                                    },
                                    {
                                        "key": "AS13335 Cloudflare",
                                        "dest_bytes": {"value": 100000},
                                        "geo": {"buckets": [{"key": "US"}]},
                                    },
                                ]},
                            },
                            {
                                "key": "udp",
                                "proto_bytes": {"value": 100000},
                                "by_dest": {"buckets": [
                                    {
                                        "key": "AS15169 Google LLC",
                                        "dest_bytes": {"value": 100000},
                                        "geo": {"buckets": [{"key": "US"}]},
                                    },
                                ]},
                            },
                        ]},
                    },
                ]},
            },
        }

        resp = await self.client.request("GET", "/api/traffic/connections/sankey")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertIn("nodes", data)
        self.assertIn("links", data)
        self.assertEqual(len(data["nodes"]["sources"]), 1)
        self.assertEqual(data["nodes"]["sources"][0]["id"], "192.168.1.10")
        self.assertEqual(len(data["nodes"]["protocols"]), 2)
        self.assertTrue(len(data["nodes"]["destinations"]) >= 1)
        self.assertTrue(len(data["links"]) >= 3)

    @unittest_run_loop
    async def test_sankey_empty(self):
        """Should handle empty aggregation results."""
        self.mock_client.search.return_value = {
            "aggregations": {"by_source": {"buckets": []}},
        }

        resp = await self.client.request("GET", "/api/traffic/connections/sankey")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["nodes"]["sources"], [])
        self.assertEqual(data["links"], [])

    @unittest_run_loop
    async def test_sankey_link_aggregation(self):
        """Links with same source→target should be aggregated."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "by_source": {"buckets": [
                    {
                        "key": "10.0.0.1",
                        "total_bytes": {"value": 200},
                        "by_proto": {"buckets": [
                            {
                                "key": "tcp",
                                "proto_bytes": {"value": 200},
                                "by_dest": {"buckets": [
                                    {"key": "Unknown", "dest_bytes": {"value": 200}, "geo": {"buckets": []}},
                                ]},
                            },
                        ]},
                    },
                    {
                        "key": "10.0.0.2",
                        "total_bytes": {"value": 100},
                        "by_proto": {"buckets": [
                            {
                                "key": "tcp",
                                "proto_bytes": {"value": 100},
                                "by_dest": {"buckets": [
                                    {"key": "Unknown", "dest_bytes": {"value": 100}, "geo": {"buckets": []}},
                                ]},
                            },
                        ]},
                    },
                ]},
            },
        }

        resp = await self.client.request("GET", "/api/traffic/connections/sankey")
        data = await resp.json()
        # tcp→Unknown should be aggregated into one link
        tcp_to_unknown = [l for l in data["links"] if l["source"] == "tcp" and l["target"] == "Unknown"]
        self.assertEqual(len(tcp_to_unknown), 1)
        self.assertEqual(tcp_to_unknown[0]["value"], 300)


class TestConnectionTimeline(AioHTTPTestCase):
    """Tests for GET /api/traffic/connections/timeline"""

    async def get_application(self):
        self.storage, self.mock_client = _make_mock_storage()
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_timeline_success(self):
        """Should return time buckets with protocol breakdown."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "over_time": {"buckets": [
                    {
                        "key_as_string": "2026-03-17T00:00:00.000Z",
                        "key": 1773984000000,
                        "doc_count": 150,
                        "by_proto": {"buckets": [
                            {"key": "tcp", "doc_count": 100},
                            {"key": "udp", "doc_count": 50},
                        ]},
                    },
                    {
                        "key_as_string": "2026-03-17T01:00:00.000Z",
                        "key": 1773987600000,
                        "doc_count": 200,
                        "by_proto": {"buckets": [
                            {"key": "tcp", "doc_count": 180},
                            {"key": "udp", "doc_count": 20},
                        ]},
                    },
                ]},
            },
        }

        resp = await self.client.request("GET", "/api/traffic/connections/timeline?interval=1h")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["interval"], "1h")
        self.assertEqual(len(data["buckets"]), 2)
        self.assertEqual(data["buckets"][0]["total"], 150)
        self.assertEqual(data["buckets"][0]["protocols"]["tcp"], 100)
        self.assertEqual(data["buckets"][0]["protocols"]["udp"], 50)

    @unittest_run_loop
    async def test_timeline_auto_interval(self):
        """Should auto-pick interval when not specified."""
        self.mock_client.search.return_value = {
            "aggregations": {"over_time": {"buckets": []}},
        }

        resp = await self.client.request("GET", "/api/traffic/connections/timeline")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        # Should have a valid interval
        self.assertIn(data["interval"], {"1m", "5m", "15m", "1h", "6h"})

    @unittest_run_loop
    async def test_timeline_invalid_interval(self):
        """Should fallback to 15m for invalid intervals."""
        self.mock_client.search.return_value = {
            "aggregations": {"over_time": {"buckets": []}},
        }

        resp = await self.client.request("GET", "/api/traffic/connections/timeline?interval=42x")
        data = await resp.json()
        self.assertEqual(data["interval"], "15m")


class TestConnectionRelated(AioHTTPTestCase):
    """Tests for GET /api/traffic/connections/related"""

    async def get_application(self):
        self.storage, self.mock_client = _make_mock_storage()
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_related_success(self):
        """Should return related connections between src-dst pair with summary."""
        self.mock_client.search.return_value = {
            "hits": {"hits": [
                {
                    "_id": "abc123",
                    "_source": {
                        "@timestamp": "2026-03-17T10:00:00Z",
                        "source": {"ip": "192.168.1.10", "bytes": 1000},
                        "destination": {"ip": "8.8.8.8", "bytes": 2000},
                        "network": {"transport": "tcp"},
                    },
                },
                {
                    "_id": "def456",
                    "_source": {
                        "@timestamp": "2026-03-17T11:00:00Z",
                        "source": {"ip": "192.168.1.10", "bytes": 500},
                        "destination": {"ip": "8.8.8.8", "bytes": 1500},
                        "network": {"transport": "udp"},
                    },
                },
            ]},
        }

        resp = await self.client.request(
            "GET",
            "/api/traffic/connections/related?src_ip=192.168.1.10&dst_ip=8.8.8.8"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["total_connections"], 2)
        self.assertEqual(data["total_bytes"], 5000)
        self.assertIn("tcp", data["protocols"])
        self.assertIn("udp", data["protocols"])
        self.assertEqual(data["first_seen"], "2026-03-17T10:00:00Z")
        self.assertEqual(data["last_seen"], "2026-03-17T11:00:00Z")
        self.assertEqual(len(data["connections"]), 2)

    @unittest_run_loop
    async def test_related_missing_params(self):
        """Should return 400 when src_ip or dst_ip missing."""
        resp = await self.client.request(
            "GET", "/api/traffic/connections/related?src_ip=192.168.1.10"
        )
        self.assertEqual(resp.status, 400)

        resp = await self.client.request(
            "GET", "/api/traffic/connections/related?dst_ip=8.8.8.8"
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_related_empty(self):
        """Should handle no matching connections."""
        self.mock_client.search.return_value = {
            "hits": {"hits": []},
        }

        resp = await self.client.request(
            "GET",
            "/api/traffic/connections/related?src_ip=10.0.0.1&dst_ip=10.0.0.2"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total_connections"], 0)
        self.assertEqual(data["total_bytes"], 0)
        self.assertIsNone(data["first_seen"])

    @unittest_run_loop
    async def test_related_opensearch_error(self):
        """Should return 502 on OpenSearch error."""
        from opensearchpy import OpenSearchException
        self.mock_client.search.side_effect = OpenSearchException("timeout")

        resp = await self.client.request(
            "GET",
            "/api/traffic/connections/related?src_ip=10.0.0.1&dst_ip=10.0.0.2"
        )
        self.assertEqual(resp.status, 502)


if __name__ == "__main__":
    unittest.main()
