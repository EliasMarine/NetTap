#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/connections-v3"

echo "=== Deploy TShark Analysis Fix ==="
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

echo "→ Step 3: Rebuild web container..."
sudo docker compose -f docker/docker-compose.yml build nettap-web
echo "   ✓ Web container rebuilt"
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

echo "→ Step 6: Test TShark API..."
sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/tshark/status | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"   TShark available: {d.get('available')}\")
print(f\"   Version: {d.get('version')}\")
" || echo "   (API check failed — container may still be starting)"
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Test in browser:"
echo "  1. Open a connection drawer on /devices/[ip] → TShark tab"
echo "  2. Click Summary → Analyze (should find packets across multiple PCAPs)"
echo "  3. Click Verbose → Analyze (should show full protocol tree)"
echo "  4. Click Follow Stream → Analyze (should show reassembled stream)"
echo "  5. Click 'Open in TShark Tool' (should navigate to /tools/tshark with filter)"
echo "  6. Open a connection drawer on /connections → same buttons should appear"
