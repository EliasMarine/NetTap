"""
Tests for daemon/services/alert_intelligence.py

Covers severity reclassification, alert categorization, assessment generation,
and suppress list management. All tests are self-contained with no external
dependencies (OpenSearch calls are not tested here).
"""

import sys
import os
import json
from datetime import datetime, timedelta, timezone

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.alert_intelligence import (
    reclassify_severity,
    categorize_alert,
    categorize_sub_category,
    generate_assessment,
    suppress_rule,
    mark_false_positive,
    is_suppressed,
    load_suppress_list,
    THREAT_CATEGORIES,
    SUB_CATEGORIES,
    MITRE_TECHNIQUES,
)
import services.alert_intelligence as alert_intelligence_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_suppress_path(tmp_path, monkeypatch):
    """Point _SUPPRESS_PATH to a temp directory for every test so tests
    never read/write the real suppress list and don't interfere with each other."""
    tmp_file = tmp_path / "nettap-suppress.json"
    monkeypatch.setattr(alert_intelligence_mod, "_SUPPRESS_PATH", tmp_file)


# ---------------------------------------------------------------------------
# Severity Reclassification
# ---------------------------------------------------------------------------


class TestReclassifySeverity:
    """Tests for reclassify_severity()."""

    def test_reclassify_severity_malware(self):
        """ET MALWARE signature should be reclassified to 1 (critical)."""
        result = reclassify_severity("ET MALWARE Win32/Emotet CnC Activity", 2)
        assert result == 1

    def test_reclassify_severity_info(self):
        """ET INFO signature should be reclassified to 5 (info)."""
        result = reclassify_severity("ET INFO Session Traversal Utilities", 1)
        assert result == 5

    def test_reclassify_severity_policy(self):
        """ET POLICY signature should be reclassified to 4 (low)."""
        result = reclassify_severity("ET POLICY PE EXE or DLL Windows file download", 1)
        assert result == 4

    def test_reclassify_severity_unknown(self):
        """Unknown prefix falls back to mapped Suricata severity.
        Suricata severity 1 maps to NetTap 2, severity 2 maps to 3,
        anything else maps to 4."""
        # Suricata sev 1 -> NetTap 2
        assert reclassify_severity("CUSTOM RULE something", 1) == 2
        # Suricata sev 2 -> NetTap 3
        assert reclassify_severity("CUSTOM RULE something", 2) == 3
        # Suricata sev 3 -> NetTap 4
        assert reclassify_severity("CUSTOM RULE something", 3) == 4

    def test_reclassify_severity_trojan(self):
        """ET TROJAN signature should be critical (1)."""
        assert reclassify_severity("ET TROJAN Agent Tesla", 3) == 1

    def test_reclassify_severity_scan(self):
        """ET SCAN signature should be medium (3)."""
        assert reclassify_severity("ET SCAN Nmap SYN Scan", 1) == 3

    def test_reclassify_severity_none_signature(self):
        """None/empty signature falls back to mapped original severity."""
        assert reclassify_severity(None, 1) == 2
        assert reclassify_severity("", 2) == 3

    def test_reclassify_severity_case_insensitive(self):
        """Signature prefix matching is case-insensitive."""
        assert reclassify_severity("et malware Something", 3) == 1
        assert reclassify_severity("Et Info Something", 1) == 5


# ---------------------------------------------------------------------------
# Alert Categorization
# ---------------------------------------------------------------------------


class TestCategorizeAlert:
    """Tests for categorize_alert()."""

    def test_categorize_alert_malware(self):
        """Signature containing MALWARE should categorize as malware_c2."""
        result = categorize_alert("ET MALWARE Win32/Emotet CnC Activity")
        assert result == "malware_c2"

    def test_categorize_alert_scan(self):
        """Signature containing SCAN should categorize as reconnaissance."""
        result = categorize_alert("ET SCAN Nmap SYN Scan Detected")
        assert result == "reconnaissance"

    def test_categorize_alert_unknown(self):
        """Signature with no matching pattern returns informational."""
        result = categorize_alert("SOME COMPLETELY UNKNOWN RULE")
        assert result == "informational"

    def test_categorize_alert_exploit(self):
        """Signature containing EXPLOIT should categorize as exploit."""
        result = categorize_alert("ET EXPLOIT Apache Struts RCE")
        assert result == "exploit"

    def test_categorize_alert_policy(self):
        """Signature containing POLICY should categorize as policy."""
        result = categorize_alert("ET POLICY PE EXE Download")
        assert result == "policy"

    def test_categorize_alert_protocol_anomaly(self):
        """SURICATA STREAM signature should categorize as protocol_anomaly."""
        result = categorize_alert("SURICATA STREAM ESTABLISHED packet out of window")
        assert result == "protocol_anomaly"

    def test_categorize_alert_none_signature(self):
        """None/empty signature returns informational."""
        assert categorize_alert(None) == "informational"
        assert categorize_alert("") == "informational"


