"""
Tests for daemon/api/setup.py — POST /api/setup/bridge/preview (CR-004).

The wizard's Verify step must check the WAN/LAN pair without building the
bridge, and refuse a port this machine still uses. Host ``ip -j`` queries are
mocked; any other host command (``ip link add``, ``set master``) would show up
in ``self.ip_calls``.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.setup import register_setup_routes
from services.capture_manager import CaptureMode
from services.capture_mode_stub import CaptureManagerStub
from services.dhcp_gateway import DhcpGatewayManager

URL = "/api/setup/bridge/preview"
PAIR = {"wan_interface": "enp2s0", "lan_interface": "enp3s0"}


class TestBridgePreview(AioHTTPTestCase):
    def setUp(self):
        # Host network as seen by ``ip -j``
        self.host_links = {"enp1s0", "enp2s0", "enp3s0"}
        self.host_addrs = {"enp1s0": ["192.168.1.50/24"]}
        self.host_routes = [
            {"dst": "default", "gateway": "192.168.1.1", "dev": "enp1s0"}
        ]
        self.ip_calls = []
        self.patch = patch(
            "services.dhcp_gateway_host.HostNetOps.ip_json", side_effect=self._ip_json
        )
        self.patch.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.patch.stop()

    async def _ip_json(self, *args):
        self.ip_calls.append(args)
        if args[:2] == ("link", "show"):
            return [{"ifname": args[3]}] if args[3] in self.host_links else []
        if args[:3] == ("-4", "route", "show"):
            return self.host_routes
        if args[:3] == ("-4", "addr", "show"):
            info = [
                {"local": c.split("/")[0], "prefixlen": int(c.split("/")[1])}
                for c in self.host_addrs.get(args[4], [])
            ]
            return [{"ifname": args[4], "addr_info": info}]
        return []

    async def get_application(self):
        app = web.Application()
        app["capture_manager"] = CaptureManagerStub()
        register_setup_routes(app)
        return app

    async def _post(self, body):
        resp = await self.client.request("POST", URL, json=body)
        return resp.status, await resp.json()

    def _only_reads(self):
        return all(c[0] in ("link", "-4") and "show" in c for c in self.ip_calls)

    async def test_spare_pair_is_ready_and_nothing_is_changed(self):
        status, body = await self._post(PAIR)
        self.assertEqual(status, 200)
        self.assertTrue(body["ready"])
        self.assertEqual((body["wan"], body["lan"]), ("enp2s0", "enp3s0"))
        self.assertIn("WAN_INTERFACE=enp2s0", body["config_preview"])
        self.assertTrue(self.ip_calls)
        self.assertTrue(self._only_reads())

    async def test_refuses_the_port_with_the_management_address(self):
        self.host_routes = []
        status, body = await self._post(
            {"wan_interface": "enp1s0", "lan_interface": "enp3s0"}
        )
        self.assertEqual(status, 400)
        self.assertIn("enp1s0", body["error"])
        self.assertIn("192.168.1.50", body["error"])
        self.assertNotIn("ready", body)

    async def test_refuses_the_default_route_port(self):
        status, body = await self._post(
            {"wan_interface": "enp2s0", "lan_interface": "enp1s0"}
        )
        self.assertEqual(status, 400)
        self.assertIn("default route", body["error"])

    async def test_refuses_the_live_dhcp_gateway_port(self):
        gateway = MagicMock(spec=DhcpGatewayManager)
        gateway.mode = CaptureMode.DHCP_GATEWAY
        gateway.routing_active = True
        gateway.get_capture_interface = MagicMock(return_value="enp3s0")
        self.app["capture_manager"] = gateway
        status, body = await self._post(PAIR)
        self.assertEqual(status, 400)
        self.assertIn("DHCP gateway mode is routing", body["error"])

    async def test_refuses_a_missing_port(self):
        status, body = await self._post(
            {"wan_interface": "enp2s0", "lan_interface": "eth9"}
        )
        self.assertEqual(status, 400)
        self.assertIn("eth9 was not found", body["error"])

    async def test_refuses_bad_names_and_the_same_port_twice(self):
        for bad in (
            {"wan_interface": "enp2s0", "lan_interface": "enp2s0"},
            {"wan_interface": "-x", "lan_interface": "enp3s0"},
            {"wan_interface": "enp2s0"},
        ):
            status, _ = await self._post(bad)
            self.assertEqual(status, 400, bad)
        self.assertEqual(self.ip_calls, [])


if __name__ == "__main__":
    unittest.main()
