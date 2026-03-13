"""
Tests for daemon/services/alert_intelligence.py

Covers severity reclassification, alert categorization, assessment generation,
and suppress list management. All tests are self-contained with no external
dependencies (OpenSearch calls are not tested here).
"""

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.alert_intelligence import (
    reclassify_severity,
    categorize_alert,
    generate_assessment,
    suppress_rule,
    mark_false_positive,
    is_suppressed,
    load_suppress_list,
    save_suppress_list,
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
        """SURICATA TLS signature should categorize as protocol_anomaly."""
        result = categorize_alert("SURICATA TLS invalid record/version")
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
            "exfiltration": "data transfer",
            "reconnaissance": "scanning",
            "exploit": "exploitation",
            "policy": "policy violation",
            "protocol_anomaly": "protocol",
            "informational": "informational",
        }
        for cat, keyword in categories.items():
            result = generate_assessment(
                signature="TEST", category=cat, count=1,
                device_count=1, trend="stable",
            )
            assert keyword in result.lower(), f"Category '{cat}' should contain '{keyword}', got: {result}"


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
        device_entries = [e for e in data["per_device"].get(device, []) if e["signature_id"] == sig_id]
        assert len(device_entries) == 1
