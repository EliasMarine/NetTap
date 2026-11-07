#!/usr/bin/env bash
# Deploy owner device names and pictures (NET-200) and check them end to end on the device.
#
# Rebuilds the daemon (the names and pictures store, its routes, owner names on every device
# list) and the web container (the Rename and Change picture panels, the image proxy). The
# nginx container is recreated too: its request limit rose from 10 MB to 16 MB, matching the
# web container's BODY_SIZE_LIMIT and the daemon's, so a backup holding photos can be restored.
# Then:
#   - checks the three request limits are live;
#   - runs scripts/remote/verify-device-names.py inside the daemon container: sets and clears a
#     name, an icon and a photo on one uncustomised device, checks the replies, the photo's
#     headers and version rule, the refusals, and the backup sections. The device ends as it began.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-device-names-pictures.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

check_eq() {  # check_eq LABEL ACTUAL EXPECTED
    if [ "$2" = "$3" ]; then echo "   ✓ $1 ($2)"; else echo "   ✗ $1 ($2, expected $3)"; FAILED=1; fi
}

echo "=== Deploy: device names and pictures (NET-200) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# A failed checkout or pull would rebuild the old code, so stop here instead
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Rebuild the daemon and web containers..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the daemon, web and nginx containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web nettap-nginx
echo ""

echo "→ Step 4: Wait for the daemon and web containers to become healthy..."
WEB_STATUS="unknown"
DAEMON_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
    echo "   ✓ Both containers healthy"
else
    echo "   ✗ Not healthy after 150 s: web=$WEB_STATUS daemon=$DAEMON_STATUS"
    echo "     Logs: sudo docker logs nettap-storage-daemon --tail 50"
    exit 1
fi
NGINX_STATE=$(sudo docker inspect --format='{{.State.Status}}' nettap-nginx 2>/dev/null || echo "missing")
check_eq "nginx running" "$NGINX_STATE" "running"
echo ""

echo "→ Step 5: Request limits (16 MB on all three layers)..."
NGINX_LIMIT=$(sudo docker exec nettap-nginx nginx -T 2>/dev/null | grep -m1 -o 'client_max_body_size [^;]*' || echo "none")
check_eq "nginx limit" "$NGINX_LIMIT" "client_max_body_size 16m"
WEB_LIMIT=$(sudo docker exec nettap-web printenv BODY_SIZE_LIMIT 2>/dev/null || echo "unset")
check_eq "web BODY_SIZE_LIMIT" "$WEB_LIMIT" "16M"
DAEMON_LIMIT=$(sudo docker exec nettap-storage-daemon python3 -c "from api.server import MAX_REQUEST_BYTES; print(MAX_REQUEST_BYTES)" 2>/dev/null || echo "unknown")
check_eq "daemon client_max_size" "$DAEMON_LIMIT" "16777216"
echo ""

echo "→ Step 6: Names and pictures end to end (inside the daemon container)..."
# shellcheck disable=SC2024  # the script is read as this user on purpose; only docker needs sudo
sudo docker exec -i nettap-storage-daemon python3 - < "$REPO_DIR/scripts/remote/verify-device-names.py" 2>&1 | grep -v "Warning"
VERIFY=${PIPESTATUS[0]}
check "verify-device-names.py" "$VERIFY" "exit $VERIFY"
echo ""

echo "→ Step 7: The store on the data volume..."
sudo docker exec nettap-storage-daemon sh -c 'ls -la /opt/nettap/data/device_custom.json /opt/nettap/data/device-pictures 2>&1 | head -n 8'
sudo docker logs nettap-storage-daemon --since 5m 2>&1 | grep -i "device names file\|device picture" | tail -n 5
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-nginx"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
    echo "Open a device's page, then Rename or Change picture."
else
    echo "=== Deploy finished with failures (✗ above) ==="
    exit 1
fi
