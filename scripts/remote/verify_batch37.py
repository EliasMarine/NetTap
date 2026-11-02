"""Batch 37 checks on real data (#97 heatmap, #98 beacons, #96 category detail, #96h failure states).

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch37.sh passes it with `python3 -c`).
Read-only: no setting or document is written.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

PERIODIC_PORTS = {53, 67, 68, 123, 137, 138, 1900, 5353, 5355}
PROBLEMS: list[str] = []


def api(path: str, **params) -> tuple[dict, float]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    query = ("&" if "?" in path else "?") + urllib.parse.urlencode(params) if params else ""
    req = urllib.request.Request("http://localhost:8880" + path + query, headers={"X-NetTap-Daemon-Token": token})
    t0 = time.time()
    body = json.load(urllib.request.urlopen(req, timeout=300))
    return body, round(time.time() - t0, 2)


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def beacons(window: dict) -> None:
    report, took = api("/api/threats/report", **window)
    check("threat report answers in under 10 s", took < 10, f"{took} s")
    found = report.get("beaconing", [])
    from services.threat_detection import _is_internal

    stray = [b for b in found if _is_internal(b["destination_ip"]) or b["destination_port"] in PERIODIC_PORTS]
    suspects = [b for b in found if b.get("pattern") != "many_hosts"]
    many = {b["source_ip"]: b.get("host_count") for b in found if b.get("pattern") == "many_hosts"}
    check("beacons are calls to internet hosts, not DNS/NTP/mDNS", not stray,
          f"{len(suspects)} suspects, many-host devices {many or 'none'}, {len(stray)} stray")
    check("threat report checks all ran", not report.get("failed_checks") and not report.get("incomplete_checks"),
          f"failed {report.get('failed_checks')} incomplete {report.get('incomplete_checks')}")


def heatmap(client, window: dict, tz: str, excluded: list[str]) -> None:
    from services.excluded_ips import build_excluded_ips_filter

    bool_clause = {"filter": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "conn"}},
                              {"range": {"@timestamp": {"gte": window["from"], "lte": window["to"]}}}]}
    if excluded:
        bool_clause["must_not"] = build_excluded_ips_filter(excluded)
    body = {"size": 0, "query": {"bool": bool_clause}, "aggs": {"h": {
        # 15 min buckets map exactly into every zone's local hours (India +5:30, Nepal +5:45)
        "date_histogram": {"field": "@timestamp", "fixed_interval": "15m"},
        "aggs": {"o": {"sum": {"field": "source.bytes", "missing": 0}}, "r": {"sum": {"field": "destination.bytes", "missing": 0}}}}}}
    zone = ZoneInfo(tz)

    def read() -> tuple[dict, list[list[int]]]:
        # both sides fresh and back to back: Zeek rewrites a long connection's record while it
        # lasts, so an hour's bytes can change between two reads (batch 37 saw 2 such records move)
        client.indices.clear_cache(index="arkime_sessions3-*", request=True)
        got = api("/api/bandwidth/heatmap", **window, tz=tz)[0]
        raw = client.search(index="arkime_sessions3-*", body=body, request_cache=False)
        want = [[0] * 24 for _ in range(7)]
        for b in raw["aggregations"]["h"]["buckets"]:
            local = datetime.fromtimestamp(b["key"] / 1000, UTC).astimezone(zone)
            want[local.weekday()][local.hour] += int(b["o"]["value"] + b["r"]["value"])
        return got, want

    for attempt in range(3):  # a difference that survives three fresh pairs of reads is real
        got, want = read()
        matrix = got.get("matrix")
        if matrix is None:
            check(f"heatmap ({tz})", False, f"no matrix in reply keys {sorted(got)}")
            return
        wrong = [(d, h, matrix[d][h], want[d][h]) for d in range(7) for h in range(24) if matrix[d][h] != want[d][h]]
        if not wrong:
            break
        print(f"  (retry) {tz}: read {attempt + 1} had {len(wrong)} cells differ {wrong[:2]}")
    filled = sum(1 for d in range(7) for h in range(24) if want[d][h])
    check(f"heatmap ({tz}) = OpenSearch hour by hour", not wrong and filled > 0,
          f"{filled} hours with traffic, total {sum(map(sum, want)):,} bytes, {len(wrong)} cells differ {wrong[:3]}; tz echoed {got.get('tz')!r}")


def categories(window: dict) -> None:
    home, _ = api("/api/traffic/categories", **window)
    rows = home.get("categories", [])
    bad = []
    for c in rows:
        detail, _ = api(f"/api/traffic/categories/{c['name']}", **window)
        if (detail["total_bytes"], detail["connection_count"]) != (c["total_bytes"], c["connection_count"]):
            bad.append(f"{c['name']} home {c['total_bytes']}/{c['connection_count']} detail {detail['total_bytes']}/{detail['connection_count']}")
        home_top = [(s["name"], s["bytes"]) for s in c.get("top_services", [])]
        detail_top = [(s["name"], s["bytes"]) for s in detail.get("services", [])][: len(home_top)]
        if home_top != detail_top:
            bad.append(f"{c['name']} top services differ: {home_top[:2]} vs {detail_top[:2]}")
    check("each category's detail = its Home bar (bytes, connections, top services)", not bad,
          f"{len(rows)} categories" + (f"; {bad[:3]}" if bad else ""))


def failure_states() -> None:
    smart, _ = api("/api/smart/health")
    check("drive health was read (not unknown)", smart.get("healthy") is not None, f"healthy={smart.get('healthy')} error={smart.get('error')}")
    storage, _ = api("/api/storage/status")
    check("storage index counts were read", storage.get("total_indices") is not None,
          f"total_indices={storage.get('total_indices')} error={storage.get('indices_error')}")
    updates, _ = api("/api/system/updates/available")
    print(f"  (info) update sources that couldn't be checked: {updates.get('failed_checks') or 'none'}")


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container

    client = OpenSearch(os.environ["OPENSEARCH_URL"], verify_certs=False, ssl_show_warn=False, timeout=120,
                        http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]))
    # whole hours ending an hour ago, so each heatmap cell is one complete hour
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    window = {"from": (end - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "to": (end - timedelta(milliseconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ").replace("000Z", "Z")}
    excluded = api("/api/settings/excluded-ips")[0].get("excluded_ips", [])
    print(f"window {window['from']} -> {window['to']}; excluded {excluded or '-'}")
    for step in (lambda: beacons(window), lambda: heatmap(client, window, "America/Los_Angeles", excluded),
                 lambda: heatmap(client, window, "UTC", excluded), lambda: heatmap(client, window, "Asia/Kolkata", excluded),
                 lambda: categories(window), failure_states):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - report and go on: one failed check must not hide the others
            check("check ran", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
