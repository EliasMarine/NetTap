"""
Tests for daemon/api/setup.py — POST /api/setup/configure.

Covers mode validation, interface / subnet validation before any write
(CR-165, CR-166), the INI + capture.env written at the reader paths (CR-007),
container restarts only when capture.env changes, and the capture manager
swap (tearing down an active DHCP gateway first, only once the router's DHCP
answers again). Mirror NICs in use are refused. All files go to a temp dir;
container restarts, mirror NIC setup and host ``ip -j`` queries are mocked.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from api.setup import register_setup_routes
from services.bridge_capture_adapter import BridgeCaptureAdapter
from services.capture_config import load_capture_config
from services.capture_manager import CaptureMode
from services.capture_mode_stub import CaptureManagerStub
from services.dhcp_gateway import DhcpGatewayManager

MODULE = "api.setup"
URL = "/api/setup/configure"
DHCP_BODY = {"capture_mode": "dhcp_gateway", "capture_interface": "enp1s0"}
RESTARTED = {"restarted": ["nettap-zeek-live"], "errors": []}
ROUTER_OFFER = {"server_ip": "192.168.1.1", "offered_ip": "192.168.1.77"}
MIRROR_BODY = {"capture_mode": "mirror", "capture_interface": "enp2s0"}


def _active_gateway(interface="enp1s0", subnet="10.77.0.0/24") -> MagicMock:
    """A DhcpGatewayManager stand-in with routing active (router DHCP back on)."""
    mgr = MagicMock(spec=DhcpGatewayManager)
    mgr.mode = CaptureMode.DHCP_GATEWAY
    mgr.routing_active = True
    mgr.get_capture_interface = MagicMock(return_value=interface)
    mgr.probe_other_dhcp = AsyncMock(return_value=([ROUTER_OFFER], ""))
    mgr.status = AsyncMock(return_value={"interface": interface, "subnet": subnet})
    mgr.teardown = AsyncMock(
        return_value={"torn_down": True, "interface": interface, "errors": []}
    )
    return mgr


class _Base(AioHTTPTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        d = self.tmpdir.name
        self.ini = os.path.join(d, "etc", "capture-mode.conf")
        self.capture_env = os.path.join(d, "etc", "capture.env")
        self.legacy_conf = os.path.join(d, "data", "capture-mode.conf")
        self.legacy_env = os.path.join(d, "data", ".env")
        self.restart = AsyncMock(return_value=RESTARTED)
        self.mirror_cls = MagicMock()
        self.mirror_cls.return_value.setup = AsyncMock(return_value={"success": True})
        # Host network as seen by ``ip -j``: {iface: [cidr, ...]} and default routes
        self.host_addrs = {}
        self.host_routes = []
        self.patches = [
            patch.dict(
                os.environ,
                {"CAPTURE_CONFIG_PATH": self.ini, "CAPTURE_ENV_PATH": self.capture_env},
            ),
            patch(f"{MODULE}.CAPTURE_MODE_CONF", self.legacy_conf),
            patch(f"{MODULE}.ENV_FILE", self.legacy_env),
            patch(f"{MODULE}.restart_capture_containers", self.restart),
            patch(f"{MODULE}.MirrorManager", self.mirror_cls),
            patch(
                "services.dhcp_gateway_host.HostNetOps.ip_json",
                side_effect=self._ip_json,
            ),
        ]
        for p in self.patches:
            p.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        for p in reversed(self.patches):
            p.stop()
        self.tmpdir.cleanup()

    async def _ip_json(self, *args):
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
        return await self.client.request("POST", URL, json=body)

    def _read(self, path):
        with open(path) as f:
            return f.read()

    def _nothing_written(self):
        return not any(
            os.path.exists(p)
            for p in (self.ini, self.capture_env, self.legacy_conf, self.legacy_env)
        )


# ---------------------------------------------------------------------------
# Validation (nothing is written on a bad request)
# ---------------------------------------------------------------------------


class TestValidation(_Base):
    async def test_unknown_mode_is_400(self):
        resp = await self._post({"capture_mode": "tap"})
        self.assertEqual(resp.status, 400)
        self.assertIn("dhcp_gateway", (await resp.json())["error"])

    async def test_non_object_body_is_400(self):
        resp = await self._post(["dhcp_gateway"])
        self.assertEqual(resp.status, 400)

    async def test_dhcp_requires_capture_interface(self):
        resp = await self._post({"capture_mode": "dhcp_gateway"})
        self.assertEqual(resp.status, 400)
        self.assertIn("dhcp_gateway mode", (await resp.json())["error"])

    async def test_bad_interface_names_are_400_in_every_mode(self):
        """CR-165: an interface name is validated before anything is written."""
        for body in (
            {**DHCP_BODY, "capture_interface": "eth0;reboot"},
            {**DHCP_BODY, "capture_interface": "enp1s0\nPCAP_FILTER=x"},
            {"capture_mode": "mirror", "capture_interface": "a" * 16},
            {
                "capture_mode": "mirror",
                "capture_interface": "enp2s0",
                "management_interface": "../../etc",
            },
            {"capture_mode": "bridge", "wan_interface": "-x", "lan_interface": "eth1"},
            {"capture_mode": "bridge", "wan_interface": "eth0", "lan_interface": 7},
        ):
            resp = await self._post(body)
            self.assertEqual(resp.status, 400, body)
            self.assertIn(
                "not a valid network interface name", (await resp.json())["error"]
            )
        self.assertTrue(self._nothing_written())
        self.restart.assert_not_awaited()

    async def test_bad_dhcp_subnets_are_400(self):
        """CR-166: the subnet is validated (private, /16-/28, network address)."""
        for subnet in (
            "8.8.8.0/24",
            "10.77.0.0/8",
            "10.77.0.5/24",
            "10.77.0.0",
            "",
            24,
        ):
            resp = await self._post({**DHCP_BODY, "dhcp_subnet": subnet})
            self.assertEqual(resp.status, 400, subnet)
        self.assertTrue(self._nothing_written())


# ---------------------------------------------------------------------------
# Files at the reader paths + restart only on change (CR-007)
# ---------------------------------------------------------------------------


class TestWrites(_Base):
    async def test_dhcp_writes_ini_and_capture_env_at_reader_paths(self):
        resp = await self._post({**DHCP_BODY, "dhcp_subnet": "10.88.0.0/24"})
        self.assertEqual(resp.status, 200)
        data = await resp.json()

        cfg = load_capture_config()  # the path the daemon reads at startup
        self.assertEqual(cfg.mode, CaptureMode.DHCP_GATEWAY)
        self.assertEqual(cfg.interface, "enp1s0")
        self.assertEqual(cfg.dhcp_subnet, "10.88.0.0/24")
        self.assertFalse(cfg.dhcp_enabled)
        self.assertEqual(
            self._read(self.capture_env),
            "CAPTURE_MODE=dhcp_gateway\n"
            "PCAP_IFACE=enp1s0\n"
            "PCAP_FILTER=net 10.88.0.0/24 or udp port 67 or udp port 68\n",
        )
        self.assertIn(self.ini, data["files_written"])
        self.assertIn(self.capture_env, data["files_written"])
        self.assertEqual(data["capture_restart"], RESTARTED)

    async def test_dhcp_subnet_defaults(self):
        resp = await self._post(DHCP_BODY)
        self.assertEqual(resp.status, 200)
        self.assertEqual(load_capture_config().dhcp_subnet, "10.77.0.0/24")

    async def test_legacy_files_still_written(self):
        resp = await self._post(
            {"capture_mode": "mirror", "capture_interface": "enp2s0"}
        )
        self.assertEqual(resp.status, 200)
        self.assertIn("CAPTURE_MODE=mirror", self._read(self.legacy_conf))
        self.assertIn("CAPTURE_INTERFACE=enp2s0", self._read(self.legacy_env))
        self.assertEqual(
            self._read(self.capture_env),
            "CAPTURE_MODE=mirror\nPCAP_IFACE=enp2s0\nPCAP_FILTER=\n",
        )

    async def test_restart_only_when_capture_env_changes(self):
        resp = await self._post(DHCP_BODY)
        self.assertEqual((await resp.json())["capture_restart"], RESTARTED)
        self.assertEqual(self.restart.await_count, 1)

        resp = await self._post(DHCP_BODY)  # same content
        self.assertEqual(
            (await resp.json())["capture_restart"], {"restarted": [], "errors": []}
        )
        self.assertEqual(self.restart.await_count, 1)

        resp = await self._post({**DHCP_BODY, "capture_interface": "enp2s0"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.restart.await_count, 2)


# ---------------------------------------------------------------------------
# Capture manager swap
# ---------------------------------------------------------------------------


class TestManagerSwap(_Base):
    async def test_swaps_to_each_mode(self):
        await self._post(DHCP_BODY)
        mgr = self.app["capture_manager"]
        self.assertIsInstance(mgr, DhcpGatewayManager)
        self.assertFalse(mgr.routing_active)  # configure never enables

        await self._post({"capture_mode": "mirror", "capture_interface": "enp2s0"})
        self.assertIs(self.app["capture_manager"], self.mirror_cls.return_value)
        self.mirror_cls.assert_called_once_with(
            interface="enp2s0", management_interface=""
        )
        self.mirror_cls.return_value.setup.assert_awaited_once()

        await self._post(
            {"capture_mode": "bridge", "wan_interface": "eth0", "lan_interface": "eth1"}
        )
        self.assertIsInstance(self.app["capture_manager"], CaptureManagerStub)
        self.assertEqual(self.app["capture_manager"].mode, CaptureMode.BRIDGE)

    async def test_leaving_active_gateway_tears_it_down_first(self):
        gateway = _active_gateway()

        def check_not_yet_written():
            self.assertFalse(os.path.exists(self.ini))
            return {"torn_down": True, "interface": "enp1s0", "errors": []}

        gateway.teardown.side_effect = check_not_yet_written
        self.app["capture_manager"] = gateway
        resp = await self._post(
            {"capture_mode": "mirror", "capture_interface": "enp2s0"}
        )
        self.assertEqual(resp.status, 200)
        gateway.teardown.assert_awaited_once()
        self.assertEqual((await resp.json())["dhcp_teardown"]["torn_down"], True)
        self.assertEqual(load_capture_config().mode, CaptureMode.MIRROR)
        self.assertIs(self.app["capture_manager"], self.mirror_cls.return_value)

    async def test_bridge_keeps_live_bridge_adapter(self):
        adapter = MagicMock(spec=BridgeCaptureAdapter)
        adapter.mode = CaptureMode.BRIDGE
        self.app["capture_manager"] = adapter
        resp = await self._post(
            {"capture_mode": "bridge", "wan_interface": "eth0", "lan_interface": "eth1"}
        )
        self.assertEqual(resp.status, 200)
        self.assertIs(self.app["capture_manager"], adapter)

    async def test_inactive_gateway_is_not_torn_down(self):
        gateway = _active_gateway()
        gateway.routing_active = False
        self.app["capture_manager"] = gateway
        resp = await self._post(
            {"capture_mode": "bridge", "wan_interface": "eth0", "lan_interface": "eth1"}
        )
        self.assertEqual(resp.status, 200)
        gateway.teardown.assert_not_awaited()
        self.assertNotIn("dhcp_teardown", await resp.json())

    async def test_same_active_gateway_is_kept(self):
        """Re-running the wizard must not drop the live gateway's state or dnsmasq."""
        gateway = _active_gateway()
        self.app["capture_manager"] = gateway
        resp = await self._post(DHCP_BODY)
        self.assertEqual(resp.status, 200)
        self.assertIs(self.app["capture_manager"], gateway)
        gateway.teardown.assert_not_awaited()
        self.assertFalse(os.path.exists(self.ini))  # its saved state is untouched

    async def test_changing_live_gateway_subnet_is_409(self):
        gateway = _active_gateway()
        self.app["capture_manager"] = gateway
        resp = await self._post({**DHCP_BODY, "dhcp_subnet": "10.88.0.0/24"})
        self.assertEqual(resp.status, 409)
        self.assertIn(
            "switch NetTap to another capture mode", (await resp.json())["error"]
        )
        self.assertIs(self.app["capture_manager"], gateway)
        gateway.teardown.assert_not_awaited()
        self.assertTrue(self._nothing_written())

    async def test_write_failure_is_500(self):
        with patch(f"{MODULE}.save_capture_config", side_effect=OSError("read-only")):
            resp = await self._post(DHCP_BODY)
        self.assertEqual(resp.status, 500)
        self.assertIn("read-only", (await resp.json())["error"])
        self.restart.assert_not_awaited()


