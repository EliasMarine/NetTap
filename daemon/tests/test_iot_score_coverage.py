"""NET-158: the IoT trust score counts only what was measured, and every view agrees.

Fleet summary, privacy report and manufacturer profiles read one contract from
IoTTrustScorer; the inputs are marked measured or unavailable in IoTMonitor.
"""

from unittest.mock import MagicMock

import pytest

from services.iot_monitor import IoTMonitor

FROM_TS = "2026-11-05T00:00:00Z"
TO_TS = "2026-11-06T00:00:00Z"
CAMERA = "AA:AA:AA:AA:AA:01"  # traffic to the internet: scored
PLUG = "AA:AA:AA:AA:AA:02"  # local chatter only: not enough measured

DEVICES = {
    CAMERA: {"mac": CAMERA, "manufacturer": "Wyze Labs", "ip": "192.168.1.20"},
    PLUG: {"mac": PLUG, "manufacturer": "Wyze Labs", "ip": "192.168.1.21"},
}
CONN = {
    CAMERA: {
        "total_connections": 10,
        "encrypted_connections": 10,
        "total_bytes": 5000,
        "dest_ports": {443},
        "third_party_orgs": 1,
        "alert_count": 0,
    },
    PLUG: {"alert_count": 0},
}
TRACKERS = [
    {"domain": "app-measurement.com", "query_count": 3},
    {"domain": "doubleclick.net", "query_count": 1},
]


@pytest.fixture
def iot(monkeypatch) -> IoTMonitor:
    monitor = IoTMonitor(client=MagicMock())
    monitor._iot_devices = dict(DEVICES)
    monkeypatch.setattr(monitor, "_discover_iot_devices_from_arkime", lambda *a: None)
    monkeypatch.setattr(monitor, "_query_conn_stats_batch", lambda *a: CONN)
    monkeypatch.setattr(
        monitor,
        "_query_dns_tracker_batch",
        lambda *a: {CAMERA: {"tracker_domain_count": 2, "total_dns_queries": 8}},
    )
    monkeypatch.setattr(
        monitor,
        "_query_dns_tracker_detail_batch",
        lambda *a: {CAMERA: {"tracker_domains": TRACKERS, "total_dns_queries": 8}},
    )
    monkeypatch.setattr(monitor, "_query_port_detail_batch", lambda *a: {})
    return monitor


class TestMixedFleet:
    def test_only_scored_devices_make_the_fleet_score(self, iot):
        fleet = iot.get_fleet_summary(FROM_TS, TO_TS)
        camera, plug = fleet["devices"]  # scored first, unscored last

        assert camera["mac"] == CAMERA
        # trackers 9 + third parties 10 + encryption 15 + ports 10 + alerts 10, of 55
        assert (camera["score"], camera["coverage"], camera["checks_available"]) == (
            98,
            55,
            5,
        )
        assert plug["score"] is None and plug["grade"] is None
        assert plug["coverage"] == 40
        assert plug["encryption_pct"] is None

        assert fleet["health_score"] == 98  # not pulled toward the plug's old 80-odd
        assert (fleet["scored_device_count"], fleet["device_count"]) == (1, 2)
        assert fleet["behavior_score"] is None  # no behaviour check is measured

    def test_anomalies_without_a_baseline_are_not_checked(self, iot):
        fleet = iot.get_fleet_summary(FROM_TS, TO_TS)
        assert fleet["anomalies_checked"] == 0
        assert [d["anomaly_count"] for d in fleet["devices"]] == [None, None]

    def test_every_device_unscored_means_no_fleet_score(self, iot, monkeypatch):
        monkeypatch.setattr(iot, "_query_conn_stats_batch", lambda *a: {})
        fleet = iot.get_fleet_summary(FROM_TS, TO_TS)
        assert fleet["health_score"] is None
        assert fleet["health_grade"] is None
        assert fleet["subtitle"].startswith("Not enough measured")

    def test_a_new_destination_on_a_familiar_port_is_not_scored_as_familiar(
        self, iot
    ):
        """new_destinations counted new *ports*, so a new IP on 443 read as no change."""
        iot._baselines[CAMERA] = {
            "known_destinations": ["1.1.1.1"],
            "known_ports": [443],
            "active_hours": list(range(24)),
            "daily_avg_bytes": 10_000,
        }
        stats = iot._build_device_stats(CAMERA, CONN[CAMERA], {}, iot._baselines[CAMERA], {443})
        assert stats["new_destinations"] is None
        assert stats["baseline_adherence"] is None
        assert iot._scorer.score_device(stats)["behavior_score"] is None


class TestOnePrivacyResult:
    def test_privacy_tab_and_table_show_the_same_privacy_score(self, iot):
        fleet = iot.get_fleet_summary(FROM_TS, TO_TS)
        privacy = iot.get_privacy_report(FROM_TS, TO_TS)
        by_mac = {d["mac"]: d for d in privacy["devices"]}
        for device in fleet["devices"]:
            assert by_mac[device["mac"]]["privacy_score"] == device["privacy_score"]

    def test_tracker_share_is_a_share_of_lookups_not_bytes(self, iot):
        camera = next(
            d for d in iot.get_privacy_report(FROM_TS, TO_TS)["devices"] if d["mac"] == CAMERA
        )
        assert camera["tracker_lookup_share"] == 0.5  # 4 of 8 lookups
        assert "telemetry_bytes" not in camera


class TestManufacturerRule:
    def test_vendor_score_is_the_fleet_rule_over_scored_devices(self, iot):
        [wyze] = iot.get_manufacturer_profiles(FROM_TS, TO_TS)["manufacturers"]
        assert wyze["avg_trust_score"] == 98  # the plug is left out, not averaged in
        assert (wyze["scored_device_count"], wyze["device_count"]) == (1, 2)

    def test_vendor_with_no_scored_device_has_no_score(self, iot, monkeypatch):
        monkeypatch.setattr(iot, "_query_conn_stats_batch", lambda *a: {})
        [wyze] = iot.get_manufacturer_profiles(FROM_TS, TO_TS)["manufacturers"]
        assert wyze["avg_trust_score"] is None
        assert wyze["avg_trust_grade"] is None
        assert wyze["encryption_pct"] is None
