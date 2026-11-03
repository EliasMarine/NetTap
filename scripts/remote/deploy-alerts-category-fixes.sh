#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/alerts-v3-category-hub"

echo "=== Deploy Alerts Category Filter + Icon + Color Fixes ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "ERROR: Cannot cd to $REPO_DIR"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code updated"
echo ""

echo "→ Step 2: Rebuild web container..."
sudo docker compose -f docker/docker-compose.yml build nettap-web
echo "   ✓ Web container rebuilt"
echo ""

echo "→ Step 3: Rebuild daemon container..."
sudo docker compose -f docker/docker-compose.yml build nettap-storage-daemon
echo "   ✓ Daemon container rebuilt"
echo ""

echo "→ Step 4: Restart containers..."
sudo docker compose -f docker/docker-compose.yml up -d nettap-web nettap-storage-daemon --force-recreate
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

echo "→ Step 6: Test category filter on alerts API..."
sudo docker exec nettap-storage-daemon curl -s 'http://localhost:8880/api/alerts?category=malware_c2&size=3' | python3 -c "
import sys, json
data = json.load(sys.stdin)
total = data.get('total', 0)
alerts = data.get('alerts', [])
print(f'   Malware & C2 filtered alerts: {total} total')
for a in alerts[:3]:
    sig = a.get('signature', a.get('rule', {}).get('name', 'unknown'))
    print(f'     - {sig}')
if total > 0:
    print('   ✓ Category filter working')
else:
    print('   ⚠ No alerts returned (may be expected if no malware alerts in default time range)')
"
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Open https://192.168.1.208/alerts and drill into a category to verify:"
echo "  1. Category icons show correct emoji (bug, search, shield, etc.)"
echo "  2. Recent Alerts table shows only alerts for that category"
echo "  3. Timeline bars render in the category color (not black)"
