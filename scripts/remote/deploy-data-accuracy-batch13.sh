#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 13 (device vendors and categories) and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #26 Devices, device detail, Home's device grid and Tools -> MAC Lookup use Malcolm's full
#       IEEE vendor name (source.oui) when the bundled ~500-prefix table has no entry, and the
#       category falls back to single-purpose vendors (Hue -> IoT, UniFi -> Infrastructure)
#
# Only the daemon restarts. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch13.sh
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

echo "=== Deploy: dashboard data accuracy, batch 13 (device vendors and categories) ==="
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

echo "→ Step 4: Compare device vendors with Malcolm's IEEE names (last 24 h)..."
BODY='{"size":0,"query":{"range":{"@timestamp":{"gte":"now-24h"}}},"aggs":{"mac":{"terms":{"field":"source.mac","size":500},"aggs":{"oui":{"terms":{"field":"source.oui","size":1}}}}}}'
# MAC -> vendor map, built inside the OpenSearch container (never pipe into "sudo docker exec -i")
TRUTH=$(sudo docker exec nettap-opensearch sh -c '
curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --cacert /usr/share/opensearch/config/certs/ca.crt \
    --insecure -H "Content-Type: application/json" "https://localhost:9200/arkime_sessions3-*/_search" -d "$1" |
python3 -c "
import json, sys
d = json.load(sys.stdin)
print(json.dumps({b[\"key\"].lower(): b[\"oui\"][\"buckets\"][0][\"key\"] for b in d[\"aggregations\"][\"mac\"][\"buckets\"] if b[\"oui\"][\"buckets\"]}))
"' _ "$BODY" 2>/dev/null)
# The registry refreshes once at startup; give it up to a minute
OUT=""
for i in $(seq 1 12); do
    OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
truth = json.loads(sys.argv[1] or '{}')
token = open('/run/nettap-auth/daemon-token').read().strip()
def get(path):
    req = urllib.request.Request('http://localhost:8880' + path, headers={'X-NetTap-Daemon-Token': token})
    return json.load(urllib.request.urlopen(req, timeout=120))
devices = get('/api/devices?limit=500')['devices']
registry = get('/api/devices/registry?limit=500')['devices']
tool = get('/api/tools/mac-lookup/BC:24:11:00:00:00')
miss = [d for d in devices if d.get('mac') and d['mac'].lower() in truth and d.get('manufacturer') in (None, 'Unknown')]
reg_miss = [r for r in registry if r.get('mac', '').lower() in truth and not r.get('manufacturer')]
cats = {}
for d in devices:
    cats[d['category']] = cats.get(d['category'], 0) + 1
wrong = [d for d in devices if not d.get('os_hint') and not d.get('hostname') and (
    ('Ubiquiti' in (d.get('manufacturer') or '') and d['category'] != 'infrastructure')
    or ('Philips Lighting' in (d.get('manufacturer') or '') and d['category'] != 'iot'))]
bad_reg_cat = [r for r in registry if r.get('category') not in ('computer', 'phone', 'iot', 'infrastructure', 'unknown')]
for d in devices:
    print('DEVICE', d['ip'], d.get('mac'), '|', d.get('manufacturer'), '|', d['category'])
print('CATS', json.dumps(cats, sort_keys=True))
print('TOOL', tool.get('found'), tool.get('vendor'))
print('SUMMARY', len(truth), len(devices), len(miss), len(registry), len(reg_miss), len(wrong), len(bad_reg_cat), int('Proxmox' in (tool.get('vendor') or '')))
" "$TRUTH" 2>&1)
    read -r _ _ _ _ _ RMISS _ _ <<<"$(echo "$OUT" | grep '^SUMMARY')"
    [ "${RMISS:-1}" = "0" ] && break
    sleep 5
done
while IFS= read -r line; do echo "   $line"; done <<<"$OUT"
read -r _ NTRUTH NDEV MISS NREG RMISS WRONG BADCAT TOOLOK <<<"$(echo "$OUT" | grep '^SUMMARY')"
if [ "${NTRUTH:-0}" -ge 1 ] && [ "${MISS:-1}" -eq 0 ]; then rc=0; else rc=1; fi
check "#26 Devices: every MAC Malcolm names has a manufacturer" "$rc" "${NDEV:-?} devices, ${MISS:-?} still Unknown (Malcolm names ${NTRUTH:-?} MACs)"
if [ "${RMISS:-1}" -eq 0 ] && [ "${BADCAT:-1}" -eq 0 ]; then rc=0; else rc=1; fi
check "#26 Registry (Home grid, device pages): vendors filled, categories valid" "$rc" "${NREG:-?} entries, ${RMISS:-?} without a vendor Malcolm knows, ${BADCAT:-?} invalid categories"
if [ "${WRONG:-1}" -eq 0 ]; then rc=0; else rc=1; fi
check "#26 Ubiquiti -> infrastructure, Philips Lighting -> iot" "$rc" "${WRONG:-?} wrong"
if [ "${TOOLOK:-0}" -eq 1 ]; then rc=0; else rc=1; fi
check "#26 Tools -> MAC Lookup knows bc:24:11 (Proxmox)" "$rc" "$(echo "$OUT" | grep '^TOOL' | cut -d' ' -f2-)"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|suricata-live|zeek-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 13 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
