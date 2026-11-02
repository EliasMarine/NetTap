"""
Tests for daemon/services/lan_anomaly_detector.py

All tests use mocks -- no OpenSearch connection required.
"""

import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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

    def test_handles_opensearch_error(self, detector, mock_client):
        mock_client.search.side_effect = Exception("Connection refused")
        alerts = detector.detect_arp_spoofing(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )
        assert alerts == []


# ---------------------------------------------------------------------------
# detect_rogue_dhcp
# ---------------------------------------------------------------------------


class TestDetectRogueDhcp:
    def test_detects_multiple_dhcp_servers(self, detector, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "dhcp_servers": {
                    "buckets": [
                        {
                            "key": "192.168.1.1",
                            "doc_count": 500,
                            "server_mac": {
                                "buckets": [
                                    {"key": "AA:BB:CC:DD:EE:01", "doc_count": 500}
                                ]
                            },
                            "first_seen": {"value": 1704067200000},
                            "last_seen": {"value": 1704153600000},
                        },
                        {
                            "key": "192.168.1.99",
                            "doc_count": 10,
                            "server_mac": {
                                "buckets": [
                                    {"key": "FF:FF:FF:FF:FF:FF", "doc_count": 10}
                                ]
                            },
                            "first_seen": {"value": 1704100000000},
                            "last_seen": {"value": 1704110000000},
                        },
                    ]
                }
            }
        }

        alerts = detector.detect_rogue_dhcp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(alerts) == 1
        assert alerts[0]["type"] == "rogue_dhcp"
        assert alerts[0]["server_ip"] == "192.168.1.99"
        assert alerts[0]["legitimate_server"] == "192.168.1.1"
        assert alerts[0]["severity"] == "critical"

    def test_no_rogue_with_single_server(self, detector, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "dhcp_servers": {
                    "buckets": [
                        {
                            "key": "192.168.1.1",
                            "doc_count": 500,
                            "server_mac": {"buckets": []},
                            "first_seen": {"value": 1704067200000},
                            "last_seen": {"value": 1704153600000},
                        }
                    ]
                }
            }
        }

        alerts = detector.detect_rogue_dhcp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(alerts) == 0

    def test_empty_results(self, detector, mock_client):
        mock_client.search.return_value = {
            "aggregations": {"dhcp_servers": {"buckets": []}}
        }

        alerts = detector.detect_rogue_dhcp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )
        assert alerts == []

    def test_handles_opensearch_error(self, detector, mock_client):
        mock_client.search.side_effect = Exception("Connection refused")
        alerts = detector.detect_rogue_dhcp(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )
        assert alerts == []


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

    def test_handles_opensearch_error(self, detector, mock_client):
        mock_client.search.side_effect = Exception("Timeout")
        alerts = detector.detect_ip_conflicts(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )
        assert alerts == []


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
            # DHCP: no rogue
            {"aggregations": {"dhcp_servers": {"buckets": []}}},
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
            # Rogue DHCP: critical severity
            {
                "aggregations": {
                    "dhcp_servers": {
                        "buckets": [
                            {
                                "key": "192.168.1.1",
                                "doc_count": 100,
                                "server_mac": {"buckets": []},
                                "first_seen": {"value": 0},
                                "last_seen": {"value": 0},
                            },
                            {
                                "key": "192.168.1.99",
                                "doc_count": 5,
                                "server_mac": {"buckets": []},
                                "first_seen": {"value": 0},
                                "last_seen": {"value": 0},
                            },
                        ]
                    }
                }
            },
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
                top = sorted(sorted(set(macs)), key=macs.count, reverse=True)[: agg["terms"]["size"]]
                bucket[name] = {"buckets": [{"key": m, "doc_count": macs.count(m)} for m in top]}
        return bucket

    def search(self, index: str, body: dict) -> dict:
        ((name, agg),) = body["aggs"].items()
        if "composite" in agg:
            if "after" in agg["composite"]:
                return {"aggregations": {name: {"buckets": []}}}
            field = agg["composite"]["sources"][0]["ip"]["terms"]["field"]
            ips = sorted({r[field] for r in self.records})
            buckets = [{"key": {"ip": ip}, **self._bucket(ip, field, agg["aggs"])} for ip in ips]
            return {"aggregations": {name: {"buckets": buckets, "after_key": buckets[-1]["key"]}}}
        field = agg["terms"]["field"]
        ips = sorted({r[field] for r in self.records})
        buckets = [{"key": ip, **self._bucket(ip, field, agg["aggs"])} for ip in ips]
        top = sorted(buckets, key=lambda b: b["doc_count"], reverse=True)[: agg["terms"]["size"]]
        count = next(k for k, v in agg["aggs"].items() if "cardinality" in v)
        return {"aggregations": {name: {"buckets": [b for b in top if b[count]["value"] > 1]}}}


def _arp_records() -> list[dict]:
    """500 busy IPs with one MAC each, then one quiet IP that two MACs used."""
    busy = [
        {"source.ip": ip, "destination.ip": ip, "source.mac": f"00:00:00:00:{i // 256:02x}:{i % 256:02x}"}
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