# ---------------------------------------------------------------------------
# Assessment Generation
# ---------------------------------------------------------------------------


class TestGenerateAssessment:
    """Tests for generate_assessment()."""

    def test_generate_assessment_targeted(self):
        """device_count=1 should mention 'targeted' in the assessment."""
        result = generate_assessment(
            signature="ET MALWARE Something",
            category="malware_c2",
            count=5,
            device_count=1,
            trend="stable",
        )
        assert "targeted" in result.lower()

    def test_generate_assessment_noisy(self):
        """device_count=30 should mention 'noisy rule' in the assessment."""
        result = generate_assessment(
            signature="ET INFO Something",
            category="informational",
            count=500,
            device_count=30,
            trend="stable",
        )
        assert "noisy rule" in result.lower()

    def test_generate_assessment_limited_spread(self):
        """device_count=2 should mention 'limited spread'."""
        result = generate_assessment(
            signature="ET SCAN Something",
            category="reconnaissance",
            count=10,
            device_count=2,
            trend="stable",
        )
        assert "limited spread" in result.lower()

    def test_generate_assessment_increasing_high_volume(self):
        """count>100 with increasing trend should mention 'investigate promptly'."""
        result = generate_assessment(
            signature="ET MALWARE Something",
            category="malware_c2",
            count=200,
            device_count=1,
            trend="increasing",
        )
        assert "investigate promptly" in result.lower()

    def test_generate_assessment_decreasing(self):
        """Decreasing trend should mention 'declining'."""
        result = generate_assessment(
            signature="ET SCAN Something",
            category="reconnaissance",
            count=5,
            device_count=1,
            trend="decreasing",
        )
        assert "declining" in result.lower()

    def test_generate_assessment_device_type_mobile_malware(self):
        """iOS device with malware_c2 should mention 'warrants attention'."""
        result = generate_assessment(
            signature="ET MALWARE Something",
            category="malware_c2",
            count=5,
            device_count=1,
            trend="stable",
            device_type="iOS",
        )
        assert "warrants attention" in result.lower()

    def test_generate_assessment_device_type_linux(self):
        """Linux device with malware_c2 should mention 'expected services'."""
        result = generate_assessment(
            signature="ET MALWARE Something",
            category="malware_c2",
            count=5,
            device_count=1,
            trend="stable",
            device_type="Linux",
        )
        assert "expected services" in result.lower()

    def test_generate_assessment_category_messages(self):
        """Each category should produce a distinct opening sentence."""
        categories = {
            "malware_c2": "malicious",
            "credential_abuse": "credential abuse",
            "exfiltration": "data transfer",
            "reconnaissance": "scanning",
            "exploit": "exploitation",
            "policy": "policy violation",
            "protocol_anomaly": "protocol",
            "geo_anomaly": "geographic",
            "encrypted_threats": "encrypted traffic",
            "iot_anomaly": "device behavior",
            "dos": "denial of service",
            "sensitive_data": "sensitive data",
            "informational": "informational",
        }
        for cat, keyword in categories.items():
            result = generate_assessment(
                signature="TEST",
                category=cat,
                count=1,
                device_count=1,
                trend="stable",
            )
            assert keyword in result.lower(), (
                f"Category '{cat}' should contain '{keyword}', got: {result}"
            )


# ---------------------------------------------------------------------------
# Suppress List Management
# ---------------------------------------------------------------------------


