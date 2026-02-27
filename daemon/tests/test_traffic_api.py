"""
Tests for daemon/api/traffic.py

All tests use mocks -- no OpenSearch connection required.
Tests cover query building, response formatting, error handling, and edge cases.
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.traffic import (
    register_traffic_routes,
    _parse_time_range,
    _parse_int_param,
    _time_range_filter,
    ZEEK_INDEX,
)
from storage.manager import StorageManager, RetentionConfig


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    config = RetentionConfig()
    with patch.object(StorageManager, "_create_client") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client
        storage = StorageManager(config, "http://localhost:9200")
    return storage, mock_client


class TestParseTimeRange(unittest.TestCase):
    """Tests for _parse_time_range helper."""

    def _make_request(self, params: dict) -> MagicMock:
        """Create a mock request with given query params."""
        mock_req = MagicMock()
        mock_req.query = params
        return mock_req

    def test_defaults_to_last_24h(self):
        """When no params given, defaults to a 24h range."""
        req = self._make_request({})
        from_ts, to_ts = _parse_time_range(req)
        # Both should be valid ISO timestamps
        from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        self.assertAlmostEqual(
            (to_dt - from_dt).total_seconds(), 24 * 3600, delta=5
        )

    def test_valid_params_preserved(self):
        """Valid ISO timestamps should be passed through."""
        req = self._make_request({
            "from": "2026-02-25T00:00:00+00:00",
            "to": "2026-02-26T00:00:00+00:00",
        })
        from_ts, to_ts = _parse_time_range(req)
        self.assertEqual(from_ts, "2026-02-25T00:00:00+00:00")
        self.assertEqual(to_ts, "2026-02-26T00:00:00+00:00")

    def test_invalid_from_falls_back_to_default(self):
        """Invalid from param should fall back to default."""
        req = self._make_request({"from": "not-a-date", "to": "2026-02-26T00:00:00+00:00"})
        from_ts, to_ts = _parse_time_range(req)
        self.assertNotEqual(from_ts, "not-a-date")
        self.assertEqual(to_ts, "2026-02-26T00:00:00+00:00")

    def test_invalid_to_falls_back_to_default(self):
        """Invalid to param should fall back to default."""
        req = self._make_request({"from": "2026-02-25T00:00:00+00:00", "to": "garbage"})
        from_ts, to_ts = _parse_time_range(req)
        self.assertEqual(from_ts, "2026-02-25T00:00:00+00:00")
        self.assertNotEqual(to_ts, "garbage")


class TestParseIntParam(unittest.TestCase):
    """Tests for _parse_int_param helper."""

    def test_valid_int(self):
        req = MagicMock()
        req.query = {"limit": "15"}
        self.assertEqual(_parse_int_param(req, "limit", 20), 15)

    def test_missing_returns_default(self):
        req = MagicMock()
        req.query = {}
        self.assertEqual(_parse_int_param(req, "limit", 20), 20)

    def test_invalid_returns_default(self):
        req = MagicMock()
        req.query = {"limit": "abc"}
        self.assertEqual(_parse_int_param(req, "limit", 20), 20)

    def test_zero_returns_one(self):
        """Zero or negative should be clamped to 1."""
        req = MagicMock()
        req.query = {"limit": "0"}
        self.assertEqual(_parse_int_param(req, "limit", 20), 1)


class TestTimeRangeFilter(unittest.TestCase):
    """Tests for _time_range_filter helper."""

    def test_builds_correct_range(self):
        result = _time_range_filter("2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z")
        self.assertEqual(result["range"]["ts"]["gte"], "2026-02-25T00:00:00Z")
        self.assertEqual(result["range"]["ts"]["lte"], "2026-02-26T00:00:00Z")
        self.assertEqual(result["range"]["ts"]["format"], "strict_date_optional_time")


class TestTrafficSummaryHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/summary."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_summary_success(self):
        """Successful summary query returns aggregated data."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 1500}},
            "aggregations": {
                "total_orig_bytes": {"value": 1000000},
                "total_resp_bytes": {"value": 2000000},
                "total_orig_pkts": {"value": 5000},
                "total_resp_pkts": {"value": 8000},
                "top_protocol": {"buckets": [{"key": "tcp", "doc_count": 1200}]},
            },
        }

        resp = await self.client.request("GET", "/api/traffic/summary")
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        self.assertEqual(data["total_bytes"], 3000000)
        self.assertEqual(data["orig_bytes"], 1000000)
        self.assertEqual(data["resp_bytes"], 2000000)
        self.assertEqual(data["packet_count"], 13000)
        self.assertEqual(data["connection_count"], 1500)
        self.assertEqual(data["top_protocol"], "tcp")

        # Verify search was called with ZEEK_INDEX
        self.mock_client.search.assert_called_once()
        call_kwargs = self.mock_client.search.call_args
        self.assertEqual(call_kwargs.kwargs.get("index") or call_kwargs[1].get("index", call_kwargs[0][0] if call_kwargs[0] else None), ZEEK_INDEX)

    @unittest_run_loop
    async def test_summary_with_time_params(self):
        """Time range params are forwarded to the query."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_orig_bytes": {"value": 0},
                "total_resp_bytes": {"value": 0},
                "total_orig_pkts": {"value": 0},
                "total_resp_pkts": {"value": 0},
                "top_protocol": {"buckets": []},
            },
        }

        resp = await self.client.request(
            "GET",
            "/api/traffic/summary?from=2026-02-25T00:00:00Z&to=2026-02-26T00:00:00Z",
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["from"], "2026-02-25T00:00:00Z")
        self.assertEqual(data["to"], "2026-02-26T00:00:00Z")
        self.assertEqual(data["top_protocol"], "unknown")

    @unittest_run_loop
    async def test_summary_opensearch_error(self):
        """OpenSearch connection error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/traffic/summary")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_summary_empty_results(self):
        """Empty results return zero counts."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_orig_bytes": {"value": None},
                "total_resp_bytes": {"value": None},
                "total_orig_pkts": {"value": None},
                "total_resp_pkts": {"value": None},
                "top_protocol": {"buckets": []},
            },
        }

        resp = await self.client.request("GET", "/api/traffic/summary")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total_bytes"], 0)
        self.assertEqual(data["packet_count"], 0)
        self.assertEqual(data["connection_count"], 0)
        self.assertEqual(data["top_protocol"], "unknown")


class TestTopTalkersHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/top-talkers."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_top_talkers_success(self):
        """Successful top talkers query returns IP list."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "top_sources": {
                    "buckets": [
                        {
                            "key": "192.168.1.100",
                            "doc_count": 500,
                            "total_bytes": {"value": 1500000},
                        },
                        {
                            "key": "192.168.1.101",
                            "doc_count": 300,
                            "total_bytes": {"value": 800000},
                        },
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/traffic/top-talkers?limit=5")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["limit"], 5)
        self.assertEqual(len(data["top_talkers"]), 2)
        self.assertEqual(data["top_talkers"][0]["ip"], "192.168.1.100")
        self.assertEqual(data["top_talkers"][0]["total_bytes"], 1500000)

    @unittest_run_loop
    async def test_top_talkers_empty(self):
        """Empty results return empty list."""
        self.mock_client.search.return_value = {
            "aggregations": {"top_sources": {"buckets": []}}
        }

        resp = await self.client.request("GET", "/api/traffic/top-talkers")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["top_talkers"], [])


class TestTopDestinationsHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/top-destinations."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_top_destinations_success(self):
        """Successful top destinations query returns IP list."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "top_destinations": {
                    "buckets": [
                        {
                            "key": "8.8.8.8",
                            "doc_count": 1000,
                            "total_bytes": {"value": 5000000},
                        },
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/traffic/top-destinations?limit=10")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["top_destinations"]), 1)
        self.assertEqual(data["top_destinations"][0]["ip"], "8.8.8.8")


class TestProtocolsHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/protocols."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_protocols_success(self):
        """Returns protocol and service distribution."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "by_proto": {
                    "buckets": [
                        {"key": "tcp", "doc_count": 5000},
                        {"key": "udp", "doc_count": 2000},
                    ]
                },
                "by_service": {
                    "buckets": [
                        {"key": "dns", "doc_count": 1500},
                        {"key": "http", "doc_count": 1000},
                    ]
                },
            }
        }

        resp = await self.client.request("GET", "/api/traffic/protocols")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["protocols"]), 2)
        self.assertEqual(data["protocols"][0]["name"], "tcp")
        self.assertEqual(data["protocols"][0]["count"], 5000)
        self.assertEqual(len(data["services"]), 2)
        self.assertEqual(data["services"][0]["name"], "dns")


class TestBandwidthHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/bandwidth."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_bandwidth_success(self):
        """Returns time-series bandwidth data."""
        self.mock_client.search.return_value = {
            "aggregations": {
                "bandwidth_over_time": {
                    "buckets": [
                        {
                            "key": 1740441600000,
                            "key_as_string": "2026-02-25T00:00:00.000Z",
                            "doc_count": 100,
                            "orig_bytes": {"value": 50000},
                            "resp_bytes": {"value": 80000},
                        },
                        {
                            "key": 1740441900000,
                            "key_as_string": "2026-02-25T00:05:00.000Z",
                            "doc_count": 150,
                            "orig_bytes": {"value": 60000},
                            "resp_bytes": {"value": 90000},
                        },
                    ]
                }
            }
        }

        resp = await self.client.request("GET", "/api/traffic/bandwidth?interval=5m")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["interval"], "5m")
        self.assertEqual(len(data["series"]), 2)
        self.assertEqual(data["series"][0]["total_bytes"], 130000)
        self.assertEqual(data["series"][0]["connections"], 100)

    @unittest_run_loop
    async def test_bandwidth_invalid_interval(self):
        """Invalid interval falls back to 5m."""
        self.mock_client.search.return_value = {
            "aggregations": {"bandwidth_over_time": {"buckets": []}}
        }

        resp = await self.client.request("GET", "/api/traffic/bandwidth?interval=99x")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["interval"], "5m")


