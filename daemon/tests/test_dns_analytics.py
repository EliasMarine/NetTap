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
from tests.fake_opensearch import FakeOpenSearch


from services.dns_analytics import DNS_LOOKUP_EXCLUSION


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
        mock_client.search.return_value = {"aggregations": {"domains": {"buckets": []}}}
        dns.get_device_dns("10.0.0.1", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        call_body = mock_client.search.call_args[1]["body"]
        filters = call_body["query"]["bool"]["filter"]
        ip_filter = [
            f for f in filters if "term" in f and "source.ip" in f.get("term", {})
        ]
        assert len(ip_filter) == 1
        assert ip_filter[0]["term"]["source.ip"] == "10.0.0.1"


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
                                "buckets": [{"key": "192.168.1.10", "doc_count": 50}]
                            },
                        }
                    ]
                }
            }
        }

        result = dns.get_nxdomain_errors("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")

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
        nxd = [
            f
            for f in filters
            if "term" in f and "zeek.dns.rcode_name" in f.get("term", {})
        ]
        assert len(nxd) == 1
        assert nxd[0]["term"]["zeek.dns.rcode_name"] == "NXDOMAIN"


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
        # OLD CODE START — #120: the timeline was a date_histogram
        # assert call_body["aggs"]["timeline"]["date_histogram"]["fixed_interval"] == "5m"
        # OLD CODE END
        ranges = call_body["aggs"]["timeline"]["date_range"]["ranges"]
        assert (ranges[0]["from"], ranges[0]["to"]) == (
            "2026-01-01T00:00:00.000Z",
            "2026-01-01T00:05:00.000Z",
        )
        assert len(ranges) == 289  # 24 h of 5 min slots, plus the slot holding the end


# ---------------------------------------------------------------------------
# get_suspicious_dns
# ---------------------------------------------------------------------------


def _dns_doc(name: str, src: str = "192.168.1.10", qtype: str = "A") -> dict:
    return {
        "event.provider": "zeek",
        "event.dataset": "dns",
        "zeek.dns.query": name,
        "zeek.dns.qtype_name": qtype,
        "source.ip": src,
        "destination.ip": "8.8.8.8",
        "destination.port": 53,
        "@timestamp": 0,
    }


def _over(reply: dict) -> DNSAnalytics:
    """#96: the detections page every name now; serve the docs an old top-list reply described."""
    aggs = reply["aggregations"]
    names = [
        _dns_doc(b["key"], f"192.168.1.{n % b['unique_clients']['value'] + 1}")
        for b in aggs.get("top_domains", {}).get("buckets", [])
        for n in range(b["doc_count"])
    ]
    txt = [
        _dns_doc(b["key"], qtype="TXT")
        for b in aggs.get("txt_domains", {}).get("buckets", [])
        for _ in range(b["doc_count"])
    ]
    return DNSAnalytics(FakeOpenSearch(names + txt))


class TestDetectionsSeeEveryName:
    """#96: detections ran on the top 200 (TXT: top 20) names; the tail was never checked."""

    _BUSY = [_dns_doc(f"site{i}.example.org") for i in range(250) for _ in range(3)]

    def test_long_name_queried_once_is_flagged(self):
        long_name = "a" * 60 + ".evil.com"
        dns = DNSAnalytics(FakeOpenSearch(self._BUSY + [_dns_doc(long_name)]))

        result = dns.get_suspicious_dns(_FROM, _TO)

        assert [(r["type"], r["domain"]) for r in result] == [
            ("long_domain", long_name)
        ]

    def test_every_txt_name_over_50_is_flagged(self):
        docs = [
            _dns_doc(f"t{i:02d}.mail.example.com", qtype="TXT")
            for i in range(25)
            for _ in range(60)
        ]

        result = DNSAnalytics(FakeOpenSearch(docs)).get_suspicious_dns(_FROM, _TO)

        assert len([r for r in result if r["type"] == "txt_abuse"]) == 25

    def test_tunnel_name_queried_once_is_detected(self):
        encoded = "a1b2c3d4e5f6g7h8i9j0.tunnel.evil.com"
        dns = DNSAnalytics(FakeOpenSearch(self._BUSY + [_dns_doc(encoded)]))

        assert [d["domain"] for d in dns.detect_dns_tunneling(_FROM, _TO)] == [encoded]