class TestSuppressList:
    """Tests for suppress/false-positive management."""

    def test_suppress_and_check(self):
        """Suppressing a rule globally should make is_suppressed return True."""
        sig_id = 2024001
        # Before suppress
        assert is_suppressed(sig_id) is False
        # Suppress globally
        suppress_rule(sig_id, reason="Too noisy")
        # After suppress
        assert is_suppressed(sig_id) is True

    def test_false_positive(self):
        """Marking a signature as false positive should make is_suppressed return True."""
        sig_id = 2024002
        assert is_suppressed(sig_id) is False
        mark_false_positive(sig_id, reason="Known safe traffic")
        assert is_suppressed(sig_id) is True

    def test_is_suppressed_per_device(self):
        """Per-device suppression only affects the specified device IP."""
        sig_id = 2024003
        device_a = "192.168.1.100"
        device_b = "192.168.1.200"

        # Suppress only for device_a
        suppress_rule(sig_id, device_ip=device_a, reason="Safe on this device")

        # device_a should be suppressed
        assert is_suppressed(sig_id, device_ip=device_a) is True
        # device_b should NOT be suppressed
        assert is_suppressed(sig_id, device_ip=device_b) is False
        # Global check (no device_ip) should NOT be suppressed
        assert is_suppressed(sig_id) is False

    def test_suppress_idempotent(self):
        """Suppressing the same rule twice should not create duplicates."""
        sig_id = 2024004
        suppress_rule(sig_id, reason="First")
        suppress_rule(sig_id, reason="Second")

        data = load_suppress_list()
        global_entries = [e for e in data["global"] if e["signature_id"] == sig_id]
        assert len(global_entries) == 1

    def test_false_positive_idempotent(self):
        """Marking the same FP twice should not create duplicates."""
        sig_id = 2024005
        mark_false_positive(sig_id, reason="First")
        mark_false_positive(sig_id, reason="Second")

        data = load_suppress_list()
        fp_entries = [e for e in data["false_positives"] if e["signature_id"] == sig_id]
        assert len(fp_entries) == 1

    def test_empty_suppress_list(self):
        """Loading a non-existent suppress file returns default structure."""
        data = load_suppress_list()
        assert "global" in data
        assert "per_device" in data
        assert "false_positives" in data
        assert data["global"] == []

    def test_suppress_per_device_idempotent(self):
        """Per-device suppression of same rule twice should not duplicate."""
        sig_id = 2024006
        device = "10.0.0.1"
        suppress_rule(sig_id, device_ip=device, reason="First")
        suppress_rule(sig_id, device_ip=device, reason="Second")

        data = load_suppress_list()
        device_entries = [
            e for e in data["per_device"].get(device, []) if e["signature_id"] == sig_id
        ]
        assert len(device_entries) == 1


# ---------------------------------------------------------------------------
# Enhancement Tests: Trend, Kill Chain, Baseline, TTL, Destination Boost
# ---------------------------------------------------------------------------


class TestComputeTrend:
    """Tests for improved trend detection."""

    def test_stable_few_events(self):
        from services.alert_intelligence import compute_trend

        result = compute_trend("2026-03-13T00:00:00Z", "2026-03-13T12:00:00Z", 3)
        assert result == "stable"

    def test_increasing_high_rate(self):
        from services.alert_intelligence import compute_trend

        # 500 events in 1 hour = rate 500/hr → increasing
        result = compute_trend("2026-03-13T00:00:00Z", "2026-03-13T01:00:00Z", 500)
        assert result == "increasing"

    def test_decreasing_low_rate(self):
        from services.alert_intelligence import compute_trend

        # 5 events over 48 hours = rate 0.1/hr → decreasing
        result = compute_trend("2026-03-11T00:00:00Z", "2026-03-13T00:00:00Z", 5)
        assert result == "decreasing"

    def test_invalid_timestamps(self):
        from services.alert_intelligence import compute_trend

        result = compute_trend("", "", 10)
        assert result == "stable"


