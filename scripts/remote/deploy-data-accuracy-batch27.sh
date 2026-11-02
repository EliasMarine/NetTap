#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 27 (IoT alert counts) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #82 IoT trust scores counted Suricata engine events (rule.name "SURICATA ...") as device
#       alerts: three devices on the G11 lost up to 10 security points for 521, 220 and 15
#       "alerts" that were all engine events
#
# Only the daemon is rebuilt. The check reads each IoT device's security score for the same
# fixed past day before and after, and compares the change with what OpenSearch's raw alert
# counts say it must be (the alert part is 10 points minus 2 per alert, never below 0).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch27.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
# A fixed past day, so the before and after reads cover the same records
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '24 hours ago 15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

daemon_get() {  # daemon_get <path> → JSON body
    sudo docker exec nettap-storage-daemon python3 -c "
import sys, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + sys.argv[1], headers={'X-NetTap-Daemon-Token': token})
print(urllib.request.urlopen(req, timeout=300).read().decode())" "$1" 2>&1
}

security_scores() {  # → {"MAC": security_score, ...} for the fixed window
    local body
    body=$(daemon_get "/api/iot/fleet-summary?from=$FROM_TS&to=$TO_TS")
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys
print(json.dumps({d['mac'].upper(): d['security_score'] for d in json.loads(sys.argv[1]).get('devices', [])}))" "$body" 2>&1
}

raw_alerts_by_mac() {  # $1 = must_not clauses → {"MAC": count, ...}, same filter as the daemon
    local body
    body=$(sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        -H 'Content-Type: application/json' "https://localhost:9200/arkime_sessions3-*/_search" \
        -d "{\"size\":0,\"query\":{\"bool\":{\"filter\":[{\"range\":{\"@timestamp\":{\"gte\":\"$FROM_TS\",\"lte\":\"$TO_TS\"}}},{\"exists\":{\"field\":\"suricata.alert.severity\"}}],\"must_not\":$1}},\"aggs\":{\"by_mac\":{\"terms\":{\"field\":\"source.mac\",\"size\":5000}}}}")
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys
out = {}
for b in json.loads(sys.argv[1])['aggregations']['by_mac']['buckets']:
    out[b['key'].upper()] = out.get(b['key'].upper(), 0) + b['doc_count']
print(json.dumps(out))" "$body" 2>&1
}

echo "=== Deploy: dashboard data accuracy, batch 27 (IoT alert counts) ==="
echo "   window: $FROM_TS → $TO_TS"
echo ""

echo "→ Step 1: Before..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
BEFORE=$(security_scores)
echo "   security scores: $BEFORE"
echo ""

echo "→ Step 2: Pull latest code..."
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

echo "→ Step 3: Build and recreate the daemon..."
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

echo "→ Step 4: Checks..."
EXCL=$(daemon_get /api/settings/excluded-ips)
EXCL_IPS=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, sys
print(json.dumps(json.loads(sys.argv[1])['excluded_ips']))" "$EXCL" 2>&1)
AFTER=$(security_scores)
ALL=$(raw_alerts_by_mac "[{\"terms\":{\"source.ip\":$EXCL_IPS}}]")
REAL=$(raw_alerts_by_mac "[{\"terms\":{\"source.ip\":$EXCL_IPS}},{\"prefix\":{\"rule.name\":\"SURICATA \"}}]")
RESULT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, sys
before, after, all_, real = (json.loads(a) for a in sys.argv[1:5])
alert_pts = lambda n: max(0, 10 - 2 * n)
bad, lines = 0, []
for mac in sorted(after):
    if mac not in before:
        continue
    a, r = all_.get(mac, 0), real.get(mac, 0)
    expected = alert_pts(r) - alert_pts(a)
    actual = after[mac] - before[mac]
    ok = abs(actual - expected) <= 1  # 1 point of slack for late records moving encryption
    bad += not ok
    if a != r or not ok:
        lines.append(f'{mac}: {a} with engine events, {r} real; security {before[mac]} -> {after[mac]} (expected {expected:+d})' + ('' if ok else '  <-- MISMATCH'))
print(bad)
print('; '.join(lines) or 'no IoT device had engine events in this window')" "$BEFORE" "$AFTER" "$ALL" "$REAL" 2>&1)
BAD=$(printf '%s\n' "$RESULT" | head -n 1)
DETAIL=$(printf '%s\n' "$RESULT" | tail -n +2)
if [ "$BAD" = "0" ]; then rc=0; else rc=1; fi
check "#82 IoT security scores ignore engine events" "$rc" "$DETAIL"
echo ""

echo "→ Step 5: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 27 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
