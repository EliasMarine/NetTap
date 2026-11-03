"""Read-only: recompute every device's Device detail and device-by-MAC figures from OpenSearch.

Runs inside nettap-storage-daemon (verify-device-figures.sh passes it with `python3 -c`), for a
fixed past day. Each figure the daemon API returns (what the page shows) is read between two raw
OpenSearch reads with the endpoint's own filters: raw before <= API <= raw after (Zeek logs a
connection when it ends, stamped with its start, so a past window still grows).
Nothing is written. Exit 0 when every figure matches.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

INDEX = "arkime_sessions3-*"
TOP_N_SIZE = 10_000  # raw per-device term lists are complete, not a top-N
BYTES = {
    "script": {
        "source": "(doc['source.bytes'].size() > 0 ? doc['source.bytes'].value : 0)"
        " + (doc['destination.bytes'].size() > 0 ? doc['destination.bytes'].value : 0)",
        "lang": "painless",
    }
}


# --- Pure comparisons (tested in daemon/tests/test_verify_device_figures.py) ---


def bracket(label: str, before: float, value: float, after: float, problems: list) -> None:
    """raw before <= API <= raw after, else a problem line."""
    if not (round(before) <= round(value) <= round(after)):
        problems.append(f"{label}: page {value:,.0f}, OpenSearch {before:,.0f} / {after:,.0f}")


def check_top(label: str, listed: list, key: str, count: str, before: dict, after: dict, problems: list) -> None:
    """A top-N list: each entry's count is bracketed, it is sorted, and nothing left out had more."""
    counts = [e[count] for e in listed]
    if counts != sorted(counts, reverse=True):
        problems.append(f"{label}: not sorted by {count}")
    for e in listed:
        bracket(f"{label} {e[key]}", before.get(e[key], 0), e[count], after.get(e[key], 0), problems)
    if listed:
        shown = {e[key] for e in listed}
        floor = min(counts)
        missed = [k for k, n in before.items() if k not in shown and n > floor]
        if missed:
            problems.append(f"{label}: {len(missed)} left out with more than {floor} (e.g. {missed[0]})")


def same_reply_sum(label: str, parts: float, whole: float, problems: list) -> None:
    """Two figures from one reply that must agree (float sums, so within 1)."""
    if abs(parts - whole) > 1:
        problems.append(f"{label}: {parts:,.0f} vs {whole:,.0f}")


# --- I/O on the box ---


def api(path: str) -> dict:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request("http://localhost:8880" + path, headers={"X-NetTap-Daemon-Token": token})
    return json.load(urllib.request.urlopen(req, timeout=300))


def counts(buckets: list) -> dict:
    return {b["key"]: b["doc_count"] for b in buckets}


