#!/usr/bin/env bash
# Deploy the sort-sweep follow-ups (#142, #143) from main. Web UI only; the daemon is untouched.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #142: severity sorts most-severe-first with a ↓ arrow (Alerts, alert categories, Home),
#     the Alerts Protocol column sorts, Certificates put blanks last, Connections sort by IP
#     then port, Infrastructure sorts index sizes as sizes and health red-first.
#   #143: the web proxy forwards a device's connection sort, so the device page's
#     Connections table really sorts (it stayed newest first).
#   The web UI is down for under a minute while it restarts.
#
# The full output is also saved to ~/nettap-sort-followups.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-sort-followups.sh
set -u
exec > >(tee "$HOME/nettap-sort-followups.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: sort-sweep follow-ups (#142, #143) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
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
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$STATUS"
echo ""

echo "→ Step 4: The new build is the one serving (#142)..."
# byteSize's size pattern is a regex literal, so it survives minification
if sudo docker exec nettap-web grep -rqF 'kb|mb|gb|tb|pb' /app/build/client; then rc=0; else rc=1; fi
check "web build has the #142 sort helpers" "$rc" "byteSize pattern in /app/build/client"
echo ""

echo "→ Step 5: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Web log since the restart..."
ERRS=$(sudo docker logs nettap-web --since 10m 2>&1 | grep -cE "ERROR|Traceback")
if [ "$ERRS" -eq 0 ]; then rc=0; else rc=1; fi
check "no errors in the nettap-web log" "$rc" "$ERRS ERROR/Traceback lines"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== #142 and #143 deployed and verified — open Alerts and click Severity: most severe first, ↓ ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
