#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 53 and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #139: the threat report (8-13 s), risk scores (7.5 s) and beaconing (5.6 s) ran their
#     OpenSearch queries on the daemon's one request loop, so every other request waited and
#     the top bar's 5 s liveness check said "Can't reach NetTap" while /threats or /compliance
#     loaded. They now run in worker threads, and the report's three checks run side by side.
#   Only the daemon is rebuilt; the UI keeps working throughout.
#
# The full output is also saved to ~/nettap-batch53.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch53.sh
set -u
exec > >(tee "$HOME/nettap-batch53.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

run_in_daemon() {  # run_in_daemon FILE: a read-only check script inside the daemon container
    sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/$1")" 2>&1 | sed 's/^/   /'
    [ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
}

echo "=== Deploy: dashboard data accuracy, batch 53 (slow pages no longer hold up the daemon) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build and recreate the daemon..."
"${COMPOSE[@]}" build nettap-storage-daemon
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
STATUS="unknown"
for _ in $(seq 1 30); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-storage-daemon health" "$rc" "$STATUS"
echo ""

echo "→ Step 3: The liveness check answers while the slow pages run (#139)..."
run_in_daemon verify_request_loop.py
echo ""

echo "→ Step 4: The threat report's figures are unchanged (batch 37 check)..."
run_in_daemon verify_batch37.py
echo ""

echo "→ Step 5: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Daemon log since the restart..."
ERRS=$(sudo docker logs nettap-storage-daemon --since 10m 2>&1 | grep -cE "ERROR|Traceback")
if [ "$ERRS" -eq 0 ]; then rc=0; else rc=1; fi
check "no errors in the daemon log" "$rc" "$ERRS ERROR/Traceback lines"
[ "$ERRS" -eq 0 ] || sudo docker logs nettap-storage-daemon --since 10m 2>&1 | grep -E "ERROR|Traceback" | tail -5 | sed 's/^/     | /'
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 53 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
