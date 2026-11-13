#!/usr/bin/env bash
# Deploy NET-249 slice 1 (click or drag the Home bandwidth chart to open that moment) and check
# it on the device's real data.
#
# Rebuilds the web UI and the daemon. Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-chart-drilldown-slice1.sh
# To test a branch first: BRANCH=<branch> bash …
#
# The figure checks use windows that ended 2 hours ago, so a connection logged after a figure
# was read (Zeek logs a connection when it ends) can't move it between two reads.
#
# Rollback: redeploy the previous main with this script's first three steps:
#   cd /home/nettap/NetTap && git checkout <previous-sha> && sudo docker compose -f docker/docker-compose.yml build nettap-web nettap-storage-daemon
#   sudo docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-web nettap-storage-daemon
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

in_daemon() {  # in_daemon < python: runs it in the daemon container; any "✗" line, or no output, fails
    local out
    out=$(sudo docker exec -i -w /opt/nettap/daemon nettap-storage-daemon python3 - 2>&1)
    echo "${out:-   ✗ no output}"
    case "$out" in *"✗ "*|"") FAILED=1 ;; esac
}

echo "=== Deploy: chart drill-down, slice 1 ($BRANCH) ==="
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

# One Python program per step, inside the daemon container. The token is read inside get(); it
# is never printed. Each program prints one "✓ …" or "✗ …" line per check.
COMMON='
import json, time, urllib.error, urllib.parse, urllib.request
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
    except urllib.error.HTTPError as e:
        return e.code, {}, time.monotonic() - t0
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
# Home ranges and their buckets (web/src/lib/utils/drilldown.ts DRILL_RANGES)
RANGES = (("1h", timedelta(hours=1), "1m", 61), ("6h", timedelta(hours=6), "5m", 73),
          ("24h", timedelta(hours=24), "5m", 289), ("7d", timedelta(days=7), "1h", 169),
          ("30d", timedelta(days=30), "3h", 241))
# Settled: ended 2 h ago. 37 s off the minute, so no range starts or ends on a slot edge
END = datetime.now(timezone.utc).replace(second=37, microsecond=0) - timedelta(hours=2)

def bucket_window(series, i, step, reply):
    """The page link for slot i: clipped to the reply, end inclusive at the slot end - 1 ms."""
    t = ms(series[i]["timestamp"])
    return max(t, ms(reply["from"])), min(t + step, ms(reply["to"]) + 1) - 1
'

echo "→ Step 5: Home's ranges give the expected slots, each in under 3 s..."
in_daemon <<PY
$COMMON
for name, span, bucket, want in RANGES:
    status, r, secs = get("/api/traffic/bandwidth", interval=bucket, **{"from": iso(END - span), "to": iso(END)})
    n = len(r.get("series", []))
    say(status == 200 and n == want and secs < 3, f"{name} @{bucket}", f"{n} slots (want {want}), {secs:.2f} s")
PY
echo ""

echo "→ Step 6: A slot's total and connections equal the summary over the slot's link window..."
in_daemon <<PY
$COMMON
def compare(label, series, i, step, reply):
    lo, hi = bucket_window(series, i, step, reply)
    status, s, _ = get("/api/traffic/summary", **{"from": at(lo), "to": at(hi)})
    p = series[i]
    got = (s.get("total_bytes"), s.get("connection_count"))
    want = (p["total_bytes"], p["connections"])
    say(status == 200 and got == want, f"{label} {at(lo)}..{at(hi)}", f"slot {want}, summary {got}")
    split = tuple(p.get(k) for k in ("download_bytes", "upload_bytes", "local_bytes"))
    narrow = tuple(s.get(k) for k in ("download_bytes", "upload_bytes", "local_bytes"))
    if status == 200 and got == want and split != narrow:
        print(f"     · down/up/local differ (IPv6 found as a gateway over the wider window): slot {split}, summary {narrow}")

for name, span, bucket, _ in RANGES:
    if name not in ("24h", "7d", "30d"):
        continue
    status, r, _ = get("/api/traffic/bandwidth", interval=bucket, **{"from": iso(END - span), "to": iso(END)})
    series = r.get("series", [])
    if status != 200 or len(series) < 4:
        say(False, f"{name} @{bucket} series", f"HTTP {status}, {len(series)} slots")
        continue
    busy = sorted(range(1, len(series) - 1), key=lambda i: -series[i]["total_bytes"])[:2]
    for i in busy:  # the two busiest whole slots
        compare(f"{name} slot {i}", series, i, STEP[bucket], r)
    if name == "24h":  # the clipped first and last slots
        compare("24h first slot (clipped)", series, 0, STEP[bucket], r)
        compare("24h last slot (clipped)", series, len(series) - 1, STEP[bucket], r)

