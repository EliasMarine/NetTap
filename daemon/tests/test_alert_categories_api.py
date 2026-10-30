"""
Tests for the enhanced alert categories API endpoints.

Covers:
- categorize_sub_category() classification for various signatures
- MITRE_TECHNIQUES structure validation
- THREAT_CATEGORIES required fields for the category hub
- _sparkline_interval() helper logic
"""

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.alert_intelligence import (
    THREAT_CATEGORIES,
    SUB_CATEGORIES,
    MITRE_TECHNIQUES,
    categorize_alert,
    categorize_sub_category,
)
from api.alerts import _sparkline_interval


# ---------------------------------------------------------------------------
# Sub-Category Classification (detailed cross-category tests)
# ---------------------------------------------------------------------------


class TestCategorizeSubCategory:
    """Tests for categorize_sub_category() across multiple categories."""

    def test_ssh_brute_in_credential_abuse(self):
        result = categorize_sub_category("ET SCAN SSH Brute Force Attempt", "credential_abuse")
        assert result == "ssh_brute"

    def test_rdp_brute_in_credential_abuse(self):
        result = categorize_sub_category("ET SCAN RDP Brute Force Login", "credential_abuse")
        assert result == "rdp_brute"

    def test_password_spray_in_credential_abuse(self):
        result = categorize_sub_category("Password Spray Attack Detected", "credential_abuse")
        assert result == "password_spray"

    def test_default_login_in_credential_abuse(self):
        result = categorize_sub_category("Default Login Attempt on Router", "credential_abuse")
        assert result == "default_login"

    def test_cleartext_creds_in_sensitive_data(self):
        result = categorize_sub_category("ET POLICY Cleartext Password in HTTP", "sensitive_data")
        assert result == "cleartext_creds"

    def test_pii_in_sensitive_data(self):
        result = categorize_sub_category("SSN Detected in Traffic", "sensitive_data")
        assert result == "pii_leak"

    def test_syn_flood_in_dos(self):
        result = categorize_sub_category("ET DOS SYN Flood Detected", "dos")
        assert result == "syn_flood"

    def test_amplification_in_dos(self):
        result = categorize_sub_category("NTP Amplification Attack", "dos")
        assert result == "amplification"

    def test_bad_cert_in_encrypted_threats(self):
        result = categorize_sub_category("SURICATA TLS Invalid certificate", "encrypted_threats")
        assert result == "bad_cert"

    def test_ja3_in_encrypted_threats(self):
        result = categorize_sub_category("Known-Bad JA3 Hash Detected", "encrypted_threats")
        assert result == "known_bad_ja3"

    def test_trojan_in_malware_c2(self):
        result = categorize_sub_category("ET TROJAN AgentTesla", "malware_c2")
        assert result == "trojan"

    def test_threat_intel_in_malware_c2(self):
        result = categorize_sub_category("ET COMPROMISED Known Host", "malware_c2")
        assert result == "threat_intel"

    def test_dns_tunnel_in_exfiltration(self):
        result = categorize_sub_category("ET DNS Tunnel Suspicious Query", "exfiltration")
        assert result == "dns_tunnel"

    def test_port_scan_in_reconnaissance(self):
        result = categorize_sub_category("ET SCAN Nmap Stealth", "reconnaissance")
        assert result == "port_scan"

    def test_web_exploit_in_exploit(self):
        result = categorize_sub_category("ET WEB_SERVER SQL Injection", "exploit")
        assert result == "web_exploit"

    def test_cve_in_exploit(self):
        result = categorize_sub_category("ET EXPLOIT CVE-2024-1234", "exploit")
        assert result == "cve"

    def test_tor_in_policy(self):
        result = categorize_sub_category("ET POLICY TOR Exit Node", "policy")
        assert result == "tor"

    def test_tls_anomaly_in_protocol(self):
        result = categorize_sub_category("SURICATA TLS missing handshake", "protocol_anomaly")
        assert result == "tls_anomaly"

    def test_upnp_in_iot(self):
        result = categorize_sub_category("UPnP Exploit Attempt", "iot_anomaly")
        assert result == "upnp_exploit"

    def test_embargoed_in_geo(self):
        result = categorize_sub_category("ET Embargo Country Connection", "geo_anomaly")
        assert result == "embargoed"

    def test_no_match_returns_none(self):
        result = categorize_sub_category("TOTALLY UNKNOWN RULE", "malware_c2")
        assert result is None

    def test_wrong_category_returns_none(self):
        """Sub-cat patterns for wrong parent should not match."""
        # "SSH Brute" is in credential_abuse, not malware_c2
        result = categorize_sub_category("SSH Brute Force", "malware_c2")
        assert result is None