class TestKillChainDetection:
    """Tests for kill chain correlation."""

    # OLD CODE START — NET-209: chains are built from each finding's real alert times now, so
    # groups without findings make none (see tests/test_alert_findings.py for the timing rules)
    # def test_detects_two_stage_chain(self):
    #     from services.alert_intelligence import detect_kill_chains
    #
    #     alerts = [
    #         {
    #             "source_ip": "10.0.0.5",
    #             "category": "reconnaissance",
    #             "signature": "ET SCAN",
    #         },
    #         {"source_ip": "10.0.0.5", "category": "exploit", "signature": "ET EXPLOIT"},
    #     ]
    #     chains = detect_kill_chains(alerts)
    #     assert len(chains) == 1
    #     assert chains[0]["source_ip"] == "10.0.0.5"
    #     assert len(chains[0]["stages"]) == 2
    #     assert 1 in chains[0]["stages"]  # recon
    #     assert 2 in chains[0]["stages"]  # exploit
    #
    # def test_full_kill_chain(self):
    #     from services.alert_intelligence import detect_kill_chains
    #
    #     alerts = [
    #         {
    #             "source_ip": "10.0.0.5",
    #             "category": "reconnaissance",
    #             "signature": "scan",
    #         },
    #         {"source_ip": "10.0.0.5", "category": "exploit", "signature": "exploit"},
    #         {"source_ip": "10.0.0.5", "category": "malware_c2", "signature": "c2"},
    #         {"source_ip": "10.0.0.5", "category": "exfiltration", "signature": "exfil"},
    #     ]
    #     chains = detect_kill_chains(alerts)
    #     assert len(chains) == 1
    #     assert len(chains[0]["stages"]) == 4
    #     assert "active intrusion" in chains[0]["assessment"]
    # OLD CODE END
    @staticmethod
    def _own(category, signature, hour):
        start = 1_762_128_000_000  # 2025-11-03T00:00:00Z
        return {
            "source_ip": "10.0.0.5",
            "category": category,
            "signature": signature,
            "findings": [
                {
                    "device": "10.0.0.5",
                    "own": True,
                    "count": 1,
                    "severity": 2,
                    "times": [(start + hour * 3_600_000, 1)],
                }
            ],
        }

    def test_detects_two_stage_chain(self):
        from services.alert_intelligence import detect_kill_chains

        chains = detect_kill_chains(
            [
                self._own("reconnaissance", "ET SCAN", 0),
                self._own("exploit", "ET EXPLOIT", 1),
            ]
        )
        assert len(chains) == 1
        assert chains[0]["source_ip"] == "10.0.0.5"
        assert chains[0]["stages"] == [1, 2]

    def test_full_kill_chain(self):
        from services.alert_intelligence import detect_kill_chains

        chains = detect_kill_chains(
            [
                self._own("reconnaissance", "scan", 0),
                self._own("exploit", "exploit", 1),
                self._own("malware_c2", "c2", 2),
                self._own("exfiltration", "exfil", 3),
            ]
        )
        assert len(chains) == 1
        assert len(chains[0]["stages"]) == 4
        assert "active intrusion" in chains[0]["assessment"]

    def test_no_chain_single_stage(self):
        from services.alert_intelligence import detect_kill_chains

        alerts = [
            {
                "source_ip": "10.0.0.5",
                "category": "reconnaissance",
                "signature": "scan",
            },
            {
                "source_ip": "10.0.0.5",
                "category": "reconnaissance",
                "signature": "scan2",
            },
        ]
        chains = detect_kill_chains(alerts)
        assert len(chains) == 0

    def test_separate_ips_no_chain(self):
        from services.alert_intelligence import detect_kill_chains

        alerts = [
            {
                "source_ip": "10.0.0.5",
                "category": "reconnaissance",
                "signature": "scan",
            },
            {"source_ip": "10.0.0.6", "category": "exploit", "signature": "exploit"},
        ]
        chains = detect_kill_chains(alerts)
        assert len(chains) == 0

    def test_ignores_non_kill_chain_categories(self):
        from services.alert_intelligence import detect_kill_chains

        alerts = [
            {"source_ip": "10.0.0.5", "category": "policy", "signature": "policy"},
            {"source_ip": "10.0.0.5", "category": "informational", "signature": "info"},
        ]
        chains = detect_kill_chains(alerts)
        assert len(chains) == 0


