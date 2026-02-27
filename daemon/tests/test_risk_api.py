"""
Tests for daemon/api/risk.py

All tests use mocks -- no OpenSearch or external dependencies required.
Tests cover the risk scoring API endpoints using AioHTTPTestCase.
"""

import unittest
from unittest.mock import MagicMock

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.risk import register_risk_routes
from services.risk_scoring import RiskScorer


def _make_mock_storage():
    """Create a mock StorageManager with a mock OpenSearch client."""
    storage = MagicMock()
    storage._client = MagicMock()
    return storage


def _make_conn_search_result(buckets=None, total=0):
    """Build a mock OpenSearch connection search result."""
    if buckets is None:
        buckets = []
    return {
        "hits": {"total": {"value": total}},
        "aggregations": {
            "devices": {"buckets": buckets},
            "conn_stats": {"count": len(buckets), "avg": 100.0, "std_deviation": 50.0},
        },
    }


def _make_device_bucket(ip, doc_count=100, orig_bytes=1000, resp_bytes=9000, ports=None):
    """Build a device aggregation bucket for mock data."""
    port_buckets = [{"key": p} for p in (ports or [80, 443])]
    return {
        "key": ip,
        "doc_count": doc_count,
        "total_orig_bytes": {"value": orig_bytes},
        "total_resp_bytes": {"value": resp_bytes},
        "ports_used": {"buckets": port_buckets},
        "external_conns": {"doc_count": int(doc_count * 0.3)},
    }


def _make_alert_search_result(ip_counts=None):
    """Build a mock Suricata alert search result."""
    buckets = []
    if ip_counts:
        for ip, count in ip_counts.items():
            buckets.append({"key": ip, "doc_count": count})
    return {
        "hits": {"total": {"value": sum(c for c in (ip_counts or {}).values())}},
        "aggregations": {"by_ip": {"buckets": buckets}},
    }


def _make_single_conn_result(total=100, orig_bytes=1000, resp_bytes=9000, ports=None):
    """Build a mock OpenSearch result for a single-device query."""
    port_buckets = [{"key": p} for p in (ports or [80, 443])]
    return {
        "hits": {"total": {"value": total}},
        "aggregations": {
            "total_orig_bytes": {"value": orig_bytes},
            "total_resp_bytes": {"value": resp_bytes},
            "ports_used": {"buckets": port_buckets},
            "external_conns": {"doc_count": 30},
        },
    }


def _make_network_stats_result(buckets=None):
    """Build a mock network stats aggregation result."""
    if buckets is None:
        buckets = [
            {"key": "192.168.1.1", "doc_count": 100},
            {"key": "192.168.1.2", "doc_count": 200},
        ]
    return {
        "hits": {"total": {"value": 300}},
        "aggregations": {"devices": {"buckets": buckets}},
    }


def _make_single_alert_result(total=0):
    """Build a mock single-device alert count result."""
    return {
        "hits": {"total": {"value": total}},
    }


class TestRiskScoresEndpoint(AioHTTPTestCase):
    """Tests for GET /api/risk/scores."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.risk_scorer = RiskScorer()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, self.risk_scorer, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_scores_empty_result(self):
        """GET /api/risk/scores with no data returns empty device list."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["device_count"], 0)
        self.assertEqual(data["devices"], [])

    @unittest_run_loop
    async def test_scores_with_devices(self):
        """GET /api/risk/scores returns scored devices."""
        buckets = [
            _make_device_bucket("192.168.1.10", doc_count=100),
            _make_device_bucket("192.168.1.20", doc_count=200),
        ]
        conn_result = _make_conn_search_result(buckets=buckets, total=300)
        alert_result = _make_alert_search_result({"192.168.1.10": 5})

        self.mock_storage._client.search.side_effect = [conn_result, alert_result]

        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["device_count"], 2)
        self.assertIsInstance(data["devices"], list)
        # Devices should be sorted by score descending
        if len(data["devices"]) >= 2:
            self.assertGreaterEqual(
                data["devices"][0]["score"], data["devices"][1]["score"]
            )

    @unittest_run_loop
    async def test_scores_contain_required_fields(self):
        """Response should contain from, to, device_count, devices."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores")
        data = await resp.json()
        self.assertIn("from", data)
        self.assertIn("to", data)
        self.assertIn("device_count", data)
        self.assertIn("devices", data)
        self.assertIn("network_avg_connections", data)
        self.assertIn("network_stddev_connections", data)

    @unittest_run_loop
    async def test_scores_opensearch_error(self):
        """OpenSearch failure returns 502."""
        from opensearchpy import OpenSearchException
        self.mock_storage._client.search.side_effect = OpenSearchException("timeout")
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertIn("error", data)

    @unittest_run_loop
    async def test_scores_device_has_score_and_level(self):
        """Each device in the response should have score and level."""
        buckets = [_make_device_bucket("192.168.1.10")]
        conn_result = _make_conn_search_result(buckets=buckets, total=100)
        alert_result = _make_alert_search_result({})

        self.mock_storage._client.search.side_effect = [conn_result, alert_result]

        resp = await self.client.request("GET", "/api/risk/scores")
        data = await resp.json()
        self.assertEqual(data["device_count"], 1)
        device = data["devices"][0]
        self.assertIn("score", device)
        self.assertIn("level", device)
        self.assertIn("factors", device)
        self.assertIn("ip", device)

    @unittest_run_loop
    async def test_scores_with_limit_param(self):
        """The limit query parameter should be accepted."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores?limit=10")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_scores_alert_query_failure_graceful(self):
        """If alert query fails, scoring should still succeed (0 alerts)."""
        from opensearchpy import OpenSearchException
        buckets = [_make_device_bucket("192.168.1.10")]
        conn_result = _make_conn_search_result(buckets=buckets, total=100)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            OpenSearchException("alert index missing"),
        ]

        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["device_count"], 1)


