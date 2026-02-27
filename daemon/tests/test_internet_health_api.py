"""
Tests for daemon/api/health_monitor.py

All tests use mocks -- no real network access required. Tests cover
all four internet health monitor API endpoints.
"""

import unittest
from datetime import datetime, timezone, timedelta

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.health_monitor import register_health_monitor_routes
from services.internet_health import InternetHealthMonitor, HealthCheck


def _make_monitor_with_history() -> InternetHealthMonitor:
    """Create a monitor with some pre-populated history."""
    monitor = InternetHealthMonitor()
    base = datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        ts = (base + timedelta(minutes=i * 5)).isoformat()
        monitor._history.append(
            HealthCheck(
                timestamp=ts,
                latency_ms=20.0 + i,
                dns_resolve_ms=50.0 + i,
                packet_loss_pct=0.0,
                status="healthy",
            )
        )
    return monitor


class TestHealthStatusEndpoint(AioHTTPTestCase):
    """Tests for GET /api/internet/health."""

    def setUp(self):
        self.monitor = _make_monitor_with_history()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_health_monitor_routes(app, self.monitor)
        return app

    @unittest_run_loop
    async def test_health_status_returns_200(self):
        """GET /api/internet/health should return 200."""
        resp = await self.client.request("GET", "/api/internet/health")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_health_status_returns_latest(self):
        """GET /api/internet/health should return the most recent check."""
        resp = await self.client.request("GET", "/api/internet/health")
        data = await resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("latency_ms", data)
        self.assertIn("dns_resolve_ms", data)
        self.assertIn("packet_loss_pct", data)

    @unittest_run_loop
    async def test_health_status_empty_history(self):
        """GET /api/internet/health with no history returns unknown."""
        self.monitor._history.clear()
        resp = await self.client.request("GET", "/api/internet/health")
        data = await resp.json()
        self.assertEqual(data["status"], "unknown")


class TestHealthHistoryEndpoint(AioHTTPTestCase):
    """Tests for GET /api/internet/history."""

    def setUp(self):
        self.monitor = _make_monitor_with_history()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_health_monitor_routes(app, self.monitor)
        return app

    @unittest_run_loop
    async def test_history_returns_200(self):
        """GET /api/internet/history should return 200."""
        resp = await self.client.request("GET", "/api/internet/history")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_history_returns_list(self):
        """GET /api/internet/history should return history array."""
        resp = await self.client.request("GET", "/api/internet/history")
        data = await resp.json()
        self.assertIn("history", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 5)

    @unittest_run_loop
    async def test_history_with_limit(self):
        """GET /api/internet/history?limit=2 should return limited history."""
        resp = await self.client.request("GET", "/api/internet/history?limit=2")
        data = await resp.json()
        self.assertEqual(data["count"], 2)

    @unittest_run_loop
    async def test_history_invalid_limit(self):
        """GET /api/internet/history?limit=abc should use default."""
        resp = await self.client.request("GET", "/api/internet/history?limit=abc")
        data = await resp.json()
        self.assertEqual(data["count"], 5)


class TestHealthStatsEndpoint(AioHTTPTestCase):
    """Tests for GET /api/internet/stats."""

    def setUp(self):
        self.monitor = _make_monitor_with_history()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_health_monitor_routes(app, self.monitor)
        return app

    @unittest_run_loop
    async def test_stats_returns_200(self):
        """GET /api/internet/stats should return 200."""
        resp = await self.client.request("GET", "/api/internet/stats")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_stats_has_expected_keys(self):
        """GET /api/internet/stats should contain all stat keys."""
        resp = await self.client.request("GET", "/api/internet/stats")
        data = await resp.json()
        expected_keys = {
            "avg_latency_ms", "p95_latency_ms", "min_latency_ms",
            "max_latency_ms", "avg_dns_ms", "avg_packet_loss_pct",
            "uptime_pct", "total_checks", "history_span_hours",
        }
        self.assertEqual(set(data.keys()), expected_keys)


class TestHealthCheckEndpoint(AioHTTPTestCase):
    """Tests for POST /api/internet/check."""

    def setUp(self):
        self.monitor = InternetHealthMonitor(
            ping_targets=["8.8.8.8"],
            dns_targets=["google.com"],
        )
        # Mock the actual network calls
        async def mock_latency(target, timeout=5.0):
            return 25.0

        async def mock_dns(domain, timeout=5.0):
            return 50.0

        async def mock_loss(target, count=10, timeout=10.0):
            return 0.0

        self.monitor.check_latency = mock_latency
        self.monitor.check_dns = mock_dns
        self.monitor.check_packet_loss = mock_loss
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_health_monitor_routes(app, self.monitor)
        return app

    @unittest_run_loop
    async def test_check_returns_200(self):
        """POST /api/internet/check should return 200."""
        resp = await self.client.request("POST", "/api/internet/check")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_check_returns_result(self):
        """POST /api/internet/check should return a health check result."""
        resp = await self.client.request("POST", "/api/internet/check")
        data = await resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("timestamp", data)
        self.assertIn("latency_ms", data)

    @unittest_run_loop
    async def test_check_adds_to_history(self):
        """POST /api/internet/check should add result to history."""
        self.assertEqual(len(self.monitor._history), 0)
        await self.client.request("POST", "/api/internet/check")
        self.assertEqual(len(self.monitor._history), 1)


class TestRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.monitor = InternetHealthMonitor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_health_monitor_routes(app, self.monitor)
        return app

    @unittest_run_loop
    async def test_monitor_stored_on_app(self):
        """The monitor should be stored on the app dict."""
        self.assertIs(self.app["internet_health"], self.monitor)


if __name__ == "__main__":
    unittest.main()
