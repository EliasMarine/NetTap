#!/usr/bin/env bash
# Deploy the release-audit fixes (daemon + web UI).
# Plan: .codex-review/2026-11-08-221633-release-audit/PLAN.md
#
# F4 moves alert suppressions, baselines and the threat-intel cache from the daemon's /tmp
# (a tmpfs that dies with the container) to /opt/nettap/data. Step 3 copies them across BEFORE
# the daemon is recreated; if that fails, the script stops and the running daemon is untouched.
#
# Run as the normal user (NOT with sudo), on the device:
#   bash scripts/remote/deploy-release-audit.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"  # was fix/release-audit-2026-11 until PR #236 merged
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
STATE_FILES=(nettap-suppress.json nettap-baselines.json nettap-threat-intel.json)  # as in migrate-daemon-state.sh
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy the release-audit fixes from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web UI and the daemon..."
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — the running containers were not touched"
    exit 1
fi
echo "   ✓ Built"
echo ""

echo "→ Step 3: Move the daemon's state from its /tmp to /opt/nettap/data (before the recreate)..."
MIGRATED=""
if [ "$(sudo docker inspect -f '{{.State.Running}}' nettap-storage-daemon 2>/dev/null)" = "true" ]; then
    # names present now, so Step 6 can check each one arrived
    MIGRATED=$(sudo docker exec nettap-storage-daemon sh -c 'cd /tmp && for f in "$@"; do [ -f "$f" ] && echo "$f"; done' sh "${STATE_FILES[@]}")
    # the helper runs in the container's own sh; its text is one argument, the dirs are $1 $2
    if ! sudo docker exec nettap-storage-daemon sh -c "$(cat "$REPO_DIR/scripts/remote/migrate-daemon-state.sh")" \
            migrate /tmp /opt/nettap/data; then
        echo "   ✗ The move failed. Nothing was recreated: the daemon still runs the old code with its"
        echo "     state in /tmp. Fix the error above and run this script again (it recopies everything)."
        exit 1
    fi
else
    echo "   - The daemon isn't running, so its /tmp is already gone: nothing to move"
fi
echo ""

echo "→ Step 4: Recreate the web UI and the daemon..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web nettap-storage-daemon
echo "   ✓ Containers recreated"
echo ""

echo "→ Step 5: Wait for containers to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        echo "   ✓ Both containers healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
[ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ] || check "containers healthy" 1 "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 6: Verify the fixes..."
SUPPRESS_PATH=$(sudo docker exec nettap-storage-daemon python3 -c 'import services.alert_intelligence as a; print(a._SUPPRESS_PATH)' 2>/dev/null)
if [ "$SUPPRESS_PATH" = "/opt/nettap/data/nettap-suppress.json" ]; then rc=0; else rc=1; fi
check "F4 state on the persistent volume" "$rc" "suppressions at ${SUPPRESS_PATH:-unknown}"
for f in $MIGRATED; do
    if sudo docker exec nettap-storage-daemon test -f "/opt/nettap/data/$f"; then rc=0; else rc=1; fi
    check "F4 $f carried over" "$rc" "/opt/nettap/data/$f"
done

# F1, F2 and F6 are checked by the smoke test in Step 8
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

echo "→ Step 8: Smoke test (read-only): F1 traffic totals, F2 pipeline check, F6 public health..."
# pipefail, so a failed smoke test fails this deploy despite the sed
if ! (set -o pipefail; bash "$REPO_DIR/scripts/remote/smoke-test-release.sh" | sed 's/^/   /'); then
    FAILED=1
fi
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy Complete: every check passed ==="
else
    echo "=== Deploy finished with failed checks (✗ above) ==="
fi
echo "Open the dashboard to verify."
[ "$FAILED" -eq 0 ]
