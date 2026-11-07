"""NET-192 PR 3: how long the slow pages' daemon calls take.

Runs inside nettap-storage-daemon (python3 -c "$(cat ...)" [pages|snapshot]), one call at a time.

  pages     Right after a restart, so the daemon has cached nothing. Every windowed call gets a
            `to` of this second, so OpenSearch's request cache can't answer it either.
  snapshot  Waits until the background beaconing check has a 7-day result, then times the
            Threats page's report at 24 h and 7 d as the page asks for it (?snapshot=).

One line per call: a fixed label, the HTTP status, seconds and the reply's size. Labels are
fixed text: no device address and never the token.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

BASE = "http://localhost:8880"
TOKEN = open("/run/nettap-auth/daemon-token").read().strip()
CALL_TIMEOUT_S = 180
PUBLIC_IP = "1.1.1.1"  # has a PTR record (one.one.one.one)
SNAPSHOT_WAIT_S = 600

H = timedelta(hours=1)
D = timedelta(days=1)

# (label, path, window or None, extra query)
PAGES = [
    ("connections stats 24h", "/api/traffic/connections/stats", 24 * H, {}),
    ("connections stats 7d", "/api/traffic/connections/stats", 7 * D, {}),
    ("connections stats 30d", "/api/traffic/connections/stats", 30 * D, {}),
    (
        "devices list 24h",
        "/api/devices",
        24 * H,
        {"sort": "bytes", "order": "desc", "limit": 500},
    ),
    (
        "devices list 30d",
        "/api/devices",
        30 * D,
        {"sort": "bytes", "order": "desc", "limit": 500},
    ),
    ("risk scores 24h", "/api/risk/scores", 24 * H, {}),
    ("bandwidth devices 24h", "/api/bandwidth/devices", 24 * H, {"limit": 50}),
    ("certificates overview 24h", "/api/certificates/overview", 24 * H, {}),
    ("threat report 24h (live)", "/api/threats/report", 24 * H, {}),
    ("threat report 7d (live)", "/api/threats/report", 7 * D, {}),
    ("reverse DNS, public IP (cold)", f"/api/lookup/dns/{PUBLIC_IP}", None, {}),
    ("reverse DNS, public IP (warm)", f"/api/lookup/dns/{PUBLIC_IP}", None, {}),
]
SNAPSHOTS = [
    ("threat report snapshot=24h", "/api/threats/report", None, {"snapshot": "24h"}),
    ("threat report snapshot=7d", "/api/threats/report", None, {"snapshot": "7d"}),
]


def stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def url(path: str, span: timedelta | None, extra: dict) -> str:
    params = dict(extra)
    if span is not None:  # computed at call time: a fresh `to` for every call
        now = datetime.now(UTC)
        params.update({"from": stamp(now - span), "to": stamp(now)})
    return BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")


def call(path: str, span: timedelta | None = None, extra: dict | None = None):
    """(status, seconds, body bytes); status 0 when no answer came."""
    req = urllib.request.Request(
        url(path, span, extra or {}), headers={"X-NetTap-Daemon-Token": TOKEN}
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=CALL_TIMEOUT_S) as r:
            body = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        body, status = e.read(), e.code
    except Exception:
        body, status = b"", 0
    return status, time.monotonic() - t0, body


def snapshot_state(body: bytes) -> str:
    try:
        snap = json.loads(body).get("beaconing_snapshot")
    except (ValueError, AttributeError):
        return "unreadable"
    return snap.get("state", "?") if isinstance(snap, dict) else "live (no snapshot)"


def report(label: str, status: int, secs: float, body: bytes, note: str = "") -> None:
    print(f"{label:<32} {status:>3} {secs:7.2f} s {len(body) / 1000:9.1f} kB{note}")


def run(calls, with_state: bool = False) -> int:
    failed = 0
    for label, path, span, extra in calls:
        status, secs, body = call(path, span, extra)
        failed += status != 200
        report(
            label,
            status,
            secs,
            body,
            f"  beaconing: {snapshot_state(body)}" if with_state else "",
        )
    return failed


def wait_for_snapshot(window: str) -> str:
    deadline = time.monotonic() + SNAPSHOT_WAIT_S
    state = "pending"
    while time.monotonic() < deadline:
        status, _, body = call("/api/threats/beaconing", None, {"snapshot": window})
        state = snapshot_state(body) if status == 200 else f"HTTP {status}"
        if state != "pending":
            break
        time.sleep(15)
    return state


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "pages"
    if mode == "snapshot":
        t0 = time.monotonic()
        state = wait_for_snapshot("7d")
        print(f"7-day beaconing snapshot: {state} after {time.monotonic() - t0:.0f} s")
        sys.exit(1 if run(SNAPSHOTS, with_state=True) or state != "ready" else 0)
    sys.exit(1 if run(PAGES) else 0)
