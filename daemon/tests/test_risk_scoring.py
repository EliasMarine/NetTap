"""
Tests for daemon/services/risk_scoring.py

Covers each scoring factor individually, combined scoring, risk level
boundaries, and edge cases. All tests are self-contained with no external
dependencies.
"""

import unittest

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.risk_scoring import RiskScorer


class TestAlertCountScoring(unittest.TestCase):
    """Tests for score_alert_count()."""

    def setUp(self):
        self.scorer = RiskScorer()

    def test_zero_alerts(self):
        """Zero alerts should score 0 points."""
        points, desc = self.scorer.score_alert_count(0)
        self.assertEqual(points, 0)
        self.assertIn("No alerts", desc)

    def test_one_alert(self):
        """1 alert scores 10 points."""
        points, _ = self.scorer.score_alert_count(1)
        self.assertEqual(points, 10)

    def test_two_alerts(self):
        """2 alerts scores 10 points."""
        points, _ = self.scorer.score_alert_count(2)
        self.assertEqual(points, 10)

    def test_three_alerts(self):
        """3 alerts scores 20 points."""
        points, _ = self.scorer.score_alert_count(3)
        self.assertEqual(points, 20)

    def test_five_alerts(self):
        """5 alerts scores 20 points."""
        points, _ = self.scorer.score_alert_count(5)
        self.assertEqual(points, 20)

    def test_six_alerts(self):
        """6 alerts scores 30 points."""
        points, _ = self.scorer.score_alert_count(6)
        self.assertEqual(points, 30)

    def test_ten_alerts(self):
        """10 alerts scores 30 points."""
        points, _ = self.scorer.score_alert_count(10)
        self.assertEqual(points, 30)

    def test_eleven_alerts(self):
        """11 alerts (10+) scores 35 points (max)."""
        points, _ = self.scorer.score_alert_count(11)
        self.assertEqual(points, 35)

    def test_large_alert_count(self):
        """Very large alert count still scores 35."""
        points, _ = self.scorer.score_alert_count(1000)
        self.assertEqual(points, 35)

    def test_negative_alerts(self):
        """Negative alert count treated as zero."""
        points, _ = self.scorer.score_alert_count(-5)
        self.assertEqual(points, 0)


class TestConnectionAnomalyScoring(unittest.TestCase):
    """Tests for score_connection_anomaly()."""

    def setUp(self):
        self.scorer = RiskScorer()

    def test_within_one_stddev(self):
        """Count within 1 stddev of avg scores 0."""
        points, _ = self.scorer.score_connection_anomaly(100, 100.0, 50.0)
        self.assertEqual(points, 0)

    def test_one_to_two_stddev(self):
        """Count 1-2 stddev above avg scores 10."""
        # avg=100, stddev=50, count=175 -> deviation=1.5
        points, _ = self.scorer.score_connection_anomaly(175, 100.0, 50.0)
        self.assertEqual(points, 10)

    def test_two_to_three_stddev(self):
        """Count 2-3 stddev above avg scores 15."""
        # avg=100, stddev=50, count=225 -> deviation=2.5
        points, _ = self.scorer.score_connection_anomaly(225, 100.0, 50.0)
        self.assertEqual(points, 15)

    def test_above_three_stddev(self):
        """Count 3+ stddev above avg scores 20."""
        # avg=100, stddev=50, count=300 -> deviation=4.0
        points, _ = self.scorer.score_connection_anomaly(300, 100.0, 50.0)
        self.assertEqual(points, 20)

    def test_zero_stddev(self):
        """Zero stddev returns 0 (cannot compute)."""
        points, desc = self.scorer.score_connection_anomaly(100, 100.0, 0.0)
        self.assertEqual(points, 0)
        self.assertIn("Insufficient", desc)

    def test_zero_avg(self):
        """Zero avg returns 0 (cannot compute)."""
        points, _ = self.scorer.score_connection_anomaly(100, 0.0, 10.0)
        self.assertEqual(points, 0)

    def test_below_avg(self):
        """Count below avg scores 0."""
        points, _ = self.scorer.score_connection_anomaly(50, 100.0, 50.0)
        self.assertEqual(points, 0)

    def test_negative_stddev(self):
        """Negative stddev returns 0 (invalid data)."""
        points, _ = self.scorer.score_connection_anomaly(100, 100.0, -10.0)
        self.assertEqual(points, 0)


