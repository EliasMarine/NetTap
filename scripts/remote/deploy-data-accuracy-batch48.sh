#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 48 and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #131: TShark's page says a filter search stopped before the end of the file instead of
#     "no packets matching"; the acceptance check tries up to 3 files and honours the flag.
#   Rebuilds only the web container, then runs the acceptance check and batch 47's names check.
#
# The full output is also saved to ~/nettap-batch48.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch48.sh
set -u
exec > >(tee "$HOME/nettap-batch48.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

echo "=== Deploy: dashboard data accuracy, batch 48 (TShark stopped-early wording) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build and recreate the web container..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ nettap-web build failed — nothing was restarted"
    exit 1
fi
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
STATUS="unknown"
for _ in $(seq 1 30); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then echo "   ✓ nettap-web health: healthy"; else echo "   ✗ nettap-web health: $STATUS"; FAILED=1; fi
echo ""

echo "→ Step 3: Devices names match Home..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_batch47.py")" 2>&1)
RC=$?
printf '%s\n' "$OUT" | sed 's/^/   /'
[ "$RC" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 4: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 48 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