# OLD CODE START — NET-209: the internal-port boost and its parameters are gone (THREAT-SCORING.md
# rule 14); TestSeverityOrder below covers the new order
# class TestDestinationAwareBoost:
#     """Tests for severity boosting on sensitive internal ports."""
#
#     def test_exploit_on_internal_ssh_boosted(self):
#         from services.alert_intelligence import reclassify_severity
#
#         # OLD CODE START — NET-209: no port boost (THREAT-SCORING.md rule 14: a port list is not
#         # a sound indicator); a scan of an internal SSH port keeps its own severity
#         # # ET EXPLOIT = severity 1, but let's test ET SCAN (3) getting boosted
#         # sev = reclassify_severity(
#         #     "ET SCAN portscan", 3, dst_port=22, dst_ip="192.168.1.10"
#         # )
#         # assert sev == 2  # Boosted from 3 → 2
#         # OLD CODE END
#         sev = reclassify_severity(
#             "ET SCAN portscan", 3, dst_port=22, dst_ip="192.168.1.10"
#         )
#         assert sev == 3
#
#     def test_no_boost_on_external_ip(self):
#         from services.alert_intelligence import reclassify_severity
#
#         sev = reclassify_severity("ET SCAN portscan", 3, dst_port=22, dst_ip="8.8.8.8")
#         assert sev == 3  # No boost — external IP
#
#     def test_no_boost_on_safe_port(self):
#         from services.alert_intelligence import reclassify_severity
#
#         sev = reclassify_severity(
#             "ET SCAN portscan", 3, dst_port=443, dst_ip="192.168.1.10"
#         )
#         assert sev == 3  # 443 not in SENSITIVE_PORTS
#
#     def test_critical_not_boosted_past_1(self):
#         from services.alert_intelligence import reclassify_severity
#
#         sev = reclassify_severity(
#             "ET MALWARE bad", 1, dst_port=22, dst_ip="192.168.1.10"
#         )
#         assert sev == 1  # Already critical, can't go higher
# OLD CODE END


class TestSeverityOrder:
    """NET-209: context categories, then ET's own signature_severity, then the prefix table, then
    Suricata's classtype priority."""

    @pytest.mark.parametrize(
        "signature, priority, et, expected",
        [
            ("ET INFO Spotify P2P Client", 1, ["Major"], 5),  # context beats everything
            ("ET HUNTING Suspicious UA", 2, None, 5),
            (
                "ET POLICY curl User-Agent",
                2,
                ["Critical"],
                1,
            ),  # ET's rating beats the table
            (
                "ET MALWARE Agent CnC",
                1,
                "Minor",
                3,
            ),  # a plain string, as some feeds send it
            (
                "ET MALWARE Agent CnC",
                1,
                ["Unknown"],
                1,
            ),  # no usable rating: the prefix table
            ("Custom rule", 1, None, 2),  # last: Suricata's priority, 1 is high
            ("Custom rule", 2, None, 3),
            ("Custom rule", 3, None, 4),
        ],
    )
    def test_order(self, signature, priority, et, expected):
        from services.alert_intelligence import reclassify_severity

        assert reclassify_severity(signature, priority, et_severity=et) == expected


class TestSuppressTTL:
    """Tests for TTL-based suppress expiration."""

    def test_expired_suppress_not_blocked(self, monkeypatch, tmp_path):
        from services import alert_intelligence

        monkeypatch.setattr(
            alert_intelligence, "_SUPPRESS_PATH", tmp_path / "suppress.json"
        )

        # Write a suppress entry that expired yesterday
        expired_entry = {
            "global": [
                {
                    "signature_id": 999,
                    "reason": "test",
                    "suppressed_at": "2026-03-01T00:00:00+00:00",
                    "expires_at": "2026-03-12T00:00:00+00:00",  # Expired
                }
            ],
            "per_device": {},
            "false_positives": [],
        }
        (tmp_path / "suppress.json").write_text(json.dumps(expired_entry))

        assert not alert_intelligence.is_suppressed(999)

    def test_active_suppress_still_blocks(self, monkeypatch, tmp_path):
        import json
        from services import alert_intelligence

        monkeypatch.setattr(
            alert_intelligence, "_SUPPRESS_PATH", tmp_path / "suppress.json"
        )

        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        active_entry = {
            "global": [
                {
                    "signature_id": 888,
                    "reason": "test",
                    "suppressed_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": future,
                }
            ],
            "per_device": {},
            "false_positives": [],
        }
        (tmp_path / "suppress.json").write_text(json.dumps(active_entry))

        assert alert_intelligence.is_suppressed(888)


