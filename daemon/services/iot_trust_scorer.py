"""
NetTap IoT Trust Scorer Service

Computes per-device trust scores (0-100, A-F grade) across three pillars:
  - Privacy  (30 pts): tracker domains, telemetry volume, third-party data sharing
  - Security (40 pts): encryption ratio, protocol compliance, alerts, firmware signals
  - Behavior (30 pts): baseline adherence, new destinations, volume spikes, timing

Also provides:
  - score_to_grade()       — numeric score to letter grade
  - compute_fleet_score()  — harmonic mean of all device scores

This is a pure computation class with no external dependencies (no OpenSearch,
no network calls).  The IoT monitor service prepares the stats dict from
OpenSearch queries and passes it here for scoring.
"""

import logging
from typing import List

logger = logging.getLogger("nettap.services.iot_trust_scorer")

# ---------------------------------------------------------------------------
# Pillar weights (raw points) — must sum to 100
# ---------------------------------------------------------------------------
PRIVACY_MAX = 30
SECURITY_MAX = 40
BEHAVIOR_MAX = 30

# Privacy sub-component maximums (must sum to PRIVACY_MAX)
_PRIVACY_TRACKER_MAX = 10
_PRIVACY_TELEMETRY_MAX = 10
_PRIVACY_THIRD_PARTY_MAX = 10

# Security sub-component maximums (must sum to SECURITY_MAX)
_SECURITY_ENCRYPTION_MAX = 15
_SECURITY_VIOLATIONS_MAX = 10
_SECURITY_ALERTS_MAX = 10
_SECURITY_FIRMWARE_MAX = 5

# Behavior sub-component maximums (must sum to BEHAVIOR_MAX)
_BEHAVIOR_BASELINE_MAX = 15
_BEHAVIOR_DESTINATIONS_MAX = 5
_BEHAVIOR_SPIKE_MAX = 5
_BEHAVIOR_TIMING_MAX = 5

# Firmware signal values
_FIRMWARE_SCORES = {
    "current": 5,
    "recent": 3,
    "unknown": 2,
    "stale": 0,
}

# Telemetry volume ceiling (bytes) — above this, score is 0
_TELEMETRY_CEILING_BYTES = 100_000_000  # 100 MB