# ---------------------------------------------------------------------------
# Leaving an active gateway: only once another DHCP server answers
# ---------------------------------------------------------------------------


class TestLeavingActiveGateway(_Base):
    async def _assert_refused(self, resp, gateway, fragment):
        self.assertEqual(resp.status, 409)
        error = (await resp.json())["error"]
        self.assertIn("Turn your router's DHCP server back on first", error)
        self.assertIn(fragment, error)
        gateway.probe_other_dhcp.assert_awaited_once()
        gateway.teardown.assert_not_awaited()
        self.assertIs(self.app["capture_manager"], gateway)
        self.assertTrue(self._nothing_written())
        self.restart.assert_not_awaited()

    async def test_refused_while_no_other_dhcp_server_answers(self):
        gateway = _active_gateway()
        gateway.probe_other_dhcp.return_value = ([], "")
        self.app["capture_manager"] = gateway
        resp = await self._post(
            {"capture_mode": "bridge", "wan_interface": "eth0", "lan_interface": "eth1"}
        )
        await self._assert_refused(resp, gateway, "enp1s0")

    async def test_refused_when_probe_fails(self):
        gateway = _active_gateway()
        gateway.probe_other_dhcp.return_value = ([], "Operation not permitted")
        self.app["capture_manager"] = gateway
        resp = await self._post(MIRROR_BODY)
        await self._assert_refused(resp, gateway, "Operation not permitted")

    async def test_proceeds_once_router_answers(self):
        gateway = _active_gateway()
        self.app["capture_manager"] = gateway
        resp = await self._post(MIRROR_BODY)
        self.assertEqual(resp.status, 200)
        gateway.probe_other_dhcp.assert_awaited_once()
        gateway.teardown.assert_awaited_once()

    async def test_same_gateway_needs_no_probe(self):
        gateway = _active_gateway()
        gateway.probe_other_dhcp.return_value = ([], "")
        self.app["capture_manager"] = gateway
        resp = await self._post(DHCP_BODY)
        self.assertEqual(resp.status, 200)
        gateway.probe_other_dhcp.assert_not_awaited()


