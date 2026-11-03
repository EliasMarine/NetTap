#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/connections-v3"

echo "=== Deploy PCAP Collection Controls ==="
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

echo "→ Step 6: Test capture status API..."
CAPTURE_STATUS=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/capture/status 2>/dev/null)
if echo "$CAPTURE_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  enabled={d[\"enabled\"]}  maxFileSizeMB={d[\"maxFileSizeMB\"]}  containerRunning={d[\"containerRunning\"]}')" 2>/dev/null; then
    echo "   ✓ Capture status API working"
else
    echo "   ⚠ Capture status API returned: $CAPTURE_STATUS"
fi
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-pcap-capture"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard and check:"
echo "  1. PCAP page → toggle switch in header (green dot = active)"
echo "  2. Settings → Capture tab (file size config)"
