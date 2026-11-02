#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 7 (Settings page) and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #53 Capture tab: shows the size netsniff really rotates at, and Save applies it
#   #54 Retention tab: ILM health no longer "Out of sync" after a clean startup apply
#   #55 About tab: real version and readable uptime (web only, unit-tested)
#
# The #53 check saves a different file size, confirms netsniff restarts with it,
# then saves the original back: pcap-capture restarts twice (a few seconds each).
# Zeek and Suricata keep capturing.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch7.sh
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

api() {  # api <METHOD> <path> [json body]  -> prints the JSON reply (or ERR ...)
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
method, path = sys.argv[1], sys.argv[2]
body = sys.argv[3].encode() if len(sys.argv) > 3 else None
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + path, data=body, method=method,
    headers={'X-NetTap-Daemon-Token': token, 'Content-Type': 'application/json'})
try:
    print(json.dumps(json.load(urllib.request.urlopen(req, timeout=120))))
except Exception as e:
    print('ERR', e)
" "$@"
}

field() {  # field '<json>' <key>
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    for k in sys.argv[2].split('.'):
        d = d[k]
    print(d)
except Exception:
    print('')
" "$1" "$2"
}

netsniff_size() {  # the -F value netsniff is running with, e.g. 4096MiB
    sudo docker top nettap-pcap-capture -eo pid,args 2>/dev/null | awk '$2 ~ /netsniff-ng$/ { for (i = 1; i <= NF; i++) if ($i == "-F") print $(i + 1) }' | head -1
}

wait_netsniff_size() {  # wait_netsniff_size <expected>  (up to 90 s)
    local got=""
    for _ in $(seq 1 30); do
        got=$(netsniff_size)
        [ "$got" = "$1" ] && break
        sleep 3
    done
    echo "$got"
}

echo "=== Deploy: dashboard data accuracy, batch 7 (Settings) ==="
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

echo "→ Step 3: Recreate the daemon and web (the daemon now gets PCAP_ROTATE_MB/MIN)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo ""

echo "→ Step 4: Check the Settings data..."
CONTAINER_MB=$(sudo docker inspect nettap-pcap-capture --format '{{range .Config.Env}}{{println .}}{{end}}' | awk -F= '$1 == "PCAP_ROTATE_MEGABYTES" { print $2 }')
CONTAINER_MIN=$(sudo docker inspect nettap-pcap-capture --format '{{range .Config.Env}}{{println .}}{{end}}' | awk -F= '$1 == "PCAP_ROTATE_MINUTES" { print $2 }')
RUNNING=$(netsniff_size)
STATUS=$(api GET /api/capture/status)
SHOWN_MB=$(field "$STATUS" maxFileSizeMB)
SHOWN_MIN=$(field "$STATUS" rotateMinutes)
if [ -n "$SHOWN_MB" ] && [ "${SHOWN_MB}MiB" = "$RUNNING" ] && [ "$SHOWN_MIN" = "$CONTAINER_MIN" ]; then rc=0; else rc=1; fi
check "#53 Capture tab shows what netsniff runs with" "$rc" "page=${SHOWN_MB:-?} MB / ${SHOWN_MIN:-?} min, netsniff -F ${RUNNING:-?}, compose ${CONTAINER_MB:-?} MB / ${CONTAINER_MIN:-?} min"

ORIG=${SHOWN_MB:-4096}
TRY=1024
[ "$ORIG" = "$TRY" ] && TRY=2048
PUT=$(api PUT /api/capture/settings "{\"maxFileSizeMB\": $TRY}")
GOT=$(wait_netsniff_size "${TRY}MiB")
if [ "$GOT" = "${TRY}MiB" ]; then rc=0; else rc=1; fi
check "#53 Save applies the size to netsniff" "$rc" "saved $TRY → netsniff -F ${GOT:-?} (reply: $PUT)"

PUT=$(api PUT /api/capture/settings "{\"maxFileSizeMB\": $ORIG}")
GOT=$(wait_netsniff_size "${ORIG}MiB")
if [ "$GOT" = "${ORIG}MiB" ]; then rc=0; else rc=1; fi
check "#53 original size restored" "$rc" "saved $ORIG → netsniff -F ${GOT:-?}"

CAPTURE_ENV=$(sudo cat /etc/nettap/capture.env 2>/dev/null | tr '\n' ' ')
case "$CAPTURE_ENV" in *"PCAP_IFACE=enp4s0"*"PCAP_ROTATE_MEGABYTES=$ORIG"*) rc=0 ;; *) rc=1 ;; esac
check "#53 capture.env keeps the capture interface and holds the size" "$rc" "$CAPTURE_ENV"

SYNCED=""
for _ in $(seq 1 24); do  # the first storage cycle applies ILM at startup
    SYNCED=$(field "$(api GET /api/storage/status)" ilm_status.synced)
    [ "$SYNCED" = "True" ] && break
    sleep 5
done
if [ "$SYNCED" = "True" ]; then rc=0; else rc=1; fi
check "#54 Retention card: ILM policies synced" "$rc" "ilm_status.synced=${SYNCED:-?}"

PCAPS_NOW=$(sudo docker exec nettap-storage-daemon sh -c 'ls -t /opt/nettap/pcap/*.pcap | head -1')
check "capture still writing after the restarts" 0 "newest file ${PCAPS_NOW##*/}"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|pcap-capture|zeek-live|suricata-live"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 7 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