class TestRiskScoreSingleEndpoint(AioHTTPTestCase):
    """Tests for GET /api/risk/scores/{ip}."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.risk_scorer = RiskScorer()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, self.risk_scorer, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_single_device_score(self):
        """GET /api/risk/scores/192.168.1.10 returns score for device."""
        conn_result = _make_single_conn_result(total=100)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=3)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["ip"], "192.168.1.10")
        self.assertIn("score", data)
        self.assertIn("level", data)
        self.assertIn("factors", data)

    @unittest_run_loop
    async def test_single_device_not_found(self):
        """GET /api/risk/scores/{ip} returns 404 for unknown device."""
        conn_result = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "total_orig_bytes": {"value": 0},
                "total_resp_bytes": {"value": 0},
                "ports_used": {"buckets": []},
                "external_conns": {"doc_count": 0},
            },
        }
        self.mock_storage._client.search.return_value = conn_result
        resp = await self.client.request("GET", "/api/risk/scores/10.0.0.99")
        self.assertEqual(resp.status, 404)

    @unittest_run_loop
    async def test_single_device_opensearch_error(self):
        """OpenSearch failure returns 502 for single device."""
        from opensearchpy import OpenSearchException
        self.mock_storage._client.search.side_effect = OpenSearchException("error")
        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 502)

    @unittest_run_loop
    async def test_single_device_has_from_to(self):
        """Response should include from and to timestamps."""
        conn_result = _make_single_conn_result(total=100)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        data = await resp.json()
        self.assertIn("from", data)
        self.assertIn("to", data)

    @unittest_run_loop
    async def test_single_device_connection_count(self):
        """Response should include connection_count."""
        conn_result = _make_single_conn_result(total=150)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        data = await resp.json()
        self.assertEqual(data["connection_count"], 150)

    @unittest_run_loop
    async def test_single_device_alert_count_in_response(self):
        """Response should include the device's alert_count."""
        conn_result = _make_single_conn_result(total=100)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=7)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        data = await resp.json()
        self.assertEqual(data["alert_count"], 7)

    @unittest_run_loop
    async def test_single_device_factors_list(self):
        """Factors list should contain 5 entries."""
        conn_result = _make_single_conn_result(total=100)
        network_result = _make_network_stats_result()
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            network_result,
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        data = await resp.json()
        self.assertEqual(len(data["factors"]), 5)

    @unittest_run_loop
    async def test_single_device_network_query_failure_graceful(self):
        """If network stats query fails, scoring still works."""
        from opensearchpy import OpenSearchException
        conn_result = _make_single_conn_result(total=100)
        alert_result = _make_single_alert_result(total=0)

        self.mock_storage._client.search.side_effect = [
            conn_result,
            OpenSearchException("network query failed"),
            alert_result,
        ]

        resp = await self.client.request("GET", "/api/risk/scores/192.168.1.10")
        self.assertEqual(resp.status, 200)


class TestRiskRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.mock_storage = _make_mock_storage()
        self.risk_scorer = RiskScorer()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        app["storage"] = self.mock_storage
        register_risk_routes(app, self.risk_scorer, self.mock_storage)
        return app

    @unittest_run_loop
    async def test_risk_scorer_stored_on_app(self):
        """The RiskScorer should be stored on the app dict."""
        self.assertIs(self.app["risk_scorer"], self.risk_scorer)

    @unittest_run_loop
    async def test_scores_route_exists(self):
        """The /api/risk/scores route should be registered."""
        self.mock_storage._client.search.return_value = _make_conn_search_result()
        resp = await self.client.request("GET", "/api/risk/scores")
        self.assertNotEqual(resp.status, 404)

    @unittest_run_loop
    async def test_single_score_route_exists(self):
        """The /api/risk/scores/{ip} route should be registered."""
        from opensearchpy import OpenSearchException
        # Will fail with 502 but not 404
        self.mock_storage._client.search.side_effect = OpenSearchException("test")
        resp = await self.client.request("GET", "/api/risk/scores/1.2.3.4")
        self.assertNotEqual(resp.status, 404)


if __name__ == "__main__":
    unittest.main()
