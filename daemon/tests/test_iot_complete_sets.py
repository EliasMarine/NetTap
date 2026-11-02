"""#96: IoT figures that need every value of a grouping, not the top N of a terms aggregation.

The fakes answer a terms aggregation the way OpenSearch does (top `size` buckets only) and a
composite aggregation page by page, so each test fails on the capped query and passes on the
paged one.
"""

import os
import sys
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.iot_monitor import (  # noqa: E402
    ANOMALY_NEW_DESTINATION,
    ANOMALY_NEW_PORT,
    IoTMonitor,
)

MAC = "AA:BB:CC:00:00:01"


def _composite_reply(body: dict, rows: list[dict]) -> dict[str, Any]:
    """One composite page over `rows` ({"key": {field: value}, ...}), keyed by the query's source names."""
    composite = body["aggs"]["all"]["composite"]
    names = {
        spec["terms"]["field"]: name
        for source in composite["sources"]
        for name, spec in source.items()
    }
    buckets = [{**r, "key": {names[f]: v for f, v in r["key"].items()}} for r in rows]
    start = 0
    if "after" in composite:
        start = 1 + next(i for i, b in enumerate(buckets) if b["key"] == composite["after"])
    page = buckets[start : start + composite["size"]]
    after = {"after_key": page[-1]["key"]} if page else {}
    return {"aggregations": {"all": {"buckets": page, **after}}}


def _composite_field(body: dict) -> str | None:
    """The first source's field of a composite query, else None."""
    composite = body.get("aggs", {}).get("all", {}).get("composite")
    if not composite:
        return None
    return next(iter(composite["sources"][0].values()))["terms"]["field"]


def _top(values: list, size: int) -> list[dict]:
    """A terms aggregation's reply: the `size` busiest values (they arrive busiest first)."""
    return [{"key": v, "doc_count": len(values) - i} for i, v in enumerate(values)][:size]


# ---------------------------------------------------------------------------
# 1. The baseline's "known" sets hold every value of the 14 days
# ---------------------------------------------------------------------------

HISTORY = {
    "destination.ip": [f"52.0.0.{i}" for i in range(150)],
    "destination.port": [10_000 + i for i in range(60)],
    "network.protocol": ["tls"],
    "destination.geo.country_name": ["United States"],
}
TERMS_AGG_FIELDS = {
    "destinations": "destination.ip",
    "dest_ports": "destination.port",
    "protocols": "network.protocol",
    "countries": "destination.geo.country_name",
}


def _terms_reply(body: dict, values_by_field: dict[str, list]) -> dict[str, Any]:
    aggs = {
        name: {"buckets": _top(values_by_field[field], body["aggs"][name]["terms"]["size"])}
        for name, field in TERMS_AGG_FIELDS.items()
        if name in body["aggs"]
    }
    return {
        "hits": {"total": {"value": 5000}},
        "aggregations": {**aggs, "hourly_activity": {"buckets": []}, "total_bytes": {"value": 0}},
    }


def _history_search(index: str, body: dict) -> dict[str, Any]:
    field = _composite_field(body)
    if field:
        rows = [{"key": {field: v}, "doc_count": 1} for v in HISTORY[field]]
        return _composite_reply(body, rows)
    return _terms_reply(body, HISTORY)


def _this_hour(destinations: list[str], ports: list[int]):
    current = {
        "destination.ip": destinations,
        "destination.port": ports,
        "network.protocol": ["tls"],
        "destination.geo.country_name": ["United States"],
    }
    return lambda index, body: _terms_reply(body, current)


class TestBaselineKnowsEveryValue:
    def test_known_sets_hold_every_destination_and_port(self):
        client = MagicMock()
        client.search.side_effect = _history_search
        baseline = IoTMonitor(client=client).build_baseline(MAC)

        # was 100 and 50: the top of a terms aggregation
        assert len(baseline["known_destinations"]) == 150
        assert len(baseline["known_ports"]) == 60

    def test_a_quiet_but_familiar_destination_is_not_new(self):
        """An Echo reaching >100 CDN IPs over 14 days got "new destination" anomalies hourly."""
        client = MagicMock()
        client.search.side_effect = _history_search
        iot = IoTMonitor(client=client)
        iot.build_baseline(MAC)

        # 52.0.0.120 and port 10055 were used in the 14 days, outside the old top 100 / 50
        client.search.side_effect = _this_hour(["52.0.0.120", "203.0.113.9"], [10_055])
        anomalies = iot.check_anomalies(MAC)

        new = {(a["type"], a["detail"]) for a in anomalies}
        assert (ANOMALY_NEW_DESTINATION, "52.0.0.120") not in new
        assert (ANOMALY_NEW_PORT, "10055") not in new
        # a destination truly absent from the 14 days is still flagged
        assert (ANOMALY_NEW_DESTINATION, "203.0.113.9") in new

    def test_known_sets_cover_only_this_device_and_window(self):
        client = MagicMock()
        client.search.side_effect = _history_search
        IoTMonitor(client=client).build_baseline(MAC)

        bodies = [c.kwargs["body"] for c in client.search.call_args_list]
        [main] = [b for b in bodies if "hourly_activity" in b["aggs"]]
        paged = [b for b in bodies if _composite_field(b)]
        assert {_composite_field(b) for b in paged} == set(HISTORY)
        assert all(b["query"] == main["query"] for b in paged)


