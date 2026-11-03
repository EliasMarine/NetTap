#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 8 (PCAP preview time limit) and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #52 a filtered preview that runs out of time says so (timed_out), instead of
#       showing an empty list as "No packets to display"
#   e7c22ab Retention card wording "Policy synced" (web only, unit-tested)
# Capture (netsniff, Zeek, Suricata) is not restarted.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch8.sh
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

echo "=== Deploy: dashboard data accuracy, batch 8 (PCAP preview time limit) ==="
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

echo "→ Step 4: Check the preview time limit through the daemon API (~1-2 min)..."
# "frame.len == 1" never matches, so tshark reads until the file ends or time runs out.
# At 0.5 CPU it reads ~5 MB/s: a file over 400 MB cannot finish in 45 s, one under
# 100 MB always does. One Python block in the daemon container: nothing piped into sudo.
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, time, urllib.parse, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
def get(path, **q):
    url = 'http://localhost:8880' + path + '?' + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={'X-NetTap-Daemon-Token': token})
    t = time.monotonic()
    body = json.load(urllib.request.urlopen(req, timeout=120))
    return body, time.monotonic() - t
try:
    files, _ = get('/api/pcap/files')
    done = files['files'][1:]  # skip the file netsniff is still writing
    big = max(done, key=lambda f: f['size_bytes'])
    small = min(done, key=lambda f: f['size_bytes'])
    for tag, f in (('BIG', big), ('SMALL', small)):
        p, dt = get('/api/pcap/preview', file=f['file'], filter='frame.len == 1', limit=100)
        print(f'{tag} {f[\"size_bytes\"] // 1000000} {p[\"count\"]} {p.get(\"timed_out\")} {dt:.1f}')
except Exception as e:
    print('ERR', e)
")
while IFS= read -r line; do echo "   $line"; done <<<"$OUT"

read -r _ MB N TIMED DT <<<"$(echo "$OUT" | grep '^BIG')"
if [ "${MB:-0}" -lt 400 ]; then
    check "#52 big-file preview reports it ran out of time" 0 "skipped: largest file is only ${MB:-?} MB (needs > 400 MB)"
elif [ "${TIMED:-}" = "True" ] && [ "${N:-x}" = "0" ] && awk -v t="${DT:-99}" 'BEGIN { exit !(t < 60) }'; then
    check "#52 big-file preview reports it ran out of time" 0 "${MB} MB: ${N} packets, timed_out=${TIMED} in ${DT} s"
else
    check "#52 big-file preview reports it ran out of time" 1 "${MB:-?} MB: ${N:-?} packets, timed_out=${TIMED:-?} in ${DT:-?} s"
fi

read -r _ MB N TIMED DT <<<"$(echo "$OUT" | grep '^SMALL')"
if [ "${MB:-999}" -ge 100 ]; then
    check "#52 small-file preview is a real 'no match'" 0 "skipped: smallest file is ${MB:-?} MB (needs < 100 MB)"
elif [ "${TIMED:-}" = "False" ] && [ "${N:-x}" = "0" ]; then
    check "#52 small-file preview is a real 'no match'" 0 "${MB} MB: ${N} packets, timed_out=${TIMED} in ${DT} s"
else
    check "#52 small-file preview is a real 'no match'" 1 "${MB:-?} MB: ${N:-?} packets, timed_out=${TIMED:-?} in ${DT:-?} s"
fi

PROCS=$(sudo docker top nettap-tshark -eo pid,args 2>/dev/null | awk 'NR > 1 && $2 == "tshark"' | wc -l)
if [ "$PROCS" -le 2 ]; then rc=0; else rc=1; fi
check "#48 no tshark left running after the timed-out read" "$rc" "tshark=$PROCS (limit 2)"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|nettap-tshark|zeek-live|suricata-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 8 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
