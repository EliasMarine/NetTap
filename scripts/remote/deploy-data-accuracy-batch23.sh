#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 23 (TShark scan speed) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #78 TShark: a filtered analysis spent the whole 15 s match-scan budget every time, because
#       piped tshark buffers its output and kept reading after head had what it needed
#
# Only the daemon is rebuilt and restarted. Capture (netsniff, Zeek, Suricata) is not touched.
# Ends with the read-only acceptance check for the whole goal.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch23.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
MAX_SECONDS=8  # scan ~1 s + JSON ~1.7 s + Info ~1 s on the G11, with room for a busy box

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

timed_analyses() {  # "<label> <packets> <seconds> <error>" for a common and a rare filter
    sudo docker exec nettap-storage-daemon python3 -c "
import json, time, urllib.parse, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
def call(path, body=None):
    req = urllib.request.Request('http://localhost:8880' + path, headers={'X-NetTap-Daemon-Token': token, 'Content-Type': 'application/json'},
        data=None if body is None else json.dumps(body).encode(), method='GET' if body is None else 'POST')
    return json.load(urllib.request.urlopen(req, timeout=120))
pcaps = sorted(call('/api/tshark/pcaps')['pcaps'], key=lambda p: p['modified'], reverse=True)
target = next(p for p in pcaps[1:] if 20e6 < p['size_bytes'] < 400e6)
for label, filt in (('analyze-dns', 'dns'), ('analyze-tls', 'tls.handshake.type == 1')):
    t0 = time.time()
    r = call('/api/tshark/analyze', {'pcap_path': target['path'], 'display_filter': filt, 'max_packets': 50, 'output_format': 'json'})
    print(label, r.get('packet_count'), round(time.time() - t0, 1), r.get('error'))
full = next(f['file'] for f in call('/api/pcap/files')['files'] if f['file'].endswith('/' + target['name']))
t0 = time.time()
p = call('/api/pcap/preview?' + urllib.parse.urlencode({'file': full, 'filter': 'dns', 'limit': 20}))
print('preview-dns', len(p.get('packets', [])), round(time.time() - t0, 1), p.get('error'))
" 2>&1
}

echo "=== Deploy: dashboard data accuracy, batch 23 (TShark scan speed) ==="
echo ""

echo "→ Step 1: Timings before..."
BEFORE=$(timed_analyses)
while IFS= read -r line; do echo "   $line"; done <<<"$BEFORE"
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

echo "→ Step 4: Timings after..."
AFTER=$(timed_analyses)
while IFS= read -r line; do echo "   $line"; done <<<"$AFTER"
read -r _ N SECS ERR <<<"$(echo "$AFTER" | grep '^analyze-dns')"
NB=$(echo "$BEFORE" | awk '$1 == "analyze-dns" {print $2}')
if [ "${N:-0}" = "50" ] && [ "${ERR:-x}" = "None" ] && awk -v s="${SECS:-99}" -v m="$MAX_SECONDS" 'BEGIN {exit !(s < m)}'; then rc=0; else rc=1; fi
check "#78 TShark 'dns' analysis returns 50 packets in under $MAX_SECONDS s" "$rc" "${N:-?} packets in ${SECS:-?} s (before: ${NB:-?} in $(echo "$BEFORE" | awk '$1 == "analyze-dns" {print $3}') s)"
read -r _ N2 _ ERR2 <<<"$(echo "$AFTER" | grep '^analyze-tls')"
N2B=$(echo "$BEFORE" | awk '$1 == "analyze-tls" {print $2}')
# At least as many: a scan cut off by its time limit used to lose tshark's unflushed buffer
if [ "${N2:-0}" -gt 0 ] && [ "${ERR2:-x}" = "None" ] && [ "$N2" -ge "${N2B:-0}" ]; then rc=0; else rc=1; fi
check "#78 a second filter returns at least the packets it did before" "$rc" "'tls.handshake.type == 1': ${N2B:-?} → ${N2:-?}"
read -r _ PN _ PERR <<<"$(echo "$AFTER" | grep '^preview-dns')"
if [ "${PN:-0}" = "20" ] && [ "${PERR:-x}" = "None" ]; then rc=0; else rc=1; fi
check "#78 PCAP preview still returns its 20 packets" "$rc" "${PN:-?} packets, error ${PERR:-?}"
echo ""

echo "→ Step 5: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 23 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