class TestGetSuspiciousDns:
    def test_detects_long_domain_names(self, dns, mock_client):
        long_domain = "a" * 60 + ".evil.com"
        reply = {
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

        result = _over(reply).get_suspicious_dns(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        long_findings = [r for r in result if r["type"] == "long_domain"]
        assert len(long_findings) >= 1
        assert long_findings[0]["length"] > 50

    def test_detects_high_frequency(self, dns, mock_client):
        reply = {
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

        result = _over(reply).get_suspicious_dns(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        hf = [r for r in result if r["type"] == "high_frequency"]
        assert len(hf) >= 1

    def test_reverse_lookups_and_plex_names_not_flagged(self, dns, mock_client):
        """#35: long or constantly-queried by design, not exfiltration or beaconing."""
        names = [
            "192-168-1-10.7c0e0efa9cb649e8a8937830d7fe6f23.plex.direct",
            "1.0.17.172.in-addr.arpa",
            "b.a.9.8.7.6.5.0.4.0.0.0.3.0.0.0.2.0.0.0.1.0.0.0.0.0.0.0.1.2.3.4.ip6.arpa",
        ]
        reply = {
            "aggregations": {
                "top_domains": {
                    "buckets": [
                        {"key": n, "doc_count": 1000, "unique_clients": {"value": 1}}
                        for n in names
                    ]
                    + [
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

        result = _over(reply).get_suspicious_dns(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert [(r["type"], r["domain"]) for r in result] == [
            ("high_frequency", "beacon.evil.com")
        ]

    def test_detects_txt_abuse(self, dns, mock_client):
        reply = {
            "aggregations": {
                "top_domains": {"buckets": []},
                "txt_domains": {
                    "buckets": [{"key": "tunnel.evil.com", "doc_count": 100}]
                },
            }
        }

        result = _over(reply).get_suspicious_dns(
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
        reply = {
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

        result = _over(reply).detect_dns_tunneling(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(result) >= 1
        assert result[0]["entropy"] > 3.5

    def test_ignores_normal_domains(self, dns, mock_client):
        reply = {
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

        result = _over(reply).detect_dns_tunneling(
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
                "avg_rtt": {"value": 0.005},  # 5ms; zeek.dns.rtt is seconds
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


# ---------------------------------------------------------------------------
# Data accuracy (2026-11-01): pcap-monitor noise, exact totals, rtt average
# ---------------------------------------------------------------------------

_FROM, _TO = "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
_NOISE = {"term": {"zeek.dns.query": "pcap-monitor"}}
_LOCAL_DISCOVERY = DNS_LOOKUP_EXCLUSION[1]


class TestDnsNoiseExclusion:
    """Malcolm's pcap-monitor lookups were about half of all DNS on the G11."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda d: d.get_top_domains(_FROM, _TO),
            lambda d: d.get_device_dns("192.168.1.10", _FROM, _TO),
            lambda d: d.get_nxdomain_errors(_FROM, _TO),
            lambda d: d.get_query_type_distribution(_FROM, _TO),
            lambda d: d.get_dns_timeline(_FROM, _TO),
            lambda d: d.get_suspicious_dns(_FROM, _TO),
            lambda d: d.detect_dns_tunneling(_FROM, _TO),
            lambda d: d.get_stats(_FROM, _TO),
        ],
        ids=[
            "top_domains",
            "device_dns",
            "nxdomains",
            "query_types",
            "timeline",
            "suspicious",
            "tunneling",
            "stats",
        ],
    )
    def test_every_query_excludes_pcap_monitor(self, dns, mock_client, call):
        mock_client.search.return_value = {}
        call(dns)
        assert mock_client.search.call_args_list
        for c in mock_client.search.call_args_list:
            must_not = c.kwargs["body"]["query"]["bool"]["must_not"]
            assert _NOISE in must_not
            # mDNS/LLMNR/NetBIOS were ~76% of dns.log on the G11 and are not lookups
            assert _LOCAL_DISCOVERY in must_not

    def test_excluded_ips_still_applied(self, dns, mock_client):
        mock_client.search.return_value = {}
        dns.get_stats(_FROM, _TO, excluded_ips=["192.168.1.2"])
        must_not = mock_client.search.call_args.kwargs["body"]["query"]["bool"][
            "must_not"
        ]
        assert must_not == [
            _NOISE,
            _LOCAL_DISCOVERY,
            {"terms": {"source.ip": ["192.168.1.2"]}},
        ]

    def test_log_search_uses_the_same_constant(self):
        import api.logs
        from services.dns_analytics import DNS_NOISE_EXCLUSION

        assert api.logs._EXCLUDE_DNS_NOISE is DNS_NOISE_EXCLUSION
        # Log Explorer still shows mDNS records; only analytics leave them out
        assert _LOCAL_DISCOVERY not in api.logs._EXCLUDE_DNS_NOISE


class TestStatsAccuracy:
    def test_total_counts_past_10000(self, dns, mock_client):
        mock_client.search.return_value = {}
        dns.get_stats(_FROM, _TO)
        assert mock_client.search.call_args.kwargs["body"]["track_total_hits"] is True

    def test_avg_ignores_unanswered_and_median_is_requested(self, dns, mock_client):
        mock_client.search.return_value = {}
        dns.get_stats(_FROM, _TO)
        aggs = mock_client.search.call_args.kwargs["body"]["aggs"]
        assert aggs["avg_rtt"] == {"avg": {"field": "zeek.dns.rtt"}}
        # #93: HDR, not t-digest, so the median doesn't change with how the data is split
        assert aggs["median_rtt"] == {
            "percentiles": {
                "field": "zeek.dns.rtt",
                "percents": [50],
                "hdr": {"number_of_significant_value_digits": 3},
            }
        }

    def test_median_resolution_ms(self, dns, mock_client):
        mock_client.search.return_value = {
            "hits": {"total": {"value": 5433}},
            "aggregations": {
                "avg_rtt": {"value": 1.25},
                "median_rtt": {"values": {"50.0": 0.2}},
            },
        }
        result = dns.get_stats(_FROM, _TO)
        assert result["avg_resolution_ms"] == 1250.0
        assert result["median_resolution_ms"] == 200.0

    def test_no_answered_queries_gives_zero(self, dns, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "avg_rtt": {"value": None},
                "median_rtt": {"values": {"50.0": None}},
            }
        }
        result = dns.get_stats(_FROM, _TO)
        assert result["avg_resolution_ms"] == 0
        assert result["median_resolution_ms"] == 0


def test_local_discovery_exclusion_is_scoped_to_local_destinations():
    """Port 5353 to an internet host is not discovery; it must stay visible (tunneling)."""
    from services.dns_analytics import DNS_LOOKUP_EXCLUSION

    scoped = DNS_LOOKUP_EXCLUSION[1]["bool"]["filter"]
    assert {"terms": {"destination.port": [5353, 5355, 137]}} in scoped
    destinations = next(c for c in scoped if "destination.ip" in c.get("terms", {}))
    assert "224.0.0.0/4" in destinations["terms"]["destination.ip"]
    assert "8.8.8.8" not in destinations["terms"]["destination.ip"]
