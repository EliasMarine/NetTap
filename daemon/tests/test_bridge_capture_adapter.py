"""
Tests for daemon/services/bridge_capture_adapter.py

All tests use mocked BridgeManager and BridgeHealthMonitor -- no real sysfs,
nsenter, or network access required. Tests cover the BridgeCaptureAdapter class:
mode property, capture interface, setup/teardown delegation, health mapping,
and sysfs-based statistics.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.bridge_capture_adapter import BridgeCaptureAdapter
from services.capture_manager import CaptureHealth, CaptureMode, CaptureStats


def _make_adapter(bridge_name="br0", wan="enp2s0", lan="enp3s0"):
    """Create a BridgeCaptureAdapter with mocked dependencies."""
    bridge_manager = MagicMock()
    bridge_health = MagicMock()
    return BridgeCaptureAdapter(
        bridge_manager=bridge_manager,
        bridge_health=bridge_health,
        wan_iface=wan,
        lan_iface=lan,
        bridge_name=bridge_name,
    )


class TestBridgeCaptureAdapterMode(unittest.TestCase):
    """Tests for mode property."""

    def test_mode_is_bridge(self):
        """mode property should return CaptureMode.BRIDGE."""
        adapter = _make_adapter()
        self.assertEqual(adapter.mode, CaptureMode.BRIDGE)


class TestGetCaptureInterface(unittest.TestCase):
    """Tests for get_capture_interface()."""

    def test_returns_bridge_name(self):
        """get_capture_interface() should return the bridge name."""
        adapter = _make_adapter(bridge_name="br0")
        self.assertEqual(adapter.get_capture_interface(), "br0")

    def test_returns_custom_bridge_name(self):
        """get_capture_interface() should return custom bridge name."""
        adapter = _make_adapter(bridge_name="br1")
        self.assertEqual(adapter.get_capture_interface(), "br1")


class TestSetup(unittest.TestCase):
    """Tests for setup() delegation."""

    def test_setup_delegates_to_bridge_manager(self):
        """setup() should call bridge_manager.create_bridge(wan, lan)."""
        adapter = _make_adapter(wan="enp2s0", lan="enp3s0")
        adapter._bridge_manager.create_bridge = AsyncMock(
            return_value={"created": True, "bridge_name": "br0"}
        )

        result = asyncio.run(adapter.setup())

        adapter._bridge_manager.create_bridge.assert_called_once_with(
            wan="enp2s0", lan="enp3s0"
        )
        self.assertTrue(result["created"])

    def test_setup_returns_bridge_manager_result(self):
        """setup() should return the dict from bridge_manager.create_bridge()."""
        adapter = _make_adapter()
        expected = {
            "created": True,
            "bridge_name": "br0",
            "wan": "enp2s0",
            "lan": "enp3s0",
            "errors": [],
            "warnings": [],
        }
        adapter._bridge_manager.create_bridge = AsyncMock(return_value=expected)

        result = asyncio.run(adapter.setup())
        self.assertEqual(result, expected)


class TestTeardown(unittest.TestCase):
    """Tests for teardown() delegation."""

    def test_teardown_delegates_to_bridge_manager(self):
        """teardown() should call bridge_manager.teardown_bridge()."""
        adapter = _make_adapter()
        adapter._bridge_manager.teardown_bridge = AsyncMock(
            return_value={"torn_down": True, "errors": []}
        )

        result = asyncio.run(adapter.teardown())

        adapter._bridge_manager.teardown_bridge.assert_called_once()
        self.assertTrue(result["torn_down"])


class TestGetHealthMapping(unittest.TestCase):
    """Tests for get_health() mapping bridge health to CaptureHealth."""

    def _make_health_dict(self, **overrides):
        """Create a typical bridge health dict with overridable fields."""
        defaults = {
            "bridge_state": "up",
            "wan_link": True,
            "lan_link": True,
            "bypass_active": False,
            "watchdog_active": True,
            "latency_us": 50.0,
            "rx_bytes_delta": 1000,
            "tx_bytes_delta": 2000,
            "rx_packets_delta": 10,
            "tx_packets_delta": 20,
            "uptime_seconds": 3600.0,
            "health_status": "normal",
            "issues": [],
            "last_check": "2026-03-08T12:00:00+00:00",
        }
        defaults.update(overrides)
        return defaults

    def _run_health(self, adapter, health_dict):
        """Helper to run get_health() with a mocked health dict."""
        adapter._bridge_health.check_health = AsyncMock(return_value=health_dict)
        return asyncio.run(adapter.get_health())

    def test_get_health_normal(self):
        """When bridge reports normal, CaptureHealth should reflect that."""
        adapter = _make_adapter()
        health = self._run_health(adapter, self._make_health_dict())

        self.assertIsInstance(health, CaptureHealth)
        self.assertEqual(health.mode, "bridge")
        self.assertEqual(health.status, "normal")
        self.assertEqual(health.capture_interface, "br0")
        self.assertTrue(health.link_up)
        self.assertTrue(health.promisc_enabled)
        self.assertEqual(health.issues, [])

    def test_get_health_degraded(self):
        """When bridge reports degraded, CaptureHealth should reflect degraded."""
        adapter = _make_adapter()
        health = self._run_health(
            adapter,
            self._make_health_dict(
                health_status="degraded",
                wan_link=False,
                issues=["WAN link down"],
            ),
        )

        self.assertEqual(health.status, "degraded")
        self.assertIn("WAN link down", health.issues)

    def test_get_health_down(self):
        """When bridge state is down, link_up should be False."""
        adapter = _make_adapter()
        health = self._run_health(
            adapter,
            self._make_health_dict(
                bridge_state="down",
                health_status="down",
                wan_link=False,
                lan_link=False,
            ),
        )

        self.assertEqual(health.status, "down")
        self.assertFalse(health.link_up)

    def test_get_health_not_configured(self):
        """When bridge reports not_configured, status should match."""
        adapter = _make_adapter()
        health = self._run_health(
            adapter,
            self._make_health_dict(
                bridge_state="not_configured",
                health_status="not_configured",
                wan_link=False,
                lan_link=False,
            ),
        )

        self.assertEqual(health.status, "not_configured")
        self.assertFalse(health.link_up)

    def test_get_health_bypass_disables_promisc(self):
        """When bypass is active, promisc_enabled should be False."""
        adapter = _make_adapter()
        health = self._run_health(
            adapter,
            self._make_health_dict(bypass_active=True),
        )

        self.assertFalse(health.promisc_enabled)

    def test_get_health_maps_bridge_health(self):
        """get_health() should populate extra dict with bridge-specific fields."""
        adapter = _make_adapter(wan="enp2s0", lan="enp3s0")
        health = self._run_health(adapter, self._make_health_dict())

        d = health.to_dict()
        self.assertEqual(d["wan_iface"], "enp2s0")
        self.assertEqual(d["lan_iface"], "enp3s0")
        self.assertTrue(d["wan_link"])
        self.assertTrue(d["lan_link"])
        self.assertFalse(d["bypass_active"])
        self.assertTrue(d["watchdog_active"])
        self.assertAlmostEqual(d["latency_us"], 50.0)


class TestGetStats(unittest.TestCase):
    """Tests for get_stats() sysfs reading."""

    def test_get_stats_reads_sysfs(self):
        """get_stats() should read sysfs counter files and return CaptureStats."""
        adapter = _make_adapter(bridge_name="br0")

        # Map of sysfs file paths to their contents
        sysfs_data = {
            "rx_bytes": "123456789",
            "tx_bytes": "987654321",
            "rx_packets": "100000",
            "tx_packets": "80000",
            "rx_dropped": "10",
            "rx_missed_errors": "5",
        }

        def mock_read_sysfs_int(path):
            basename = os.path.basename(path)
            if basename == "speed":
                return 2500
            return int(sysfs_data.get(basename, "0"))

        adapter._read_sysfs_int = mock_read_sysfs_int

        stats = asyncio.run(adapter.get_stats())

        self.assertIsInstance(stats, CaptureStats)
        self.assertEqual(stats.capture_interface, "br0")
        self.assertEqual(stats.rx_bytes, 123456789)
        self.assertEqual(stats.tx_bytes, 987654321)
        self.assertEqual(stats.rx_packets, 100000)
        self.assertEqual(stats.tx_packets, 80000)
        self.assertEqual(stats.rx_dropped, 10)
        self.assertEqual(stats.rx_missed_errors, 5)
        self.assertEqual(stats.link_speed_mbps, 2500)
        # drop_rate = (10 + 5) / 100000 * 100 = 0.015
        self.assertAlmostEqual(stats.drop_rate_pct, 0.015, places=3)

    def test_get_stats_zero_packets_no_division_error(self):
        """get_stats() should handle zero rx_packets without division by zero."""
        adapter = _make_adapter()

        def mock_read_sysfs_int(path):
            return 0

        adapter._read_sysfs_int = mock_read_sysfs_int

        stats = asyncio.run(adapter.get_stats())

        self.assertAlmostEqual(stats.drop_rate_pct, 0.0)

    def test_get_stats_negative_speed_clamped(self):
        """get_stats() should clamp negative link speed to 0."""
        adapter = _make_adapter()

        def mock_read_sysfs_int(path):
            basename = os.path.basename(path)
            if basename == "speed":
                return -1
            return 0

        adapter._read_sysfs_int = mock_read_sysfs_int

        stats = asyncio.run(adapter.get_stats())

        self.assertEqual(stats.link_speed_mbps, 0)


if __name__ == "__main__":
    unittest.main()
