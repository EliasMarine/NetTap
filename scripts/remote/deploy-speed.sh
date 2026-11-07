#!/usr/bin/env bash
# NET-192 PR 3 (speed): deploy the web and the daemon, then check what the PR changed.
# Tracking: tracking-fixes/2026-11-07-ui-consistency-speed.md
#
#   - The Threats page reads the background beaconing scan (?snapshot=24h|7d|30d).
#   - Reverse DNS answers within 6 s, once per IP, from a cache; WHOIS is cached.
#   - Connections stats gets ASN and country for its top 10 only; the LAN rule is CIDR terms.
#   - Connections offers 30d again.
# Then the page figures must still match OpenSearch (verify-figures, verify-device-figures,
# verify-split-invariance). Timing with NETTAP_QUERY_TIMING is deploy-speed-timing.sh, not this.
#
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=feature/net192-speed bash /home/nettap/NetTap/scripts/remote/deploy-speed.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="docker/docker-compose.yml"
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy NET-192 PR 3 (speed) from $BRANCH ==="
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

echo "→ Step 2: Build the web and the daemon..."
if ! sudo docker compose -f "$COMPOSE_FILE" build nettap-web nettap-storage-daemon; then
    echo "   ✗ build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Restart both..."
sudo docker compose -f "$COMPOSE_FILE" up -d --no-deps --force-recreate nettap-web nettap-storage-daemon
echo ""

echo "→ Step 4: Wait for both to become healthy..."
WEB_STATUS="unknown"
DAEMON_STATUS="unknown"
for i in $(seq 1 36); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/36)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "containers healthy" "$rc" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 5: The slow pages' daemon calls, cold, one at a time (a few minutes)..."
sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_page_speed.py")" pages 2>&1 | sed 's/^/   /'
check "every call answered 200" "${PIPESTATUS[0]}" "see the lines above (Connections 30d included)"
echo ""

echo "→ Step 6: The Threats report from the background beaconing scan (waits up to 10 min)..."
sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_page_speed.py")" snapshot 2>&1 | sed 's/^/   /'
check "7-day snapshot ready and the report answered" "${PIPESTATUS[0]}" "see the lines above"
echo ""

echo "→ Step 7: Page figures still match OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" 2>&1 | sed 's/^/   /'
check "verify-figures.sh" "${PIPESTATUS[0]}" "every page figure"
bash "$REPO_DIR/scripts/remote/verify-device-figures.sh" 2>&1 | sed 's/^/   /'
check "verify-device-figures.sh" "${PIPESTATUS[0]}" "every device, every MAC"
bash "$REPO_DIR/scripts/remote/verify-split-invariance.sh" 2>&1 | sed 's/^/   /'
check "verify-split-invariance.sh" "${PIPESTATUS[0]}" "figures do not depend on how the window is split"
echo ""

echo "→ Step 8: Daemon errors since the restart..."
ERRS=$(sudo docker logs --since 15m nettap-storage-daemon 2>&1 | grep -E "Traceback|ERROR" | sed 's/^[0-9T:., -]*//' | sort | uniq -c | sort -rn | head -10)
if [ -z "$ERRS" ]; then rc=0; else rc=1; printf '%s\n' "$ERRS" | sed 's/^/   /'; fi
check "daemon log" "$rc" "errors or tracebacks in the last 15 minutes"
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed. Open Threats (24h, 7d, 30d) and Connections (30d) to look. ==="
else
    echo "=== Deploy finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
