#!/usr/bin/env bash
# Deploy NET-330 (roadmap #8, quiet hours) and check it on the box (plan §8):
#   - the running daemon is the image just built (image ID, not the tag);
#   - live and read-only: zoneinfo works, GET /api/notifications/config has quiet and tz, no
#     quiet hours warning in the log;
#   - isolated: verify_quiet_hours.py runs in a throwaway copy of that image with no network and
#     no mounts, holding two data cap warnings overnight and releasing them as one message;
#   - the daemon's settled memory stays within 50 MB of before.
# No live setting, channel, cap or journal is changed. Rebuilds and recreates only
# nettap-storage-daemon and nettap-web. Prints status codes and figures, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-quiet-hours.sh
# To try a branch before it merges: BRANCH=feature/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
DAEMON_IMAGE="nettap/storage-daemon:latest"
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

echo "=== Deploy: quiet hours (NET-330, $BRANCH) ==="
echo ""

echo "→ Step 1: Baseline (settled daemon memory)..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
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
# a failed build must stop here: recreating would bring back the OLD images unnoticed
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
BUILT=$(sudo docker image inspect "$DAEMON_IMAGE" --format '{{.Id}}' 2>/dev/null)
echo "   ✓ Images built (daemon ${BUILT:7:12})"
echo ""

echo "→ Step 4: Recreate the daemon and web containers (nothing else is touched)..."
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
echo ""

echo "→ Step 6: The running daemon is the image just built..."
RUNNING=$(sudo docker inspect nettap-storage-daemon --format '{{.Image}}' 2>/dev/null)
if [ -n "$BUILT" ] && [ "$RUNNING" = "$BUILT" ]; then rc=0; else rc=1; fi
check "daemon image ID" "$rc" "running ${RUNNING:7:12}, built ${BUILT:7:12}"
echo ""

echo "→ Step 7: Live and read-only..."
result "zoneinfo works in the daemon" "$(daemon_py "
from zoneinfo import ZoneInfo
print('OK', datetime.now(ZoneInfo('Europe/London')).tzname())")"
result "the config reply has quiet and tz" "$(daemon_py "
s, b = call('GET', '/api/notifications/config')
c = json.loads(b) if s == 200 else {}
q = c.get('quiet') or {}
ok = s == 200 and isinstance(c.get('tz'), str) and set(q) == {'enabled', 'start', 'end', 'critical_through'}
# only these two fields: the reply also holds channel settings
print('OK' if ok else 'FAIL', 'status', s, 'quiet', json.dumps(q), 'tz', c.get('tz'))")"
WARNINGS=$(sudo docker logs nettap-storage-daemon --since 15m 2>&1 | grep -ciE "quiet hours" || true)
if [ "${WARNINGS:-0}" -eq 0 ]; then rc=0; else rc=1; fi
check "no quiet hours warning in the daemon log" "$rc" "${WARNINGS:-0} line(s)"
echo ""

echo "→ Step 8: Isolated exercise in a throwaway copy of the image (no network, no mounts)..."
if [ -z "$RUNNING" ] || [ "$RUNNING" != "$BUILT" ]; then
    check "isolated exercise" 1 "skipped: the running image isn't the one built"
else
    # the user reads the script and docker gets it on stdin, so sudo needn't touch the redirect
    # shellcheck disable=SC2024
    OUT=$(sudo docker run --rm -i --network none --entrypoint python3 "$BUILT" - < scripts/remote/verify_quiet_hours.py 2>&1)
    echo "$OUT" | grep -E "^   " || true
    if echo "$OUT" | grep -qx "QUIET-HOURS-OK"; then rc=0; else rc=1; fi
    check "held overnight, released once at 07:00 (Europe/London)" "$rc" "$(echo "$OUT" | tail -n 1)"
fi
echo ""

echo "→ Step 9: Settled memory..."
DAEMON_RSS_AFTER=$(settled_rss_mb)
if [ $((DAEMON_RSS_AFTER - DAEMON_RSS_BEFORE)) -le 50 ]; then rc=0; else rc=1; fi
check "settled daemon VmRSS within 50 MB of before" "$rc" "$DAEMON_RSS_BEFORE -> $DAEMON_RSS_AFTER MB"
echo ""

echo "→ Step 10: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 15m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
