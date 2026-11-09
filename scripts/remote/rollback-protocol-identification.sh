#!/usr/bin/env bash
# Roll back NET-219 (plan .codex-review/2026-11-08-unidentified-protocols/PLAN.md, "Rollback"):
# check the device out at the revision deploy-protocol-identification.sh recorded before it changed
# anything, rebuild the daemon and the web UI, and recreate zeek-live, the daemon and the web UI.
# Malcolm's defaults come back: QUIC analyzer off, ICS analyzers on.
#
# Run as the normal user (NOT with sudo). It needn't exist in the revision it goes back to:
#   git -C /home/nettap/NetTap fetch origin
#   bash <(git -C /home/nettap/NetTap show origin/main:scripts/remote/rollback-protocol-identification.sh) [--force] [<revision>]
# (before the PR merges, origin/fix/unidentified-protocols instead of origin/main).
# With no revision it reads ~/.nettap-deploys/protocol-identification.baseline. After a rollback
# with every check passing, that file is renamed, so a later rollout records a fresh one.
# It refuses when the checkout has moved on since the NET-219 deploy (a rollback would also undo the
# later changes, which it lists); --force rolls back anyway.
set -u

REPO_DIR="/home/nettap/NetTap"
BASELINE="$HOME/.nettap-deploys/protocol-identification.baseline"
DEPLOYED="$HOME/.nettap-deploys/protocol-identification.deployed"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
FORCE=0
if [ "${1:-}" = "--force" ]; then FORCE=1; shift; fi

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_healthy() {  # wait_healthy CONTAINER
    local status="unknown"
    for _ in $(seq 1 30); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$1" 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && break
        sleep 5
    done
    if [ "$status" = "healthy" ]; then check "$1 health" 0 "$status"; else check "$1 health" 1 "$status"; fi
}

# The deploy writes the revision it left in $DEPLOYED. Any other checkout means a later deploy
# moved the device on, and going back would undo that too (security review L1). Tested in
# tests/scripts/test_protocol_identification.bats.
same_as_deployed() {  # 0 when the checkout is still the one the NET-219 deploy left
    local head="" deployed=""
    head=$(git rev-parse HEAD) && deployed=$(cat "$DEPLOYED" 2>/dev/null) && [ "$head" = "$deployed" ] && return 0
    echo "   ✗ The device has moved on since the NET-219 deploy (deployed ${deployed:-unknown}, now ${head:-unknown}),"
    echo "     so this would also undo the later changes above. Nothing was changed."
    echo "     To roll back anyway, run it again with --force as the first argument."
    return 1
}

echo "=== Roll back NET-219 (protocol identification) ==="
echo ""

