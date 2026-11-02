"""Batch 42 checks: System → Updates rows (each row its own update, "Not checked" for what
nothing checks), the host's OS version, and Home's bandwidth chart bucket by bucket against
range filters (OpenSearch 3.5's date_histogram can bucket a stale copy of a rewritten record).

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch42.sh passes it with `python3 -c`).
Read-only: the update check only re-reads sources; nothing is applied.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

PROBLEMS: list[str] = []
NEVER_CHECKED = {"os", "kernel", "docker", "python3", "opensearch"}  # no update source covers these


def call(path: str, method: str = "GET", **params) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request("http://localhost:8880" + path + query, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def version_id(path: str) -> str | None:
    try:
        with open(path) as fh:
            return next((ln.split("=", 1)[1].strip().strip('"') for ln in fh if ln.startswith("VERSION_ID=")), None)
    except OSError:
        return None


def bandwidth_chart(client) -> None:
    from services.excluded_ips import build_excluded_ips_filter

    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    start = end - timedelta(hours=24)
    window = {"from": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": (end - timedelta(milliseconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ").replace("000Z", "Z")}
    excluded = call("/api/settings/excluded-ips")[1].get("excluded_ips", [])
    clause = {"filter": [{"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "conn"}}], "must_not": build_excluded_ips_filter(excluded)}
    for minutes in (15, 60):
        slots = [start + timedelta(minutes=minutes * i) for i in range(24 * 60 // minutes)]
        aggs = {"h": {"filters": {"filters": {s.isoformat(): {"range": {"@timestamp": {"gte": s.isoformat(), "lt": (s + timedelta(minutes=minutes)).isoformat()}}} for s in slots}},
                      "aggs": {"o": {"sum": {"field": "source.bytes", "missing": 0}}, "r": {"sum": {"field": "destination.bytes", "missing": 0}}}}}
        for attempt in range(3):  # Zeek rewrites a long connection's record while it lasts
            _, chart = call("/api/traffic/bandwidth", interval=f"{minutes}m" if minutes < 60 else "1h", **window)
            raw = client.search(index="arkime_sessions3-*", body={"size": 0, "query": {"bool": clause}, "aggs": aggs}, request_cache=False)
            truth = {datetime.fromisoformat(k): (int(b["o"]["value"] + b["r"]["value"]), b["doc_count"]) for k, b in raw["aggregations"]["h"]["buckets"].items()}
            got = {datetime.fromisoformat(str(b["timestamp"]).replace("Z", "+00:00")): (int(b["total_bytes"]), b["connections"]) for b in chart.get("series", [])}
            wrong = [(k.strftime("%H:%M"), got.get(k), v) for k, v in sorted(truth.items()) if got.get(k, (0, 0)) != v]
            if not wrong:
                break
            print(f"  (retry) {minutes} min chart: read {attempt + 1} had {len(wrong)} buckets differ {wrong[:2]}")
        check(f"Home's bandwidth chart ({minutes} min) = range filters bucket by bucket", not wrong,
              f"{len(truth)} buckets, {sum(v[0] for v in truth.values()):,} bytes; differ {wrong[:3] or 'none'}")


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container

    client = OpenSearch(os.environ["OPENSEARCH_URL"], verify_certs=False, ssl_show_warn=False, timeout=120,
                        http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]))
    try:
        bandwidth_chart(client)
    except Exception as exc:  # noqa: BLE001 - report and go on: one failed check must not hide the others
        check("check ran", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    call("/api/system/versions/scan", "POST")
    _, upd = call("/api/system/updates/check", "POST")
    _, vers = call("/api/system/versions")
    rows = {v["name"]: v for v in vers.get("versions", [])}

    host, image = version_id("/host/etc/os-release"), version_id("/etc/os-release")
    os_row = rows.get("os", {})
    check("OS version is the host's, not the daemon image's", host is not None and os_row.get("current_version") == host,
          f"page {os_row.get('current_version')!r} {os_row.get('details')}, host {host!r}, daemon image {image!r}")

    names = [u["component"] for u in upd.get("updates", [])]
    unmatched = [n for n in names if n not in rows]
    check("every listed update has its own row", not unmatched, f"{len(names)} updates {names}; without a row: {unmatched or 'none'}")
    checked = set(upd.get("checked") or [])
    wrong = sorted(NEVER_CHECKED & checked)
    covered = sorted(set(names) - checked)
    check("the check says what it covered (OS, Docker, Python... not)", bool(checked) and not wrong and not covered,
          f"checked {sorted(checked)}; wrongly claimed {wrong or 'none'}; updates outside it {covered or 'none'}")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
