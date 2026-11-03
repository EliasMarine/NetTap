#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 14 (TShark filters, PCAP page) and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #64 TShark tool: a display filter searches the whole file, not just its first N packets
#   #65 TShark tool: Analyze uses the filter typed in the box (unit-tested; browser pass)
#   #63 PCAP page: "Top Protocol in Preview" label (browser pass)
#   #23 PCAP end to end: newest file current, filtered analysis, file download intact
#   #66 PCAP preview/download refuse paths outside the PCAP directory (".." or a sibling dir)
#
# The daemon and web restart. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch14.sh
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

echo "=== Deploy: dashboard data accuracy, batch 14 (TShark filters, PCAP) ==="
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

echo "→ Step 3: Recreate the daemon and web..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo ""

echo "→ Step 4: PCAP and TShark checks..."
# All API calls run inside the daemon container; replies stay there (they can be large)
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, time, urllib.error, urllib.parse, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
def call(path, body=None, timeout=90):
    req = urllib.request.Request('http://localhost:8880' + path, headers={'X-NetTap-Daemon-Token': token, 'Content-Type': 'application/json'},
        data=None if body is None else json.dumps(body).encode(), method='GET' if body is None else 'POST')
    return urllib.request.urlopen(req, timeout=timeout)
pcaps = json.load(call('/api/tshark/pcaps'))['pcaps']
pcaps = sorted(pcaps, key=lambda p: p['modified'], reverse=True)
print('NEWEST', pcaps[0]['name'], int(time.time() - pcaps[0]['modified']))
target = next(p for p in pcaps[1:] if 20e6 < p['size_bytes'] < 400e6)  # closed, mid-sized
print('FILE', target['name'], target['size_bytes'])
t0 = time.time()
r = json.load(call('/api/tshark/analyze', {'pcap_path': target['path'], 'display_filter': 'dns', 'max_packets': 50, 'output_format': 'json'}))
dns = sum('dns' in (p.get('_source', {}).get('layers') or {}) for p in r.get('packets', []))
print('DNS', r.get('packet_count'), dns, round(time.time() - t0, 1), r.get('truncated'), r.get('error'))
t0 = time.time()
r = json.load(call('/api/tshark/analyze', {'pcap_path': target['path'], 'display_filter': 'dns && tcp.port == 1', 'max_packets': 50, 'output_format': 'json'}))
print('NONE', r.get('packet_count'), round(time.time() - t0, 1), r.get('error'))
# The page downloads by the full path the PCAP listing gives
listed = json.load(call('/api/pcap/files'))['files']
full = next(f['file'] for f in listed if f['file'].endswith('/' + target['name']))
resp = call('/api/pcap/download-file?' + urllib.parse.urlencode({'file': full}), timeout=300)
head = resp.read(4); total = 4 + sum(len(c) for c in iter(lambda: resp.read(1 << 20), b''))
print('DOWNLOAD', head.hex(), total)
codes = []
for bad in (full.rsplit('/', 1)[0] + '/../../../etc/passwd', full.rsplit('/', 1)[0] + '-old/x.pcap'):
    try:
        codes.append(str(call('/api/pcap/download-file?' + urllib.parse.urlencode({'file': bad})).status))
    except urllib.error.HTTPError as e:
        codes.append(str(e.code))
print('OUTSIDE', ','.join(codes))
" 2>&1)
while IFS= read -r line; do echo "   $line"; done <<<"$OUT"
read -r _ NEWEST AGE <<<"$(echo "$OUT" | grep '^NEWEST')"
read -r _ FILE SIZE <<<"$(echo "$OUT" | grep '^FILE')"
read -r _ COUNT DNS SECS TRUNC _ <<<"$(echo "$OUT" | grep '^DNS')"
read -r _ NONE NONESECS _ <<<"$(echo "$OUT" | grep '^NONE')"
read -r _ MAGIC GOT <<<"$(echo "$OUT" | grep '^DOWNLOAD')"
read -r _ OUTSIDE <<<"$(echo "$OUT" | grep '^OUTSIDE')"
# Ground truth: the first 50 DNS packets, straight from tshark in its container
TRUTH=$(sudo docker exec nettap-tshark sh -c 'tshark -r "$1" -Y dns -T fields -e frame.number 2>/dev/null | head -n 50 | wc -l' _ "/pcap/${FILE:-none}" 2>/dev/null | tr -d ' ')

if [ -n "${AGE:-}" ] && [ "$AGE" -lt 900 ]; then rc=0; else rc=1; fi
check "#23 capture is writing" "$rc" "newest file ${NEWEST:-?} modified ${AGE:-?} s ago"
if [ -n "${COUNT:-}" ] && [ "${COUNT}" = "${TRUTH:-x}" ] && [ "${COUNT}" = "${DNS:-y}" ] && [ "${COUNT}" -gt 0 ]; then rc=0; else rc=1; fi
check "#64 TShark filter 'dns' finds the file's DNS packets" "$rc" "${COUNT:-?} packets, ${DNS:-?} with a DNS layer, tshark direct ${TRUTH:-?}, ${SECS:-?} s, truncated=${TRUNC:-?} (${FILE:-?})"
if [ "${NONE:-x}" = "0" ]; then rc=0; else rc=1; fi
check "#64 a filter with no matches answers 0 without error" "$rc" "${NONE:-?} packets in ${NONESECS:-?} s"
case "${MAGIC:-}" in d4c3b2a1|a1b2c3d4|4d3cb2a1|a1b23c4d|0a0d0d0a) MOK=0 ;; *) MOK=1 ;; esac
if [ "$MOK" -eq 0 ] && [ "${GOT:-0}" = "${SIZE:-x}" ]; then rc=0; else rc=1; fi
check "#23 PCAP download is a whole pcap file" "$rc" "magic ${MAGIC:-?}, ${GOT:-?} of ${SIZE:-?} bytes"
if [ "${OUTSIDE:-}" = "400,400" ]; then rc=0; else rc=1; fi
check "#66 download refuses '..' and a sibling directory" "$rc" "HTTP ${OUTSIDE:-?}"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|nettap-tshark|suricata-live|zeek-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 14 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
