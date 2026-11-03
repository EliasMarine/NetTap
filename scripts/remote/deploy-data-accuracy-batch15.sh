#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 15 (device list speed, categories, page widths) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #21 Devices page: the per-device fingerprint lookups go out as one _msearch, not 4 queries a device
#   #69 Devices page: Windows PCs are Computers and game consoles are Media (they were Unknown)
#   #67 Settings: Suricata Rules, Backup and Notifications are full width (browser pass)
#
# The device list is saved before the deploy and compared after it over the same time window:
# MAC, hostname, OS and vendor must not change; a category may only move off "unknown".
# The daemon and web restart. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch15.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
# One fixed window for both snapshots, so new traffic can't make them differ
TO_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)

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

snapshot() {  # prints "MS <median ms>" then one tab-separated line per device, sorted by IP
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, time, urllib.parse, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
url = 'http://localhost:8880/api/devices?' + urllib.parse.urlencode({'limit': 500, 'from': sys.argv[1], 'to': sys.argv[2]})
times = []
for _ in range(3):
    t0 = time.time()
    devices = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={'X-NetTap-Daemon-Token': token}), timeout=120))['devices']
    times.append(time.time() - t0)
print('MS', int(sorted(times)[1] * 1000))
clean = lambda v: str(v if v is not None else '-').replace('\t', ' ').replace('\n', ' ')
for d in sorted(devices, key=lambda d: d['ip']):
    print('\t'.join(clean(d.get(k)) for k in ('ip', 'mac', 'hostname', 'os_hint', 'manufacturer', 'category')))
" "$FROM_TS" "$TO_TS" 2>&1
}

echo "=== Deploy: dashboard data accuracy, batch 15 (device list speed, categories, page widths) ==="
echo "   Window for the device comparison: $FROM_TS → $TO_TS"
echo ""

echo "→ Step 1: Save the device list from the running daemon..."
BEFORE_RAW=$(snapshot)
BEFORE_MS=$(echo "$BEFORE_RAW" | awk '$1 == "MS" {print $2}')
BEFORE=$(echo "$BEFORE_RAW" | grep -P '\t' || true)
echo "   ✓ $(echo "$BEFORE" | grep -c .) devices, /api/devices took ${BEFORE_MS:-?} ms (median of 3)"
echo ""

echo "→ Step 2: Pull latest code..."
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

echo "→ Step 3: Build the daemon and web images..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 4: Recreate the daemon and web..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo "   waiting for the startup registry refresh to finish (it loads OpenSearch)..."
for i in $(seq 1 36); do
    sudo docker logs --since 10m nettap-storage-daemon 2>&1 | grep -q "Device registry refresh" && break
    sleep 5
done
echo ""

echo "→ Step 5: Compare the device list..."
AFTER_RAW=$(snapshot)
AFTER_MS=$(echo "$AFTER_RAW" | awk '$1 == "MS" {print $2}')
AFTER=$(echo "$AFTER_RAW" | grep -P '\t' || true)
echo "$AFTER_RAW" | grep -v -P '\t' | grep -v '^MS ' | sed 's/^/   /'
NB=$(echo "$BEFORE" | grep -c .)
NA=$(echo "$AFTER" | grep -c .)
# Same IP, different MAC / hostname / OS / vendor
DRIFT=$(awk -F'\t' 'NR == FNR {k[$1] = $2 FS $3 FS $4 FS $5; next} ($1 in k) && k[$1] != ($2 FS $3 FS $4 FS $5) {print $1 ": " k[$1] " → " $2 FS $3 FS $4 FS $5}' <(echo "$BEFORE") <(echo "$AFTER"))
# Category changes; only a move off "unknown" is intended
CHANGED=$(awk -F'\t' 'NR == FNR {c[$1] = $6; o[$1] = $4; next} ($1 in c) && c[$1] != $6 {print $1 " (" o[$1] "): " c[$1] " → " $6}' <(echo "$BEFORE") <(echo "$AFTER"))
BAD=$(echo "$CHANGED" | grep . | grep -v -c ': unknown → ')
[ -n "$DRIFT" ] && while IFS= read -r line; do echo "   drift  $line"; done <<<"$DRIFT"
[ -n "$CHANGED" ] && while IFS= read -r line; do echo "   category  $line"; done <<<"$CHANGED"

if [ "$NB" -gt 0 ] && [ "$NB" = "$NA" ]; then rc=0; else rc=1; fi
check "#21 same devices before and after" "$rc" "$NB before, $NA after"
if [ "$NB" -gt 0 ] && [ -z "$DRIFT" ]; then rc=0; else rc=1; fi
check "#21 MAC, hostname, OS and vendor unchanged" "$rc" "$(echo "$DRIFT" | grep -c .) devices differ"
if [ "$BAD" -eq 0 ]; then rc=0; else rc=1; fi
check "#69 category changes only fill in Unknown" "$rc" "$(echo "$CHANGED" | grep -c .) changed, $BAD not from unknown"
if [ -n "${AFTER_MS:-}" ] && [ "$AFTER_MS" -lt 1500 ]; then rc=0; else rc=1; fi
check "#21 /api/devices is fast" "$rc" "${BEFORE_MS:-?} ms → ${AFTER_MS:-?} ms (limit=500, median of 3)"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 15 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
