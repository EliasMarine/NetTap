"""Tests for NIC discovery API endpoint."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.nic_discovery import (
    _classify_type,
    _get_speed,
    _read_sysfs,
    _should_exclude,
    discover_interfaces,
    register_nic_discovery_routes,
)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestShouldExclude(unittest.TestCase):
    def test_docker_interface(self):
        self.assertTrue(_should_exclude("docker0"))

    def test_veth_interface(self):
        self.assertTrue(_should_exclude("vethab12cd"))

    def test_bridge_prefix(self):
        self.assertTrue(_should_exclude("br-abc123"))

    def test_virbr(self):
        self.assertTrue(_should_exclude("virbr0"))

    def test_normal_eth(self):
        self.assertFalse(_should_exclude("eth0"))

    def test_normal_wlan(self):
        self.assertFalse(_should_exclude("wlan0"))

    def test_enp_name(self):
        self.assertFalse(_should_exclude("enp3s0"))


class TestReadSysfs(unittest.TestCase):
    def test_reads_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "speed"
            p.write_text("2500\n")
            self.assertEqual(_read_sysfs(p), "2500")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nonexistent"
            self.assertEqual(_read_sysfs(p), "")


class TestGetSpeed(unittest.TestCase):
    def _make(self, name, content):
        d = Path(self._tmpdir) / name
        d.mkdir(exist_ok=True)
        (d / "speed").write_text(content)
        return Path(self._tmpdir)

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._tmpdir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_gigabit(self):
        p = self._make("eth0", "1000\n")
        self.assertEqual(_get_speed(p, "eth0"), "1Gb/s")

    def test_2500mbps(self):
        p = self._make("eth0", "2500\n")
        self.assertEqual(_get_speed(p, "eth0"), "2.5Gb/s")

    def test_100mbps(self):
        p = self._make("eth0", "100\n")
        self.assertEqual(_get_speed(p, "eth0"), "100Mb/s")

    def test_link_down(self):
        p = self._make("eth0", "-1\n")
        self.assertEqual(_get_speed(p, "eth0"), "")


class TestClassifyType(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._tmpdir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_loopback(self):
        self.assertEqual(_classify_type(self._tmpdir, "lo"), "loopback")

    def test_wireless(self):
        (self._tmpdir / "wlan0").mkdir()
        (self._tmpdir / "wlan0" / "wireless").mkdir()
        self.assertEqual(_classify_type(self._tmpdir, "wlan0"), "wireless")

    def test_virtual_no_device(self):
        (self._tmpdir / "tun0").mkdir()
        self.assertEqual(_classify_type(self._tmpdir, "tun0"), "virtual")

    def test_ethernet_with_device(self):
        (self._tmpdir / "eth0").mkdir()
        (self._tmpdir / "eth0" / "device").mkdir()
        (self._tmpdir / "eth0" / "type").write_text("1\n")
        self.assertEqual(_classify_type(self._tmpdir, "eth0"), "ethernet")


# ---------------------------------------------------------------------------
# Integration test: discover_interfaces with fake sysfs
# ---------------------------------------------------------------------------


def _create_fake_sysfs(root: Path) -> Path:
    """Build a fake /sys/class/net tree with 2 ethernet + 1 wireless + lo."""
    sys_net = root / "sys" / "class" / "net"
    sys_net.mkdir(parents=True)

    eth0 = sys_net / "eth0"
    eth0.mkdir()
    (eth0 / "address").write_text("a8:a1:59:c2:0e:01\n")
    (eth0 / "operstate").write_text("up\n")
    (eth0 / "speed").write_text("2500\n")
    (eth0 / "type").write_text("1\n")
    (eth0 / "device").mkdir()

    eth1 = sys_net / "eth1"
    eth1.mkdir()
    (eth1 / "address").write_text("a8:a1:59:c2:0e:02\n")
    (eth1 / "operstate").write_text("down\n")
    (eth1 / "speed").write_text("-1\n")
    (eth1 / "type").write_text("1\n")
    (eth1 / "device").mkdir()

    wlan0 = sys_net / "wlan0"
    wlan0.mkdir()
    (wlan0 / "address").write_text("b4:6b:fc:d3:12:ab\n")
    (wlan0 / "operstate").write_text("up\n")
    (wlan0 / "speed").write_text("-1\n")
    (wlan0 / "type").write_text("1\n")
    (wlan0 / "device").mkdir()
    (wlan0 / "wireless").mkdir()

    lo = sys_net / "lo"
    lo.mkdir()
    (lo / "address").write_text("00:00:00:00:00:00\n")
    (lo / "operstate").write_text("unknown\n")
    (lo / "type").write_text("772\n")

    docker0 = sys_net / "docker0"
    docker0.mkdir()
    (docker0 / "address").write_text("02:42:ab:cd:ef:01\n")
    (docker0 / "operstate").write_text("down\n")

    return sys_net


class TestDiscoverInterfaces(AioHTTPTestCase):
    """discover_interfaces reads from a fake sysfs tree and returns correct data."""

    async def get_application(self):
        app = web.Application()
        register_nic_discovery_routes(app)
        return app

    @unittest_run_loop
    async def test_discovers_real_interfaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sys_net = _create_fake_sysfs(Path(tmpdir))

            mock_ipv4 = {"wlan0": "192.168.1.50"}
            with patch("api.nic_discovery._get_ipv4_map", new_callable=AsyncMock, return_value=mock_ipv4):
                with patch("api.nic_discovery._get_sys_net_path", return_value=sys_net):
                    result = await discover_interfaces()

        names = [i["name"] for i in result]
        self.assertIn("eth0", names)
        self.assertIn("eth1", names)
        self.assertIn("wlan0", names)
        self.assertIn("lo", names)
        self.assertNotIn("docker0", names)

        eth0 = next(i for i in result if i["name"] == "eth0")
        self.assertEqual(eth0["mac"], "a8:a1:59:c2:0e:01")
        self.assertEqual(eth0["state"], "up")
        self.assertEqual(eth0["speed"], "2.5Gb/s")
        self.assertEqual(eth0["type"], "ethernet")

        wlan0 = next(i for i in result if i["name"] == "wlan0")
        self.assertEqual(wlan0["type"], "wireless")
        self.assertEqual(wlan0.get("ipv4"), "192.168.1.50")


# ---------------------------------------------------------------------------
# HTTP endpoint test
# ---------------------------------------------------------------------------


class TestNicListEndpoint(AioHTTPTestCase):
    """GET /api/setup/nics returns JSON with interfaces array."""

    async def get_application(self):
        app = web.Application()
        register_nic_discovery_routes(app)
        return app

    @unittest_run_loop
    async def test_returns_interfaces(self):
        mock_ifaces = [
            {"name": "eth0", "mac": "aa:bb:cc:dd:ee:ff", "state": "up",
             "speed": "2.5Gb/s", "driver": "igc", "type": "ethernet"},
        ]
        with patch("api.nic_discovery.discover_interfaces", new_callable=AsyncMock, return_value=mock_ifaces):
            resp = await self.client.request("GET", "/api/setup/nics")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data["source"], "daemon")
            self.assertEqual(len(data["interfaces"]), 1)
            self.assertEqual(data["interfaces"][0]["name"], "eth0")

    @unittest_run_loop
    async def test_empty_when_no_interfaces(self):
        with patch("api.nic_discovery.discover_interfaces", new_callable=AsyncMock, return_value=[]):
            resp = await self.client.request("GET", "/api/setup/nics")
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data["interfaces"], [])


if __name__ == "__main__":
    unittest.main()
