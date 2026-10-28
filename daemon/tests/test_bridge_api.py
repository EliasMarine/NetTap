"""
Tests for daemon/api/bridge.py

All tests use mocked BridgeHealthMonitor -- no real sysfs, systemctl,
or network access required. Tests cover all bridge health API endpoints
using AioHTTPTestCase.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from api.bridge import register_bridge_routes
from services.bridge_health import BridgeHealthMonitor
from services.bridge_manager import BridgeManager


def _make_mock_monitor():
    """Create a mock BridgeHealthMonitor with async method stubs."""
    monitor = BridgeHealthMonitor.__new__(BridgeHealthMonitor)
    monitor._bypass_active = False
    monitor._history = []
    return monitor


def _make_mock_manager():
    """Create a mock BridgeManager with async method stubs."""
    manager = BridgeManager.__new__(BridgeManager)
    manager._bridge_name = "br0"
    return manager


def _make_health_result(
    bridge_state="up",
    wan_link=True,
    lan_link=True,
    health_status="normal",
    bypass_active=False,
):
    """Build a mock health check result dict."""
    return {
        "bridge_state": bridge_state,
        "wan_link": wan_link,
        "lan_link": lan_link,
        "bypass_active": bypass_active,
        "watchdog_active": False,
        "latency_us": 50.0,
        "rx_bytes_delta": 1000,
        "tx_bytes_delta": 2000,
        "rx_packets_delta": 10,
        "tx_packets_delta": 20,
        "uptime_seconds": 3600.0,
        "health_status": health_status,
        "issues": [],
        "last_check": "2026-02-26T12:00:00+00:00",
    }


class TestBridgeHealthEndpoint(AioHTTPTestCase):
    """Tests for GET /api/bridge/health."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor)
        return app

    @unittest_run_loop
    async def test_health_returns_200(self):
        """GET /api/bridge/health should return 200."""
        self.mock_monitor.check_health = AsyncMock(return_value=_make_health_result())
        resp = await self.client.request("GET", "/api/bridge/health")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_health_returns_correct_structure(self):
        """Response should contain expected keys."""
        self.mock_monitor.check_health = AsyncMock(return_value=_make_health_result())
        resp = await self.client.request("GET", "/api/bridge/health")
        data = await resp.json()
        expected_keys = {
            "bridge_state",
            "wan_link",
            "lan_link",
            "bypass_active",
            "watchdog_active",
            "latency_us",
            "rx_bytes_delta",
            "tx_bytes_delta",
            "rx_packets_delta",
            "tx_packets_delta",
            "uptime_seconds",
            "health_status",
            "issues",
            "last_check",
        }
        self.assertEqual(set(data.keys()), expected_keys)

    @unittest_run_loop
    async def test_health_normal_status(self):
        """Health check with normal bridge should return 'normal'."""
        self.mock_monitor.check_health = AsyncMock(
            return_value=_make_health_result(health_status="normal")
        )
        resp = await self.client.request("GET", "/api/bridge/health")
        data = await resp.json()
        self.assertEqual(data["health_status"], "normal")

    @unittest_run_loop
    async def test_health_error_returns_500(self):
        """Internal error should return 500."""
        self.mock_monitor.check_health = AsyncMock(
            side_effect=RuntimeError("test error")
        )
        resp = await self.client.request("GET", "/api/bridge/health")
        self.assertEqual(resp.status, 500)
        data = await resp.json()
        self.assertIn("error", data)


