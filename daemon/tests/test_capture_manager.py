"""
Tests for daemon/services/capture_manager.py

Tests cover the CaptureMode enum, CaptureHealth and CaptureStats dataclasses,
and verifies that CaptureManager is abstract and cannot be instantiated directly.
"""

import os
import sys
import unittest

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.capture_manager import (
    CaptureHealth,
    CaptureManager,
    CaptureMode,
    CaptureStats,
)


class TestCaptureModeEnum(unittest.TestCase):
    """Tests for the CaptureMode enum."""

    def test_bridge_value(self):
        """CaptureMode.BRIDGE should have value 'bridge'."""
        self.assertEqual(CaptureMode.BRIDGE.value, "bridge")

    def test_mirror_value(self):
        """CaptureMode.MIRROR should have value 'mirror'."""
        self.assertEqual(CaptureMode.MIRROR.value, "mirror")

    def test_from_string_bridge(self):
        """CaptureMode('bridge') should return BRIDGE."""
        self.assertEqual(CaptureMode("bridge"), CaptureMode.BRIDGE)

    def test_from_string_mirror(self):
        """CaptureMode('mirror') should return MIRROR."""
        self.assertEqual(CaptureMode("mirror"), CaptureMode.MIRROR)

    def test_invalid_value_raises(self):
        """CaptureMode with invalid string should raise ValueError."""
        with self.assertRaises(ValueError):
            CaptureMode("span")


class TestCaptureHealth(unittest.TestCase):
    """Tests for the CaptureHealth dataclass."""

    def _make_health(self, **overrides):
        """Create a CaptureHealth with sensible defaults."""
        defaults = {
            "mode": "bridge",
            "status": "normal",
            "capture_interface": "br0",
            "link_up": True,
            "promisc_enabled": True,
            "issues": [],
            "extra": {},
        }
        defaults.update(overrides)
        return CaptureHealth(**defaults)

    def test_to_dict_includes_all_fields(self):
        """to_dict() should include mode, status, capture_interface, link_up, promisc_enabled, issues."""
        health = self._make_health()
        d = health.to_dict()
        expected_keys = {
            "mode",
            "status",
            "capture_interface",
            "link_up",
            "promisc_enabled",
            "issues",
        }
        self.assertTrue(expected_keys.issubset(set(d.keys())))

    def test_to_dict_preserves_values(self):
        """to_dict() should preserve exact values."""
        health = self._make_health(
            mode="mirror",
            status="degraded",
            capture_interface="enp2s0",
            link_up=False,
            promisc_enabled=False,
            issues=["No carrier"],
        )
        d = health.to_dict()
        self.assertEqual(d["mode"], "mirror")
        self.assertEqual(d["status"], "degraded")
        self.assertEqual(d["capture_interface"], "enp2s0")
        self.assertFalse(d["link_up"])
        self.assertFalse(d["promisc_enabled"])
        self.assertEqual(d["issues"], ["No carrier"])

    def test_to_dict_includes_extra_fields(self):
        """to_dict() should merge extra dict into the output."""
        health = self._make_health(
            extra={"wan_link": True, "lan_link": False, "latency_us": 42.5}
        )
        d = health.to_dict()
        self.assertTrue(d["wan_link"])
        self.assertFalse(d["lan_link"])
        self.assertAlmostEqual(d["latency_us"], 42.5)

    def test_default_issues_empty(self):
        """Default issues should be an empty list."""
        health = CaptureHealth(
            mode="bridge",
            status="normal",
            capture_interface="br0",
            link_up=True,
            promisc_enabled=True,
        )
        self.assertEqual(health.issues, [])

    def test_default_extra_empty(self):
        """Default extra should be an empty dict."""
        health = CaptureHealth(
            mode="bridge",
            status="normal",
            capture_interface="br0",
            link_up=True,
            promisc_enabled=True,
        )
        self.assertEqual(health.extra, {})


