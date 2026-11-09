"""NET-226 / NET-237 B-h (DEV-9, DEV-10, DEV-11): IoT guesses and grades never claim what wasn't seen.

- Vendor keywords match whole words: "ring" is not in "Murata Manufacturing".
- An input never observed is None (not measured), never 0 or 1.0: trackers need DNS lookups
  from the device, third-party organisations need ASN-enriched connections.
- Isolation with no IoT devices is not measured, and "no pairs" says what NetTap can see.
"""

from unittest.mock import MagicMock

import pytest

from services.iot_monitor import IoTMonitor

FROM_TS = "2026-11-05T00:00:00Z"
TO_TS = "2026-11-06T00:00:00Z"
SEEN = "AA:AA:AA:AA:AA:01"  # DNS, ASN-enriched traffic to the internet
UNSEEN = "AA:AA:AA:AA:AA:02"  # nothing but an alert count of 0
DEVICES = {
    SEEN: {"mac": SEEN, "manufacturer": "Wyze Labs", "ip": "192.168.1.20"},
    UNSEEN: {"mac": UNSEEN, "manufacturer": "Wyze Labs", "ip": "192.168.1.21"},
}
CONN = {
    SEEN: {
        "total_connections": 10,
        "encrypted_connections": 10,
        "total_bytes": 5000,
        "dest_ports": {443},
        "third_party_orgs": 1,
        "alert_count": 0,
    },
    UNSEEN: {"alert_count": 0},
}


@pytest.fixture
def iot(monkeypatch) -> IoTMonitor:
    monitor = IoTMonitor(client=MagicMock())
    monitor._iot_devices = dict(DEVICES)
    monkeypatch.setattr(monitor, "_discover_iot_devices_from_arkime", lambda *a: None)
    monkeypatch.setattr(monitor, "_query_conn_stats_batch", lambda *a: CONN)
    monkeypatch.setattr(
        monitor,
        "_query_dns_tracker_batch",
        lambda *a: {SEEN: {"tracker_domain_count": 0, "total_dns_queries": 8}},
    )
    monkeypatch.setattr(
        monitor,
        "_query_dns_tracker_detail_batch",
        lambda *a: {SEEN: {"tracker_domains": [], "total_dns_queries": 8}},
    )
    return monitor


class TestWholeWordVendors:
    def test_ring_is_not_found_inside_manufacturing(self):
        assert IoTMonitor._is_iot_oui("Murata Manufacturing Co., Ltd.") is False
        assert IoTMonitor._is_iot_oui("Shenzhen Engineering Co.") is False
        assert IoTMonitor._is_iot_oui("Ring LLC") is True
        assert IoTMonitor._is_iot_oui("TP-Link Technologies Co., Ltd.") is True

    def test_a_murata_phone_is_neither_iot_nor_a_doorbell(self):
        iot = IoTMonitor(client=MagicMock())
        murata = {"manufacturer": "Murata Manufacturing Co., Ltd.", "hostname": ""}
        assert iot.classify_as_iot("AA:BB:CC:00:00:01", murata) is False
        assert iot._categorize_device(murata) == "default"
        assert (
            iot._categorize_device({"manufacturer": "", "hostname": "ring-doorbell"})
            == "doorbell"
        )


class TestEachInputHasItsOwnAvailability:
    def test_dns_absent_asn_present(self, iot):
        stats = iot._build_device_stats(UNSEEN, {**CONN[SEEN]}, {}, None, {443})
        assert (
            stats["tracker_domain_count"] is None
        )  # no DNS lookup seen: not 0 trackers
        assert stats["third_party_orgs"] == 1

    def test_dns_present_asn_absent(self, iot):
        conn = {**CONN[SEEN], "third_party_orgs": None}
        dns = {"tracker_domain_count": 0, "total_dns_queries": 12}
        stats = iot._build_device_stats(SEEN, conn, dns, None, {443})
        assert stats["tracker_domain_count"] == 0  # looked up names, none a tracker
        assert stats["third_party_orgs"] is None

    def test_no_destination_port_is_not_zero_violations(self, iot):
        stats = iot._build_device_stats(UNSEEN, CONN[UNSEEN], {}, None, {443})
        assert stats["protocol_violations"] is None

    def test_organisations_are_measured_only_with_asn_enriched_connections(self):
        client = MagicMock()
        bucket = {
            "doc_count": 5,
            "no_payload": {"doc_count": 0},
            "encrypted": {"doc_count": 5},
            "total_bytes": {"value": 100},
            "third_party_orgs": {"value": 0},
        }
        reply = {
            "aggregations": {
                "by_mac": {
                    "buckets": [
                        {**bucket, "key": SEEN, "with_asn": {"doc_count": 5}},
                        {**bucket, "key": UNSEEN, "with_asn": {"doc_count": 0}},
                    ]
                }
            }
        }

        def search(index=None, body=None, **_):
            aggs = body["aggs"]
            if "all" in aggs:  # every destination port per device, one page
                return {"aggregations": {"all": {"buckets": []}}}
            if "third_party_orgs" in aggs["by_mac"].get("aggs", {}):  # the conn stats
                return reply
            return {"aggregations": {"by_mac": {"buckets": []}}}  # alert counts

        client.search.side_effect = search
        stats = IoTMonitor(client=client)._query_conn_stats_batch(
            [SEEN, UNSEEN], FROM_TS, TO_TS, []
        )
        assert stats[SEEN]["third_party_orgs"] == 0
        assert stats[UNSEEN]["third_party_orgs"] is None


class TestPrivacyReportWithUnmeasuredDevices:
    def test_sorts_without_error_and_lists_unmeasured_last(self, iot):
        devices = iot.get_privacy_report(FROM_TS, TO_TS)["devices"]
        assert [d["mac"] for d in devices] == [SEEN, UNSEEN]
        unseen = devices[1]
        assert unseen["privacy_score"] is None and unseen["privacy_grade"] is None
        assert unseen["tracker_count"] is None
        assert unseen["third_party_orgs"] is None
        assert unseen["encryption_ratio"] is None

    def test_fleet_and_report_agree_on_the_unmeasured_tracker_count(self, iot):
        fleet = {d["mac"]: d for d in iot.get_fleet_summary(FROM_TS, TO_TS)["devices"]}
        assert fleet[UNSEEN]["tracker_count"] is None
        assert fleet[SEEN]["tracker_count"] == 0


class TestNoHealthVerdict:
    def test_a_high_score_describes_the_checks_not_health(self):
        subtitle = IoTMonitor._build_subtitle(95, 3, 0, 0)
        assert "healthy" not in subtitle.lower()
        assert "checks NetTap could measure" in subtitle


class TestIsolation:
    def test_no_iot_devices_is_not_measured(self, monkeypatch):
        iot = IoTMonitor(client=MagicMock())
        monkeypatch.setattr(iot, "_discover_iot_devices_from_arkime", lambda *a: None)
        result = iot.get_network_isolation(FROM_TS, TO_TS)
        assert result["segmentation_score"] is None
        assert result["segmentation_grade"] is None

    def test_no_pairs_says_what_netTap_can_see(self, monkeypatch):
        client = MagicMock()
        client.search.return_value = {"aggregations": {"all": {"buckets": []}}}
        iot = IoTMonitor(client=client)
        iot._iot_devices = dict(DEVICES)
        monkeypatch.setattr(iot, "_discover_iot_devices_from_arkime", lambda *a: None)
        result = iot.get_network_isolation(FROM_TS, TO_TS)
        assert result["recommendation"] == (
            "No IoT-to-LAN traffic seen in the traffic NetTap can see."
        )
