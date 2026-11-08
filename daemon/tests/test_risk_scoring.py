"""
Tests for daemon/services/risk_scoring.py

NET-209: three factors (alerts 50, connection anomaly 25, upload spike 25), each device compared
with its own usual day, and the volume factors scored only alongside a high or critical alert in
the device's own traffic. Rules: Debugging/THREAT-SCORING.md.
"""

import unittest

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.risk_scoring import RiskScorer

# OLD CODE: the five-factor tests (alert tiers by count, stddev anomaly, external ratio, port
# lists, upload ratio) went with those factors in NET-209; see
# `git show origin/main:daemon/tests/test_risk_scoring.py`

MB, GB = 1000**2, 1000**3
NOT_SCORED = "not scored without a high or critical alert"


def _days(conns, sent=None):
    """History rows, one per earlier day."""
    sent = sent or [0] * len(conns)
    return [{"connections": c, "upload_bytes": b} for c, b in zip(conns, sent)]


def _factor(result, name):
    return next(f for f in result["factors"] if f["name"] == name)


class TestAlertsFactor(unittest.TestCase):
    """Distinct signatures in the device's own traffic, each at its worst severity (rule 5)."""

    def setUp(self):
        self.scorer = RiskScorer()

    def test_no_signatures_is_zero(self):
        self.assertEqual(
            self.scorer.score_alerts({}, 0), (0, "No alerts in this device's own traffic")
        )

    def test_points_per_severity(self):
        for severity, points in ((1, 50), (2, 25), (3, 5), (4, 1)):
            with self.subTest(severity=severity):
                self.assertEqual(self.scorer.score_alerts({"S": severity}, 1)[0], points)

    def test_distinct_signatures_add_up(self):
        self.assertEqual(self.scorer.score_alerts({"A": 3, "B": 3, "C": 4}, 9)[0], 11)

    def test_capped_at_50(self):
        self.assertEqual(self.scorer.score_alerts({"A": 2, "B": 2, "C": 2}, 3)[0], 50)

    def test_description_counts_signatures_and_alerts(self):
        self.assertEqual(
            self.scorer.score_alerts({"A": 3, "B": 4}, 1234)[1],
            "2 signatures in its own traffic (1,234 alerts), worst medium",
        )
        self.assertEqual(
            self.scorer.score_alerts({"A": 1}, 1)[1],
            "1 signature in its own traffic (1 alert), worst critical",
        )

    def test_one_critical_own_signature_is_high_alone(self):
        result = self.scorer.score_device({"signatures": {"ET MALWARE x": 1}, "alert_count": 1})
        self.assertEqual((result["score"], result["level"]), (50, "high"))


class TestConnectionAnomaly(unittest.TestCase):
    """Connections opened vs the device's median day (rule 11)."""

    def setUp(self):
        self.scorer = RiskScorer()

    def _points(self, count, usual, window_days=1.0, corroborated=True):
        return self.scorer.score_connection_anomaly(count, usual, window_days, corroborated)

    def test_tiers(self):
        usual = [200] * 7
        for count, points in ((590, 0), (600, 10), (900, 10), (1000, 25)):
            with self.subTest(count=count):
                self.assertEqual(self._points(count, usual)[0], points)

    def test_needs_500_connections(self):
        self.assertEqual(self._points(499, [10] * 7)[0], 0)
        self.assertEqual(self._points(500, [10] * 7)[0], 25)

    def test_needs_three_earlier_days(self):
        points, description = self._points(5000, [100, 100])
        self.assertEqual(points, 0)
        self.assertEqual(
            description, "5,000 connections; not enough earlier days to compare with"
        )

    def test_description_gives_the_facts(self):
        self.assertEqual(self._points(1000, [200] * 7)[1], "1,000 connections, 5.0× its usual")

    def test_days_without_traffic_are_not_part_of_the_usual_day(self):
        # Three active days of 300: 1,000 is 3.3× (10). Counting the four quiet days, the
        # median would be 0 and any count a spike (25).
        result = RiskScorer().score_device(
            {
                "connections": 1000,
                "history": _days([300, 0, 300, 0, 0, 300, 0]),
                "corroborated": True,
            }
        )
        self.assertEqual(_factor(result, "connection_anomaly")["score"], 10)

    def test_a_sub_day_window_is_compared_with_a_whole_usual_day(self):
        # One hour of 600 vs a usual day of 200 is 3× (10); scaled to the hour it would be 72×
        result = RiskScorer().score_device(
            {
                "connections": 600,
                "history": _days([200] * 7),
                "window_days": 1 / 24,
                "corroborated": True,
            }
        )
        self.assertEqual(_factor(result, "connection_anomaly")["score"], 10)

    def test_a_multi_day_window_is_compared_with_as_many_usual_days(self):
        # 7 days of 4,200 vs 7 × 200 is 3× (10), not 21×
        result = RiskScorer().score_device(
            {
                "connections": 4200,
                "history": _days([200] * 7),
                "window_days": 7.0,
                "corroborated": True,
            }
        )
        self.assertEqual(_factor(result, "connection_anomaly")["score"], 10)