# A range that ends on a slot edge: the last slot is one instant, from == to
edge = END.replace(second=0)
status, r, _ = get("/api/traffic/bandwidth", interval="1m", **{"from": iso(edge - timedelta(hours=1)), "to": iso(edge)})
series = r.get("series", [])
if status == 200 and series:
    lo, hi = bucket_window(series, len(series) - 1, STEP["1m"], r)
    say(lo == hi, "1h @1m trailing slot is one instant", f"{at(lo)}..{at(hi)}")
    compare("1h trailing slot", series, len(series) - 1, STEP["1m"], r)
else:
    say(False, "1h @1m series", f"HTTP {status}")
PY
echo ""

echo "→ Step 7: The moment's top devices match the Devices list for the same window..."
in_daemon <<PY
$COMMON
for label, span in (("5 min", timedelta(minutes=5)), ("1 hour", timedelta(hours=1))):
    win = {"from": iso(END - span), "to": iso(END)}
    s1, m, t1 = get("/api/moment/devices", limit=10, **win)
    s2, d, t2 = get("/api/devices", sort="bytes", order="desc", limit=10, **win)
    mine = [(x["ip"], x["total_bytes"]) for x in m.get("devices", [])]
    theirs = [(x["ip"], x["total_bytes"]) for x in d.get("devices", [])]
    # the same figures in the same order; two devices with equal bytes may swap places
    same = [b for _, b in mine] == [b for _, b in theirs] and dict(mine) == {ip: b for ip, b in theirs if ip in dict(mine)}
    say(s1 == 200 and s2 == 200 and same, f"{label}: top {len(mine)} devices and bytes", f"{t1:.2f} s vs {t2:.2f} s")
    if not same:
        print(f"     moment {mine[:5]}\n     devices {theirs[:5]}")
    say(isinstance(m.get("total_devices"), int) and m.get("total_devices", -1) >= len(mine),
        f"{label}: total_devices", m.get("total_devices"))
    # Step 7b: what each device talked to never adds up to more than the device moved
    worst = []
    for x in m.get("devices", []):
        for key in ("destinations", "apps"):
            over = [e for e in x.get(key, []) if e["bytes"] > x["total_bytes"]]
            worst += [(x["ip"], key, e) for e in over]
    say(not worst, f"{label}: no destination or app exceeds its device's total", worst[:3] or "")
s3, _, _ = get("/api/moment/devices", limit=26, **{"from": iso(END - timedelta(hours=1)), "to": iso(END)})
say(s3 == 400, "limit=26 is refused", s3)
PY
echo ""

echo "→ Step 8: Every protocol bar's count is what its Log Explorer link lists..."
in_daemon <<PY
$COMMON
win = {"from": iso(END - timedelta(hours=1)), "to": iso(END)}
status, p, _ = get("/api/traffic/protocols", **win)
excluded = p.get("excluded_ips")
say(status == 200 and isinstance(excluded, list), "protocols reports excluded_ips", excluded)
def link_query(name):  # web/src/lib/utils/drilldown.ts serviceLogsHref
    if name == "ssl":
        return 'network.protocol:"ssl" AND NOT network.protocol:"quic"'
    if name == "unknown":
        return "NOT _exists_:network.protocol"
    return f'network.protocol:"{name}"'
for bar in p.get("services", []):
    params = {"log_type": "zeek.conn", "query": link_query(bar["name"]), "size": 1, **win}
    if excluded:
        params["exclude_src"] = ",".join(excluded)
    s2, found, _ = get("/api/logs/search", **params)
    say(s2 == 200 and found.get("total") == bar["count"], f"{bar['name']}: bar {bar['count']}, list", found.get("total"))
PY
echo ""

echo "→ Step 9: Every request the moment page makes answers in under 3 s on a fresh window..."
in_daemon <<PY
$COMMON
# The moment page's daemon reads, beside the chart (web/src/routes/moment/+page.svelte load)
CALLS = (("/api/traffic/summary", {}), ("/api/alerts/count", {}), ("/api/devices/count", {}),
         ("/api/moment/devices", {}), ("/api/traffic/protocols", {}),
         ("/api/traffic/categories", {}),
         ("/api/alerts", {"size": 10, "sort": "severity", "order": "desc"}),
         ("/api/changelog", {"type": "device_joined", "limit": 50}))