class TestExternalRatioScoring(unittest.TestCase):
    """Tests for score_external_ratio()."""

    def setUp(self):
        self.scorer = RiskScorer()

    def test_no_connections(self):
        """Zero total connections scores 0."""
        points, _ = self.scorer.score_external_ratio(0, 0)
        self.assertEqual(points, 0)

    def test_low_external_ratio(self):
        """<30% external connections scores 0."""
        points, _ = self.scorer.score_external_ratio(20, 100)
        self.assertEqual(points, 0)

    def test_moderate_external_ratio(self):
        """30-60% external scores 5."""
        points, _ = self.scorer.score_external_ratio(45, 100)
        self.assertEqual(points, 5)

    def test_elevated_external_ratio(self):
        """60-80% external scores 10."""
        points, _ = self.scorer.score_external_ratio(70, 100)
        self.assertEqual(points, 10)

    def test_high_external_ratio(self):
        """>80% external scores 15."""
        points, _ = self.scorer.score_external_ratio(85, 100)
        self.assertEqual(points, 15)

    def test_all_external(self):
        """100% external scores 15."""
        points, _ = self.scorer.score_external_ratio(100, 100)
        self.assertEqual(points, 15)

    def test_boundary_thirty_percent(self):
        """Exactly 30% scores 5 (30-60% range)."""
        points, _ = self.scorer.score_external_ratio(30, 100)
        self.assertEqual(points, 5)


class TestSuspiciousPortsScoring(unittest.TestCase):
    """Tests for score_suspicious_ports()."""

    def setUp(self):
        self.scorer = RiskScorer()

    def test_empty_ports(self):
        """Empty port list scores 0."""
        points, _ = self.scorer.score_suspicious_ports([])
        self.assertEqual(points, 0)

    def test_only_safe_ports(self):
        """Only common ports scores 0."""
        points, _ = self.scorer.score_suspicious_ports([80, 443, 53, 22])
        self.assertEqual(points, 0)

    def test_unusual_ports(self):
        """Non-standard, non-suspicious ports scores 8."""
        points, _ = self.scorer.score_suspicious_ports([80, 443, 9200, 3000])
        self.assertEqual(points, 8)

    def test_suspicious_port_4444(self):
        """Port 4444 (known suspicious) scores 15."""
        points, _ = self.scorer.score_suspicious_ports([80, 4444])
        self.assertEqual(points, 15)

    def test_suspicious_port_31337(self):
        """Port 31337 (eleet) scores 15."""
        points, _ = self.scorer.score_suspicious_ports([31337])
        self.assertEqual(points, 15)

    def test_multiple_suspicious_ports(self):
        """Multiple suspicious ports still scores 15."""
        points, _ = self.scorer.score_suspicious_ports([4444, 5555, 6666])
        self.assertEqual(points, 15)

    def test_suspicious_overrides_unusual(self):
        """Suspicious ports take priority over unusual ports."""
        points, _ = self.scorer.score_suspicious_ports([9200, 3000, 4444])
        self.assertEqual(points, 15)

    def test_known_suspicious_ports_list(self):
        """All known suspicious ports are in the set."""
        expected = {4444, 5555, 6666, 8888, 9999, 31337, 12345, 65535}
        self.assertEqual(RiskScorer.SUSPICIOUS_PORTS, expected)


class TestDataExfiltrationScoring(unittest.TestCase):
    """Tests for score_data_exfiltration()."""

    def setUp(self):
        self.scorer = RiskScorer()

    def test_no_traffic(self):
        """Zero traffic scores 0."""
        points, _ = self.scorer.score_data_exfiltration(0, 0)
        self.assertEqual(points, 0)

    def test_normal_upload_ratio(self):
        """<10% upload scores 0."""
        points, _ = self.scorer.score_data_exfiltration(5, 95)
        self.assertEqual(points, 0)

    def test_slightly_elevated_upload(self):
        """10-30% upload scores 5."""
        points, _ = self.scorer.score_data_exfiltration(20, 80)
        self.assertEqual(points, 5)

    def test_elevated_upload(self):
        """30-50% upload scores 10."""
        points, _ = self.scorer.score_data_exfiltration(40, 60)
        self.assertEqual(points, 10)

    def test_high_upload(self):
        """>50% upload scores 15."""
        points, _ = self.scorer.score_data_exfiltration(60, 40)
        self.assertEqual(points, 15)

    def test_all_upload(self):
        """100% upload scores 15."""
        points, _ = self.scorer.score_data_exfiltration(100, 0)
        self.assertEqual(points, 15)

    def test_boundary_ten_percent(self):
        """Exactly 10% upload scores 5 (10-30% range)."""
        points, _ = self.scorer.score_data_exfiltration(10, 90)
        self.assertEqual(points, 5)


class TestRiskLevel(unittest.TestCase):
    """Tests for risk_level() static method."""

    def test_low_score_zero(self):
        self.assertEqual(RiskScorer.risk_level(0), "low")

    def test_low_score_24(self):
        self.assertEqual(RiskScorer.risk_level(24), "low")

    def test_medium_score_25(self):
        self.assertEqual(RiskScorer.risk_level(25), "medium")

    def test_medium_score_49(self):
        self.assertEqual(RiskScorer.risk_level(49), "medium")

    def test_high_score_50(self):
        self.assertEqual(RiskScorer.risk_level(50), "high")

    def test_high_score_74(self):
        self.assertEqual(RiskScorer.risk_level(74), "high")

    def test_critical_score_75(self):
        self.assertEqual(RiskScorer.risk_level(75), "critical")

    def test_critical_score_100(self):
        self.assertEqual(RiskScorer.risk_level(100), "critical")

    def test_negative_score(self):
        """Negative score should map to 'low'."""
        self.assertEqual(RiskScorer.risk_level(-10), "low")