class TestBaseline:
    """Tests for baseline management."""

    def test_update_baseline_stores_history(self, monkeypatch, tmp_path):
        from services import alert_intelligence

        monkeypatch.setattr(
            alert_intelligence, "_BASELINE_PATH", tmp_path / "baselines.json"
        )

        summary = {"total_events": 100, "threat_score": 25, "categories": {}}
        result = alert_intelligence.update_baseline(summary)

        assert result["history_points"] == 1
        assert result["deviation"] == 1.0  # Not enough history for deviation

    def test_baseline_detects_anomaly(self, monkeypatch, tmp_path):
        from datetime import datetime, timezone

        from services import alert_intelligence

        monkeypatch.setattr(
            alert_intelligence, "_BASELINE_PATH", tmp_path / "baselines.json"
        )

        # Ten earlier hours of a 24 h view at 10 events per window
        baselines = {
            "history": [
                {
                    "hour": f"2026-11-02T{h:02d}",
                    "metric": "counted-v2",  # NET-209
                    "window_hours": 24,
                    "events_per_hour": 10 / 24,
                    "threat_score": 5,
                }
                for h in range(10)
            ]
        }
        (tmp_path / "baselines.json").write_text(json.dumps(baselines))

        # Current is 10x higher → anomalous
        summary = {"total_events": 100, "threat_score": 50, "categories": {}}
        now = datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc)
        result = alert_intelligence.update_baseline(summary, 24.0, now=now)

        assert result["deviation"] == 10.0
        assert result["avg_events"] == 10.0
        assert result["is_anomalous"] is True


class TestBaselineMetric:
    """NET-209: snapshots of the old count (every alert) are not compared with the new one."""

    def test_snapshots_from_before_are_dropped(self, monkeypatch, tmp_path):
        from datetime import datetime, timezone

        from services import alert_intelligence

        path = tmp_path / "baselines.json"
        monkeypatch.setattr(alert_intelligence, "_BASELINE_PATH", path)
        old = [
            {
                "hour": f"2026-11-02T{h:02d}",
                "window_hours": 24,
                "events_per_hour": 100.0,
            }
            for h in range(10)
        ]
        path.write_text(json.dumps({"history": old}))

        now = datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc)
        result = alert_intelligence.update_baseline({"total_events": 24}, 24.0, now=now)

        assert result["history_points"] == 1  # only this hour's new snapshot
        assert result["deviation"] == 1.0
        saved = json.loads(path.read_text())["history"]
        assert [h["metric"] for h in saved] == ["counted-v2"]


class TestBaselineIsFactual:
    """#95: the baseline was a list of requests, not of hours.

    Every summary request appended a point and the last 168 were called "7 days of hourly
    snapshots", so an open, auto-refreshing page made the baseline span minutes, and 24 h,
    7 d and single-device summaries were averaged together.
    """

    @pytest.fixture
    def ai(self, monkeypatch, tmp_path):
        from services import alert_intelligence

        monkeypatch.setattr(
            alert_intelligence, "_BASELINE_PATH", tmp_path / "baselines.json"
        )
        return alert_intelligence

    def _now(self, hour, minute=0):
        from datetime import datetime, timezone

        return datetime(2026, 11, 2, hour, minute, tzinfo=timezone.utc)

    def test_many_requests_in_one_hour_are_one_snapshot(self, ai):
        for minute in range(0, 60, 2):
            result = ai.update_baseline(
                {"total_events": 50 + minute}, 24.0, now=self._now(9, minute)
            )
        assert result["history_points"] == 1

    def test_only_recorded_views_are_kept(self, ai):
        ai.update_baseline({"total_events": 50}, 24.0, record=False, now=self._now(9))
        assert (
            ai.update_baseline(
                {"total_events": 50}, 24.0, record=False, now=self._now(10)
            )["history_points"]
            == 0
        )

    def test_window_lengths_are_compared_separately(self, ai):
        for hour in range(8):  # 7 d views with a high rate
            ai.update_baseline({"total_events": 7000}, 168.0, now=self._now(hour))
        for hour in range(8):  # 24 h views at 24 events per day
            ai.update_baseline({"total_events": 24}, 24.0, now=self._now(hour))
        result = ai.update_baseline({"total_events": 24}, 24.0, now=self._now(9))
        assert result["deviation"] == 1.0
        assert result["history_points"] == 9

    def test_per_request_points_from_before_are_dropped(self, ai, tmp_path):
        old = {
            "history": [
                {
                    "timestamp": "2026-11-02T09:00:00Z",
                    "total_events": 1,
                    "threat_score": 0,
                    "categories": {},
                }
            ]
            * 100
        }
        (tmp_path / "baselines.json").write_text(json.dumps(old))
        result = ai.update_baseline({"total_events": 500}, 24.0, now=self._now(10))
        assert result == {
            "deviation": 1.0,
            "avg_events": 0.0,
            "avg_threat_score": 0.0,
            "history_points": 1,
            "is_anomalous": False,
        }

    def test_live_means_the_window_ends_now(self, ai):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        hours, live = ai._window_hours(
            (now - timedelta(hours=24)).isoformat(), now.isoformat()
        )
        assert round(hours) == 24 and live
        assert ai._window_hours("2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z") == (
            168.0,
            False,
        )


