"""
Tests for daemon/services/cert_monitor.py

Covers certificate listing, expiry detection, self-signed detection,
and issuer change detection. All tests use mocked OpenSearch.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.cert_monitor import CertificateMonitor


def _make_ssl_hit(
    _id: str,
    domain: str = "example.com",
    subject: str = "example.com",
    issuer: str = "Let's Encrypt",
    not_before: str = "2026-01-01T00:00:00Z",
    not_after: str = "2026-12-31T00:00:00Z",
    validation_status: str = "ok",
    source_ip: str = "192.168.1.100",
    dest_ip: str = "93.184.216.34",
) -> dict:
    """Build a fake OpenSearch SSL log hit."""
    return {
        "_id": _id,
        "_source": {
            "@timestamp": "2026-03-08T10:00:00Z",
            "tls": {
                "server": {
                    "subject": subject,
                    "issuer": issuer,
                    "not_before": not_before,
                    "not_after": not_after,
                    "hash": {"sha256": "abc123def456"},
                    "x509": {
                        "subject": {"common_name": subject},
                        "issuer": {"common_name": issuer},
                        "not_before": not_before,
                        "not_after": not_after,
                    },
                },
                "version": "TLSv1.3",
            },
            "destination": {"domain": domain, "ip": dest_ip, "port": 443},
            "source": {"ip": source_ip},
            "zeek": {
                "ssl": {
                    "server_name": domain,
                    "subject": subject,
                    "issuer": issuer,
                    "not_valid_before": not_before,
                    "not_valid_after": not_after,
                    "validation_status": validation_status,
                }
            },
            "event": {"provider": "zeek", "dataset": "ssl"},
        },
    }


class TestCertificateMonitorGetCertificates(unittest.TestCase):
    """Tests for CertificateMonitor.get_certificates()."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.monitor = CertificateMonitor(client=self.mock_client)

    def test_get_certificates_returns_normalized_certs(self):
        """get_certificates() normalizes SSL hits into cert records."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit("cert-1", domain="google.com", issuer="GTS CA 1C3"),
                    _make_ssl_hit("cert-2", domain="github.com", issuer="DigiCert"),
                ]
            }
        }

        certs = self.monitor.get_certificates()
        self.assertEqual(len(certs), 2)
        self.assertEqual(certs[0]["domain"], "google.com")
        self.assertEqual(certs[0]["issuer"], "GTS CA 1C3")
        self.assertEqual(certs[0]["_id"], "cert-1")
        self.assertEqual(certs[1]["domain"], "github.com")

    def test_get_certificates_opensearch_error(self):
        """get_certificates() returns empty list on error."""
        from opensearchpy import OpenSearchException

        self.mock_client.search.side_effect = OpenSearchException("timeout")
        certs = self.monitor.get_certificates()
        self.assertEqual(certs, [])

    def test_get_certificates_empty_results(self):
        """get_certificates() returns empty list when no hits."""
        self.mock_client.search.return_value = {"hits": {"hits": []}}
        certs = self.monitor.get_certificates()
        self.assertEqual(certs, [])


class TestCertificateMonitorExpiring(unittest.TestCase):
    """Tests for CertificateMonitor.get_expiring_certs()."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.monitor = CertificateMonitor(client=self.mock_client)

    def test_detects_expiring_cert(self):
        """get_expiring_certs() flags certs expiring within N days."""
        # Cert expiring in 15 days
        soon = (datetime.now(timezone.utc) + timedelta(days=15)).isoformat()
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit("cert-exp", not_after=soon),
                ]
            }
        }

        certs = self.monitor.get_expiring_certs(days=30)
        self.assertEqual(len(certs), 1)
        self.assertEqual(certs[0]["status"], "expiring")
        self.assertIn("days_until_expiry", certs[0])

    def test_detects_expired_cert(self):
        """get_expiring_certs() flags already-expired certs."""
        past = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit("cert-expired", not_after=past),
                ]
            }
        }

        certs = self.monitor.get_expiring_certs(days=30)
        self.assertEqual(len(certs), 1)
        self.assertEqual(certs[0]["status"], "expired")

    def test_ignores_valid_cert(self):
        """get_expiring_certs() ignores certs not expiring soon."""
        future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit("cert-valid", not_after=future),
                ]
            }
        }

        certs = self.monitor.get_expiring_certs(days=30)
        self.assertEqual(len(certs), 0)


class TestCertificateMonitorSelfSigned(unittest.TestCase):
    """Tests for CertificateMonitor.detect_self_signed()."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.monitor = CertificateMonitor(client=self.mock_client)

    def test_detects_subject_equals_issuer(self):
        """detect_self_signed() flags certs where subject == issuer."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit(
                        "cert-ss",
                        subject="myserver.local",
                        issuer="myserver.local",
                    ),
                ]
            }
        }

        certs = self.monitor.detect_self_signed()
        self.assertEqual(len(certs), 1)
        self.assertEqual(certs[0]["detection_reason"], "subject matches issuer")

    def test_detects_validation_status_self_signed(self):
        """detect_self_signed() flags certs with self-signed validation status."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit(
                        "cert-ss2",
                        subject="server.local",
                        issuer="My CA",
                        validation_status="self signed certificate",
                    ),
                ]
            }
        }

        certs = self.monitor.detect_self_signed()
        self.assertEqual(len(certs), 1)

    def test_ignores_valid_ca_signed(self):
        """detect_self_signed() ignores properly CA-signed certs."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit("cert-ok", subject="example.com", issuer="DigiCert"),
                ]
            }
        }

        certs = self.monitor.detect_self_signed()
        self.assertEqual(len(certs), 0)


