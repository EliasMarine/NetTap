"""
Tests for daemon/services/alert_enrichment.py

All tests use mocks or temporary files -- no external dependencies required.
Tests cover SID lookup, pattern-based generation, risk context, recommendations,
JSON loading, graceful fallback, and alert field preservation.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.alert_enrichment import (
    AlertEnrichment,
    generate_description,
    get_recommendation,
    get_risk_context,
    _get_category_from_signature,
)


class TestGenerateDescription(unittest.TestCase):
    """Tests for generate_description()."""

    def test_et_malware_prefix(self):
        """ET MALWARE prefix generates malware description."""
        result = generate_description("ET MALWARE Win32/Emotet Activity")
        self.assertTrue(result.startswith("Potential malware activity detected:"))
        self.assertIn("Win32/Emotet Activity", result)

    def test_et_scan_prefix(self):
        """ET SCAN prefix generates scanning description."""
        result = generate_description("ET SCAN Nmap SYN Scan")
        self.assertTrue(result.startswith("Network scanning activity detected:"))
        self.assertIn("Nmap SYN Scan", result)

    def test_et_trojan_prefix(self):
        """ET TROJAN prefix generates trojan description."""
        result = generate_description("ET TROJAN Zeus GameOver Activity")
        self.assertTrue(result.startswith("Trojan horse communication detected:"))
        self.assertIn("Zeus GameOver Activity", result)

    def test_et_exploit_prefix(self):
        """ET EXPLOIT prefix generates exploit description."""
        result = generate_description("ET EXPLOIT Apache Log4j RCE Attempt")
        self.assertTrue(result.startswith("Exploit attempt detected:"))
        self.assertIn("Apache Log4j RCE Attempt", result)

    def test_et_policy_prefix(self):
        """ET POLICY prefix generates policy description."""
        result = generate_description("ET POLICY curl User-Agent Outbound")
        self.assertTrue(result.startswith("Network policy violation:"))
        self.assertIn("curl User-Agent Outbound", result)

    def test_et_info_prefix(self):
        """ET INFO prefix generates informational description."""
        result = generate_description("ET INFO Observed DNS Query to .onion TLD")
        self.assertTrue(result.startswith("Informational network event:"))
        self.assertIn("Observed DNS Query to .onion TLD", result)

    def test_et_dns_prefix(self):
        """ET DNS prefix generates DNS description."""
        result = generate_description("ET DNS Query for Suspicious Domain")
        self.assertTrue(result.startswith("Suspicious DNS activity:"))
        self.assertIn("Query for Suspicious Domain", result)

    def test_et_web_server_prefix(self):
        """ET WEB_SERVER prefix generates web server attack description."""
        result = generate_description("ET WEB_SERVER SQL Injection Attack")
        self.assertTrue(result.startswith("Web server attack detected:"))
        self.assertIn("SQL Injection Attack", result)

    def test_et_web_client_prefix(self):
        """ET WEB_CLIENT prefix generates web client description."""
        result = generate_description("ET WEB_CLIENT Suspicious PDF Download")
        self.assertTrue(result.startswith("Web client vulnerability activity:"))
        self.assertIn("Suspicious PDF Download", result)

    def test_gpl_prefix(self):
        """GPL prefix generates known threat description."""
        result = generate_description("GPL ATTACK_RESPONSE id check returned root")
        self.assertTrue(result.startswith("Known threat signature matched:"))
        self.assertIn("ATTACK_RESPONSE id check returned root", result)

    def test_unknown_signature(self):
        """Unknown signature prefix generates generic description."""
        result = generate_description("CUSTOM RULE Something Unusual")
        self.assertTrue(result.startswith("Network security event detected:"))
        self.assertIn("CUSTOM RULE Something Unusual", result)

    def test_empty_signature(self):
        """Empty signature returns generic message."""
        result = generate_description("")
        self.assertEqual(result, "Network security event detected.")

    def test_case_insensitive_prefix_matching(self):
        """Prefix matching is case-insensitive."""
        result = generate_description("et malware Some Lowercase Signature")
        self.assertTrue(result.startswith("Potential malware activity detected:"))


class TestGetRecommendation(unittest.TestCase):
    """Tests for get_recommendation()."""

    def test_malware_recommendation(self):
        """Malware category returns appropriate recommendation."""
        result = get_recommendation("malware")
        self.assertIn("malware", result.lower())
        self.assertIn("isolat", result.lower())

    def test_scan_recommendation(self):
        """Scan category returns appropriate recommendation."""
        result = get_recommendation("scan")
        self.assertIn("reconnaissance", result.lower())

    def test_trojan_recommendation(self):
        """Trojan category returns appropriate recommendation."""
        result = get_recommendation("trojan")
        self.assertIn("command-and-control", result.lower())

    def test_exploit_recommendation(self):
        """Exploit category returns appropriate recommendation."""
        result = get_recommendation("exploit")
        self.assertIn("exploit", result.lower())

    def test_unknown_category_returns_generic(self):
        """Unknown category returns generic recommendation."""
        result = get_recommendation("nonexistent_category")
        self.assertIn("review", result.lower())

    def test_info_recommendation(self):
        """Info category returns appropriate recommendation."""
        result = get_recommendation("info")
        self.assertIn("informational", result.lower())

    def test_dns_recommendation(self):
        """DNS category returns appropriate recommendation."""
        result = get_recommendation("dns")
        self.assertIn("dns", result.lower())


class TestGetRiskContext(unittest.TestCase):
    """Tests for get_risk_context()."""

    def test_high_severity_malware(self):
        """High severity malware returns critical context."""
        result = get_risk_context(1, "malware")
        self.assertIn("critical", result.lower())

    def test_medium_severity_malware(self):
        """Medium severity malware returns moderate context."""
        result = get_risk_context(2, "malware")
        self.assertIn("moderate", result.lower())

    def test_low_severity_malware(self):
        """Low severity malware returns low-severity context."""
        result = get_risk_context(3, "malware")
        self.assertIn("low", result.lower())

    def test_high_severity_scan(self):
        """High severity scan returns aggressive context."""
        result = get_risk_context(1, "scan")
        self.assertIn("aggressive", result.lower())

    def test_unknown_category_high_severity(self):
        """Unknown category with high severity returns default high context."""
        result = get_risk_context(1, "nonexistent")
        self.assertIn("high-severity", result.lower())

    def test_unknown_category_low_severity(self):
        """Unknown category with low severity returns default low context."""
        result = get_risk_context(3, "nonexistent")
        self.assertIn("low-severity", result.lower())

    def test_unknown_severity_level(self):
        """Unknown severity level returns generic context."""
        result = get_risk_context(99, "nonexistent")
        self.assertIn("severity 99", result.lower())

    def test_exploit_high_severity(self):
        """High severity exploit returns critical context."""
        result = get_risk_context(1, "exploit")
        self.assertIn("critical", result.lower())


class TestAlertEnrichment(unittest.TestCase):
    """Tests for the AlertEnrichment class."""

    def _make_descriptions_file(self, data: dict) -> str:
        """Create a temporary descriptions JSON file and return the path."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(data, tmp)
        tmp.close()
        return tmp.name

    def test_enrich_alert_with_known_sid(self):
        """enrich_alert uses SID lookup when available."""
        data = {
            "descriptions": {
                "12345": {
                    "signature": "ET MALWARE Test Malware",
                    "description": "A test malware was detected on your network.",
                    "risk_context": "This is a test risk context.",
                    "recommendation": "This is a test recommendation.",
                }
            },
            "prefix_descriptions": {},
        }
        path = self._make_descriptions_file(data)
        try:
            enricher = AlertEnrichment(descriptions_file=path)
            alert = {
                "alert": {
                    "signature": "ET MALWARE Test Malware",
                    "signature_id": 12345,
                    "severity": 1,
                },
                "src_ip": "192.168.1.100",
                "dest_ip": "10.0.0.1",
            }

            result = enricher.enrich_alert(alert)

            self.assertEqual(
                result["plain_description"],
                "A test malware was detected on your network.",
            )
            self.assertEqual(result["risk_context"], "This is a test risk context.")
            self.assertEqual(result["recommendation"], "This is a test recommendation.")
        finally:
            os.unlink(path)

    def test_enrich_alert_with_unknown_sid_known_prefix(self):
        """enrich_alert falls back to pattern matching for unknown SIDs."""
        data = {"descriptions": {}, "prefix_descriptions": {}}
        path = self._make_descriptions_file(data)
        try:
            enricher = AlertEnrichment(descriptions_file=path)
            alert = {
                "alert": {
                    "signature": "ET MALWARE Unknown Variant Activity",
                    "signature_id": 99999,
                    "severity": 2,
                },
            }

            result = enricher.enrich_alert(alert)

            self.assertTrue(
                result["plain_description"].startswith(
                    "Potential malware activity detected:"
                )
            )
            self.assertIn("Unknown Variant Activity", result["plain_description"])
            self.assertIsInstance(result["risk_context"], str)
            self.assertIsInstance(result["recommendation"], str)
        finally:
            os.unlink(path)

    def test_enrich_alert_with_unknown_sid_unknown_prefix(self):
        """enrich_alert handles completely unknown signatures."""
        data = {"descriptions": {}, "prefix_descriptions": {}}
        path = self._make_descriptions_file(data)
        try:
            enricher = AlertEnrichment(descriptions_file=path)
            alert = {
                "alert": {
                    "signature": "CUSTOM Some Completely Unknown Rule",
                    "signature_id": 88888,
                    "severity": 3,
                },
            }

            result = enricher.enrich_alert(alert)

            self.assertTrue(
                result["plain_description"].startswith(
                    "Network security event detected:"
                )
            )
            self.assertIsInstance(result["risk_context"], str)
            self.assertIsInstance(result["recommendation"], str)
        finally:
            os.unlink(path)

    def test_enrich_alert_preserves_original_fields(self):
        """enrich_alert does not remove any original alert fields."""
        data = {"descriptions": {}, "prefix_descriptions": {}}
        path = self._make_descriptions_file(data)
        try:
            enricher = AlertEnrichment(descriptions_file=path)
            alert = {
                "alert": {
                    "signature": "ET SCAN Test Scan",
                    "signature_id": 77777,
                    "severity": 2,
                    "category": "Scanning",
                },
                "src_ip": "10.0.0.1",
                "dest_ip": "192.168.1.1",
                "proto": "tcp",
                "timestamp": "2026-02-25T12:00:00Z",
                "_id": "alert-xyz",
                "custom_field": "preserved",
            }

            result = enricher.enrich_alert(alert)

            # Verify original fields are preserved
            self.assertEqual(result["src_ip"], "10.0.0.1")
            self.assertEqual(result["dest_ip"], "192.168.1.1")
            self.assertEqual(result["proto"], "tcp")
            self.assertEqual(result["timestamp"], "2026-02-25T12:00:00Z")
            self.assertEqual(result["_id"], "alert-xyz")
            self.assertEqual(result["custom_field"], "preserved")
            self.assertEqual(result["alert"]["signature"], "ET SCAN Test Scan")
            # Verify enrichment fields are added
            self.assertIn("plain_description", result)
            self.assertIn("risk_context", result)
            self.assertIn("recommendation", result)
        finally:
            os.unlink(path)

    def test_loading_descriptions_from_json(self):
        """AlertEnrichment correctly loads SID descriptions from JSON."""
        data = {
            "descriptions": {
                "100": {
                    "signature": "Test Sig",
                    "description": "Test description from JSON.",
                    "risk_context": "Test risk.",
                    "recommendation": "Test rec.",
                },
                "200": {
                    "signature": "Test Sig 2",
                    "description": "Second description.",
                    "risk_context": "Second risk.",
                    "recommendation": "Second rec.",
                },
            },
            "prefix_descriptions": {
                "ET MALWARE": "Malware prefix desc",
            },
        }
        path = self._make_descriptions_file(data)
        try:
            enricher = AlertEnrichment(descriptions_file=path)
            self.assertEqual(len(enricher._sid_descriptions), 2)
            self.assertIn("100", enricher._sid_descriptions)
            self.assertIn("200", enricher._sid_descriptions)
            self.assertIn("ET MALWARE", enricher._prefix_descriptions)
        finally:
            os.unlink(path)

    def test_missing_json_file_graceful_fallback(self):
        """AlertEnrichment handles missing JSON file gracefully."""
        enricher = AlertEnrichment(
            descriptions_file="/tmp/nettap-test-nonexistent-descriptions.json"
        )
        # Should have empty descriptions but still work
        self.assertEqual(enricher._sid_descriptions, {})
        self.assertEqual(enricher._prefix_descriptions, {})

        # enrich_alert should still work via pattern matching
        alert = {
            "alert": {
                "signature": "ET TROJAN Test",
                "signature_id": 11111,
                "severity": 1,
            },
        }
        result = enricher.enrich_alert(alert)
        self.assertTrue(
            result["plain_description"].startswith(
                "Trojan horse communication detected:"
            )
        )

    def test_corrupt_json_file_graceful_fallback(self):
        """AlertEnrichment handles corrupt JSON file gracefully."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write("not valid json{{{")
        tmp.close()
        try:
            enricher = AlertEnrichment(descriptions_file=tmp.name)
            self.assertEqual(enricher._sid_descriptions, {})

            # Should still work via fallback
            alert = {
                "alert": {
                    "signature": "ET EXPLOIT Test",
                    "signature_id": 22222,
                    "severity": 2,
                },
            }
            result = enricher.enrich_alert(alert)
            self.assertTrue(
                result["plain_description"].startswith("Exploit attempt detected:")
            )
        finally:
            os.unlink(tmp.name)

    def test_enrich_alert_missing_alert_subdict(self):
        """enrich_alert handles alerts without the 'alert' sub-dict gracefully."""
        data = {"descriptions": {}, "prefix_descriptions": {}}
        path = self._make_descriptions_file(data)
        try:
            enricher = AlertEnrichment(descriptions_file=path)
            alert = {"src_ip": "10.0.0.1", "dest_ip": "192.168.1.1"}

            result = enricher.enrich_alert(alert)

            self.assertIn("plain_description", result)
            self.assertIn("risk_context", result)
            self.assertIn("recommendation", result)
        finally:
            os.unlink(path)

    def test_default_descriptions_file_path(self):
        """AlertEnrichment uses the correct default descriptions file path."""
        # The default file should be daemon/data/suricata_descriptions.json
        enricher = AlertEnrichment()
        expected_dir = Path(__file__).resolve().parent.parent / "data"
        expected_file = expected_dir / "suricata_descriptions.json"
        self.assertEqual(enricher._descriptions_file, expected_file)


class TestGetCategoryFromSignature(unittest.TestCase):
    """Tests for _get_category_from_signature()."""

    def test_malware_category(self):
        self.assertEqual(_get_category_from_signature("ET MALWARE Test"), "malware")

    def test_scan_category(self):
        self.assertEqual(_get_category_from_signature("ET SCAN Test"), "scan")

    def test_trojan_category(self):
        self.assertEqual(_get_category_from_signature("ET TROJAN Test"), "trojan")

    def test_exploit_category(self):
        self.assertEqual(_get_category_from_signature("ET EXPLOIT Test"), "exploit")

    def test_unknown_category(self):
        self.assertEqual(_get_category_from_signature("CUSTOM RULE Test"), "unknown")

    def test_empty_string(self):
        self.assertEqual(_get_category_from_signature(""), "unknown")


if __name__ == "__main__":
    unittest.main()
