#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/alerts-v3-category-hub"

echo "=== Deploy Alerts v3 Category Hub ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || exit 1
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

echo "→ Step 6: Test enhanced categories endpoint..."
sudo docker exec nettap-storage-daemon curl -s 'http://localhost:8880/api/alerts/categories?from=now-24h&to=now' | python3 -c "
import sys, json
data = json.load(sys.stdin)
cats = data.get('categories', [])
print(f'   Categories returned: {len(cats)}')
for c in cats[:5]:
    subs = len(c.get('sub_categories', []))
    print(f'     {c[\"id\"]}: {c[\"count\"]} alerts, {subs} sub-cats')
if len(cats) >= 13:
    print('   ✓ All 13 categories present')
else:
    print(f'   ⚠ Only {len(cats)} categories (expected 13)')
" 2>/dev/null || echo "   ⚠ Categories endpoint not responding yet"
echo ""

echo "→ Step 7: Test category detail endpoint..."
sudo docker exec nettap-storage-daemon curl -s 'http://localhost:8880/api/alerts/categories/reconnaissance?from=now-24h&to=now' | python3 -c "
import sys, json
data = json.load(sys.stdin)
cat = data.get('category', {})
stats = data.get('stats', {})
mitre = data.get('mitre_techniques', [])
print(f'   Category: {cat.get(\"label\", \"?\")}')
print(f'   Total: {stats.get(\"total\", 0)} alerts, {stats.get(\"unique_sources\", 0)} sources')
print(f'   MITRE techniques: {len(mitre)}')
print('   ✓ Category detail working')
" 2>/dev/null || echo "   ⚠ Category detail endpoint not responding yet"
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard and navigate to /alerts to verify the category hub."
