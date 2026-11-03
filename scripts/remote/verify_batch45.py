"""Batch 45 checks: System → Updates rows for OpenSearch (#119) and NetTap's own images (#117),
what the banner can offer (#118, checked in the browser too), and the Log Explorer timeline
slot by slot against one range filter per slot (#120: OpenSearch 3.5's date_histogram misplaced
up to ~970 records an hour there).

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch45.sh passes it with `python3 -c`).
Read-only: the update check only re-reads sources; nothing is applied.
"""

import json
import os
import sys
import urllib.error
import urllib.request

PROBLEMS: list[str] = []
NETTAP_IMAGES = {"nettap-web", "nettap-tshark", "nettap-cyberchef", "nettap-storage-daemon"}


def call(path: str, method: str = "GET") -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request("http://localhost:8880" + path, method=method, data=b"{}" if method == "POST" else None,
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


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container

    client = OpenSearch(os.environ["OPENSEARCH_URL"], verify_certs=False, ssl_show_warn=False, timeout=60,
                        http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]))
    real = client.info()["version"]["number"]
    call("/api/system/versions/scan", "POST")
    rows = {v["name"]: v for v in call("/api/system/versions")[1].get("versions", [])}
    row = rows.get("opensearch", {})
    check("OpenSearch row = the cluster's version", row.get("current_version") == real and row.get("status") == "ok",
          f"page {row.get('current_version')!r} ({row.get('status')}), cluster {real!r}")

    _, upd = call("/api/system/updates/check", "POST")
    checked, failed = set(upd.get("checked") or []), upd.get("failed_checks") or []
    listed = {u["component"]: u for u in upd.get("updates", [])}
    current = "nettap-daemon" not in failed and "nettap-daemon" not in listed
    images = sorted(NETTAP_IMAGES & set(rows))
    ok = all((name in checked) == current for name in images)
    check("NetTap's images are up to date only when its release is", ok and bool(images),
          f"release check {'found nothing newer' if current else 'failed or found a newer release'}; "
          f"images {images}; counted as checked {sorted(NETTAP_IMAGES & checked) or 'none'}")
    applicable = [n for n, u in listed.items() if not u.get("applies_with")]
    print(f"  (info) banner: {len(listed)} updates, applicable here {applicable or 'none'} -> Update All {'shown' if applicable else 'hidden'}")
    try:
        log_timeline(client)
    except Exception as exc:  # noqa: BLE001 - report and go on
        check("check ran", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


def log_timeline(client) -> None:
    from datetime import UTC, datetime, timedelta

    from api.logs import _EXCLUDE_DNS_NOISE

    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    start = end - timedelta(hours=24)
    window = {"from": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": (end - timedelta(milliseconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ").replace("000Z", "Z")}
    query = {"bool": {"filter": [{"range": {"@timestamp": {"gte": window["from"], "lte": window["to"]}}}],
                      "must_not": [{"term": {"event.dataset": "alert"}}, *_EXCLUDE_DNS_NOISE]}}
    slots = [start + timedelta(hours=i) for i in range(24)]
    aggs = {"h": {"filters": {"filters": {s.isoformat(): {"range": {"@timestamp": {"gte": s.isoformat(), "lt": (s + timedelta(hours=1)).isoformat()}}} for s in slots}},
                  "aggs": {"t": {"terms": {"field": "event.dataset", "size": 20}}}}}
    qs = "&".join(f"{k}={v}" for k, v in window.items())
    for attempt in range(3):  # Zeek and Arkime rewrite records while a connection lasts
        _, got = call(f"/api/logs/timeline?interval=1h&{qs}")
        raw = client.search(index="arkime_sessions3-*", body={"size": 0, "query": query, "aggs": aggs}, request_cache=False)
        truth = {datetime.fromisoformat(k): (b["doc_count"], next((t["doc_count"] for t in b["t"]["buckets"] if t["key"] == "conn"), 0))
                 for k, b in raw["aggregations"]["h"]["buckets"].items()}
        page = {datetime.fromisoformat(str(b["timestamp"])): (b["total"], b["conn"]) for b in got.get("buckets", [])}
        wrong = [(k.strftime("%H:%M"), page.get(k), v) for k, v in sorted(truth.items()) if page.get(k) != v]
        if not wrong:
            break
        print(f"  (retry) log timeline: read {attempt + 1} had {len(wrong)} hours differ {wrong[:2]}")
    check("Log Explorer timeline = range filters hour by hour", not wrong,
          f"{len(truth)} hours, {sum(v[0] for v in truth.values()):,} records; differ {wrong[:3] or 'none'}")


if __name__ == "__main__":
    sys.exit(main())
