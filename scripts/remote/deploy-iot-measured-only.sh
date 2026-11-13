#!/usr/bin/env bash
# Deploy NET-171 (IoT checks score only measured data) and NET-174 (the unused classify route
# is gone), and check both on the device.
#
# Rebuilds the web UI and the daemon. Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-iot-measured-only.sh
# To test a branch first: git checkout <branch> && git pull, then BRANCH=<branch> bash …
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

api() {  # api PATH EXPRESSION: GET PATH from the daemon with its token, print EXPRESSION over the reply `d`
    # The expression is always a literal from this script. The token is read inside the
    # container, inside fetch(): it, the headers and the request are gone before the eval runs
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.error, urllib.request
def fetch(path):
    headers = {'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip()}
    req = urllib.request.Request('http://localhost:8880' + path, headers=headers)
    try:
        return json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        return {'_status': e.code}
    except (urllib.error.URLError, ValueError):
        return {'_status': 'unreachable'}  # truthy, so no check passes on it
d = fetch(sys.argv[1])
del fetch
print(eval(sys.argv[2]))" "$1" "$2" 2>&1 | tail -n 1
}

status() {  # status METHOD PATH: the HTTP status the daemon answers (an empty JSON body for POST)
    sudo docker exec nettap-storage-daemon python3 -c "
import sys, urllib.error, urllib.request
method, path = sys.argv[1], sys.argv[2]
headers = {'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip(),
           'Content-Type': 'application/json'}
req = urllib.request.Request('http://localhost:8880' + path, method=method, headers=headers,
                             data=b'{}' if method == 'POST' else None)
try:
    print(urllib.request.urlopen(req, timeout=30).status)
except urllib.error.HTTPError as e:
    print(e.code)
except urllib.error.URLError:
    print('unreachable')" "$1" "$2" 2>&1 | tail -n 1
}

echo "=== Deploy: IoT checks score only measured data ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web and daemon containers..."
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the web and the daemon..."
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

echo "→ Step 5: NET-171 — the trust score counts only measured checks..."
FLEET=/api/iot/fleet-summary
echo "   $(api "$FLEET" "d.get('_status') or '%s IoT devices, %s scored, fleet score %s' % (d.get('device_count'), d.get('scored_device_count'), d.get('health_score'))")"
# telemetry and firmware left the model: nine checks (none on the device means nothing to check)
R=$(api "$FLEET" "d.get('_status') or sorted({x.get('checks_total') for x in d['devices']}) or 'no IoT devices'")
if [ "$R" = "no IoT devices" ]; then
    check "every device is scored over 9 checks" 0 "no IoT devices, check skipped"
else
    expect "every device is scored over 9 checks" "$R" "[9]"
fi
# behaviour needs a baseline (NET-170): no device and not the fleet may show a behaviour score
R=$(api "$FLEET" "d.get('_status') or ([x['name'] for x in d['devices'] if x.get('behavior_score') is not None] or ('fleet' if d.get('behavior_score') is not None else 'ok'))")
expect "behaviour is not measured, so it has no score" "$R" ok
# a score needs 50 of the 85 points; a device with nothing measured has no score and no pillar
R=$(api "$FLEET" "d.get('_status') or ([x['name'] for x in d['devices'] if not 0 <= x.get('coverage', -1) <= 85 or (x.get('score') is not None and x['coverage'] < 50) or (x.get('checks_available') == 0 and any(x.get(k) is not None for k in ('score', 'privacy_score', 'security_score', 'behavior_score')))] or 'ok')")
expect "no device shows a score it didn't measure" "$R" ok
R=$(api /api/iot/privacy-report "d.get('_status') or ('ok' if isinstance(d.get('devices'), list) else 'no devices key')")
expect "/api/iot/privacy-report" "$R" ok
R=$(api /api/iot/manufacturer-profiles "d.get('_status') or ('ok' if isinstance(d.get('manufacturers'), list) else 'no manufacturers key')")
expect "/api/iot/manufacturer-profiles" "$R" ok
echo ""

echo "→ Step 6: NET-174 — the classify route is gone..."
# Safe even if the route were still there: an empty body never classifies a device
expect "POST /api/iot/devices/…/classify" "$(status POST /api/iot/devices/AA:BB:CC:DD:EE:FF/classify)" 404
# 405 here would mean the route still exists for POST
expect "GET /api/iot/devices/…/classify" "$(status GET /api/iot/devices/AA:BB:CC:DD:EE:FF/classify)" 404
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo "Open the IoT page: Behaviour reads \"Not measured\", and a device's drawer says \"from N of 9 checks\"."
