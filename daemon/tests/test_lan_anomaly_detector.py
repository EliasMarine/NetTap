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
                "by_ip": {
                    "buckets": [
                        {
                            "key": "192.168.1.1",
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
                "by_ip": {
                    "buckets": [
                        {
                            "key": "192.168.1.1",
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
        mock_client.search.return_value = {
            "aggregations": {"by_ip": {"buckets": []}}
        }

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
                "by_dest_ip": {
                    "buckets": [
                        {
                            "key": "192.168.1.50",
                            "doc_count": 20,
                            "src_mac_count": {"value": 2},
                            "src_macs": {
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
                "by_dest_ip": {
                    "buckets": [
                        {
                            "key": "192.168.1.50",
                            "doc_count": 20,
                            "src_mac_count": {"value": 1},
                            "src_macs": {
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
                    "by_ip": {
                        "buckets": [
                            {
                                "key": "192.168.1.1",
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
                    "by_dest_ip": {
                        "buckets": [
                            {
                                "key": "192.168.1.50",
                                "doc_count": 10,
                                "src_mac_count": {"value": 2},
                                "src_macs": {
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
                    "by_ip": {
                        "buckets": [
                            {
                                "key": "10.0.0.1",
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
            {"aggregations": {"by_dest_ip": {"buckets": []}}},
        ]

        anomalies = detector.get_all_anomalies(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )

        assert len(anomalies) >= 2
        # Critical should come first
        assert anomalies[0]["severity"] == "critical"
