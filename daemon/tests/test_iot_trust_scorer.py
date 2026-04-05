"""
Tests for daemon/services/iot_trust_scorer.py

All tests are pure-computation -- no external dependencies required.
"""

import sys
import os
from unittest.mock import MagicMock

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
        result = scorer.compute_fleet_score([])
        assert result == 100
