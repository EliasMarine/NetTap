"""
Tests for daemon/services/mirror_manager.py

All tests use mocked nsenter commands and sysfs reads -- no real network
namespace, ip, ethtool, or sysfs access required. Tests cover the MirrorManager
class: mode property, capture interface, setup steps, teardown, health checks,
and sysfs-based statistics.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.mirror_manager import MirrorManager
from services.capture_manager import CaptureHealth, CaptureMode, CaptureStats


def _make_manager(interface="enp2s0", management="enp3s0"):
    """Create a MirrorManager with no persistence dirs."""
    return MirrorManager(
        interface=interface,
        management_interface=management,
        netplan_dir="",
        systemd_dir="",
    )


class TestMirrorManagerMode(unittest.TestCase):
    """Tests for mode property."""

    def test_mode_is_mirror(self):
        """mode property should return CaptureMode.MIRROR."""
        mgr = _make_manager()
        self.assertEqual(mgr.mode, CaptureMode.MIRROR)


class TestGetCaptureInterface(unittest.TestCase):
    """Tests for get_capture_interface()."""

    def test_returns_mirror_interface(self):
        """get_capture_interface() should return the mirror NIC name."""
        mgr = _make_manager(interface="enp2s0")
        self.assertEqual(mgr.get_capture_interface(), "enp2s0")

    def test_returns_custom_interface(self):
        """get_capture_interface() should return whatever interface was configured."""
        mgr = _make_manager(interface="eth5")
        self.assertEqual(mgr.get_capture_interface(), "eth5")


class TestSetup(unittest.TestCase):
    """Tests for setup() — verifies each configuration step."""

    def _track_nsenter(self, mgr):
        """Replace _run_nsenter with a tracker that records all commands and succeeds."""
        commands = []

        async def mock_nsenter(*args):
            commands.append(list(args))
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter
        return commands

    def test_setup_strips_ip(self):
        """setup() should call 'ip addr flush dev <iface>'."""
        mgr = _make_manager(interface="enp2s0")
        commands = self._track_nsenter(mgr)

        asyncio.run(mgr.setup())

        flush_cmds = [
            c for c in commands
            if "addr" in c and "flush" in c and "enp2s0" in c
        ]
        self.assertEqual(len(flush_cmds), 1)

    def test_setup_enables_promisc(self):
        """setup() should call 'ip link set <iface> promisc on'."""
        mgr = _make_manager(interface="enp2s0")
        commands = self._track_nsenter(mgr)

        asyncio.run(mgr.setup())

        promisc_cmds = [
            c for c in commands
            if "promisc" in c and "on" in c
        ]
        self.assertEqual(len(promisc_cmds), 1)

    def test_setup_disables_offloads(self):
        """setup() should call 'ethtool -K <iface> tso off gso off ...'."""
        mgr = _make_manager(interface="enp2s0")
        commands = self._track_nsenter(mgr)

        asyncio.run(mgr.setup())

        ethtool_k_cmds = [
            c for c in commands
            if "ethtool" in c and "-K" in c
        ]
        self.assertEqual(len(ethtool_k_cmds), 1)
        cmd = ethtool_k_cmds[0]
        self.assertIn("tso", cmd)
        self.assertIn("gso", cmd)
        self.assertIn("gro", cmd)
        self.assertIn("lro", cmd)

    def test_setup_increases_ring_buffer(self):
        """setup() should call 'ethtool -G <iface> rx 4096'."""
        mgr = _make_manager(interface="enp2s0")
        commands = self._track_nsenter(mgr)

        asyncio.run(mgr.setup())

        ethtool_g_cmds = [
            c for c in commands
            if "ethtool" in c and "-G" in c
        ]
        self.assertEqual(len(ethtool_g_cmds), 1)
        cmd = ethtool_g_cmds[0]
        self.assertIn("rx", cmd)
        self.assertIn("4096", cmd)

    def test_setup_brings_interface_up(self):
        """setup() should call 'ip link set <iface> up'."""
        mgr = _make_manager(interface="enp2s0")
        commands = self._track_nsenter(mgr)

        asyncio.run(mgr.setup())

        up_cmds = [
            c for c in commands
            if "link" in c and "set" in c and "up" in c
            and "promisc" not in c  # exclude promisc commands
        ]
        self.assertEqual(len(up_cmds), 1)

    def test_setup_returns_success(self):
        """setup() should return success=True when all commands succeed."""
        mgr = _make_manager(interface="enp2s0")
        self._track_nsenter(mgr)

        result = asyncio.run(mgr.setup())

        self.assertTrue(result["success"])
        self.assertEqual(result["interface"], "enp2s0")
        self.assertEqual(result["errors"], [])

    def test_setup_fails_when_interface_not_found(self):
        """setup() should return success=False when interface doesn't exist."""
        mgr = _make_manager(interface="fake0")

        call_count = 0

        async def mock_nsenter(*args):
            nonlocal call_count
            call_count += 1
            # First call is 'ip -j link show <iface>' — fail it
            if call_count == 1:
                return (1, "", "Device does not exist")
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.setup())

        self.assertFalse(result["success"])
        self.assertTrue(len(result["errors"]) >= 1)

    def test_setup_with_persistence_dirs(self):
        """setup() should write persistence files when dirs are configured."""
        import tempfile

        with tempfile.TemporaryDirectory() as netplan_dir, \
             tempfile.TemporaryDirectory() as systemd_dir:
            mgr = MirrorManager(
                interface="enp2s0",
                management_interface="enp3s0",
                netplan_dir=netplan_dir,
                systemd_dir=systemd_dir,
            )

            async def mock_nsenter(*args):
                return (0, "", "")

            mgr._run_nsenter = mock_nsenter

            result = asyncio.run(mgr.setup())

            self.assertTrue(result["success"])
            self.assertTrue(len(result["persistence_files"]) >= 1)


