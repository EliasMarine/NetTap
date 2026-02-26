"""
Tests for daemon/services/traffic_classifier.py

All tests use mocks -- no OpenSearch connection required.
Tests cover domain classification, service/port lookups, connection
classification priority, category labels, and async category stats.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.traffic_classifier import (
    classify_domain,
    classify_by_service,
    classify_by_port,
    classify_connection,
    get_category_label,
    get_category_stats,
    CATEGORIES,
    DOMAIN_RULES,
    PORT_RULES,
    SERVICE_RULES,
)


class TestClassifyDomain(unittest.TestCase):
    """Tests for classify_domain()."""

    def test_exact_wildcard_match(self):
        """Known domain like www.netflix.com matches *.netflix.com."""
        result = classify_domain("www.netflix.com")
        self.assertEqual(result, "streaming")

    def test_subdomain_match(self):
        """Deep subdomain like video.cdn.netflix.com matches *.netflix.com."""
        result = classify_domain("video.cdn.netflix.com")
        self.assertEqual(result, "streaming")

    def test_gaming_domain(self):
        """Gaming domain like store.steampowered.com is classified correctly."""
        result = classify_domain("store.steampowered.com")
        self.assertEqual(result, "gaming")

    def test_social_media_domain(self):
        """Social media domain like m.facebook.com is classified correctly."""
        result = classify_domain("m.facebook.com")
        self.assertEqual(result, "social")

    def test_communication_domain(self):
        """Communication domain like app.zoom.us is classified correctly."""
        result = classify_domain("app.zoom.us")
        self.assertEqual(result, "communication")

    def test_work_domain(self):
        """Work domain like api.github.com is classified correctly."""
        result = classify_domain("api.github.com")
        self.assertEqual(result, "work")

    def test_iot_domain(self):
        """IoT domain like fw.ring.com is classified correctly."""
        result = classify_domain("fw.ring.com")
        self.assertEqual(result, "iot")

    def test_no_match_returns_other(self):
        """Unknown domain returns 'other'."""
        result = classify_domain("randomsite.example.org")
        self.assertEqual(result, "other")

    def test_empty_string_returns_other(self):
        """Empty domain string returns 'other'."""
        result = classify_domain("")
        self.assertEqual(result, "other")

    def test_case_insensitivity(self):
        """Domain matching is case-insensitive."""
        result = classify_domain("WWW.NETFLIX.COM")
        self.assertEqual(result, "streaming")

    def test_case_insensitivity_mixed(self):
        """Mixed case domain matching works."""
        result = classify_domain("Video.YouTube.com")
        self.assertEqual(result, "streaming")

    def test_cloud_domain(self):
        """Cloud domain like s3.amazonaws.com is classified correctly."""
        result = classify_domain("s3.amazonaws.com")
        self.assertEqual(result, "cloud")

    def test_suspicious_domain(self):
        """Suspicious domain like something.onion is classified correctly."""
        result = classify_domain("hidden.onion")
        self.assertEqual(result, "suspicious")

    def test_email_domain(self):
        """Email domain like mail.gmail.com is classified correctly."""
        result = classify_domain("mail.gmail.com")
        self.assertEqual(result, "email")

    def test_file_transfer_domain(self):
        """File transfer domain like dl.dropbox.com is classified correctly."""
        result = classify_domain("dl.dropbox.com")
        self.assertEqual(result, "file_transfer")

    def test_security_domain(self):
        """Security domain like api.nordvpn.com is classified correctly."""
        result = classify_domain("api.nordvpn.com")
        self.assertEqual(result, "security")


class TestClassifyByService(unittest.TestCase):
    """Tests for classify_by_service()."""

    def test_known_service_http(self):
        """Known service 'http' returns 'web'."""
        result = classify_by_service("http")
        self.assertEqual(result, "web")

    def test_known_service_dns(self):
        """Known service 'dns' returns 'dns'."""
        result = classify_by_service("dns")
        self.assertEqual(result, "dns")

    def test_known_service_ssh(self):
        """Known service 'ssh' returns 'security'."""
        result = classify_by_service("ssh")
        self.assertEqual(result, "security")

    def test_unknown_service_returns_other(self):
        """Unknown service returns 'other'."""
        result = classify_by_service("unknownsvc")
        self.assertEqual(result, "other")

    def test_empty_service_returns_other(self):
        """Empty service string returns 'other'."""
        result = classify_by_service("")
        self.assertEqual(result, "other")

    def test_case_insensitivity(self):
        """Service matching is case-insensitive."""
        result = classify_by_service("HTTP")
        self.assertEqual(result, "web")


class TestClassifyByPort(unittest.TestCase):
    """Tests for classify_by_port()."""

    def test_known_port_443(self):
        """Port 443 returns 'web'."""
        result = classify_by_port(443)
        self.assertEqual(result, "web")

    def test_known_port_53(self):
        """Port 53 returns 'dns'."""
        result = classify_by_port(53)
        self.assertEqual(result, "dns")

    def test_known_port_22(self):
        """Port 22 returns 'security'."""
        result = classify_by_port(22)
        self.assertEqual(result, "security")

    def test_unknown_port_returns_other(self):
        """Unknown port returns 'other'."""
        result = classify_by_port(9999)
        self.assertEqual(result, "other")

    def test_none_port_returns_other(self):
        """None port returns 'other'."""
        result = classify_by_port(None)
        self.assertEqual(result, "other")


class TestClassifyConnection(unittest.TestCase):
    """Tests for classify_connection()."""

    def test_domain_takes_priority_over_service(self):
        """Domain classification has priority over service classification."""
        result = classify_connection(
            service="http", domain="www.netflix.com", port=443
        )
        self.assertEqual(result, "streaming")

    def test_service_fallback_when_domain_is_other(self):
        """Falls back to service when domain returns 'other'."""
        result = classify_connection(
            service="dns", domain="unknown.example.org", port=80
        )
        self.assertEqual(result, "dns")

    def test_port_fallback_when_service_is_other(self):
        """Falls back to port when both domain and service return 'other'."""
        result = classify_connection(
            service="unknown", domain="unknown.example.org", port=22
        )
        self.assertEqual(result, "security")

    def test_all_none_returns_other(self):
        """All None parameters return 'other'."""
        result = classify_connection(service=None, domain=None, port=None)
        self.assertEqual(result, "other")

    def test_only_domain_provided(self):
        """Only domain provided, correctly classified."""
        result = classify_connection(domain="cdn.discord.com")
        self.assertEqual(result, "communication")

    def test_only_service_provided(self):
        """Only service provided, correctly classified."""
        result = classify_connection(service="smtp")
        self.assertEqual(result, "email")

    def test_only_port_provided(self):
        """Only port provided, correctly classified."""
        result = classify_connection(port=587)
        self.assertEqual(result, "email")


class TestGetCategoryLabel(unittest.TestCase):
    """Tests for get_category_label()."""

    def test_valid_key(self):
        """Valid category key returns display name."""
        self.assertEqual(get_category_label("streaming"), "Streaming")
        self.assertEqual(get_category_label("social"), "Social Media")
        self.assertEqual(get_category_label("work"), "Work & Productivity")
        self.assertEqual(get_category_label("iot"), "IoT & Smart Home")

    def test_invalid_key_returns_title_case(self):
        """Invalid category key returns title-cased version."""
        result = get_category_label("some_unknown_category")
        self.assertEqual(result, "Some Unknown Category")

    def test_other_key(self):
        """'other' key returns 'Other'."""
        self.assertEqual(get_category_label("other"), "Other")


class TestGetCategoryStats(unittest.TestCase):
    """Tests for get_category_stats() async function."""

    def test_category_stats_success(self):
        """Successful category stats query returns categorized data."""
        mock_client = MagicMock()

        # Mock DNS query results
        mock_client.search.side_effect = [
            # First call: DNS domains
            {
                "aggregations": {
                    "top_domains": {
                        "buckets": [
                            {"key": "www.netflix.com", "doc_count": 150},
                            {"key": "cdn.netflix.com", "doc_count": 100},
                            {"key": "api.github.com", "doc_count": 80},
                            {"key": "unknown.example.org", "doc_count": 50},
                            {"key": "play.google.com", "doc_count": 40},
                        ]
                    }
                }
            },
            # Second call: Connection stats by service
            {
                "aggregations": {
                    "by_service": {
                        "buckets": [
                            {
                                "key": "ssl",
                                "doc_count": 5000,
                                "total_bytes": {"value": 10000000},
                            },
                            {
                                "key": "dns",
                                "doc_count": 2000,
                                "total_bytes": {"value": 500000},
                            },
                            {
                                "key": "http",
                                "doc_count": 1000,
                                "total_bytes": {"value": 3000000},
                            },
                        ]
                    }
                }
            },
        ]

        async def run():
            return await get_category_stats(
                mock_client, "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
            )

        result = asyncio.run(run())

        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)

        # Check that categories are present
        names = [r["name"] for r in result]
        self.assertIn("streaming", names)
        self.assertIn("web", names)

        # Verify streaming has the netflix domains
        streaming = next(r for r in result if r["name"] == "streaming")
        self.assertEqual(streaming["label"], "Streaming")
        self.assertTrue(streaming["connection_count"] > 0)
        domain_names = [d["domain"] for d in streaming["top_domains"]]
        self.assertIn("www.netflix.com", domain_names)

        # Verify search was called twice (DNS + connections)
        self.assertEqual(mock_client.search.call_count, 2)

    def test_category_stats_dns_error(self):
        """DNS query error returns empty list."""
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("Connection refused")

        async def run():
            return await get_category_stats(
                mock_client, "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
            )

        result = asyncio.run(run())
        self.assertEqual(result, [])

    def test_category_stats_conn_error(self):
        """Connection stats query error returns empty list."""
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            # DNS query succeeds
            {"aggregations": {"top_domains": {"buckets": []}}},
            # Connection query fails
            Exception("Connection refused"),
        ]

        async def run():
            return await get_category_stats(
                mock_client, "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
            )

        result = asyncio.run(run())
        self.assertEqual(result, [])

    def test_category_stats_empty_results(self):
        """Empty results from both queries returns empty list."""
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            {"aggregations": {"top_domains": {"buckets": []}}},
            {"aggregations": {"by_service": {"buckets": []}}},
        ]

        async def run():
            return await get_category_stats(
                mock_client, "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
            )

        result = asyncio.run(run())
        self.assertEqual(result, [])

    def test_category_stats_sorted_by_bytes(self):
        """Results are sorted by total_bytes descending."""
        mock_client = MagicMock()
        mock_client.search.side_effect = [
            {
                "aggregations": {
                    "top_domains": {
                        "buckets": [
                            {"key": "www.netflix.com", "doc_count": 10},
                            {"key": "api.github.com", "doc_count": 5},
                        ]
                    }
                }
            },
            {
                "aggregations": {
                    "by_service": {
                        "buckets": [
                            {
                                "key": "http",
                                "doc_count": 100,
                                "total_bytes": {"value": 50000},
                            },
                            {
                                "key": "dns",
                                "doc_count": 200,
                                "total_bytes": {"value": 10000},
                            },
                        ]
                    }
                }
            },
        ]

        async def run():
            return await get_category_stats(
                mock_client, "2026-02-25T00:00:00Z", "2026-02-26T00:00:00Z"
            )

        result = asyncio.run(run())

        if len(result) >= 2:
            # First result should have the most bytes
            self.assertGreaterEqual(
                result[0]["total_bytes"], result[1]["total_bytes"]
            )


if __name__ == "__main__":
    unittest.main()
