#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/infrastructure-redesign"

echo "=== Deploy Bulletproof Retention System ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "ERROR: Cannot cd to $REPO_DIR"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code updated"
echo ""

echo "→ Step 2: Rebuild daemon container..."
sudo docker compose -f docker/docker-compose.yml build nettap-storage-daemon
echo "   ✓ Daemon container rebuilt"
echo ""

echo "→ Step 3: Rebuild web container..."
sudo docker compose -f docker/docker-compose.yml build nettap-web
echo "   ✓ Web container rebuilt"
echo ""

echo "→ Step 4: Restart containers..."
sudo docker compose -f docker/docker-compose.yml up -d nettap-storage-daemon nettap-web --force-recreate
echo "   ✓ Containers restarted"
echo ""

echo "→ Step 5: Wait for containers to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        echo "   ✓ Both containers healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
echo ""

echo "→ Step 6: Test storage status API (new fields)..."
STORAGE_STATUS=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/storage/status 2>/dev/null || echo "{}")
echo "   Response preview:"
echo "$STORAGE_STATUS" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'   hot_days:       {d.get(\"hot_days\", \"MISSING\")}')
    print(f'   warm_days:      {d.get(\"warm_days\", \"MISSING\")}')
    print(f'   cold_days:      {d.get(\"cold_days\", \"MISSING\")}')
    print(f'   ilm_synced:     {d.get(\"ilm_synced\", \"MISSING\")}')
    print(f'   last_prune_at:  {d.get(\"last_prune_at\", \"MISSING\")}')
    ilm = d.get('ilm_status', {})
    print(f'   ilm_status.synced: {ilm.get(\"synced\", \"MISSING\")}')
    print(f'   disk_usage:     {d.get(\"disk_usage_percent\", \"MISSING\")}%')
except:
    print('   ✗ Failed to parse response')
" 2>/dev/null || echo "   ✗ Could not reach daemon API"
echo ""

echo "→ Step 7: Test new config endpoint exists..."
CONFIG_RESP=$(sudo docker exec nettap-storage-daemon curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d '{"hot_days": 90, "warm_days": 180, "cold_days": 30, "disk_threshold_percent": 80, "emergency_threshold_percent": 90}' http://localhost:8880/api/storage/config 2>/dev/null || echo "000")
if [ "$CONFIG_RESP" = "200" ]; then
    echo "   ✓ POST /api/storage/config returned 200"
else
    echo "   ⚠ POST /api/storage/config returned $CONFIG_RESP (may need OpenSearch bootstrap)"
fi
echo ""

echo "→ Step 8: Check retention.json was created..."
if sudo docker exec nettap-storage-daemon test -f /opt/nettap/data/retention.json; then
    echo "   ✓ retention.json exists"
    sudo docker exec nettap-storage-daemon cat /opt/nettap/data/retention.json | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    r = d.get('retention', {})
    t = d.get('thresholds', {})
    print(f'   hot={r.get(\"hot_days\")}d  warm={r.get(\"warm_days\")}d  cold={r.get(\"cold_days\")}d')
    print(f'   disk_threshold={t.get(\"disk_threshold_percent\")}%  emergency={t.get(\"emergency_threshold_percent\")}%')
except:
    print('   (could not parse)')
" 2>/dev/null
else
    echo "   ⚠ retention.json not yet created (will be created on first API call or prune cycle)"
fi
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo ""
echo "Open the dashboard and go to Settings > Retention to see the new health card."
echo "The card shows ILM sync status, disk usage, and last prune cycle."