class TestTeardown(unittest.TestCase):
    """Tests for teardown()."""

    def test_teardown_disables_promisc(self):
        """teardown() should call 'ip link set <iface> promisc off'."""
        mgr = _make_manager(interface="enp2s0")
        commands = []

        async def mock_nsenter(*args):
            commands.append(list(args))
            return (0, "", "")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.teardown())

        promisc_off_cmds = [
            c for c in commands
            if "promisc" in c and "off" in c
        ]
        self.assertEqual(len(promisc_off_cmds), 1)
        self.assertTrue(result["torn_down"])

    def test_teardown_returns_error_on_failure(self):
        """teardown() should report errors when promisc off fails."""
        mgr = _make_manager()

        async def mock_nsenter(*args):
            return (1, "", "Operation not permitted")

        mgr._run_nsenter = mock_nsenter

        result = asyncio.run(mgr.teardown())

        self.assertFalse(result["torn_down"])
        self.assertTrue(len(result["errors"]) >= 1)


class TestGetHealth(unittest.TestCase):
    """Tests for get_health() — checks health status mapping."""

    def _setup_health_mocks(self, mgr, operstate="up", carrier="1",
                            flags="0x1103", has_ip=False):
        """Set up sysfs and nsenter mocks for health checks."""
        sysfs_files = {
            "operstate": operstate,
            "carrier": carrier,
            "flags": flags,
        }

        def mock_read_sysfs_file(path):
            basename = os.path.basename(path)
            return sysfs_files.get(basename, "")

        mgr._read_sysfs_file = mock_read_sysfs_file

        # Mock os.path.exists to say interface dir exists
        iface_dir = os.path.join("/host/sys/class/net", mgr._interface)

        # Mock _check_has_ip
        async def mock_check_has_ip():
            return has_ip

        mgr._check_has_ip = mock_check_has_ip

        return iface_dir

    @patch("os.path.exists", return_value=True)
    def test_get_health_normal(self, mock_exists):
        """Normal health: interface up, carrier, promisc, no IP."""
        mgr = _make_manager(interface="enp2s0")
        self._setup_health_mocks(
            mgr, operstate="up", carrier="1", flags="0x1103", has_ip=False
        )

        health = asyncio.run(mgr.get_health())

        self.assertIsInstance(health, CaptureHealth)
        self.assertEqual(health.mode, "mirror")
        self.assertEqual(health.status, "normal")
        self.assertTrue(health.link_up)
        self.assertTrue(health.promisc_enabled)
        self.assertEqual(health.issues, [])

    @patch("os.path.exists", return_value=True)
    def test_get_health_degraded_no_promisc(self, mock_exists):
        """Degraded health: interface up but promisc not enabled."""
        mgr = _make_manager(interface="enp2s0")
        # flags without IFF_PROMISC (0x100) bit
        self._setup_health_mocks(
            mgr, operstate="up", carrier="1", flags="0x1003", has_ip=False
        )

        health = asyncio.run(mgr.get_health())

        self.assertEqual(health.status, "degraded")
        self.assertFalse(health.promisc_enabled)

    @patch("os.path.exists", return_value=True)
    def test_get_health_degraded_has_ip(self, mock_exists):
        """Degraded health: interface up but has an IP address."""
        mgr = _make_manager(interface="enp2s0")
        self._setup_health_mocks(
            mgr, operstate="up", carrier="1", flags="0x1103", has_ip=True
        )

        health = asyncio.run(mgr.get_health())

        self.assertEqual(health.status, "degraded")
        has_ip_issues = [i for i in health.issues if "IP address" in i]
        self.assertTrue(len(has_ip_issues) >= 1)

    @patch("os.path.exists", return_value=True)
    def test_get_health_down(self, mock_exists):
        """Down health: no carrier."""
        mgr = _make_manager(interface="enp2s0")
        self._setup_health_mocks(
            mgr, operstate="down", carrier="0", flags="0x1003", has_ip=False
        )

        health = asyncio.run(mgr.get_health())

        self.assertEqual(health.status, "down")
        self.assertFalse(health.link_up)

    @patch("os.path.exists", return_value=False)
    def test_get_health_not_configured(self, mock_exists):
        """Not configured: interface not found in sysfs."""
        mgr = _make_manager(interface="enp2s0")

        health = asyncio.run(mgr.get_health())

        self.assertEqual(health.status, "not_configured")
        self.assertFalse(health.link_up)
        self.assertFalse(health.promisc_enabled)
        self.assertTrue(len(health.issues) >= 1)


