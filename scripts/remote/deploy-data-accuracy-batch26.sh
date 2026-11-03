#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 26 (Security Posture page) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #81 Security Posture (/compliance) crashed on every visit and stayed on "Calculating...":
#       the web client read `scores`, but /api/risk/scores sends `devices`
#
# Only the web container is rebuilt. Open /compliance afterwards: it must show its six cards.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch26.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: dashboard data accuracy, batch 26 (Security Posture page) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
PULLED=1
for attempt in 1 2 3 4 5; do
    if git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; then PULLED=0; break; fi
    echo "   pull failed (attempt $attempt/5), retrying in 5 s..."
    sleep 5
done
if [ "$PULLED" -ne 0 ]; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build and recreate the web container..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
STATUS="unknown"
for _ in $(seq 1 36); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$STATUS"
echo ""

echo "→ Step 3: Checks..."
# The fix runs in the browser: the page itself is checked by opening /compliance
CODE=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/compliance)
case "$CODE" in 200|302|303) rc=0 ;; *) rc=1 ;; esac
check "#81 /compliance answers" "$rc" "HTTP $CODE"
echo ""

echo "→ Step 4: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 26 deployed and verified — open /compliance to see the six cards ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
