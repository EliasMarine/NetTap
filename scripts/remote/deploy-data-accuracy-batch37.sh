#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 37 (honest failures everywhere, heatmap, beacons) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #96h Every web page and daemon service that turned a failed request into "none", 0 or
#        "healthy" now says it couldn't check.
#   #97  The Bandwidth heatmap was empty on OpenSearch 3 (removed Joda date getters) and bucketed
#        by UTC; it now counts every record, in the viewer's time zone. Checked cell by cell.
#   #98  Beacons are scheduled calls to internet hosts (no NTP/mDNS/LAN pairs, a peer-to-peer
#        device is one line), and the threat report answers in under 10 s.
#   Category detail pages now classify ASNs exactly as Home does. Checked per category.
#
# The full output is also saved to ~/nettap-batch37.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch37.sh
set -u
exec > >(tee "$HOME/nettap-batch37.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: dashboard data accuracy, batch 37 (honest failures, heatmap, beacons) ==="
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
for svc in nettap-storage-daemon nettap-web; do
    if ! "${COMPOSE[@]}" build "$svc"; then
        echo "   ✗ $svc build failed — nothing was restarted"
        exit 1
    fi
done
STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
for svc in nettap-storage-daemon nettap-web; do
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

echo "→ Step 3: #96-#98 checks on real data..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_batch37.py")" 2>&1)
RC=$?
printf '%s\n' "$OUT" | sed 's/^/   /'
[ "$RC" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 4: Heaviest pages over 24 h and 30 days..."
SLOW=$(sudo docker exec nettap-storage-daemon python3 -c "
import time, urllib.parse, urllib.request
from datetime import UTC, datetime, timedelta
token = open('/run/nettap-auth/daemon-token').read().strip()
now = datetime.now(UTC)
worst = []
for days in (1, 30):
    q = urllib.parse.urlencode({'from': (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'to': now.strftime('%Y-%m-%dT%H:%M:%SZ')})
    for p in ['/api/threats/report', '/api/threats/beaconing', '/api/risk/scores', '/api/devices/count', '/api/iot/fleet-summary',
              '/api/iot/network-isolation', '/api/iot/privacy-report', '/api/mac/merge-suggestions', '/api/certificates/issuer-changes',
              '/api/lan/arp-spoofing', '/api/traffic/categories', '/api/traffic/categories/streaming', '/api/alerts/categories',
              '/api/dns/suspicious', '/api/bandwidth/heatmap']:
        t0 = time.time()
        urllib.request.urlopen(urllib.request.Request('http://localhost:8880' + p + '?' + q, headers={'X-NetTap-Daemon-Token': token}), timeout=300).read()
        worst.append((round(time.time() - t0, 2), f'{p} ({days} d)'))
worst.sort(reverse=True)
print(worst[0][0], '; '.join(f'{p} {t} s' for t, p in worst[:8]))
" 2>&1)
SLOWEST=${SLOW%% *}
if [[ "$SLOWEST" =~ ^[0-9.]+$ ]] && awk "BEGIN { exit !($SLOWEST < 10) }"; then rc=0; else rc=1; fi
check "pages answer in under 10 s (slowest 8)" "$rc" "${SLOW#* }"
echo ""

echo "→ Step 5: Figures don't depend on how the data is split (now incl. every traffic category)..."
bash "$REPO_DIR/scripts/remote/verify-split-invariance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Every device's figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-device-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 7: Page figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 8: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 9: Daemon errors since the restart..."
ERRS=$(sudo docker logs --since "$STARTED" nettap-storage-daemon 2>&1 | grep -E "Traceback|ERROR|shard\(s\) failed" | sed 's/^[0-9T:., -]*//' | sort | uniq -c | sort -rn | head -10)
if [ -z "$ERRS" ]; then
    check "daemon log" 0 "no errors or tracebacks since $STARTED"
else
    check "daemon log" 1 "errors since $STARTED:"
    echo "      ${ERRS//$'\n'/$'\n'      }"
fi
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 37 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
