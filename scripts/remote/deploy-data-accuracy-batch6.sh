#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 6 (PCAP Search) and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #48 tshark/mergecap run under coreutils timeout inside the container (no orphans)
#   #49 PCAP search is a background job the page polls (no 10 s proxy timeout)
#   #50 filtered preview shows the first 100 matches, not matches among 100 packets
# Capture (netsniff, Zeek, Suricata) is not restarted.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch6.sh
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

echo "=== Deploy: dashboard data accuracy, batch 6 (PCAP Search) ==="
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

echo "→ Step 2: Build the daemon and web images..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the daemon and web, restart tshark (clears any orphaned reads)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
sudo docker restart nettap-tshark >/dev/null && echo "   ✓ nettap-tshark restarted"
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo ""

echo "→ Step 4: Check PCAP preview and search through the daemon API (~2 min)..."
# One Python block in the daemon container: no host python3, nothing piped into sudo.
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
token = open('/run/nettap-auth/daemon-token').read().strip()
def get(path, **q):
    url = 'http://localhost:8880' + path + ('?' + urllib.parse.urlencode(q) if q else '')
    req = urllib.request.Request(url, headers={'X-NetTap-Daemon-Token': token})
    t = time.monotonic()
    body = json.load(urllib.request.urlopen(req, timeout=120))
    return body, time.monotonic() - t
try:
    files, _ = get('/api/pcap/files')
    newest = files['files'][0]['file']
    older = files['files'][1]['file'] if len(files['files']) > 1 else newest
    p, dt = get('/api/pcap/preview', file=newest, limit=100)
    print(f'PREVIEW {p[\"count\"]} {dt:.1f}')
    p, dt = get('/api/pcap/preview', file=older, filter='dns', limit=100)
    dns = sum('dns' in x['protocol'] for x in p['packets'])
    print(f'FILTERED {p[\"count\"]} {dns} {dt:.1f}')
    now = datetime.now(timezone.utc)
    q = dict(filter='dns', **{'from': (now - timedelta(hours=1)).isoformat(), 'to': now.isoformat()})
    s, dt = get('/api/pcap/search', **q)
    print(f'SEARCH_START {s[\"files_total\"]} {s[\"files_checked\"]} {s[\"complete\"]} {dt:.2f}')
    for _ in range(40):
        time.sleep(3)
        s, _ = get('/api/pcap/search', **q)
        if s['files_checked'] >= 1:
            break
    print(f'SEARCH_PROGRESS {s[\"files_checked\"]} {s[\"files_total\"]} {s[\"count\"]} {s[\"timed_out\"]}')
except Exception as e:
    print('ERR', e)
")
while IFS= read -r line; do echo "   $line"; done <<<"$OUT"

read -r _ N DT <<<"$(echo "$OUT" | grep '^PREVIEW')"
if [ "${N:-0}" -ge 1 ] && awk -v t="${DT:-99}" 'BEGIN { exit !(t < 10) }'; then rc=0; else rc=1; fi
check "#48 preview of the newest file answers inside the 10 s proxy limit" "$rc" "${N:-?} packets in ${DT:-?} s"

read -r _ N DNS DT <<<"$(echo "$OUT" | grep '^FILTERED')"
if [ "${N:-0}" -ge 1 ] && [ "${DNS:-0}" -eq "${N:-x}" ]; then rc=0; else rc=1; fi
check "#50 filtered preview returns matching packets from anywhere in the file" "$rc" "${N:-?} packets, ${DNS:-?} DNS, ${DT:-?} s"

read -r _ TOTAL CHECKED COMPLETE DT <<<"$(echo "$OUT" | grep '^SEARCH_START')"
if [ "${TOTAL:-0}" -ge 1 ] && awk -v t="${DT:-99}" 'BEGIN { exit !(t < 2) }'; then rc=0; else rc=1; fi
check "#49 search starts a job and answers at once" "$rc" "files_total=${TOTAL:-?} checked=${CHECKED:-?} complete=${COMPLETE:-?} in ${DT:-?} s"

read -r _ CHECKED TOTAL COUNT TIMED <<<"$(echo "$OUT" | grep '^SEARCH_PROGRESS')"
if [ "${CHECKED:-0}" -ge 1 ]; then rc=0; else rc=1; fi
check "#49 search job makes progress in the background" "$rc" "checked ${CHECKED:-?} of ${TOTAL:-?}, files with DNS=${COUNT:-?}, timed out=${TIMED:-?}"

PROCS=$(sudo docker top nettap-tshark -eo args 2>/dev/null | grep -c '^tshark ')
BOUNDED=$(sudo docker top nettap-tshark -eo args 2>/dev/null | grep -c '^timeout -k 5 ')
if [ "$PROCS" -le 2 ] && [ "$BOUNDED" -ge "$PROCS" ]; then rc=0; else rc=1; fi
check "#48 tshark processes are bounded and few" "$rc" "tshark=$PROCS under-timeout=$BOUNDED (limit 2)"

MEM=$(sudo docker stats --no-stream --format '{{.MemUsage}}' nettap-tshark)
check "#48 tshark container memory" 0 "$MEM (was 909 MiB of 1 GiB with orphans)"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|nettap-tshark|zeek-live|suricata-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 6 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
