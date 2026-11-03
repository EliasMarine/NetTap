#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 33 (exact top lists) and check every device's figures.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #90 OpenSearch 3.5 slices each shard for aggregations ("auto" concurrent segment search),
#       so every terms top-N counted like 4 shards: device top destinations, ports and DNS
#       lookups read low and the MAC page's byte ranking was off. The daemon turns it off.
#   #91 Device categories read only the top 200 ASNs
#   #92 Unique destinations was a cardinality estimate
#
# Only the daemon is rebuilt. The daemon sets the cluster setting on its first storage cycle;
# the script waits for it, clears OpenSearch's request cache (it may hold sliced results),
# then recomputes every device's figures from raw OpenSearch.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch33.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

os_query() {  # os_query <method> <path>: OpenSearch from inside its container
    sudo docker exec nettap-opensearch curl -s -X "$1" --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        "https://localhost:9200$2"
}

echo "=== Deploy: dashboard data accuracy, batch 33 (exact top lists) ==="
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

echo "→ Step 2: Build and recreate the daemon..."
BUILT=1
for attempt in 1 2; do
    if "${COMPOSE[@]}" build nettap-storage-daemon; then BUILT=0; break; fi
    echo "   build failed (attempt $attempt/2), retrying..."
done
if [ "$BUILT" -ne 0 ]; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
STATUS="unknown"
for _ in $(seq 1 36); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-storage-daemon health" "$rc" "$STATUS"
echo ""

echo "→ Step 3: Wait for the daemon to turn off concurrent segment search (#90)..."
MODE="unset"
for _ in $(seq 1 36); do
    if os_query GET "/_cluster/settings?flat_settings=true" | grep -q '"search.concurrent_segment_search.mode":"none"'; then
        MODE="none"
        break
    fi
    sleep 5
done
if [ "$MODE" = "none" ]; then rc=0; else rc=1; fi
check "#90 persistent search.concurrent_segment_search.mode" "$rc" "$MODE"
os_query POST "/arkime_sessions3-*/_cache/clear?request=true" >/dev/null
echo "   request cache cleared"
echo ""

echo "→ Step 4: Every device's figures vs OpenSearch (#90-#92)..."
bash "$REPO_DIR/scripts/remote/verify-device-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 5: Page figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 33 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
