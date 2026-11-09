"""
Tests for daemon/services/lan_anomaly_detector.py

All tests use mocks -- no OpenSearch connection required.
"""

import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.excluded_ips import CONN_ACCOUNTING
from services.lan_anomaly_detector import LANAnomalyDetector


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def detector(mock_client):
    return LANAnomalyDetector(client=mock_client)


# ---------------------------------------------------------------------------
# detect_arp_spoofing
# ---------------------------------------------------------------------------


class TestDetectArpSpoofing:
    def test_detects_multiple_macs_for_one_ip(self, detector, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "all": {
                    "buckets": [
                        {
                            "key": {"ip": "192.168.1.1"},
                            "doc_count": 100,
                            "mac_count": {"value": 2},
                            "macs": {
                                "buckets": [
                                    {"key": "AA:BB:CC:DD:EE:01", "doc_count": 60},
                                    {"key": "AA:BB:CC:DD:EE:02", "doc_count": 40},
                                ]
                            },
                        }
                    ]
                }
            }
        }

        alerts = detector.detect_arp_spoofing(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(alerts) == 1
        assert alerts[0]["type"] == "arp_spoofing"
        assert alerts[0]["ip"] == "192.168.1.1"
        assert len(alerts[0]["mac_addresses"]) == 2
        assert alerts[0]["severity"] == "high"

    def test_no_spoofing_when_single_mac(self, detector, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "all": {
                    "buckets": [
                        {
                            "key": {"ip": "192.168.1.1"},
                            "doc_count": 50,
                            "mac_count": {"value": 1},
                            "macs": {
                                "buckets": [
                                    {"key": "AA:BB:CC:DD:EE:01", "doc_count": 50}
                                ]
                            },
                        }
                    ]
                }
            }
        }

        alerts = detector.detect_arp_spoofing(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(alerts) == 0

    def test_empty_results(self, detector, mock_client):
        mock_client.search.return_value = {"aggregations": {"all": {"buckets": []}}}

        alerts = detector.detect_arp_spoofing(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )
        assert alerts == []

    def test_opensearch_error_raises(self, detector, mock_client):
        """#96: [] read as "no ARP spoofing detected"."""
        mock_client.search.side_effect = Exception("Connection refused")
        with pytest.raises(Exception, match="Connection refused"):
            detector.detect_arp_spoofing("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")


# ---------------------------------------------------------------------------
# detect_rogue_dhcp
# ---------------------------------------------------------------------------


def _pairs(*pairs):
    """One composite page of (mac, ip, count) buckets."""
    return {
        "aggregations": {
            "all": {
                "buckets": [
                    {"key": {"mac": m, "ip": ip}, "doc_count": n} for m, ip, n in pairs
                ]
            }
        }
    }


GATEWAY = "d0:21:f9:5e:35:32"


class TestDetectRogueDhcp:
    def _detect(self, detector, mock_client, sent_from_67, answered_on_67):
        mock_client.search.side_effect = [
            _pairs(*sent_from_67),
            _pairs(*answered_on_67),
        ]
        return detector.detect_rogue_dhcp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

    def test_one_gateway_on_three_networks_is_one_server(self, detector, mock_client):
        """The G11: Zeek's DHCP records name clients, and 192.168.1.89 and 10.10.0.108 (devices
        renewing leases) were reported as critical rogue servers."""
        alerts = self._detect(
            detector,
            mock_client,
            [(GATEWAY, "192.168.1.1", 1), (GATEWAY, "192.168.40.1", 1)],
            [
                (GATEWAY, "10.10.0.1", 47),
                (GATEWAY, "192.168.1.1", 180),
                (GATEWAY, "192.168.40.1", 4),
            ],
        )
        assert alerts == []

    def test_a_second_server_device_is_flagged(self, detector, mock_client):
        alerts = self._detect(
            detector,
            mock_client,
            [(GATEWAY, "192.168.1.1", 2), ("aa:bb:cc:00:00:99", "192.168.1.99", 3)],
            [(GATEWAY, "192.168.1.1", 180), (GATEWAY, "10.10.0.1", 40)],
        )
        assert len(alerts) == 1
        a = alerts[0]
        assert (a["type"], a["server_ip"], a["server_mac"], a["offer_count"]) == (
            "rogue_dhcp",
            "192.168.1.99",
            "aa:bb:cc:00:00:99",
            3,
        )
        assert (
            a["legitimate_server"] == "10.10.0.1"
        )  # lowest of the main server's addresses
        assert a["severity"] == "critical"
        assert "192.168.1.99" in a["description"]

    def test_clients_only_means_no_alert(self, detector, mock_client):
        assert self._detect(detector, mock_client, [], []) == []

    def test_a_server_without_a_recorded_mac_counts_by_address(
        self, detector, mock_client
    ):
        alerts = self._detect(
            detector,
            mock_client,
            [],
            [(GATEWAY, "192.168.1.1", 100), (None, "192.168.1.250", 4)],
        )
        assert [(a["server_ip"], a["server_mac"]) for a in alerts] == [
            ("192.168.1.250", "unknown")
        ]

    def test_reads_who_sent_from_and_answered_on_udp_67(self, detector, mock_client):
        self._detect(detector, mock_client, [], [])
        sent, answered = [c.kwargs["body"] for c in mock_client.search.call_args_list]
        for body, side in ((sent, "source"), (answered, "destination")):
            q = body["query"]["bool"]
            assert {"term": {f"{side}.port": 67}} in q["filter"]
            # OLD CODE: assert {"term": {"event.dataset": "conn"}} in q["filter"] (F1)
            assert CONN_ACCOUNTING in q["filter"]
            assert {"terms": {f"{side}.ip": ["255.255.255.255", "0.0.0.0"]}} in q[
                "must_not"
            ]
            assert [
                list(src) for src in body["aggs"]["all"]["composite"]["sources"]
            ] == [["mac"], ["ip"]]
        assert {"range": {"destination.packets": {"gt": 0}}} in answered["query"][
            "bool"
        ]["filter"]

    def test_opensearch_error_raises(self, detector, mock_client):
        """#96: [] read as "no rogue DHCP server"."""
        mock_client.search.side_effect = Exception("Connection refused")
        with pytest.raises(Exception, match="Connection refused"):
            detector.detect_rogue_dhcp("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")


# ---------------------------------------------------------------------------
# detect_ip_conflicts
# ---------------------------------------------------------------------------


class TestDetectIpConflicts:
    def test_detects_ip_conflict(self, detector, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "all": {
                    "buckets": [
                        {
                            "key": {"ip": "192.168.1.50"},
                            "doc_count": 20,
                            "mac_count": {"value": 2},
                            "macs": {
                                "buckets": [
                                    {"key": "AA:BB:CC:11:22:33", "doc_count": 12},
                                    {"key": "DD:EE:FF:44:55:66", "doc_count": 8},
                                ]
                            },
                        }
                    ]
                }
            }
        }

        alerts = detector.detect_ip_conflicts(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(alerts) == 1
        assert alerts[0]["type"] == "ip_conflict"
        assert alerts[0]["ip"] == "192.168.1.50"
        assert len(alerts[0]["mac_addresses"]) == 2
        assert alerts[0]["severity"] == "medium"

    def test_no_conflict_single_mac(self, detector, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "all": {
                    "buckets": [
                        {
                            "key": {"ip": "192.168.1.50"},
                            "doc_count": 20,
                            "mac_count": {"value": 1},
                            "macs": {
                                "buckets": [
                                    {"key": "AA:BB:CC:11:22:33", "doc_count": 20}
                                ]
                            },
                        }
                    ]
                }
            }
        }

        alerts = detector.detect_ip_conflicts(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(alerts) == 0

    def test_opensearch_error_raises(self, detector, mock_client):
        """#96: [] read as "no IP conflicts"."""
        mock_client.search.side_effect = Exception("Timeout")
        with pytest.raises(Exception, match="Timeout"):
            detector.detect_ip_conflicts("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")

    def test_one_failed_check_fails_all_anomalies(self, detector, mock_client):
        """#96: /api/lan/anomalies must not list two checks' findings as the whole picture."""
        mock_client.search.side_effect = Exception("Timeout")
        with pytest.raises(Exception, match="Timeout"):
            detector.get_all_anomalies("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")


# ---------------------------------------------------------------------------
# get_all_anomalies
# ---------------------------------------------------------------------------


class TestGetAllAnomalies:
    def test_combines_all_detection_types(self, detector, mock_client):
        # ARP spoofing response (call 1)
        # Rogue DHCP response (call 2)
        # IP conflict response (call 3)
        mock_client.search.side_effect = [
            # ARP: one spoofing alert
            {
                "aggregations": {
                    "all": {
                        "buckets": [
                            {
                                "key": {"ip": "192.168.1.1"},
                                "doc_count": 50,
                                "mac_count": {"value": 2},
                                "macs": {
                                    "buckets": [
                                        {"key": "AA:AA:AA:AA:AA:AA", "doc_count": 30},
                                        {"key": "BB:BB:BB:BB:BB:BB", "doc_count": 20},
                                    ]
                                },
                            }
                        ]
                    }
                }
            },
            # DHCP: one server (who sent from UDP 67, who answered on it)
            _pairs(),
            _pairs((GATEWAY, "192.168.1.1", 100)),
            # IP conflict: one conflict
            {
                "aggregations": {
                    "all": {
                        "buckets": [
                            {
                                "key": {"ip": "192.168.1.50"},
                                "doc_count": 10,
                                "mac_count": {"value": 2},
                                "macs": {
                                    "buckets": [
                                        {"key": "CC:CC:CC:CC:CC:CC", "doc_count": 6},
                                        {"key": "DD:DD:DD:DD:DD:DD", "doc_count": 4},
                                    ]
                                },
                            }
                        ]
                    }
                }
            },
        ]

        anomalies = detector.get_all_anomalies(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(anomalies) == 2
        types = {a["type"] for a in anomalies}
        assert "arp_spoofing" in types
        assert "ip_conflict" in types

    def test_sorted_by_severity(self, detector, mock_client):
        mock_client.search.side_effect = [
            # ARP: medium severity (ip_conflict) + high (arp_spoofing)
            {
                "aggregations": {
                    "all": {
                        "buckets": [
                            {
                                "key": {"ip": "10.0.0.1"},
                                "doc_count": 20,
                                "mac_count": {"value": 2},
                                "macs": {
                                    "buckets": [
                                        {"key": "A1:B2:C3:D4:E5:F6", "doc_count": 10},
                                        {"key": "11:22:33:44:55:66", "doc_count": 10},
                                    ]
                                },
                            }
                        ]
                    }
                }
            },
            # Rogue DHCP: critical severity (a second device answers DHCP)
            _pairs(("aa:bb:cc:00:00:99", "192.168.1.99", 5)),
            _pairs((GATEWAY, "192.168.1.1", 100)),
            # No IP conflicts
            {"aggregations": {"all": {"buckets": []}}},
        ]

        anomalies = detector.get_all_anomalies(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(anomalies) >= 2
        # Critical should come first
        assert anomalies[0]["severity"] == "critical"


# ---------------------------------------------------------------------------
# Every IP is checked, not just the busiest (#96)
# ---------------------------------------------------------------------------


class _ArpIndex:
    """ARP records answering per-IP aggregations the way OpenSearch does: a terms list keeps
    its top `size` IPs and only then runs bucket_selector; a composite pages every IP."""

    def __init__(self, records: list[dict]):
        self.records = records

    def _bucket(self, ip: str, field: str, sub_aggs: dict) -> dict:
        macs = [r["source.mac"] for r in self.records if r[field] == ip]
        bucket: dict = {"doc_count": len(macs)}
        for name, agg in sub_aggs.items():
            if "cardinality" in agg:
                bucket[name] = {"value": len(set(macs))}
            elif "terms" in agg:
                top = sorted(sorted(set(macs)), key=macs.count, reverse=True)[
                    : agg["terms"]["size"]
                ]
                bucket[name] = {
                    "buckets": [{"key": m, "doc_count": macs.count(m)} for m in top]
                }
        return bucket

    def search(self, index: str, body: dict) -> dict:
        ((name, agg),) = body["aggs"].items()
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        if any("script" in f for f in filters):  # GRATUITOUS_ARP: sender IP = target IP
            return _ArpIndex(
                [r for r in self.records if r["source.ip"] == r["destination.ip"]]
            ).search(index, {**body, "query": {}})
        if "composite" in agg:
            if "after" in agg["composite"]:
                return {"aggregations": {name: {"buckets": []}}}
            field = agg["composite"]["sources"][0]["ip"]["terms"]["field"]
            ips = sorted({r[field] for r in self.records})
            buckets = [
                {"key": {"ip": ip}, **self._bucket(ip, field, agg["aggs"])}
                for ip in ips
            ]
            return {
                "aggregations": {
                    name: {"buckets": buckets, "after_key": buckets[-1]["key"]}
                }
            }
        field = agg["terms"]["field"]
        ips = sorted({r[field] for r in self.records})
        buckets = [{"key": ip, **self._bucket(ip, field, agg["aggs"])} for ip in ips]
        top = sorted(buckets, key=lambda b: b["doc_count"], reverse=True)[
            : agg["terms"]["size"]
        ]
        count = next(k for k, v in agg["aggs"].items() if "cardinality" in v)
        return {
            "aggregations": {
                name: {"buckets": [b for b in top if b[count]["value"] > 1]}
            }
        }


def _arp_records() -> list[dict]:
    """500 busy IPs with one MAC each, then one quiet IP that two MACs used."""
    busy = [
        {
            "source.ip": ip,
            "destination.ip": ip,
            "source.mac": f"00:00:00:00:{i // 256:02x}:{i % 256:02x}",
        }
        for i in range(500)
        for ip in [f"10.0.{i // 250}.{i % 250}"]
        for _ in range(3)
    ]
    quiet = [
        {"source.ip": "10.9.9.9", "destination.ip": "10.9.9.9", "source.mac": mac}
        for mac in ("aa:aa:aa:aa:aa:aa", "bb:bb:bb:bb:bb:bb")
    ]
    return busy + quiet


def test_spoofing_of_an_ip_outside_the_busiest_500_is_found():
    """#96: the >1-MAC filter ran after a 500-IP cut, so this returned []."""
    alerts = LANAnomalyDetector(_ArpIndex(_arp_records())).detect_arp_spoofing(
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
    )
    assert [(a["ip"], a["mac_count"]) for a in alerts] == [("10.9.9.9", 2)]
    assert alerts[0]["mac_addresses"] == ["aa:aa:aa:aa:aa:aa", "bb:bb:bb:bb:bb:bb"]


def test_conflict_on_an_ip_outside_the_busiest_500_is_found():
    """#96: same cut on destination.ip."""
    alerts = LANAnomalyDetector(_ArpIndex(_arp_records())).detect_ip_conflicts(
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
    )
    assert [(a["ip"], a["mac_count"]) for a in alerts] == [("10.9.9.9", 2)]


def test_hosts_asking_for_the_router_are_not_an_ip_conflict():
    """Grouped by target IP, every "who has 192.168.1.1?" counted its asker's MAC, so the router
    was an IP conflict on any network; only announcements of one's own address count."""
    asks = [
        {
            "source.ip": f"192.168.1.{n}",
            "destination.ip": "192.168.1.1",
            "source.mac": f"aa:00:00:00:00:{n:02x}",
        }
        for n in range(10, 20)
    ]
    announce = [
        {"source.ip": "192.168.1.50", "destination.ip": "192.168.1.50", "source.mac": m}
        for m in ("cc:cc:cc:cc:cc:01", "cc:cc:cc:cc:cc:02")
    ]
    alerts = LANAnomalyDetector(_ArpIndex(asks + announce)).detect_ip_conflicts(
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
    )
    assert [a["ip"] for a in alerts] == ["192.168.1.50"]
