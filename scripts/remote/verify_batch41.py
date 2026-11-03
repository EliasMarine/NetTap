"""Batch 41 checks: an unreadable from/to is a 400 everywhere, never the default window (#105).

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch41.sh passes it with `python3 -c`).
Read-only.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

PROBLEMS: list[str] = []
# one endpoint per module that reads from/to, plus PCAP
WINDOWED = ["/api/traffic/summary", "/api/alerts/count", "/api/dns/top-domains", "/api/threats/report", "/api/devices",
            "/api/risk/scores", "/api/lan/anomalies", "/api/iot/fleet-summary", "/api/bandwidth/heatmap",
            "/api/certificates/issuer-changes", "/api/mac/merge-suggestions", "/api/changelog", "/api/pcap/files"]


def call(path: str, **params) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request("http://localhost:8880" + path + query, headers={"X-NetTap-Daemon-Token": token})
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


def main() -> int:
    wrong = []
    for path in WINDOWED:
        status, body = call(path, **{"from": "now-5m", "to": "now"})
        if status != 400 or "ISO 8601" not in str(body.get("error")):
            wrong.append(f"{path} HTTP {status}")
    check("an unreadable time is a 400 naming the format, not 24 h of data", not wrong,
          f"{len(WINDOWED) - len(wrong)} of {len(WINDOWED)} endpoints; wrong: {wrong or 'none'}")
    ok = [p for p in ("/api/traffic/summary", "/api/alerts/count", "/api/pcap/files") if call(p, **{"from": "", "to": ""})[0] == 200]
    check("an empty from/to still means the default window", len(ok) == 3, f"{len(ok)} of 3 answer 200")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