echo "→ Step 1: Find the revision to go back to..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin || echo "   - git fetch failed; using the revisions already here"
if [ $# -ge 1 ]; then
    TARGET="$1"
    echo "   Revision given: $TARGET"
elif [ -s "$BASELINE" ]; then
    TARGET=$(sed -n 's/^revision=//p' "$BASELINE")
    echo "   From $BASELINE:"
    sed 's/^/     /' "$BASELINE"
else
    echo "   ✗ No rollback point at $BASELINE; pass the revision the device ran before NET-219"
    exit 1
fi
if ! REV=$(git rev-parse --verify --quiet "${TARGET}^{commit}"); then
    echo "   ✗ '$TARGET' is not a commit in $REPO_DIR — nothing was changed"
    exit 1
fi
if git show "$REV:docker/docker-compose.yml" | grep -q 'ZEEK_DISABLE_SPICY_QUIC: "false"'; then
    echo "   ✗ $REV still has NET-219 (QUIC on in docker-compose.yml); pass the revision before it — nothing was changed"
    exit 1
fi
echo "   ✓ $(git log -1 --format='%h %s' "$REV")"
echo "   Going back to it undoes (newest first, at most 20):"
git log --oneline "$REV..HEAD" | head -n 20 | sed 's/^/     /'
if [ "$FORCE" -eq 0 ] && ! same_as_deployed; then exit 1; fi
echo ""

echo "→ Step 2: Check out $REV (detached)..."
if ! git checkout --detach "$REV"; then
    echo "   ✗ Checkout failed (local changes?) — nothing was changed"
    exit 1
fi
echo ""

echo "→ Step 3: Build the daemon and the web UI..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — the checkout is at $REV but the running containers were not touched; run this again"
    exit 1
fi
echo "   ✓ Built"
echo ""

echo "→ Step 4: Recreate zeek-live, the daemon and the web UI..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web zeek-live
RECREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "   Recreated at $RECREATED"
echo ""

echo "→ Step 5: Verify..."
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
QUIC_VAL=$(sudo docker exec nettap-zeek-live printenv ZEEK_DISABLE_SPICY_QUIC)
ICS_VAL=$(sudo docker exec nettap-zeek-live printenv ZEEK_DISABLE_ICS_ALL)
if [ "$QUIC_VAL" != "false" ]; then rc=0; else rc=1; fi
check "QUIC analyzer back to Malcolm's default" "$rc" "ZEEK_DISABLE_SPICY_QUIC=${QUIC_VAL:-unset} (want anything but false)"
if [ "$ICS_VAL" != "true" ]; then rc=0; else rc=1; fi
check "ICS analyzers back to Malcolm's default" "$rc" "ZEEK_DISABLE_ICS_ALL=${ICS_VAL:-unset} (want anything but true)"
# zeekctl writes the open log in logs/current (a link into spool); wait up to 2 minutes for it
CONN_LOG=""
for _ in $(seq 1 12); do
    CONN_LOG=$(sudo docker exec nettap-zeek-live sh -c 'ls /zeek/live/logs/current/conn.log /zeek/live/spool/*/conn.log 2>/dev/null | head -n 1')
    [ -n "$CONN_LOG" ] && break
    sleep 10
done
if [ -n "$CONN_LOG" ]; then
    # size and modification time; a rotation in between also changes them, and means Zeek writes
    S1=$(sudo docker exec nettap-zeek-live stat -L -c '%s bytes, mtime %Y' "$CONN_LOG" 2>/dev/null)
    sleep 60
    S2=$(sudo docker exec nettap-zeek-live stat -L -c '%s bytes, mtime %Y' "$CONN_LOG" 2>/dev/null)
    if [ -n "$S1" ] && [ -n "$S2" ] && [ "$S1" != "$S2" ]; then rc=0; else rc=1; fi
    check "Zeek still writes conn.log" "$rc" "$CONN_LOG: ${S1:-?} → ${S2:-?} over 60 s"
else
    check "Zeek still writes conn.log" 1 "no conn.log under /zeek/live/logs/current or /zeek/live/spool after 2 minutes"
fi
REJ=$(sudo docker logs nettap-logstash --since "$RECREATED" 2>&1 | grep -c "Could not index event")
if [ "$REJ" -eq 0 ]; then rc=0; else rc=1; fi
check "no new Logstash indexing rejections" "$rc" "$REJ since $RECREATED"
echo "   Note: connections already indexed with a QUIC label keep it; only new QUIC connections are unlabelled again."
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-zeek-live|nettap-storage-daemon|nettap-web|nettap-logstash"
echo ""

if [ "$FAILED" -eq 0 ]; then
    if [ -f "$BASELINE" ]; then
        DONE="$BASELINE.rolled-back-$(date -u +%Y%m%dT%H%M%SZ)"
        mv "$BASELINE" "$DONE" && echo "   Rollback point moved to $DONE"
    fi
    rm -f "$DEPLOYED"
    echo "=== Rolled back to $(git log -1 --format='%h' "$REV"); later deploys go back to main as usual ==="
else
    echo "=== FAIL: rolled back to $REV with ✗ lines above — paste this output back (the rollback point is kept) ==="
fi
