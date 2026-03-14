"""
Tests for daemon/services/threat_detection.py

Covers pure utility functions: Shannon entropy, beacon confidence scoring,
and RFC1918 internal IP detection. All tests are self-contained with no
external dependencies (OpenSearch calls are not tested here).
"""

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.threat_detection import (
    _shannon_entropy,
    _beacon_confidence,
    _is_internal,
)


# ---------------------------------------------------------------------------
# Shannon Entropy
# ---------------------------------------------------------------------------


class TestShannonEntropy:
    """Tests for _shannon_entropy()."""

    def test_shannon_entropy_random_high(self):
        """A random-looking string should have high entropy (>3.5)."""
        # Simulate a DGA-like string with varied characters
        result = _shannon_entropy("x7k2m9q4z1w8")
        assert result > 3.5, f"Expected high entropy, got {result}"

    def test_shannon_entropy_simple_low(self):
        """A repeated single character should have zero entropy."""
        result = _shannon_entropy("aaaaaa")
        assert result == 0.0, f"Expected 0.0 entropy for uniform string, got {result}"

    def test_shannon_entropy_empty(self):
        """An empty string should return 0.0."""
        result = _shannon_entropy("")
        assert result == 0.0

    def test_shannon_entropy_two_chars(self):
        """A string with exactly two equally distributed chars has entropy 1.0."""
        result = _shannon_entropy("ababab")
        assert abs(result - 1.0) < 0.01, f"Expected ~1.0, got {result}"


# ---------------------------------------------------------------------------
# Beacon Confidence
# ---------------------------------------------------------------------------


class TestBeaconConfidence:
    """Tests for _beacon_confidence()."""

    def test_beacon_confidence_high(self):
        """Low jitter + high count + common interval = high confidence score."""
        # cv=0.03 (<0.05 → +50), count=150 (>100 → +30), interval=60 (common → +20)
        result = _beacon_confidence(cv=0.03, count=150, interval=60.0)
        assert result == 100.0, f"Expected 100.0, got {result}"

    def test_beacon_confidence_low(self):
        """High jitter + low count + non-standard interval = low confidence."""
        # cv=0.14 (<0.15 → +20), count=12 (<20 → +0), interval=77 (not common → +0)
        result = _beacon_confidence(cv=0.14, count=12, interval=77.0)
        assert result == 20.0, f"Expected 20.0, got {result}"

    def test_beacon_confidence_medium(self):
        """Medium jitter + medium count + common interval = medium score."""
        # cv=0.07 (<0.10 → +35), count=55 (>50 → +20), interval=300 (common → +20)
        result = _beacon_confidence(cv=0.07, count=55, interval=300.0)
        assert result == 75.0, f"Expected 75.0, got {result}"

    def test_beacon_confidence_capped_at_100(self):
        """Score should never exceed 100."""
        result = _beacon_confidence(cv=0.01, count=200, interval=60.0)
        assert result <= 100.0


# ---------------------------------------------------------------------------
# Internal IP Detection
# ---------------------------------------------------------------------------


class TestIsInternal:
    """Tests for _is_internal()."""

    def test_is_internal_192_168(self):
        """192.168.x.x addresses are internal."""
        assert _is_internal("192.168.1.100") is True

    def test_is_internal_10(self):
        """10.x.x.x addresses are internal."""
        assert _is_internal("10.0.0.1") is True

    def test_is_internal_172_16(self):
        """172.16.x.x addresses are internal."""
        assert _is_internal("172.16.0.1") is True

    def test_is_internal_172_31(self):
        """172.31.x.x addresses are internal (upper bound of 172.16-31 range)."""
        assert _is_internal("172.31.255.254") is True

    def test_is_internal_external(self):
        """8.8.8.8 is a public IP and should return False."""
        assert _is_internal("8.8.8.8") is False

    def test_is_internal_external_1_1_1_1(self):
        """1.1.1.1 is external."""
        assert _is_internal("1.1.1.1") is False

    def test_is_internal_172_outside_range(self):
        """172.32.x.x is outside the RFC1918 range and should be external."""
        assert _is_internal("172.32.0.1") is False
