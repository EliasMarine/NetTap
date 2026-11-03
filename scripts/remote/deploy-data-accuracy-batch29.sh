#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 29 (page counts) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #85 Alerts, Connections and Device detail's connections offered every page of an exact
#       total, but OpenSearch returns nothing past 10,000 results, so later pages were empty
#       with Next still enabled
#
# Only the daemon is rebuilt. The check opens the last page each list offers: it must hold rows.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch29.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '24 hours ago 15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
RANGE="from=$FROM_TS&to=$TO_TS"

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

api() {  # api <path> <python expression on the reply `d`> [value for sys.argv[3]] → value
    # The expression is always a literal from this script; values from the box go in as sys.argv[3]
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + sys.argv[1], headers={'X-NetTap-Daemon-Token': token})
d = json.load(urllib.request.urlopen(req, timeout=300))
print(eval(sys.argv[2]))" "$@" 2>&1
}

last_page() {  # last_page "label" <path without page/size> <rows key>: the last page offered must hold rows
    local info pages rows total rc
    info=$(api "$2&size=50&page=1" "(d['total'], d['total_pages'])")
    total=$(printf '%s' "$info" | tr -d '()' | cut -d, -f1 | tr -d ' ')
    pages=$(printf '%s' "$info" | tr -d '()' | cut -d, -f2 | tr -d ' ')
    if ! [[ "${pages:-x}" =~ ^[0-9]+$ ]]; then check "$1" 1 "no page count: $info"; return; fi
    rows=$(api "$2&size=50&page=$pages" "len(d.get(sys.argv[3]) or [])" "$3")
    if [[ "${rows:-x}" =~ ^[0-9]+$ ]] && { [ "$pages" -eq 0 ] || [ "$rows" -gt 0 ]; } && [ "$pages" -le 200 ]; then rc=0; else rc=1; fi
    check "$1" "$rc" "$total total, $pages pages, last page has $rows rows"
}

echo "=== Deploy: dashboard data accuracy, batch 29 (page counts) ==="
echo "   window: $FROM_TS → $TO_TS"
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
if ! "${COMPOSE[@]}" build nettap-storage-daemon; then
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

echo "→ Step 3: Checks..."
last_page "#85 Connections" "/api/traffic/connections?$RANGE" connections
last_page "#85 Alerts (7 days)" "/api/alerts?from=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ)&to=$TO_TS" alerts
last_page "#85 Device detail connections (192.168.1.1)" "/api/devices/192.168.1.1/connections?$RANGE" connections
echo ""

echo "→ Step 4: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 29 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