class TestConnectionsHandler(AioHTTPTestCase):
    """Tests for GET /api/traffic/connections."""

    def setUp(self):
        self.storage, self.mock_client = _make_mock_storage()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.storage
        register_traffic_routes(app, self.storage)
        return app

    @unittest_run_loop
    async def test_connections_success(self):
        """Returns paginated connection list."""
        self.mock_client.search.return_value = {
            "hits": {
                "total": {"value": 250},
                "hits": [
                    {
                        "_id": "doc1",
                        "_index": "zeek-conn-2026.02.25",
                        "_source": {
                            "ts": "2026-02-25T12:00:00Z",
                            "proto": "tcp",
                            "id.orig_h": "192.168.1.100",
                            "id.resp_h": "8.8.8.8",
                        },
                    },
                ],
            }
        }

        resp = await self.client.request(
            "GET", "/api/traffic/connections?page=1&size=50"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["total"], 250)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["size"], 50)
        self.assertEqual(data["total_pages"], 5)
        self.assertEqual(len(data["connections"]), 1)
        self.assertEqual(data["connections"][0]["_id"], "doc1")
        self.assertEqual(data["connections"][0]["proto"], "tcp")

    @unittest_run_loop
    async def test_connections_with_search(self):
        """Search query is forwarded to OpenSearch query_string."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request(
            "GET", "/api/traffic/connections?q=dns"
        )
        self.assertEqual(resp.status, 200)

        # Verify the query_string was used
        call_args = self.mock_client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        must = body["query"]["bool"]["must"]
        self.assertTrue(any("query_string" in clause for clause in must))

    @unittest_run_loop
    async def test_connections_size_capped(self):
        """Page size is capped at 200."""
        self.mock_client.search.return_value = {
            "hits": {"total": {"value": 0}, "hits": []}
        }

        resp = await self.client.request(
            "GET", "/api/traffic/connections?size=500"
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["size"], 200)

    @unittest_run_loop
    async def test_connections_opensearch_error(self):
        """OpenSearch error returns 502."""
        from opensearchpy import ConnectionError as OSConnectionError

        self.mock_client.search.side_effect = OSConnectionError(
            "N/A", "Connection refused", Exception("refused")
        )

        resp = await self.client.request("GET", "/api/traffic/connections")
        self.assertEqual(resp.status, 502)


if __name__ == "__main__":
    unittest.main()
