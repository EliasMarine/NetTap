"""
Tests for daemon/services/iot_trust_scorer.py

All tests are pure-computation -- no external dependencies required.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.iot_trust_scorer import IoTTrustScorer


@pytest.fixture
def scorer():
    return IoTTrustScorer()


# ---------------------------------------------------------------------------
# score_device
# ---------------------------------------------------------------------------


class TestScoreDevice:
    def test_perfect_device_gets_A(self, scorer):
        stats = {
            "tracker_domain_count": 0,
            "telemetry_bytes": 1000,
            "third_party_orgs": 1,
            "encryption_ratio": 1.0,
            "protocol_violations": 0,
            "alert_count": 0,
            "firmware_age_signal": "current",
            "baseline_adherence": 1.0,
            "new_destinations": 0,
            "volume_spike": False,
            "unusual_timing": False,
        }
        result = scorer.score_device(stats)
        assert result["score"] >= 90
        assert result["grade"] == "A"

    def test_terrible_device_gets_F(self, scorer):
        stats = {
            "tracker_domain_count": 30,
            "telemetry_bytes": 500_000_000,
            "third_party_orgs": 15,
            "encryption_ratio": 0.1,
            "protocol_violations": 5,
            "alert_count": 10,
            "firmware_age_signal": "stale",
            "baseline_adherence": 0.3,
            "new_destinations": 10,
            "volume_spike": True,
            "unusual_timing": True,
        }
        result = scorer.score_device(stats)
        assert result["score"] < 40
        assert result["grade"] == "F"

    def test_score_has_three_subscores(self, scorer):
        stats = {
            "tracker_domain_count": 5,
            "telemetry_bytes": 50_000,
            "third_party_orgs": 3,
            "encryption_ratio": 0.95,
            "protocol_violations": 0,
            "alert_count": 0,
            "firmware_age_signal": "unknown",
            "baseline_adherence": 0.9,
            "new_destinations": 1,
            "volume_spike": False,
            "unusual_timing": False,
        }
        result = scorer.score_device(stats)
        assert "privacy_score" in result
        assert "security_score" in result
        assert "behavior_score" in result
        assert 0 <= result["privacy_score"] <= 100
        assert 0 <= result["security_score"] <= 100
        assert 0 <= result["behavior_score"] <= 100


# ---------------------------------------------------------------------------
# score_to_grade
# ---------------------------------------------------------------------------


class TestGradeMapping:
    def test_grade_A(self, scorer):
        assert scorer.score_to_grade(95) == "A"

    def test_grade_B(self, scorer):
        assert scorer.score_to_grade(80) == "B"

    def test_grade_C(self, scorer):
        assert scorer.score_to_grade(65) == "C"

    def test_grade_D(self, scorer):
        assert scorer.score_to_grade(50) == "D"

    def test_grade_F(self, scorer):
        assert scorer.score_to_grade(30) == "F"


# ---------------------------------------------------------------------------
# compute_fleet_score
# ---------------------------------------------------------------------------


class TestFleetScore:
    def test_fleet_score_harmonic_mean(self, scorer):
        device_scores = [95, 90, 85, 20]
        result = scorer.compute_fleet_score(device_scores)
        assert result < 70  # Harmonic mean pulls down
        assert result > 0

    def test_empty_fleet(self, scorer):
        """NET-158: no devices is nothing measured, not 100."""
        assert scorer.compute_fleet_score([]) is None

    def test_all_unscored_fleet_has_no_score(self, scorer):
        assert scorer.compute_fleet_score([None, None]) is None

    def test_a_zero_makes_the_fleet_zero(self, scorer):
        """NET-158: a 0 was counted as 1, so [0, 100] read 2."""
        assert scorer.compute_fleet_score([0, 100]) == 0

    def test_unscored_devices_are_left_out(self, scorer):
        assert scorer.compute_fleet_score([None, 80, 40]) == 53


# ---------------------------------------------------------------------------
# Availability-aware score (NET-158)
# ---------------------------------------------------------------------------


MEASURED = {
    "tracker_domain_count": 0,
    "third_party_orgs": 1,
    "encryption_ratio": 0.5,
    "protocol_violations": 0,
    "alert_count": 0,
}
UNAVAILABLE = {
    "telemetry_bytes": None,
    "firmware_age_signal": "unknown",
    "baseline_adherence": None,
    "new_destinations": None,
    "volume_spike": None,
    "unusual_timing": None,
}


class TestAvailabilityAwareScore:
    def test_score_is_earned_over_available_weight(self, scorer):
        result = scorer.score_device({**MEASURED, **UNAVAILABLE})
        # 47.5 of 55 points: encryption 7.5 of 15, everything else full
        assert result["score"] == 86
        assert result["grade"] == "B"
        assert result["coverage"] == 55
        assert (result["checks_available"], result["checks_total"]) == (5, 11)
        assert result["security_breakdown"]["firmware_signal"] is None
        assert result["behavior_score"] is None  # no available check in the pillar

    def test_no_baseline_telemetry_firmware_or_encryption_means_no_score(self, scorer):
        """The old score gave this device 2 + 7.5 + 20 + 15 + 10 points it never earned."""
        result = scorer.score_device(
            {**MEASURED, **UNAVAILABLE, "encryption_ratio": None}
        )
        assert result["coverage"] == 40  # below the 50-point line
        assert result["score"] is None
        assert result["grade"] is None
        assert result["privacy_score"] == 100
        assert result["security_score"] == 100

    def test_a_measured_zero_stays_distinct_from_unavailable(self, scorer):
        result = scorer.score_device(
            {**MEASURED, **UNAVAILABLE, "tracker_domain_count": 40}
        )
        assert result["privacy_breakdown"]["tracker_domains"] == 0
        assert result["privacy_breakdown"]["telemetry_volume"] is None
