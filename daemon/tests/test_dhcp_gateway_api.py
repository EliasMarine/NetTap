"""
Tests for daemon/api/dhcp_gateway.py

Covers GET /api/capture/dhcp/preflight, POST /api/capture/dhcp/enable,
POST /api/capture/dhcp/disable and GET /api/capture/dhcp/status. The
DhcpGatewayManager is a spec'd mock (its behaviour is covered in
test_dhcp_gateway.py); container restarts are mocked; capture-mode.conf and
capture.env go to a temp dir.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.dhcp_gateway import CAPTURE_LOCK_KEY, register_dhcp_gateway_routes
from services.capture_config import CaptureConfig, save_capture_config
from services.capture_manager import CaptureMode
from services.capture_mode_stub import CaptureManagerStub
from services.dhcp_gateway import DhcpGatewayManager

MODULE = "api.dhcp_gateway"

STATUS = {
    "interface": "enp1s0",
    "subnet": "10.77.0.0/24",
    "gateway_ip": "10.77.0.1",
    "upstream": {"address": "192.168.1.50/24", "gateway": "192.168.1.1"},
    "routing_active": True,
    "dhcp_enabled": True,
    "dhcp_server_running": True,
    "leases": [],
    "issues": [],
}
CHECKS = [
    {
        "name": "no_other_dhcp",
        "passed": False,
        "blocking": True,
        "message": "Your router's DHCP server is still on (192.168.1.1).",
    }
]
RESTARTED = {"restarted": ["nettap-zeek-live"], "errors": []}


def _manager() -> MagicMock:
    """A DhcpGatewayManager stand-in (passes isinstance)."""
    mgr = MagicMock(spec=DhcpGatewayManager)
    mgr.mode = CaptureMode.DHCP_GATEWAY
    mgr.routing_active = False
    mgr.preflight = AsyncMock(return_value={"ready": True, "checks": []})
    mgr.enable = AsyncMock(return_value=(True, dict(STATUS)))
    mgr.disable = AsyncMock(return_value={**STATUS, "dhcp_enabled": False})
    mgr.status = AsyncMock(return_value=dict(STATUS))
    return mgr


class _Base(AioHTTPTestCase):
    """App with the DHCP routes, a mock manager and temp capture files."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.conf_path = os.path.join(self.tmpdir.name, "capture-mode.conf")
        self.env_path = os.path.join(self.tmpdir.name, "capture.env")
        self.env_patch = patch.dict(
            os.environ,
            {"CAPTURE_CONFIG_PATH": self.conf_path, "CAPTURE_ENV_PATH": self.env_path},
        )
        self.env_patch.start()
        save_capture_config(
            CaptureConfig(
                mode=CaptureMode.DHCP_GATEWAY,
                interface="enp1s0",
                dhcp_upstream_address="192.168.1.50/24",
                dhcp_upstream_gateway="192.168.1.1",
                dhcp_enabled=True,
            )
        )
        self.mgr = _manager()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.env_patch.stop()
        self.tmpdir.cleanup()

    async def get_application(self):
        app = web.Application()
        app["capture_manager"] = self.mgr
        register_dhcp_gateway_routes(app)
        return app

    def _use_stub(self):
        with patch.dict(os.environ, {"CAPTURE_CONFIG_PATH": "/nonexistent.conf"}):
            self.app["capture_manager"] = CaptureManagerStub()


# ---------------------------------------------------------------------------
# Mode mismatch (all four endpoints)
# ---------------------------------------------------------------------------


class TestModeMismatch(_Base):
    async def test_all_endpoints_409_when_not_dhcp_mode(self):
        self._use_stub()
        for method, path, body in (
            ("GET", "/api/capture/dhcp/preflight", None),
            ("POST", "/api/capture/dhcp/enable", {"confirm": True}),
            ("POST", "/api/capture/dhcp/disable", None),
            ("GET", "/api/capture/dhcp/status", None),
        ):
            resp = await self.client.request(method, path, json=body)
            self.assertEqual(resp.status, 409, path)
            data = await resp.json()
            self.assertIn("bridge", data["error"])
        self.mgr.enable.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /api/capture/dhcp/preflight
# ---------------------------------------------------------------------------


class TestPreflight(_Base):
    async def test_returns_manager_preflight(self):
        resp = await self.client.request("GET", "/api/capture/dhcp/preflight")
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.json(), {"ready": True, "checks": []})

    async def test_exception_is_500(self):
        self.mgr.preflight.side_effect = RuntimeError("probe exploded")
        resp = await self.client.request("GET", "/api/capture/dhcp/preflight")
        self.assertEqual(resp.status, 500)
        self.assertIn("probe exploded", (await resp.json())["error"])


# ---------------------------------------------------------------------------
# POST /api/capture/dhcp/enable
# ---------------------------------------------------------------------------


