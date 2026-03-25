#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/infrastructure-redesign"

echo "=== Deploy Live Network Monitor v2 ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR"
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

echo "→ Step 6: Test dashboard API endpoint..."
DASHBOARD_RESPONSE=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/live/dashboard?limit=5 2>/dev/null || echo "FAILED")
if echo "$DASHBOARD_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   connections: {d[\"count\"]}, rate: {d[\"stats\"][\"connections_per_second\"]}/s, arcs: {len(d[\"geo_arcs\"])}')" 2>/dev/null; then
    echo "   ✓ Dashboard API working"
else
    echo "   ⚠ Dashboard API returned: ${DASHBOARD_RESPONSE:0:200}"
fi
echo ""

echo "→ Step 7: Test connection detail endpoint..."
DETAIL_RESPONSE=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/live/connection/detail?src=192.168.1.1&dst=1.1.1.1" 2>/dev/null || echo "FAILED")
if echo "$DETAIL_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   alerts: {d[\"alert_count\"]}, history: {d[\"history\"][\"connection_count\"]} connections')" 2>/dev/null; then
    echo "   ✓ Connection detail API working"
else
    echo "   ⚠ Detail API returned: ${DETAIL_RESPONSE:0:200}"
fi
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard and navigate to /live to verify the new Live Network Monitor."
echo "Features to check:"
echo "  - Stats ribbon with 4 cards (conn/s, bandwidth, devices, top country)"
echo "  - World map with animated arcs to destination cities"
echo "  - Protocol donut chart + Top talkers bar chart"
echo "  - Sortable connections table"
echo "  - Click a table row to open the detail drawer"
echo "  - Click map dots/chart items to cross-filter"
