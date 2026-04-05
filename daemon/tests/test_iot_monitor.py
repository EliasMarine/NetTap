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
