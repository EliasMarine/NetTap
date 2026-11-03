#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 51 and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #137: PCAP Search fits the box. tshark needs ~120 MiB plus about the file's size, so
#     4 GB capture files couldn't be searched in the TShark container's 1 GiB. Capture files
#     rotate at 256 MB (owner decision 2026-11-03, set here through the Capture settings
#     API), the TShark container gets 1 CPU, an out-of-memory kill is reported as such, and
#     the page shows sizes and a time-left estimate and searches the last hour by default.
#   Recreating the daemon ends any PCAP search that is running.
#
# The full output is also saved to ~/nettap-batch51.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch51.sh
set -u
exec > >(tee "$HOME/nettap-batch51.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

api() {  # api METHOD PATH [JSON]: the daemon API from inside its container
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
t = open('/run/nettap-auth/daemon-token').read().strip()
m, p = sys.argv[1], sys.argv[2]
d = sys.argv[3].encode() if len(sys.argv) > 3 else None
r = urllib.request.Request('http://localhost:8880' + p, method=m, data=d,
                           headers={'X-NetTap-Daemon-Token': t, 'Content-Type': 'application/json'})
try:
    print(json.dumps(json.load(urllib.request.urlopen(r, timeout=120))))
except urllib.error.HTTPError as e:
    print(json.dumps({'http_error': e.code, 'body': e.read().decode()[:300]}))
" "$@"
}

echo "=== Deploy: dashboard data accuracy, batch 51 (PCAP Search fits the box) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the daemon and web, recreate them and the TShark container..."
for svc in nettap-storage-daemon nettap-web; do
    if ! "${COMPOSE[@]}" build "$svc"; then
        echo "   ✗ $svc build failed — nothing was restarted"
        exit 1
    fi
done
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web nettap-tshark
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
CPUS=$(sudo docker inspect --format='{{.HostConfig.NanoCpus}}' nettap-tshark 2>/dev/null)
if [ "$CPUS" = "1000000000" ]; then rc=0; else rc=1; fi
check "TShark container has 1 CPU" "$rc" "NanoCpus=$CPUS"
echo ""

echo "→ Step 3: Capture files rotate at 256 MB (Capture settings API)..."
OUT=$(api PUT /api/capture/settings '{"maxFileSizeMB": 256}')
echo "   $OUT"
STATUS_JSON=$(api GET /api/capture/status)
case "$STATUS_JSON" in *'"maxFileSizeMB": 256'*'"containerRunning": true'*) rc=0 ;; *) rc=1 ;; esac
check "capture status reads 256 MB and running" "$rc" "$STATUS_JSON"
SET_AT=$(date +%s)
echo ""

echo "→ Step 4: A capture file closes at 256 MB (waits up to 12 minutes)..."
PCAP=/var/lib/docker/volumes/docker_pcap-data/_data
CLOSED=""
for _ in $(seq 1 72); do
    # files newer than the setting change, oldest first; all but the newest are closed
    CLOSED=$(sudo find "$PCAP" -name '*.pcap' -newermt "@$SET_AT" -printf '%T@ %s %f\n' | sort -n | head -n -1 | tail -1)
    [ -n "$CLOSED" ] && break
    sleep 10
done
if [ -n "$CLOSED" ]; then
    SIZE=$(echo "$CLOSED" | awk '{print $2}')
    if [ "$SIZE" -le $((257 * 1048576)) ]; then rc=0; else rc=1; fi
    check "a closed file is at most 256 MiB" "$rc" "$(echo "$CLOSED" | awk '{print $3}') $((SIZE / 1048576)) MiB"
else
    check "a closed file is at most 256 MiB" 1 "no file closed within 12 minutes"
fi
echo ""

echo "→ Step 5: An 'http || tls' search over the files since the change, with exact counts..."
# files written before the change are up to ~800 MB and may run out of memory (reported as such)
FROM=$(date -u -d "@$SET_AT" +%Y-%m-%dT%H:%M:%SZ)
TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
Q="/api/pcap/search?filter=http+%7C%7C+tls&from=$FROM&to=$TO"
START=$(date +%s)
RES=""
for _ in $(seq 1 120); do
    RES=$(api GET "$Q")
    case "$RES" in *'"complete": true'*) break ;; esac
    sleep 10
done
SUMMARY=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, sys
r = json.loads(sys.argv[1])
print('   files', r.get('files_checked'), 'of', r.get('files_total'), '| GB', round(r.get('bytes_total', 0) / 1e9, 1),
      '| matched files', r.get('count'), '| timed out', r.get('timed_out'), '| failed', r.get('failed'), r.get('error') or '',
      '| seconds', r.get('seconds_elapsed'))
print('BIGGEST', max(r.get('results', []), key=lambda x: x['size_bytes'], default={}).get('name', ''),
      max(r.get('results', []), key=lambda x: x['size_bytes'], default={}).get('matching_packets', ''))
" "$RES" 2>&1)
echo "$SUMMARY" | head -1
case "$RES" in *'"complete": true'*'"timed_out": 0'*'"failed": 0'*) rc=0 ;; *) rc=1 ;; esac
check "search complete, no file timed out or ran out of memory" "$rc" "in $(( $(date +%s) - START )) s"
read -r _ BIG BIGN < <(echo "$SUMMARY" | grep '^BIGGEST')
if [ -n "${BIG:-}" ]; then
    DIRECT=$(sudo docker exec nettap-tshark sh -c 'tshark -r "/pcap/$1" -Y "http || tls" -T fields -e frame.number 2>/dev/null | wc -l' _ "$BIG")
    if [ "$DIRECT" = "$BIGN" ]; then rc=0; else rc=1; fi
    check "the largest matched file's count = tshark run directly" "$rc" "$BIG: search $BIGN, tshark $DIRECT"
fi
echo ""

echo "→ Step 6: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 51 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
