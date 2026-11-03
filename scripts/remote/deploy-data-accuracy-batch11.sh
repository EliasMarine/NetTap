#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 11 (per-device alert counts) and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #60 Devices, device detail, a device's alert list and Risk scores leave Suricata engine
#       events ("SURICATA ..." decoder/stream noise) out of alert counts, like the Alerts page
#
# Only the daemon restarts. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch11.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_healthy() {
    local name="$1" status="unknown"
    for i in $(seq 1 36); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && break
        [ $((i % 6)) -eq 0 ] && echo "   waiting... $name=$status ($i/36)"
        sleep 5
    done
    if [ "$status" = "healthy" ]; then rc=0; else rc=1; fi
    check "$name health" "$rc" "$status"
}

echo "=== Deploy: dashboard data accuracy, batch 11 (per-device alert counts) ==="
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

echo "→ Step 2: Build the daemon image..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Image built"
echo ""

echo "→ Step 3: Recreate the daemon..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
wait_healthy nettap-storage-daemon
echo ""

echo "→ Step 4: Compare per-device alert counts with OpenSearch..."
FROM=$(date -u -d '-24 hours' +%Y-%m-%dT%H:%M:%SZ)
TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# Ground truth: Suricata alerts per source IP, with and without the engine events
BODY='{"size":0,"query":{"bool":{"filter":[{"range":{"@timestamp":{"gte":"'"$FROM"'","lte":"'"$TO"'"}}},{"term":{"event.provider":"suricata"}},{"term":{"event.dataset":"alert"}}]}},"aggs":{"ip":{"terms":{"field":"source.ip","size":40},"aggs":{"engine":{"filter":{"prefix":{"rule.name":"SURICATA "}}}}}}}'
TRUTH=$(sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc \
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure \
    -H 'Content-Type: application/json' "https://localhost:9200/arkime_sessions3-*/_search" -d "$BODY")
# Compare inside the daemon container: it fetches /api/devices itself (too big for an argument)
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.parse, urllib.request
truth, frm, to = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3]
token = open('/run/nettap-auth/daemon-token').read().strip()
url = 'http://localhost:8880/api/devices?' + urllib.parse.urlencode({'from': frm, 'to': to, 'limit': 500})
devices = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'X-NetTap-Daemon-Token': token}), timeout=120))
shown = {d['ip']: d.get('alert_count', 0) for d in devices.get('devices', [])}
checked = bad = noisy = 0
for b in truth['aggregations']['ip']['buckets']:
    ip = b['key']
    if ip not in shown:
        continue  # not a LAN device on the Devices page
    expected = b['doc_count'] - b['engine']['doc_count']
    checked += 1
    if b['engine']['doc_count'] > 0:
        noisy += 1
        print(f'DEVICE {ip} page={shown[ip]} expected={expected} engine_removed={b[\"engine\"][\"doc_count\"]}')
    if shown[ip] != expected:
        bad += 1
        print(f'MISMATCH {ip} page={shown[ip]} expected={expected}')
print(f'SUMMARY {checked} {bad} {noisy}')
" "$TRUTH" "$FROM" "$TO" 2>&1)
while IFS= read -r line; do echo "   $line"; done <<<"$OUT"
read -r _ CHECKED BAD NOISY <<<"$(echo "$OUT" | grep '^SUMMARY')"
if [ "${CHECKED:-0}" -ge 1 ] && [ "${BAD:-1}" -eq 0 ]; then rc=0; else rc=1; fi
check "#60 Devices alert counts = Suricata alerts without engine events" "$rc" "${CHECKED:-?} devices checked, ${BAD:-?} mismatches, ${NOISY:-?} had engine events removed"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|suricata-live|zeek-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 11 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