class TestCertificateMonitorIssuerChanges(unittest.TestCase):
    """Tests for CertificateMonitor.detect_issuer_changes()."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.monitor = CertificateMonitor(client=self.mock_client)

    def test_detects_multiple_issuers(self):
        """detect_issuer_changes() flags domains with multiple issuers."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit("c1", domain="bank.com", issuer="DigiCert"),
                    _make_ssl_hit("c2", domain="bank.com", issuer="Unknown CA"),
                ]
            }
        }

        changes = self.monitor.detect_issuer_changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["domain"], "bank.com")
        self.assertEqual(changes[0]["issuer_count"], 2)
        self.assertIn("DigiCert", changes[0]["issuers"])
        self.assertIn("Unknown CA", changes[0]["issuers"])

    def test_no_changes_single_issuer(self):
        """detect_issuer_changes() returns empty for single-issuer domains."""
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit("c1", domain="google.com", issuer="GTS CA 1C3"),
                    _make_ssl_hit("c2", domain="google.com", issuer="GTS CA 1C3"),
                ]
            }
        }

        changes = self.monitor.detect_issuer_changes()
        self.assertEqual(len(changes), 0)

    def test_empty_results(self):
        """detect_issuer_changes() returns empty for no certs."""
        self.mock_client.search.return_value = {"hits": {"hits": []}}
        changes = self.monitor.detect_issuer_changes()
        self.assertEqual(changes, [])


class TestCertificateMonitorStats(unittest.TestCase):
    """Tests for CertificateMonitor.get_cert_stats()."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.monitor = CertificateMonitor(client=self.mock_client)

    def test_stats_aggregates_counts(self):
        """get_cert_stats() returns correct aggregate counts."""
        soon = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        self.mock_client.search.return_value = {
            "hits": {
                "hits": [
                    _make_ssl_hit("c1", domain="a.com", issuer="CA1", not_after=soon),
                    _make_ssl_hit("c2", domain="b.com", subject="self", issuer="self"),
                    _make_ssl_hit("c3", domain="c.com", issuer="CA2"),
                    _make_ssl_hit("c4", domain="c.com", issuer="CA3"),
                ]
            }
        }

        stats = self.monitor.get_cert_stats()
        self.assertEqual(stats["total_certs"], 4)
        self.assertGreaterEqual(stats["expiring_count"], 1)
        self.assertGreaterEqual(stats["self_signed_count"], 1)
        self.assertGreaterEqual(stats["issuer_changes_count"], 1)


class TestCertificateMonitorNormalize(unittest.TestCase):
    """Tests for the _normalize_cert static method."""

    def test_normalize_ecs_fields(self):
        """_normalize_cert extracts ECS TLS fields."""
        src = {
            "@timestamp": "2026-03-08T10:00:00Z",
            "tls": {
                "server": {
                    "subject": "example.com",
                    "issuer": "CA",
                    "not_before": "2026-01-01",
                    "not_after": "2026-12-31",
                    "hash": {"sha256": "abc"},
                    "x509": {
                        "subject": {"common_name": "example.com"},
                        "issuer": {"common_name": "CA"},
                        "not_before": "2026-01-01",
                        "not_after": "2026-12-31",
                    },
                },
                "version": "TLSv1.3",
            },
            "destination": {"domain": "example.com", "ip": "1.2.3.4", "port": 443},
            "source": {"ip": "192.168.1.1"},
            "zeek": {"ssl": {}},
        }

        cert = CertificateMonitor._normalize_cert(src)
        self.assertEqual(cert["domain"], "example.com")
        self.assertEqual(cert["issuer"], "CA")
        self.assertEqual(cert["tls_version"], "TLSv1.3")

    def test_normalize_zeek_fallback(self):
        """_normalize_cert falls back to Zeek-native fields."""
        src = {
            "@timestamp": "2026-03-08T10:00:00Z",
            "tls": {"server": {}},
            "destination": {},
            "source": {},
            "zeek": {
                "ssl": {
                    "server_name": "test.local",
                    "subject": "test.local",
                    "issuer": "Self",
                    "not_valid_before": "2026-01-01",
                    "not_valid_after": "2026-12-31",
                    "validation_status": "self signed certificate",
                }
            },
        }

        cert = CertificateMonitor._normalize_cert(src)
        self.assertEqual(cert["domain"], "test.local")
        self.assertEqual(cert["issuer"], "Self")
        self.assertEqual(cert["status"], "self-signed")


if __name__ == "__main__":
    unittest.main()
