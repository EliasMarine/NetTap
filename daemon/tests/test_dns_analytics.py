"""
Tests for daemon/services/dns_analytics.py

All tests use mocks -- no OpenSearch connection required.
"""

import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.dns_analytics import DNSAnalytics, _shannon_entropy


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def dns(mock_client):
    return DNSAnalytics(client=mock_client)


# ---------------------------------------------------------------------------
# _shannon_entropy
# ---------------------------------------------------------------------------


class TestShannonEntropy:
    def test_empty_string(self):
        assert _shannon_entropy("") == 0.0

    def test_single_char(self):
        assert _shannon_entropy("aaaa") == 0.0

    def test_high_entropy(self):
        """Random-looking string should have high entropy."""
        entropy = _shannon_entropy("a1b2c3d4e5f6g7h8")
        assert entropy > 3.5

    def test_low_entropy(self):
        """Repetitive string should have low entropy."""
        entropy = _shannon_entropy("aaaaabbbbb")
        assert entropy < 2.0


# ---------------------------------------------------------------------------
# get_top_domains
# ---------------------------------------------------------------------------


class TestGetTopDomains:
    def test_returns_domain_list(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "top_domains": {
                    "buckets": [
                        {
                            "key": "google.com",
                            "doc_count": 500,
                            "unique_clients": {"value": 10},
                        },
                        {
                            "key": "facebook.com",
                            "doc_count": 300,
                            "unique_clients": {"value": 5},
                        },
                    ]
                }
            }
        }

        result = dns.get_top_domains("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")

        assert len(result) == 2
        assert result[0]["domain"] == "google.com"
        assert result[0]["count"] == 500
        assert result[0]["unique_clients"] == 10

    def test_respects_limit(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {"top_domains": {"buckets": []}}
        }
        dns.get_top_domains("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", limit=10)

        call_body = mock_client.search.call_args[1]["body"]
        assert call_body["aggs"]["top_domains"]["terms"]["size"] == 10

    def test_empty_result(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {"top_domains": {"buckets": []}}
        }
        result = dns.get_top_domains("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert result == []


# ---------------------------------------------------------------------------
# get_device_dns
# ---------------------------------------------------------------------------


class TestGetDeviceDns:
    def test_returns_device_domains(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "domains": {
                    "buckets": [
                        {
                            "key": "api.example.com",
                            "doc_count": 100,
                            "query_types": {
                                "buckets": [
                                    {"key": "A", "doc_count": 80},
                                    {"key": "AAAA", "doc_count": 20},
                                ]
                            },
                        }
                    ]
                }
            }
        }

        result = dns.get_device_dns(
            "192.168.1.100", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(result) == 1
        assert result[0]["domain"] == "api.example.com"
        assert len(result[0]["query_types"]) == 2

    def test_filters_by_device_ip(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {"domains": {"buckets": []}}
        }
        dns.get_device_dns(
            "10.0.0.1", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )
        call_body = mock_client.search.call_args[1]["body"]
        filters = call_body["query"]["bool"]["filter"]
        ip_filter = [f for f in filters if "term" in f and "source.ip.keyword" in f.get("term", {})]
        assert len(ip_filter) == 1
        assert ip_filter[0]["term"]["source.ip.keyword"] == "10.0.0.1"


# ---------------------------------------------------------------------------
# get_nxdomain_errors
# ---------------------------------------------------------------------------


class TestGetNxdomainErrors:
    def test_returns_nxdomain_list(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "nxdomains": {
                    "buckets": [
                        {
                            "key": "nonexistent.test",
                            "doc_count": 50,
                            "clients": {
                                "buckets": [
                                    {"key": "192.168.1.10", "doc_count": 50}
                                ]
                            },
                        }
                    ]
                }
            }
        }

        result = dns.get_nxdomain_errors(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(result) == 1
        assert result[0]["domain"] == "nonexistent.test"
        assert "192.168.1.10" in result[0]["clients"]

    def test_filters_by_nxdomain_rcode(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {"nxdomains": {"buckets": []}}
        }
        dns.get_nxdomain_errors("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        call_body = mock_client.search.call_args[1]["body"]
        filters = call_body["query"]["bool"]["filter"]
        nxd = [f for f in filters if "term" in f and "zeek.dns.rcode_name.keyword" in f.get("term", {})]
        assert len(nxd) == 1
        assert nxd[0]["term"]["zeek.dns.rcode_name.keyword"] == "NXDOMAIN"


# ---------------------------------------------------------------------------
# get_query_type_distribution
# ---------------------------------------------------------------------------


class TestGetQueryTypeDistribution:
    def test_returns_type_counts(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "query_types": {
                    "buckets": [
                        {"key": "A", "doc_count": 1000},
                        {"key": "AAAA", "doc_count": 500},
                        {"key": "CNAME", "doc_count": 200},
                    ]
                }
            }
        }

        result = dns.get_query_type_distribution(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(result) == 3
        assert result[0]["type"] == "A"
        assert result[0]["count"] == 1000


# ---------------------------------------------------------------------------
# get_dns_timeline
# ---------------------------------------------------------------------------


class TestGetDnsTimeline:
    def test_returns_timeline_series(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "timeline": {
                    "buckets": [
                        {"key_as_string": "2026-01-01T00:00:00Z", "doc_count": 100},
                        {"key_as_string": "2026-01-01T00:01:00Z", "doc_count": 150},
                    ]
                }
            }
        }

        result = dns.get_dns_timeline(
            "2026-01-01T00:00:00Z", "2026-01-01T00:10:00Z", interval="1m"
        )

        assert len(result) == 2
        assert result[0]["count"] == 100

    def test_invalid_interval_defaults_to_5m(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {"timeline": {"buckets": []}}
        }
        dns.get_dns_timeline(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", interval="99x"
        )
        call_body = mock_client.search.call_args[1]["body"]
        assert call_body["aggs"]["timeline"]["date_histogram"]["fixed_interval"] == "5m"


# ---------------------------------------------------------------------------
# get_suspicious_dns
# ---------------------------------------------------------------------------


class TestGetSuspiciousDns:
    def test_detects_long_domain_names(self, dns, mock_client):
        long_domain = "a" * 60 + ".evil.com"
        mock_client.search.return_value = {
            "aggregations": {
                "top_domains": {
                    "buckets": [
                        {
                            "key": long_domain,
                            "doc_count": 10,
                            "unique_clients": {"value": 1},
                        }
                    ]
                },
                "txt_domains": {"buckets": []},
            }
        }

        result = dns.get_suspicious_dns(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        long_findings = [r for r in result if r["type"] == "long_domain"]
        assert len(long_findings) >= 1
        assert long_findings[0]["length"] > 50

    def test_detects_high_frequency(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "top_domains": {
                    "buckets": [
                        {
                            "key": "beacon.evil.com",
                            "doc_count": 1000,
                            "unique_clients": {"value": 1},
                        }
                    ]
                },
                "txt_domains": {"buckets": []},
            }
        }

        result = dns.get_suspicious_dns(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        hf = [r for r in result if r["type"] == "high_frequency"]
        assert len(hf) >= 1

    def test_detects_txt_abuse(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "top_domains": {"buckets": []},
                "txt_domains": {
                    "buckets": [
                        {"key": "tunnel.evil.com", "doc_count": 100}
                    ]
                },
            }
        }

        result = dns.get_suspicious_dns(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        txt = [r for r in result if r["type"] == "txt_abuse"]
        assert len(txt) >= 1


# ---------------------------------------------------------------------------
# detect_dns_tunneling
# ---------------------------------------------------------------------------


class TestDetectDnsTunneling:
    def test_detects_high_entropy_subdomains(self, dns, mock_client):
        # Base32-encoded subdomain (high entropy)
        encoded = "a1b2c3d4e5f6g7h8i9j0.tunnel.evil.com"
        mock_client.search.return_value = {
            "aggregations": {
                "top_domains": {
                    "buckets": [
                        {
                            "key": encoded,
                            "doc_count": 200,
                            "unique_clients": {"value": 1},
                        }
                    ]
                }
            }
        }

        result = dns.detect_dns_tunneling(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(result) >= 1
        assert result[0]["entropy"] > 3.5

    def test_ignores_normal_domains(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "top_domains": {
                    "buckets": [
                        {
                            "key": "www.google.com",
                            "doc_count": 500,
                            "unique_clients": {"value": 10},
                        }
                    ]
                }
            }
        }

        result = dns.detect_dns_tunneling(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(result) == 0


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_returns_hero_stats(self, dns, mock_client):
        mock_client.search.return_value = {
            "hits": {"total": {"value": 10000}},
            "aggregations": {
                "unique_domains": {"value": 500},
                "nxdomain_count": {"doc_count": 42},
                "avg_rtt": {"value": 5000000},  # 5ms in nanoseconds
            },
        }

        result = dns.get_stats("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")

        assert result["total_queries"] == 10000
        assert result["unique_domains"] == 500
        assert result["nxdomain_count"] == 42
        assert result["avg_resolution_ms"] == 5.0

    def test_handles_missing_aggs(self, dns, mock_client):
        mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {},
        }

        result = dns.get_stats("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")

        assert result["total_queries"] == 0
        assert result["unique_domains"] == 0