# ---------------------------------------------------------------------------
# Mirror NIC must be spare (mirror setup flushes its addresses)
# ---------------------------------------------------------------------------


class TestMirrorNicInUse(_Base):
    async def _assert_refused(self, resp, fragment):
        self.assertEqual(resp.status, 400)
        error = (await resp.json())["error"]
        self.assertIn("enp2s0", error)
        self.assertIn(fragment, error)
        self.assertTrue(self._nothing_written())
        self.mirror_cls.assert_not_called()
        self.restart.assert_not_awaited()

    async def test_refused_when_nic_has_an_address(self):
        self.host_addrs["enp2s0"] = ["192.168.1.60/24"]
        await self._assert_refused(await self._post(MIRROR_BODY), "192.168.1.60")

    async def test_refused_when_nic_carries_default_route(self):
        self.host_routes = [
            {"dst": "default", "gateway": "192.168.1.1", "dev": "enp2s0"}
        ]
        await self._assert_refused(await self._post(MIRROR_BODY), "default route")

    async def test_refused_on_the_live_gateway_nic(self):
        gateway = _active_gateway(interface="enp2s0")
        self.app["capture_manager"] = gateway
        await self._assert_refused(
            await self._post(MIRROR_BODY), "DHCP gateway mode is routing"
        )
        gateway.teardown.assert_not_awaited()
        gateway.probe_other_dhcp.assert_not_awaited()

    async def test_spare_nic_is_accepted(self):
        self.host_addrs["enp1s0"] = ["192.168.1.50/24"]
        self.host_routes = [
            {"dst": "default", "gateway": "192.168.1.1", "dev": "enp1s0"}
        ]
        resp = await self._post(MIRROR_BODY)
        self.assertEqual(resp.status, 200)
        self.mirror_cls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
