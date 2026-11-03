#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 34 (exact top lists across daily indices) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #93 A window spanning several daily indices merges each index's top terms, so site-wide top
#       lists (Log Explorer top talkers, DNS top domains, top signatures, top destinations,
#       Sankey, nested lists like risk's unusual ports) lost counts; the DNS median was a
#       t-digest estimate. The daemon's client now asks every shard for every term, and the
#       median is an HDR percentile.
#
# Only the daemon is rebuilt. The data may still sit in one daily index, so the check splits it
# with OpenSearch's slicing (transient, put back) and requires the same figures.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch34.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: dashboard data accuracy, batch 34 (exact top lists across daily indices) ==="
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

echo "→ Step 3: Figures don't depend on how the data is split (#93)..."
bash "$REPO_DIR/scripts/remote/verify-split-invariance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 4: Every device's figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-device-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 5: Heaviest pages over 30 days (the larger per-shard lists cost time)..."
SLOW=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, time, urllib.parse, urllib.request
from datetime import UTC, datetime, timedelta
token = open('/run/nettap-auth/daemon-token').read().strip()
now = datetime.now(UTC)
q = urllib.parse.urlencode({'from': (now - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'to': now.strftime('%Y-%m-%dT%H:%M:%SZ')})
worst = []
for p in ['/api/traffic/connections/sankey', '/api/traffic/top-destinations', '/api/logs/top-talkers', '/api/dns/top-domains',
          '/api/alerts/top-signatures', '/api/risk/scores', '/api/devices?limit=500', '/api/iot/fleet-summary', '/api/traffic/categories']:
    t0 = time.time()
    urllib.request.urlopen(urllib.request.Request('http://localhost:8880' + p + ('&' if '?' in p else '?') + q, headers={'X-NetTap-Daemon-Token': token}), timeout=120).read()
    worst.append((round(time.time() - t0, 2), p))
worst.sort(reverse=True)
print(worst[0][0], '; '.join(f'{p} {t} s' for t, p in worst))
" 2>&1)
SLOWEST=${SLOW%% *}
if [[ "$SLOWEST" =~ ^[0-9.]+$ ]] && awk "BEGIN { exit !($SLOWEST < 10) }"; then rc=0; else rc=1; fi
check "30-day pages answer in under 10 s" "$rc" "${SLOW#* }"
echo ""

echo "→ Step 6: Page figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 7: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 34 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
