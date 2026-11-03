#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/manual-data-cleanup"

echo "=== Deploy Manual Data Cleanup Feature ==="
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

echo "→ Step 6: Test cleanup preview API..."
PREVIEW_RESULT=$(sudo docker exec nettap-storage-daemon curl -s -X POST http://localhost:8880/api/storage/cleanup/preview \
    -H "Content-Type: application/json" \
    -d '{"older_than_days": 365}')
echo "   Preview response (data older than 365 days):"
echo "   $PREVIEW_RESULT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'   Indices: {d.get(\"total_indices\", \"?\")}, PCAPs: {d.get(\"total_pcap_files\", \"?\")}, Size: {d.get(\"estimated_freed_bytes\", 0) / 1024 / 1024:.1f} MB')
except:
    print(f'   Raw: {sys.stdin.read()[:200]}')
" 2>/dev/null || echo "   $PREVIEW_RESULT"
echo ""

echo "→ Step 7: Test storage status API..."
sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/storage/status | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'   Disk: {d.get(\"disk_usage_percent\", \"?\")}% used')
    print(f'   Indices: {d.get(\"total_indices\", \"?\")} total')
    print(f'   Retention: hot={d.get(\"hot_days\",\"?\")}d, warm={d.get(\"warm_days\",\"?\")}d, cold={d.get(\"cold_days\",\"?\")}d')
except:
    print('   Could not parse response')
" 2>/dev/null
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard → Settings → Retention tab to see the new Manual Data Cleanup section."
