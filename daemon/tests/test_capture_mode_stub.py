"""
Tests for daemon/services/capture_mode_stub.py

Tests cover the CaptureManagerStub class, verifying it correctly reads
capture mode from environment variables and returns safe defaults for
health, stats, and interface queries.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.capture_manager import CaptureHealth, CaptureMode, CaptureStats
from services.capture_mode_stub import CaptureManagerStub


class TestCaptureManagerStubDefaults(unittest.TestCase):
    """Tests for CaptureManagerStub with default (bridge) config."""

    def setUp(self):
        """Create a stub with default config (bridge mode)."""
        # Ensure no config file interferes — force env-based fallback
        with patch.dict(
            os.environ,
            {"CAPTURE_CONFIG_PATH": "/nonexistent/path.conf"},
            clear=False,
        ):
            self.stub = CaptureManagerStub()

    def test_mode_is_bridge_by_default(self):
        """Default mode should be BRIDGE."""
        self.assertEqual(self.stub.mode, CaptureMode.BRIDGE)

    def test_mode_value_is_string(self):
        """mode.value should be the string 'bridge'."""
        self.assertEqual(self.stub.mode.value, "bridge")

    def test_get_capture_interface_returns_br0(self):
        """Default bridge interface should be 'br0'."""
        self.assertEqual(self.stub.get_capture_interface(), "br0")

    def test_get_health_returns_capture_health(self):
        """get_health() should return a CaptureHealth instance."""
        health = asyncio.get_event_loop().run_until_complete(self.stub.get_health())
        self.assertIsInstance(health, CaptureHealth)

    def test_get_health_status_not_configured(self):
        """Stub health status should be 'not_configured'."""
        health = asyncio.get_event_loop().run_until_complete(self.stub.get_health())
        self.assertEqual(health.status, "not_configured")

    def test_get_health_has_stub_flag(self):
        """Stub health extra should contain stub=True."""
        health = asyncio.get_event_loop().run_until_complete(self.stub.get_health())
        d = health.to_dict()
        self.assertTrue(d.get("stub"))

    def test_get_health_link_down(self):
        """Stub should report link_up=False since no real interface is active."""
        health = asyncio.get_event_loop().run_until_complete(self.stub.get_health())
        self.assertFalse(health.link_up)

    def test_get_health_promisc_disabled(self):
        """Stub should report promisc_enabled=False."""
        health = asyncio.get_event_loop().run_until_complete(self.stub.get_health())
        self.assertFalse(health.promisc_enabled)

    def test_get_health_has_issue(self):
        """Stub health should report an issue explaining it's a stub."""
        health = asyncio.get_event_loop().run_until_complete(self.stub.get_health())
        self.assertEqual(len(health.issues), 1)
        self.assertIn("stub", health.issues[0].lower())

    def test_get_stats_returns_capture_stats(self):
        """get_stats() should return a CaptureStats instance."""
        stats = asyncio.get_event_loop().run_until_complete(self.stub.get_stats())
        self.assertIsInstance(stats, CaptureStats)

    def test_get_stats_zeroed(self):
        """Stub stats should have all zero counters."""
        stats = asyncio.get_event_loop().run_until_complete(self.stub.get_stats())
        self.assertEqual(stats.rx_bytes, 0)
        self.assertEqual(stats.tx_bytes, 0)
        self.assertEqual(stats.rx_packets, 0)
        self.assertEqual(stats.tx_packets, 0)
        self.assertEqual(stats.rx_dropped, 0)

    def test_get_stats_interface_matches(self):
        """Stats capture_interface should match get_capture_interface()."""
        stats = asyncio.get_event_loop().run_until_complete(self.stub.get_stats())
        self.assertEqual(stats.capture_interface, self.stub.get_capture_interface())

    def test_setup_is_noop(self):
        """setup() should return success with stub=True."""
        result = asyncio.get_event_loop().run_until_complete(self.stub.setup())
        self.assertTrue(result.get("success"))
        self.assertTrue(result.get("stub"))

    def test_teardown_is_noop(self):
        """teardown() should return success with stub=True."""
        result = asyncio.get_event_loop().run_until_complete(self.stub.teardown())
        self.assertTrue(result.get("success"))
        self.assertTrue(result.get("stub"))


class TestCaptureManagerStubMirrorMode(unittest.TestCase):
    """Tests for CaptureManagerStub when CAPTURE_MODE=mirror."""

    def setUp(self):
        """Create a stub with mirror mode set via env."""
        with patch.dict(
            os.environ,
            {
                "CAPTURE_CONFIG_PATH": "/nonexistent/path.conf",
                "CAPTURE_MODE": "mirror",
                "PCAP_IFACE": "enp2s0",
            },
            clear=False,
        ):
            self.stub = CaptureManagerStub()

    def test_mode_is_mirror(self):
        """Mode should be MIRROR when CAPTURE_MODE=mirror."""
        self.assertEqual(self.stub.mode, CaptureMode.MIRROR)

    def test_interface_is_mirror_nic(self):
        """Interface should be the mirror NIC, not br0."""
        self.assertEqual(self.stub.get_capture_interface(), "enp2s0")

    def test_health_mode_string(self):
        """Health mode should be 'mirror'."""
        health = asyncio.get_event_loop().run_until_complete(self.stub.get_health())
        self.assertEqual(health.mode, "mirror")

    def test_stats_interface_matches(self):
        """Stats interface should match the mirror NIC."""
        stats = asyncio.get_event_loop().run_until_complete(self.stub.get_stats())
        self.assertEqual(stats.capture_interface, "enp2s0")


if __name__ == "__main__":
    unittest.main()
