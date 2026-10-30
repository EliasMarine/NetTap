#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/infrastructure-redesign"

echo "=== Deploy Phase 4: Infrastructure + Live Monitor + UniFi + Self-Traffic Exclusion ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "ERROR: Cannot cd to $REPO_DIR"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code updated"
echo ""

echo "→ Step 2: Set MGMT_IP for self-traffic exclusion..."
if ! grep -q "^MGMT_IP=" docker/.env 2>/dev/null; then
    # Auto-detect the management IP from br0 or eth0
    DETECTED_IP=$(ip -4 addr show br0 2>/dev/null | grep -oP 'inet \K[^/]+' || ip -4 addr show eth0 2>/dev/null | grep -oP 'inet \K[^/]+' || echo "")
    if [ -n "$DETECTED_IP" ]; then
        echo "MGMT_IP=$DETECTED_IP" >> docker/.env
        echo "   ✓ Auto-detected and set MGMT_IP=$DETECTED_IP"
    else
        echo "   ⚠ Could not auto-detect MGMT_IP — set manually in docker/.env"
    fi
else
    EXISTING_IP=$(grep "^MGMT_IP=" docker/.env | cut -d= -f2)
    echo "   ✓ MGMT_IP already set: $EXISTING_IP"
fi
echo ""

echo "→ Step 3: Rebuild web container (no cache)..."
sudo docker compose -f docker/docker-compose.yml build --no-cache nettap-web
echo "   ✓ Web container rebuilt"
echo ""

echo "→ Step 4: Rebuild daemon container (no cache)..."
sudo docker compose -f docker/docker-compose.yml build --no-cache nettap-storage-daemon
echo "   ✓ Daemon container rebuilt"
echo ""

echo "→ Step 5: Restart containers (web + daemon + nginx)..."
sudo docker compose -f docker/docker-compose.yml up -d nettap-web nettap-storage-daemon nettap-nginx --force-recreate
echo "   ✓ Containers restarted"
echo ""

echo "→ Step 6: Wait for containers to become healthy..."
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

echo "→ Step 7: Verify self-traffic exclusion..."
EXCLUDED=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/settings/excluded-ips 2>/dev/null || echo "FAILED")
echo "   Excluded IPs: $EXCLUDED"
echo ""

echo "→ Step 8: Verify live dashboard API..."
DASHBOARD=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/live/dashboard?limit=5 2>/dev/null || echo "FAILED")
if echo "$DASHBOARD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   connections: {d[\"count\"]}, arcs: {len(d[\"geo_arcs\"])}, top_country: {d[\"stats\"][\"top_country\"]}')" 2>/dev/null; then
    echo "   ✓ Live dashboard API working"
else
    echo "   ⚠ Dashboard API returned: ${DASHBOARD:0:200}"
fi
echo ""

echo "→ Step 9: Verify UniFi integration status..."
UNIFI=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/integrations/unifi/status 2>/dev/null || echo "FAILED")
echo "   UniFi status: $UNIFI"
echo ""

echo "→ Step 10: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-nginx"
echo ""

echo "=== Deploy Complete ==="
echo ""
echo "Next steps:"
echo "  1. Open the dashboard and verify the /live page shows the world map with arcs"
echo "  2. Check that your device IP is excluded from logs (Settings → Network → Excluded IPs)"
echo "  3. To configure UniFi: Settings → Integrations → paste API key from UniFi controller"
echo "  4. After UniFi config: Infrastructure page shows APs, switches, firewall, networks"
