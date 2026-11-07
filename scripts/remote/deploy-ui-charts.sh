#!/usr/bin/env bash
# Deploy NET-192 PR 1 (web only): charts fill their cards, 1024 px rows, the visible layout breakage.
#
# Only nettap-web is rebuilt and recreated. Checks: the build carries both new a11y.css
# corrections (8: half-width rows at 1024 px; 9: the donut in a col card), the web answers its
# health check and serves the sign-in page. The pages themselves are checked by eye on the
# dashboard: DNS, Alerts, Live, IoT, Compliance at full width and at about 1024 px.
#
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=feature/ui-consistency-speed bash /home/nettap/NetTap/scripts/remote/deploy-ui-charts.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy charts that fill their cards (NET-192 PR 1) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
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

echo "→ Step 3: Recreate the web container..."
"${COMPOSE[@]}" up -d --force-recreate nettap-web
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

echo "→ Step 5: Check the build carries the new corrections..."
# Correction 8 counts a .stack as full width; correction 9 places the donut svg absolutely.
# The minifier may drop spaces, so match without them.
CSS_HITS=$(sudo docker exec nettap-web sh -c "cat /app/build/client/_app/immutable/assets/*.css" 2>/dev/null | tr -d ' ' | grep -o -e '\.c-12,\.stack' -e '\.donut-box>svg' | sort -u | wc -l)
if [ "$CSS_HITS" -eq 2 ]; then rc=0; else rc=1; fi
check "a11y.css corrections 8 and 9 in the build" "$rc" "$CSS_HITS of 2 found"
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
    echo "=== Deploy complete: every check passed. Open DNS, Alerts, Live, IoT and Compliance to look. ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
exit "$FAILED"