class IoTTrustScorer:
    """Pure-computation trust scorer for IoT devices."""

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def score_device(self, stats: dict) -> dict:
        """Score a single device based on its behavioral statistics.

        Parameters
        ----------
        stats : dict
            Must contain the following keys:
              tracker_domain_count  (int)   — distinct tracker domains contacted
              telemetry_bytes       (int)   — bytes of telemetry traffic
              third_party_orgs      (int)   — distinct third-party organisations
              encryption_ratio      (float) — 0.0..1.0 fraction of TLS traffic
              protocol_violations   (int)   — protocol-compliance violations
              alert_count           (int)   — IDS / Suricata alerts
              firmware_age_signal   (str)   — one of current|recent|unknown|stale
              baseline_adherence    (float) — 0.0..1.0 how closely device follows baseline
              new_destinations      (int)   — new IPs/domains not in baseline
              volume_spike          (bool)  — traffic volume spike detected
              unusual_timing        (bool)  — off-hours activity detected

        Returns
        -------
        dict with keys: score, grade, privacy_score, security_score,
        behavior_score, and raw sub-component breakdowns.
        """
        privacy_raw, privacy_breakdown = self._score_privacy(stats)
        security_raw, security_breakdown = self._score_security(stats)
        behavior_raw, behavior_breakdown = self._score_behavior(stats)

        # Total raw score is 0-100 since pillar maxes sum to 100
        total_raw = privacy_raw + security_raw + behavior_raw
        total_score = int(round(max(0, min(100, total_raw))))

        # Normalise each pillar to 0-100 for display
        privacy_pct = int(round((privacy_raw / PRIVACY_MAX) * 100)) if PRIVACY_MAX else 0
        security_pct = int(round((security_raw / SECURITY_MAX) * 100)) if SECURITY_MAX else 0
        behavior_pct = int(round((behavior_raw / BEHAVIOR_MAX) * 100)) if BEHAVIOR_MAX else 0

        return {
            "score": total_score,
            "grade": self.score_to_grade(total_score),
            "privacy_score": max(0, min(100, privacy_pct)),
            "security_score": max(0, min(100, security_pct)),
            "behavior_score": max(0, min(100, behavior_pct)),
            "privacy_breakdown": privacy_breakdown,
            "security_breakdown": security_breakdown,
            "behavior_breakdown": behavior_breakdown,
        }

    def score_to_grade(self, score: int) -> str:
        """Map a numeric score (0-100) to a letter grade.

        A: 90-100, B: 75-89, C: 60-74, D: 40-59, F: 0-39
        """
        if score >= 90:
            return "A"
        if score >= 75:
            return "B"
        if score >= 60:
            return "C"
        if score >= 40:
            return "D"
        return "F"

    def compute_fleet_score(self, device_scores: List[int]) -> int:
        """Compute the fleet-wide trust score as the harmonic mean.

        The harmonic mean penalises low outliers — one compromised device
        tanks the fleet score, which is the desired behaviour.

        An empty list returns 100 (no devices = no risk).
        """
        if not device_scores:
            return 100

        # Filter out zeros to avoid division-by-zero in harmonic mean
        nonzero = [s for s in device_scores if s > 0]
        if not nonzero:
            return 0

        n = len(device_scores)
        reciprocal_sum = sum(1.0 / s for s in nonzero)
        # If some scores were zero, add a large reciprocal penalty per zero
        zero_count = n - len(nonzero)
        if zero_count > 0:
            # Treat zero-score devices as score=1 for the harmonic mean
            reciprocal_sum += zero_count * 1.0

        harmonic = n / reciprocal_sum
        return int(round(max(0, min(100, harmonic))))

    # -----------------------------------------------------------------
    # Private scoring helpers
    # -----------------------------------------------------------------

    def _score_privacy(self, stats: dict) -> tuple:
        """Score the Privacy pillar (30 pts max).

        - Tracker domains:  10 pts — deduct 0.5 per tracker (0 = 10, 20+ = 0)
        - Telemetry volume: 10 pts — linear scale down over 100 MB
        - Third-party orgs: 10 pts — deduct 1.0 per org above 1 (1 = 10, 11+ = 0)
        """
        tracker_count = stats.get("tracker_domain_count", 0)
        telemetry_bytes = stats.get("telemetry_bytes", 0)
        third_party_orgs = stats.get("third_party_orgs", 0)

        # Tracker domains: 10 - 0.5 * count, clamped to [0, 10]
        tracker_score = max(0, _PRIVACY_TRACKER_MAX - 0.5 * tracker_count)

        # Telemetry volume: linear from 10 (0 bytes) to 0 (100 MB+)
        if telemetry_bytes >= _TELEMETRY_CEILING_BYTES:
            telemetry_score = 0
        else:
            telemetry_score = _PRIVACY_TELEMETRY_MAX * (
                1.0 - telemetry_bytes / _TELEMETRY_CEILING_BYTES
            )

        # Third-party orgs: 10 - 1.0 * (orgs - 1), clamped to [0, 10]
        orgs_above_one = max(0, third_party_orgs - 1)
        third_party_score = max(0, _PRIVACY_THIRD_PARTY_MAX - 1.0 * orgs_above_one)

        total = tracker_score + telemetry_score + third_party_score

        breakdown = {
            "tracker_domains": round(tracker_score, 2),
            "telemetry_volume": round(telemetry_score, 2),
            "third_party_orgs": round(third_party_score, 2),
        }

        return total, breakdown

    def _score_security(self, stats: dict) -> tuple:
        """Score the Security pillar (40 pts max).

        - Encryption ratio:    15 pts * ratio
        - Protocol violations: 10 pts — deduct 3 per violation
        - Alert count:         10 pts — deduct 2 per alert
        - Firmware signal:      5 pts (current=5, recent=3, unknown=2, stale=0)
        """
        encryption_ratio = stats.get("encryption_ratio", 0.0)
        protocol_violations = stats.get("protocol_violations", 0)
        alert_count = stats.get("alert_count", 0)
        firmware_signal = stats.get("firmware_age_signal", "unknown")

        # Encryption: 15 * ratio
        encryption_score = _SECURITY_ENCRYPTION_MAX * encryption_ratio

        # Protocol violations: 10 - 3 * count, clamped to [0, 10]
        violation_score = max(0, _SECURITY_VIOLATIONS_MAX - 3 * protocol_violations)

        # Alerts: 10 - 2 * count, clamped to [0, 10]
        alert_score = max(0, _SECURITY_ALERTS_MAX - 2 * alert_count)

        # Firmware: lookup
        firmware_score = _FIRMWARE_SCORES.get(firmware_signal, 2)

        total = encryption_score + violation_score + alert_score + firmware_score

        breakdown = {
            "encryption_ratio": round(encryption_score, 2),
            "protocol_violations": round(violation_score, 2),
            "alert_count": round(alert_score, 2),
            "firmware_signal": round(firmware_score, 2),
        }

        return total, breakdown

    def _score_behavior(self, stats: dict) -> tuple:
        """Score the Behavior pillar (30 pts max).

        - Baseline adherence: 15 pts * adherence ratio
        - New destinations:    5 pts — deduct 1 per new destination
        - Volume spike:        5 pts if no spike, 0 if spike
        - Unusual timing:      5 pts if normal, 0 if unusual
        """
        baseline_adherence = stats.get("baseline_adherence", 0.0)
        new_destinations = stats.get("new_destinations", 0)
        volume_spike = stats.get("volume_spike", False)
        unusual_timing = stats.get("unusual_timing", False)

        # Baseline adherence: 15 * ratio
        baseline_score = _BEHAVIOR_BASELINE_MAX * baseline_adherence

        # New destinations: 5 - 1 * count, clamped to [0, 5]
        destination_score = max(0, _BEHAVIOR_DESTINATIONS_MAX - 1 * new_destinations)

        # Volume spike: binary
        spike_score = 0 if volume_spike else _BEHAVIOR_SPIKE_MAX

        # Unusual timing: binary
        timing_score = 0 if unusual_timing else _BEHAVIOR_TIMING_MAX

        total = baseline_score + destination_score + spike_score + timing_score

        breakdown = {
            "baseline_adherence": round(baseline_score, 2),
            "new_destinations": round(destination_score, 2),
            "volume_spike": round(spike_score, 2),
            "unusual_timing": round(timing_score, 2),
        }

        return total, breakdown
