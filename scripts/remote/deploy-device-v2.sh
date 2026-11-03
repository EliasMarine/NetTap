#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/traffic-category-duplicate-services"

echo "=== Deploy Device Intelligence Dashboard v2 ==="
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

echo "→ Step 6: Test new device API endpoints..."
TEST_IP="192.168.1.113"

echo "   Testing /api/devices/$TEST_IP/categories..."
CAT=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/devices/$TEST_IP/categories" 2>/dev/null)
CAT_COUNT=$(echo "$CAT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('categories',[])))" 2>/dev/null || echo "error")
echo "   Categories: $CAT_COUNT"

echo "   Testing /api/devices/$TEST_IP/alerts..."
ALERTS=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/devices/$TEST_IP/alerts?limit=5" 2>/dev/null)
ALERT_COUNT=$(echo "$ALERTS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'total={d.get(\"total\",0)} returned={len(d.get(\"alerts\",[]))}')" 2>/dev/null || echo "error")
echo "   Alerts: $ALERT_COUNT"

echo "   Testing /api/devices/$TEST_IP/ports..."
PORTS=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/devices/$TEST_IP/ports" 2>/dev/null)
PORT_COUNT=$(echo "$PORTS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('ports',[])))" 2>/dev/null || echo "error")
echo "   Ports: $PORT_COUNT"

echo "   Testing /api/risk/scores/$TEST_IP..."
RISK=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/risk/scores/$TEST_IP" 2>/dev/null)
RISK_INFO=$(echo "$RISK" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'score={d.get(\"score\",\"?\")} level={d.get(\"level\",\"?\")} factors={len(d.get(\"factors\",[]))}')" 2>/dev/null || echo "error")
echo "   Risk: $RISK_INFO"

echo "   Testing enhanced /api/devices/$TEST_IP..."
DETAIL=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/devices/$TEST_IP" 2>/dev/null)
DETAIL_INFO=$(echo "$DETAIL" | python3 -c "import sys,json; d=json.load(sys.stdin).get('device',{}); print(f'orig_bytes={d.get(\"orig_bytes\",\"missing\")} unique_dests={d.get(\"unique_destinations\",\"missing\")} services={len(d.get(\"top_services\",[]))}')" 2>/dev/null || echo "error")
echo "   Detail v2: $DETAIL_INFO"
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo ""
echo "Open https://nettap.bitspec.co/devices/192.168.1.113 to see:"
echo "  - Device identity header with risk gauge + status dot"
echo "  - 6 stat cards (bandwidth DL/UL, upload ratio, connections, alerts, unique dests, first seen)"
echo "  - Bandwidth over time chart"
echo "  - Traffic categories + top services (2-column)"
echo "  - Risk factor breakdown + recent alerts (2-column)"
echo "  - Top destinations + DNS activity + top ports (3-column)"
echo "  - Clickable connections → drill-down drawer with TShark analysis"
