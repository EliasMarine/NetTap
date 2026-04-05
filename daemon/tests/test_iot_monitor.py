"""
Tests for daemon/services/iot_monitor.py

All tests use mocks -- no OpenSearch connection required.
"""

import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.iot_monitor import (
    IoTMonitor,
    ANOMALY_NEW_DESTINATION,
    ANOMALY_NEW_COUNTRY,
    ANOMALY_NEW_PORT,
    ANOMALY_VOLUME_SPIKE,
    ANOMALY_PROTOCOL_CHANGE,
)


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def iot(mock_client):
    return IoTMonitor(client=mock_client)


# ---------------------------------------------------------------------------
# classify_as_iot
# ---------------------------------------------------------------------------


class TestClassifyAsIot:
    def test_known_iot_manufacturer(self, iot):
        result = iot.classify_as_iot(
            "AA:BB:CC:DD:EE:FF",
            {"manufacturer": "Ring", "hostname": "ring-doorbell"},
        )
        assert result is True

    def test_known_iot_by_hostname(self, iot):
        result = iot.classify_as_iot(
            "AA:BB:CC:DD:EE:FF",
            {"manufacturer": "Unknown", "hostname": "roku-livingroom"},
        )
        assert result is True

    def test_non_iot_device(self, iot):
        result = iot.classify_as_iot(
            "AA:BB:CC:DD:EE:FF",
            {"manufacturer": "Dell", "hostname": "desktop-pc"},
        )
        assert result is False

    def test_adds_to_iot_registry(self, iot):
        iot.classify_as_iot(
            "aa:bb:cc:dd:ee:ff",
            {"manufacturer": "Nest", "ip": "192.168.1.50"},
        )
        devices = iot.get_iot_devices()
        assert len(devices) == 1
        assert devices[0]["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_case_insensitive(self, iot):
        assert iot.classify_as_iot("A:B:C", {"manufacturer": "WYZE"}) is True
        assert iot.classify_as_iot("D:E:F", {"manufacturer": "tp-link"}) is True


# ---------------------------------------------------------------------------
# build_baseline
# ---------------------------------------------------------------------------


class TestBuildBaseline:
    def test_builds_baseline_from_opensearch(self, iot, mock_client):
        mock_client.search.return_value = {
            "hits": {"total": {"value": 1000}},
            "aggregations": {
                "destinations": {
                    "buckets": [
                        {"key": "8.8.8.8", "doc_count": 100},
                        {"key": "1.1.1.1", "doc_count": 50},
                    ]
                },
                "dest_ports": {
                    "buckets": [
                        {"key": 443, "doc_count": 800},
                        {"key": 80, "doc_count": 200},
                    ]
                },
                "protocols": {
                    "buckets": [{"key": "tcp", "doc_count": 1000}]
                },
                "hourly_activity": {"buckets": []},
                "total_bytes": {"value": 5000000},
                "countries": {
                    "buckets": [{"key": "United States", "doc_count": 900}]
                },
            },
        }

        baseline = iot.build_baseline("AA:BB:CC:DD:EE:FF", days=7)

        assert baseline["mac"] == "AA:BB:CC:DD:EE:FF"
        assert "8.8.8.8" in baseline["known_destinations"]
        assert 443 in baseline["known_ports"]
        assert "tcp" in baseline["known_protocols"]
        assert baseline["total_bytes"] == 5000000
        assert baseline["connection_count"] == 1000

    def test_handles_opensearch_error(self, iot, mock_client):
        mock_client.search.side_effect = Exception("Connection refused")
        baseline = iot.build_baseline("AA:BB:CC:DD:EE:FF")
        assert "error" in baseline

    def test_stores_baseline(self, iot, mock_client):
        mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "destinations": {"buckets": []},
                "dest_ports": {"buckets": []},
                "protocols": {"buckets": []},
                "hourly_activity": {"buckets": []},
                "total_bytes": {"value": 0},
                "countries": {"buckets": []},
            },
        }

        iot.build_baseline("AA:BB:CC:DD:EE:FF")
        result = iot.get_device_baseline("AA:BB:CC:DD:EE:FF")
        assert result is not None
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"


