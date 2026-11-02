"""Batch 40 checks on real data: GeoIP version, update honesty, IP conflicts, protocol totals,
registry last-seen times, the Infrastructure page's 5-minute rates.

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch40.sh passes it with `python3 -c`).
Read-only: nothing is written, applied or rolled back.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

PROBLEMS: list[str] = []
NETTAP_APPLIES = {"nettap-daemon", "suricata-rules"}  # the only updates NetTap applies itself
GEOIP_GLOB = "/usr/share/logstash/vendor/bundle/jruby/*/gems/logstash-filter-geoip-*/vendor/GeoLite2-City.mmdb"


def call(path: str, method: str = "GET", **params) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request("http://localhost:8880" + path + query, method=method,
                                 data=b"{}" if method == "POST" else None,
                                 headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, {}


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def geoip_and_updates() -> None:
    container = os.environ.get("LOGSTASH_CONTAINER_NAME", "nettap-logstash")
    out = subprocess.run(["docker", "exec", container, "sh", "-c", f"stat -c %Y {GEOIP_GLOB} 2>/dev/null | sort -n | tail -1"],
                         capture_output=True, text=True, timeout=30, check=False).stdout.strip()
    want = datetime.fromtimestamp(int(out), tz=UTC).strftime("%Y-%m-%d") if out.isdigit() else None
    # fresh reads, not the caches from before the restart (both only re-read; nothing is applied)
    print(f"  (info) version scan HTTP {call('/api/system/versions/scan', 'POST')[0]}, "
          f"update check HTTP {call('/api/system/updates/check', 'POST')[0]}")
    _, vers = call("/api/system/versions")
    row = next((c for c in vers.get("versions", []) if c.get("name") == "geoip-db"), {})
    check("GeoIP version = the database Logstash enriches with", want is not None and row.get("current_version") == want,
          f"page {row.get('current_version')!r} ({row.get('status')}), Logstash file {want!r} {row.get('details')}")

    _, upd = call("/api/system/updates/available")
    updates = upd.get("updates", [])
    unmarked = [u["component"] for u in updates if u.get("component") not in NETTAP_APPLIES and not u.get("applies_with")]
    check("updates NetTap can't apply say how they arrive", not unmarked,
          f"{len(updates)} updates, {sum(1 for u in updates if u.get('applies_with'))} marked; unmarked {unmarked or 'none'}")
    geo = next((u for u in updates if u.get("component") == "geoip-db"), None)
    stale = want is not None and datetime.now(UTC) - datetime.fromisoformat(want).replace(tzinfo=UTC) >= timedelta(days=7)
    failed = upd.get("failed_checks") or []
    check("the GeoIP database's age is checked (listed when 7+ days old)", "geoip-db" not in failed and (geo is not None) == stale,
          f"database {want}, listed {geo is not None}, applies_with {bool(geo and geo.get('applies_with'))}; couldn't check {failed or 'none'}")


def lan_and_protocols() -> None:
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    window = {"from": iso(end - timedelta(hours=24)), "to": iso(end)}
    status, lan = call("/api/lan/anomalies", **window)
    check("LAN checks answer (IP conflicts read gratuitous ARP only)", status == 200,
          f"HTTP {status}, {len(lan.get('anomalies', []))} anomalies, arp_recorded={lan.get('arp_recorded')}")
    _, summary = call("/api/traffic/summary", **window)
    _, protocols = call("/api/traffic/protocols", **window)
    transport = sum(p["count"] for p in protocols.get("protocols", []))
    check("Home's protocol total = its connection count (both leave out excluded IPs)",
          transport == summary.get("connection_count"), f"protocols {transport:,}, connections {summary.get('connection_count'):,}")


def registry(client) -> None:
    from services.device_registry import record_time

    devices = client.search(index="nettap-devices", body={"size": 1000, "query": {"match_all": {}}})["hits"]["hits"]
    late = []
    for hit in devices:
        d = hit["_source"]
        body = {"size": 0, "query": {"bool": {"should": [{"terms": {"source.ip": d.get("ips") or []}},
                                                         {"term": {"source.mac": d["mac"].lower()}}], "minimum_should_match": 1}},
                "aggs": {"newest": {"max": {"field": "@timestamp"}}}}
        newest = record_time(client.search(index="arkime_sessions3-*", body=body)["aggregations"]["newest"].get("value"))
        if newest and datetime.fromisoformat(d["last_seen"]) > datetime.fromisoformat(newest) + timedelta(seconds=1):
            late.append(f"{d['mac']} {d['last_seen'][:19]} > {newest[:19]}")
    check("no device is 'last seen' after its newest record", not late, f"{len(devices)} devices; later than their records: {late[:3] or 'none'}")


def rates() -> None:
    now = datetime.now(UTC)
    five = {"from": iso(now - timedelta(minutes=5)), "to": iso(now)}
    s5, last5 = call("/api/traffic/summary", **five)
    _, day = call("/api/traffic/summary")
    a5, alerts5 = call("/api/alerts/count", **five)
    check("Infrastructure rates read the last 5 minutes", s5 == 200 and a5 == 200 and last5.get("from") == five["from"]
          and last5.get("connection_count", 0) < day.get("connection_count", 0),
          f"{last5.get('connection_count')} connections ({round(last5.get('connection_count', 0) / 300, 1)}/s) and "
          f"{(alerts5.get('counts') or {}).get('total')} alerts ({round((alerts5.get('counts') or {}).get('total', 0) / 300, 1)}/s) "
          f"in 5 min; the page showed {round(day.get('connection_count', 0) / 300)} evt/s (a day / 300 s)")


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container

    client = OpenSearch(os.environ["OPENSEARCH_URL"], verify_certs=False, ssl_show_warn=False, timeout=120,
                        http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]))
    for step in (geoip_and_updates, lan_and_protocols, lambda: registry(client), rates):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - report and go on: one failed check must not hide the others
            check("check ran", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
