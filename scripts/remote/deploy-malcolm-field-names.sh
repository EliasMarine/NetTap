#!/usr/bin/env bash
# Deploy the daemon + web query fix for Malcolm's real field mapping (Chain 24).
#
# Once malcolm_template applies (fix-index-template.sh), fields like source.ip
# are ip/keyword with no .keyword sub-field. The daemon and web queried the
# .keyword names, so the devices page and other views came back empty.
#
# Run as the normal user (NOT with sudo), after fix-index-template.sh:
#   bash /home/nettap/NetTap/scripts/remote/deploy-malcolm-field-names.sh
set -u

REPO_DIR="/home/nettap/NetTap"
# OLD CODE START — 2026-11-08: fix/index-template-pattern is merged; the device runs main (NET-214)
# BRANCH="fix/index-template-pattern"
# OLD CODE END
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

api() {
    local token
    token=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)
    # OLD CODE (NET-237: the token was on the command line, visible in ps):
    # curl -s -m 20 -H "X-NetTap-Daemon-Token: $token" "http://localhost:8880$1"
    printf 'X-NetTap-Daemon-Token: %s\n' "$token" | curl -s -m 20 -H @- "http://localhost:8880$1"
}

echo "=== Deploy: daemon + web use Malcolm's field names ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Rebuild the daemon and web images..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images rebuilt"
echo ""

echo "→ Step 3: Recreate the daemon and web (OpenSearch and capture are not touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo "   ✓ Recreated"
echo ""

echo "→ Step 4: Wait for both to become healthy..."
WEB_STATUS="unknown"
DAEMON_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        echo "   ✓ Both healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" != "healthy" ] || [ "$DAEMON_STATUS" != "healthy" ]; then
    echo "   ✗ Not healthy after 150s — see: sudo docker logs nettap-storage-daemon --tail 50"
    FAILED=1
fi
echo ""

echo "→ Step 5: Dashboard APIs return data..."
CONNS=$(api /api/traffic/summary | grep -o '"connection_count": *[0-9]*' | grep -o '[0-9]*$')
DEVICES=$(api "/api/devices?limit=500" | grep -o '"ip": *"' | wc -l | tr -d ' ')
TALKERS=$(api "/api/traffic/top-talkers?limit=5" | grep -o '"ip": *"' | wc -l | tr -d ' ')
echo "   traffic summary connections: ${CONNS:-none}"
echo "   devices: $DEVICES"
echo "   top talkers: $TALKERS"
if [ -n "$CONNS" ] && [ "$CONNS" -gt 0 ] && [ "$DEVICES" -gt 0 ]; then
    echo "   ✓ Traffic and devices are populated"
else
    echo "   ✗ Still empty — check: sudo docker logs nettap-storage-daemon --since 5m | grep -iE 'error|exception'"
    FAILED=1
fi
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete — open https://<this box's IP> and test ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
