"""#144/#145 check, run inside nettap-storage-daemon: the Connections list and the Live feed.

#145: the Connections list sorts every page on the daemon (each column both ways, blanks last,
Source by IP then port), its State filter covers every page, and bad parameters are refused.
#144: every row carries `length`, the duration the pages now show, equal to event end minus start,
and the Live feed reports real durations instead of 0 s. Read-only: GET requests only.
"""

import ipaddress
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
    "duration": ("length",),
    "dl": ("destination", "bytes"),
    "ul": ("source", "bytes"),
}
REJECTED = {"REJ", "RSTR", "RSTO"}


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
    return record[0] if isinstance(record, list) and record else record


def in_order(values: list, order: str) -> bool:
    present = [v for v in values if v is not None]
    blanks_last = values[: len(present)] == present
    return blanks_last and present == sorted(present, reverse=order == "desc")


def time_key(stamp):
    """ISO time in order: as text, ".571000064Z" sorts before ".5Z"."""
    if stamp is None:
        return None
    head, _, fraction = str(stamp).rstrip("Z").partition(".")
    return head, float("0." + (fraction or "0"))


def address_key(record: dict) -> tuple[int, int] | None:
    """Source IP then port, IPv4 placed where OpenSearch puts it (IPv4-mapped IPv6)."""
    ip = value(record, ("source", "ip"))
    if ip is None:
        return None
    addr = ipaddress.ip_address(ip)
    if addr.version == 4:
        addr = ipaddress.IPv6Address("::ffff:" + str(addr))
    return int(addr), value(record, ("source", "port")) or 0


def check(label: str, ok: bool, detail: str) -> bool:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    return ok


now = datetime.now(UTC)
window = {"from": (now - timedelta(hours=1)).isoformat(), "to": now.isoformat(), "size": 50}
LIST = "/api/traffic/connections"
all_ok = True
totals = set()

for key, path in FIELDS.items():
    for order in ("desc", "asc"):
        code, body = get(LIST, {**window, "sort": key, "order": order})
        rows = body.get("connections") or []
        totals.add(body.get("total"))
        values = [value(r, path) for r in rows]
        if key == "time":
            values = [time_key(v) for v in values]
        all_ok &= check(
            f"#145 sort={key} order={order}",
            code == 200 and len(rows) > 0 and in_order(values, order),
            f"HTTP {code}, {len(rows)} rows, first {values[:1]}, last {values[-1:]}",
        )

for order in ("asc", "desc"):
    code, body = get(LIST, {**window, "sort": "source", "order": order})
    rows = body.get("connections") or []
    keys = [address_key(r) for r in rows]
    all_ok &= check(
        f"#145 sort=source order={order} (IP, then port)",
        code == 200 and len(rows) > 0 and in_order(keys, order),
        f"HTTP {code}, {len(rows)} rows, first {value(rows[0], ('source', 'ip')) if rows else None}",
    )
all_ok &= check("#145 same total for every sort", len(totals) == 1, f"{sorted(map(str, totals))}")

everything = totals.pop() if len(totals) == 1 else None
code, body = get(LIST, {**window, "state": "rejected"})
rows = body.get("connections") or []
states = {value(r, ("zeek", "conn", "conn_state")) for r in rows}
all_ok &= check(
    "#145 state=rejected filters every page",
    code == 200 and states <= REJECTED and (everything is None or body.get("total", 0) < everything),
    f"HTTP {code}, total {body.get('total')} of {everything}, states on page 1 {sorted(map(str, states))}",
)

for params in ({"sort": "bogus"}, {"order": "up"}, {"state": "weird"}):
    code, _ = get(LIST, {**window, **params})
    all_ok &= check(f"#145 refused {params}", code == 400, f"HTTP {code}")

code, body = get(LIST, {**window, "sort": "duration", "order": "desc"})
rows = body.get("connections") or []
mismatched = []
for r in rows:
    start, end = value(r, ("event", "start")), value(r, ("event", "end"))
    if str(start).isdigit() and str(end).isdigit() and int(end) - int(start) != r.get("length"):
        mismatched.append((r.get("length"), start, end))
with_length = sum(isinstance(r.get("length"), (int, float)) for r in rows)
all_ok &= check(
    "#144 every row has length = end minus start (ms)",
    code == 200 and rows and with_length == len(rows) and not mismatched,
    f"{with_length}/{len(rows)} with length, longest {rows[0].get('length') if rows else None} ms, "
    f"mismatches {mismatched[:2]}",
)
services = sum(value(r, ("network", "protocol")) is not None for r in rows)
print(f"  #145 Service column: {services}/{len(rows)} of the longest rows name a service (network.protocol)")

code, body = get("/api/live/connections", {"limit": 100})
live = body.get("connections") or []
timed = [c["duration"] for c in live if (c.get("duration") or 0) > 0]
all_ok &= check(
    "#144 Live feed reports real durations",
    code == 200 and len(live) > 0 and len(timed) > 0,
    f"HTTP {code}, {len(timed)}/{len(live)} with a duration over 0 s, longest {max(timed, default=0):.3f} s",
)
sys.exit(0 if all_ok else 1)