class TestCaptureStats(unittest.TestCase):
    """Tests for the CaptureStats dataclass."""

    def _make_stats(self, **overrides):
        """Create a CaptureStats with sensible defaults."""
        defaults = {
            "capture_interface": "br0",
            "rx_bytes": 1000000,
            "tx_bytes": 500000,
            "rx_packets": 10000,
            "tx_packets": 5000,
            "rx_dropped": 5,
            "rx_missed_errors": 2,
            "link_speed_mbps": 2500,
            "drop_rate_pct": 0.07,
        }
        defaults.update(overrides)
        return CaptureStats(**defaults)

    def test_to_dict_includes_all_fields(self):
        """to_dict() should include all counter and metric fields."""
        stats = self._make_stats()
        d = stats.to_dict()
        expected_keys = {
            "capture_interface",
            "rx_bytes",
            "tx_bytes",
            "rx_packets",
            "tx_packets",
            "rx_dropped",
            "rx_missed_errors",
            "link_speed_mbps",
            "drop_rate_pct",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_preserves_values(self):
        """to_dict() should preserve exact counter values."""
        stats = self._make_stats(
            capture_interface="enp2s0",
            rx_bytes=999999,
            tx_bytes=888888,
            rx_packets=7777,
            tx_packets=6666,
            rx_dropped=55,
            rx_missed_errors=44,
            link_speed_mbps=1000,
            drop_rate_pct=0.5,
        )
        d = stats.to_dict()
        self.assertEqual(d["capture_interface"], "enp2s0")
        self.assertEqual(d["rx_bytes"], 999999)
        self.assertEqual(d["tx_bytes"], 888888)
        self.assertEqual(d["rx_packets"], 7777)
        self.assertEqual(d["tx_packets"], 6666)
        self.assertEqual(d["rx_dropped"], 55)
        self.assertEqual(d["rx_missed_errors"], 44)
        self.assertEqual(d["link_speed_mbps"], 1000)
        self.assertAlmostEqual(d["drop_rate_pct"], 0.5)

    def test_default_values(self):
        """Default counter values should be zero."""
        stats = CaptureStats(capture_interface="br0")
        self.assertEqual(stats.rx_bytes, 0)
        self.assertEqual(stats.tx_bytes, 0)
        self.assertEqual(stats.rx_packets, 0)
        self.assertEqual(stats.tx_packets, 0)
        self.assertEqual(stats.rx_dropped, 0)
        self.assertEqual(stats.rx_missed_errors, 0)
        self.assertEqual(stats.link_speed_mbps, 0)
        self.assertAlmostEqual(stats.drop_rate_pct, 0.0)


class TestCaptureManagerAbstract(unittest.TestCase):
    """Tests verifying CaptureManager is abstract."""

    def test_cannot_instantiate(self):
        """CaptureManager should not be instantiable directly."""
        with self.assertRaises(TypeError):
            CaptureManager()

    def test_subclass_must_implement_all_methods(self):
        """A subclass missing abstract methods should raise TypeError."""

        class IncompleteCaptureManager(CaptureManager):
            pass

        with self.assertRaises(TypeError):
            IncompleteCaptureManager()

    def test_complete_subclass_can_instantiate(self):
        """A subclass implementing all abstract methods should work."""

        class FakeCaptureManager(CaptureManager):
            async def setup(self):
                return {}

            async def teardown(self):
                return {}

            async def get_health(self):
                return CaptureHealth(
                    mode="bridge",
                    status="normal",
                    capture_interface="br0",
                    link_up=True,
                    promisc_enabled=True,
                )

            def get_capture_interface(self):
                return "br0"

            async def get_stats(self):
                return CaptureStats(capture_interface="br0")

            @property
            def mode(self):
                return CaptureMode.BRIDGE

        mgr = FakeCaptureManager()
        self.assertEqual(mgr.mode, CaptureMode.BRIDGE)
        self.assertEqual(mgr.get_capture_interface(), "br0")


if __name__ == "__main__":
    unittest.main()