# ---------------------------------------------------------------------------
# 2. Every destination port a device used, for the trust score and the protocol audit
# ---------------------------------------------------------------------------

FROM_TS = "2026-11-01T00:00:00Z"
TO_TS = "2026-11-02T00:00:00Z"


def _composite_fields(body: dict) -> list[str]:
    composite = body.get("aggs", {}).get("all", {}).get("composite", {})
    return [next(iter(s.values()))["terms"]["field"] for s in composite.get("sources", [])]


def _by_mac(buckets: list[dict]) -> dict[str, Any]:
    return {"aggregations": {"by_mac": {"buckets": buckets}}}


def _ports_search(ports: list[int]):
    """A device that used `ports`, busiest first; every other query finds nothing."""

    def search(index: str, body: dict) -> dict[str, Any]:
        if _composite_fields(body) == ["source.mac", "destination.port"]:
            rows = [
                {"key": {"source.mac": MAC.lower(), "destination.port": p}, "doc_count": 1}
                for p in ports
            ]
            return _composite_reply(body, rows)
        if _composite_fields(body):
            return _composite_reply(body, [])
        sub = body.get("aggs", {}).get("by_mac", {}).get("aggs", {})
        if "encrypted" in sub:
            bucket = {"key": MAC.lower(), "doc_count": 1000, "encrypted": {"doc_count": 1000}}
            if "dest_ports" in sub:
                size = sub["dest_ports"]["terms"]["size"]
                bucket = {**bucket, "dest_ports": {"buckets": _top(ports, size)}}
            return _by_mac([bucket])
        if "ports" in sub:
            top = _top(ports, sub["ports"]["terms"]["size"])
            return _by_mac([{"key": MAC.lower(), "ports": {"buckets": top}}])
        return _by_mac([])

    return search


def _monitor_with_device(client: MagicMock) -> IoTMonitor:
    iot = IoTMonitor(client=client)
    iot._iot_devices = {
        MAC: {"mac": MAC, "manufacturer": "Tuya Smart Inc.", "hostname": None, "ip": "192.168.1.40"}
    }
    return iot


class TestEveryPortCounts:
    def test_protocol_audit_flags_a_quiet_telnet_port(self):
        """250 ports, telnet the quietest: the old top 200 dropped the one high-severity finding."""
        client = MagicMock()
        client.search.side_effect = _ports_search([*range(20_000, 20_249), 23])
        [device] = _monitor_with_device(client).get_protocol_audit(FROM_TS, TO_TS)["devices"]

        telnet = [f for f in device["findings"] if f["port"] == 23]
        assert [f["severity"] for f in telnet] == ["high"]
        assert device["violation_count"] == 250  # was 200

    def test_trust_score_sees_ports_beyond_the_busiest_100(self):
        """150 ports, the 50 quietest new since the baseline: the old top 100 saw none of them."""
        ports = list(range(30_000, 30_150))
        client = MagicMock()
        client.search.side_effect = _ports_search(ports)
        iot = _monitor_with_device(client)
        baseline = {"known_ports": ports[:100], "known_destinations": [], "active_hours": []}

        conn = iot._query_conn_stats_batch([MAC], FROM_TS, TO_TS, [])[MAC]
        stats = iot._build_device_stats(MAC, conn, {}, baseline, set())

        assert len(conn["dest_ports"]) == 150  # was 100
        assert stats["new_destinations"] == 50  # was 0
        assert stats["baseline_adherence"] == 100 / 150  # was 1.0

    def test_port_counts_keep_the_device_filter(self):
        client = MagicMock()
        client.search.side_effect = _ports_search([443])
        _monitor_with_device(client).get_protocol_audit(
            FROM_TS, TO_TS, excluded_ips=["10.0.0.9"]
        )

        bodies = [c.kwargs["body"] for c in client.search.call_args_list]
        paged = next(b for b in bodies if _composite_fields(b) == ["source.mac", "destination.port"])
        assert {"terms": {"source.mac": [MAC, MAC.lower()]}} in paged["query"]["bool"]["filter"]
        assert {"terms": {"source.ip": ["10.0.0.9"]}} in paged["query"]["bool"]["must_not"]