# ---------------------------------------------------------------------------
# check_anomalies
# ---------------------------------------------------------------------------


class TestCheckAnomalies:
    def _setup_baseline(self, iot, mock_client):
        """Pre-populate a baseline for testing anomaly detection."""
        mock_client.search.return_value = {
            "hits": {"total": {"value": 1000}},
            "aggregations": {
                "destinations": {
                    "buckets": [{"key": "8.8.8.8", "doc_count": 100}]
                },
                "dest_ports": {
                    "buckets": [{"key": 443, "doc_count": 800}]
                },
                "protocols": {
                    "buckets": [{"key": "tcp", "doc_count": 1000}]
                },
                "hourly_activity": {"buckets": []},
                "total_bytes": {"value": 240000},  # ~10K/hr average
                "countries": {
                    "buckets": [{"key": "United States", "doc_count": 900}]
                },
            },
        }
        iot.build_baseline("AA:BB:CC:DD:EE:FF")

    def test_detects_new_destination(self, iot, mock_client):
        self._setup_baseline(iot, mock_client)

        # Now return anomalous data with new destination
        mock_client.search.return_value = {
            "aggregations": {
                "destinations": {
                    "buckets": [
                        {"key": "8.8.8.8", "doc_count": 10},
                        {"key": "185.100.87.202", "doc_count": 5},
                    ]
                },
                "dest_ports": {"buckets": [{"key": 443, "doc_count": 15}]},
                "protocols": {"buckets": [{"key": "tcp", "doc_count": 15}]},
                "total_bytes": {"value": 1000},
                "countries": {
                    "buckets": [{"key": "United States", "doc_count": 15}]
                },
            }
        }

        anomalies = iot.check_anomalies("AA:BB:CC:DD:EE:FF")
        new_dest = [a for a in anomalies if a["type"] == ANOMALY_NEW_DESTINATION]
        assert len(new_dest) >= 1
        assert new_dest[0]["detail"] == "185.100.87.202"

    def test_detects_new_country(self, iot, mock_client):
        self._setup_baseline(iot, mock_client)

        mock_client.search.return_value = {
            "aggregations": {
                "destinations": {"buckets": []},
                "dest_ports": {"buckets": []},
                "protocols": {"buckets": []},
                "total_bytes": {"value": 100},
                "countries": {
                    "buckets": [{"key": "Russia", "doc_count": 5}]
                },
            }
        }

        anomalies = iot.check_anomalies("AA:BB:CC:DD:EE:FF")
        new_country = [a for a in anomalies if a["type"] == ANOMALY_NEW_COUNTRY]
        assert len(new_country) >= 1
        assert new_country[0]["detail"] == "Russia"

    def test_detects_new_port(self, iot, mock_client):
        self._setup_baseline(iot, mock_client)

        mock_client.search.return_value = {
            "aggregations": {
                "destinations": {"buckets": []},
                "dest_ports": {
                    "buckets": [{"key": 22, "doc_count": 3}]
                },
                "protocols": {"buckets": []},
                "total_bytes": {"value": 100},
                "countries": {"buckets": []},
            }
        }

        anomalies = iot.check_anomalies("AA:BB:CC:DD:EE:FF")
        new_port = [a for a in anomalies if a["type"] == ANOMALY_NEW_PORT]
        assert len(new_port) >= 1

    def test_detects_volume_spike(self, iot, mock_client):
        self._setup_baseline(iot, mock_client)

        mock_client.search.return_value = {
            "aggregations": {
                "destinations": {"buckets": []},
                "dest_ports": {"buckets": []},
                "protocols": {"buckets": []},
                "total_bytes": {"value": 100000},  # Way above 10K/hr avg
                "countries": {"buckets": []},
            }
        }

        anomalies = iot.check_anomalies("AA:BB:CC:DD:EE:FF")
        spike = [a for a in anomalies if a["type"] == ANOMALY_VOLUME_SPIKE]
        assert len(spike) >= 1

    def test_no_anomalies_when_normal(self, iot, mock_client):
        self._setup_baseline(iot, mock_client)

        mock_client.search.return_value = {
            "aggregations": {
                "destinations": {
                    "buckets": [{"key": "8.8.8.8", "doc_count": 10}]
                },
                "dest_ports": {
                    "buckets": [{"key": 443, "doc_count": 10}]
                },
                "protocols": {
                    "buckets": [{"key": "tcp", "doc_count": 10}]
                },
                "total_bytes": {"value": 500},  # Normal volume
                "countries": {
                    "buckets": [{"key": "United States", "doc_count": 10}]
                },
            }
        }

        anomalies = iot.check_anomalies("AA:BB:CC:DD:EE:FF")
        # Should have no destination/port/protocol/country/volume anomalies
        typed = [
            a for a in anomalies
            if a["type"] in (
                ANOMALY_NEW_DESTINATION, ANOMALY_NEW_COUNTRY,
                ANOMALY_NEW_PORT, ANOMALY_VOLUME_SPIKE, ANOMALY_PROTOCOL_CHANGE,
            )
        ]
        assert len(typed) == 0

    def test_no_baseline_returns_empty(self, iot):
        anomalies = iot.check_anomalies("FF:FF:FF:FF:FF:FF")
        assert anomalies == []


