#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 25 (Top Destinations exclusion) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #80 Top Destinations left out excluded IPs only as destinations, so what they sent still
#       counted (NetTap's own lookups: 37,121 a day to 9.9.9.9 on the G11)
#
# Only the daemon is rebuilt. Ends with the read-only figures and acceptance checks.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch25.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
DEST="9.9.9.9"
# A fixed past day (a sliding one loses records at its old end between reads)
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '24 hours ago 15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

dest_count() {  # connections to $DEST that Top Destinations reports for the window (0 if absent)
    sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880/api/traffic/top-destinations?from=$FROM_TS&to=$TO_TS&limit=1000', headers={'X-NetTap-Daemon-Token': token})
rows = json.load(urllib.request.urlopen(req, timeout=120))['top_destinations']
print(next((r['connection_count'] for r in rows if r['ip'] == '$DEST'), 0))" 2>&1
}

raw_dest_count() {  # same from OpenSearch; $1 = must_not clauses
    sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        -H 'Content-Type: application/json' "https://localhost:9200/arkime_sessions3-*/_count" \
        -d "{\"query\":{\"bool\":{\"filter\":[{\"range\":{\"@timestamp\":{\"gte\":\"$FROM_TS\",\"lte\":\"$TO_TS\"}}},{\"term\":{\"event.provider\":\"zeek\"}},{\"term\":{\"event.dataset\":\"conn\"}},{\"term\":{\"destination.ip\":\"$DEST\"}}],\"must_not\":$1}}}" \
        | grep -o '"count":[0-9]*' | cut -d: -f2
}

echo "=== Deploy: dashboard data accuracy, batch 25 (Top Destinations exclusion) ==="
echo ""

echo "→ Step 1: Before..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
EXCL=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880/api/settings/excluded-ips', headers={'X-NetTap-Daemon-Token': token})
print(json.dumps(json.load(urllib.request.urlopen(req, timeout=60))['excluded_ips']))" 2>&1)
BEFORE=$(dest_count)
ALL=$(raw_dest_count '[]')
echo "   excluded: $EXCL; $DEST in Top Destinations ($FROM_TS → $TO_TS): $BEFORE connections; all sources: ${ALL:-?}"
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
R1=$(raw_dest_count "[{\"terms\":{\"source.ip\":$EXCL}}]")
AFTER=$(dest_count)
R2=$(raw_dest_count "[{\"terms\":{\"source.ip\":$EXCL}}]")
if [[ "${R1:-x}" =~ ^[0-9]+$ && "${AFTER:-x}" =~ ^[0-9]+$ && "${R2:-x}" =~ ^[0-9]+$ ]] && [ "$R1" -le "$AFTER" ] && [ "$AFTER" -le "$R2" ]; then rc=0; else rc=1; fi
check "#80 Top Destinations leaves out what excluded IPs send" "$rc" "$DEST: $BEFORE → $AFTER connections; OpenSearch without excluded senders ${R1:-?} / ${R2:-?}, with them ${ALL:-?}"
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
    echo "=== Batch 25 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
