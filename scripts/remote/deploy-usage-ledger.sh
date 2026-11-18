#!/usr/bin/env bash
# Deploy NET-329 (roadmap F4, the durable usage ledger) and check it on the box:
#   - a real full sweep of every stored day, forced with POST /api/usage/recount, watched for
#     host swap, OpenSearch memory and API latency (the roadmap's stop rule);
#   - yesterday's ledger total equals a fresh raw count of the same day;
#   - a repeat run, a daemon restart and another run change no settled total;
#   - the ledger file's size, `since` and gaps, and the daemon's settled memory.
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and figures, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-usage-ledger.sh
# To try a branch before it merges: BRANCH=feature/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
OPENSEARCH="nettap-opensearch"
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

# Run a Python check inside the daemon container with the shared token as `call(method, path, body)`.
daemon_py() {  # daemon_py PYTHON_SNIPPET
    sudo docker exec -e SNIPPET="$1" nettap-storage-daemon python3 -c '
import json, os, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
token = open("/run/nettap-auth/daemon-token").read().strip()
def call(method, path, body=None):
    data = None if body is None else body.encode()
    req = urllib.request.Request("http://localhost:8880" + path, data=data, method=method,
                                 headers={"X-NetTap-Daemon-Token": token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
try:
    exec(os.environ["SNIPPET"])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])' 2>/dev/null || echo "FAIL could not run inside the daemon container"
}

result() {  # result LABEL OUTPUT  (OUTPUT starting with OK passes)
    local rc
    case "$2" in OK*) rc=0 ;; *) rc=1 ;; esac
    check "$1" "$rc" "$2"
}

daemon_rss_mb() {  # the daemon process's resident memory, in MB (not docker stats: F1 lesson)
    # OLD CODE: the first /proc entry whose cmdline held "main.py". The daemon shares the host's
    # PID namespace, so that was this script's own `sh -c` (6 MB), not the daemon.
    # sudo docker exec nettap-storage-daemon sh -c 'for p in /proc/[0-9]*; do if grep -q main.py "$p/cmdline" 2>/dev/null; then awk "/^VmRSS:/ {print int(\$2/1024)}" "$p/status"; break; fi; done' 2>/dev/null
    sudo docker top nettap-storage-daemon -o pid,rss,args 2>/dev/null | awk '$3 ~ /python/ && / main\.py/ { if ($2 > m) m = $2 } END { printf "%d", m / 1024 }'
}

daemon_uptime_s() {
    local started
    started=$(sudo docker inspect -f '{{.State.StartedAt}}' nettap-storage-daemon 2>/dev/null)
    echo $(( $(date +%s) - $(date -d "$started" +%s 2>/dev/null || date +%s) ))
}

settled_rss_mb() {  # wait until VmRSS moves under 10% across a minute (at most 5 minutes)
    local prev now i
    # Start-up holds about 1.2 GB for its first minutes (F1 and F4 deploys), steady across a
    # minute, so a fresh daemon is read only once it has run 5 minutes.
    # OLD CODE: no wait (step 9 read 1,202 MB right after step 8's restart; 364 MB at 3 min)
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

container_mb() {  # container_mb NAME -> memory in MB from docker stats
    sudo docker stats --no-stream --format '{{.MemUsage}}' "$1" 2>/dev/null | awk '{
        v=$1; u=v; gsub(/[0-9.]/, "", u); gsub(/[A-Za-z]/, "", v);
        if (u=="GiB") v*=1024; else if (u=="KiB") v/=1024; printf "%d", v }'
}

anon_mb() {  # anon_mb NAME -> the container's anonymous memory in MB, from its cgroup
    # docker stats also counts active file cache: index pages a query just read, which the
    # kernel reclaims under pressure. The heap and other process memory are `anon`.
    sudo docker exec "$1" sh -c 'cat /sys/fs/cgroup/memory.stat' 2>/dev/null | awk '/^anon / { printf "%d", $2 / 1048576 }'
}

swap_mb() { free -m | awk '/^Swap:/ {print $3}'; }

latency_ms() {  # one GET /api/bandwidth/daily for yesterday, timed inside the daemon container
    daemon_py "
y = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
t = time.monotonic()
status, _ = call('GET', '/api/bandwidth/daily?from=' + y + 'T00:00:00Z&to=' + y + 'T23:59:59.999Z')
print(int((time.monotonic() - t) * 1000) if status == 200 else 999999)"
}

echo "=== Deploy: durable usage ledger (NET-329, $BRANCH) ==="
echo ""

echo "→ Step 1: Baseline (settled daemon memory, swap, OpenSearch, latency)..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
free -m | sed -n 1,3p
DAEMON_RSS_BEFORE=$(settled_rss_mb)
SWAP_BEFORE=$(swap_mb)
# OLD CODE: OS_BEFORE=$(container_mb "$OPENSEARCH") (docker stats counts reclaimable file cache)
OS_BEFORE=$(anon_mb "$OPENSEARCH")
LAT_BEFORE=$(latency_ms)
echo "   daemon VmRSS ${DAEMON_RSS_BEFORE} MB (settled), swap ${SWAP_BEFORE} MB, opensearch anon ${OS_BEFORE:-?} MB, /api/bandwidth/daily ${LAT_BEFORE} ms"
echo ""

