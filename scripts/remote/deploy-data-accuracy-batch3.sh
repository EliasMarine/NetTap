#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 3 and check each fix on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# Recreates the daemon and web (new code) and zeek-live and suricata-live
# (offline PCAP processor switched off). Capture pauses for a few seconds while
# the live containers restart. arkime-live is off by default since 2026-11-02 (#44).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch3.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
OS_CURL=(sudo docker exec nettap-opensearch curl -s
    --config /var/local/curlrc/.opensearch.primary.curlrc
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure
    -H "Content-Type: application/json")
FAILED=0

api() {
    local token
    token=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)
    curl -s -m 60 -H "X-NetTap-Daemon-Token: $token" "http://localhost:8880$1"
}

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

json_num() {  # json_num <key> — first numeric value of "key" on stdin
    grep -o "\"$1\": *[0-9.]*" | head -1 | grep -o '[0-9.]*$'
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

echo "=== Deploy: dashboard data accuracy, batch 3 ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
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

echo "→ Step 3: Recreate daemon, web and the live capture containers..."
# OLD CODE START — 2026-11-02: arkime-live is off by default (compose profile "arkime", #44); naming it here would start it
# "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web zeek-live suricata-live arkime-live
# OLD CODE END
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web zeek-live suricata-live
# nginx bind-mounts nginx.conf as a single file; git replaced the file, so a reload
# would keep the old copy. A restart re-reads it (CSP worker-src for CyberChef).
sudo docker restart nettap-nginx >/dev/null
echo ""

echo "→ Step 4: Wait for health..."
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
CSP=$(curl -skI https://localhost/cyberchef/ | grep -i '^content-security-policy')
if printf '%s' "$CSP" | grep -q "worker-src 'self' blob:"; then rc=0; else rc=1; fi
check "#36 CSP lets CyberChef start its workers" "$rc" "$(printf '%s' "$CSP" | grep -o "worker-src[^;]*" || echo 'worker-src missing')"
# OLD CODE START — 2026-11-02: arkime-live is off by default (compose profile "arkime", #44)
# for c in nettap-zeek-live nettap-suricata-live nettap-arkime-live; do
# OLD CODE END
for c in nettap-zeek-live nettap-suricata-live; do
    state=$(sudo docker inspect --format='{{.State.Status}}' "$c" 2>/dev/null || echo "missing")
    if [ "$state" = "running" ]; then rc=0; else rc=1; fi
    check "$c running" "$rc" "$state"
done
echo ""

echo "→ Step 5: Check each fix..."
# OLD CODE START — 2026-11-02: arkime-live is off by default (compose profile "arkime", #44)
# for c in nettap-zeek-live nettap-suricata-live nettap-arkime-live; do
# OLD CODE END
for c in nettap-zeek-live nettap-suricata-live; do
    # wc -l, not grep -c: grep -c exits 1 on a zero count, which tripped the fallback
    PROCS=$(sudo docker exec "$c" sh -c 'ps -eo args | grep "[p]cap_.*_processor.py" | wc -l' 2>/dev/null | tr -d ' ')
    if [ "$PROCS" = "0" ]; then rc=0; else rc=1; fi
    check "#32 no offline PCAP processor in $c" "$rc" "processes=$PROCS"
done

echo "   (waiting 3 min for the registry refresh and for new DNS records to arrive...)"
sleep 180
PCAPMON_Q='{"size":0,"track_total_hits":true,"query":{"bool":{"filter":[{"range":{"@timestamp":{"gte":"now-2m"}}},{"term":{"zeek.dns.query":"pcap-monitor"}}]}}}'
PCAPMON=$("${OS_CURL[@]}" "https://localhost:9200/arkime_sessions3-*/_search" -d "$PCAPMON_Q" | grep -o '"total":{"value":[0-9]*' | grep -o '[0-9]*$')
if [ "${PCAPMON:-1}" -eq 0 ]; then rc=0; else rc=1; fi
check "#32 no pcap-monitor DNS lookups in the last 2 min" "$rc" "lookups=${PCAPMON:-?}"

REG=$(api "/api/devices/registry?limit=200")
REG_COUNT=$(printf '%s' "$REG" | grep -io '"mac": *"[0-9a-f:]\{17\}"' | wc -l | tr -d ' ')  # registry MACs are upper case
if [ "$REG_COUNT" -gt 0 ]; then rc=0; else rc=1; fi
check "#16/#18 device registry filled" "$rc" "devices=$REG_COUNT (device list: $(api /api/devices/count | json_num count))"

JOINED=$(api "/api/changelog?limit=200" | grep -o 'device_joined' | wc -l | tr -d ' ')
if [ "$JOINED" -gt 0 ]; then rc=0; else rc=1; fi
check "#16 changelog has device_joined events" "$rc" "events=$JOINED"

BW=$(api "/api/bandwidth/devices?limit=10")
FIRST_IP=$(printf '%s' "$BW" | grep -o '"ip": *"[^"]*"' | head -1 | cut -d'"' -f4)
PUBLIC=$(printf '%s' "$BW" | grep -o '"ip": *"[^"]*"' | cut -d'"' -f4 | grep -cvE '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)')
TOP_LIST=$(api "/api/devices?sort=bytes&order=desc&limit=1" | grep -o '"ip": *"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -n "$FIRST_IP" ] && [ "$FIRST_IP" = "$TOP_LIST" ] && [ "$PUBLIC" -eq 0 ]; then rc=0; else rc=1; fi
check "#31 bandwidth top device = device list top, LAN only" "$rc" "bandwidth #1=$FIRST_IP devices #1=$TOP_LIST non-LAN rows=$PUBLIC"

STATS_TOTAL=$(api /api/logs/stats | json_num total_events)
SEARCH_TOTAL=$(api "/api/logs/search?size=1" | json_num total)
DIFF=$(( ${STATS_TOTAL:-0} > ${SEARCH_TOTAL:-0} ? ${STATS_TOTAL:-0} - ${SEARCH_TOTAL:-0} : ${SEARCH_TOTAL:-0} - ${STATS_TOTAL:-0} ))
# a few seconds apart, so allow 1% for new records
if [ -n "$STATS_TOTAL" ] && [ -n "$SEARCH_TOTAL" ] && [ $(( DIFF * 100 )) -le "${SEARCH_TOTAL:-1}" ]; then rc=0; else rc=1; fi
check "#33 Log Explorer total = results" "$rc" "stats=${STATS_TOTAL:-?} search=${SEARCH_TOTAL:-?}"

LEVEL=$(api /api/alerts/smart/summary | grep -o '"threat_level": *"[a-z]*"' | cut -d'"' -f4)
echo "     #29 threat level now: ${LEVEL:-?}"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|zeek-live|suricata-live|arkime-live"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 3 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
