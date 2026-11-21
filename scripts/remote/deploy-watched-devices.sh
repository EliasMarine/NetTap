#!/usr/bin/env bash
# Deploy NET-331 (roadmap #5, "device went offline" alerts) and check it on the box (plan §2.8):
#   - the running daemon and web app are the images just built (image IDs, not the tags);
#   - production, read only: a natural watched-devices run after the recreate with no error, the
#     /api/devices/watched shape with a fresh check (success or an expected skip), and the
#     notification config's watched_device flag;
#   - a live probe on the real index with temporary stores (probe_watched_devices.py, inside the
#     daemon container): real search, samples from raw conn hits, nothing written, nothing sent;
#   - isolated: verify_watched_devices.py in a throwaway copy of the image (no network, no mounts);
#   - the daemon's settled memory stays within 50 MB of before.
# Nothing live is written: no watch is set or cleared, no job is forced, no notification is sent.
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Prints figures, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-watched-devices.sh
# To try a branch before it merges: BRANCH=feature/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
DAEMON_IMAGE="nettap/storage-daemon:latest"
WEB_IMAGE="nettap/web:latest"
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

# Run a Python check inside the daemon container with the shared token as `call(method, path, body)`.
daemon_py() {  # daemon_py PYTHON_SNIPPET
    sudo docker exec -e SNIPPET="$1" nettap-storage-daemon python3 -c '
import json, os, time, urllib.error, urllib.request
from datetime import datetime, timezone
token = open("/run/nettap-auth/daemon-token").read().strip()
def call(method, path, body=None):
    data = None if body is None else body.encode()
    req = urllib.request.Request("http://localhost:8880" + path, data=data, method=method,
                                 headers={"X-NetTap-Daemon-Token": token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
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
    sudo docker top nettap-storage-daemon -o pid,rss,args 2>/dev/null | awk '$3 ~ /python/ && / main\.py/ { if ($2 > m) m = $2 } END { printf "%d", m / 1024 }'
}

daemon_uptime_s() {
    local started
    started=$(sudo docker inspect -f '{{.State.StartedAt}}' nettap-storage-daemon 2>/dev/null)
    echo $(( $(date +%s) - $(date -d "$started" +%s 2>/dev/null || date +%s) ))
}

settled_rss_mb() {  # wait until VmRSS moves under 10% across a minute (at most 5 minutes)
    local prev now i
    # start-up holds about 1.2 GB for its first minutes (F1 and F4 deploys): read after 5 minutes
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

echo "=== Deploy: watched devices (NET-331, $BRANCH) ==="
echo ""

echo "→ Step 1: Baseline..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
free -m | sed 's/^/   /'
sudo docker stats --no-stream --format "   {{.Name}} {{.MemUsage}}" nettap-storage-daemon nettap-web 2>/dev/null || true
DAEMON_RSS_BEFORE=$(settled_rss_mb)
echo "   daemon VmRSS ${DAEMON_RSS_BEFORE} MB (settled)"
echo ""

echo "→ Step 2: Update the code..."
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Build the daemon and web containers..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
BUILT=$(sudo docker image inspect "$DAEMON_IMAGE" --format '{{.Id}}' 2>/dev/null)
BUILT_WEB=$(sudo docker image inspect "$WEB_IMAGE" --format '{{.Id}}' 2>/dev/null)
echo "   ✓ Images built (daemon ${BUILT:7:12}, web ${BUILT_WEB:7:12})"
echo ""

echo "→ Step 4: Recreate the daemon and web containers (nothing else is touched)..."
RECREATED_AT=$(date -u +%Y-%m-%dT%H:%M:%S)
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web; then
    echo "   ✗ Recreation failed — the checks below would test the old containers"
    exit 1
fi
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
RUNNING=$(sudo docker inspect nettap-storage-daemon --format '{{.Image}}' 2>/dev/null)
if [ -n "$BUILT" ] && [ "$RUNNING" = "$BUILT" ]; then rc=0; else rc=1; fi
check "daemon image ID" "$rc" "running ${RUNNING:7:12}, built ${BUILT:7:12}"
RUNNING_WEB=$(sudo docker inspect nettap-web --format '{{.Image}}' 2>/dev/null)
if [ -n "$BUILT_WEB" ] && [ "$RUNNING_WEB" = "$BUILT_WEB" ]; then rc=0; else rc=1; fi
check "web image ID" "$rc" "running ${RUNNING_WEB:7:12}, built ${BUILT_WEB:7:12}"
echo ""

echo "→ Step 6: Production, read only (waits for a natural run; nothing is forced)..."
result "a watched-devices run after the recreate, with no error" "$(daemon_py "
since = '$RECREATED_AT'
for _ in range(84):  # up to 7 minutes, every 5 s
    s, b = call('GET', '/api/jobs')
    job = next((j for j in json.loads(b).get('jobs', []) if j.get('name') == 'watched-devices'), None) if s == 200 else None
    if job and job.get('last_run') and job['last_run'][:19] >= since and not job.get('running'):
        break
    time.sleep(5)
else:
    job = None
if not job:
    print('FAIL no completed run after', since)
elif job.get('last_error'):
    print('FAIL', str(job['last_error'])[:160])
else:
    print('OK ran at', job['last_run'][:19], 'in', job.get('last_duration_ms'), 'ms')")"
result "/api/devices/watched: shape and a fresh check" "$(daemon_py "
since = '$RECREATED_AT'
s, b = call('GET', '/api/devices/watched')
d = json.loads(b) if s == 200 else {}
c, devices = d.get('check') or {}, d.get('devices')
attempt = c.get('attempt_at') or ''
if s != 200 or not isinstance(devices, list):
    print('FAIL status', s)
elif c.get('error'):
    print('FAIL check error:', str(c['error'])[:160])
elif attempt[:19] < since:
    print('FAIL the last check is from before the recreate:', attempt[:19])
elif c.get('success_at') == attempt or c.get('skipped') in ('mode', 'pipeline'):
    states = {}
    for x in devices:
        states[x.get('state')] = states.get(x.get('state'), 0) + 1
    print('OK', len(devices), 'watched', states, 'skipped', c.get('skipped'))
else:
    print('FAIL unexpected check', {k: c.get(k) for k in ('attempt_at', 'success_at', 'skipped')})")"
result "the notification config carries the watched_device flag" "$(daemon_py "
s, b = call('GET', '/api/notifications/config')
d = json.loads(b) if s == 200 else {}
print('OK' if s == 200 and 'watched_device' in d else 'FAIL', 'status', s)")"
echo ""

echo "→ Step 7: Live probe on the real index (temporary stores, nothing written or sent)..."
# the user reads the script and docker gets it on stdin, so sudo needn't touch the redirect
# shellcheck disable=SC2024
OUT=$(sudo docker exec -i nettap-storage-daemon python3 - < scripts/remote/probe_watched_devices.py 2>&1)
echo "$OUT" | grep -E "^   " || true
if echo "$OUT" | grep -qx "WATCHED-PROBE-OK"; then rc=0; else rc=1; fi
check "real search, samples up, negative cases unknown" "$rc" "$(echo "$OUT" | tail -n 1)"
echo ""

echo "→ Step 8: Isolated exercise in a throwaway copy of the image (no network, no mounts)..."
if [ -z "$RUNNING" ] || [ "$RUNNING" != "$BUILT" ]; then
    check "isolated exercise" 1 "skipped: the running image isn't the one built"
else
    # shellcheck disable=SC2024
    OUT=$(sudo docker run --rm -i --network none --entrypoint python3 "$BUILT" - < scripts/remote/verify_watched_devices.py 2>&1)
    echo "$OUT" | grep -E "^   " || true
    if echo "$OUT" | grep -qx "WATCHED-DEVICES-OK"; then rc=0; else rc=1; fi
    check "state machine, crash cases, skips, refused replies, watch-only clear" "$rc" "$(echo "$OUT" | tail -n 1)"
fi
echo ""

echo "→ Step 9: Settled memory..."
DAEMON_RSS_AFTER=$(settled_rss_mb)
if [ $((DAEMON_RSS_AFTER - DAEMON_RSS_BEFORE)) -le 50 ]; then rc=0; else rc=1; fi
check "settled daemon VmRSS within 50 MB of before" "$rc" "$DAEMON_RSS_BEFORE -> $DAEMON_RSS_AFTER MB"
free -m | sed 's/^/   /'
echo ""

echo "→ Step 10: Log errors since the restart..."
sudo docker logs --since "${RECREATED_AT}Z" nettap-storage-daemon 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -ne 0 ]; then
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
echo "=== Deploy complete: every check passed ==="
echo "Owner check: watch a smart plug at 15 minutes, wait until the card shows it Online, unplug it"
echo "and time the alert (about 30-35 minutes), then plug it back in for Back online."