class TestBridgeHistoryEndpoint(AioHTTPTestCase):
    """Tests for GET /api/bridge/history."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor)
        return app

    @unittest_run_loop
    async def test_history_returns_200(self):
        """GET /api/bridge/history should return 200."""
        self.mock_monitor.get_history = AsyncMock(return_value=[])
        resp = await self.client.request("GET", "/api/bridge/history")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_history_returns_list(self):
        """Response should contain a history list."""
        self.mock_monitor.get_history = AsyncMock(
            return_value=[_make_health_result(), _make_health_result()]
        )
        resp = await self.client.request("GET", "/api/bridge/history")
        data = await resp.json()
        self.assertIn("history", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], 2)
        self.assertIsInstance(data["history"], list)

    @unittest_run_loop
    async def test_history_with_limit_param(self):
        """The limit query parameter should be accepted."""
        self.mock_monitor.get_history = AsyncMock(return_value=[])
        resp = await self.client.request("GET", "/api/bridge/history?limit=10")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_history_invalid_limit_ignored(self):
        """Invalid limit parameter should be silently ignored."""
        self.mock_monitor.get_history = AsyncMock(return_value=[])
        resp = await self.client.request("GET", "/api/bridge/history?limit=abc")
        self.assertEqual(resp.status, 200)


class TestBridgeStatsEndpoint(AioHTTPTestCase):
    """Tests for GET /api/bridge/stats."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor)
        return app

    @unittest_run_loop
    async def test_stats_returns_200(self):
        """GET /api/bridge/stats should return 200."""
        self.mock_monitor.get_statistics = AsyncMock(
            return_value={
                "average_latency_us": 50.0,
                "total_rx_bytes": 10000,
                "total_tx_bytes": 20000,
                "total_rx_packets": 100,
                "total_tx_packets": 200,
                "uptime_percentage": 99.5,
                "longest_downtime_seconds": 30,
                "total_checks": 100,
                "status_counts": {"normal": 95, "degraded": 3, "bypass": 1, "down": 1},
            }
        )
        resp = await self.client.request("GET", "/api/bridge/stats")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_stats_contains_expected_keys(self):
        """Stats response should contain all expected keys."""
        self.mock_monitor.get_statistics = AsyncMock(
            return_value={
                "average_latency_us": 50.0,
                "total_rx_bytes": 10000,
                "total_tx_bytes": 20000,
                "total_rx_packets": 100,
                "total_tx_packets": 200,
                "uptime_percentage": 99.5,
                "longest_downtime_seconds": 30,
                "total_checks": 100,
                "status_counts": {"normal": 95, "degraded": 3, "bypass": 1, "down": 1},
            }
        )
        resp = await self.client.request("GET", "/api/bridge/stats")
        data = await resp.json()
        self.assertIn("average_latency_us", data)
        self.assertIn("total_rx_bytes", data)
        self.assertIn("uptime_percentage", data)
        self.assertIn("status_counts", data)


class TestBypassEnableEndpoint(AioHTTPTestCase):
    """Tests for POST /api/bridge/bypass/enable."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor)
        return app

    @unittest_run_loop
    async def test_bypass_enable_returns_200(self):
        """POST /api/bridge/bypass/enable should return 200."""
        self.mock_monitor.trigger_bypass = AsyncMock(
            return_value={
                "bypass_active": True,
                "activated_at": "2026-02-26T12:00:00+00:00",
                "message": "Bypass mode activated",
            }
        )
        resp = await self.client.request("POST", "/api/bridge/bypass/enable")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_bypass_enable_confirms_activation(self):
        """Response should confirm bypass activation."""
        self.mock_monitor.trigger_bypass = AsyncMock(
            return_value={
                "bypass_active": True,
                "activated_at": "2026-02-26T12:00:00+00:00",
                "message": "Bypass mode activated",
            }
        )
        resp = await self.client.request("POST", "/api/bridge/bypass/enable")
        data = await resp.json()
        self.assertTrue(data["bypass_active"])
        self.assertIn("activated_at", data)


class TestBypassDisableEndpoint(AioHTTPTestCase):
    """Tests for POST /api/bridge/bypass/disable."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor)
        return app

    @unittest_run_loop
    async def test_bypass_disable_returns_200(self):
        """POST /api/bridge/bypass/disable should return 200."""
        self.mock_monitor.disable_bypass = AsyncMock(
            return_value={
                "bypass_active": False,
                "deactivated_at": "2026-02-26T12:00:00+00:00",
                "message": "Bypass mode deactivated",
            }
        )
        resp = await self.client.request("POST", "/api/bridge/bypass/disable")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_bypass_disable_confirms_deactivation(self):
        """Response should confirm bypass deactivation."""
        self.mock_monitor.disable_bypass = AsyncMock(
            return_value={
                "bypass_active": False,
                "deactivated_at": "2026-02-26T12:00:00+00:00",
                "message": "Bypass mode deactivated",
            }
        )
        resp = await self.client.request("POST", "/api/bridge/bypass/disable")
        data = await resp.json()
        self.assertFalse(data["bypass_active"])
        self.assertIn("deactivated_at", data)


