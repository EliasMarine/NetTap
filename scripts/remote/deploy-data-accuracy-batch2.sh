#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 2 (daemon and web) and check each fix.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch2.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

api() {
    local token
    token=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)
    curl -s -m 60 -H "X-NetTap-Daemon-Token: $token" "http://localhost:8880$1"
}

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

json_num() {  # json_num <key> — first numeric value of "key" on stdin
    grep -o "\"$1\": *[0-9.]*" | head -1 | grep -o '[0-9.]*$'
}

echo "=== Deploy: dashboard data accuracy, batch 2 ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the daemon and web images..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the daemon and web..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for the daemon and web to become healthy..."
for name in nettap-storage-daemon nettap-web; do
    STATUS="unknown"
    for i in $(seq 1 30); do
        STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "unknown")
        [ "$STATUS" = "healthy" ] && break
        echo "   waiting... $name=$STATUS ($i/30)"
        sleep 5
    done
    if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
    check "$name health" "$rc" "$STATUS"
done
echo ""

echo "→ Step 5: Check each fix..."
LOCAL=$(api "/api/dns/top-domains?limit=50" | grep -c '\.local"')
if [ "$LOCAL" -eq 0 ]; then rc=0; else rc=1; fi
check "#24 no .local names in DNS top domains" "$rc" "occurrences=$LOCAL"

DNS=$(api /api/dns/stats)
AVG=$(printf '%s' "$DNS" | json_num avg_resolution_ms | cut -d. -f1)
if [ -n "$AVG" ] && [ "$AVG" -lt 500 ]; then rc=0; else rc=1; fi
check "#24 DNS average resolution is lookups only" "$rc" "avg=${AVG:-?} ms median=$(printf '%s' "$DNS" | json_num median_resolution_ms) ms queries=$(printf '%s' "$DNS" | json_num total_queries)"

ALERTS=$(api /api/alerts/count | json_num total)
SMART=$(api /api/alerts/smart/summary)
EVENTS=$(printf '%s' "$SMART" | json_num total_events)
INFO=$(printf '%s' "$SMART" | json_num informational_events)
SHOWN=$(( ${EVENTS:-0} + ${INFO:-0} ))
# to review + informational should account for the Alerts card total (suppressed rules aside)
if [ -n "$INFO" ] && [ -n "$ALERTS" ] && [ $(( SHOWN * 100 )) -ge $(( ALERTS * 90 )) ]; then rc=0; else rc=1; fi
check "#19 Alert Summary accounts for every alert" "$rc" "to review=${EVENTS:-?} + informational=${INFO:-?} = $SHOWN vs Alerts card ${ALERTS:-?}"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 2 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
