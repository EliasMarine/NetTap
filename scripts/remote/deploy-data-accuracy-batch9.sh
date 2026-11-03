#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 9 and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #27 Suricata reassembles IP fragments itself: no more "AF-PACKET/IPv4 truncated
#       packet" alerts (it inspected only the first 1514 bytes of each fragmented datagram)
#   #38 Infrastructure shows the mirror port, not an unconfigured bridge, in mirror mode
#   #39 index counts agree (System "Data Indices"; Infrastructure "N data · M system")
#   #20 Home says UNIDENTIFIED instead of UNKNOWN
#   Settings never saves defaults over real settings after a failed load (unit-tested)
#
# suricata-live restarts once (~1-2 min without IDS alerts while rules load).
# Zeek and netsniff keep capturing. The #27 check pings the gateway 3 times with
# 3000-byte packets (they fragment) and watches them on the mirror port.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch9.sh
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

api() {  # api <path> -> the daemon's JSON reply (or ERR ...)
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + sys.argv[1], headers={'X-NetTap-Daemon-Token': token})
try:
    print(json.dumps(json.load(urllib.request.urlopen(req, timeout=60))))
except Exception as e:
    print('ERR', e)
" "$1"
}

# Count lines in Suricata's newest eve file that match $1 and are stamped at or after $2.
# eve timestamps look like 2026-11-02T07:27:51.803748+0000, so a string compare works.
read -r -d '' EVE_COUNT <<'SH'
F=$(ls -t /var/log/suricata/live/eve*.json 2>/dev/null | head -1)
[ -n "$F" ] || { echo 0; exit 0; }
tail -c 8000000 "$F" | grep -e "$1" | awk -F'"' -v t="$2" '$4 >= t' | wc -l
SH
eve_count() { sudo docker exec nettap-suricata-live sh -c "$EVE_COUNT" _ "$1" "$2" 2>/dev/null || echo 0; }

echo "=== Deploy: dashboard data accuracy, batch 9 ==="
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

echo "→ Step 2: Build the web image..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Image built"
echo ""

echo "→ Step 3: Recreate the web and suricata-live (Suricata picks up AF_PACKET defrag off)..."
RESTART=$(date -u +%Y-%m-%dT%H:%M:%S)
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web suricata-live
wait_healthy nettap-web
NEW=0
for i in $(seq 1 36); do  # Suricata has no healthcheck: wait for it to log new events
    NEW=$(eve_count '"event_type"' "$RESTART")
    [ "${NEW:-0}" -gt 0 ] && break
    [ $((i % 6)) -eq 0 ] && echo "   waiting for Suricata to load its rules... ($i/36)"
    sleep 5
done
if [ "${NEW:-0}" -gt 0 ]; then rc=0; else rc=1; fi
check "suricata-live inspecting again" "$rc" "${NEW:-0} new eve events since $RESTART"
echo ""

echo "→ Step 4: Check the fixes..."
DEFRAG=$(sudo docker exec nettap-suricata-live sh -c "sed -n '/^af-packet:/,/^[a-z]/p' /etc/suricata/suricata.yaml | grep -m1 'defrag:'" 2>/dev/null | awk '{print $2}')
case "$DEFRAG" in no|false) rc=0 ;; *) rc=1 ;; esac
check "#27 Suricata af-packet kernel defrag off" "$rc" "defrag: ${DEFRAG:-?}"

CAPIF=$(sudo cat /etc/nettap/capture.env 2>/dev/null | awk -F= '$1 == "PCAP_IFACE" { print $2 }')
GW=$(ip route show default | awk '{ print $3; exit }')
MYIP=$(ip route get "$GW" 2>/dev/null | awk '{ for (i = 1; i <= NF; i++) if ($i == "src") print $(i + 1) }' | head -1)
FRAGFILE=$(mktemp)
T0=$(date -u +%Y-%m-%dT%H:%M:%S)
# shellcheck disable=SC2024  # the output file is this user's own mktemp; only tcpdump needs root
sudo timeout 12 tcpdump -l -n -i "${CAPIF:-enp4s0}" "host ${MYIP:-0.0.0.0} and ip[6:2] & 0x3fff != 0" >"$FRAGFILE" 2>/dev/null &
TCPDUMP_PID=$!
sleep 2
ping -c 3 -s 3000 -W 1 "$GW" >/dev/null 2>&1
wait "$TCPDUMP_PID" 2>/dev/null
FRAGS=$(wc -l <"$FRAGFILE" | tr -d ' ')
rm -f "$FRAGFILE"
sleep 15  # let Suricata flush eve
TRUNC=$(eve_count 'truncated packet' "$T0")
if [ "${FRAGS:-0}" -lt 6 ]; then
    check "#27 fragmented test pings seen on the mirror port" 1 "only ${FRAGS:-0} fragments on ${CAPIF:-?} (ping $MYIP → $GW); cannot judge the fix"
elif [ "${TRUNC:-x}" = "0" ]; then
    check "#27 no truncated-packet alerts for fragmented traffic" 0 "${FRAGS} fragments on ${CAPIF}, 0 alerts (was 12 for the same 3 pings)"
else
    check "#27 no truncated-packet alerts for fragmented traffic" 1 "${FRAGS} fragments on ${CAPIF}, ${TRUNC:-?} truncated-packet alerts"
fi

HEALTH=$(api /api/capture/health)
case "$HEALTH" in *'"mode": "mirror"'*'"link_up": true'*) rc=0 ;; *) rc=1 ;; esac
check "#38 mirror-port data the Infrastructure node shows" "$rc" "$(echo "$HEALTH" | cut -c1-160)"

COUNTS=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
def get(p):
    req = urllib.request.Request('http://localhost:8880' + p, headers={'X-NetTap-Daemon-Token': token})
    return json.load(urllib.request.urlopen(req, timeout=60))
try:
    names = [i['index'] for i in get('/api/opensearch/indices')['indices']]
    data = sum(not n.startswith('.') for n in names)
    print(len(names), data, get('/api/storage/status').get('total_indices'))
except Exception as e:
    print('ERR', e)
")
read -r ALL DATA SYS_PAGE <<<"$COUNTS"
if [ -n "${DATA:-}" ] && [ "${DATA}" = "${SYS_PAGE:-x}" ]; then rc=0; else rc=1; fi
check "#39 System 'Data Indices' = Infrastructure's data count" "$rc" "all=${ALL:-?} data=${DATA:-?} system page=${SYS_PAGE:-?}"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|storage-daemon|suricata-live|zeek-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 9 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
