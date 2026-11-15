"""
NET-287: NetTap never adopts, retunes or deletes a bridge called br0 that it didn't make.

A br0 is NetTap's when its alias is "nettap", or (a bridge netplan rebuilt from NetTap's
file at boot) when it has ports, every one is listed in 10-nettap-bridge.yaml, and it has
no global address and no default route. Host state is faked: a tmp sysfs, a tmp netplan
dir, HostNetOps.ip_json (addresses) and HostNetOps._run_nsenter (routes).
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.bridge_health import BridgeHealthMonitor
from services.bridge_manager import BridgeManager, bridge_is_nettaps

NETPLAN = """network:
  bridges:
    br0:
      interfaces:
        - enp2s0
        - enp3s0
"""
GLOBAL_ADDR = {
    "family": "inet",
    "local": "192.168.1.5",
    "prefixlen": 24,
    "scope": "global",
}
CHANGING = (("ip", "link", "set"), ("ip", "link", "add"), ("ip", "link", "del"))


class OwnershipCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sysfs = os.path.join(self.tmp, "sys")
        self.netplan_dir = os.path.join(self.tmp, "netplan")
        os.makedirs(os.path.join(self.sysfs, "br0", "brif"))
        os.makedirs(self.netplan_dir)
        self.addr_info = []
        self.addr_readable = True
        self.routes = {"-4": (0, "[]\n"), "-6": (0, "[]\n")}
        self.alias_rc = 0
        self.commands = []
        for p in (
            patch("services.bridge_manager._SYSFS_NET", self.sysfs),
            patch(
                "services.dhcp_gateway_host.HostNetOps.ip_json",
                side_effect=self._ip_json,
            ),
            patch(
                "services.dhcp_gateway_host.HostNetOps._run_nsenter",
                side_effect=self._host_run,
            ),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    # -- fake host --------------------------------------------------------
    async def _ip_json(self, *args):
        if args == ("addr", "show", "dev", "br0") and self.addr_readable:
            return [{"ifname": "br0", "addr_info": self.addr_info}]
        return []

    async def _host_run(self, *args):
        family = args[2] if args[:2] == ("ip", "-j") and "route" in args else None
        rc, out = self.routes.get(family, (1, ""))
        return rc, out, ""

    async def _mgr_run(self, *args):
        self.commands.append(args)
        if args == ("ip", "link", "show", "br0"):
            return (0, "", "")  # br0 exists
        if args[-2:] == ("alias", "nettap"):
            return (self.alias_rc, "", "RTNETLINK answers: Operation not permitted")
        return (0, "", "")

    def ports(self, *names):
        for name in names:
            os.makedirs(os.path.join(self.sysfs, "br0", "brif", name))

    def netplan(self, text=NETPLAN):
        with open(os.path.join(self.netplan_dir, "10-nettap-bridge.yaml"), "w") as f:
            f.write(text)

    def alias(self):
        with open(os.path.join(self.sysfs, "br0", "ifalias"), "w") as f:
            f.write("nettap\n")

    def manager(self, netplan_dir=None):
        mgr = BridgeManager()
        mgr._netplan_dir = self.netplan_dir if netplan_dir is None else netplan_dir
        mgr._run_nsenter = self._mgr_run
        return mgr

    def changing(self):
        return [
            c
            for c in self.commands
            if c[:3] in CHANGING or c[0] in ("sysctl", "ethtool")
        ]

    def create(self, mgr=None):
        return asyncio.run(
            (mgr or self.manager()).create_bridge("enp2s0", "enp3s0", persist=False)
        )

    def assert_refused(self, result):
        self.assertFalse(result["created"])
        self.assertIn("didn't set up", result["errors"][0])
        self.assertIn("sudo ip link set br0 alias nettap", result["errors"][0])
        self.assertEqual(self.changing(), [], "a foreign bridge must not be touched")


class TestCreateRefusesForeignBridge(OwnershipCase):
    def test_no_alias_and_no_netplan_file(self):
        self.ports("enp1s0", "vnet0")
        self.assert_refused(self.create())

    def test_a_port_missing_from_netplan_file(self):
        self.netplan()
        self.ports("enp2s0", "vnet0")
        self.assert_refused(self.create())

    def test_empty_bridge_next_to_matching_file(self):
        self.netplan()
        self.assert_refused(self.create())

    def test_host_uplink_bridge_whose_port_matches_a_stale_file(self):
        self.netplan()
        self.ports("enp2s0")
        self.addr_info = [GLOBAL_ADDR]
        self.assert_refused(self.create())

    def test_default_route_via_the_bridge(self):
        self.netplan()
        self.ports("enp2s0")
        self.routes["-6"] = (0, json.dumps([{"dst": "default", "dev": "br0"}]))
        self.assert_refused(self.create())

    def test_route_command_that_fails(self):
        self.netplan()
        self.ports("enp2s0")
        self.routes["-4"] = (1, "")
        self.assert_refused(self.create())

    def test_malformed_route_json(self):
        self.netplan()
        self.ports("enp2s0")
        self.routes["-4"] = (0, "not json")
        self.assert_refused(self.create())

    def test_unreadable_address_list(self):
        self.netplan()
        self.ports("enp2s0")
        self.addr_readable = False
        self.assert_refused(self.create())

    def test_empty_netplan_dir_never_reads_the_working_dir(self):
        self.ports("enp2s0")
        cwd = os.getcwd()
        os.chdir(self.netplan_dir)
        self.addCleanup(os.chdir, cwd)
        self.netplan()  # a matching file in the working dir must not count
        with patch.dict(os.environ, {"HOST_NETPLAN_DIR": ""}):
            self.assert_refused(self.create(self.manager(netplan_dir="")))


class TestCreateOnNetTapsBridge(OwnershipCase):
    def assert_reconfigured(self, result):
        self.assertTrue(result["created"], result["errors"])
        self.assertEqual(result["state"], "reconfigured")
        cmds = [" ".join(c) for c in self.changing()]
        # The alias comes before any port or setting change
        self.assertEqual(cmds[0], "ip link set br0 alias nettap")
        self.assertIn("ip link set enp2s0 nomaster", cmds)

    def test_alias(self):
        self.alias()
        self.ports(
            "enp1s0", "vnet0"
        )  # its ports don't matter once it carries the alias
        self.assert_reconfigured(self.create())

    def test_legacy_bridge_rebuilt_from_netplan(self):
        self.netplan()
        self.ports("enp2s0", "enp3s0")
        self.assert_reconfigured(self.create())

    def test_legacy_bridge_when_ip_prints_nothing_for_no_routes(self):
        self.netplan()
        self.ports("enp2s0")
        self.routes = {"-4": (0, ""), "-6": (0, "")}
        self.assert_reconfigured(self.create())

    def test_management_address_lines_are_not_ports(self):
        self.netplan(
            NETPLAN + "    enp1s0:\n      addresses:\n        - 192.0.2.10/24\n"
        )
        self.ports("enp2s0")
        self.assert_reconfigured(self.create())

    def test_alias_failure_on_reconfigure_changes_nothing(self):
        self.alias()
        self.alias_rc = 1
        result = self.create()
        self.assertFalse(result["created"])
        self.assertIn("Could not mark br0", result["errors"][0])
        self.assertEqual(
            [" ".join(c) for c in self.changing()], ["ip link set br0 alias nettap"]
        )


class TestNewBridgeAlias(unittest.TestCase):
    def _create(self, alias_rc, del_rc=0):
        commands = []

        async def run(*args):
            commands.append(" ".join(args))
            if args == ("ip", "link", "show", "br0"):
                return (1, "", 'Device "br0" does not exist.')
            if args[-2:] == ("alias", "nettap"):
                return (alias_rc, "", "boom")
            if args == ("ip", "link", "del", "br0"):
                return (del_rc, "", "busy")
            return (0, "", "")

        mgr = BridgeManager(netplan_dir="")
        mgr._run_nsenter = run
        result = asyncio.run(mgr.create_bridge("enp2s0", "enp3s0", persist=False))
        changing = [
            c
            for c in commands
            if c.startswith(("ip link set", "ip link add", "ip link del"))
        ]
        return result, changing

    def test_alias_is_set_right_after_creation(self):
        result, changing = self._create(alias_rc=0)
        self.assertTrue(result["created"])
        self.assertEqual(
            changing[:2],
            ["ip link add br0 type bridge", "ip link set br0 alias nettap"],
        )

    def test_alias_failure_deletes_only_the_bridge_just_made(self):
        result, changing = self._create(alias_rc=1)
        self.assertFalse(result["created"])
        self.assertEqual(
            changing,
            [
                "ip link add br0 type bridge",
                "ip link set br0 alias nettap",
                "ip link del br0",
            ],
        )

    def test_failed_cleanup_says_the_bridge_may_remain(self):
        result, _ = self._create(alias_rc=1, del_rc=1)
        self.assertFalse(result["created"])
        self.assertIn("may still exist", result["errors"][0])
        self.assertIn("sudo ip link del br0", result["errors"][0])
        self.assertNotIn("Nothing was changed", result["errors"][0])


class TestTeardownAndReadiness(OwnershipCase):
    def test_teardown_refuses_a_foreign_bridge(self):
        self.ports("enp1s0")
        result = asyncio.run(self.manager().teardown_bridge())
        self.assertFalse(result["torn_down"])
        self.assertIn("won't remove it", result["errors"][0])
        self.assertIn("sudo ip link set br0 alias nettap", result["errors"][0])
        self.assertEqual(self.changing(), [])
        self.assertFalse(any("master" in c for c in self.commands))

    def test_readiness_does_not_count_a_foreign_bridge(self):
        self.ports("enp1s0")
        result = asyncio.run(self.manager().check_readiness())
        self.assertFalse(result["ready"])
        self.assertEqual(result["checks"][0]["name"], "bridge_exists")
        self.assertFalse(result["checks"][0]["passed"])
        self.assertIn("didn't set up", result["message"])
        self.assertEqual(len(result["checks"]), 8)

    def test_readiness_counts_netTaps_bridge(self):
        self.alias()
        result = asyncio.run(self.manager().check_readiness())
        self.assertTrue(result["checks"][0]["passed"])


class TestBypassRefusesForeignBridge(OwnershipCase):
    def monitor(self, active):
        monitor = BridgeHealthMonitor()
        monitor._bypass_active = active
        writes, calls = [], []
        monitor._write_bypass_file = lambda active: writes.append(active)

        async def run(*args):
            calls.append(args)
            return (0, "", "")

        monitor._run_nsenter = run
        return monitor, writes, calls

    def _refused(self, method, active):
        self.ports("enp1s0", "vnet0")
        monitor, writes, calls = self.monitor(active)
        with patch("services.bridge_health._SYSFS_NET", self.sysfs):
            result = asyncio.run(getattr(monitor, method)())
        self.assertIn("bypass mode can't change it", result["error"])
        self.assertIn("sudo ip link set br0 alias nettap", result["error"])
        self.assertEqual(monitor._bypass_active, active)  # flag unchanged
        self.assertEqual((writes, calls), ([], []))  # no state file, no promisc

    def test_enable(self):
        self._refused("trigger_bypass", active=False)

    def test_disable(self):
        self._refused("disable_bypass", active=True)

    def test_netTaps_bridge_still_bypasses(self):
        self.alias()
        monitor, writes, calls = self.monitor(False)
        with patch("services.bridge_health._SYSFS_NET", self.sysfs):
            result = asyncio.run(monitor.trigger_bypass())
        self.assertTrue(result["bypass_active"])
        self.assertEqual(writes, [True])


class TestBridgeIsNetTaps(OwnershipCase):
    def test_missing_netplan_file(self):
        self.ports("enp2s0")
        self.assertFalse(asyncio.run(bridge_is_nettaps("br0", self.netplan_dir)))

    def test_missing_bridge(self):
        self.netplan()
        self.assertFalse(asyncio.run(bridge_is_nettaps("br7", self.netplan_dir)))

    def test_undecodable_netplan_file_refuses(self):
        self.ports("enp2s0")
        with open(os.path.join(self.netplan_dir, "10-nettap-bridge.yaml"), "wb") as f:
            f.write(b"\xff\xfe        - enp2s0\n")
        self.assertFalse(asyncio.run(bridge_is_nettaps("br0", self.netplan_dir)))


if __name__ == "__main__":
    unittest.main()
