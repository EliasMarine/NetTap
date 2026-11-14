"""
NetTap IoT Trust Scorer Service

Computes per-device trust scores (0-100, A-F grade) across three pillars:
  - Privacy  (20 pts): tracker domains, third-party data sharing
  - Security (35 pts): encryption ratio, protocol compliance, alerts
  - Behavior (30 pts): baseline adherence, new destinations, volume spikes, timing
OLD CODE: Privacy (30) also had telemetry volume and Security (40) a firmware signal. Nothing
can measure either (passive capture sees no firmware version, and no flow is attributed to a
tracker), so NET-171 took them out of the model rather than leave them as checks that never
report.

Every check is either measured or unavailable (its input is None: not measured, or only
a placeholder). The score is earned over available weight, so an unmeasured check never
reads as a pass or a fail (NET-158):
  score    = 100 x (points earned on available checks) / (weight of available checks)
  coverage = weight of available checks, out of 85 (the nine checks' total)
Below MIN_COVERAGE there is no score or grade; a pillar with no available check is None.

Also provides:
  - score_to_grade()       — numeric score to letter grade
  - compute_fleet_score()  — harmonic mean of the scored devices' scores

This is a pure computation class with no external dependencies (no OpenSearch,
no network calls).  The IoT monitor service prepares the stats dict from
OpenSearch queries and passes it here for scoring.
"""

import logging
from typing import Any, List

logger = logging.getLogger("nettap.services.iot_trust_scorer")

# ---------------------------------------------------------------------------
# Pillar weights (raw points) — sum to 85 since NET-171
# ---------------------------------------------------------------------------
# OLD CODE START — NET-171: telemetry (10) and firmware (5) left the model; nothing measures them
# PRIVACY_MAX = 30
# SECURITY_MAX = 40
# OLD CODE END
PRIVACY_MAX = 20
SECURITY_MAX = 35
BEHAVIOR_MAX = 30

# Privacy sub-component maximums (must sum to PRIVACY_MAX)
_PRIVACY_TRACKER_MAX = 10
# OLD CODE: _PRIVACY_TELEMETRY_MAX = 10 (NET-171: nothing measures telemetry)
_PRIVACY_THIRD_PARTY_MAX = 10

# Security sub-component maximums (must sum to SECURITY_MAX)
_SECURITY_ENCRYPTION_MAX = 15
_SECURITY_VIOLATIONS_MAX = 10
_SECURITY_ALERTS_MAX = 10
# OLD CODE: _SECURITY_FIRMWARE_MAX = 5 (NET-171: nothing measures firmware)

# Behavior sub-component maximums (must sum to BEHAVIOR_MAX)
_BEHAVIOR_BASELINE_MAX = 15
_BEHAVIOR_DESTINATIONS_MAX = 5
_BEHAVIOR_SPIKE_MAX = 5
_BEHAVIOR_TIMING_MAX = 5

# Each pillar's checks and their weights (the 9 checks; they sum to 85)
# OLD CODE: the 11 checks summing to 100 also had "telemetry_volume" (privacy, 10) and
# "firmware_signal" (security, 5) (NET-171: nothing measures them)
CHECK_WEIGHTS: dict[str, dict[str, int]] = {
    "privacy": {
        "tracker_domains": _PRIVACY_TRACKER_MAX,
        "third_party_orgs": _PRIVACY_THIRD_PARTY_MAX,
    },
    "security": {
        "encryption_ratio": _SECURITY_ENCRYPTION_MAX,
        "protocol_violations": _SECURITY_VIOLATIONS_MAX,
        "alert_count": _SECURITY_ALERTS_MAX,
    },
    "behavior": {
        "baseline_adherence": _BEHAVIOR_BASELINE_MAX,
        "new_destinations": _BEHAVIOR_DESTINATIONS_MAX,
        "volume_spike": _BEHAVIOR_SPIKE_MAX,
        "unusual_timing": _BEHAVIOR_TIMING_MAX,
    },
}
CHECK_COUNT = sum(len(checks) for checks in CHECK_WEIGHTS.values())
# Below this many points of measured checks a device gets no score or grade. Unchanged by
# NET-171: today's five measurable checks make 55 points, so a device still needs all five.
MIN_COVERAGE = 50

# Firmware signal values
# OLD CODE START — NET-158: "unknown" earned 2 of 5 points for a signal nothing measures
# _FIRMWARE_SCORES = {
#     "current": 5,
#     "recent": 3,
#     "unknown": 2,
#     "stale": 0,
# }
# OLD CODE END
# OLD CODE START — NET-171: firmware left the model; nothing measures it
# _FIRMWARE_SCORES = {
#     "current": 5,
#     "recent": 3,
#     "stale": 0,
# }
# OLD CODE END