class TestUploadSpike(unittest.TestCase):
    """Bytes sent to the internet vs the device's median day, with published floors (rule 13)."""

    def setUp(self):
        self.scorer = RiskScorer()

    def _points(self, sent, usual, corroborated=True):
        return self.scorer.score_upload_spike(sent, usual, 1.0, corroborated)

    def test_a_few_kilobytes_never_score(self):
        # the screenshot's 11.7 KB at 77% upload scored 15/15 as "data exfiltration"
        self.assertEqual(self._points(11_700, [100] * 7)[0], 0)

    def test_needs_100_mb(self):
        self.assertEqual(self._points(99 * MB, [1 * MB] * 7)[0], 0)
        self.assertEqual(self._points(100 * MB, [1 * MB] * 7)[0], 10)

    def test_three_times_usual_is_10(self):
        self.assertEqual(self._points(150 * MB, [10 * MB] * 7)[0], 10)

    def test_three_times_usual_and_a_gigabyte_is_25(self):
        self.assertEqual(self._points(2 * GB, [100 * MB] * 7)[0], 25)

    def test_under_three_times_usual_is_zero(self):
        self.assertEqual(self._points(2 * GB, [1 * GB] * 7)[0], 0)

    def test_needs_three_earlier_days(self):
        self.assertEqual(
            self._points(5 * GB, [1 * MB, 1 * MB]),
            (0, "Sent 5.0 GB; not enough earlier days to compare with"),
        )

    def test_description_gives_the_facts(self):
        self.assertEqual(
            self._points(2 * GB, [100 * MB] * 7)[1],
            "Sent 2.0 GB to the internet, 20.0× its usual",
        )


class TestCorroboration(unittest.TestCase):
    """The volume factors score only with a high or critical alert in the device's own traffic."""

    BACKUP = {
        "connections": 5000,
        "upload_bytes": 5 * GB,
        "history": _days([500] * 7, [100 * MB] * 7),
    }

    def test_a_backup_alone_scores_nothing(self):
        result = RiskScorer().score_device(self.BACKUP)
        self.assertEqual(result["score"], 0)
        for name in ("connection_anomaly", "upload_spike"):
            factor = _factor(result, name)
            self.assertEqual(factor["score"], 0)
            self.assertTrue(factor["description"].endswith(NOT_SCORED), factor)

    def test_a_backup_with_a_low_alert_scores_only_the_alert(self):
        result = RiskScorer().score_device(
            {**self.BACKUP, "signatures": {"ET POLICY x": 4}, "alert_count": 2}
        )
        self.assertEqual(result["score"], 1)

    def test_a_backup_with_a_high_own_alert_is_scored(self):
        result = RiskScorer().score_device(
            {
                **self.BACKUP,
                "signatures": {"ET MALWARE x": 2},
                "alert_count": 3,
                "corroborated": True,
            }
        )
        self.assertEqual(
            [f["score"] for f in result["factors"]], [25, 25, 25]
        )
        self.assertEqual((result["score"], result["level"]), (75, "critical"))


class TestScoreDevice(unittest.TestCase):
    def test_three_factors_with_their_weights(self):
        result = RiskScorer().score_device({})
        self.assertEqual(
            [(f["name"], f["max"]) for f in result["factors"]],
            [("alert_count", 50), ("connection_anomaly", 25), ("upload_spike", 25)],
        )
        for f in result["factors"]:
            self.assertEqual(set(f), {"name", "score", "max", "description"})

    def test_empty_stats_are_zero_and_low(self):
        result = RiskScorer().score_device({})
        self.assertEqual((result["score"], result["level"]), (0, "low"))

    def test_everything_at_once_is_100(self):
        result = RiskScorer().score_device(
            {
                "signatures": {"A": 1, "B": 1},
                "alert_count": 9,
                "corroborated": True,
                "connections": 50_000,
                "upload_bytes": 50 * GB,
                "history": _days([500] * 7, [100 * MB] * 7),
            }
        )
        self.assertEqual((result["score"], result["level"]), (100, "critical"))


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


if __name__ == "__main__":
    unittest.main()
