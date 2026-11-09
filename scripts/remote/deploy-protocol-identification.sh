#!/usr/bin/env bash
# Deploy NET-219: Zeek's QUIC analyzer on, its industrial-control (ICS) analyzers off, and Home's
# "Unidentified" bar split into conversations, one way and ICMP (daemon + web UI).
# Plan: .codex-review/2026-11-08-unidentified-protocols/PLAN.md, step 5 ("Device run").
#
# zeek-live, the daemon and the web UI restart (a capture gap of a few seconds). About 20 minutes:
# a CPU sample, the builds, 10 minutes of new data, the checks, another CPU sample.
#
# Run as the normal user (NOT with sudo), while the device still runs the code from before this
# change: the first step records that revision as the rollback point, then the script switches to
# $BRANCH itself. Two commands:
#   git -C /home/nettap/NetTap fetch origin
#   bash <(git -C /home/nettap/NetTap show origin/fix/unidentified-protocols:scripts/remote/deploy-protocol-identification.sh)
# Running it again after a failed check keeps the first rollback point.
# The full output is also saved to ~/nettap-protocol-identification.log.
set -u
exec > >(tee "$HOME/nettap-protocol-identification.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/unidentified-protocols"
BASELINE="$HOME/.nettap-deploys/protocol-identification.baseline"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

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

print_rollback() {
    echo "   Roll back with (as the normal user):"
    echo "     git -C $REPO_DIR fetch origin"
    echo "     bash <(git -C $REPO_DIR show origin/$BRANCH:scripts/remote/rollback-protocol-identification.sh)"
}

# The rollback point is the checkout this script starts from, unless that checkout already has
# NET-219 (a retry after a failed check): then the point recorded before is kept. A checkout
# without NET-219 always replaces an older point (ponytail #1: a deploy in between moved the
# device on). Tested in tests/scripts/test_protocol_identification.bats.
record_baseline() {
    local rev
    if ! rev=$(git rev-parse HEAD); then
        echo "   ✗ Can't read the checkout's revision"
        return 1
    fi
    if git show "$rev:docker/docker-compose.yml" | grep -q 'ZEEK_DISABLE_SPICY_QUIC: "false"'; then
        if [ -s "$BASELINE" ]; then
            echo "   ✓ The checkout already has NET-219; rollback point kept from an earlier run ($BASELINE):"
            sed 's/^/     /' "$BASELINE"
            return 0
        fi
        echo "   ✗ The checkout ($rev) already has NET-219, so it can't be the rollback point."
        echo "     Check out the revision the device ran before and run this again."
        return 1
    fi
    mkdir -p "$(dirname "$BASELINE")" || return 1
    # through a temp file, so an interrupted run never leaves a half-written point
    if ! {
        echo "revision=$rev"
        echo "zeek_live_image=$(sudo docker inspect --format '{{.Image}}' nettap-zeek-live 2>/dev/null)"
        echo "daemon_image=$(sudo docker inspect --format '{{.Image}}' nettap-storage-daemon 2>/dev/null)"
        echo "web_image=$(sudo docker inspect --format '{{.Image}}' nettap-web 2>/dev/null)"
        echo "recorded=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$BASELINE.tmp" || ! mv "$BASELINE.tmp" "$BASELINE"; then
        echo "   ✗ Can't write $BASELINE"
        return 1
    fi
    echo "   ✓ Rollback point recorded in $BASELINE:"
    sed 's/^/     /' "$BASELINE"
}

zeek_cpu() {  # zeek-live's average CPU in % of one core: 12 samples 5 s apart
    local samples="" i
    for i in $(seq 1 12); do
        samples="$samples $(sudo docker stats --no-stream --format '{{.CPUPerc}}' nettap-zeek-live 2>/dev/null | tr -d '%')"
        [ "$i" -lt 12 ] && sleep 5
    done
    echo "$samples" | awk '{ s = 0; for (i = 1; i <= NF; i++) s += $i; if (NF) printf "%.1f\n", s / NF; else print "n/a" }'
}

rejections() {  # rejections SINCE: Logstash's "Could not index" lines (OpenSearch refused a record)
    sudo docker logs nettap-logstash --since "$1" 2>&1 | grep -c "Could not index event"
}

echo "=== Deploy NET-219: protocol identification from $BRANCH ==="
echo ""

echo "→ Step 1: Record the rollback point (before anything changes)..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
record_baseline || exit 1
print_rollback
echo ""

echo "→ Step 2: zeek-live CPU before (1 minute)..."
CPU_BEFORE=$(zeek_cpu)
REJ_BEFORE=$(rejections 10m)
echo "   zeek-live CPU: ${CPU_BEFORE}% of one core"
echo "   Logstash rejections in the last 10 minutes: $REJ_BEFORE"
echo ""

echo "→ Step 3: Pull $BRANCH..."
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 4: Build the daemon and the web UI..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — the running containers were not touched"
    exit 1
fi
echo "   ✓ Built"
echo ""

echo "→ Step 5: Recreate zeek-live, the daemon and the web UI..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web zeek-live
# Every Zeek record stamped from here on comes from the new zeek-live: the checks' window start
RECREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "   Recreated at $RECREATED"
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo ""

echo "→ Step 6: zeek-live has the new settings..."
QUIC_VAL=$(sudo docker exec nettap-zeek-live printenv ZEEK_DISABLE_SPICY_QUIC)
ICS_VAL=$(sudo docker exec nettap-zeek-live printenv ZEEK_DISABLE_ICS_ALL)
if [ "$QUIC_VAL" = "false" ]; then rc=0; else rc=1; fi
check "QUIC analyzer on" "$rc" "ZEEK_DISABLE_SPICY_QUIC=${QUIC_VAL:-unset} (want false)"
if [ "$ICS_VAL" = "true" ]; then rc=0; else rc=1; fi
check "ICS analyzers off" "$rc" "ZEEK_DISABLE_ICS_ALL=${ICS_VAL:-unset} (want true)"
echo ""

echo "→ Step 7: Wait 10 minutes for new connections to be indexed..."
for left in 10 9 8 7 6 5 4 3 2 1; do
    echo "   $left min left..."
    sleep 60
done
echo ""

echo "→ Step 8: Check the protocol figures against OpenSearch (window from $RECREATED)..."
sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_protocols.py")" "$RECREATED" 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 9: Logstash indexing since the recreate..."
REJ_AFTER=$(rejections "$RECREATED")
if [ "$REJ_AFTER" -eq 0 ]; then rc=0; else rc=1; fi
check "no new indexing rejections" "$rc" "$REJ_AFTER since $RECREATED ($REJ_BEFORE in the 10 minutes before the deploy)"
[ "$REJ_AFTER" -eq 0 ] || sudo docker logs nettap-logstash --since "$RECREATED" 2>&1 | grep "Could not index event" | tail -3 | cut -c1-300 | sed 's/^/     | /'
echo ""

echo "→ Step 10: zeek-live CPU after (1 minute) and restarts..."
CPU_AFTER=$(zeek_cpu)
echo "   zeek-live CPU: ${CPU_BEFORE}% before, ${CPU_AFTER}% after (% of one core)"
if [[ "$CPU_BEFORE" =~ ^[0-9.]+$ && "$CPU_AFTER" =~ ^[0-9.]+$ ]]; then
    if awk -v a="$CPU_AFTER" -v b="$CPU_BEFORE" 'BEGIN { exit !(a - b > 10) }'; then
        echo "   ⚠ FLAG: zeek-live CPU rose by more than 10 points of one core; look at it (not a failure)"
    fi
else
    echo "   ⚠ FLAG: CPU not measured both times; compare by hand with: sudo docker stats --no-stream nettap-zeek-live"
fi
RESTARTS=$(sudo docker inspect --format '{{.RestartCount}}' nettap-zeek-live 2>/dev/null)
if [ "${RESTARTS:-x}" = "0" ]; then rc=0; else rc=1; fi
check "zeek-live not restarting" "$rc" "${RESTARTS:-unknown} restarts since the recreate"
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-zeek-live|nettap-storage-daemon|nettap-web|nettap-logstash"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== NET-219 deployed and verified — Home's Application layer now shows QUIC, and the note below it ==="
else
    echo "=== FAIL: NET-219 deployed but a check above is ✗ or FAIL — paste this output back ==="
    print_rollback
fi
