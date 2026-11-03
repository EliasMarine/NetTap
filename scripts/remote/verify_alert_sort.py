"""#146/#147 check, run inside nettap-storage-daemon: the alert tables sort every page, and a
category's (and sub-category's) alert list holds exactly the alerts its header counts.

#146: severity "desc" must put the range's most severe alert on page 1 (the pages ranked only the
50 newest), each column comes back in order both ways, and unknown values are refused.
#147: each category's list total equals its header (Exploit listed 99 under a 6-alert header),
and each sub-category's list equals its bar. Read-only: GET requests to the daemon only.
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


def ip_key(text):
    if not text:
        return None
    addr = ipaddress.ip_address(text)
    return int(ipaddress.IPv6Address("::ffff:" + text) if addr.version == 4 else addr)


# sort key -> the value each returned alert is ordered by (severity: 1 is the most severe)
VALUES = {
    "severity": lambda a: -(a.get("alert") or {}).get("severity", 4),
    "dest_port": lambda a: a.get("dest_port"),
    "source": lambda a: ip_key(a.get("src_ip")),
    "proto": lambda a: a.get("proto") or None,
}


def in_order(values: list, order: str) -> bool:
    present = [v for v in values if v is not None]
    blanks_last = values[: len(present)] == present
    return blanks_last and present == sorted(present, reverse=order == "desc")


def check(label: str, ok: bool, detail: str) -> bool:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    return ok


# ends 10 minutes ago, so records still arriving can't change a total between two calls
now = datetime.now(UTC) - timedelta(minutes=10)
window = {"from": (now - timedelta(hours=24)).isoformat(), "to": now.isoformat()}
all_ok = True

code, body = get("/api/alerts/count", window)
counts = body.get("counts") or {}
worst = 1 if counts.get("high") else 2 if counts.get("medium") else 3
code, body = get("/api/alerts", {**window, "sort": "severity", "order": "desc", "size": 50})
rows = body.get("alerts") or []
first = (rows[0].get("alert") or {}).get("severity") if rows else None
all_ok &= check(
    "severity desc puts the range's most severe alert on page 1",
    code == 200 and first == worst,
    f"HTTP {code}, first severity {first}, most severe in 24 h {worst} "
    f"(high {counts.get('high')}, medium {counts.get('medium')}, low {counts.get('low')})",
)

totals = set()
for key, read in VALUES.items():
    for order in ("desc", "asc"):
        code, body = get("/api/alerts", {**window, "sort": key, "order": order, "size": 50})
        rows = body.get("alerts") or []
        totals.add(body.get("total"))
        values = [read(a) for a in rows]
        all_ok &= check(
            f"sort={key} order={order}",
            code == 200 and len(rows) > 0 and in_order(values, order),
            f"HTTP {code}, {len(rows)} rows, first {values[:1]}, last {values[-1:]}",
        )
all_ok &= check("same total for every sort", len(totals) == 1, f"{sorted(map(str, totals))}")

code, cats = get("/api/alerts/categories", window)
busiest = max(cats.get("categories") or [], key=lambda c: c.get("count") or 0, default=None)
if busiest:
    slug = busiest.get("id") or busiest.get("slug")
    plain = get("/api/alerts", {**window, "category": slug, "size": 25})[1].get("total")
    code, body = get("/api/alerts", {**window, "category": slug, "sort": "severity", "order": "desc", "size": 25})
    all_ok &= check(
        f"category {slug} keeps its filter while sorted",
        code == 200 and body.get("total") == plain,
        f"HTTP {code}, total {body.get('total')} sorted vs {plain} unsorted",
    )

for cat in cats.get("categories") or []:
    detail = get(f"/api/alerts/categories/{cat['id']}", window)[1]
    header = (detail.get("stats") or {}).get("total")
    code, body = get("/api/alerts", {**window, "category": cat["id"], "size": 1})
    all_ok &= check(
        f"#147 category {cat['id']}: list total = header",
        code == 200 and body.get("total") == header == cat.get("count"),
        f"HTTP {code}, list {body.get('total')}, header {header}, overview {cat.get('count')}",
    )
    for sub in detail.get("sub_categories") or []:
        code, body = get("/api/alerts", {**window, "category": cat["id"], "sub": sub["id"], "size": 1})
        all_ok &= check(
            f"#147   sub-category {sub['id']}: list total = bar",
            code == 200 and body.get("total") == sub.get("count"),
            f"HTTP {code}, list {body.get('total')}, bar {sub.get('count')}",
        )

for params in ({"sort": "bogus"}, {"order": "up"}, {"category": "bogus"}, {"category": "exploit", "sub": "tor"}):
    code, _ = get("/api/alerts", {**window, **params})
    all_ok &= check(f"refused {params}", code == 400, f"HTTP {code}")
sys.exit(0 if all_ok else 1)
