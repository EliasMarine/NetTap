#!/usr/bin/env bash
# Deploy NET-269 and NET-270 from main. Web UI only; the daemon is untouched.
#
#   NET-269: the device page that Devices › By type opens (/devices/mac/<mac>) gets the
#     Compare periods button and the Leases › DHCP history link (they were on /devices/<ip> only).
#   NET-270: a chart's highlight column stays a narrow column inside the chart; with a few
#     points (a picked few minutes) it painted a big grey box over the sidebar.
#   The web UI is down for under a minute while it restarts.
#
# The full output is also saved to ~/nettap-device-compare-mac.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-device-compare-mac.sh
# To test a branch first: BRANCH=<branch> bash …
set -u
exec > >(tee "$HOME/nettap-device-compare-mac.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
BAND_FIX="346f6d92"  # NET-270 on main (#270)
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: Compare periods on the MAC device page (NET-269) + chart band (NET-270) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
if git merge-base --is-ancestor "$BAND_FIX" HEAD 2>/dev/null; then rc=0; else rc=1; fi
check "the chart band fix is in this code" "$rc" "$BAND_FIX"
echo ""

echo "→ Step 2: Build the web UI..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — the running container was not touched"
    exit 1
fi
echo "   ✓ Built"
echo ""

echo "→ Step 3: Recreate it and wait for health..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
STATUS="unknown"
for _ in $(seq 1 30); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    echo "   waiting... web=$STATUS"
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$STATUS"
echo ""

echo "→ Step 4: The new build is the one serving..."
# string literals survive minification; "could not be found in the registry" is the MAC page's own text
MAC_PAGE=$(sudo docker exec nettap-web grep -rlF "could not be found in the registry" /app/build/client/_app/immutable/nodes 2>/dev/null | head -1)
if [ -n "$MAC_PAGE" ]; then rc=0; else rc=1; fi
check "found the MAC device page in the build" "$rc" "${MAC_PAGE:-none}"
for want in "Compare periods" "/tools/dhcp-timeline?mac=" "cmp-ip"; do
    if [ -n "$MAC_PAGE" ] && sudo docker exec nettap-web grep -qF "$want" "$MAC_PAGE"; then rc=0; else rc=1; fi
    check "the MAC page has \"$want\"" "$rc" "NET-269"
done
if sudo docker exec nettap-web grep -rqF "may have belonged to another device before" /app/build/client; then rc=0; else rc=1; fi
check "the compare card names the address it compares" "$rc" "NET-269"
echo ""

echo "→ Step 5: Web log since the restart..."
ERRS=$(sudo docker logs nettap-web --since 10m 2>&1 | grep -cE "ERROR|Traceback")
if [ "$ERRS" -eq 0 ]; then rc=0; else rc=1; fi
check "no errors in the nettap-web log" "$rc" "$ERRS ERROR/Traceback lines"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deployed and verified — open Devices › By type › a device: Compare periods is at top right ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