def _pct(points: float, weight: int) -> int:
    """Points earned out of `weight`, as a whole 0-100 score."""
    # OLD CODE START — NET-256: round() rounds half to even, so 74.5 became 74 (grade C)
    # return int(round(max(0, min(100, points / weight * 100))))
    # OLD CODE END
    # + 0.5 then int: halves round up; clamped to 0-100, so int() never sees a negative
    return int(max(0, min(100, points / weight * 100)) + 0.5)


# OLD CODE START — NET-171: telemetry left the model; nothing measures it
# # Telemetry volume ceiling (bytes) — above this, score is 0
# _TELEMETRY_CEILING_BYTES = 100_000_000  # 100 MB
# OLD CODE END


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
              third_party_orgs      (int)   — distinct third-party organisations
              encryption_ratio      (float) — 0.0..1.0 fraction of TLS traffic
              protocol_violations   (int)   — protocol-compliance violations
              alert_count           (int)   — IDS / Suricata alerts
              baseline_adherence    (float) — 0.0..1.0 how closely device follows baseline
              new_destinations      (int)   — new IPs/domains not in baseline
              volume_spike          (bool)  — traffic volume spike detected
              unusual_timing        (bool)  — off-hours activity detected
            OLD CODE: telemetry_bytes and firmware_age_signal (NET-171: no longer checks;
            ignored if passed)

        Any key that is None or missing is unavailable: its check earns nothing and its
        weight leaves the denominator.

        Returns
        -------
        dict with keys: score and grade (None below MIN_COVERAGE), coverage (weight of
        the available checks, out of 85), checks_available, checks_total,
        privacy_score, security_score, behavior_score (0-100; None for a pillar with no
        available check), and per-check points breakdowns (None if unavailable).
        """
        # OLD CODE START — NET-158: every check counted, so a placeholder (telemetry 0 bytes,
        # firmware "unknown", no baseline, no eligible traffic) earned points as if measured
        # privacy_raw, privacy_breakdown = self._score_privacy(stats)
        # security_raw, security_breakdown = self._score_security(stats)
        # behavior_raw, behavior_breakdown = self._score_behavior(stats)
        #
        # # Total raw score is 0-100 since pillar maxes sum to 100
        # total_raw = privacy_raw + security_raw + behavior_raw
        # total_score = int(round(max(0, min(100, total_raw))))
        #
        # # Normalise each pillar to 0-100 for display
        # privacy_pct = (
        #     int(round((privacy_raw / PRIVACY_MAX) * 100)) if PRIVACY_MAX else 0
        # )
        # security_pct = (
        #     int(round((security_raw / SECURITY_MAX) * 100)) if SECURITY_MAX else 0
        # )
        # behavior_pct = (
        #     int(round((behavior_raw / BEHAVIOR_MAX) * 100)) if BEHAVIOR_MAX else 0
        # )
        #
        # return {
        #     "score": total_score,
        #     "grade": self.score_to_grade(total_score),
        #     "privacy_score": max(0, min(100, privacy_pct)),
        #     "security_score": max(0, min(100, security_pct)),
        #     "behavior_score": max(0, min(100, behavior_pct)),
        #     "privacy_breakdown": privacy_breakdown,
        #     "security_breakdown": security_breakdown,
        #     "behavior_breakdown": behavior_breakdown,
        # }
        # OLD CODE END
        pillars = {
            "privacy": self._score_privacy(stats),
            "security": self._score_security(stats),
            "behavior": self._score_behavior(stats),
        }
        result: dict[str, Any] = {}
        earned = 0.0
        coverage = 0
        checks_available = 0
        for name, breakdown in pillars.items():
            measured = {k: v for k, v in breakdown.items() if v is not None}
            weight = sum(CHECK_WEIGHTS[name][k] for k in measured)
            earned += sum(measured.values())
            coverage += weight
            checks_available += len(measured)
            result[f"{name}_score"] = (
                _pct(sum(measured.values()), weight) if weight else None
            )
            result[f"{name}_breakdown"] = {
                k: None if v is None else round(v, 2) for k, v in breakdown.items()
            }

        score = _pct(earned, coverage) if coverage >= MIN_COVERAGE else None
        return {
            "score": score,
            "grade": self.score_to_grade(score),
            "coverage": coverage,
            "checks_available": checks_available,
            "checks_total": CHECK_COUNT,
            **result,
        }

    def score_to_grade(self, score: int | None) -> str | None:
        """Map a numeric score (0-100) to a letter grade; no score, no grade.

        A: 90-100, B: 75-89, C: 60-74, D: 40-59, F: 0-39
        """
        if score is None:
            return None
        if score >= 90:
            return "A"
        if score >= 75:
            return "B"
        if score >= 60:
            return "C"
        if score >= 40:
            return "D"
        return "F"

    def compute_fleet_score(self, device_scores: List[int | None]) -> int | None:
        """Compute the fleet-wide trust score as the harmonic mean of scored devices.

        The harmonic mean penalises low outliers — one compromised device
        tanks the fleet score, which is the desired behaviour.

        Devices with no score (None) are left out. With no scored device (an empty
        fleet, or every device below the coverage line) there is no fleet score: None,
        never 100. Any device at 0 makes it 0, the harmonic mean's limit.
        """
        # OLD CODE START — NET-158: an empty fleet read 100 (a score nothing measured), and a
        # device at 0 was counted as a score of 1
        # if not device_scores:
        #     return 100
        #
        # # Filter out zeros to avoid division-by-zero in harmonic mean
        # nonzero = [s for s in device_scores if s > 0]
        # if not nonzero:
        #     return 0
        #
        # n = len(device_scores)
        # reciprocal_sum = sum(1.0 / s for s in nonzero)
        # # If some scores were zero, add a large reciprocal penalty per zero
        # zero_count = n - len(nonzero)
        # if zero_count > 0:
        #     # Treat zero-score devices as score=1 for the harmonic mean
        #     reciprocal_sum += zero_count * 1.0
        #
        # harmonic = n / reciprocal_sum
        # return int(round(max(0, min(100, harmonic))))
        # OLD CODE END
        scored = [s for s in device_scores if s is not None]
        if not scored:
            return None
        if min(scored) <= 0:
            return 0
        harmonic = len(scored) / sum(1.0 / s for s in scored)
        return int(round(max(0, min(100, harmonic))))

    # -----------------------------------------------------------------
    # Private scoring helpers
    # -----------------------------------------------------------------

    def _score_privacy(self, stats: dict) -> dict[str, float | None]:
        """Score the Privacy pillar (20 pts max).

        - Tracker domains:  10 pts — deduct 0.5 per tracker (0 = 10, 20+ = 0)
        - Third-party orgs: 10 pts — deduct 1.0 per org above 1 (1 = 10, 11+ = 0)
        OLD CODE: Telemetry volume, 10 pts, linear scale down over 100 MB (NET-171)

        A check whose input is None (or missing) is None: unavailable (NET-158).
        """
        # OLD CODE START — NET-158: a missing input was a measured 0
        # tracker_count = stats.get("tracker_domain_count", 0)
        # telemetry_bytes = stats.get("telemetry_bytes", 0)
        # third_party_orgs = stats.get("third_party_orgs", 0)
        # OLD CODE END
        tracker_count = stats.get("tracker_domain_count")
        # OLD CODE: telemetry_bytes = stats.get("telemetry_bytes") (NET-171)
        third_party_orgs = stats.get("third_party_orgs")

        # Tracker domains: 10 - 0.5 * count, clamped to [0, 10]
        tracker_score = (
            None
            if tracker_count is None
            else max(0, _PRIVACY_TRACKER_MAX - 0.5 * tracker_count)
        )

        # OLD CODE START — NET-171: nothing measures telemetry, so it is not a check
        # # Telemetry volume: linear from 10 (0 bytes) to 0 (100 MB+)
        # if telemetry_bytes is None:
        #     telemetry_score = None
        # elif telemetry_bytes >= _TELEMETRY_CEILING_BYTES:
        #     telemetry_score = 0
        # else:
        #     telemetry_score = _PRIVACY_TELEMETRY_MAX * (
        #         1.0 - telemetry_bytes / _TELEMETRY_CEILING_BYTES
        #     )
        # OLD CODE END

        # Third-party orgs: 10 - 1.0 * (orgs - 1), clamped to [0, 10]
        third_party_score = (
            None
            if third_party_orgs is None
            else max(0, _PRIVACY_THIRD_PARTY_MAX - 1.0 * max(0, third_party_orgs - 1))
        )

        breakdown = {
            "tracker_domains": tracker_score,
            # OLD CODE: "telemetry_volume": telemetry_score, (NET-171)
            "third_party_orgs": third_party_score,
        }
        # OLD CODE START — NET-158: rounded, and totalled over every check
        # total = tracker_score + telemetry_score + third_party_score
        # breakdown = {
        #     "tracker_domains": round(tracker_score, 2),
        #     "telemetry_volume": round(telemetry_score, 2),
        #     "third_party_orgs": round(third_party_score, 2),
        # }
        # OLD CODE END
        return breakdown

    def _score_security(self, stats: dict) -> dict[str, float | None]:
        """Score the Security pillar (35 pts max).

        - Encryption ratio:    15 pts * ratio
        - Protocol violations: 10 pts — deduct 3 per violation
        - Alert count:         10 pts — deduct 2 per alert
        OLD CODE: Firmware signal, 5 pts (current=5, recent=3, stale=0) (NET-171)

        A check whose input is None (or missing) is None: unavailable (NET-158).
        """
        # OLD CODE START — NET-158: a missing input was a measured value
        # encryption_ratio = stats.get("encryption_ratio", 0.0)
        # protocol_violations = stats.get("protocol_violations", 0)
        # alert_count = stats.get("alert_count", 0)
        # firmware_signal = stats.get("firmware_age_signal", "unknown")
        # OLD CODE END
        encryption_ratio = stats.get("encryption_ratio")
        protocol_violations = stats.get("protocol_violations")
        alert_count = stats.get("alert_count")
        # OLD CODE: firmware_signal = stats.get("firmware_age_signal") (NET-171)

        # Encryption: 15 * ratio
        encryption_score = (
            None
            if encryption_ratio is None
            else _SECURITY_ENCRYPTION_MAX * encryption_ratio
        )

        # Protocol violations: 10 - 3 * count, clamped to [0, 10]
        violation_score = (
            None
            if protocol_violations is None
            else max(0, _SECURITY_VIOLATIONS_MAX - 3 * protocol_violations)
        )

        # Alerts: 10 - 2 * count, clamped to [0, 10]
        alert_score = (
            None
            if alert_count is None
            else max(0, _SECURITY_ALERTS_MAX - 2 * alert_count)
        )

        # OLD CODE START — NET-171: nothing measures firmware, so it is not a check
        # # Firmware: lookup; "unknown" (or anything unlisted) is not a measurement
        # firmware_score = _FIRMWARE_SCORES.get(firmware_signal)
        # OLD CODE END

        breakdown = {
            "encryption_ratio": encryption_score,
            "protocol_violations": violation_score,
            "alert_count": alert_score,
            # OLD CODE: "firmware_signal": firmware_score, (NET-171)
        }
        # OLD CODE START — NET-158: rounded, and totalled over every check
        # firmware_score = _FIRMWARE_SCORES.get(firmware_signal, 2)
        # total = encryption_score + violation_score + alert_score + firmware_score
        # breakdown = {
        #     "encryption_ratio": round(encryption_score, 2),
        #     "protocol_violations": round(violation_score, 2),
        #     "alert_count": round(alert_score, 2),
        #     "firmware_signal": round(firmware_score, 2),
        # }
        # OLD CODE END
        return breakdown

    def _score_behavior(self, stats: dict) -> dict[str, float | None]:
        """Score the Behavior pillar (30 pts max).

        - Baseline adherence: 15 pts * adherence ratio
        - New destinations:    5 pts — deduct 1 per new destination
        - Volume spike:        5 pts if no spike, 0 if spike
        - Unusual timing:      5 pts if normal, 0 if unusual

        A check whose input is None (or missing) is None: unavailable (NET-158).
        """
        # OLD CODE START — NET-158: a missing input was a measured value
        # baseline_adherence = stats.get("baseline_adherence", 0.0)
        # new_destinations = stats.get("new_destinations", 0)
        # volume_spike = stats.get("volume_spike", False)
        # unusual_timing = stats.get("unusual_timing", False)
        # OLD CODE END
        baseline_adherence = stats.get("baseline_adherence")
        new_destinations = stats.get("new_destinations")
        volume_spike = stats.get("volume_spike")
        unusual_timing = stats.get("unusual_timing")

        # Baseline adherence: 15 * ratio
        baseline_score = (
            None
            if baseline_adherence is None
            else _BEHAVIOR_BASELINE_MAX * baseline_adherence
        )

        # New destinations: 5 - 1 * count, clamped to [0, 5]
        destination_score = (
            None
            if new_destinations is None
            else max(0, _BEHAVIOR_DESTINATIONS_MAX - 1 * new_destinations)
        )

        # Volume spike: binary
        spike_score = (
            None if volume_spike is None else 0 if volume_spike else _BEHAVIOR_SPIKE_MAX
        )

        # Unusual timing: binary
        timing_score = (
            None
            if unusual_timing is None
            else 0
            if unusual_timing
            else _BEHAVIOR_TIMING_MAX
        )

        breakdown = {
            "baseline_adherence": baseline_score,
            "new_destinations": destination_score,
            "volume_spike": spike_score,
            "unusual_timing": timing_score,
        }
        # OLD CODE START — NET-158: rounded, and totalled over every check
        # total = baseline_score + destination_score + spike_score + timing_score
        # breakdown = {
        #     "baseline_adherence": round(baseline_score, 2),
        #     "new_destinations": round(destination_score, 2),
        #     "volume_spike": round(spike_score, 2),
        #     "unusual_timing": round(timing_score, 2),
        # }
        # OLD CODE END
        return breakdown