# ---------------------------------------------------------------------------
# New Categories (6 additions to original 7)
# ---------------------------------------------------------------------------


class TestCategorizeAlertNewCategories:
    """Tests for the 6 new threat categories added in v3."""

    def test_categorize_credential_abuse_ssh_brute(self):
        """SSH Brute Force should categorize as credential_abuse."""
        result = categorize_alert("ET SCAN SSH Brute Force Attempt")
        assert result == "credential_abuse"

    def test_categorize_credential_abuse_password_spray(self):
        """Password Spray should categorize as credential_abuse."""
        result = categorize_alert("ET SCAN Password Spray Detected")
        assert result == "credential_abuse"

    def test_categorize_sensitive_data_cleartext(self):
        """Cleartext Password should categorize as sensitive_data."""
        result = categorize_alert("ET POLICY Cleartext Password in HTTP")
        assert result == "sensitive_data"

    def test_categorize_dos_syn_flood(self):
        """SYN Flood should categorize as dos."""
        result = categorize_alert("ET DOS SYN Flood Detected")
        assert result == "dos"

    def test_categorize_encrypted_threats_tls_invalid(self):
        """TLS Invalid record should categorize as encrypted_threats."""
        result = categorize_alert("SURICATA TLS Invalid record/version")
        assert result == "encrypted_threats"

    def test_categorize_iot_anomaly(self):
        """IoT/Smart Home alert should categorize as iot_anomaly."""
        result = categorize_alert("ET IoT Smart Home Device Anomaly")
        assert result == "iot_anomaly"

    def test_categorize_geo_anomaly(self):
        """GeoIP alert should categorize as geo_anomaly."""
        result = categorize_alert("ET GeoIP Unusual Country Connection")
        assert result == "geo_anomaly"

    def test_ordering_credential_before_recon(self):
        """Credential-abuse patterns must match before recon SCAN patterns."""
        # "ET SCAN SSH Brute Force" has both SCAN and Brute Force
        result = categorize_alert("ET SCAN SSH Brute Force")
        assert result == "credential_abuse"

    def test_ordering_sensitive_before_policy(self):
        """Sensitive data must match before policy (POLICY keyword)."""
        result = categorize_alert("ET POLICY Cleartext Password Transmission")
        assert result == "sensitive_data"

    def test_ordering_encrypted_before_protocol(self):
        """Encrypted threats must match before protocol_anomaly (SURICATA TLS)."""
        result = categorize_alert("SURICATA TLS Invalid handshake message")
        assert result == "encrypted_threats"


# ---------------------------------------------------------------------------
# Sub-Category Classification
# ---------------------------------------------------------------------------


class TestCategorizeSubCategory:
    """Tests for categorize_sub_category()."""

    def test_ssh_brute_sub(self):
        result = categorize_sub_category("ET SCAN SSH Brute Force", "credential_abuse")
        assert result == "ssh_brute"

    def test_rdp_brute_sub(self):
        result = categorize_sub_category("ET SCAN RDP Brute Force", "credential_abuse")
        assert result == "rdp_brute"

    def test_trojan_sub(self):
        result = categorize_sub_category("ET TROJAN Agent Tesla Callback", "malware_c2")
        assert result == "trojan"

    def test_botnet_sub(self):
        result = categorize_sub_category("ET MALWARE Known CnC Beacon", "malware_c2")
        assert result == "botnet"

    def test_dns_tunnel_sub(self):
        result = categorize_sub_category("ET DNS Tunnel Detected", "exfiltration")
        assert result == "dns_tunnel"

    def test_port_scan_sub(self):
        result = categorize_sub_category("ET SCAN Nmap Stealth Scan", "reconnaissance")
        assert result == "port_scan"

    def test_web_exploit_sub(self):
        result = categorize_sub_category(
            "ET WEB_SERVER SQL Injection Attempt", "exploit"
        )
        assert result == "web_exploit"

    def test_syn_flood_sub(self):
        result = categorize_sub_category("ET DOS SYN Flood Detected", "dos")
        assert result == "syn_flood"

    def test_no_match_returns_none(self):
        result = categorize_sub_category("SOME UNKNOWN RULE", "malware_c2")
        assert result is None

    def test_unknown_category_returns_none(self):
        result = categorize_sub_category("ET MALWARE Something", "nonexistent_category")
        assert result is None

    def test_none_signature_returns_none(self):
        result = categorize_sub_category(None, "malware_c2")
        assert result is None


