"""#140 check, run inside nettap-storage-daemon: a device's connections sort by every column.

Takes the busiest device of the last 24 h and asks for its connections sorted by each
numeric column both ways, then checks the rows really come back in that order, blanks last,
with the same total every time. Read-only: GET requests to the daemon only.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

with open("/run/nettap-auth/daemon-token") as token_file:
    TOKEN = token_file.read().strip()

# sort key -> the field it orders by, as a path into each returned record
FIELDS = {
    "time": ("@timestamp",),
    "dl": ("destination", "bytes"),
    "ul": ("source", "bytes"),
    "duration": ("length",),
}


def get(path: str, params: dict) -> tuple[int, dict]:
    url = "http://localhost:8880" + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"X-NetTap-Daemon-Token": TOKEN})
    try:
        with urllib.request.urlopen(request, timeout=120) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception as exc:  # noqa: BLE001 — any failure is reported, not hidden
        print(f"✗ request failed: {path}: {exc}")
        return 0, {}


def value(record: dict, path: tuple[str, ...]):
    for part in path:
        record = record.get(part) if isinstance(record, dict) else None
    return record


def in_order(values: list, order: str) -> bool:
    present = [v for v in values if v is not None]
    blanks_last = values[: len(present)] == present
    expected = sorted(present, reverse=order == "desc")
    return blanks_last and present == expected


def check(label: str, ok: bool, detail: str) -> bool:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    return ok


now = datetime.now(UTC)
window = {
    "from": (now - timedelta(hours=24)).isoformat(),
    "to": now.isoformat(),
}
code, listing = get("/api/devices", {**window, "limit": 50})
devices = listing.get("devices") or []
if code != 200 or not devices:
    check(
        "device list", False, f"HTTP {code}, {len(devices)} devices — nothing to sort"
    )
    sys.exit(1)
ip = max(devices, key=lambda d: d.get("connection_count") or 0)["ip"]
print(f"  device {ip}")

all_ok = True
totals = set()
for key, path in FIELDS.items():
    for order in ("desc", "asc"):
        code, body = get(
            f"/api/devices/{ip}/connections",
            {**window, "sort": key, "order": order, "size": 50},
        )
        rows = body.get("connections") or []
        totals.add(body.get("total"))
        values = [value(r, path) for r in rows]
        all_ok &= check(
            f"sort={key} order={order}",
            code == 200 and len(rows) > 0 and in_order(values, order),
            f"HTTP {code}, {len(rows)} rows, first {values[:1]}, last {values[-1:]}",
        )

all_ok &= check(
    "same total for every sort", len(totals) == 1, f"{sorted(map(str, totals))}"
)
code, _ = get(f"/api/devices/{ip}/connections", {**window, "sort": "bogus"})
all_ok &= check("unknown sort refused", code == 400, f"HTTP {code}")
sys.exit(0 if all_ok else 1)