echo "→ Step 2: Update the code..."
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Build the daemon and web containers..."
# A failed build must stop here: recreating would bring back the OLD images unnoticed.
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 4: Recreate the daemon and web containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 5: Wait for both to become healthy..."
WEB="unknown"; DAEMON="unknown"
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$WEB" = "healthy" ] && [ "$DAEMON" = "healthy" ] && break
    echo "   waiting... web=$WEB daemon=$DAEMON ($i/30)"
    sleep 5
done
if [ "$WEB" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$WEB"
if [ "$DAEMON" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-storage-daemon health" "$rc" "$DAEMON"
echo ""

echo "→ Step 6: A real sweep of every stored day, watched (at most 6 runs)..."
SWEEP_BEFORE=$(daemon_py "
s, b = call('GET', '/api/usage/month')
print(json.loads(b)['sweep']['id'] if s == 200 else 'FAIL')")
REQ_AT=$(daemon_py "print(datetime.now(timezone.utc).isoformat())")
REQ=$(daemon_py "
s, b = call('POST', '/api/usage/recount')
print('OK' if s == 202 else 'FAIL', s)")
result "recount requested" "$REQ"
# A request while a sweep is under way doesn't restart it: done = a sweep finished after the
# request (that one, or a new one), checked by finished_at, not by a new sweep id.
# OLD CODE: done = a new sweep id with no cursor (a running sweep kept its id, so it never matched)
SWAP_PEAK=$SWAP_BEFORE; OS_PEAK=${OS_BEFORE:-0}; LAT_PEAK=$LAT_BEFORE; RUNS=1; DONE=""
for i in $(seq 1 360); do  # 5 s steps, 30 minutes at most
    sleep 5
    S=$(swap_mb); [ "$S" -gt "$SWAP_PEAK" ] && SWAP_PEAK=$S
    # OLD CODE: O=$(container_mb "$OPENSEARCH")
    O=$(anon_mb "$OPENSEARCH"); [ -n "$O" ] && [ "$O" -gt "$OS_PEAK" ] && OS_PEAK=$O
    if [ $((i % 6)) -eq 0 ]; then L=$(latency_ms); [ "$L" -gt "$LAT_PEAK" ] && LAT_PEAK=$L; fi
    STATE=$(daemon_py "
s, b = call('GET', '/api/usage/month')
sw = json.loads(b)['sweep'] if s == 200 else {}
_, jb = call('GET', '/api/jobs')
job = next((j for j in json.loads(jb)['jobs'] if j['name'] == 'usage-ledger'), {})
fin = sw.get('finished_at')
after = bool(fin) and datetime.fromisoformat(fin) > datetime.fromisoformat('$REQ_AT')
print(sw.get('id'), sw.get('cursor') or '-', sw.get('chunks_done'), sw.get('chunks_failed'), 'running' if job.get('running') else 'idle', 'after' if after else 'before')")
    read -r SID CURSOR CHUNKS FAILS RUNNING FINISHED <<< "$STATE"
    if [ "$FINISHED" = "after" ] && [ "$CURSOR" = "-" ] && [ "$RUNNING" = "idle" ]; then DONE=1; break; fi
    if [ "$CURSOR" != "-" ] && [ "$RUNNING" = "idle" ] && [ "$RUNS" -lt 6 ]; then
        daemon_py "call('POST', '/api/jobs/usage-ledger/run')" >/dev/null
        RUNS=$((RUNS + 1))
        echo "   sweep continues: cursor $CURSOR, chunks $CHUNKS, run $RUNS/6"
    fi
done
if [ -n "$DONE" ]; then rc=0; else rc=1; fi
check "the sweep finished within 6 runs" "$rc" "sweep ${SWEEP_BEFORE} -> ${SID}, runs ${RUNS}, chunks ${CHUNKS}, failed ${FAILS}"
if [ "${FAILS:-1}" = "0" ]; then rc=0; else rc=1; fi
check "no chunk failed" "$rc" "chunks_failed ${FAILS}"
EXPECTED=$(daemon_py "
s, b = call('GET', '/api/usage/month')
since = json.loads(b)['since']
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
s, b = call('GET', '/api/usage/daily?from=' + since + '&to=' + today)
days = [d for d in json.loads(b)['days'] if d['status'] not in ('not_counted', 'future')]
print(max(1, -(-len(days) // 7)))")
if [ "${CHUNKS:-0}" -ge "${EXPECTED:-1}" ] 2>/dev/null; then rc=0; else rc=1; fi
check "every stored day was swept" "$rc" "chunks ${CHUNKS} for about ${EXPECTED} expected"
LIMIT=$((SWAP_BEFORE + SWAP_BEFORE / 20))
if [ "$SWAP_PEAK" -le "$LIMIT" ]; then rc=0; else rc=1; fi
check "swap stayed within the baseline + 5%" "$rc" "$SWAP_BEFORE -> peak $SWAP_PEAK MB, limit $LIMIT"
if [ $((OS_PEAK - ${OS_BEFORE:-0})) -le 200 ]; then rc=0; else rc=1; fi
check "OpenSearch anonymous memory rose by no more than 200 MB" "$rc" "${OS_BEFORE:-?} -> peak $OS_PEAK MB (heap is capped by -Xmx)"
if [ "$LAT_PEAK" -le $((LAT_BEFORE * 3 + 50)) ]; then rc=0; else rc=1; fi
check "API latency stayed under 3x its baseline" "$rc" "$LAT_BEFORE -> peak $LAT_PEAK ms"
echo ""

echo "→ Step 7: Yesterday's ledger total equals a fresh raw count of the same day..."
# Yesterday in the ledger's own zone, over that day's exact UTC bounds: /api/bandwidth/daily
# (get_daily_usage) filters to the window and sums with the same filters and direction split.
# OLD CODE: the UTC day only, and FAIL unless the zone was UTC (a re-run after the owner picks a zone)
result "ledger yesterday == raw yesterday" "$(daemon_py "
from urllib.parse import quote
from zoneinfo import ZoneInfo
def iso(t):
    return t.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
def compare():
    s, b = call('GET', '/api/usage/month')
    tz = json.loads(b)['tz']
    y = (datetime.now(ZoneInfo(tz)) - timedelta(days=1)).strftime('%Y-%m-%d')
    _, lb = call('GET', '/api/usage/daily?from=' + y + '&to=' + y)
    day = json.loads(lb)['days'][0]
    start = datetime.fromisoformat(day['start'])
    end = datetime.fromisoformat(day['end']) - timedelta(milliseconds=1)
    _, rb = call('GET', '/api/bandwidth/daily?from=' + quote(iso(start)) + '&to=' + quote(iso(end)))
    raw = sum(d['upload_bytes'] + d['download_bytes'] for d in json.loads(rb)['daily'])
    return tz, y, day['status'], day['total'], raw
tz, y, status, ledger, raw = compare()
if ledger != raw:
    call('POST', '/api/jobs/usage-ledger/run'); time.sleep(30)
    tz, y, status, ledger, raw = compare()
print('OK' if ledger == raw else 'FAIL', y, tz, 'status', status, 'ledger', ledger, 'raw', raw)")"
echo ""

echo "→ Step 8: A repeat run, a daemon restart and another run change no settled total..."
SNAPSHOT=$(daemon_py "
s, b = call('GET', '/api/usage/month')
since = json.loads(b)['since']
cut = (datetime.now(timezone.utc) - timedelta(days=2)).strftime('%Y-%m-%d')
_, d = call('GET', '/api/usage/daily?from=' + since + '&to=' + cut)
print(json.dumps({x['date']: x['total'] for x in json.loads(d)['days'] if x['total'] is not None}))")
daemon_py "call('POST', '/api/jobs/usage-ledger/run'); time.sleep(60)" >/dev/null
sudo docker restart nettap-storage-daemon >/dev/null
for i in $(seq 1 30); do
    [ "$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null)" = "healthy" ] && break
    sleep 5
done
daemon_py "call('POST', '/api/jobs/usage-ledger/run'); time.sleep(60)" >/dev/null
result "no total before yesterday changed" "$(daemon_py "
before = json.loads('''$SNAPSHOT''')
s, b = call('GET', '/api/usage/month')
since = json.loads(b)['since']
cut = (datetime.now(timezone.utc) - timedelta(days=2)).strftime('%Y-%m-%d')
_, d = call('GET', '/api/usage/daily?from=' + since + '&to=' + cut)
after = {x['date']: x['total'] for x in json.loads(d)['days'] if x['total'] is not None}
changed = [k for k in before if after.get(k) != before[k]]
print('OK' if not changed else 'FAIL', len(before), 'days compared, changed', changed[:5])")"
echo ""

echo "→ Step 9: The ledger file and settled memory..."
result "ledger under 400 bytes a day; since and gaps" "$(daemon_py "
size = os.path.getsize('/opt/nettap/data/usage-ledger.json')
led = json.load(open('/opt/nettap/data/usage-ledger.json'))
days = len(led.get('days', {}))
print('OK' if size < 400 * days + 8192 else 'FAIL', size, 'bytes, since', led.get('since'), 'gaps', len(led.get('gaps', [])), 'days', days)")"
DAEMON_RSS_AFTER=$(settled_rss_mb)
if [ $((DAEMON_RSS_AFTER - DAEMON_RSS_BEFORE)) -le 50 ]; then rc=0; else rc=1; fi
check "settled daemon VmRSS within 50 MB of before" "$rc" "$DAEMON_RSS_BEFORE -> $DAEMON_RSS_AFTER MB"
free -m | sed -n 1,3p
echo ""

echo "→ Step 10: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 10m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|$OPENSEARCH"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
