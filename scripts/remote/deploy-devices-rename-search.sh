#!/usr/bin/env bash
# Deploy NET-201 and NET-202 (web only):
#   - a device opened from All devices (the IP device page) has Rename and Change picture too;
#   - Devices › By type shows the list only (the cards are gone);
#   - the search box opens an IP's own page (device page on the LAN, address page otherwise),
#     a device by its name or MAC, a domain's page, and lists your devices as suggestions.
#
# Only nettap-web is rebuilt and recreated. Checks: the build carries all three changes and no
# longer has the Cards / List switch, the web answers its health check and serves the sign-in page.
#
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=fix/devices-rename-all-devices-list-view bash /home/nettap/NetTap/scripts/remote/deploy-devices-rename-search.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy device renames from All devices, list-only By type and search (NET-201, NET-202) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# A failed checkout or pull would rebuild the old code, so stop here instead
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code at $(git log --oneline -1)"
echo ""

echo "→ Step 2: Rebuild the web container..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
if "${COMPOSE[@]}" build nettap-web; then rc=0; else rc=1; fi
check "image built" "$rc" "nettap-web"
if [ "$rc" -ne 0 ]; then
    echo ""
    echo "=== Stopped: the build failed; the running container was left as it was ==="
    exit 1
fi
echo ""

echo "→ Step 3: Recreate the web container (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
echo ""

echo "→ Step 4: Wait for it to become healthy..."
WEB_STATUS=unknown
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "web healthy" "$rc" "web=$WEB_STATUS"
echo ""

echo "→ Step 5: Check the build carries the changes..."
# Each string exists only in this build: the IP page's one-save-per-device message, and search's
# "several devices share this name" announcement.
if sudo docker exec nettap-web sh -c "grep -rqs 'A change to this device is still saving' /app/build" 2>/dev/null; then rc=0; else rc=1; fi
check "Rename on the IP device page" "$rc" "nettap-web"
if sudo docker exec nettap-web sh -c "grep -rqs 'devices are called' /app/build" 2>/dev/null; then rc=0; else rc=1; fi
check "search opens devices, IPs and domains" "$rc" "nettap-web"
# The Cards / List switch remembered its choice under this key; the list-only build never names it.
if sudo docker exec nettap-web sh -c "grep -rqs 'nettap-devices-layout' /app/build" 2>/dev/null; then rc=1; else rc=0; fi
check "By type has no Cards / List switch" "$rc" "nettap-web"
LOGIN=$(sudo docker exec nettap-web node -e "fetch('http://localhost:3000/login').then(r=>console.log(r.status)).catch(()=>console.log(0))")
if [ "$LOGIN" = "200" ]; then rc=0; else rc=1; fi
check "sign-in page" "$rc" "HTTP $LOGIN"
echo ""

echo "→ Step 6: Web log errors since the restart..."
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed. Open Devices › All devices, click a device, then Rename; or search an IP. ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
exit "$FAILED"
