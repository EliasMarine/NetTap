#!/usr/bin/env bash
# Deploy NET-340 (roadmap #1, the weekly report) and check it on the box:
#   - memory before, during and after one real "Generate now" (the roadmap's stop rule);
#   - the report's traffic equals /api/usage/daily and its alert totals equal /api/alerts/count,
#     exactly, for the same dates;
#   - history lists the report, its file is mode 600, and deleting the schedule removes it.
# The check uses a throwaway schedule ("deploy-check") with no recipients, so it emails no one;
# a trap deletes it on every exit path. Rebuilds and recreates only nettap-storage-daemon and
# nettap-web. Daemon calls run inside the daemon container, so the token never leaves it.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-weekly-report.sh
# To try a branch before it merges: BRANCH=feature/weekly-report bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
RECORD="/home/nettap/.nettap-rollback-net340"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
SERVICES=(nettap-storage-daemon nettap-web)
OPENSEARCH="nettap-opensearch"
REPORT_COPY="/tmp/nettap-deploy-check-report.json"   # inside the daemon container
FAILED=0
PENDING=0
SCHEDULE_ID=""

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

result() {  # result LABEL OUTPUT  (OUTPUT starting with OK passes)
    local rc
    case "$2" in OK*) rc=0 ;; *) rc=1 ;; esac
    check "$1" "$rc" "$2"
}

# Run a Python check inside the daemon container with the shared token as `call(method, path, body)`.
daemon_py() {  # daemon_py PYTHON_SNIPPET [SCHEDULE_ID]
    sudo docker exec -e SNIPPET="$1" -e SID="${2:-}" -e COPY="$REPORT_COPY" nettap-storage-daemon python3 -c '
import json, os, time, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
token = open("/run/nettap-auth/daemon-token").read().strip()
SID = os.environ["SID"]
COPY = os.environ["COPY"]
def call(method, path, body=None, timeout=120):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request("http://localhost:8880" + path, data=data, method=method,
                                 headers={"X-NetTap-Daemon-Token": token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
try:
    exec(os.environ["SNIPPET"])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])' 2>/dev/null || echo "FAIL could not run inside the daemon container"
}

daemon_rss_mb() {  # the daemon process's resident memory, in MB (the deploy-usage-ledger.sh sampler)
    sudo docker top nettap-storage-daemon -o pid,rss,args 2>/dev/null | awk '$3 ~ /python/ && / main\.py/ { if ($2 > m) m = $2 } END { printf "%d", m / 1024 }'
}

daemon_uptime_s() {
    local started
    started=$(sudo docker inspect -f '{{.State.StartedAt}}' nettap-storage-daemon 2>/dev/null)
    echo $(( $(date +%s) - $(date -d "$started" +%s 2>/dev/null || date +%s) ))
}

settled_rss_mb() {  # wait until VmRSS moves under 10% across a minute (at most 5 minutes)
    local prev now i
    # A fresh daemon holds about 1.2 GB for its first minutes (F1 and F4 deploys), so it is
    # read only once it has run 5 minutes.
    while [ "$(daemon_uptime_s)" -lt 300 ]; do sleep 15; done
    prev=$(daemon_rss_mb)
    for i in 1 2 3 4 5; do
        sleep 60
        now=$(daemon_rss_mb)
        if [ -n "$prev" ] && [ -n "$now" ] && [ $(( (now > prev ? now - prev : prev - now) * 10 )) -le "$prev" ]; then
            echo "$now"; return
        fi
        prev=$now
    done
    echo "${now:-0}"
}

anon_mb() {  # anon_mb NAME -> the container's anonymous memory in MB, from its cgroup
    sudo docker exec "$1" sh -c 'cat /sys/fs/cgroup/memory.stat' 2>/dev/null | awk '/^anon / { printf "%d", $2 / 1048576 }'
}

swap_mb() { free -m | awk '/^Swap:/ {print $3}'; }

health_ms() {  # one GET /api/health (no token needed), in whole milliseconds
    curl -s -o /dev/null -m 10 -w '%{time_total}' http://localhost:8880/api/health 2>/dev/null | awk '{ printf "%d", $1 * 1000 }'
}

cleanup() {  # delete the throwaway schedule on every exit path
    if [ -n "$SCHEDULE_ID" ]; then
        daemon_py '
s, _ = call("DELETE", "/api/reports/schedules/" + SID)
print("deleted" if s in (200, 204, 404) else f"left behind (HTTP {s})")' "$SCHEDULE_ID" | sed 's/^/   cleanup: deploy-check schedule /'
        sudo docker exec nettap-storage-daemon rm -f "$REPORT_COPY" 2>/dev/null
        SCHEDULE_ID=""
    fi
}
trap cleanup EXIT