# ---------------------------------------------------------------------------
# MITRE Techniques Structure
# ---------------------------------------------------------------------------


class TestMitreTechniques:
    """Validate MITRE_TECHNIQUES dict structure and coverage."""

    def test_mitre_covers_key_categories(self):
        """MITRE mapping should exist for high-risk categories."""
        expected = {"credential_abuse", "malware_c2", "exfiltration", "reconnaissance", "exploit", "dos"}
        for cat in expected:
            assert cat in MITRE_TECHNIQUES, f"Missing MITRE mapping for {cat}"

    def test_each_technique_has_required_fields(self):
        """Every technique entry must have id, name, description."""
        for cat, techniques in MITRE_TECHNIQUES.items():
            assert isinstance(techniques, list), f"{cat} should be a list"
            for t in techniques:
                assert "id" in t, f"Missing 'id' in {cat}"
                assert "name" in t, f"Missing 'name' in {cat}"
                assert "description" in t, f"Missing 'description' in {cat}"

    def test_technique_ids_start_with_T(self):
        """MITRE technique IDs always start with 'T'."""
        for cat, techniques in MITRE_TECHNIQUES.items():
            for t in techniques:
                assert t["id"].startswith("T"), f"ID {t['id']} in {cat} should start with T"

    def test_no_duplicate_technique_ids_per_category(self):
        """No duplicate technique IDs within a single category."""
        for cat, techniques in MITRE_TECHNIQUES.items():
            ids = [t["id"] for t in techniques]
            assert len(ids) == len(set(ids)), f"Duplicate technique IDs in {cat}"


# ---------------------------------------------------------------------------
# Category Detail Response Structure
# ---------------------------------------------------------------------------


class TestCategoryDetailResponse:
    """Verify THREAT_CATEGORIES has all fields needed by the category hub."""

    def test_all_categories_have_color(self):
        """Each category needs a color for the hub card."""
        for cat_id, cat in THREAT_CATEGORIES.items():
            assert "color" in cat, f"{cat_id} missing 'color'"
            assert cat["color"].startswith("#"), f"{cat_id} color should be hex"

    def test_all_categories_have_description(self):
        """Each category needs a description for the hub card."""
        for cat_id, cat in THREAT_CATEGORIES.items():
            assert "description" in cat, f"{cat_id} missing 'description'"
            assert len(cat["description"]) > 10, f"{cat_id} description too short"

    def test_all_categories_have_icon(self):
        """Each category needs an icon identifier."""
        for cat_id, cat in THREAT_CATEGORIES.items():
            assert "icon" in cat, f"{cat_id} missing 'icon'"
            assert len(cat["icon"]) > 0, f"{cat_id} icon is empty"

    def test_category_count_is_13(self):
        assert len(THREAT_CATEGORIES) == 13

    def test_sub_categories_aligned_with_categories(self):
        """Every parent category should have sub-categories defined."""
        for cat_id in THREAT_CATEGORIES:
            assert cat_id in SUB_CATEGORIES, f"No sub-categories for {cat_id}"


# ---------------------------------------------------------------------------
# Sparkline Interval Helper
# ---------------------------------------------------------------------------


class TestSparklineInterval:
    """Tests for _sparkline_interval() time range helper."""

    def test_short_range_returns_10m(self):
        result = _sparkline_interval("2026-03-16T10:00:00Z", "2026-03-16T14:00:00Z")
        assert result == "10m"

    def test_24h_range_returns_1h(self):
        result = _sparkline_interval("2026-03-15T10:00:00Z", "2026-03-16T10:00:00Z")
        assert result == "1h"

    def test_7d_range_returns_6h(self):
        result = _sparkline_interval("2026-03-09T10:00:00Z", "2026-03-16T10:00:00Z")
        assert result == "6h"

    def test_30d_range_returns_1d(self):
        result = _sparkline_interval("2026-02-14T10:00:00Z", "2026-03-16T10:00:00Z")
        assert result == "1d"

    def test_invalid_timestamps_default(self):
        result = _sparkline_interval("invalid", "also-invalid")
        assert result == "1h"  # defaults to 24h span logic
