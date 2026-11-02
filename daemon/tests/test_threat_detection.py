"""
Tests for daemon/services/threat_detection.py

Covers pure utility functions: Shannon entropy, beacon confidence scoring,
and RFC1918 internal IP detection. All tests are self-contained with no
external dependencies (OpenSearch calls are not tested here).
"""

import sys
import os

from services.dns_analytics import DNS_LOOKUP_EXCLUSION

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from services.threat_detection import (
    _shannon_entropy,
    _beacon_confidence,
    _is_internal,
)


# ---------------------------------------------------------------------------
# Shannon Entropy
# ---------------------------------------------------------------------------


class TestShannonEntropy:
    """Tests for _shannon_entropy()."""

    def test_shannon_entropy_random_high(self):
        """A random-looking string should have high entropy (>3.5)."""
        # Simulate a DGA-like string with varied characters
        result = _shannon_entropy("x7k2m9q4z1w8")
        assert result > 3.5, f"Expected high entropy, got {result}"

    def test_shannon_entropy_simple_low(self):
        """A repeated single character should have zero entropy."""
        result = _shannon_entropy("aaaaaa")
        assert result == 0.0, f"Expected 0.0 entropy for uniform string, got {result}"

    def test_shannon_entropy_empty(self):
        """An empty string should return 0.0."""
        result = _shannon_entropy("")
        assert result == 0.0

    def test_shannon_entropy_two_chars(self):
        """A string with exactly two equally distributed chars has entropy 1.0."""
        result = _shannon_entropy("ababab")
        assert abs(result - 1.0) < 0.01, f"Expected ~1.0, got {result}"


# ---------------------------------------------------------------------------
# Beacon Confidence
# ---------------------------------------------------------------------------


class TestBeaconConfidence:
    """Tests for _beacon_confidence()."""

    def test_beacon_confidence_high(self):
        """Low jitter + high count + common interval = high confidence score."""
        # cv=0.03 (<0.05 → +50), count=150 (>100 → +30), interval=60 (common → +20)
        result = _beacon_confidence(cv=0.03, count=150, interval=60.0)
        assert result == 100.0, f"Expected 100.0, got {result}"

    def test_beacon_confidence_low(self):
        """High jitter + low count + non-standard interval = low confidence."""
        # cv=0.14 (<0.15 → +20), count=12 (<20 → +0), interval=77 (not common → +0)
        result = _beacon_confidence(cv=0.14, count=12, interval=77.0)
        assert result == 20.0, f"Expected 20.0, got {result}"

    def test_beacon_confidence_medium(self):
        """Medium jitter + medium count + common interval = medium score."""
        # cv=0.07 (<0.10 → +35), count=55 (>50 → +20), interval=300 (common → +20)
        result = _beacon_confidence(cv=0.07, count=55, interval=300.0)
        assert result == 75.0, f"Expected 75.0, got {result}"

    def test_beacon_confidence_capped_at_100(self):
        """Score should never exceed 100."""
        result = _beacon_confidence(cv=0.01, count=200, interval=60.0)
        assert result <= 100.0


# ---------------------------------------------------------------------------
# Internal IP Detection
# ---------------------------------------------------------------------------


class TestIsInternal:
    """Tests for _is_internal()."""

    def test_is_internal_192_168(self):
        """192.168.x.x addresses are internal."""
        assert _is_internal("192.168.1.100") is True

    def test_is_internal_10(self):
        """10.x.x.x addresses are internal."""
        assert _is_internal("10.0.0.1") is True

    def test_is_internal_172_16(self):
        """172.16.x.x addresses are internal."""
        assert _is_internal("172.16.0.1") is True

    def test_is_internal_172_31(self):
        """172.31.x.x addresses are internal (upper bound of 172.16-31 range)."""
        assert _is_internal("172.31.255.254") is True

    def test_is_internal_external(self):
        """8.8.8.8 is a public IP and should return False."""
        assert _is_internal("8.8.8.8") is False

    def test_is_internal_external_1_1_1_1(self):
        """1.1.1.1 is external."""
        assert _is_internal("1.1.1.1") is False

    def test_is_internal_172_outside_range(self):
        """172.32.x.x is outside the RFC1918 range and should be external."""
        assert _is_internal("172.32.0.1") is False


# ---------------------------------------------------------------------------
# DNS anomalies skip pcap-monitor (2026-11-01)
# ---------------------------------------------------------------------------


