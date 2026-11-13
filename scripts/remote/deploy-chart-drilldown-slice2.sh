#!/usr/bin/env bash
# Deploy NET-249 slice 2 (click or drag every other time chart to open exactly that window) and
# check it on the device's real data.
#
# Rebuilds the web UI and the daemon. Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-chart-drilldown-slice2.sh
# To test a branch first: BRANCH=<branch> bash …
#
# What each step proves (PLAN.md §5):
#   6   every server-backed time chart answers each range with the owner's bucket, its slot count,
#       the bucket and window echoed, and a fresh window in under 3 s
#   7   every chart whose link carries count=: a slot's figure is the total of the list it opens
#   8   the pages that narrow themselves: the same route over a slot's window has the slot's figure
#   9   an unknown bucket, and one too fine for the window, are refused with a 400
#   10  the live connection drawer: 5 min slots over 24 h with their window and port, and a
#       settled slot's connections are what its Log Explorer link lists
#   11  every changed page renders on a logged-in full reload through nginx
#
# The figure checks use windows that ended 2 hours ago, so a connection logged after a figure
# was read (Zeek logs a connection when it ends) can't move it between two reads. The sample
# address, device, names and categories are picked from that data in step 5 and printed.
#
# Rollback: redeploy the previous main with this script's first three steps:
#   cd /home/nettap/NetTap && git checkout <previous-sha> && sudo docker compose -f docker/docker-compose.yml build nettap-web nettap-storage-daemon
#   sudo docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-web nettap-storage-daemon
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
LAST_OUT=""
SAMPLES=""

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

in_daemon() {  # in_daemon < python: runs it in the daemon container; a "✗" line, a crash or no output fails
    local out
    out=$(sudo docker exec -i -w /opt/nettap/daemon nettap-storage-daemon python3 - 2>&1)
    # SAMPLES and PAGE lines are for this script, not the reader
    printf '%s\n' "${out:-   ✗ no output}" | grep -v -e '^SAMPLES ' -e '^PAGE '
    case "$out" in *"✗ "*|*Traceback*|"") FAILED=1 ;; esac
    LAST_OUT=$out
}

echo "=== Deploy: chart drill-down, slice 2 ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
PREVIOUS=$(git rev-parse --short HEAD)
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s') (was $PREVIOUS)"
echo ""

echo "→ Step 2: Build the web and daemon containers..."
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the web and the daemon..."
RECREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web nettap-storage-daemon
echo ""

echo "→ Step 4: Wait for them to become healthy..."
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB" = "healthy" ] && [ "$DAEMON" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB daemon=$DAEMON ($i/30)"
    sleep 5
done
expect "nettap-web" "$WEB" healthy
expect "nettap-storage-daemon" "$DAEMON" healthy
echo ""

# One Python program per step, inside the daemon container, each starting with COMMON. The token
# is read inside get(); it is never printed. Each program prints one "✓ …" or "✗ …" line per check.
COMMON=$(cat <<'PY'
import base64, collections, json, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

def get(path, **params):
    """(status, body, seconds) of a daemon GET; the body is {} when it is not JSON."""
    token = open("/run/nettap-auth/daemon-token").read().strip()
    url = "http://localhost:8880" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"X-NetTap-Daemon-Token": token})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.load(r), time.monotonic() - t0
    except urllib.error.HTTPError as e:  # a refusal's {"error": …} is checked in step 9
        try:
            body = json.load(e)
        except ValueError:
            body = {}
        return e.code, body, time.monotonic() - t0
    except (urllib.error.URLError, ValueError) as e:
        return "unreachable", {"error": str(e)}, time.monotonic() - t0

def say(ok, label, detail=""):
    print(("   ✓ " if ok else "   ✗ ") + label + (": " + str(detail) if detail != "" else ""))

def iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")

def ms(text):
    return round(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)

def at(n):
    return iso(datetime.fromtimestamp(n / 1000, timezone.utc))

STEP = {"1m": 60_000, "5m": 300_000, "1h": 3_600_000, "3h": 10_800_000}
DAY = 86_400_000
# The ranges and the owner's buckets (web/src/lib/utils/drilldown.ts DRILL_RANGES), with slot counts
RANGES = (("1h", timedelta(hours=1), "1m", 61), ("6h", timedelta(hours=6), "5m", 73),
          ("24h", timedelta(hours=24), "5m", 289), ("7d", timedelta(days=7), "1h", 169),
          ("30d", timedelta(days=30), "3h", 241))