class TestGetStats(unittest.TestCase):
    """Tests for get_stats() — sysfs counter reading."""

    def test_get_stats_reads_sysfs(self):
        """get_stats() should read sysfs counter files and return CaptureStats."""
        mgr = _make_manager(interface="enp2s0")

        sysfs_int_data = {
            "rx_bytes": 500000000,
            "tx_bytes": 100000,
            "rx_packets": 50000,
            "tx_packets": 1000,
            "rx_dropped": 25,
            "rx_missed_errors": 10,
        }

        def mock_read_sysfs_int(path):
            basename = os.path.basename(path)
            return sysfs_int_data.get(basename, 0)

        def mock_read_sysfs_file(path):
            basename = os.path.basename(path)
            if basename == "speed":
                return "2500"
            return "0"

        mgr._read_sysfs_int = mock_read_sysfs_int
        mgr._read_sysfs_file = mock_read_sysfs_file

        stats = asyncio.run(mgr.get_stats())

        self.assertIsInstance(stats, CaptureStats)
        self.assertEqual(stats.capture_interface, "enp2s0")
        self.assertEqual(stats.rx_bytes, 500000000)
        self.assertEqual(stats.tx_bytes, 100000)
        self.assertEqual(stats.rx_packets, 50000)
        self.assertEqual(stats.tx_packets, 1000)
        self.assertEqual(stats.rx_dropped, 25)
        self.assertEqual(stats.rx_missed_errors, 10)
        self.assertEqual(stats.link_speed_mbps, 2500)

    def test_get_stats_calculates_drop_rate(self):
        """get_stats() should calculate drop_rate_pct from rx_dropped / (rx_packets + rx_dropped)."""
        mgr = _make_manager(interface="enp2s0")

        def mock_read_sysfs_int(path):
            basename = os.path.basename(path)
            if basename == "rx_packets":
                return 99000
            if basename == "rx_dropped":
                return 1000
            return 0

        def mock_read_sysfs_file(path):
            return "1000"

        mgr._read_sysfs_int = mock_read_sysfs_int
        mgr._read_sysfs_file = mock_read_sysfs_file

        stats = asyncio.run(mgr.get_stats())

        # MirrorManager: drop_rate = rx_dropped / (rx_packets + rx_dropped) * 100
        # = 1000 / (99000 + 1000) * 100 = 1.0%
        self.assertAlmostEqual(stats.drop_rate_pct, 1.0, places=2)

    def test_get_stats_zero_packets_no_division_error(self):
        """get_stats() should handle zero packets without division by zero."""
        mgr = _make_manager()

        def mock_read_sysfs_int(path):
            return 0

        def mock_read_sysfs_file(path):
            return "0"

        mgr._read_sysfs_int = mock_read_sysfs_int
        mgr._read_sysfs_file = mock_read_sysfs_file

        stats = asyncio.run(mgr.get_stats())

        self.assertAlmostEqual(stats.drop_rate_pct, 0.0)

    def test_get_stats_negative_speed_clamped(self):
        """get_stats() should clamp negative or invalid link speed to 0."""
        mgr = _make_manager()

        def mock_read_sysfs_int(path):
            return 0

        def mock_read_sysfs_file(path):
            basename = os.path.basename(path)
            if basename == "speed":
                return "-1"
            return "0"

        mgr._read_sysfs_int = mock_read_sysfs_int
        mgr._read_sysfs_file = mock_read_sysfs_file

        stats = asyncio.run(mgr.get_stats())

        self.assertEqual(stats.link_speed_mbps, 0)

    def test_get_stats_very_large_speed_clamped(self):
        """get_stats() should clamp unreasonably large link speed to 0."""
        mgr = _make_manager()

        def mock_read_sysfs_int(path):
            return 0

        def mock_read_sysfs_file(path):
            basename = os.path.basename(path)
            if basename == "speed":
                return "999999"
            return "0"

        mgr._read_sysfs_int = mock_read_sysfs_int
        mgr._read_sysfs_file = mock_read_sysfs_file

        stats = asyncio.run(mgr.get_stats())

        self.assertEqual(stats.link_speed_mbps, 0)


if __name__ == "__main__":
    unittest.main()