def raw_device(os_client, ip: str, t: dict, conn: list, noise: list, dns_excl: list) -> dict:
    """Everything Device detail shows for one IP, computed without the daemon."""
    r = os_client.search(index=INDEX, body={
        "size": 0, "track_total_hits": True,
        "query": {"bool": {"filter": [t, {"term": {"source.ip": ip}}, *conn]}},
        "aggs": {
            "total": {"sum": BYTES},
            "orig": {"sum": {"field": "source.bytes"}},
            "resp": {"sum": {"field": "destination.bytes"}},
            "dests": {"terms": {"field": "destination.ip", "size": TOP_N_SIZE}},
            "ports": {"terms": {"field": "destination.port", "size": TOP_N_SIZE}},
            "asn": {"filter": {"exists": {"field": "destination.as.full"}}},
        },
    })
    a = r["aggregations"]
    alerts = os_client.count(index=INDEX, body={"query": {"bool": {
        "filter": [t, {"term": {"source.ip": ip}}, {"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}],
        "must_not": noise}}})["count"]
    dns = os_client.search(index=INDEX, body={"size": 0, "query": {"bool": {
        "filter": [t, {"term": {"source.ip": ip}}, {"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "dns"}}],
        "must_not": dns_excl}},
        "aggs": {"q": {"terms": {"field": "zeek.dns.query", "size": TOP_N_SIZE}}}})
    return {
        "conns": r["hits"]["total"]["value"], "total": a["total"]["value"], "orig": a["orig"]["value"],
        "resp": a["resp"]["value"], "dests": counts(a["dests"]["buckets"]), "ports": counts(a["ports"]["buckets"]),
        "asn_conns": a["asn"]["doc_count"], "alerts": alerts, "dns": counts(dns["aggregations"]["q"]["buckets"]),
    }


def raw_all(os_client, t: dict, conn: list, noise: list) -> dict:
    """Connections, bytes and alerts per source IP for the whole window (the Devices list)."""
    r = os_client.search(index=INDEX, body={"size": 0, "query": {"bool": {"filter": [t, *conn]}},
        "aggs": {"ip": {"terms": {"field": "source.ip", "size": TOP_N_SIZE}, "aggs": {"total": {"sum": BYTES}}}}})
    al = os_client.search(index=INDEX, body={"size": 0, "query": {"bool": {
        "filter": [t, {"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}], "must_not": noise}},
        "aggs": {"ip": {"terms": {"field": "source.ip", "size": TOP_N_SIZE}}}})
    alerts = counts(al["aggregations"]["ip"]["buckets"])
    return {b["key"]: {"conns": b["doc_count"], "total": b["total"]["value"], "alerts": alerts.get(b["key"], 0)}
            for b in r["aggregations"]["ip"]["buckets"]}


def raw_mac(os_client, mac: str, ips: list, t: dict, conn_records: dict) -> dict:
    """What the device-by-MAC page shows: the MAC or any of its IPs as the source."""
    should = [{"term": {"source.mac": mac}}, {"term": {"source.mac": mac.lower()}}] + [{"term": {"source.ip": i}} for i in ips]
    r = os_client.search(index=INDEX, body={
        "size": 0, "track_total_hits": True,
        "query": {"bool": {"filter": [t, conn_records], "should": should, "minimum_should_match": 1}},
        "aggs": {
            "total": {"sum": BYTES},
            "out": {"sum": {"field": "source.bytes", "missing": 0}},
            "in": {"sum": {"field": "destination.bytes", "missing": 0}},
            "dests": {"terms": {"field": "destination.ip", "size": TOP_N_SIZE}, "aggs": {"b": {"sum": BYTES}}},
        },
    })
    a = r["aggregations"]
    return {"conns": r["hits"]["total"]["value"], "total": a["total"]["value"], "out": a["out"]["value"],
            "in": a["in"]["value"], "dest_bytes": {b["key"]: b["b"]["value"] for b in a["dests"]["buckets"]}}


def check_ip(os_client, listed: dict, before_list: dict, q: str, f: dict, problems: list) -> None:
    ip = listed["ip"]
    b = raw_device(os_client, ip, *f["device_args"])
    d = api(f"/api/devices/{ip}?{q}")["device"]
    ports = api(f"/api/devices/{ip}/ports?{q}")["ports"]
    cats = api(f"/api/devices/{ip}/categories?{q}")["categories"]
    risk = api(f"/api/risk/scores/{ip}?{q}")
    a = raw_device(os_client, ip, *f["device_args"])
    p = f"{ip}"
    for field, raw_key in (("connection_count", "conns"), ("total_bytes", "total"), ("orig_bytes", "orig"),
                           ("resp_bytes", "resp"), ("alert_count", "alerts")):
        bracket(f"{p} {field}", b[raw_key], d[field], a[raw_key], problems)
    same_reply_sum(f"{p} sent + received = total", d["orig_bytes"] + d["resp_bytes"], d["total_bytes"], problems)
    series = d.get("bandwidth_series") or []
    same_reply_sum(f"{p} chart sum = total", sum(s["bytes"] for s in series), d["total_bytes"], problems)
    same_reply_sum(f"{p} chart upload = sent", sum(s["upload_bytes"] for s in series), d["orig_bytes"], problems)
    bracket(f"{p} unique destinations", len(b["dests"]), d["unique_destinations"], len(a["dests"]), problems)
    check_top(f"{p} top destinations", d["top_destinations"], "ip", "connections", b["dests"], a["dests"], problems)
    check_top(f"{p} ports", ports, "port", "connections", b["ports"], a["ports"], problems)
    dns = [{"domain": x["domain"], "count": x["count"]} for x in d.get("dns_queries") or []]
    check_top(f"{p} DNS lookups", dns, "domain", "count", b["dns"], a["dns"], problems)
    bracket(f"{p} categories connections", b["asn_conns"], sum(c["connection_count"] for c in cats), a["asn_conns"], problems)
    bracket(f"{p} risk connections", b["conns"], risk["connection_count"], a["conns"], problems)
    bracket(f"{p} risk alerts", b["alerts"], risk["alert_count"], a["alerts"], problems)
    # the Devices list row was read before this device's raw reads, so its lower bound is the whole-window read
    for field, raw_key in (("connection_count", "conns"), ("total_bytes", "total"), ("alert_count", "alerts")):
        bracket(f"{p} Devices list {field}", before_list.get(ip, {}).get(raw_key, 0), listed[field], a[raw_key], problems)


def check_mac(os_client, mac: str, ips: list, q: str, f: dict, problems: list) -> None:
    b = raw_mac(os_client, mac, ips, f["t"], f["conn_records"])
    tr = api(f"/api/devices/registry/{urllib.parse.quote(mac)}/traffic?{q}")["traffic"]
    a = raw_mac(os_client, mac, ips, f["t"], f["conn_records"])
    p = f"MAC {mac}"
    for field, raw_key in (("connection_count", "conns"), ("total_bytes", "total"),
                           ("outbound_bytes", "out"), ("inbound_bytes", "in")):
        bracket(f"{p} {field}", b[raw_key], tr[field], a[raw_key], problems)
    same_reply_sum(f"{p} in + out = total", tr["inbound_bytes"] + tr["outbound_bytes"], tr["total_bytes"], problems)
    check_top(f"{p} top destinations", tr["top_destinations"], "ip", "bytes", b["dest_bytes"], a["dest_bytes"], problems)


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    from api.alerts import SURICATA_NOISE_EXCLUSION
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container
    from services.device_registry import CONN_RECORDS
    from services.dns_analytics import DNS_LOOKUP_EXCLUSION

    os_client = OpenSearch(os.environ["OPENSEARCH_URL"], verify_certs=False, ssl_show_warn=False, timeout=120,
                           http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]))
    now = datetime.now(UTC)
    to_ts = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    from_ts = (now - timedelta(hours=24, minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = urllib.parse.urlencode({"from": from_ts, "to": to_ts})
    t = {"range": {"@timestamp": {"gte": from_ts, "lte": to_ts, "format": "strict_date_optional_time"}}}
    conn = [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "conn"}}]
    f = {"t": t, "conn_records": CONN_RECORDS, "device_args": (t, conn, SURICATA_NOISE_EXCLUSION, DNS_LOOKUP_EXCLUSION)}
    print(f"window {from_ts} -> {to_ts}")

    before_list = raw_all(os_client, t, conn, SURICATA_NOISE_EXCLUSION)
    devices = api(f"/api/devices?{q}&limit=500")["devices"]
    problems: list = []
    for dev in devices:
        check_ip(os_client, dev, before_list, q, f, problems)
    print(f"DEVICES {len(devices)} devices: Devices list row, Device detail, ports, categories, risk")

    registry = api("/api/devices/registry?limit=500")["devices"]
    macs = 0
    for reg in registry:
        if reg.get("mac"):
            check_mac(os_client, reg["mac"], reg.get("ips") or [], q, f, problems)
            macs += 1
    print(f"MACS {macs} registry devices: device-by-MAC page")

    for line in problems:
        print(f"PROBLEM {line}")
    print(f"RESULT {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