# Settled: ended 2 h ago. 37 s off the minute, so no range starts or ends on a slot edge
END = datetime.now(timezone.utc).replace(second=37, microsecond=0) - timedelta(hours=2)
E = round(END.timestamp() * 1000)
TOO_MANY = "Too many points for this window; pick a longer bucket"  # api/time_range.py TOO_MANY_SLOTS

def span_ms(span):
    return span // timedelta(milliseconds=1)

def window(lo, hi):
    return {"from": at(lo), "to": at(hi)}

def seg(value):  # encodeURIComponent, for a path segment
    return urllib.parse.quote(value, safe="")

def link_window(times, i, step, reply):
    """A pick of slot i (drilldown.ts bucketWindow): clipped to the reply, ending at the slot end - 1 ms."""
    t = ms(times[i])
    return max(t, ms(reply["from"])), min(t + step, ms(reply["to"]) + 1) - 1

def bucket_for(lo, hi):
    """A custom window's bucket (drilldown.ts bucketFor): the smallest range that covers it."""
    return next((b for _, span, b, _ in RANGES if span_ms(span) >= hi - lo), RANGES[-1][2])

def picks(slots):
    """The slots each count check takes: the busiest whole one, then the clipped first and last."""
    busiest = max(range(1, len(slots) - 1), key=lambda i: slots[i][1])
    return (("busiest", busiest), ("first (clipped)", 0), ("last (clipped)", len(slots) - 1))

def samples(b64):
    return json.loads(base64.b64decode(b64) or b"{}")

def sev(b):  # alerts/+page.svelte bucketTotal: every severity, Info included
    return b["high"] + b["medium"] + b["low"] + b.get("info", 0)

# Every server-backed time chart: (label, the sample it needs, its route, its slots as
# [(start, figure)] as the page draws them, the key its bucket is echoed under)
CHARTS = (
    ("Alerts", None, "/api/alerts/timeline",
     lambda r: [(b["timestamp"], sev(b)) for b in r["buckets"]], "interval"),
    ("Alert category", "alert_category", "/api/alerts/categories/{}/timeline",
     lambda r: [(p["timestamp"], p["total"]) for p in r["series"]], "interval"),
    ("Suricata category", "suricata_category", "/api/alerts/suricata/{}",
     lambda r: [(p["t"], p["n"]) for p in r["timeline"]], "interval"),
    ("Log Explorer", None, "/api/logs/timeline",
     lambda r: [(b["timestamp"], b["total"]) for b in r["buckets"]], "interval"),
    ("DNS", None, "/api/dns/timeline",
     lambda r: [(p["timestamp"], p["count"]) for p in r["series"]], "interval"),
    ("Connections", None, "/api/traffic/connections/timeline",
     lambda r: [(b["timestamp"], b["total"]) for b in r["buckets"]], "interval"),
    ("Address", "address", "/api/addresses/{}",
     lambda r: [(p["t"], p["n"]) for p in r["timeline"]], "interval"),
    ("Domain", "domain", "/api/domains/{}",
     lambda r: [(p["t"], p["n"]) for p in r["dns"]["timeline"]], "interval"),
    ("Traffic category", "traffic_category", "/api/traffic/categories/{}/bandwidth",
     lambda r: [(p["timestamp"], p["total_bytes"]) for p in r["series"]], "interval"),
    ("Device", "device", "/api/devices/{}",
     lambda r: [(p["timestamp"], p["bytes"]) for p in r["device"]["bandwidth_series"]], "bandwidth_interval"),
    ("IoT activity", "iot_mac", "/api/iot/devices/{}/activity-timeline",
     lambda r: [(b["time"], b["connections"]) for b in r["buckets"]], "interval"),
)
CHART = {c[0]: c for c in CHARTS}

def path_of(chart):
    """The chart's route with its sample, or None (said once per step) when step 5 found none."""
    label, kind, route = chart[:3]
    if kind is None:
        return route
    if kind in S:
        return route.format(seg(S[kind]))
    print(f"     · {label}: skipped, no {kind.replace('_', ' ')} sample (see step 5)")
    return None

