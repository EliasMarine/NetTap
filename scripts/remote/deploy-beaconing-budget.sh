#!/usr/bin/env bash
# Deploy the beaconing time budget and faster scan (NET-187) and check them on the device.
#
# Rebuilds the daemon and the web UI. Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-beaconing-budget.sh
# To test a branch first: git checkout <branch> && git pull, then BRANCH=<branch> bash …
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BUDGET_S=60   # BEACON_BUDGET_SECONDS in daemon/api/threats.py
LIMIT_S=75    # the budget plus the rest of the report (under 3 s on the G11); the web proxy waits 120 s
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

timed() {  # timed PATH-WITHOUT-WINDOW HOURS: GET PATH?from=&to= (the last HOURS hours), print "status seconds" + a summary
    # The token is read inside the container, inside fetch(); it is never printed
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
def fetch(path):
    headers = {'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip()}
    req = urllib.request.Request('http://localhost:8880' + path, headers=headers)
    try:
        return 200, json.load(urllib.request.urlopen(req, timeout=150))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, ValueError, TimeoutError):
        return 'unreachable', {}
to = datetime.now(timezone.utc)
frm = to - timedelta(hours=float(sys.argv[2]))
z = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')
started = time.monotonic()
status, d = fetch(sys.argv[1] + '?from=' + z(frm) + '&to=' + z(to))
del fetch
secs = time.monotonic() - started
failed = d.get('failed_checks') or []
slow = d.get('timed_out_checks') or []
if 'beacons' in d:
    what = 'beacons=%d complete=%s' % (len(d['beacons']), d.get('complete'))
elif 'beaconing' in d:
    what = 'beaconing=%s failed=%s timed_out=%s' % ('not checked' if 'beaconing' in failed else len(d['beaconing']), failed, slow)
else:
    what = 'error=%r' % d.get('error')
print(status, '%.1f' % secs, what)" "$1" "$2" 2>&1 | tail -n 1
}

echo "=== Deploy: beaconing time budget and faster scan, NET-187 ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the daemon and web containers..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the daemon and the web UI..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
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

echo "→ Step 5: The background scans after the restart (24 h was 11–16 s, 7 d 55–76 s on the G11)..."
# They run one after another at start; the timings below wait for all three, so they don't share OpenSearch
for i in $(seq 1 60); do
    sudo docker logs --since "$STARTED" nettap-storage-daemon 2>&1 | grep -q 'beacon-snapshot window=30d' && break
    sleep 5
done
for W in 24h 7d 30d; do
    LINE=$(sudo docker logs --since "$STARTED" nettap-storage-daemon 2>&1 | grep "beacon-snapshot window=$W " | tail -n 1)
    case "$LINE" in *"outcome=published"*) check "$W scan published" 0 "${LINE##*beacon-snapshot }" ;; *) check "$W scan published" 1 "${LINE:-no beacon-snapshot line within 5 min}" ;; esac
done
echo ""

echo "→ Step 6: Live 24 h threat report against the ${BUDGET_S} s budget..."
read -r STATUS SECS REST <<<"$(timed /api/threats/report 24)"
OK=1
[ "$STATUS" = "200" ] && [ "${SECS%.*}" -lt "$BUDGET_S" ] && case "$REST" in *"beaconing=not checked"*) false ;; *) true ;; esac && OK=0
check "24 h report: HTTP $STATUS in ${SECS} s" $OK "$REST"
echo ""

echo "→ Step 7: Live 30 d threat report: a result or 'not checked in time', within ${LIMIT_S} s..."
read -r STATUS SECS REST <<<"$(timed /api/threats/report 720)"
OK=1
if [ "$STATUS" = "200" ] && [ "${SECS%.*}" -lt "$LIMIT_S" ]; then
    case "$REST" in
        *"beaconing=not checked"*"timed_out=['beaconing']"*) OK=0; REST="beaconing not checked in time (honest); $REST" ;;
        *"beaconing=not checked"*) OK=1 ;;  # failed for another reason
        *) OK=0 ;;
    esac
fi
check "30 d report: HTTP $STATUS in ${SECS} s" $OK "$REST"
echo ""

echo "→ Step 8: Live 30 d beaconing route: 200, or 503 'took too long', within ${LIMIT_S} s..."
read -r STATUS SECS REST <<<"$(timed /api/threats/beaconing 720)"
OK=1
if [ "${SECS%.*}" -lt "$LIMIT_S" ]; then
    case "$STATUS $REST" in
        "200 beacons="*) OK=0 ;;
        "503 "*"took too long"*) OK=0 ;;
    esac
fi
check "30 d beaconing: HTTP $STATUS in ${SECS} s" $OK "$REST"
echo ""

echo "→ Step 9: The page's own path (?snapshot=24h) still answers..."
R=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
req = urllib.request.Request('http://localhost:8880/api/threats/report?snapshot=24h', headers={'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip()})
try:
    d = json.load(urllib.request.urlopen(req, timeout=120))
    print('ok' if d.get('beaconing_snapshot', {}).get('state') in ('ready', 'stale', 'pending') else 'no beaconing_snapshot')
except Exception as e:
    print(type(e).__name__)" 2>&1 | tail -n 1)
expect "snapshot report" "$R" ok
echo ""

echo "→ Step 10: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo "Open /threats and pick 1h: the beaconing card should load as before."