# ---------------------------------------------------------------------------
# 3. Discovery sees every MAC, so device_count counts every IoT device
# ---------------------------------------------------------------------------


def _mac_bucket(mac: str, oui: str, conns: int) -> dict:
    return {
        "key": {"source.mac": mac},
        "doc_count": conns,
        "oui": {"buckets": [{"key": oui, "doc_count": conns}]},
        "latest_ip": {"buckets": [{"key": "192.168.1.9", "doc_count": conns}]},
        "last_seen": {"value": 0},
    }


def _network_search(macs: list[dict]):
    """A network whose MACs are `macs` (busiest first); IoT detail queries find nothing."""

    def search(index: str, body: dict) -> dict[str, Any]:
        if _composite_fields(body) == ["source.mac"]:
            return _composite_reply(body, macs)
        if _composite_fields(body):
            return _composite_reply(body, [])
        by_mac = body.get("aggs", {}).get("by_mac", {})
        if "oui" in by_mac.get("aggs", {}):
            size = by_mac["terms"]["size"]
            return _by_mac([{**b, "key": b["key"]["source.mac"]} for b in macs[:size]])
        return _by_mac([])

    return search


class TestDiscoverySeesEveryMac:
    def test_a_quiet_iot_device_on_a_busy_network_is_counted(self):
        """520 busier non-IoT MACs: the old top 500 never reached the plug, so 0 devices."""
        busy = [_mac_bucket(f"00:00:00:00:{i // 256:02x}:{i % 256:02x}", "Dell Inc.", 1000 - i) for i in range(520)]
        plug = _mac_bucket("d8:1f:12:00:00:01", "Tuya Smart Inc.", 3)
        client = MagicMock()
        client.search.side_effect = _network_search([*busy, plug])

        fleet = IoTMonitor(client=client).get_fleet_summary(FROM_TS, TO_TS)

        assert fleet["device_count"] == 1  # was 0
        assert [d["mac"] for d in fleet["devices"]] == ["D8:1F:12:00:00:01"]


# ---------------------------------------------------------------------------
# 4. Tracker counts come from every domain a device looked up
# ---------------------------------------------------------------------------

TRACKERS = [
    "google-analytics.com",
    "googletagmanager.com",
    "googlesyndication.com",
    "googleadservices.com",
    "analytics.google.com",
    "tagmanager.google.com",
]
# 500 busier lookups ahead of the trackers: the old top-500 list ended before them
LOOKUPS = [*(f"cdn-{i}.example.net" for i in range(500)), *TRACKERS]


def _dns_search(index: str, body: dict) -> dict[str, Any]:
    if _composite_fields(body) == ["source.mac", "dns.host"]:
        rows = [
            {"key": {"source.mac": MAC.lower(), "dns.host": d}, "doc_count": 1}
            for d in LOOKUPS
        ]
        return _composite_reply(body, rows)
    if _composite_fields(body):
        return _composite_reply(body, [])
    if {"term": {"network.protocol": "dns"}} in body["query"]["bool"]["filter"]:
        bucket = {"key": MAC.lower(), "doc_count": 5000}
        sub = body["aggs"]["by_mac"].get("aggs", {})
        if "queried_domains" in sub:
            top = _top(LOOKUPS, sub["queried_domains"]["terms"]["size"])
            bucket = {**bucket, "queried_domains": {"buckets": top}}
        return _by_mac([bucket])
    return _by_mac([])


class TestEveryTrackerCounts:
    def test_fleet_counts_trackers_past_the_500_busiest_lookups(self):
        client = MagicMock()
        client.search.side_effect = _dns_search
        fleet = _monitor_with_device(client).get_fleet_summary(FROM_TS, TO_TS)

        assert fleet["devices"][0]["tracker_count"] == 6  # was 0
        assert fleet["privacy_concerns"] == 1  # more than 5 trackers; was 0

    def test_privacy_report_lists_every_tracker(self):
        client = MagicMock()
        client.search.side_effect = _dns_search
        [device] = _monitor_with_device(client).get_privacy_report(FROM_TS, TO_TS)["devices"]

        assert device["tracker_count"] == 6  # was 0
        assert {t["domain"] for t in device["tracker_domains"]} == set(TRACKERS)