def read(path, chart, lo, hi, bucket):
    """(status, reply, slots or None, seconds) of a chart's route over [lo, hi] at `bucket`."""
    status, r, secs = get(path, interval=bucket, **window(lo, hi))
    try:
        slots = chart[3](r) if status == 200 else None
    except (KeyError, TypeError):
        slots = None
    return status, r, slots, secs

def has_window(r):
    return isinstance(r.get("from"), str) and isinstance(r.get("to"), str)

def chart_step(chart, r, slots):
    """The slot length a pick uses: the bucket the reply echoes, never the one asked for
    (chart-pick.ts toTimeChart); None when the chart stays a picture."""
    if slots is None or len(slots) < 3 or not has_window(r):
        return None
    return STEP.get(r.get(chart[4]))

def logs_total(lo, hi, **params):
    """Log Explorer's table total (logs/+page.svelte fetchLogs; size, sort and fields don't change it)."""
    status, r, _ = get("/api/logs/search", size=1, **params, **window(lo, hi))
    return status, r.get("total")

def alerts_total(lo, hi, **params):
    """The Alerts list's total (alerts/+page.svelte listParams, no other filter set)."""
    status, r, _ = get("/api/alerts", page=1, size=1, **params, **window(lo, hi))
    return status, r.get("total")
PY
)

echo "→ Step 5: Pick the sample address, device, names and categories from the last day..."
in_daemon <<PY
$COMMON
import ipaddress
from services.hostnames import canonical_name  # the domain route's own check
S = {}
W = window(E - DAY, E)

def found(kind, value, detail):
    S[kind] = value
    say(True, kind.replace("_", " "), f"{value} ({detail})")

def missing(kind, detail):
    say(False, f"no {kind.replace('_', ' ')} sample", detail)

status, r, _ = get("/api/devices", sort="bytes", order="desc", limit=5, **W)
busy = [d for d in r.get("devices", []) if d.get("total_bytes")]
if busy:
    found("device", busy[0]["ip"], f"the busiest device, {busy[0]['total_bytes']:,} bytes")
    if busy[0].get("mac"):
        S["device_mac"] = busy[0]["mac"]
else:
    missing("device", f"HTTP {status}, no device moved data")

status, r, _ = get("/api/logs/top-destinations", limit=10, **W)
# a public address first, as the address page is mostly opened for; never a multicast group
dests = sorted((x for x in r.get("destinations", []) if x.get("ip") and x.get("count")
                and not ipaddress.ip_address(x["ip"]).is_multicast),
               key=lambda x: not ipaddress.ip_address(x["ip"]).is_global)
if dests:
    found("address", dests[0]["ip"], f"a top destination, {dests[0]['count']:,} records")
else:
    missing("address", f"HTTP {status}, no destinations")

status, r, _ = get("/api/dns/top-domains", limit=20, **W)
names = [n for n in (canonical_name(x.get("domain")) for x in r.get("domains", [])) if n]
if names:
    found("domain", names[0], "the most looked-up host name")
else:
    missing("domain", f"HTTP {status}, no host names looked up")

status, r, _ = get("/api/traffic/categories", **W)
cats = sorted((c for c in r.get("categories", []) if c.get("total_bytes")),
              key=lambda c: (c["name"] == "other", -c["total_bytes"]))  # a named one before Other
if cats:
    found("traffic_category", cats[0]["name"], f"{cats[0]['total_bytes']:,} bytes")
else:
    missing("traffic_category", f"HTTP {status}, no category moved data")

status, r, _ = get("/api/alerts/categories", **W)
threat = [c for c in r.get("categories", []) if c.get("count")]
if threat:
    found("alert_category", threat[0]["id"], f"{threat[0]['count']:,} alerts")
else:
    missing("alert_category", f"HTTP {status}, no alerts in a category")

# The names a row links its Suricata category by (alerts.py rule_categories), among the latest 200
status, r, _ = get("/api/alerts", page=1, size=200, **W)
named = collections.Counter(n for a in r.get("alerts", []) for n in (a.get("alert") or {}).get("rule_category", []))
if named:
    name, n = named.most_common(1)[0]
    found("suricata_category", name, f"{n} of the latest {len(r.get('alerts', []))} alerts")
else:
    missing("suricata_category", f"HTTP {status}, no alert carries a rule.category")

status, r, _ = get("/api/iot/devices")
macs = [d["mac"] for d in r.get("devices", []) if d.get("mac")]
if macs:
    found("iot_mac", macs[0], f"the first of {len(macs)} IoT devices")
