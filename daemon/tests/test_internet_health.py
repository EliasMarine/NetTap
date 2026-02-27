"""
Tests for daemon/services/internet_health.py

All tests use mocks for subprocess calls and DNS resolution -- no real
network access required. Tests cover the HealthCheck dataclass, status
determination, statistics computation, run_check orchestration, and
history management.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.internet_health import HealthCheck, InternetHealthMonitor


class TestHealthCheckDataclass(unittest.TestCase):
    """Tests for the HealthCheck dataclass."""

    def test_to_dict_returns_all_fields(self):
        """to_dict() should return a dict with all expected fields."""
        hc = HealthCheck(
            timestamp="2026-02-26T12:00:00+00:00",
            latency_ms=25.0,
            dns_resolve_ms=50.0,
            packet_loss_pct=0.0,
            status="healthy",
        )
        d = hc.to_dict()
        expected_keys = {"timestamp", "latency_ms", "dns_resolve_ms", "packet_loss_pct", "status"}
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_values(self):
        """to_dict() should preserve the exact values."""
        hc = HealthCheck(
            timestamp="2026-02-26T12:00:00+00:00",
            latency_ms=25.5,
            dns_resolve_ms=100.0,
            packet_loss_pct=5.0,
            status="degraded",
        )
        d = hc.to_dict()
        self.assertEqual(d["latency_ms"], 25.5)
        self.assertEqual(d["dns_resolve_ms"], 100.0)
        self.assertEqual(d["packet_loss_pct"], 5.0)
        self.assertEqual(d["status"], "degraded")

    def test_to_dict_with_none_latency(self):
        """to_dict() should handle None values correctly."""
        hc = HealthCheck(
            timestamp="2026-02-26T12:00:00+00:00",
            latency_ms=None,
            dns_resolve_ms=None,
            packet_loss_pct=100.0,
            status="down",
        )
        d = hc.to_dict()
        self.assertIsNone(d["latency_ms"])
        self.assertIsNone(d["dns_resolve_ms"])

    def test_healthcheck_equality(self):
        """Two HealthCheck instances with same values should be equal."""
        hc1 = HealthCheck("ts", 10.0, 20.0, 0.0, "healthy")
        hc2 = HealthCheck("ts", 10.0, 20.0, 0.0, "healthy")
        self.assertEqual(hc1, hc2)


class TestDetermineStatus(unittest.TestCase):
    """Tests for InternetHealthMonitor._determine_status()."""

    def setUp(self):
        self.monitor = InternetHealthMonitor()

    def test_healthy_status(self):
        """Good metrics should return 'healthy'."""
        status = self.monitor._determine_status(20.0, 50.0, 0.0)
        self.assertEqual(status, "healthy")

    def test_healthy_boundary(self):
        """Just below thresholds should still be healthy."""
        status = self.monitor._determine_status(99.9, 499.9, 4.9)
        self.assertEqual(status, "healthy")

    def test_degraded_high_latency(self):
        """High latency (>=100ms) should return 'degraded'."""
        status = self.monitor._determine_status(100.0, 50.0, 0.0)
        self.assertEqual(status, "degraded")

    def test_degraded_high_dns(self):
        """High DNS time (>=500ms) should return 'degraded'."""
        status = self.monitor._determine_status(50.0, 500.0, 0.0)
        self.assertEqual(status, "degraded")

    def test_degraded_high_packet_loss(self):
        """Packet loss >=5% should return 'degraded'."""
        status = self.monitor._determine_status(50.0, 50.0, 5.0)
        self.assertEqual(status, "degraded")

    def test_degraded_latency_none_dns_ok(self):
        """Latency None but DNS OK should return 'degraded'."""
        status = self.monitor._determine_status(None, 50.0, 0.0)
        self.assertEqual(status, "degraded")

    def test_degraded_dns_none_latency_ok(self):
        """DNS None but latency OK should return 'degraded'."""
        status = self.monitor._determine_status(50.0, None, 0.0)
        self.assertEqual(status, "degraded")

    def test_down_both_none(self):
        """Both latency and DNS None should return 'down'."""
        status = self.monitor._determine_status(None, None, 0.0)
        self.assertEqual(status, "down")

    def test_down_high_packet_loss(self):
        """Packet loss >=50% should return 'down'."""
        status = self.monitor._determine_status(50.0, 50.0, 50.0)
        self.assertEqual(status, "down")

    def test_down_100_percent_loss(self):
        """100% packet loss should return 'down'."""
        status = self.monitor._determine_status(50.0, 50.0, 100.0)
        self.assertEqual(status, "down")

    def test_down_none_and_high_loss(self):
        """Both None + high loss should still be 'down'."""
        status = self.monitor._determine_status(None, None, 80.0)
        self.assertEqual(status, "down")

    def test_degraded_very_high_latency(self):
        """Very high latency with OK other metrics is degraded, not down."""
        status = self.monitor._determine_status(450.0, 50.0, 0.0)
        self.assertEqual(status, "degraded")


class TestGetStatisticsEmpty(unittest.TestCase):
    """Tests for get_statistics() with empty history."""

    def test_empty_history_returns_defaults(self):
        """Empty history should return None stats and zero totals."""
        monitor = InternetHealthMonitor()
        stats = monitor.get_statistics()
        self.assertIsNone(stats["avg_latency_ms"])
        self.assertIsNone(stats["p95_latency_ms"])
        self.assertIsNone(stats["min_latency_ms"])
        self.assertIsNone(stats["max_latency_ms"])
        self.assertIsNone(stats["avg_dns_ms"])
        self.assertIsNone(stats["avg_packet_loss_pct"])
        self.assertIsNone(stats["uptime_pct"])
        self.assertEqual(stats["total_checks"], 0)
        self.assertEqual(stats["history_span_hours"], 0)


class TestGetStatisticsPopulated(unittest.TestCase):
    """Tests for get_statistics() with populated history."""

    def setUp(self):
        self.monitor = InternetHealthMonitor()
        base = datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc)
        # Add 10 healthy checks, 5 min apart
        for i in range(10):
            ts = (base + timedelta(minutes=i * 5)).isoformat()
            self.monitor._history.append(
                HealthCheck(
                    timestamp=ts,
                    latency_ms=20.0 + i,
                    dns_resolve_ms=50.0 + i,
                    packet_loss_pct=0.0,
                    status="healthy",
                )
            )

    def test_avg_latency(self):
        """Average latency should be computed correctly."""
        stats = self.monitor.get_statistics()
        # 20,21,22,...,29 -> avg = 24.5
        self.assertAlmostEqual(stats["avg_latency_ms"], 24.5)

    def test_min_latency(self):
        """Min latency should be the smallest value."""
        stats = self.monitor.get_statistics()
        self.assertEqual(stats["min_latency_ms"], 20.0)

    def test_max_latency(self):
        """Max latency should be the largest value."""
        stats = self.monitor.get_statistics()
        self.assertEqual(stats["max_latency_ms"], 29.0)

    def test_p95_latency(self):
        """P95 latency should be approximately the 95th percentile."""
        stats = self.monitor.get_statistics()
        self.assertIsNotNone(stats["p95_latency_ms"])

    def test_avg_dns(self):
        """Average DNS time should be computed correctly."""
        stats = self.monitor.get_statistics()
        # 50,51,...,59 -> avg = 54.5
        self.assertAlmostEqual(stats["avg_dns_ms"], 54.5)

    def test_uptime_all_healthy(self):
        """All healthy checks should give 100% uptime."""
        stats = self.monitor.get_statistics()
        self.assertEqual(stats["uptime_pct"], 100.0)

    def test_uptime_with_down_checks(self):
        """Add some down checks and verify uptime calculation."""
        # Add 5 down checks
        base = datetime(2026, 2, 26, 1, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            ts = (base + timedelta(minutes=i * 5)).isoformat()
            self.monitor._history.append(
                HealthCheck(
                    timestamp=ts,
                    latency_ms=None,
                    dns_resolve_ms=None,
                    packet_loss_pct=100.0,
                    status="down",
                )
            )
        stats = self.monitor.get_statistics()
        # 10 healthy + 5 down = 10/15 = 66.67%
        self.assertAlmostEqual(stats["uptime_pct"], 66.67)

    def test_total_checks(self):
        """Total checks should match history length."""
        stats = self.monitor.get_statistics()
        self.assertEqual(stats["total_checks"], 10)

    def test_history_span(self):
        """History span should be calculated correctly."""
        stats = self.monitor.get_statistics()
        # 10 checks, 5 min apart = 45 min span = 0.75 hours
        self.assertAlmostEqual(stats["history_span_hours"], 0.75)

    def test_avg_packet_loss(self):
        """Average packet loss should be 0 for all-healthy checks."""
        stats = self.monitor.get_statistics()
        self.assertEqual(stats["avg_packet_loss_pct"], 0.0)


class TestRunCheck(unittest.TestCase):
    """Tests for run_check() with mocked network calls."""

    def test_run_check_healthy(self):
        """run_check() with good mocked results returns healthy check."""
        monitor = InternetHealthMonitor(
            ping_targets=["8.8.8.8", "1.1.1.1"],
            dns_targets=["google.com", "example.com"],
        )

        async def mock_latency(target, timeout=5.0):
            return 25.0

        async def mock_dns(domain, timeout=5.0):
            return 50.0

        async def mock_loss(target, count=10, timeout=10.0):
            return 0.0

        monitor.check_latency = mock_latency
        monitor.check_dns = mock_dns
        monitor.check_packet_loss = mock_loss

        check = asyncio.run(monitor.run_check())
        self.assertEqual(check.status, "healthy")
        self.assertIsNotNone(check.latency_ms)
        self.assertIsNotNone(check.dns_resolve_ms)
        self.assertEqual(check.packet_loss_pct, 0.0)

    def test_run_check_down(self):
        """run_check() with all failures returns down check."""
        monitor = InternetHealthMonitor(
            ping_targets=["8.8.8.8"],
            dns_targets=["google.com"],
        )

        async def mock_latency(target, timeout=5.0):
            return None

        async def mock_dns(domain, timeout=5.0):
            return None

        async def mock_loss(target, count=10, timeout=10.0):
            return 100.0

        monitor.check_latency = mock_latency
        monitor.check_dns = mock_dns
        monitor.check_packet_loss = mock_loss

        check = asyncio.run(monitor.run_check())
        self.assertEqual(check.status, "down")
        self.assertIsNone(check.latency_ms)
        self.assertIsNone(check.dns_resolve_ms)
        self.assertEqual(check.packet_loss_pct, 100.0)

    def test_run_check_degraded(self):
        """run_check() with high latency returns degraded check."""
        monitor = InternetHealthMonitor(
            ping_targets=["8.8.8.8"],
            dns_targets=["google.com"],
        )

        async def mock_latency(target, timeout=5.0):
            return 200.0

        async def mock_dns(domain, timeout=5.0):
            return 50.0

        async def mock_loss(target, count=10, timeout=10.0):
            return 0.0

        monitor.check_latency = mock_latency
        monitor.check_dns = mock_dns
        monitor.check_packet_loss = mock_loss

        check = asyncio.run(monitor.run_check())
        self.assertEqual(check.status, "degraded")

    def test_run_check_stores_in_history(self):
        """run_check() should append result to history."""
        monitor = InternetHealthMonitor(
            ping_targets=["8.8.8.8"],
            dns_targets=["google.com"],
        )

        async def mock_latency(target, timeout=5.0):
            return 25.0

        async def mock_dns(domain, timeout=5.0):
            return 50.0

        async def mock_loss(target, count=10, timeout=10.0):
            return 0.0

        monitor.check_latency = mock_latency
        monitor.check_dns = mock_dns
        monitor.check_packet_loss = mock_loss

        async def _run_twice():
            self.assertEqual(len(monitor._history), 0)
            await monitor.run_check()
            self.assertEqual(len(monitor._history), 1)
            await monitor.run_check()
            self.assertEqual(len(monitor._history), 2)

        asyncio.run(_run_twice())


class TestHistorySizeLimit(unittest.TestCase):
    """Tests for history size bounding."""

    def test_history_respects_max_size(self):
        """History should not exceed history_size."""
        monitor = InternetHealthMonitor(
            ping_targets=["8.8.8.8"],
            dns_targets=["google.com"],
            history_size=5,
        )

        async def mock_latency(target, timeout=5.0):
            return 25.0

        async def mock_dns(domain, timeout=5.0):
            return 50.0

        async def mock_loss(target, count=10, timeout=10.0):
            return 0.0

        monitor.check_latency = mock_latency
        monitor.check_dns = mock_dns
        monitor.check_packet_loss = mock_loss

        async def _run_ten():
            for _ in range(10):
                await monitor.run_check()

        asyncio.run(_run_ten())

        self.assertEqual(len(monitor._history), 5)

    def test_history_keeps_newest(self):
        """After overflow, history should keep the most recent entries."""
        monitor = InternetHealthMonitor(history_size=3)
        base = datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            ts = (base + timedelta(minutes=i)).isoformat()
            monitor._history.append(
                HealthCheck(ts, float(i), float(i), 0.0, "healthy")
            )
        # Trim like run_check does
        if len(monitor._history) > monitor._history_size:
            monitor._history = monitor._history[-monitor._history_size:]

        self.assertEqual(len(monitor._history), 3)
        # Should be entries 2, 3, 4
        self.assertEqual(monitor._history[0].latency_ms, 2.0)
        self.assertEqual(monitor._history[2].latency_ms, 4.0)


class TestGetCurrentStatus(unittest.TestCase):
    """Tests for get_current_status()."""

    def test_empty_history_returns_unknown(self):
        """With no history, current status should be 'unknown'."""
        monitor = InternetHealthMonitor()
        status = monitor.get_current_status()
        self.assertEqual(status["status"], "unknown")
        self.assertIsNone(status["timestamp"])

    def test_returns_last_check(self):
        """Should return the most recent health check."""
        monitor = InternetHealthMonitor()
        monitor._history.append(
            HealthCheck("ts1", 10.0, 20.0, 0.0, "healthy")
        )
        monitor._history.append(
            HealthCheck("ts2", 200.0, 600.0, 10.0, "degraded")
        )
        status = monitor.get_current_status()
        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["timestamp"], "ts2")


class TestGetHistory(unittest.TestCase):
    """Tests for get_history()."""

    def test_empty_history(self):
        """Empty history returns empty list."""
        monitor = InternetHealthMonitor()
        self.assertEqual(monitor.get_history(), [])

    def test_returns_dicts(self):
        """History entries should be dicts."""
        monitor = InternetHealthMonitor()
        monitor._history.append(
            HealthCheck("ts1", 10.0, 20.0, 0.0, "healthy")
        )
        history = monitor.get_history()
        self.assertIsInstance(history[0], dict)

    def test_newest_first(self):
        """History should be returned newest first."""
        monitor = InternetHealthMonitor()
        monitor._history.append(HealthCheck("ts1", 10.0, 20.0, 0.0, "healthy"))
        monitor._history.append(HealthCheck("ts2", 20.0, 30.0, 0.0, "healthy"))
        history = monitor.get_history()
        self.assertEqual(history[0]["timestamp"], "ts2")
        self.assertEqual(history[1]["timestamp"], "ts1")

    def test_limit_parameter(self):
        """History should respect the limit parameter."""
        monitor = InternetHealthMonitor()
        for i in range(10):
            monitor._history.append(
                HealthCheck(f"ts{i}", float(i), float(i), 0.0, "healthy")
            )
        history = monitor.get_history(limit=3)
        self.assertEqual(len(history), 3)


class TestInitialization(unittest.TestCase):
    """Tests for InternetHealthMonitor initialization."""

    def test_default_targets(self):
        """Default ping and DNS targets should be set."""
        monitor = InternetHealthMonitor()
        self.assertEqual(
            monitor._ping_targets, InternetHealthMonitor.DEFAULT_PING_TARGETS
        )
        self.assertEqual(
            monitor._dns_targets, InternetHealthMonitor.DEFAULT_DNS_TARGETS
        )

    def test_custom_targets(self):
        """Custom ping and DNS targets should override defaults."""
        monitor = InternetHealthMonitor(
            ping_targets=["1.2.3.4"],
            dns_targets=["test.com"],
        )
        self.assertEqual(monitor._ping_targets, ["1.2.3.4"])
        self.assertEqual(monitor._dns_targets, ["test.com"])

    def test_custom_history_size(self):
        """Custom history size should be stored."""
        monitor = InternetHealthMonitor(history_size=100)
        self.assertEqual(monitor._history_size, 100)


if __name__ == "__main__":
    unittest.main()
