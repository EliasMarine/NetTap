"""
Tests for daemon/api/setup.py — POST /api/setup/bridge/preview (CR-004).

The wizard's Verify step must check the WAN/LAN pair without building the
bridge, and refuse a port this machine still uses. Host ``ip -j`` queries are
mocked; any other host command (``ip link add``, ``set master``) would show up
in ``self.ip_calls``.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.setup import _nic_in_use_problem, register_setup_routes
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
        self.host_masters = {}  # NET-287: NIC -> the bridge or bond it is a port of
        self.sysfs = tempfile.mkdtemp()
        self.patch = patch(
            "services.dhcp_gateway_host.HostNetOps.ip_json", side_effect=self._ip_json
        )
        self.patch.start()
        self.sysfs_patch = patch("services.bridge_manager._SYSFS_NET", self.sysfs)
        self.sysfs_patch.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.patch.stop()
        self.sysfs_patch.stop()
        shutil.rmtree(self.sysfs)

    async def _ip_json(self, *args):
        self.ip_calls.append(args)
        if args[:2] == ("link", "show"):
            if args[3] not in self.host_links:
                return []
            master = self.host_masters.get(args[3])
            return [{"ifname": args[3], **({"master": master} if master else {})}]
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

    # -- NET-287: a br0 NetTap didn't make, and ports of bridges or bonds ---------
    def _br0(self, nettaps=False):
        self.host_links.add("br0")
        os.makedirs(os.path.join(self.sysfs, "br0", "brif"))
        if nettaps:
            with open(os.path.join(self.sysfs, "br0", "ifalias"), "w") as f:
                f.write("nettap\n")

    async def test_refuses_spare_ports_while_a_foreign_br0_exists(self):
        self._br0()
        status, body = await self._post(PAIR)
        self.assertEqual(status, 400)
        self.assertIn("br0 that NetTap didn't set up", body["error"])
        self.assertTrue(self._only_reads())

    async def test_refuses_a_port_of_a_foreign_br0(self):
        self._br0()
        self.host_masters["enp3s0"] = "br0"
        status, body = await self._post(PAIR)
        self.assertEqual(status, 400)
        self.assertIn("didn't set up", body["error"])

    async def test_refuses_a_port_of_a_bond(self):
        self.host_masters["enp3s0"] = "bond0"
        status, body = await self._post(PAIR)
        self.assertEqual(status, 400)
        self.assertIn("enp3s0 is already part of bond0", body["error"])
        self.assertNotIn("alias", body["error"])  # the br0 fix doesn't apply to a bond

    async def test_accepts_a_port_of_nettaps_own_br0(self):
        self._br0(nettaps=True)
        self.host_masters["enp3s0"] = "br0"
        status, body = await self._post(PAIR)
        self.assertEqual(status, 200, body)

    async def test_guard_calls_a_port_of_a_foreign_br0_in_use(self):
        self._br0()
        self.host_masters["enp3s0"] = "br0"
        problem = await _nic_in_use_problem(None, "enp3s0")
        # OLD CODE: "is already part of br0, which this machine set up for something else", (NET-287 review)
        self.assertEqual(
            problem,
            "is already part of br0, which this machine set up for something else. "
            "If you're sure NetTap made it, run sudo ip link set br0 alias nettap "
            "on this machine and try again",
        )


if __name__ == "__main__":
    unittest.main()
