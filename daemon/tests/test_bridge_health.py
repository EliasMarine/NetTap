"""
Tests for daemon/services/bridge_health.py

All tests use mocks -- no real sysfs, systemctl, or network access required.
Tests cover the BridgeHealthMonitor class: health checks, history management,
statistics computation, bypass mode, delta calculation, health status
determination, and graceful degradation when sysfs files are absent.
"""

import asyncio
import os
import sys
import unittest

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.bridge_health import BridgeHealthCheck, BridgeHealthMonitor


class TestBridgeHealthCheckDataclass(unittest.TestCase):
    """Tests for the BridgeHealthCheck dataclass."""

    def test_to_dict_returns_all_fields(self):
        """to_dict() should return a dict with all expected fields."""
        check = BridgeHealthCheck(
            bridge_state="up",
            wan_link=True,
            lan_link=True,
            bypass_active=False,
            watchdog_active=True,
            latency_us=50.0,
            rx_bytes_delta=1000,
            tx_bytes_delta=2000,
            rx_packets_delta=10,
            tx_packets_delta=20,
            uptime_seconds=3600.0,
            health_status="normal",
            issues=[],
            last_check="2026-02-26T12:00:00+00:00",
        )
        d = check.to_dict()
        expected_keys = {
            "bridge_state", "wan_link", "lan_link", "bypass_active",
            "watchdog_active", "latency_us", "rx_bytes_delta", "tx_bytes_delta",
            "rx_packets_delta", "tx_packets_delta", "uptime_seconds",
            "health_status", "issues", "last_check",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_preserves_values(self):
        """to_dict() should preserve exact values."""
        check = BridgeHealthCheck(
            bridge_state="down",
            wan_link=False,
            lan_link=True,
            bypass_active=True,
            watchdog_active=False,
            latency_us=150.0,
            rx_bytes_delta=5000,
            tx_bytes_delta=6000,
            rx_packets_delta=50,
            tx_packets_delta=60,
            uptime_seconds=0.0,
            health_status="bypass",
            issues=["Bypass mode is active"],
            last_check="2026-02-26T12:00:00+00:00",
        )
        d = check.to_dict()
        self.assertEqual(d["bridge_state"], "down")
        self.assertFalse(d["wan_link"])
        self.assertTrue(d["lan_link"])
        self.assertTrue(d["bypass_active"])
        self.assertEqual(d["latency_us"], 150.0)
        self.assertEqual(d["issues"], ["Bypass mode is active"])


class TestInitialization(unittest.TestCase):
    """Tests for BridgeHealthMonitor initialization."""

    def test_default_parameters(self):
        """Default init should use br0, eth0, eth1."""
        monitor = BridgeHealthMonitor()
        self.assertEqual(monitor._bridge_name, "br0")
        self.assertEqual(monitor._wan_iface, "eth0")
        self.assertEqual(monitor._lan_iface, "eth1")
        self.assertEqual(monitor._max_history, 2880)

    def test_custom_parameters(self):
        """Custom parameters should be stored."""
        monitor = BridgeHealthMonitor(
            bridge_name="br1",
            wan_iface="enp1s0",
            lan_iface="enp2s0",
            max_history=100,
        )
        self.assertEqual(monitor._bridge_name, "br1")
        self.assertEqual(monitor._wan_iface, "enp1s0")
        self.assertEqual(monitor._lan_iface, "enp2s0")
        self.assertEqual(monitor._max_history, 100)

    def test_history_starts_empty(self):
        """History should be empty on initialization."""
        monitor = BridgeHealthMonitor()
        self.assertEqual(len(monitor._history), 0)

    def test_bypass_starts_inactive(self):
        """Bypass should be inactive on initialization."""
        monitor = BridgeHealthMonitor()
        self.assertFalse(monitor._bypass_active)


class TestDetermineHealthStatus(unittest.TestCase):
    """Tests for BridgeHealthMonitor._determine_health_status()."""

    def setUp(self):
        self.monitor = BridgeHealthMonitor()

    def test_normal_status(self):
        """Bridge up + both links + no bypass = normal."""
        status = self.monitor._determine_health_status("up", True, True, False)
        self.assertEqual(status, "normal")

    def test_bypass_overrides_all(self):
        """Bypass active should always return 'bypass'."""
        status = self.monitor._determine_health_status("up", True, True, True)
        self.assertEqual(status, "bypass")

    def test_bypass_even_when_down(self):
        """Bypass should be reported even if bridge is down."""
        status = self.monitor._determine_health_status("down", False, False, True)
        self.assertEqual(status, "bypass")

    def test_bridge_down_is_down(self):
        """Bridge down without bypass = down."""
        status = self.monitor._determine_health_status("down", True, True, False)
        self.assertEqual(status, "down")

    def test_both_nics_unlinked_is_down(self):
        """Both NICs unlinked = down."""
        status = self.monitor._determine_health_status("up", False, False, False)
        self.assertEqual(status, "down")

    def test_unknown_bridge_is_degraded(self):
        """Unknown bridge state = degraded."""
        status = self.monitor._determine_health_status("unknown", True, True, False)
        self.assertEqual(status, "degraded")

    def test_wan_down_is_degraded(self):
        """Bridge up but WAN down = degraded."""
        status = self.monitor._determine_health_status("up", False, True, False)
        self.assertEqual(status, "degraded")

    def test_lan_down_is_degraded(self):
        """Bridge up but LAN down = degraded."""
        status = self.monitor._determine_health_status("up", True, False, False)
        self.assertEqual(status, "degraded")


class TestEstimateLatency(unittest.TestCase):
    """Tests for BridgeHealthMonitor._estimate_latency()."""

    def setUp(self):
        self.monitor = BridgeHealthMonitor()

    def test_bridge_not_up_returns_zero(self):
        """Non-up bridge should return 0 latency."""
        self.assertEqual(self.monitor._estimate_latency("down", True, True), 0.0)
        self.assertEqual(self.monitor._estimate_latency("unknown", True, True), 0.0)

    def test_normal_latency(self):
        """Bridge up with both links should return base latency."""
        latency = self.monitor._estimate_latency("up", True, True)
        self.assertEqual(latency, 50.0)

    def test_degraded_latency_higher(self):
        """Missing link should return higher latency."""
        latency = self.monitor._estimate_latency("up", False, True)
        self.assertGreater(latency, 50.0)


class TestCalculateDeltas(unittest.TestCase):
    """Tests for BridgeHealthMonitor._calculate_deltas()."""

    def test_first_check_returns_zeros(self):
        """First check with no previous counters should return zeros."""
        monitor = BridgeHealthMonitor()
        result = monitor._calculate_deltas({"rx_bytes": 100, "tx_bytes": 200, "rx_packets": 10, "tx_packets": 20})
        self.assertEqual(result, (0, 0, 0, 0))

    def test_delta_calculation(self):
        """Second check should return correct deltas."""
        monitor = BridgeHealthMonitor()
        monitor._prev_rx_bytes = 100
        monitor._prev_tx_bytes = 200
        monitor._prev_rx_packets = 10
        monitor._prev_tx_packets = 20

        current = {"rx_bytes": 300, "tx_bytes": 500, "rx_packets": 25, "tx_packets": 35}
        result = monitor._calculate_deltas(current)
        self.assertEqual(result, (200, 300, 15, 15))

    def test_counter_wrap_returns_zero(self):
        """Counter wrap (current < prev) should return 0 via max(0, ...)."""
        monitor = BridgeHealthMonitor()
        monitor._prev_rx_bytes = 1000
        monitor._prev_tx_bytes = 2000
        monitor._prev_rx_packets = 100
        monitor._prev_tx_packets = 200

        current = {"rx_bytes": 50, "tx_bytes": 100, "rx_packets": 5, "tx_packets": 10}
        result = monitor._calculate_deltas(current)
        self.assertEqual(result, (0, 0, 0, 0))

    def test_empty_stats_returns_zeros(self):
        """Empty stats dict should return zeros."""
        monitor = BridgeHealthMonitor()
        monitor._prev_rx_bytes = 100
        result = monitor._calculate_deltas({})
        self.assertEqual(result, (0, 0, 0, 0))


class TestCheckHealth(unittest.TestCase):
    """Tests for check_health() with mocked sysfs/system calls."""

    def _make_monitor_with_mocks(self, bridge_state="up", wan_carrier=True, lan_carrier=True):
        """Create a monitor with mocked internal methods."""
        monitor = BridgeHealthMonitor()

        async def mock_bridge_state():
            return bridge_state

        async def mock_carrier(iface):
            if iface == "eth0":
                return wan_carrier
            return lan_carrier

        async def mock_stats(iface):
            return {"rx_bytes": 1000, "tx_bytes": 2000, "rx_packets": 10, "tx_packets": 20}

        async def mock_watchdog():
            return False

        monitor._check_bridge_state = mock_bridge_state
        monitor._check_carrier = mock_carrier
        monitor._read_interface_stats = mock_stats
        monitor._check_watchdog = mock_watchdog
        monitor._check_bypass_file = lambda: False

        return monitor

    def test_check_health_returns_correct_structure(self):
        """check_health() should return dict with all expected keys."""
        monitor = self._make_monitor_with_mocks()

        result = asyncio.run(monitor.check_health())

        expected_keys = {
            "bridge_state", "wan_link", "lan_link", "bypass_active",
            "watchdog_active", "latency_us", "rx_bytes_delta", "tx_bytes_delta",
            "rx_packets_delta", "tx_packets_delta", "uptime_seconds",
            "health_status", "issues", "last_check",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_check_health_normal(self):
        """Bridge up + both links = normal health."""
        monitor = self._make_monitor_with_mocks("up", True, True)
        result = asyncio.run(monitor.check_health())
        self.assertEqual(result["health_status"], "normal")
        self.assertEqual(result["bridge_state"], "up")
        self.assertTrue(result["wan_link"])
        self.assertTrue(result["lan_link"])

    def test_check_health_degraded_wan_down(self):
        """WAN link down = degraded health."""
        monitor = self._make_monitor_with_mocks("up", False, True)
        result = asyncio.run(monitor.check_health())
        self.assertEqual(result["health_status"], "degraded")
        self.assertFalse(result["wan_link"])

    def test_check_health_down(self):
        """Bridge down = down health."""
        monitor = self._make_monitor_with_mocks("down", True, True)
        result = asyncio.run(monitor.check_health())
        self.assertEqual(result["health_status"], "down")

    def test_check_health_stores_in_history(self):
        """check_health() should append to history."""
        monitor = self._make_monitor_with_mocks()
        self.assertEqual(len(monitor._history), 0)
        asyncio.run(monitor.check_health())
        self.assertEqual(len(monitor._history), 1)
        asyncio.run(monitor.check_health())
        self.assertEqual(len(monitor._history), 2)

    def test_check_health_has_iso_timestamp(self):
        """last_check should be a valid ISO timestamp."""
        monitor = self._make_monitor_with_mocks()
        result = asyncio.run(monitor.check_health())
        self.assertIn("T", result["last_check"])
        self.assertIn("+00:00", result["last_check"])

    def test_check_health_issues_list(self):
        """Issues list should contain relevant warnings."""
        monitor = self._make_monitor_with_mocks("up", False, True)
        result = asyncio.run(monitor.check_health())
        issues = result["issues"]
        self.assertTrue(any("WAN" in i for i in issues))


class TestGracefulDegradation(unittest.TestCase):
    """Tests for graceful degradation when sysfs files do not exist."""

    def test_check_bridge_state_missing_sysfs(self):
        """Missing sysfs file should return 'unknown'."""
        monitor = BridgeHealthMonitor(bridge_name="nonexistent_br99")
        result = asyncio.run(monitor._check_bridge_state())
        self.assertEqual(result, "unknown")

    def test_check_carrier_missing_sysfs(self):
        """Missing carrier file should return False."""
        monitor = BridgeHealthMonitor(wan_iface="nonexistent_eth99")
        result = asyncio.run(monitor._check_carrier("nonexistent_eth99"))
        self.assertFalse(result)

    def test_read_interface_stats_missing_sysfs(self):
        """Missing stats files should return zeros."""
        monitor = BridgeHealthMonitor(bridge_name="nonexistent_br99")
        result = asyncio.run(monitor._read_interface_stats("nonexistent_br99"))
        self.assertEqual(result["rx_bytes"], 0)
        self.assertEqual(result["tx_bytes"], 0)
        self.assertEqual(result["rx_packets"], 0)
        self.assertEqual(result["tx_packets"], 0)

    def test_read_sysfs_file_missing(self):
        """_read_sysfs_file with bad path should return None."""
        result = BridgeHealthMonitor._read_sysfs_file("/nonexistent/path")
        self.assertIsNone(result)


class TestHistoryBounding(unittest.TestCase):
    """Tests for history size bounding."""

    def test_history_respects_max_size(self):
        """History should not exceed max_history."""
        monitor = BridgeHealthMonitor(max_history=5)

        async def mock_bridge_state():
            return "up"

        async def mock_carrier(iface):
            return True

        async def mock_stats(iface):
            return {"rx_bytes": 0, "tx_bytes": 0, "rx_packets": 0, "tx_packets": 0}

        async def mock_watchdog():
            return False

        monitor._check_bridge_state = mock_bridge_state
        monitor._check_carrier = mock_carrier
        monitor._read_interface_stats = mock_stats
        monitor._check_watchdog = mock_watchdog
        monitor._check_bypass_file = lambda: False

        async def run_checks():
            for _ in range(10):
                await monitor.check_health()

        asyncio.run(run_checks())
        self.assertEqual(len(monitor._history), 5)

    def test_history_keeps_newest(self):
        """After overflow, newest entries should be retained."""
        monitor = BridgeHealthMonitor(max_history=3)
        for i in range(5):
            check = BridgeHealthCheck(
                bridge_state="up",
                wan_link=True,
                lan_link=True,
                bypass_active=False,
                watchdog_active=True,
                latency_us=float(i),
                rx_bytes_delta=0,
                tx_bytes_delta=0,
                rx_packets_delta=0,
                tx_packets_delta=0,
                uptime_seconds=0.0,
                health_status="normal",
                issues=[],
                last_check=f"ts{i}",
            )
            monitor._history.append(check)

        self.assertEqual(len(monitor._history), 3)
        # Should be entries 2, 3, 4
        self.assertEqual(monitor._history[0].latency_us, 2.0)
        self.assertEqual(monitor._history[2].latency_us, 4.0)


class TestGetHistory(unittest.TestCase):
    """Tests for get_history()."""

    def setUp(self):
        self.monitor = BridgeHealthMonitor()
        for i in range(5):
            check = BridgeHealthCheck(
                bridge_state="up",
                wan_link=True,
                lan_link=True,
                bypass_active=False,
                watchdog_active=True,
                latency_us=float(i),
                rx_bytes_delta=i * 100,
                tx_bytes_delta=i * 200,
                rx_packets_delta=i,
                tx_packets_delta=i * 2,
                uptime_seconds=float(i * 30),
                health_status="normal",
                issues=[],
                last_check=f"ts{i}",
            )
            self.monitor._history.append(check)

    def test_returns_list_of_dicts(self):
        """get_history() should return a list of dicts."""
        history = asyncio.run(self.monitor.get_history())
        self.assertIsInstance(history, list)
        self.assertIsInstance(history[0], dict)

    def test_newest_first(self):
        """History should be returned newest first."""
        history = asyncio.run(self.monitor.get_history())
        self.assertEqual(history[0]["last_check"], "ts4")
        self.assertEqual(history[-1]["last_check"], "ts0")

    def test_limit_parameter(self):
        """limit parameter should restrict results."""
        history = asyncio.run(self.monitor.get_history(limit=2))
        self.assertEqual(len(history), 2)

    def test_empty_history(self):
        """Empty history should return empty list."""
        monitor = BridgeHealthMonitor()
        history = asyncio.run(monitor.get_history())
        self.assertEqual(history, [])


class TestGetStatistics(unittest.TestCase):
    """Tests for get_statistics()."""

    def test_empty_history_returns_defaults(self):
        """Empty history should return None/zero stats."""
        monitor = BridgeHealthMonitor()
        stats = asyncio.run(monitor.get_statistics())
        self.assertIsNone(stats["average_latency_us"])
        self.assertIsNone(stats["uptime_percentage"])
        self.assertEqual(stats["total_checks"], 0)
        self.assertEqual(stats["total_rx_bytes"], 0)
        self.assertEqual(stats["total_tx_bytes"], 0)

    def test_statistics_with_data(self):
        """Stats should be computed correctly from history."""
        monitor = BridgeHealthMonitor()
        for i in range(10):
            check = BridgeHealthCheck(
                bridge_state="up",
                wan_link=True,
                lan_link=True,
                bypass_active=False,
                watchdog_active=True,
                latency_us=50.0,
                rx_bytes_delta=100,
                tx_bytes_delta=200,
                rx_packets_delta=10,
                tx_packets_delta=20,
                uptime_seconds=float(i * 30),
                health_status="normal",
                issues=[],
                last_check=f"ts{i}",
            )
            monitor._history.append(check)

        stats = asyncio.run(monitor.get_statistics())
        self.assertEqual(stats["total_checks"], 10)
        self.assertEqual(stats["average_latency_us"], 50.0)
        self.assertEqual(stats["total_rx_bytes"], 1000)
        self.assertEqual(stats["total_tx_bytes"], 2000)
        self.assertEqual(stats["total_rx_packets"], 100)
        self.assertEqual(stats["total_tx_packets"], 200)
        self.assertEqual(stats["uptime_percentage"], 100.0)
        self.assertEqual(stats["longest_downtime_seconds"], 0)

    def test_statistics_with_downtime(self):
        """Downtime stats should be computed correctly."""
        monitor = BridgeHealthMonitor()
        # 5 normal, 3 down, 2 normal
        statuses = (["normal"] * 5) + (["down"] * 3) + (["normal"] * 2)
        for i, s in enumerate(statuses):
            check = BridgeHealthCheck(
                bridge_state="up" if s == "normal" else "down",
                wan_link=s == "normal",
                lan_link=s == "normal",
                bypass_active=False,
                watchdog_active=True,
                latency_us=50.0 if s == "normal" else 0.0,
                rx_bytes_delta=0,
                tx_bytes_delta=0,
                rx_packets_delta=0,
                tx_packets_delta=0,
                uptime_seconds=0.0,
                health_status=s,
                issues=[],
                last_check=f"ts{i}",
            )
            monitor._history.append(check)

        stats = asyncio.run(monitor.get_statistics())
        self.assertEqual(stats["total_checks"], 10)
        # 7 up (normal) out of 10
        self.assertEqual(stats["uptime_percentage"], 70.0)
        # Longest down streak = 3 * 30s = 90s
        self.assertEqual(stats["longest_downtime_seconds"], 90)
        self.assertEqual(stats["status_counts"]["normal"], 7)
        self.assertEqual(stats["status_counts"]["down"], 3)

    def test_statistics_status_counts(self):
        """Status counts should include all four categories."""
        monitor = BridgeHealthMonitor()
        stats = asyncio.run(monitor.get_statistics())
        self.assertIn("normal", stats["status_counts"])
        self.assertIn("degraded", stats["status_counts"])
        self.assertIn("bypass", stats["status_counts"])
        self.assertIn("down", stats["status_counts"])


class TestBypassMode(unittest.TestCase):
    """Tests for bypass mode enable/disable."""

    def test_trigger_bypass(self):
        """trigger_bypass() should activate bypass and return confirmation."""
        monitor = BridgeHealthMonitor()
        # Mock file write to avoid filesystem side effects
        monitor._write_bypass_file = lambda active: None

        result = asyncio.run(monitor.trigger_bypass())
        self.assertTrue(result["bypass_active"])
        self.assertIn("activated_at", result)
        self.assertIn("message", result)
        self.assertTrue(monitor._bypass_active)

    def test_disable_bypass(self):
        """disable_bypass() should deactivate bypass and return confirmation."""
        monitor = BridgeHealthMonitor()
        monitor._bypass_active = True
        monitor._write_bypass_file = lambda active: None

        result = asyncio.run(monitor.disable_bypass())
        self.assertFalse(result["bypass_active"])
        self.assertIn("deactivated_at", result)
        self.assertIn("message", result)
        self.assertFalse(monitor._bypass_active)

    def test_bypass_affects_health_status(self):
        """Health check during bypass should report 'bypass' status."""
        monitor = BridgeHealthMonitor()
        monitor._bypass_active = True

        async def mock_bridge_state():
            return "up"

        async def mock_carrier(iface):
            return True

        async def mock_stats(iface):
            return {"rx_bytes": 0, "tx_bytes": 0, "rx_packets": 0, "tx_packets": 0}

        async def mock_watchdog():
            return False

        monitor._check_bridge_state = mock_bridge_state
        monitor._check_carrier = mock_carrier
        monitor._read_interface_stats = mock_stats
        monitor._check_watchdog = mock_watchdog
        monitor._check_bypass_file = lambda: False

        result = asyncio.run(monitor.check_health())
        self.assertEqual(result["health_status"], "bypass")
        self.assertTrue(result["bypass_active"])


class TestCheckWatchdog(unittest.TestCase):
    """Tests for _check_watchdog() graceful degradation."""

    def test_watchdog_not_available(self):
        """When systemctl is not found, watchdog should return False."""
        monitor = BridgeHealthMonitor()
        # On macOS / test environments, systemctl is not available
        result = asyncio.run(monitor._check_watchdog())
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