elif "device_mac" in S:  # the route counts any MAC's connections the same way
    found("iot_mac", S["device_mac"], "no IoT device is listed, so the busiest device's MAC")
else:
    missing("iot_mac", f"HTTP {status}, no IoT device listed and no device MAC")

# Every changed page, then the self-narrowing pages on a picked 5-minute slot (as a pick opens them)
pages = ["/alerts", "/logs", "/dns", "/connections", "/iot", "/pcap", "/packets", "/bandwidth"]
for kind, base in (("alert_category", "/alerts/{}"), ("suricata_category", "/alerts/suricata/{}"),
                   ("address", "/address/{}"), ("domain", "/domain/{}"),
                   ("traffic_category", "/traffic/{}"), ("device", "/devices/{}")):
    if kind in S:
        pages.append(base.format(seg(S[kind])))
slot = (E // STEP["5m"] - 1) * STEP["5m"]
picked = urllib.parse.urlencode({"from": at(slot), "to": at(slot + STEP["5m"] - 1), "range": "24h"})
pages.append("/dns?" + picked)
for kind, base in (("alert_category", "/alerts/{}"), ("domain", "/domain/{}"),
                   ("traffic_category", "/traffic/{}"), ("device", "/devices/{}")):
    if kind in S:
        pages.append(base.format(seg(S[kind])) + "?" + picked)
for page in pages:
    print("PAGE " + page)
print("SAMPLES " + base64.b64encode(json.dumps(S).encode()).decode())
PY
SAMPLES=$(printf '%s\n' "$LAST_OUT" | sed -n 's/^SAMPLES //p')
mapfile -t PAGES < <(printf '%s\n' "$LAST_OUT" | sed -n 's/^PAGE //p')
echo ""

echo "→ Step 6: Every time chart gives each range its bucket and slots, a fresh window in under 3 s..."
in_daemon <<PY
$COMMON
S = samples("$SAMPLES")

def problems(result, which, bucket, want, chart):
    status, r, slots, _ = result
    if slots is None:
        return [f"{which} read HTTP {status}"]
    found = [f"{which} read {len(slots)} slots"] if len(slots) != want else []
    if r.get(chart[4]) != bucket:
        found.append(f"{which} read echoed {chart[4]}={r.get(chart[4])!r}")
    if not has_window(r):
        found.append(f"{which} read echoed no from/to")
    if chart[1] == "iot_mac" and not isinstance(r.get("excluded_ips"), list):
        found.append(f"{which} read echoed no excluded_ips")
    return found

for chart in CHARTS:
    path = path_of(chart)
    if path is None:
        continue
    for name, span, bucket, want in RANGES:
        # the first read of this window after the recreate, then one no earlier read used (7 min
        # earlier), as a new click would be: only the second is held to 3 s
        first, fresh = (read(path, chart, end - span_ms(span), end, bucket) for end in (E, E - 420_000))
        found = problems(first, "first", bucket, want, chart) + problems(fresh, "fresh", bucket, want, chart)
        if fresh[3] >= 3:
            found.append(f"fresh window {fresh[3]:.2f} s")
        say(not found, f"{chart[0]} {name} @{bucket}",
            "; ".join(found) or f"{want} slots, {fresh[3]:.2f} s (first read after the recreate {first[3]:.2f} s)")

# Bandwidth's Daily usage (T10) picks by the day the reply echoes
status, r, secs = get("/api/bandwidth/daily", **window(E - 30 * DAY, E))
say(status == 200 and r.get("interval") == "1d" and has_window(r), "Daily usage echoes 1d and its window",
    f"HTTP {status}, {r.get('interval')!r}, {len(r.get('daily', []))} days, {secs:.2f} s")
PY
echo ""

echo "→ Step 7: A slot's figure is the total of the list its link opens (24 h, 5 min slots)..."
in_daemon <<PY
$COMMON
S = samples("$SAMPLES")

def either_side(ip):  # drilldown.ts logsHrefForIp
    return f'(source.ip:"{ip}" OR destination.ip:"{ip}")'

def iot_list(r, lo, hi):  # iot/+page.svelte pickActivity: its MAC in either case, the reply's exclusions
    mac = r["mac"].strip()
    params = {"log_type": "zeek.conn", "query": f'source.mac:"{mac.upper()}" OR source.mac:"{mac.lower()}"'}
    if r.get("excluded_ips"):
        params["exclude_src"] = ",".join(r["excluded_ips"])
    return logs_total(lo, hi, **params)

# What each counted chart's pick opens, asked of the daemon as that page asks it
TARGETS = (
    ("Alerts", "the Alerts list", lambda r, lo, hi: alerts_total(lo, hi)),
    ("Suricata category", "the Alerts list for the category",
     lambda r, lo, hi: alerts_total(lo, hi, suricata_category=S["suricata_category"])),
    ("Log Explorer", "Log Explorer (every type, no query)", lambda r, lo, hi: logs_total(lo, hi)),
    ("Connections", "Log Explorer conn records", lambda r, lo, hi: logs_total(lo, hi, log_type="zeek.conn")),
    ("Address", "Log Explorer conn records either side",
     lambda r, lo, hi: logs_total(lo, hi, log_type="zeek.conn", query=either_side(S["address"]))),
    ("IoT activity", "Log Explorer conn records from its MAC", iot_list),
)
name, span, bucket, _ = RANGES[2]
for label, target, opened in TARGETS:
    chart = CHART[label]
    path = path_of(chart)
    if path is None:
        continue
    status, r, slots, _ = read(path, chart, E - span_ms(span), E, bucket)
    step = chart_step(chart, r, slots)
    if step is None:
        say(False, f"{label} {name} chart", f"HTTP {status}, not pickable (bucket {r.get(chart[4])!r})")
        continue
    times = [t for t, _ in slots]
    for which, i in picks(slots):
        lo, hi = link_window(times, i, step, r)
        s2, total = opened(r, lo, hi)
        say(s2 == 200 and total == slots[i][1], f"{label}, {which} slot {at(lo)}..{at(hi)}",
            f"chart {slots[i][1]}, {target} {total}")
PY
echo ""

echo "→ Step 8: The pages that narrow themselves count the slot's figure over its window..."
in_daemon <<PY
$COMMON
S = samples("$SAMPLES")
name, span, bucket, _ = RANGES[2]
for label in ("Alert category", "DNS", "Domain", "Traffic category", "Device"):
    chart = CHART[label]
    path = path_of(chart)
    if path is None:
        continue
    status, r, slots, _ = read(path, chart, E - span_ms(span), E, bucket)
    step = chart_step(chart, r, slots)
    if step is None:
        say(False, f"{label} {name} chart", f"HTTP {status}, not pickable (bucket {r.get(chart[4])!r})")
        continue
    times = [t for t, _ in slots]
    for which, i in picks(slots):
        lo, hi = link_window(times, i, step, r)
        narrow = bucket_for(lo, hi)  # the page's Custom window picks its own bucket
        s2, _, narrowed, _ = read(path, chart, lo, hi, narrow)
        got = sum(v for _, v in narrowed) if narrowed is not None else None
        line = f"{label}, {which} slot {at(lo)}..{at(hi)}"
        detail = f"slot {slots[i][1]}, the page over that window {got} (@{narrow})"
        if label == "Device" and narrowed is not None:
            # expected to differ at times: the device's IPv6 addresses are worked out per window
            same = "the same" if got == slots[i][1] else "they differ (IPv6 ownership per window; the page says so)"
            print(f"     · {line}: {detail}, {same}")
        else:
            say(s2 == 200 and got == slots[i][1], line, detail)
PY
echo ""

echo "→ Step 9: An unknown bucket, and one too fine for the window, are refused..."
in_daemon <<PY
$COMMON
S = samples("$SAMPLES")
for chart in CHARTS:
    path = path_of(chart)
    if path is None:
        continue
    s1, _, _ = get(path, interval="42x", **window(E - DAY, E))
    say(s1 == 400, f"{chart[0]}: interval=42x", s1)
    s2, r2, _ = get(path, interval="1m", **window(E - 7 * DAY, E))
    say(s2 == 400 and r2.get("error") == TOO_MANY, f"{chart[0]}: 1m over 7 days", f"{s2} {r2.get('error')!r}")
PY
echo ""

echo "→ Step 10: The live connection drawer's history..."
in_daemon <<PY
$COMMON
status, dash, _ = get("/api/live/dashboard")
rows = [c for c in dash.get("connections", []) if c.get("source_ip") and c.get("dest_ip")]
if status != 200 or not rows:
    say(False, "a live connection to open", f"HTTP {status}, {len(rows)} rows")
    raise SystemExit
c = rows[0]  # live/+page.svelte openDrawer: the row's pair, port and located end
params = {"src": c["source_ip"], "dst": c["dest_ip"]}
if c.get("dest_port") is not None:
    params["port"] = c["dest_port"]
if c.get("geo_ip"):
    params["geo"] = c["geo_ip"]
print(f"     · the first live row: {c['source_ip']} to {c['dest_ip']} port {c.get('dest_port')}")
s1, _, first = get("/api/live/connection/detail", **params)
s2, d, secs = get("/api/live/connection/detail", **params)
say(s1 == 200 and s2 == 200 and secs < 3, "the drawer's detail answers in under 3 s",
    f"HTTP {s1}/{s2}, {secs:.2f} s (first read {first:.2f} s)")
h = d.get("history") or {}
timeline = h.get("timeline") or []
say(h.get("interval") == "5m", "history interval", h.get("interval"))
say(has_window(h), "history from/to", f"{h.get('from')} .. {h.get('to')}")
want_port = params.get("port") or None  # live_connections.py filters on a port only when it is set
say("port" in h and h["port"] == want_port, "history port is the one it filtered on", h.get("port"))
say(len(timeline) == 289, "history slots", f"{len(timeline)} (want 289: 5 min over 24 h)")

# A slot that ended 2 h before the history's end: the drawer's link lists its connections
if has_window(h) and timeline:
    settled = [i for i, p in enumerate(timeline)
               if ms(p["timestamp"]) + STEP["5m"] <= ms(h["to"]) - 2 * 3_600_000 and p.get("connections")]
    if settled:
        i = max(settled, key=lambda i: timeline[i]["connections"])
        lo, hi = link_window([p["timestamp"] for p in timeline], i, STEP["5m"], h)
        a, b = f'"{c["source_ip"]}"', f'"{c["dest_ip"]}"'  # LiveConnectionDrawerContent pickHistory
        query = f"((source.ip:{a} AND destination.ip:{b}) OR (source.ip:{b} AND destination.ip:{a}))"
        if isinstance(h.get("port"), int):
            query += f" AND destination.port:{h['port']}"
        s3, total = logs_total(lo, hi, log_type="zeek.conn", query=query)
        say(s3 == 200 and total == timeline[i]["connections"], f"a settled slot {at(lo)}..{at(hi)}",
            f"history {timeline[i]['connections']} connections, its Log Explorer link {total}")
    else:
        print("     · no slot that ended 2 h ago has connections for this pair; the link check is skipped")
PY
echo ""

echo "→ Step 11: Every changed page renders on a logged-in full reload through nginx..."
# A 60-second session per page, signed inside nettap-web with its own secret. It is never printed
# and never on a command line: printf is a shell builtin and curl reads the header from stdin.
MINT='const fs=require("fs"),jwt=require("jsonwebtoken");const d=process.env.DATA_DIR||"/var/lib/nettap-web";const s=process.env.JWT_SECRET||fs.readFileSync(d+"/jwt-secret.txt","utf8").trim();const u=JSON.parse(fs.readFileSync(d+"/users.json","utf8")).users[0].username;process.stdout.write(jwt.sign({username:u,role:"admin"},s,{expiresIn:60}))'
if [ "${#PAGES[@]}" -eq 0 ]; then
    check "the pages to load" 1 "step 5 listed none"
fi
for page in "${PAGES[@]}"; do
    SESSION=$(sudo docker exec -w /app nettap-web node -e "$MINT" 2>/dev/null)
    if [ -z "$SESSION" ]; then
        check "GET $page" 1 "could not sign a test session; open it in the browser instead"
        continue
    fi
    got=$(printf 'Cookie: nettap_token=%s\n' "$SESSION" | curl -sk -H @- -o /dev/null -w '%{http_code} %{size_download}' "https://localhost$page")
    case "$got" in 200\ *) rc=0 ;; *) rc=1 ;; esac
    check "GET $page" "$rc" "$got bytes"
done
unset SESSION
big=$(sudo docker logs --since "$RECREATED" nettap-nginx 2>&1 | grep -c 'upstream sent too big header')
expect "nginx cut off no page's headers since the recreate" "$big" 0
echo ""

echo "→ Step 12: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo "Open Alerts, DNS or a device, click a point on the chart, then drag across a few points."
