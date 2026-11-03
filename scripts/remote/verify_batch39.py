"""Batch 39 checks on real data: exact device counts and the rules version.

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch39.sh passes it with `python3 -c`).
Read-only.
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


def call(path: str, **params) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request("http://localhost:8880" + path + query, headers={"X-NetTap-Daemon-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def devices(client) -> None:
    now = datetime.now(UTC)
    since = (now - timedelta(hours=24)).isoformat()
    status, new = call("/api/devices/registry/new-count", since=since)
    raw = client.count(index="nettap-devices", body={"query": {"range": {"first_seen": {"gte": since}}}})["count"]
    total = client.count(index="nettap-devices")["count"]
    check("New (24h) = registry devices first seen in 24 h", status == 200 and new.get("count") == raw,
          f"API {new.get('count')}, OpenSearch {raw}, of {total} known (the page used to say every device)")
    window = {"from": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"), "to": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    _, online = call("/api/devices/count", **window)
    _, listed = call("/api/devices", limit=500, **window)
    check("Online Now = devices with traffic in the last 5 min", online.get("count") == len(listed.get("devices", [])),
          f"count {online.get('count')}, list {len(listed.get('devices', []))}")
    _, day = call("/api/devices/count")
    _, page = call("/api/devices", sort="bytes", order="desc", limit=500)
    check("the Devices list is complete on this network", len(page.get("devices", [])) == day.get("count"),
          f"list {len(page.get('devices', []))} of {day.get('count')} devices")


def rules() -> None:
    _, vers = call("/api/system/versions")
    row = next((c for c in vers.get("versions", []) if c.get("name") == "suricata-rules"), {})
    container = os.environ.get("SURICATA_CONTAINER_NAME", "nettap-suricata-live")
    out = subprocess.run(["docker", "exec", container, "stat", "-c", "%Y", "/var/lib/suricata/rules/suricata.rules"],
                         capture_output=True, text=True, timeout=30, check=False)
    want = datetime.fromtimestamp(int(out.stdout.strip()), tz=UTC).strftime("%Y-%m-%d") if out.stdout.strip().isdigit() else None
    check("rules version = the Suricata container's rules file date", want is not None and row.get("current_version") == want,
          f"page {row.get('current_version')!r} ({row.get('status')}), file {want!r} {row.get('details')}")


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container

    client = OpenSearch(os.environ["OPENSEARCH_URL"], verify_certs=False, ssl_show_warn=False, timeout=120,
                        http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]))
    # the versions cache may predate the restart: ask for a fresh scan first
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request("http://localhost:8880/api/system/versions/scan", data=b"{}", method="POST",
                                 headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=120).read()
    except urllib.error.URLError as exc:
        print(f"  (info) version rescan: {exc}")
    for step in (lambda: devices(client), rules):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - report and go on: one failed check must not hide the others
            check("check ran", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
