#!/usr/bin/env bash
# Deploy NET-192 PR 4 (web only): one look on every page: en-GB 24-hour times, one range set,
# the Auto/Paused button, stale notes, voice, Threats/IoT/Settings structure.
#
# Only nettap-web is rebuilt and recreated. Checks: the build carries the Auto/Paused button,
# the web answers its health check and serves the sign-in page, and every request the pages'
# new long ranges make (30 d; 7 d on Connections) answers within 80% of its proxy timeout.
#
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=feature/ui-consistency-pr4 bash /home/nettap/NetTap/scripts/remote/deploy-ui-consistency.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy one look on every page (NET-192 PR 4) from $BRANCH ==="
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

echo "→ Step 5: Check the build carries PR 4..."
# The Auto/Paused button's title exists only in PR 4's build.
if sudo docker exec nettap-web sh -c "grep -rqs 'Refreshes every' /app/build" 2>/dev/null; then rc=0; else rc=1; fi
check "Auto/Paused button in the build" "$rc" "nettap-web"
LOGIN=$(sudo docker exec nettap-web node -e "fetch('http://localhost:3000/login').then(r=>console.log(r.status)).catch(()=>console.log(0))")
if [ "$LOGIN" = "200" ]; then rc=0; else rc=1; fi
check "sign-in page" "$rc" "HTTP $LOGIN"
echo ""

echo "→ Step 5b: Long ranges answer in time (30 d; 7 d on Connections)..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_long_range_timings.py")" 2>&1)
RC=$?
printf '%s\n' "$OUT" | sed 's/^/   /'
check "long-range requests within their proxy timeouts" "$RC" "exit $RC"
echo ""

echo "→ Step 6: Web log errors since the restart..."
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed. Open Home, DNS, Connections, Live, IoT, Threats and Settings to look. ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
exit "$FAILED"
