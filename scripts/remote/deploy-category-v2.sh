#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/traffic-category-duplicate-services"

echo "=== Deploy Traffic Category Detail v2 ==="
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

echo "→ Step 4: Restart both containers..."
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

echo "→ Step 6: Test category bandwidth API (new endpoint)..."
BW=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/traffic/categories/cloud/bandwidth?interval=1h" 2>/dev/null)
BW_POINTS=$(echo "$BW" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'points={len(d.get(\"series\",[]))} category={d.get(\"category\",\"?\")}')" 2>/dev/null || echo "parse error")
echo "   Category bandwidth: $BW_POINTS"
echo ""

echo "→ Step 7: Test category detail API (with hostnames)..."
DETAIL=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/traffic/categories/cloud" 2>/dev/null)
DEVICE_COUNT=$(echo "$DETAIL" | python3 -c "import sys,json; d=json.load(sys.stdin); devs=d.get('devices',[]); with_host=sum(1 for d in devs if d.get('hostname')); print(f'devices={len(devs)} with_hostname={with_host}')" 2>/dev/null || echo "0")
SVC_CHECK=$(echo "$DETAIL" | python3 -c "import sys,json; d=json.load(sys.stdin); svcs=d.get('services',[]); has_conn=all('connections' in s for s in svcs); dupes=[s['name'] for s in svcs if [x['name'] for x in svcs].count(s['name'])>1]; print(f'services={len(svcs)} has_connections={has_conn} dupes={len(set(dupes))}')" 2>/dev/null || echo "parse error")
echo "   Devices: $DEVICE_COUNT"
echo "   Services: $SVC_CHECK"
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo ""
echo "Open the dashboard and click any traffic category to see:"
echo "  - Bandwidth over time chart"
echo "  - Hostnames next to device IPs"
echo "  - Traffic share % column"
echo "  - DL/UL split bars (cyan/purple)"
echo "  - Search filter on device table"
echo "  - Auto-refresh toggle"
echo "  - Clickable services to filter devices"
echo "  - % of Network stat card"
echo "  - Trend indicators vs previous period"