# ---------------------------------------------------------------------------
# get_iot_devices / get_anomalies
# ---------------------------------------------------------------------------


class TestIoTDeviceRegistry:
    def test_initially_empty(self, iot):
        assert iot.get_iot_devices() == []

    def test_get_device_baseline_none(self, iot):
        assert iot.get_device_baseline("FF:FF:FF:FF:FF:FF") is None

    def test_get_anomalies_checks_all_devices(self, iot, mock_client):
        # Register two IoT devices
        iot.classify_as_iot("AA:AA:AA:AA:AA:AA", {"manufacturer": "Ring"})
        iot.classify_as_iot("BB:BB:BB:BB:BB:BB", {"manufacturer": "Nest"})

        # Both have no baselines, so check_anomalies returns []
        anomalies = iot.get_anomalies(
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
        )
        assert anomalies == []


# ---------------------------------------------------------------------------
# Fleet Summary
# ---------------------------------------------------------------------------


class TestFleetSummary:
    def test_returns_health_score(self, iot, mock_client):
        """Fleet summary returns all required top-level keys."""
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
        }
        iot._baselines = {
            "AA:BB:CC:DD:EE:FF": {
                "known_destinations": ["1.2.3.4"],
                "known_ports": [443],
                "known_countries": ["US"],
                "daily_avg_bytes": 1000,
                "connection_count": 100,
                "active_hours": [8, 9, 10, 11, 12],
            },
        }
        # Mock OpenSearch to return empty aggregations for all queries
        mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {
                "by_mac": {"buckets": []},
            },
        }

        result = iot.get_fleet_summary(
            "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert "health_score" in result
        assert "health_grade" in result
        assert "device_count" in result
        assert result["device_count"] == 1
        assert "devices" in result
        assert len(result["devices"]) == 1
        assert "privacy_score" in result
        assert "security_score" in result
        assert "behavior_score" in result
        assert "anomaly_count" in result
        assert "privacy_concerns" in result
        assert "unencrypted_count" in result
        assert "subtitle" in result

    def test_empty_fleet(self, iot, mock_client):
        """Fleet summary with no IoT devices returns healthy defaults."""
        result = iot.get_fleet_summary(
            "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert result["health_score"] == 100
        assert result["health_grade"] == "A"
        assert result["device_count"] == 0
        assert result["devices"] == []

    def test_device_details_in_response(self, iot, mock_client):
        """Each device in the fleet summary has required per-device fields."""
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
        }
        mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {"by_mac": {"buckets": []}},
        }

        result = iot.get_fleet_summary(
            "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        dev = result["devices"][0]
        assert dev["mac"] == "AA:BB:CC:DD:EE:FF"
        assert dev["manufacturer"] == "Ring"
        assert "score" in dev
        assert "grade" in dev
        assert "privacy_score" in dev
        assert "security_score" in dev
        assert "behavior_score" in dev
        assert "anomaly_count" in dev
        assert "encryption_pct" in dev
        assert "tracker_count" in dev

    def test_with_conn_stats(self, iot, mock_client):
        """Fleet summary integrates OpenSearch connection data."""
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
        }
        iot._baselines = {
            "AA:BB:CC:DD:EE:FF": {
                "known_destinations": ["1.2.3.4"],
                "known_ports": [443],
                "known_countries": ["US"],
                "daily_avg_bytes": 50000,
                "connection_count": 100,
                "active_hours": list(range(24)),
            },
        }

        # First call: conn stats, second: alert counts, third: DNS stats
        # Then anomaly check calls (for check_anomalies per device)
        mock_client.search.side_effect = [
            # Conn stats batch
            {
                "hits": {"total": {"value": 50}},
                "aggregations": {
                    "by_mac": {
                        "buckets": [
                            {
                                "key": "AA:BB:CC:DD:EE:FF",
                                "doc_count": 50,
                                "total_bytes": {"value": 10000},
                                "dest_ports": {
                                    "buckets": [
                                        {"key": 443, "doc_count": 45},
                                        {"key": 80, "doc_count": 5},
                                    ]
                                },
                                "encrypted": {"doc_count": 45},
                                "third_party_orgs": {"value": 3},
                            }
                        ]
                    }
                },
            },
            # Alert counts
            {
                "hits": {"total": {"value": 0}},
                "aggregations": {"by_mac": {"buckets": []}},
            },
            # DNS tracker batch
            {
                "hits": {"total": {"value": 10}},
                "aggregations": {
                    "by_mac": {
                        "buckets": [
                            {
                                "key": "AA:BB:CC:DD:EE:FF",
                                "doc_count": 10,
                                "queried_domains": {
                                    "buckets": [
                                        {"key": "ring.com", "doc_count": 5},
                                        {"key": "google-analytics.com", "doc_count": 3},
                                    ]
                                },
                            }
                        ]
                    }
                },
            },
            # check_anomalies call for the device
            {
                "aggregations": {
                    "destinations": {"buckets": [{"key": "1.2.3.4", "doc_count": 10}]},
                    "dest_ports": {"buckets": [{"key": 443, "doc_count": 10}]},
                    "protocols": {"buckets": [{"key": "tcp", "doc_count": 10}]},
                    "total_bytes": {"value": 500},
                    "countries": {"buckets": [{"key": "US", "doc_count": 10}]},
                },
            },
        ]

        result = iot.get_fleet_summary(
            "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )

        assert result["device_count"] == 1
        dev = result["devices"][0]
        assert dev["encryption_pct"] == 90  # 45/50 = 0.9
        assert dev["tracker_count"] == 1  # google-analytics.com is a tracker
        assert isinstance(result["health_score"], int)
        assert result["health_score"] > 0

    def test_multiple_devices(self, iot, mock_client):
        """Fleet summary handles multiple devices."""
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
            "11:22:33:44:55:66": {
                "mac": "11:22:33:44:55:66",
                "manufacturer": "Nest",
                "ip": "192.168.1.51",
                "hostname": "nest-thermostat",
                "classified_at": "2026-04-04T01:00:00Z",
            },
        }
        mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {"by_mac": {"buckets": []}},
        }

        result = iot.get_fleet_summary(
            "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert result["device_count"] == 2
        assert len(result["devices"]) == 2

    def test_subtitle_healthy(self, iot, mock_client):
        """Subtitle reflects a healthy fleet."""
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
        }
        mock_client.search.return_value = {
            "hits": {"total": {"value": 0}},
            "aggregations": {"by_mac": {"buckets": []}},
        }

        result = iot.get_fleet_summary(
            "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert isinstance(result["subtitle"], str)
        assert len(result["subtitle"]) > 0

    def test_tracker_domain_detection(self, iot):
        """Verify tracker domain suffix matching works."""
        assert iot._is_tracker_domain("google-analytics.com") is True
        assert iot._is_tracker_domain("sub.google-analytics.com") is True
        assert iot._is_tracker_domain("notgoogle-analytics.com") is False
        assert iot._is_tracker_domain("ring.com") is False
        assert iot._is_tracker_domain("mixpanel.com") is True
        assert iot._is_tracker_domain("api.mixpanel.com") is True

    def test_opensearch_error_handled(self, iot, mock_client):
        """Fleet summary handles OpenSearch failures gracefully."""
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
        }
        mock_client.search.side_effect = Exception("Connection refused")

        result = iot.get_fleet_summary(
            "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        # Should still return a valid structure (empty stats, default scores)
        assert result["device_count"] == 1
        assert "health_score" in result
        assert "devices" in result


# ---------------------------------------------------------------------------
# Privacy Report
# ---------------------------------------------------------------------------


class TestPrivacyReport:
    def _setup_devices(self, iot):
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
        }

    def test_empty_devices(self, iot):
        result = iot.get_privacy_report("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert result == {"devices": []}

    def test_returns_device_privacy_data(self, iot, mock_client):
        self._setup_devices(iot)
        # conn stats batch, alert counts, DNS detail batch
        mock_client.search.side_effect = [
            # Conn stats
            {
                "aggregations": {
                    "by_mac": {
                        "buckets": [
                            {
                                "key": "AA:BB:CC:DD:EE:FF",
                                "doc_count": 100,
                                "total_bytes": {"value": 50000},
                                "dest_ports": {"buckets": [{"key": 443, "doc_count": 90}]},
                                "encrypted": {"doc_count": 90},
                                "third_party_orgs": {"value": 3},
                            }
                        ]
                    }
                },
            },
            # Alert counts
            {"aggregations": {"by_mac": {"buckets": []}}},
            # DNS tracker detail
            {
                "aggregations": {
                    "by_mac": {
                        "buckets": [
                            {
                                "key": "AA:BB:CC:DD:EE:FF",
                                "doc_count": 50,
                                "queried_domains": {
                                    "buckets": [
                                        {"key": "ring.com", "doc_count": 30},
                                        {"key": "google-analytics.com", "doc_count": 15},
                                        {"key": "crashlytics.com", "doc_count": 5},
                                    ]
                                },
                            }
                        ]
                    }
                },
            },
        ]

        result = iot.get_privacy_report("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert "devices" in result
        assert len(result["devices"]) == 1
        dev = result["devices"][0]
        assert dev["mac"] == "AA:BB:CC:DD:EE:FF"
        assert "privacy_grade" in dev
        assert "privacy_score" in dev
        assert "tracker_domains" in dev
        assert isinstance(dev["tracker_domains"], list)
        assert "encryption_ratio" in dev
        assert dev["encryption_ratio"] == 0.9
        assert "phone_home_per_hour" in dev
        assert dev["tracker_count"] >= 1  # at least google-analytics.com

    def test_opensearch_error(self, iot, mock_client):
        self._setup_devices(iot)
        mock_client.search.side_effect = Exception("Connection refused")

        result = iot.get_privacy_report("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        # Should still return valid structure with default data
        assert "devices" in result
        assert len(result["devices"]) == 1


# ---------------------------------------------------------------------------
# Communication Map
# ---------------------------------------------------------------------------


class TestCommunicationMap:
    def test_empty_result(self, iot, mock_client):
        mock_client.search.return_value = {
            "aggregations": {"by_dest": {"buckets": []}},
        }

        result = iot.get_communication_map(
            "AA:BB:CC:DD:EE:FF", "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        assert result["destinations"] == []

    def test_returns_destinations(self, iot, mock_client):
        mock_client.search.side_effect = [
            # Main conn query
            {
                "aggregations": {
                    "by_dest": {
                        "buckets": [
                            {
                                "key": "54.239.28.85",
                                "doc_count": 234,
                                "ports": {"buckets": [{"key": 443, "doc_count": 234}]},
                                "bytes_sent": {"value": 12500},
                                "bytes_received": {"value": 45000},
                                "country": {"buckets": [{"key": "US", "doc_count": 234}]},
                                "first_seen": {"value": 1709251200000, "value_as_string": "2026-03-01T00:00:00Z"},
                                "last_seen": {"value": 1712188800000, "value_as_string": "2026-04-04T00:00:00Z"},
                            },
                        ]
                    }
                },
            },
            # Hostname resolution query
            {
                "aggregations": {
                    "by_answer_ip": {
                        "buckets": [
                            {
                                "key": "54.239.28.85",
                                "domain": {"buckets": [{"key": "ring.com", "doc_count": 50}]},
                            }
                        ]
                    }
                },
            },
        ]

        result = iot.get_communication_map(
            "AA:BB:CC:DD:EE:FF", "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        assert len(result["destinations"]) == 1
        dest = result["destinations"][0]
        assert dest["ip"] == "54.239.28.85"
        assert dest["hostname"] == "ring.com"
        assert dest["country"] == "US"
        assert 443 in dest["ports"]
        assert dest["bytes_sent"] == 12500
        assert dest["bytes_received"] == 45000
        assert dest["connection_count"] == 234
        assert "in_baseline" in dest

    def test_opensearch_error(self, iot, mock_client):
        mock_client.search.side_effect = Exception("timeout")
        result = iot.get_communication_map(
            "AA:BB:CC:DD:EE:FF", "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        assert result["destinations"] == []


# ---------------------------------------------------------------------------
# Activity Timeline
# ---------------------------------------------------------------------------


class TestActivityTimeline:
    def test_empty_result(self, iot, mock_client):
        mock_client.search.return_value = {
            "aggregations": {"hourly": {"buckets": []}},
        }

        result = iot.get_activity_timeline(
            "AA:BB:CC:DD:EE:FF", "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        assert result["interval"] == "1h"
        assert result["buckets"] == []
        assert result["baseline_hours"] == []

    def test_returns_hourly_buckets(self, iot, mock_client):
        mock_client.search.return_value = {
            "aggregations": {
                "hourly": {
                    "buckets": [
                        {
                            "key_as_string": "2026-04-04T00:00:00Z",
                            "key": 1712188800000,
                            "doc_count": 12,
                            "bytes": {"value": 45000},
                            "destinations": {"value": 3},
                        },
                        {
                            "key_as_string": "2026-04-04T01:00:00Z",
                            "key": 1712192400000,
                            "doc_count": 8,
                            "bytes": {"value": 30000},
                            "destinations": {"value": 2},
                        },
                    ]
                }
            },
        }

        result = iot.get_activity_timeline(
            "AA:BB:CC:DD:EE:FF", "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert len(result["buckets"]) == 2
        assert result["buckets"][0]["connections"] == 12
        assert result["buckets"][0]["bytes"] == 45000
        assert result["buckets"][0]["destinations"] == 3

    def test_includes_baseline_overlay(self, iot, mock_client):
        iot._baselines["AA:BB:CC:DD:EE:FF"] = {
            "active_hours": [8, 9, 10, 11, 12],
            "daily_avg_bytes": 48000,
        }
        mock_client.search.return_value = {
            "aggregations": {"hourly": {"buckets": []}},
        }

        result = iot.get_activity_timeline(
            "AA:BB:CC:DD:EE:FF", "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert result["baseline_hours"] == [8, 9, 10, 11, 12]
        assert result["baseline_avg_hourly_bytes"] == 2000  # 48000 / 24

    def test_opensearch_error(self, iot, mock_client):
        mock_client.search.side_effect = Exception("timeout")
        result = iot.get_activity_timeline(
            "AA:BB:CC:DD:EE:FF", "2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"
        )
        assert result["mac"] == "AA:BB:CC:DD:EE:FF"
        assert result["buckets"] == []


# ---------------------------------------------------------------------------
# Protocol Audit
# ---------------------------------------------------------------------------


class TestProtocolAudit:
    def _setup_devices(self, iot):
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
        }

    def test_empty_devices(self, iot):
        result = iot.get_protocol_audit("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert result == {"devices": []}

    def test_detects_unexpected_port(self, iot, mock_client):
        self._setup_devices(iot)
        mock_client.search.side_effect = [
            # Conn stats batch
            {
                "aggregations": {
                    "by_mac": {
                        "buckets": [
                            {
                                "key": "AA:BB:CC:DD:EE:FF",
                                "doc_count": 100,
                                "total_bytes": {"value": 50000},
                                "dest_ports": {"buckets": [
                                    {"key": 443, "doc_count": 90},
                                    {"key": 8888, "doc_count": 10},
                                ]},
                                "encrypted": {"doc_count": 90},
                                "third_party_orgs": {"value": 1},
                            }
                        ]
                    }
                },
            },
            # Alert counts
            {"aggregations": {"by_mac": {"buckets": []}}},
            # Port detail batch
            {
                "aggregations": {
                    "by_mac": {
                        "buckets": [
                            {
                                "key": "AA:BB:CC:DD:EE:FF",
                                "ports": {
                                    "buckets": [
                                        {"key": 443, "doc_count": 90},
                                        {"key": 8888, "doc_count": 5},
                                    ]
                                },
                            }
                        ]
                    }
                },
            },
            # Hardcoded DNS batch
            {"aggregations": {"by_mac": {"buckets": []}}},
        ]

        result = iot.get_protocol_audit("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert len(result["devices"]) == 1
        dev = result["devices"][0]
        assert dev["mac"] == "AA:BB:CC:DD:EE:FF"
        assert dev["category"] == "doorbell"
        # Port 8888 is not in doorbell expected ports
        unexpected = [f for f in dev["findings"] if f["type"] == "unexpected_port"]
        assert len(unexpected) >= 1
        assert unexpected[0]["port"] == 8888
        assert dev["compliant"] is False

    def test_compliant_device(self, iot, mock_client):
        self._setup_devices(iot)
        mock_client.search.side_effect = [
            # Conn stats batch - all traffic on expected ports, all encrypted
            {
                "aggregations": {
                    "by_mac": {
                        "buckets": [
                            {
                                "key": "AA:BB:CC:DD:EE:FF",
                                "doc_count": 100,
                                "total_bytes": {"value": 50000},
                                "dest_ports": {"buckets": [{"key": 443, "doc_count": 100}]},
                                "encrypted": {"doc_count": 100},
                                "third_party_orgs": {"value": 1},
                            }
                        ]
                    }
                },
            },
            # Alert counts
            {"aggregations": {"by_mac": {"buckets": []}}},
            # Port detail batch - only port 443
            {
                "aggregations": {
                    "by_mac": {
                        "buckets": [
                            {
                                "key": "AA:BB:CC:DD:EE:FF",
                                "ports": {"buckets": [{"key": 443, "doc_count": 100}]},
                            }
                        ]
                    }
                },
            },
            # Hardcoded DNS batch
            {"aggregations": {"by_mac": {"buckets": []}}},
        ]

        result = iot.get_protocol_audit("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        dev = result["devices"][0]
        assert dev["compliant"] is True
        assert dev["violation_count"] == 0

    def test_opensearch_error(self, iot, mock_client):
        self._setup_devices(iot)
        mock_client.search.side_effect = Exception("Connection refused")

        result = iot.get_protocol_audit("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert "devices" in result
        assert len(result["devices"]) == 1


# ---------------------------------------------------------------------------
# Network Isolation
# ---------------------------------------------------------------------------


class TestNetworkIsolation:
    def _setup_devices(self, iot):
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "smart-camera",
                "classified_at": "2026-04-04T00:00:00Z",
            },
        }

    def test_empty_devices(self, iot):
        result = iot.get_network_isolation("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert result["segmentation_score"] == 100
        assert result["segmentation_grade"] == "A"
        assert result["pairs"] == []

    def test_detects_iot_to_internal_pairs(self, iot, mock_client):
        self._setup_devices(iot)
        mock_client.search.return_value = {
            "aggregations": {
                "by_source_mac": {
                    "buckets": [
                        {
                            "key": "AA:BB:CC:DD:EE:FF",
                            "by_dest_ip": {
                                "buckets": [
                                    {
                                        "key": "192.168.1.10",
                                        "doc_count": 45,
                                        "ports": {"buckets": [
                                            {"key": 445, "doc_count": 30},
                                            {"key": 139, "doc_count": 15},
                                        ]},
                                        "source_ip": {"buckets": [{"key": "192.168.1.50", "doc_count": 45}]},
                                    }
                                ]
                            },
                        }
                    ]
                }
            },
        }

        result = iot.get_network_isolation("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert result["segmentation_score"] < 100
        assert len(result["pairs"]) == 1
        pair = result["pairs"][0]
        assert pair["iot_device"]["mac"] == "AA:BB:CC:DD:EE:FF"
        assert pair["internal_target"]["ip"] == "192.168.1.10"
        assert pair["risk"] == "critical"  # ports 445, 139
        assert 445 in pair["ports"]
        assert "recommendation" in result

    def test_perfect_segmentation(self, iot, mock_client):
        self._setup_devices(iot)
        mock_client.search.return_value = {
            "aggregations": {"by_source_mac": {"buckets": []}},
        }

        result = iot.get_network_isolation("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert result["segmentation_score"] == 100
        assert result["segmentation_grade"] == "A"
        assert result["pairs"] == []

    def test_opensearch_error(self, iot, mock_client):
        self._setup_devices(iot)
        mock_client.search.side_effect = Exception("Connection refused")

        result = iot.get_network_isolation("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert result["segmentation_score"] == 100
        assert result["pairs"] == []


# ---------------------------------------------------------------------------
# Manufacturer Profiles
# ---------------------------------------------------------------------------


class TestManufacturerProfiles:
    def _setup_devices(self, iot):
        iot._iot_devices = {
            "AA:BB:CC:DD:EE:FF": {
                "mac": "AA:BB:CC:DD:EE:FF",
                "manufacturer": "Ring",
                "ip": "192.168.1.50",
                "hostname": "ring-doorbell",
                "classified_at": "2026-04-04T00:00:00Z",
            },
            "11:22:33:44:55:66": {
                "mac": "11:22:33:44:55:66",
                "manufacturer": "Roku",
                "ip": "192.168.1.51",
                "hostname": "roku-tv",
                "classified_at": "2026-04-04T01:00:00Z",
            },
        }

    def test_empty_devices(self, iot):
        result = iot.get_manufacturer_profiles("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert result == {"manufacturers": []}

    def test_groups_by_manufacturer(self, iot, mock_client):
        self._setup_devices(iot)
        # Return empty aggregations for all queries
        mock_client.search.return_value = {
            "aggregations": {"by_mac": {"buckets": []}},
        }

        result = iot.get_manufacturer_profiles("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert "manufacturers" in result
        assert len(result["manufacturers"]) == 2

        names = [m["name"] for m in result["manufacturers"]]
        assert "Ring" in names
        assert "Roku" in names

        for m in result["manufacturers"]:
            assert "device_count" in m
            assert "avg_trust_score" in m
            assert "avg_trust_grade" in m
            assert "avg_privacy_grade" in m
            assert "encryption_pct" in m
            assert "total_tracker_domains" in m
            assert "total_violations" in m
            assert m["device_count"] == 1

    def test_opensearch_error(self, iot, mock_client):
        self._setup_devices(iot)
        mock_client.search.side_effect = Exception("Connection refused")

        result = iot.get_manufacturer_profiles("2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z")
        assert "manufacturers" in result
        assert len(result["manufacturers"]) == 2


# ---------------------------------------------------------------------------
# Category classification helper
# ---------------------------------------------------------------------------


class TestCategorizeDevice:
    def test_ring_is_doorbell(self, iot):
        assert iot._categorize_device({"manufacturer": "Ring", "hostname": ""}) == "doorbell"

    def test_roku_is_smart_tv(self, iot):
        assert iot._categorize_device({"manufacturer": "Roku", "hostname": ""}) == "smart_tv"

    def test_ecobee_is_thermostat(self, iot):
        assert iot._categorize_device({"manufacturer": "Ecobee", "hostname": ""}) == "thermostat"

    def test_echo_is_smart_speaker(self, iot):
        assert iot._categorize_device({"manufacturer": "Echo", "hostname": ""}) == "smart_speaker"

    def test_hue_is_light(self, iot):
        assert iot._categorize_device({"manufacturer": "Philips Hue", "hostname": ""}) == "light"

    def test_unknown_is_default(self, iot):
        assert iot._categorize_device({"manufacturer": "Unknown", "hostname": "generic"}) == "default"

    def test_hostname_matching(self, iot):
        assert iot._categorize_device({"manufacturer": "", "hostname": "kasa-plug"}) == "smart_plug"
