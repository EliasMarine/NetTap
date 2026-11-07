"""NET-192 PR 4: the pages that gained a long range answer it in time.

Runs inside nettap-storage-daemon (python3 -c "$(cat ...)"). Calls, one at a time (the first
call is usually cold), each 30-day request DNS, IoT and the MAC device page now make, and
Connections' 7-day ones (no 30d there until PR 3 speeds up its stats). A call fails if it takes
more than 80% of the web proxy's timeout for it (10 s by default; 30 s for connections stats,
web/src/routes/api/[...path]/+server.ts). Prints one line per call, slowest first.
The G11 holds data from 2026-11-02, so until December a "30-day" window covers fewer days.
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
PROXY_TIMEOUT_S = {"/api/traffic/connections/stats": 30}
DEFAULT_PROXY_TIMEOUT_S = 10
MARGIN = 0.8


def get(path, timeout=120):
    req = urllib.request.Request(BASE + path, headers={"X-NetTap-Daemon-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


now = datetime.now(UTC)
win = {"from": stamp(now - timedelta(days=30)), "to": stamp(now)}
week = {"from": stamp(now - timedelta(days=7)), "to": stamp(now)}


def q(window=None, **extra):
    return "?" + urllib.parse.urlencode({**(window or win), **extra})


def first_mac(path, key):
    try:
        rows = get(path).get(key) or []
        return next(
            (
                r.get("mac") or r.get("mac_address")
                for r in rows
                if r.get("mac") or r.get("mac_address")
            ),
            None,
        )
    except Exception:
        return None


# (label, request): a device's MAC goes in the request only; the label says {mac}
calls = [
    (p.split("?")[0], p)
    for p in [
        "/api/dns/stats" + q(),
        "/api/dns/top-domains" + q(limit=50),
        "/api/dns/nxdomain" + q(),
        "/api/dns/types" + q(),
        "/api/dns/suspicious" + q(),
        "/api/dns/timeline" + q(interval="6h"),
        "/api/traffic/connections/stats" + q(week),
        "/api/traffic/connections/sankey" + q(week, limit=10),
        "/api/traffic/connections/timeline" + q(week, interval="6h"),
        "/api/traffic/connections" + q(week, page=1, size=50),
        "/api/live/dashboard" + q(week, limit=1),
        "/api/iot/fleet-summary" + q(),
        "/api/iot/privacy-report" + q(),
        "/api/iot/protocol-audit" + q(),
        "/api/iot/network-isolation" + q(),
        "/api/iot/manufacturer-profiles" + q(),
    ]
]
iot_mac = first_mac("/api/iot/devices", "devices")
if iot_mac:
    m = urllib.parse.quote(iot_mac, safe="")
    for tail in ("communication-map", "activity-timeline"):
        calls.append(
            (f"/api/iot/devices/{{mac}}/{tail}", f"/api/iot/devices/{m}/{tail}" + q())
        )
reg_mac = first_mac("/api/devices/registry?limit=1", "devices")
if reg_mac:
    r = urllib.parse.quote(reg_mac, safe="")
    calls.append(
        (
            "/api/devices/registry/{mac}/traffic",
            f"/api/devices/registry/{r}/traffic" + q(),
        )
    )

results, failed = [], False
for label, path in calls:
    limit = PROXY_TIMEOUT_S.get(label, DEFAULT_PROXY_TIMEOUT_S) * MARGIN
    t0 = time.monotonic()
    try:
        get(path)
        err = ""
    except urllib.error.HTTPError as exc:
        err = f" (HTTP {exc.code})"
    except Exception as exc:
        err = f" ({type(exc).__name__})"
    secs = time.monotonic() - t0
    bad = bool(err) or secs > limit
    failed |= bad
    results.append(
        (secs, f"{'✗' if bad else '✓'} {label} {secs:.1f} s (limit {limit:.0f} s){err}")
    )

for _, line in sorted(results, reverse=True):
    print(line)
if not iot_mac or not reg_mac:
    print("(info) no IoT or registry device found, so its drawer calls were not timed")
sys.exit(1 if failed else 0)