class TestEnable(_Base):
    async def _enable(self, **kwargs):
        return await self.client.request("POST", "/api/capture/dhcp/enable", **kwargs)

    async def test_400_without_confirm(self):
        for kwargs in (
            {},
            {"json": {}},
            {"json": {"confirm": False}},
            {"json": {"confirm": "true"}},
            {"json": [True]},
            {"data": "not json", "headers": {"Content-Type": "application/json"}},
        ):
            resp = await self._enable(**kwargs)
            self.assertEqual(resp.status, 400, kwargs)
        self.mgr.enable.assert_not_awaited()

    @patch(f"{MODULE}.restart_capture_containers", new_callable=AsyncMock)
    async def test_409_with_checks_when_preflight_blocks(self, mock_restart):
        self.mgr.enable.return_value = (
            False,
            {"error": "DHCP gateway mode can't be turned on yet.", "checks": CHECKS},
        )
        resp = await self._enable(json={"confirm": True})
        self.assertEqual(resp.status, 409)
        data = await resp.json()
        self.assertEqual(data["checks"], CHECKS)
        self.assertIn("error", data)
        mock_restart.assert_not_awaited()
        self.assertFalse(os.path.exists(self.env_path))

    @patch(f"{MODULE}.restart_capture_containers", new_callable=AsyncMock)
    async def test_500_when_apply_fails(self, mock_restart):
        self.mgr.enable.return_value = (
            False,
            {"error": "Could not turn on DHCP gateway mode: boom"},
        )
        resp = await self._enable(json={"confirm": True})
        self.assertEqual(resp.status, 500)
        self.assertIn("boom", (await resp.json())["error"])
        mock_restart.assert_not_awaited()

    @patch(f"{MODULE}.restart_capture_containers", new_callable=AsyncMock)
    async def test_success_writes_env_then_restarts(self, mock_restart):
        def check_env_written():
            # capture.env must be on disk before the containers re-read it
            with open(self.env_path) as f:
                self.assertIn("PCAP_IFACE=enp1s0", f.read())
            return RESTARTED

        mock_restart.side_effect = check_env_written
        resp = await self._enable(json={"confirm": True})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data, {**STATUS, "capture_restart": RESTARTED})
        mock_restart.assert_awaited_once()
        with open(self.env_path) as f:
            self.assertEqual(
                f.read(),
                "CAPTURE_MODE=dhcp_gateway\n"
                "PCAP_IFACE=enp1s0\n"
                "PCAP_FILTER=net 10.77.0.0/24 or udp port 67 or udp port 68\n",
            )

    @patch(f"{MODULE}.restart_capture_containers", new_callable=AsyncMock)
    async def test_unchanged_env_skips_restart(self, mock_restart):
        """The wizard already wrote this capture.env: no capture outage on enable."""
        with open(self.env_path, "w") as f:
            f.write(
                "CAPTURE_MODE=dhcp_gateway\n"
                "PCAP_IFACE=enp1s0\n"
                "PCAP_FILTER=net 10.77.0.0/24 or udp port 67 or udp port 68\n"
            )
        resp = await self._enable(json={"confirm": True})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["capture_restart"], {"restarted": [], "errors": []})
        mock_restart.assert_not_awaited()

    @patch(f"{MODULE}.restart_capture_containers", new_callable=AsyncMock)
    async def test_env_write_failure_is_reported_not_500(self, mock_restart):
        """Routing is already on: a capture.env problem must not look like a failed enable."""
        with patch(
            f"{MODULE}.write_env_file_if_changed", side_effect=OSError("read-only")
        ):
            resp = await self._enable(json={"confirm": True})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["capture_restart"]["restarted"], [])
        self.assertIn("read-only", data["capture_restart"]["errors"][0])
        mock_restart.assert_not_awaited()

    @patch(f"{MODULE}.restart_capture_containers", new_callable=AsyncMock)
    async def test_waits_for_the_shared_lock(self, mock_restart):
        mock_restart.return_value = RESTARTED
        lock = self.app[CAPTURE_LOCK_KEY]
        await lock.acquire()
        task = asyncio.ensure_future(self._enable(json={"confirm": True}))
        await asyncio.sleep(0.05)
        self.assertFalse(task.done())
        self.mgr.enable.assert_not_awaited()
        lock.release()
        resp = await task
        self.assertEqual(resp.status, 200)
        self.mgr.enable.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /api/capture/dhcp/disable, GET /api/capture/dhcp/status
# ---------------------------------------------------------------------------


class TestDisableAndStatus(_Base):
    async def test_disable_returns_status(self):
        resp = await self.client.request("POST", "/api/capture/dhcp/disable")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertFalse(data["dhcp_enabled"])
        self.assertTrue(data["routing_active"])
        self.mgr.disable.assert_awaited_once()

    async def test_disable_exception_is_500(self):
        self.mgr.disable.side_effect = RuntimeError("stuck")
        resp = await self.client.request("POST", "/api/capture/dhcp/disable")
        self.assertEqual(resp.status, 500)

    async def test_status(self):
        resp = await self.client.request("GET", "/api/capture/dhcp/status")
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.json(), STATUS)


if __name__ == "__main__":
    unittest.main()