class TestDnsAnomalyNoise:
    def test_pcap_monitor_excluded(self):
        """Malcolm's own NXDOMAIN-heavy health check showed up as an NXDOMAIN spike."""
        from unittest.mock import MagicMock

        from services.threat_detection import analyze_dns_anomalies

        client = MagicMock()
        client.search.return_value = {}
        analyze_dns_anomalies(client, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        must_not = client.search.call_args.kwargs["body"]["query"]["bool"]["must_not"]
        assert {"term": {"zeek.dns.query": "pcap-monitor"}} in must_not
        # long mDNS service names would otherwise read as DNS tunneling
        assert DNS_LOOKUP_EXCLUSION[1] in must_not


# ---------------------------------------------------------------------------
# DGA rule scores the registered name (#35, 2026-11-02)
# ---------------------------------------------------------------------------


class TestDgaRegisteredName:
    """Real names the G11 flagged as DGA because the rule scored the leftmost label."""

    def _dga(self, domains: list[str]) -> list[str]:
        from services.threat_detection import analyze_dns_anomalies
        from tests.fake_opensearch import FakeOpenSearch

        # OLD CODE START — #96: mocked the old top-500 terms reply; names are now paged
        # client = MagicMock()
        # client.search.return_value = {
        #     "aggregations": {"domains": {"buckets": [{"key": d, "doc_count": 5} for d in domains]}}
        # }
        # OLD CODE END
        client = FakeOpenSearch([_dns(d) for d in domains for _ in range(5)])
        found = analyze_dns_anomalies(client, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        return [f["domain"] for f in found["dga_suspects"]]

    def test_random_hostname_under_real_domain_not_flagged(self):
        assert self._dga([
            "7b18d6de7a0148e5ae70caf5253e933c-7a0ef8ad28aa.cdn.forter.com",
            "23o27znco77ezwi2qraa3vul2diwfioswcqputkh0e9e8735e3b694b2sac.d.aa.online-metrix.net",
            "s3-figma-force-client-reloads-production.figma.com",
        ]) == []

    def test_single_label_lan_hostname_not_flagged(self):
        assert self._dga(["sarabouzeid-fgwk3p497k"]) == []

    def test_hyphenated_words_not_flagged(self):
        assert self._dga(["browser-intake-datadoghq.com"]) == []

    def test_random_registered_name_flagged(self):
        # equal counts and entropy: name order, as OpenSearch breaks count ties
        assert self._dga(["www.kq3z8wxv1m7tbn5r6yhp.com", "kq3z8wxv1m7tbn5r6yhp.co.uk"]) == [
            "kq3z8wxv1m7tbn5r6yhp.co.uk",
            "www.kq3z8wxv1m7tbn5r6yhp.com",
        ]


# ---------------------------------------------------------------------------
# Detections see every pair and name, not the first page (#96)
# ---------------------------------------------------------------------------

_T0 = 1_767_225_600_000  # 2026-01-01T00:00:00Z in epoch ms
_DAY = ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")


def _conn(src: str, dst: str, port: int, ts: int) -> dict:
    return {
        "event.provider": "zeek",
        "event.dataset": "conn",
        "source.ip": src,
        "destination.ip": dst,
        "destination.port": port,
        "@timestamp": ts,
    }


def _dns(name: str, src: str = "192.168.1.10", rcode: str = "NOERROR") -> dict:
    return {
        "event.provider": "zeek",
        "event.dataset": "dns",
        "zeek.dns.query": name,
        "zeek.dns.rcode_name": rcode,
        "source.ip": src,
        "destination.ip": "8.8.8.8",
        "destination.port": 53,
        "@timestamp": _T0,
    }


def _beacon_docs(src: str, every_s: int, count: int) -> list[dict]:
    return [_conn(src, "203.0.113.9", 443, _T0 + k * every_s * 1000) for k in range(count)]


class TestBeaconingSeesEveryPair:
    def test_beacon_after_the_first_300_pairs_is_found(self):
        """One 300-pair page in key order: 192.168.1.50 sorted after 400 one-off 10.x pairs."""
        from services.threat_detection import detect_beaconing
        from tests.fake_opensearch import FakeOpenSearch

        noise = [_conn(f"10.0.{i // 200}.{i % 200}", "198.51.100.1", 443, _T0) for i in range(400)]
        client = FakeOpenSearch(noise + _beacon_docs("192.168.1.50", 60, 20))

        beacons, complete = detect_beaconing(client, *_DAY)

        assert [(b["source_ip"], b["interval_seconds"], b["connection_count"]) for b in beacons] == [
            ("192.168.1.50", 60.0, 20)
        ]
        assert complete is True

    def test_requests_stay_under_max_buckets(self, monkeypatch):
        """30 pairs x 40 slots in one response passed max_buckets and read as "no beacons"."""
        import services.threat_detection as td
        from tests.fake_opensearch import FakeOpenSearch

        monkeypatch.setattr(td, "HISTOGRAM_BUCKETS_PER_REQUEST", 500, raising=False)
        irregular = [
            _conn(f"10.0.0.{i}", "198.51.100.1", 443, _T0 + k * k * 10_000) for i in range(29) for k in range(40)
        ]
        client = FakeOpenSearch(irregular + _beacon_docs("192.168.1.50", 300, 40), max_buckets=1_000)

        beacons, complete = td.detect_beaconing(client, *_DAY)

        assert [b["source_ip"] for b in beacons] == ["192.168.1.50"]
        assert max(client.bucket_counts) <= 500

    def test_pair_too_busy_for_a_shared_request_is_paged(self, monkeypatch):
        import services.threat_detection as td
        from tests.fake_opensearch import FakeOpenSearch

        monkeypatch.setattr(td, "HISTOGRAM_BUCKETS_PER_REQUEST", 20)
        client = FakeOpenSearch(_beacon_docs("192.168.1.50", 60, 30))

        beacons, complete = td.detect_beaconing(client, "now-1h", "now")

        assert [(b["source_ip"], b["connection_count"]) for b in beacons] == [("192.168.1.50", 30)]
        assert any("date_histogram" in str(b["aggs"]["all"]["composite"]["sources"]) for b in client.bodies)

    def test_budget_is_under_opensearch_max_buckets(self):
        from services.threat_detection import HISTOGRAM_BUCKETS_PER_REQUEST

        assert HISTOGRAM_BUCKETS_PER_REQUEST < 65_535


class TestLateralMovementSeesEveryPair:
    def test_internal_fan_out_behind_400_inbound_scans_is_found(self):
        """Public scanners on 22 sort before 192.168.x and filled the one 300-pair page."""
        from services.threat_detection import detect_lateral_movement
        from tests.fake_opensearch import FakeOpenSearch

        scans = [_conn(f"1.2.{i // 200}.{i % 200}", "192.168.1.10", 22, _T0) for i in range(400)]
        fan_out = [_conn("192.168.1.66", f"192.168.1.{h}", 445, _T0 + h) for h in (10, 11, 12)]
        client = FakeOpenSearch(scans + fan_out)

        moves, complete = detect_lateral_movement(client, *_DAY)

        assert sorted((m["source_ip"], m["destination_ip"], m.get("fan_out")) for m in moves) == [
            ("192.168.1.66", "192.168.1.10", 3),
            ("192.168.1.66", "192.168.1.11", 3),
            ("192.168.1.66", "192.168.1.12", 3),
        ]
        assert complete is True


class TestDnsAnomaliesSeeEveryNameAndSource:
    def test_once_queried_names_and_the_101st_source_are_checked(self):
        """Top 500 names / top 100 sources: tunnel and DGA names are queried ~once, so were cut."""
        from services.threat_detection import analyze_dns_anomalies
        from tests.fake_opensearch import FakeOpenSearch

        tunnel = "x" * 55 + ".t.evil-tunnel.com"
        docs = (
            [_dns("www.example.com", f"10.1.0.{s}") for s in range(1, 101) for _ in range(80)]
            + [_dns(f"site{i}.example.org", "10.1.0.1") for i in range(600) for _ in range(3)]
            + [_dns(f"zz{k}.invalid-test.net", "10.9.9.9", "NXDOMAIN") for k in range(45)]
            + [_dns("www.example.com", "10.9.9.9") for _ in range(15)]
            + [_dns(tunnel, "10.9.9.8"), _dns("kq3z8wxv1m7tbn5r6yhp.com", "10.9.9.8")]
        )

        found = analyze_dns_anomalies(FakeOpenSearch(docs), *_DAY)

        assert [d["domain"] for d in found["dga_suspects"]] == ["kq3z8wxv1m7tbn5r6yhp.com"]
        assert [t["domain"] for t in found["tunnel_suspects"]] == [tunnel]
        assert [(s["source_ip"], s["nxdomain_count"], s["unique_domains"]) for s in found["nxdomain_spikes"]] == [
            ("10.9.9.9", 45, 46)
        ]
        assert found["complete"] is True


class TestDetectorsDoNotHideFailures:
    """#96: a failed query returned [] and the page said "No beaconing patterns detected"."""

    def _failing_client(self):
        from unittest.mock import MagicMock

        client = MagicMock()
        client.search.side_effect = ConnectionError("OpenSearch unreachable")
        return client

    def test_each_detector_raises_when_its_query_fails(self):
        import pytest

        from services.threat_detection import analyze_dns_anomalies, detect_beaconing, detect_lateral_movement

        for detect in (detect_beaconing, detect_lateral_movement, analyze_dns_anomalies):
            with pytest.raises(ConnectionError):
                detect(self._failing_client(), *_DAY)

    def test_a_capped_scan_says_it_is_incomplete(self, monkeypatch):
        import services.threat_detection as td
        from tests.fake_opensearch import FakeOpenSearch

        real = td.all_buckets
        monkeypatch.setattr(td, "all_buckets", lambda *a, **kw: real(*a, **{**kw, "page_size": 1, "max_buckets": 1}))
        fan_out = [_conn("192.168.1.66", f"192.168.1.{h}", 445, _T0 + h) for h in (10, 11, 12)]

        moves, complete = td.detect_lateral_movement(FakeOpenSearch(fan_out), *_DAY)

        assert complete is False
        assert len(moves) == 1
