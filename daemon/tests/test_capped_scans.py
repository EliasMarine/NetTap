"""NET-237 (caps): a scan that stops at its bucket cap is an error, not a complete-looking answer.

Each test stops one scan, picked by the fields it groups on, and lets every other scan finish, so a
test fails only when its own guard is gone.
"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from services import (
    dns_analytics,
    excluded_ips,
    iot_monitor,
    lan_anomaly_detector,
    mac_correlator,
    traffic_classifier,
)
from storage.exact_terms import PartialResultsError

MAC = "00:00:5E:00:53:01"
WINDOW = ("now-1d", "now")


def _fields(sources: list[dict]) -> tuple[str, ...]:
    return tuple(next(iter(s.values()))["terms"]["field"] for s in sources)


def _stop_at_cap(monkeypatch, module, fields: tuple[str, ...], capped=()):
    """Every all_buckets scan in `module` finishes empty, except the one on `fields`, which stops."""
    seen: list[tuple[str, ...]] = []

    def fake(client, index, query, sources, *args, **kwargs):
        seen.append(_fields(sources))
        return (list(capped), False) if _fields(sources) == fields else ([], True)

    monkeypatch.setattr(module, "all_buckets", fake)
    return seen


def test_iot_discovery(monkeypatch):
    _stop_at_cap(monkeypatch, iot_monitor, ("source.mac",))
    with pytest.raises(PartialResultsError, match="IoT discovery"):
        iot_monitor.IoTMonitor(MagicMock())._discover_iot_devices_from_arkime(*WINDOW)


def test_iot_baseline_stops_on_a_later_value_list(monkeypatch):
    seen = _stop_at_cap(monkeypatch, iot_monitor, ("destination.geo.country_name",))
    with pytest.raises(PartialResultsError, match="baseline known_countries"):
        iot_monitor.IoTMonitor(MagicMock())._baseline_known_sets({"match_all": {}}, MAC)
    # the earlier lists finished before the stopped one
    assert len(seen) == len(iot_monitor.BASELINE_KNOWN_SOURCES)


def test_iot_values_per_device(monkeypatch):
    _stop_at_cap(monkeypatch, iot_monitor, ("source.mac", "destination.port"))
    with pytest.raises(PartialResultsError, match="destination.port per device"):
        iot_monitor.IoTMonitor(MagicMock())._counts_by_mac(
            {"match_all": {}}, "destination.port"
        )


def test_iot_isolation_pairs(monkeypatch):
    seen = _stop_at_cap(monkeypatch, iot_monitor, ("source.mac", "destination.ip"))
    monitor = iot_monitor.IoTMonitor(MagicMock())
    monkeypatch.setattr(monitor, "_discover_iot_devices_from_arkime", lambda *a: None)
    monitor._iot_devices = {MAC: {"mac": MAC, "ip": "192.168.1.20"}}
    with pytest.raises(PartialResultsError, match="network isolation"):
        monitor.get_network_isolation(*WINDOW)
    assert seen == [("source.mac", "destination.ip")]


def _correlator(tmp_path):
    return mac_correlator.MACCorrelator(
        MagicMock(), merge_file=str(tmp_path / "m.json")
    )


def test_randomized_macs(monkeypatch, tmp_path):
    _stop_at_cap(monkeypatch, mac_correlator, ("source.mac",))
    with pytest.raises(PartialResultsError, match="MAC scan"):
        _correlator(tmp_path).detect_randomized_macs(*WINDOW)


def test_merge_fingerprints(monkeypatch, tmp_path):
    _stop_at_cap(monkeypatch, mac_correlator, ("source.mac",))
    with pytest.raises(PartialResultsError, match="MAC fingerprints"):
        _correlator(tmp_path)._fingerprints(*WINDOW)


def test_arp_scan(monkeypatch):
    _stop_at_cap(monkeypatch, lan_anomaly_detector, ("source.ip",))
    with pytest.raises(PartialResultsError, match="ARP scan by source.ip"):
        lan_anomaly_detector._ips_with_many_macs(MagicMock(), {}, "source.ip")


@pytest.mark.parametrize("side", ["source", "destination"])
def test_rogue_dhcp_either_direction(monkeypatch, side):
    _stop_at_cap(monkeypatch, lan_anomaly_detector, (f"{side}.mac", f"{side}.ip"))
    with pytest.raises(PartialResultsError, match=f"rogue DHCP {side} scan"):
        lan_anomaly_detector.LANAnomalyDetector(MagicMock()).detect_rogue_dhcp(*WINDOW)


def test_rogue_dhcp_handler_answers_an_error(monkeypatch):
    from api.lan_security import handle_rogue_dhcp

    _stop_at_cap(monkeypatch, lan_anomaly_detector, ("source.mac", "source.ip"))
    app = web.Application()
    app["lan_anomaly_detector"] = lan_anomaly_detector.LANAnomalyDetector(MagicMock())
    req = make_mocked_request("GET", "/api/lan/rogue-dhcp", app=app)

    resp = asyncio.run(handle_rogue_dhcp(req))

    assert resp.status >= 500
    assert "alerts" not in json.loads(resp.text)


def test_traffic_category_asns(monkeypatch):
    _stop_at_cap(monkeypatch, traffic_classifier, ("destination.as.full",))
    with pytest.raises(PartialResultsError, match="traffic categories"):
        traffic_classifier._asn_buckets(MagicMock(), *WINDOW)


def test_traffic_category_devices(monkeypatch):
    seen = _stop_at_cap(monkeypatch, traffic_classifier, ("source.ip",))
    monkeypatch.setattr(
        traffic_classifier,
        "_category_asn_buckets",
        lambda *a: [{"key": {"asn": "AS64496 Example"}}],
    )
    category = next(iter(traffic_classifier.CATEGORIES))
    with pytest.raises(PartialResultsError, match="category devices"):
        traffic_classifier.get_category_devices(MagicMock(), category, *WINDOW)
    assert seen == [("source.ip",)]


def test_lan_redetection_keeps_the_current_filter(monkeypatch):
    """A capped scan used to replace the LAN filter with the subnets it happened to read."""
    monkeypatch.delenv("LAN_SUBNETS", raising=False)
    _stop_at_cap(
        monkeypatch,
        excluded_ips,
        ("source.ip",),
        capped=[{"key": {"ip": "192.168.7.20"}, "doc_count": 50}],
    )
    current = excluded_ips.build_lan_filter([(10, 0, 0)])

    assert excluded_ips.detect_lan_subnets(MagicMock()) == []
    assert excluded_ips.changed_lan_filter(MagicMock(), current) is None


def test_dns_name_scan(monkeypatch):
    _stop_at_cap(monkeypatch, dns_analytics, ("zeek.dns.query",))
    with pytest.raises(PartialResultsError, match="DNS name scan"):
        dns_analytics.DNSAnalytics(MagicMock())._all_domains(*WINDOW)


def test_dns_name_scan_checks_its_pages():
    """A page without aggregations used to read as the end of the names, so nothing was checked."""
    client = MagicMock()
    client.search.return_value = {}
    with pytest.raises(PartialResultsError, match="DNS names"):
        dns_analytics.DNSAnalytics(client)._all_domains(*WINDOW)


def test_suspicious_dns_answers_502_on_an_unreadable_page():
    from api.dns import handle_suspicious

    client = MagicMock()
    client.search.return_value = {}
    app = web.Application()
    app["dns_analytics"] = dns_analytics.DNSAnalytics(client)
    req = make_mocked_request("GET", "/api/dns/suspicious", app=app)

    resp = asyncio.run(handle_suspicious(req))

    assert resp.status == 502


# ---------------------------------------------------------------------------
# complete_terms dropped the paged scan's completeness flag (NET-237 delta)
# ---------------------------------------------------------------------------


def test_complete_terms_raises_when_its_paged_scan_hits_the_cap(monkeypatch):
    from storage import all_buckets as ab

    monkeypatch.setattr(ab, "all_buckets", lambda *a, **k: ([], False))
    with pytest.raises(PartialResultsError, match="destination.ip"):
        ab.complete_terms(
            MagicMock(),
            "arkime_sessions3-*",
            {"match_all": {}},
            {"buckets": [], "sum_other_doc_count": 5},
            {"terms": {"field": "destination.ip"}},
        )


def test_iot_anomalies_answer_incomplete_when_a_value_list_is_capped(monkeypatch):
    """A capped scan of the hour's destinations answered 200 with part of the findings."""
    from api.iot import register_iot_routes
    from storage import all_buckets as ab

    monkeypatch.setattr(ab, "all_buckets", lambda *a, **k: ([], False))
    client = MagicMock()
    client.search.return_value = {
        "aggregations": {"destinations": {"buckets": [], "sum_other_doc_count": 5}}
    }
    app = web.Application()
    register_iot_routes(app, MagicMock(_client=client))
    monitor = app["iot_monitor"]
    monitor._iot_devices = {MAC: {"mac": MAC, "ip": "192.168.1.20"}}
    monitor._baselines = {MAC: {"mac": MAC}}

    from api.iot import handle_iot_anomalies

    req = make_mocked_request("GET", "/api/iot/anomalies", app=app)
    try:
        resp = asyncio.run(handle_iot_anomalies(req))
    finally:
        app["iot_executor"].shutdown(wait=False)

    assert resp.status == 502
    assert json.loads(resp.text)["error"] == "The IoT search was incomplete"
