#!/usr/bin/env bash
# NET-192 PR 3, part 1a: measure the slow pages' daemon calls on the device (daemon only).
# Tracking: tracking-fixes/2026-11-07-ui-consistency-speed.md
#
#   1. The daemon restarts with NETTAP_QUERY_TIMING=1 and the background beaconing check off,
#      so nothing competes with the measured calls. verify_page_speed.py times each slow call
#      cold (fresh `to`), then the "query-timing" lines show which OpenSearch query dominated.
#   2. The daemon restarts as it normally runs (no timing, background check on).
#      verify_page_speed.py waits for the 7-day beaconing snapshot, then times the Threats
#      report as the page now asks for it (?snapshot=).
#
# The full output is also saved to ~/nettap-speed-timing.log.
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=feature/net192-speed bash /home/nettap/NetTap/scripts/remote/deploy-speed-timing.sh
set -u
exec > >(tee "$HOME/nettap-speed-timing.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="docker/docker-compose.yml"
SERVICE="nettap-storage-daemon"
TIMING_LINES=60
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_healthy() {
    local status="unknown"
    for _ in $(seq 1 36); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$SERVICE" 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && break
        sleep 5
    done
    if [ "$status" = "healthy" ]; then rc=0; else rc=1; fi
    check "$SERVICE health" "$rc" "$status"
    return "$rc"
}

speed() {  # speed <pages|snapshot>
    sudo docker exec "$SERVICE" python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_page_speed.py")" "$1" 2>&1 | sed 's/^/   /'
    return "${PIPESTATUS[0]}"
}

echo "=== Measure the slow pages' daemon calls (NET-192 PR 3) from $BRANCH ==="
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

echo "→ Step 2: Build the daemon..."
if ! sudo docker compose -f "$COMPOSE_FILE" build "$SERVICE"; then
    echo "   ✗ $SERVICE build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Daemon built"
echo ""

echo "→ Step 3: Restart the daemon with query timing on and the background beaconing check off..."
STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# OLD CODE START — the G11's docker-only sudo rule (no SETENV) refuses to set these variables
# sudo NETTAP_QUERY_TIMING=1 NETTAP_BEACON_BACKGROUND=0 docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$SERVICE"
# OLD CODE END
sudo docker compose -f "$COMPOSE_FILE" -f scripts/remote/speed-timing.compose.yml up -d --no-deps --force-recreate "$SERVICE"
wait_healthy
echo ""

echo "→ Step 4: Time each slow call, cold, one at a time (a few minutes)..."
speed pages
check "every call answered 200" "$?" "see the lines above"
echo ""

echo "→ Step 5: The $TIMING_LINES slowest OpenSearch requests (wall ms, then the caller that built the query)..."
LINES=$(sudo docker logs --since "$STARTED" "$SERVICE" 2>&1 | grep "query-timing ")
echo "   $(printf '%s\n' "$LINES" | grep -c "query-timing ") requests logged since $STARTED"
printf '%s\n' "$LINES" |
    sed 's/^.*query-timing //' |
    awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^wall_ms=/) { split($i, w, "="); print w[2] "\t" $0 } }' |
    sort -rn | head -n "$TIMING_LINES" | cut -f2- | sed 's/^/   /'
echo ""
echo "   Total wall ms per caller (top 20):"
printf '%s\n' "$LINES" |
    sed 's/^.*query-timing //' |
    awk '{ c = ""; w = 0; for (i = 1; i <= NF; i++) { if ($i ~ /^caller=/) c = $i; if ($i ~ /^wall_ms=/) { split($i, x, "="); w = x[2] } } s[c] += w; n[c]++ }
         END { for (k in s) printf "%d\t%d requests\t%s\n", s[k], n[k], k }' |
    sort -rn | head -20 | sed 's/^/   /'
echo ""

echo "→ Step 6: Restart the daemon as it normally runs (no timing, background check on)..."
sudo docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate "$SERVICE"
NORMAL_STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
wait_healthy
echo ""

echo "→ Step 7: The Threats report from the background snapshot (waits up to 10 min for it)..."
speed snapshot
check "7-day snapshot ready and the report answered" "$?" "see the lines above"
echo ""

echo "→ Step 8: Background beaconing runs since the restart..."
sudo docker logs --since "$NORMAL_STARTED" "$SERVICE" 2>&1 | grep "beacon-snapshot " | sed 's/^.*beacon-snapshot /   /'
echo ""

echo "→ Step 9: Daemon errors since the restart..."
ERRS=$(sudo docker logs --since "$NORMAL_STARTED" "$SERVICE" 2>&1 | grep -E "Traceback|ERROR" | sed 's/^[0-9T:., -]*//' | sort | uniq -c | sort -rn | head -10)
if [ -z "$ERRS" ]; then
    check "daemon log" 0 "no errors or tracebacks since $NORMAL_STARTED"
else
    check "daemon log" 1 "errors since $NORMAL_STARTED:"
    echo "      ${ERRS//$'\n'/$'\n'      }"
fi
echo ""

echo "→ Step 10: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Measured: paste this output back (also in ~/nettap-speed-timing.log) ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