class TestBypassStatusEndpoint(AioHTTPTestCase):
    """Tests for GET /api/bridge/bypass/status."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor)
        return app

    @unittest_run_loop
    async def test_bypass_status_returns_200(self):
        """GET /api/bridge/bypass/status should return 200."""
        resp = await self.client.request("GET", "/api/bridge/bypass/status")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_bypass_status_default_inactive(self):
        """Bypass should be inactive by default."""
        resp = await self.client.request("GET", "/api/bridge/bypass/status")
        data = await resp.json()
        self.assertFalse(data["bypass_active"])

    @unittest_run_loop
    async def test_bypass_status_active(self):
        """Bypass status should reflect activated state."""
        self.mock_monitor._bypass_active = True
        resp = await self.client.request("GET", "/api/bridge/bypass/status")
        data = await resp.json()
        self.assertTrue(data["bypass_active"])


class TestBridgeCreateEndpoint(AioHTTPTestCase):
    """Tests for POST /api/setup/bridge."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        self.mock_manager = _make_mock_manager()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor, self.mock_manager)
        return app

    @unittest_run_loop
    async def test_create_returns_200(self):
        """POST /api/setup/bridge should return 200 on success."""
        self.mock_manager.create_bridge = AsyncMock(
            return_value={
                "created": True,
                "bridge_name": "br0",
                "wan": "enp2s0",
                "lan": "enp3s0",
                "state": "created",
                "errors": [],
                "warnings": [],
                "persistence_files": [],
            }
        )
        resp = await self.client.request(
            "POST",
            "/api/setup/bridge",
            json={"wan_interface": "enp2s0", "lan_interface": "enp3s0"},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["created"])

    @unittest_run_loop
    async def test_create_missing_params_returns_400(self):
        """Missing wan/lan params should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/bridge",
            json={"wan_interface": "enp2s0"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_create_invalid_json_returns_400(self):
        """Invalid JSON body should return 400."""
        resp = await self.client.request(
            "POST",
            "/api/setup/bridge",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    @unittest_run_loop
    async def test_create_failure_returns_400(self):
        """Bridge creation failure should return 400."""
        self.mock_manager.create_bridge = AsyncMock(
            return_value={
                "created": False,
                "bridge_name": "br0",
                "wan": "eth0",
                "lan": "eth0",
                "state": "error",
                "errors": ["WAN and LAN interfaces must be different"],
                "warnings": [],
                "persistence_files": [],
            }
        )
        resp = await self.client.request(
            "POST",
            "/api/setup/bridge",
            json={"wan_interface": "eth0", "lan_interface": "eth0"},
        )
        self.assertEqual(resp.status, 400)


class TestBridgeTeardownEndpoint(AioHTTPTestCase):
    """Tests for POST /api/bridge/teardown."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        self.mock_manager = _make_mock_manager()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor, self.mock_manager)
        return app

    @unittest_run_loop
    async def test_teardown_returns_200(self):
        """POST /api/bridge/teardown should return 200 on success."""
        self.mock_manager.teardown_bridge = AsyncMock(
            return_value={"torn_down": True, "errors": []}
        )
        resp = await self.client.request("POST", "/api/bridge/teardown")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["torn_down"])

    @unittest_run_loop
    async def test_teardown_failure_returns_400(self):
        """Teardown failure should return 400."""
        self.mock_manager.teardown_bridge = AsyncMock(
            return_value={
                "torn_down": False,
                "errors": ["Bridge br0 does not exist"],
            }
        )
        resp = await self.client.request("POST", "/api/bridge/teardown")
        self.assertEqual(resp.status, 400)


