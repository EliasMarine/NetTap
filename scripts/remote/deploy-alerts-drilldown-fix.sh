#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/alerts-v3-category-hub"

echo "=== Deploy: Alert Category Drill-Down Fix ==="
echo "Fixes: each_key_duplicate crash, broken timeline, missing last_seen"
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code updated"
echo ""

echo "→ Step 2: Rebuild daemon container..."
sudo docker compose -f docker/docker-compose.yml build nettap-storage-daemon
echo "   ✓ Daemon container rebuilt"
echo ""

echo "→ Step 3: Restart daemon container..."
sudo docker compose -f docker/docker-compose.yml up -d nettap-storage-daemon --force-recreate
echo "   ✓ Daemon container restarted"
echo ""

echo "→ Step 4: Wait for daemon to become healthy..."
for i in $(seq 1 30); do
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$DAEMON_STATUS" = "healthy" ]; then
        echo "   ✓ Daemon healthy"
        break
    fi
    echo "   waiting... daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
echo ""

echo "→ Step 5: Test category detail endpoint (affected_devices as objects)..."
DETAIL_RESPONSE=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/alerts/categories/reconnaissance 2>/dev/null)
DEVICE_IP=$(echo "$DETAIL_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    devices = data.get('affected_devices', [])
    if not devices:
        print('NO_DEVICES (may be no recon alerts — check other categories)')
    elif isinstance(devices[0], dict) and 'ip' in devices[0]:
        print('OK: first device = ' + devices[0]['ip'] + ' (count=' + str(devices[0].get('count','?')) + ', severity=' + str(devices[0].get('severity','?')) + ')')
    elif isinstance(devices[0], str):
        print('FAIL: still returning strings, not objects!')
    else:
        print('UNEXPECTED: ' + str(type(devices[0])))
except Exception as e:
    print('ERROR: ' + str(e))
" 2>/dev/null)
echo "   affected_devices: $DEVICE_IP"
echo ""

echo "→ Step 6: Test top_signatures has last_seen field..."
SIG_LAST_SEEN=$(echo "$DETAIL_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    sigs = data.get('top_signatures', [])
    if not sigs:
        print('NO_SIGNATURES (may be no alerts in time range)')
    elif 'last_seen' in sigs[0]:
        print('OK: last_seen = ' + str(sigs[0]['last_seen']))
    else:
        print('FAIL: last_seen field missing from top_signatures!')
except Exception as e:
    print('ERROR: ' + str(e))
" 2>/dev/null)
echo "   top_signatures: $SIG_LAST_SEEN"
echo ""

echo "→ Step 7: Test timeline endpoint (series, not buckets)..."
TIMELINE_RESPONSE=$(sudo docker exec nettap-storage-daemon curl -s 'http://localhost:8880/api/alerts/categories/reconnaissance/timeline' 2>/dev/null)
TIMELINE_CHECK=$(echo "$TIMELINE_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'series' in data:
        series = data['series']
        if series and 'total' in series[0] and 'sub_categories' in series[0]:
            non_zero = [s for s in series if s['total'] > 0]
            print('OK: series has ' + str(len(series)) + ' points (' + str(len(non_zero)) + ' non-zero), fields: total + sub_categories')
        else:
            print('PARTIAL: series key exists but inner fields wrong: ' + str(list(series[0].keys()) if series else 'empty'))
    elif 'buckets' in data:
        print('FAIL: still returning \"buckets\" instead of \"series\"!')
    else:
        print('UNEXPECTED keys: ' + str(list(data.keys())))
except Exception as e:
    print('ERROR: ' + str(e))
" 2>/dev/null)
echo "   timeline: $TIMELINE_CHECK"
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep nettap-storage-daemon
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard → Alerts → click any category card to verify."
echo "The page should load without crashing, showing:"
echo "  - Affected devices table with IPs, counts, severity badges"
echo "  - Timeline chart with bars"
echo "  - Top signatures with 'last seen' timestamps"