# ---------------------------------------------------------------------------
# MITRE ATT&CK Techniques Structure
# ---------------------------------------------------------------------------


class TestMitreTechniques:
    """Tests for the MITRE_TECHNIQUES mapping structure."""

    def test_mitre_has_major_categories(self):
        """MITRE mapping should cover major threat categories."""
        expected = [
            "credential_abuse",
            "malware_c2",
            "exfiltration",
            "reconnaissance",
            "exploit",
            "dos",
        ]
        for cat in expected:
            assert cat in MITRE_TECHNIQUES, f"Missing MITRE mapping for {cat}"

    def test_mitre_technique_structure(self):
        """Each MITRE technique should have id, name, and description."""
        for cat, techniques in MITRE_TECHNIQUES.items():
            assert isinstance(techniques, list), f"{cat} techniques should be a list"
            for tech in techniques:
                assert "id" in tech, f"Technique in {cat} missing 'id'"
                assert "name" in tech, f"Technique in {cat} missing 'name'"
                assert "description" in tech, (
                    f"Technique in {cat} missing 'description'"
                )
                assert tech["id"].startswith("T"), (
                    f"MITRE ID should start with 'T': {tech['id']}"
                )

    def test_mitre_credential_abuse_has_brute_force(self):
        """credential_abuse should include T1110 (Brute Force)."""
        ids = [t["id"] for t in MITRE_TECHNIQUES["credential_abuse"]]
        assert "T1110" in ids


# ---------------------------------------------------------------------------
# THREAT_CATEGORIES / SUB_CATEGORIES Structure Tests
# ---------------------------------------------------------------------------


class TestThreatCategoriesStructure:
    """Tests for THREAT_CATEGORIES and SUB_CATEGORIES dict structure."""

    def test_all_13_categories_present(self):
        """THREAT_CATEGORIES should have exactly 13 entries."""
        expected = {
            "credential_abuse",
            "sensitive_data",
            "dos",
            "encrypted_threats",
            "malware_c2",
            "exfiltration",
            "reconnaissance",
            "exploit",
            "policy",
            "protocol_anomaly",
            "iot_anomaly",
            "geo_anomaly",
            "informational",
        }
        assert set(THREAT_CATEGORIES.keys()) == expected

    def test_category_required_fields(self):
        """Each category must have label, icon, color, description, patterns."""
        for cat_id, cat in THREAT_CATEGORIES.items():
            assert "label" in cat, f"{cat_id} missing 'label'"
            assert "icon" in cat, f"{cat_id} missing 'icon'"
            assert "color" in cat, f"{cat_id} missing 'color'"
            assert "description" in cat, f"{cat_id} missing 'description'"
            assert "patterns" in cat, f"{cat_id} missing 'patterns'"
            assert len(cat["patterns"]) > 0, f"{cat_id} has empty patterns"

    def test_sub_categories_cover_all_parents(self):
        """SUB_CATEGORIES should have entries for all 13 parent categories."""
        for cat_id in THREAT_CATEGORIES:
            assert cat_id in SUB_CATEGORIES, f"Missing SUB_CATEGORIES for {cat_id}"
            assert len(SUB_CATEGORIES[cat_id]) > 0, f"Empty sub-categories for {cat_id}"

    def test_sub_category_structure(self):
        """Each sub-category must have id, label, and patterns."""
        for parent_id, subs in SUB_CATEGORIES.items():
            for sub in subs:
                assert "id" in sub, f"Sub in {parent_id} missing 'id'"
                assert "label" in sub, f"Sub in {parent_id} missing 'label'"
                assert "patterns" in sub, f"Sub in {parent_id} missing 'patterns'"
                assert len(sub["patterns"]) > 0, (
                    f"Sub {sub['id']} in {parent_id} has empty patterns"
                )