echo "=== Deploy: weekly report, NET-340 ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
TARGET=$(git rev-parse HEAD)
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Memory before anything changes..."
free -m
BEFORE_RSS=$(daemon_rss_mb)
BEFORE_ANON=$(anon_mb "$OPENSEARCH")
echo "   daemon VmRSS ${BEFORE_RSS} MB (running image) · OpenSearch anon ${BEFORE_ANON} MB · swap used $(swap_mb) MB"
echo ""

echo "→ Step 3: Record the running images for a rollback..."
if [ -s "$RECORD" ]; then
    REC_DAEMON=$(sed -n 's/^daemon=//p' "$RECORD")
    REC_WEB=$(sed -n 's/^web=//p' "$RECORD")
    TAG_DAEMON=$(sudo docker image inspect -f '{{.Id}}' nettap/storage-daemon:rollback-net340 2>/dev/null)
    TAG_WEB=$(sudo docker image inspect -f '{{.Id}}' nettap/web:rollback-net340 2>/dev/null)
    if [ "$TAG_DAEMON" != "$REC_DAEMON" ] || [ "$TAG_WEB" != "$REC_WEB" ]; then
        echo "   ✗ The :rollback-net340 tags no longer point at the images in $RECORD — nothing was changed"
        exit 1
    fi
    echo "   ✓ Keeping the existing record in $RECORD (tags still match)"
else
    DAEMON_IMAGE=$(sudo docker inspect -f '{{.Image}}' nettap-storage-daemon 2>/dev/null)
    WEB_IMAGE=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
    if [ -z "$DAEMON_IMAGE" ] || [ -z "$WEB_IMAGE" ]; then
        echo "   ✗ Couldn't read the running images — nothing was changed"
        exit 1
    fi
    if ! sudo docker tag "$DAEMON_IMAGE" nettap/storage-daemon:rollback-net340 \
        || ! sudo docker tag "$WEB_IMAGE" nettap/web:rollback-net340; then
        echo "   ✗ Couldn't tag the running images — nothing was changed"
        exit 1
    fi
    printf 'target=%s\ndaemon=%s\nweb=%s\nrecorded=%s\n' "$TARGET" "$DAEMON_IMAGE" "$WEB_IMAGE" "$(date -u +%FT%TZ)" > "$RECORD"
    echo "   ✓ Tagged both as :rollback-net340 and wrote $RECORD"
fi
echo ""

echo "→ Step 4: Build and recreate the daemon and web..."
if ! "${COMPOSE[@]}" build "${SERVICES[@]}"; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate "${SERVICES[@]}"; then
    echo "   ✗ docker compose up failed"
    exit 1
fi
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
check "Both containers healthy" "$([ "$WEB_STATUS" = healthy ] && [ "$DAEMON_STATUS" = healthy ] && echo 0 || echo 1)" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
[ "$FAILED" -eq 0 ] || exit 1
echo "   Waiting for the new daemon's memory to settle (5 minutes or more)..."
BASE_RSS=$(settled_rss_mb)
BASE_SWAP=$(swap_mb)
echo "   ✓ Settled: daemon VmRSS ${BASE_RSS} MB · OpenSearch anon $(anon_mb "$OPENSEARCH") MB · swap used ${BASE_SWAP} MB"
echo ""

