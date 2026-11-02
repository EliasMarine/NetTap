#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 5 and check each change on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# Batch 5 (owner decisions 2026-11-02 plus the Live Monitor fixes):
#   #44 arkime-live off: removed here; compose keeps it behind the "arkime" profile
#   #37 PCAP capped at PCAP_MAX_DISK_PCT of the disk (default 25%), oldest first
#   #45 Live Monitor: bundled world map, LAN-only device count, NIC line-rate
#       bandwidth, connection total in the protocol donut
# Capture (netsniff, Zeek, Suricata) is not restarted.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch5.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
OS_CURL=(sudo docker exec nettap-opensearch curl -s
    --config /var/local/curlrc/.opensearch.primary.curlrc
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure
    -H "Content-Type: application/json")
FAILED=0

api_eval() {  # api_eval <path> '<python expression over d>'
    # Fetches and parses inside the daemon container: no host python3, and nothing
    # is piped into sudo (its stdin may carry the password). eval is safe here: every
    # expression is a literal written in this script, never data from the API.
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
path, expr = sys.argv[1], sys.argv[2]
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + path, headers={'X-NetTap-Daemon-Token': token})
try:
    d = json.load(urllib.request.urlopen(req, timeout=120))
    print(eval(expr))
except Exception as e:
    print('ERR', e)
" "$@"
}

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

echo "=== Deploy: dashboard data accuracy, batch 5 ==="
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

echo "→ Step 3: Remove arkime-live (#44)..."
# docker rm, not "docker compose ... arkime-live": naming the service starts it again
if sudo docker ps -a --format '{{.Names}}' | grep -qx nettap-arkime-live; then
    sudo docker rm -f nettap-arkime-live >/dev/null && echo "   ✓ nettap-arkime-live removed"
else
    echo "   ✓ nettap-arkime-live was not present"
fi
echo ""

echo "→ Step 4: Recreate the daemon and web..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo ""

echo "→ Step 5: Check each change..."
LEFT=$(sudo docker ps -a --format '{{.Names}}' | grep -cx nettap-arkime-live)
if [ "$LEFT" -eq 0 ]; then rc=0; else rc=1; fi
check "#44 arkime-live is gone" "$rc" "containers=$LEFT"

if "${COMPOSE[@]}" config --services 2>/dev/null | grep -qx arkime-live; then rc=1; else rc=0; fi
check "#44 a plain 'docker compose up' no longer starts arkime-live" "$rc" "default services exclude it"

echo "   (waiting 60 s, then counting OpenSearch TLS errors from the old Arkime loop...)"
sleep 60
TLS_ERRS=$(sudo docker logs nettap-opensearch --since 50s 2>&1 | grep -c "TLS handshake failed")
if [ "$TLS_ERRS" -eq 0 ]; then rc=0; else rc=1; fi
check "#44 OpenSearch TLS handshake errors in the last 50 s" "$rc" "errors=$TLS_ERRS (was ~58 a minute)"

CAP=$(sudo docker exec nettap-storage-daemon printenv PCAP_MAX_DISK_PCT 2>/dev/null)
PCAP_SHARE=$(sudo docker exec nettap-storage-daemon python3 -c "
import os, shutil
from pathlib import Path
d = os.environ.get('PCAP_DIR', '/opt/nettap/pcap')
used = sum(p.stat().st_size for p in Path(d).rglob('*.pcap'))
print(round(used * 100 / shutil.disk_usage(d).total, 1), round(used / 1e9, 1))" 2>/dev/null)
SHARE_PCT=${PCAP_SHARE%% *}
if [ "${CAP:-}" = "25" ] && awk -v s="${SHARE_PCT:-999}" -v c="${CAP:-0}" 'BEGIN { exit !(s <= c + 1) }'; then rc=0; else rc=1; fi
check "#37 PCAP stays within its disk share" "$rc" "cap=${CAP:-?}% now=${SHARE_PCT:-?}% (${PCAP_SHARE##* } GB)"

GEO=$(curl -sk -o /dev/null -w '%{http_code} %{size_download}' https://localhost/geo/countries-110m.geojson)
if [ "${GEO%% *}" = "200" ] && [ "${GEO##* }" -gt 100000 ]; then rc=0; else rc=1; fi
check "#45 Live map serves its bundled world outline" "$rc" "HTTP ${GEO%% *}, ${GEO##* } bytes"

LAN_Q='{"size":0,"query":{"bool":{"filter":[{"term":{"event.dataset":"conn"}},{"range":{"@timestamp":{"gte":"now-5m"}}},{"terms":{"source.ip":["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]}}]}},"aggs":{"n":{"cardinality":{"field":"source.ip"}}}}'
LAN_TRUTH=$("${OS_CURL[@]}" "https://localhost:9200/arkime_sessions3-*/_search" -d "$LAN_Q" | grep -o '"n":{"value":[0-9]*' | grep -o '[0-9]*$')
ACTIVE=$(api_eval /api/live/dashboard "d['stats']['active_devices']")
WINDOW=$(api_eval /api/live/dashboard "d['stats'].get('connections_in_window')")
# both are 5-minute windows taken seconds apart
if [ -n "$LAN_TRUTH" ] && [ "${ACTIVE:-x}" -ge $((LAN_TRUTH - 3)) ] 2>/dev/null && [ "$ACTIVE" -le $((LAN_TRUTH + 3)) ]; then rc=0; else rc=1; fi
check "#45 Live active devices = LAN sources in 5 min" "$rc" "live=${ACTIVE:-?} OpenSearch=${LAN_TRUTH:-?} (connections in window=${WINDOW:-?})"

IFACE=$(api_eval /api/capture/interface "d.get('interface') or ''")
api_eval /api/live/dashboard "d['stats']['bandwidth_bytes_per_second']" >/dev/null  # primes the sampler
A=$(cat "/sys/class/net/$IFACE/statistics/rx_bytes" 2>/dev/null); T0=$(date +%s)
sleep 10
B=$(cat "/sys/class/net/$IFACE/statistics/rx_bytes" 2>/dev/null); T1=$(date +%s)
LIVE_BW=$(api_eval /api/live/dashboard "int(d['stats']['bandwidth_bytes_per_second'])")
NIC_BW=$(( (${B:-0} - ${A:-0}) / ( (T1 - T0) > 0 ? (T1 - T0) : 1 ) ))
if [ "${NIC_BW:-0}" -gt 0 ] && awk -v l="${LIVE_BW:-0}" -v n="$NIC_BW" 'BEGIN { r = l / n; exit !(r > 0.7 && r < 1.3) }'; then rc=0; else rc=1; fi
check "#45 Live bandwidth = capture NIC line rate" "$rc" "live=${LIVE_BW:-?} B/s NIC($IFACE)=$NIC_BW B/s"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|zeek-live|suricata-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 5 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