class TestCombinedScoring(unittest.TestCase):
    """Tests for score_device() combined scoring."""

    def setUp(self):
        self.scorer = RiskScorer()

    def test_benign_device(self):
        """A device with no risk indicators scores low."""
        stats = {
            "alert_count": 0,
            "connection_count": 50,
            "network_avg_connections": 100.0,
            "network_stddev_connections": 50.0,
            "external_connection_count": 10,
            "total_connection_count": 50,
            "ports_used": [80, 443],
            "orig_bytes": 1000,
            "resp_bytes": 99000,
        }
        result = self.scorer.score_device(stats)
        self.assertLessEqual(result["score"], 24)
        self.assertEqual(result["level"], "low")
        self.assertEqual(len(result["factors"]), 5)

    def test_highly_suspicious_device(self):
        """A device with many risk indicators scores critical."""
        stats = {
            "alert_count": 50,
            "connection_count": 5000,
            "network_avg_connections": 100.0,
            "network_stddev_connections": 50.0,
            "external_connection_count": 90,
            "total_connection_count": 100,
            "ports_used": [4444, 31337, 65535],
            "orig_bytes": 80000,
            "resp_bytes": 20000,
        }
        result = self.scorer.score_device(stats)
        self.assertGreaterEqual(result["score"], 75)
        self.assertEqual(result["level"], "critical")

    def test_score_clamped_to_100(self):
        """Total score should never exceed 100."""
        stats = {
            "alert_count": 999,
            "connection_count": 99999,
            "network_avg_connections": 10.0,
            "network_stddev_connections": 1.0,
            "external_connection_count": 100,
            "total_connection_count": 100,
            "ports_used": [4444, 31337],
            "orig_bytes": 99999,
            "resp_bytes": 1,
        }
        result = self.scorer.score_device(stats)
        self.assertLessEqual(result["score"], 100)

    def test_empty_stats(self):
        """Empty/default stats should score 0."""
        result = self.scorer.score_device({})
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["level"], "low")

    def test_factors_have_required_keys(self):
        """Each factor should have name, score, max, description."""
        stats = {
            "alert_count": 5,
            "connection_count": 200,
            "network_avg_connections": 100.0,
            "network_stddev_connections": 50.0,
            "external_connection_count": 40,
            "total_connection_count": 100,
            "ports_used": [80, 443, 9200],
            "orig_bytes": 5000,
            "resp_bytes": 45000,
        }
        result = self.scorer.score_device(stats)
        for factor in result["factors"]:
            self.assertIn("name", factor)
            self.assertIn("score", factor)
            self.assertIn("max", factor)
            self.assertIn("description", factor)
            self.assertGreaterEqual(factor["score"], 0)
            self.assertLessEqual(factor["score"], factor["max"])

    def test_max_score_is_100(self):
        """Sum of all max weights equals 100."""
        total_max = (
            RiskScorer.WEIGHT_ALERT_COUNT
            + RiskScorer.WEIGHT_CONNECTION_ANOMALY
            + RiskScorer.WEIGHT_EXTERNAL_RATIO
            + RiskScorer.WEIGHT_SUSPICIOUS_PORTS
            + RiskScorer.WEIGHT_DATA_EXFILTRATION
        )
        self.assertEqual(total_max, 100)

    def test_medium_risk_device(self):
        """A device with moderate indicators scores medium."""
        stats = {
            "alert_count": 3,
            "connection_count": 200,
            "network_avg_connections": 100.0,
            "network_stddev_connections": 50.0,
            "external_connection_count": 50,
            "total_connection_count": 100,
            "ports_used": [80, 443, 9200],
            "orig_bytes": 15000,
            "resp_bytes": 85000,
        }
        result = self.scorer.score_device(stats)
        self.assertGreaterEqual(result["score"], 25)
        self.assertLessEqual(result["score"], 49)
        self.assertEqual(result["level"], "medium")


class TestEdgeCases(unittest.TestCase):
    """Edge case tests for RiskScorer."""

    def setUp(self):
        self.scorer = RiskScorer()

    def test_score_device_missing_keys(self):
        """Missing keys should default to zero/empty without error."""
        result = self.scorer.score_device({"alert_count": 5})
        self.assertIsInstance(result["score"], int)
        self.assertIn(result["level"], ("low", "medium", "high", "critical"))

    def test_zero_total_bytes(self):
        """Zero total bytes should not cause division error."""
        points, _ = self.scorer.score_data_exfiltration(0, 0)
        self.assertEqual(points, 0)

    def test_zero_total_connections(self):
        """Zero total connections should not cause division error."""
        points, _ = self.scorer.score_external_ratio(0, 0)
        self.assertEqual(points, 0)


if __name__ == "__main__":
    unittest.main()