class TestBridgeReadinessEndpoint(AioHTTPTestCase):
    """Tests for GET /api/bridge/readiness."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        self.mock_manager = _make_mock_manager()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor, self.mock_manager)
        return app

    @unittest_run_loop
    async def test_readiness_returns_200(self):
        """GET /api/bridge/readiness should return 200."""
        self.mock_manager.check_readiness = AsyncMock(
            return_value={
                "ready": False,
                "checks": [{"name": "bridge_exists", "passed": False, "detail": "Not found"}],
                "message": "Bridge not configured",
            }
        )
        resp = await self.client.request("GET", "/api/bridge/readiness")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_readiness_returns_correct_structure(self):
        """Readiness response should contain ready, checks, message."""
        self.mock_manager.check_readiness = AsyncMock(
            return_value={
                "ready": True,
                "checks": [],
                "message": "All good",
            }
        )
        resp = await self.client.request("GET", "/api/bridge/readiness")
        data = await resp.json()
        self.assertIn("ready", data)
        self.assertIn("checks", data)
        self.assertIn("message", data)

    @unittest_run_loop
    async def test_readiness_error_returns_500(self):
        """Internal error should return 500."""
        self.mock_manager.check_readiness = AsyncMock(
            side_effect=RuntimeError("test error")
        )
        resp = await self.client.request("GET", "/api/bridge/readiness")
        self.assertEqual(resp.status, 500)


class TestRouteRegistration(AioHTTPTestCase):
    """Tests for route registration."""

    def setUp(self):
        self.mock_monitor = _make_mock_monitor()
        self.mock_manager = _make_mock_manager()
        super().setUp()

    async def get_application(self):
        app = web.Application()
        register_bridge_routes(app, self.mock_monitor, self.mock_manager)
        return app

    @unittest_run_loop
    async def test_monitor_stored_on_app(self):
        """The BridgeHealthMonitor should be stored on the app dict."""
        self.assertIs(self.app["bridge_health"], self.mock_monitor)

    @unittest_run_loop
    async def test_manager_stored_on_app(self):
        """The BridgeManager should be stored on the app dict."""
        self.assertIs(self.app["bridge_manager"], self.mock_manager)

    @unittest_run_loop
    async def test_all_routes_registered(self):
        """All 9 bridge routes should be registered."""
        # Verify routes exist by checking they do not return 404
        self.mock_monitor.check_health = AsyncMock(return_value=_make_health_result())
        self.mock_monitor.get_history = AsyncMock(return_value=[])
        self.mock_monitor.get_statistics = AsyncMock(
            return_value={
                "average_latency_us": None,
                "total_rx_bytes": 0,
                "total_tx_bytes": 0,
                "total_rx_packets": 0,
                "total_tx_packets": 0,
                "uptime_percentage": None,
                "longest_downtime_seconds": 0,
                "total_checks": 0,
                "status_counts": {"normal": 0, "degraded": 0, "bypass": 0, "down": 0},
            }
        )
        self.mock_monitor.trigger_bypass = AsyncMock(
            return_value={
                "bypass_active": True,
                "activated_at": "ts",
                "message": "ok",
            }
        )
        self.mock_monitor.disable_bypass = AsyncMock(
            return_value={
                "bypass_active": False,
                "deactivated_at": "ts",
                "message": "ok",
            }
        )
        self.mock_manager.create_bridge = AsyncMock(
            return_value={
                "created": True,
                "bridge_name": "br0",
                "wan": "eth0",
                "lan": "eth1",
                "state": "created",
                "errors": [],
                "warnings": [],
                "persistence_files": [],
            }
        )
        self.mock_manager.teardown_bridge = AsyncMock(
            return_value={"torn_down": True, "errors": []}
        )
        self.mock_manager.check_readiness = AsyncMock(
            return_value={
                "ready": False,
                "checks": [],
                "message": "Not ready",
            }
        )

        routes_to_check = [
            ("GET", "/api/bridge/health"),
            ("GET", "/api/bridge/history"),
            ("GET", "/api/bridge/stats"),
            ("POST", "/api/bridge/bypass/enable"),
            ("POST", "/api/bridge/bypass/disable"),
            ("GET", "/api/bridge/bypass/status"),
            ("GET", "/api/bridge/readiness"),
            ("POST", "/api/bridge/teardown"),
        ]
        for method, path in routes_to_check:
            resp = await self.client.request(method, path)
            self.assertNotEqual(
                resp.status,
                404,
                f"Route {method} {path} returned 404 -- not registered",
            )


if __name__ == "__main__":
    unittest.main()
