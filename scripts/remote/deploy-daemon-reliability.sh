#!/usr/bin/env bash
# Deploy NET-192 PR 2: the daemon keeps answering while pages load (daemon + web proxy).
# Tracking: tracking-fixes/2026-11-07-ui-consistency-speed.md
#
# Checks:
#   - five Home pages at once: /api/health answers in under 1 s the whole time, no page call fails
#     (before PR 2 on the G11: 2.79 s, 4 answers in 6 s);
#   - OpenSearch rejected no searches during that load;
#   - the page figures still equal raw OpenSearch (verify-figures, -device-figures, -split-invariance);
#   - no daemon errors since the restart.
#
# The full output is also saved to ~/nettap-daemon-reliability.log.
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=fix/daemon-event-loop bash /home/nettap/NetTap/scripts/remote/deploy-daemon-reliability.sh
set -u
exec > >(tee "$HOME/nettap-daemon-reliability.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
SERVICES=(nettap-storage-daemon nettap-web)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

search_rejected() {  # total searches OpenSearch has turned away since it started
    sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        "https://localhost:9200/_nodes/stats/thread_pool/search" |
        sudo docker exec -i nettap-storage-daemon python3 -c "
import json, sys
nodes = json.load(sys.stdin).get('nodes', {}).values()
print(sum(n['thread_pool']['search']['rejected'] for n in nodes))"
}

echo "=== Deploy: the daemon keeps answering while pages load (NET-192 PR 2) from $BRANCH ==="
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

echo "→ Step 2: Build and recreate the daemon and the web container..."
for svc in "${SERVICES[@]}"; do
    if ! "${COMPOSE[@]}" build "$svc"; then
        echo "   ✗ $svc build failed — nothing was restarted"
        exit 1
    fi
done
STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
"${COMPOSE[@]}" up -d --no-deps --force-recreate "${SERVICES[@]}"
for svc in "${SERVICES[@]}"; do
    STATUS="unknown"
    for _ in $(seq 1 36); do
        STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "unknown")
        [ "$STATUS" = "healthy" ] && break
        sleep 5
    done
    if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
    check "$svc health" "$rc" "$STATUS"
done
echo ""

echo "→ Step 3: Five Home pages at once (the first run is cold)..."
REJECTED_BEFORE=$(search_rejected)
for run in cold warm; do
    OUT=$(sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_event_loop.py")" 2>&1)
    RC=$?
    check "health answers in under 1 s ($run)" "$RC" "$OUT"
done
REJECTED_AFTER=$(search_rejected)
if [[ "$REJECTED_BEFORE" =~ ^[0-9]+$ && "$REJECTED_AFTER" =~ ^[0-9]+$ ]] && [ "$REJECTED_AFTER" -eq "$REJECTED_BEFORE" ]; then rc=0; else rc=1; fi
check "OpenSearch rejected no searches" "$rc" "rejected before $REJECTED_BEFORE, after $REJECTED_AFTER"
echo ""

echo "→ Step 4: Figures don't depend on how the data is split..."
bash "$REPO_DIR/scripts/remote/verify-split-invariance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 5: Every device's figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-device-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Page figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 7: Daemon errors since the restart..."
ERRS=$(sudo docker logs --since "$STARTED" nettap-storage-daemon 2>&1 | grep -E "Traceback|ERROR|shard\(s\) failed" | grep -v nettap_not_a_field | sed 's/^[0-9T:., -]*//' | sort | uniq -c | sort -rn | head -10)
if [ -z "$ERRS" ]; then
    check "daemon log" 0 "no errors or tracebacks since $STARTED"
else
    check "daemon log" 1 "errors since $STARTED:"
    echo "      ${ERRS//$'\n'/$'\n'      }"
fi
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deployed and verified: every check passed ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
