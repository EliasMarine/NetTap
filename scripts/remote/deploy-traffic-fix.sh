#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/traffic-category-duplicate-services"

echo "=== Deploy Traffic Category Fix ==="
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

echo "→ Step 6: Test traffic categories API..."
CATEGORIES=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/traffic/categories 2>/dev/null)
CAT_COUNT=$(echo "$CATEGORIES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('categories',[])))" 2>/dev/null || echo "0")
echo "   Categories returned: $CAT_COUNT"
echo ""

echo "→ Step 7: Test category detail API (cloud — was broken)..."
DETAIL=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/traffic/categories/cloud" 2>/dev/null)
DEVICE_COUNT=$(echo "$DETAIL" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('device_count',0))" 2>/dev/null || echo "0")
SVC_NAMES=$(echo "$DETAIL" | python3 -c "import sys,json; d=json.load(sys.stdin); names=[s['name'] for s in d.get('services',[])]; dupes=[n for n in names if names.count(n)>1]; print(f'services={len(names)} dupes={len(set(dupes))}')" 2>/dev/null || echo "parse error")
echo "   Cloud category devices: $DEVICE_COUNT"
echo "   Service dedup check: $SVC_NAMES"
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard and click Cloud (or any traffic category) to verify no more loading spinner."