echo "→ Step 5: @timestamp is a millisecond date in every network index..."
MAPPING=$(sudo docker exec "$OPENSEARCH" sh -c "curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --cacert /usr/share/opensearch/config/certs/ca.crt --insecure 'https://localhost:9200/arkime_sessions3-*/_mapping/field/@timestamp' | python3 -c '
import json, sys
m = json.load(sys.stdin)
types = {f[\"mapping\"][\"@timestamp\"][\"type\"] for i in m.values() for f in [i[\"mappings\"][\"@timestamp\"]]}
print((\"OK \" if types == {\"date\"} else \"FAIL \") + \",\".join(sorted(types)) + f\" in {len(m)} indices\")'" 2>/dev/null)
result "@timestamp mapping" "${MAPPING:-FAIL no reply from OpenSearch}"
echo ""

echo "→ Step 6: Create the throwaway schedule (weekly, today, 00:00, no recipients)..."
CREATED=$(daemon_py '
s, b = call("POST", "/api/reports/schedules", {"name": "deploy-check", "frequency": "weekly", "weekday": 0, "hour": 0, "recipients": [], "enabled": False})
if s != 201:
    print(f"FAIL HTTP {s}: {b}")
else:
    wd = datetime.now(ZoneInfo(b["tz"])).weekday()
    s2, b2 = call("PUT", "/api/reports/schedules/" + b["id"], {"weekday": wd, "rev": b["rev"]})
    sid, tzn = b["id"], b["tz"]
    print(f"OK {sid} weekday={wd} tz={tzn}" if s2 == 200 else f"FAIL HTTP {s2} on the weekday PUT: {b2} id={sid}")')
case "$CREATED" in
    OK*) SCHEDULE_ID=$(echo "$CREATED" | awk '{print $2}') ;;
    *) SCHEDULE_ID=$(echo "$CREATED" | sed -n 's/.*id=\([0-9a-f-]*\).*/\1/p') ;;
esac
result "deploy-check schedule" "$CREATED"
[ "$FAILED" -eq 0 ] || exit 1
echo ""

echo "→ Step 7: Generate now, sampling memory, swap and /api/health every 2 s..."
GEN_OUT=$(mktemp)
daemon_py '
t0 = time.monotonic()
s, b = call("POST", "/api/reports/generate/" + SID, {}, timeout=90)
took = time.monotonic() - t0
if s != 200:
    print(f"FAIL HTTP {s} after {took:.1f} s: {b}")
else:
    json.dump(b, open(COPY, "w"))
    a = b["sections"]["alerts"]
    days = a.get("days") or []
    last = b["period"]["last"]
    ylast = next((d["count"] for d in days if d["date"] == last), 0)
    worst = "complete" if a.get("worst") is not None else "missing"
    rid, first = b["id"], b["period"]["first"]
    print(f"OK took={took:.1f} id={rid} first={first} last={last} days={len(days)} last_day_alerts={ylast} worst={worst}")' "$SCHEDULE_ID" > "$GEN_OUT" &
GEN_PID=$!
PEAK_RSS=0; PEAK_ANON=0; PEAK_SWAP=0; PEAK_HEALTH=0
while kill -0 "$GEN_PID" 2>/dev/null; do
    R=$(daemon_rss_mb); A=$(anon_mb "$OPENSEARCH"); S=$(swap_mb); H=$(health_ms)
    [ "${R:-0}" -gt "$PEAK_RSS" ] && PEAK_RSS=$R
    [ "${A:-0}" -gt "$PEAK_ANON" ] && PEAK_ANON=$A
    [ "${S:-0}" -gt "$PEAK_SWAP" ] && PEAK_SWAP=$S
    [ "${H:-0}" -gt "$PEAK_HEALTH" ] && PEAK_HEALTH=$H
    sleep 2
done
wait "$GEN_PID"
GEN=$(cat "$GEN_OUT"); rm -f "$GEN_OUT"
echo "   $GEN"
echo "   peaks: daemon VmRSS ${PEAK_RSS} MB · OpenSearch anon ${PEAK_ANON} MB · swap used ${PEAK_SWAP} MB · /api/health ${PEAK_HEALTH} ms"
result "Generate now answered" "$GEN"
[ "$FAILED" -eq 0 ] || exit 1
REPORT_ID=$(echo "$GEN" | sed -n 's/.* id=\([^ ]*\).*/\1/p')
TOOK=$(echo "$GEN" | sed -n 's/.* took=\([0-9.]*\).*/\1/p')
echo ""

echo "→ Step 8: The stop rule (any ✗ here: stop and review before release)..."
check "Took under 30 s" "$(awk -v t="$TOOK" 'BEGIN { exit !(t < 30) }' && echo 0 || echo 1)" "${TOOK} s"
check "/api/health stayed under 2 s" "$([ "$PEAK_HEALTH" -le 2000 ] && echo 0 || echo 1)" "peak ${PEAK_HEALTH} ms"
check "The worst five completed" "$(echo "$GEN" | grep -q 'worst=complete' && echo 0 || echo 1)"
sleep 60
AFTER_RSS=$(daemon_rss_mb)
check "Daemon VmRSS within 50 MB of settled, 60 s after" "$([ $(( AFTER_RSS - BASE_RSS )) -le 50 ] && echo 0 || echo 1)" "${BASE_RSS} → ${AFTER_RSS} MB"
check "Swap used rose by 16 MB or less" "$([ $(( PEAK_SWAP - BASE_SWAP )) -le 16 ] && echo 0 || echo 1)" "${BASE_SWAP} → peak ${PEAK_SWAP} MB"
REP=$(daemon_py '
b = json.load(open(COPY))
tz = ZoneInfo(b["period"]["tz"])
yesterday = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
days = b["sections"]["alerts"].get("days") or []
last_count = next((d["count"] for d in days if d["date"] == yesterday), 0)
ok = b["period"]["last"] == yesterday and len(days) == 7 and last_count > 0
last = b["period"]["last"]
print(("OK" if ok else "PENDING") + f" last={last} (yesterday {yesterday}), {len(days)} day rows, {last_count} alerts yesterday")')
case "$REP" in
    OK*) echo "   ✓ Representative data: $REP" ;;
    *) echo "   … Unverified, no representative data: $REP"; PENDING=1 ;;
esac
echo ""

echo "→ Step 9: Parity with the pages' own figures..."
PARITY=$(daemon_py '
b = json.load(open(COPY))
p, t, a = b["period"], b["sections"]["traffic"], b["sections"]["alerts"]
s, u = call("GET", "/api/usage/daily?" + urllib.parse.urlencode({"from": p["first"], "to": p["last"]}))
usage = u["bytes"]["total"] if s == 200 else None
end = datetime.fromisoformat(p["end"].replace("Z", "+00:00")) - timedelta(milliseconds=1)
to = end.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
frm = datetime.fromisoformat(p["start"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
s2, reply = call("GET", "/api/alerts/count?" + urllib.parse.urlencode({"from": frm, "to": to, "activity": "false"}))
# OLD CODE: read total/high/medium/low from the top level; the endpoint nests them under "counts"
c = reply.get("counts", {}) if s2 == 200 and isinstance(reply, dict) else {}
sev = a.get("by_severity") or {}
same_sev = s2 == 200 and (sev.get("1", 0), sev.get("2", 0), sev.get("3", 0)) == (c.get("high", 0), c.get("medium", 0), c.get("low", 0))
traffic_ok = usage is not None and usage == t["total"]
alerts_ok = s2 == 200 and c.get("total") == a["total"] and same_sev
report_total, alert_total = t["total"], a["total"]
count_total = c.get("total") if s2 == 200 else s2
print(("OK" if traffic_ok and alerts_ok else "FAIL") + f" traffic {report_total} vs /api/usage/daily {usage}; alerts {alert_total} vs /api/alerts/count {count_total}; severities match={same_sev}")')
result "Traffic and alert totals match exactly" "$PARITY"
echo ""

echo "→ Step 10: History lists the report and its file is mode 600..."
HIST=$(daemon_py '
s, h = call("GET", "/api/reports/history?" + urllib.parse.urlencode({"schedule": SID}))
rid = json.load(open(COPY))["id"]
listed = s == 200 and any(r["id"] == rid for r in h.get("reports", []))
import glob, stat
files = glob.glob(f"/opt/nettap/data/reports/{SID}/{rid}.json")
mode = oct(stat.S_IMODE(os.stat(files[0]).st_mode)) if files else "missing"
print(("OK" if listed and mode == "0o600" else "FAIL") + f" listed={listed} mode={mode}")' "$SCHEDULE_ID")
result "History and file mode" "$HIST"
echo ""

echo "→ Step 11: Email..."
echo "   … report email: unverified on device (the check emails no one)"
echo ""

echo "→ Step 12: Delete the throwaway schedule..."
GONE=$(daemon_py '
s, _ = call("DELETE", "/api/reports/schedules/" + SID)
gone = not os.path.exists(f"/opt/nettap/data/reports/{SID}")
print(("OK" if s in (200, 204) and gone else "FAIL") + f" HTTP {s}, directory gone={gone}")' "$SCHEDULE_ID")
result "Schedule and its reports deleted" "$GONE"
case "$GONE" in OK*) SCHEDULE_ID="" ; sudo docker exec nettap-storage-daemon rm -f "$REPORT_COPY" 2>/dev/null ;; esac
echo ""

echo "→ Step 13: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -ne 0 ]; then
    echo "=== Deploy finished with failures (✗ above): stop and review. Roll back with: bash scripts/remote/rollback-weekly-report.sh ==="
    exit 1
fi
if [ "$PENDING" -ne 0 ]; then
    echo "=== Deploy complete; every check passed, but release verification stays pending (no representative data) ==="
    exit 0
fi
echo "=== Deploy complete: every check passed (report $REPORT_ID) ==="