# OLD CODE START — first G11 run (2026-11-13): the first read of a window size right after the
# recreate took 3.7 s for /api/moment/devices over 24 h (OpenSearch reading those days from
# disk); any later window over the same days took 0.3-1.5 s. Timing only that read failed
# every deploy, so it is now reported and a second, fresh window is held to 3 s.
# for label, span, bucket in (("5 min", timedelta(minutes=5), "1m"), ("1 hour", timedelta(hours=1), "1m"),
#                             ("24 hours", timedelta(hours=24), "5m")):  # drilldown.ts bucketFor
#     win = {"from": iso(END - span), "to": iso(END)}
#     slow = []
#     for path, extra in CALLS + (("/api/traffic/bandwidth", {"interval": bucket}),):
#         status, _, secs = get(path, **extra, **win)
#         if status != 200 or secs >= 3:
#             slow.append(f"{path} {status} {secs:.2f} s")
#     say(not slow, f"{label}: {len(CALLS) + 1} reads", "; ".join(slow))
# OLD CODE END
def reads(span, bucket, end):
    """[(seconds, path, status)] of every read the page makes for the window ending at end."""
    win = {"from": iso(end - span), "to": iso(end)}
    out = []
    for path, extra in CALLS + (("/api/traffic/bandwidth", {"interval": bucket}),):
        status, _, secs = get(path, **extra, **win)
        out.append((secs, path, status))
    return out

for label, span, bucket in (("5 min", timedelta(minutes=5), "1m"), ("1 hour", timedelta(hours=1), "1m"),
                            ("24 hours", timedelta(hours=24), "5m")):  # drilldown.ts bucketFor
    first = reads(span, bucket, END)
    secs, path, _ = max(first)
    print(f"     · {label}, first read after the recreate: slowest {path} {secs:.2f} s")
    # a window no earlier read used (7 minutes earlier), as a new click would be
    later = reads(span, bucket, END - timedelta(minutes=7))
    slow = [f"{p} {s} {t:.2f} s" for t, p, s in first + later if s != 200] + \
           [f"{p} {t:.2f} s" for t, p, s in later if s == 200 and t >= 3]
    say(not slow, f"{label}: {len(CALLS) + 1} reads on a fresh window, each under 3 s",
        "; ".join(slow) or f"slowest {max(later)[1]} {max(later)[0]:.2f} s")
PY
echo ""

echo "→ Step 10: The moment page renders on a logged-in full reload through nginx..."
# A 60-second session, signed inside nettap-web with its own secret. It is never printed and
# never on a command line: printf is a shell builtin and curl reads the header from stdin.
MINT='const fs=require("fs"),jwt=require("jsonwebtoken");const d=process.env.DATA_DIR||"/var/lib/nettap-web";const s=process.env.JWT_SECRET||fs.readFileSync(d+"/jwt-secret.txt","utf8").trim();const u=JSON.parse(fs.readFileSync(d+"/users.json","utf8")).users[0].username;process.stdout.write(jwt.sign({username:u,role:"admin"},s,{expiresIn:60}))'
SESSION=$(sudo docker exec -w /app nettap-web node -e "$MINT" 2>/dev/null)
if [ -z "$SESSION" ]; then
    check "a test session" 1 "could not sign one; open /moment in the browser instead"
else
    M_FROM=$(date -u -d '125 minutes ago' +%Y-%m-%dT%H:%M:00.000Z)
    M_TO=$(date -u -d '120 minutes ago' +%Y-%m-%dT%H:%M:59.999Z)
    for page in "/" "/moment?from=$M_FROM&to=$M_TO&range=24h"; do
        got=$(printf 'Cookie: nettap_token=%s\n' "$SESSION" | curl -sk -H @- -o /dev/null -w '%{http_code} %{size_download}' "https://localhost$page")
        case "$got" in 200\ *) rc=0 ;; *) rc=1 ;; esac
        check "GET $page" "$rc" "$got bytes"
    done
    unset SESSION
fi
got=$(curl -sk -o /dev/null -w '%{http_code} %{redirect_url}' "https://localhost/moment")
case "$got" in "302 https://localhost/login"*) rc=0 ;; *) rc=1 ;; esac
check "/moment without a session goes to sign-in" "$rc" "$got"
big=$(sudo docker logs --since "$RECREATED" nettap-nginx 2>&1 | grep -c 'upstream sent too big header')
expect "nginx cut off no page's headers since the recreate" "$big" 0
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo "Open Home, click a point on the bandwidth chart, then drag across a few points."