# ---------------------------------------------------------------------------
# 5. Isolation sees every LAN host and every risky port of a pair
# ---------------------------------------------------------------------------


def _not_icmp(ports: dict[int, int], spec: dict) -> dict[str, Any]:
    """The not_icmp sub-aggregation as OpenSearch answers `spec` for a pair's ports."""
    ordered = sorted(ports.items(), key=lambda kv: (-kv[1], kv[0]))
    size = spec["aggs"]["ports"]["terms"]["size"]
    out: dict[str, Any] = {
        "doc_count": sum(ports.values()),
        "ports": {"buckets": [{"key": p, "doc_count": c} for p, c in ordered[:size]]},
    }
    if "risky" in spec["aggs"]:
        risky = spec["aggs"]["risky"]["filter"]["terms"]["destination.port"]
        hits = [{"key": p, "doc_count": c} for p, c in ordered if p in risky]
        out = {**out, "risky": {"ports": {"buckets": hits}}}
    if "port_count" in spec["aggs"]:
        out = {**out, "port_count": {"value": len(ports)}}
    return out


def _isolation_search(pairs: list[tuple[str, dict[int, int], int]]):
    """MAC reached each (LAN host, {port: connections}, pings); busiest pair first."""
    ordered = sorted(pairs, key=lambda p: -(sum(p[1].values()) + p[2]))

    def pair_bucket(key: Any, dest: str, ports: dict[int, int], pings: int, spec: dict) -> dict:
        return {
            "key": key,
            "doc_count": sum(ports.values()) + pings,
            "not_icmp": _not_icmp(ports, spec),
            "source_ip": {"buckets": [{"key": "192.168.1.40", "doc_count": 1}]},
        }

    def search(index: str, body: dict) -> dict[str, Any]:
        if _composite_fields(body) == ["source.mac", "destination.ip"]:
            spec = body["aggs"]["all"]["aggs"]["not_icmp"]
            rows = [
                pair_bucket({"source.mac": MAC.lower(), "destination.ip": d}, d, ports, pings, spec)
                for d, ports, pings in ordered
            ]
            return _composite_reply(body, rows)
        if _composite_fields(body):
            return _composite_reply(body, [])
        by_dest = body.get("aggs", {}).get("by_source_mac", {}).get("aggs", {}).get("by_dest_ip")
        if by_dest:
            spec = by_dest["aggs"]["not_icmp"]
            dests = [pair_bucket(d, d, ports, pings, spec) for d, ports, pings in ordered]
            mac = {"key": MAC.lower(), "by_dest_ip": {"buckets": dests[: by_dest["terms"]["size"]]}}
            return {"aggregations": {"by_source_mac": {"buckets": [mac]}}}
        return _by_mac([])

    return search


class TestIsolationSeesEveryPair:
    def test_a_port_sweep_is_critical(self):
        """1,000 ports once each: the old top 20 were ports 1-20, so no SSH/SMB and "medium"."""
        sweep = {port: 1 for port in range(1, 1001)}
        client = MagicMock()
        client.search.side_effect = _isolation_search([("192.168.1.20", sweep, 0)])
        result = _monitor_with_device(client).get_network_isolation(FROM_TS, TO_TS)

        [pair] = result["pairs"]
        assert pair["risk"] == "critical"  # was medium
        assert {22, 23, 139, 445} <= set(pair["ports"])
        assert result["segmentation_score"] == 75  # was 95
        assert pair["description"].endswith("+995 more")  # was +15 more

    def test_a_pair_past_the_50th_lan_host_counts(self):
        """60 hosts pinged often and one quiet SMB connection: the old top 50 dropped the SMB."""
        pings = [(f"192.168.2.{i}", {}, 100) for i in range(60)]
        smb = ("192.168.3.5", {445: 2}, 0)
        client = MagicMock()
        client.search.side_effect = _isolation_search([*pings, smb])
        result = _monitor_with_device(client).get_network_isolation(FROM_TS, TO_TS)

        assert len(result["pairs"]) == 61  # was 50
        assert result["pairs"][0]["internal_target"]["ip"] == "192.168.3.5"
        assert result["pairs"][0]["risk"] == "critical"
        assert result["segmentation_score"] == 75  # was 100
