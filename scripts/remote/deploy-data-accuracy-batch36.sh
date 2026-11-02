#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 36 (every figure counts every device, pair and domain) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #96 Code that counted, summed or scanned "all" of something took a terms list of the top
#       N (500 devices, 300 pairs, 500 domains...). On a bigger network the rest went missing.
#       Those reads now page through every bucket. A failed check no longer reads "none
#       detected": the threat detectors, DNS page and risk scores report the failure, and a
#       reply from only some OpenSearch shards is an error instead of a smaller count.
#
# This home network is below every old cap, so the figures here must not change; what this run
# proves is that the new queries work on this OpenSearch and agree with each other.
# The daemon and the web container are rebuilt. The slicing setting is transient and always put back.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch36.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: dashboard data accuracy, batch 36 (complete sets, honest failures) ==="
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

echo "→ Step 3: #96 the new queries agree with each other on real data..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.parse, urllib.request
from datetime import UTC, datetime, timedelta
token = open('/run/nettap-auth/daemon-token').read().strip()
now = datetime.now(UTC)
q = urllib.parse.urlencode({'from': (now - timedelta(hours=25)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'to': (now - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')})
def api(p):
    return json.load(urllib.request.urlopen(urllib.request.Request('http://localhost:8880' + p + ('&' if '?' in p else '?') + q, headers={'X-NetTap-Daemon-Token': token}), timeout=300))
count = api('/api/devices/count')['count']
listed = len(api('/api/devices?limit=500')['devices'])
risk = api('/api/risk/scores')
scored = len(risk['devices'])
report = api('/api/threats/report')
beacon = api('/api/threats/beaconing')
lateral = api('/api/threats/lateral')
problems = []
if not (count == listed or (count > 500 and listed == 500)):
    problems.append(f'device count {count} vs device list {listed}')
if scored != count:
    problems.append(f'risk list {scored} devices vs device count {count}')
if report.get('failed_checks') or report.get('incomplete_checks'):
    problems.append(f\"threat report failed {report.get('failed_checks')} incomplete {report.get('incomplete_checks')}\")
if beacon.get('complete') is not True or lateral.get('complete') is not True:
    problems.append(f\"beaconing complete={beacon.get('complete')} lateral complete={lateral.get('complete')}\")
if len(report.get('beaconing', [])) != beacon['total'] or len(report.get('lateral_movement', [])) != lateral['total']:
    problems.append(f\"report beacons {len(report.get('beaconing', []))}/{beacon['total']} lateral {len(report.get('lateral_movement', []))}/{lateral['total']}\")
print(int(not problems), f'devices: count {count} = list {listed} = risk-scored {scored}; threat report: {beacon[\"total\"]} beacons, {lateral[\"total\"]} lateral paths, all checks ran and finished', '|' if problems else '', '; '.join(problems))
" 2>&1)
if [ "${OUT%% *}" = "1" ]; then rc=0; else rc=1; fi
check "#96 complete sets agree" "$rc" "${OUT#* }"
echo ""

echo "→ Step 4: #96 heaviest complete-set pages over 24 h and 30 days..."
SLOW=$(sudo docker exec nettap-storage-daemon python3 -c "
import time, urllib.parse, urllib.request
from datetime import UTC, datetime, timedelta
token = open('/run/nettap-auth/daemon-token').read().strip()
now = datetime.now(UTC)
worst = []
for days in (1, 30):
    q = urllib.parse.urlencode({'from': (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'to': now.strftime('%Y-%m-%dT%H:%M:%SZ')})
    for p in ['/api/threats/report', '/api/risk/scores', '/api/devices/count', '/api/iot/fleet-summary', '/api/iot/network-isolation',
              '/api/iot/privacy-report', '/api/mac/merge-suggestions', '/api/certificates/issuer-changes', '/api/lan/arp-spoofing',
              '/api/traffic/categories', '/api/alerts/categories', '/api/dns/suspicious']:
        t0 = time.time()
        urllib.request.urlopen(urllib.request.Request('http://localhost:8880' + p + '?' + q, headers={'X-NetTap-Daemon-Token': token}), timeout=300).read()
        worst.append((round(time.time() - t0, 2), f'{p} ({days} d)'))
worst.sort(reverse=True)
print(worst[0][0], '; '.join(f'{p} {t} s' for t, p in worst[:8]))
" 2>&1)
SLOWEST=${SLOW%% *}
if [[ "$SLOWEST" =~ ^[0-9.]+$ ]] && awk "BEGIN { exit !($SLOWEST < 10) }"; then rc=0; else rc=1; fi
check "complete-set pages answer in under 10 s (slowest 8)" "$rc" "${SLOW#* }"
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
    echo "$ERRS" | sed 's/^/      /'
fi
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 36 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
