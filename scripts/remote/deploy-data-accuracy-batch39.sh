#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 39 (exact device counts, web follow-ups, rules version) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #100 /devices "New (24h)" counted every device (first_seen is the first record in the
#        page's own 24 h window); "Online Now" and the category pills counted only the 200
#        busiest. Now: registry first-seen count, the 5-minute device count, a 500 list.
#   #96h web follow-ups: update history, the top bar's Online, Home's "No traffic" banner and
#        trends, real zeros on Home, the PCAP capture toggle, the setup wizard's NIC, disk and
#        Docker checks, retention health, bridge latency "Not measured", update sizes.
#   Rules version from the Suricata container's rules file (was "unknown", before that today).
#   Batches 37-38's checks run again.
#
# The full output is also saved to ~/nettap-batch39.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch39.sh
set -u
exec > >(tee "$HOME/nettap-batch39.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: dashboard data accuracy, batch 39 (exact device counts, web follow-ups) ==="
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

echo "→ Step 3: Checks on real data (batches 37-38's, then exact device counts and the rules version)..."
for check_file in verify_batch37.py verify_batch38.py verify_batch39.py; do
    OUT=$(sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/$check_file")" 2>&1)
    RC=$?
    echo "   [$check_file]"
    printf '%s\n' "$OUT" | sed 's/^/   /'
    [ "$RC" -eq 0 ] || FAILED=1
done
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
              '/api/lan/arp-spoofing', '/api/lan/rogue-dhcp', '/api/lan/anomalies', '/api/iot/anomalies', '/api/devices/registry/new-count', '/api/traffic/categories', '/api/traffic/categories/streaming', '/api/alerts/categories',
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
ERRS=$(sudo docker logs --since "$STARTED" nettap-storage-daemon 2>&1 | grep -E "Traceback|ERROR|shard\(s\) failed" | grep -v nettap_not_a_field | sed 's/^[0-9T:., -]*//' | sort | uniq -c | sort -rn | head -10)
if [ -z "$ERRS" ]; then
    check "daemon log" 0 "no errors or tracebacks since $STARTED (the two deliberate bad filters left out)"
else
    check "daemon log" 1 "errors since $STARTED:"
    echo "      ${ERRS//$'\n'/$'\n'      }"
fi
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 39 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
