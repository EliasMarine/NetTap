#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 1 and check each fix on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# Recreates: daemon, zeek-live (no hourly conn-summary), logstash and
# nettap-cyberchef (loopback ports for the daemon). Logstash takes ~3 min to
# start its pipelines; Filebeat queues logs meanwhile.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch1.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
OS_CURL=(sudo docker exec nettap-opensearch curl -s
    --config /var/local/curlrc/.opensearch.primary.curlrc
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure)
FAILED=0

api() {
    local token
    token=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)
    curl -s -m 30 -H "X-NetTap-Daemon-Token: $token" "http://localhost:8880$1"
}

check() {  # check "label" <condition result 0/1> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_healthy() {
    local name="$1" status="unknown"
    for i in $(seq 1 60); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && { echo "   ✓ $name healthy"; return 0; }
        [ $((i % 6)) -eq 0 ] && echo "   waiting... $name=$status ($i/60)"
        sleep 5
    done
    echo "   ✗ $name not healthy after 5 min ($status)"
    FAILED=1
}

echo "=== Deploy: dashboard data accuracy, batch 1 ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the daemon and zeek-live images..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon zeek-live; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate daemon, zeek-live, logstash and cyberchef..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon zeek-live logstash nettap-cyberchef
echo ""

echo "→ Step 4: Wait for health (Logstash pipelines take ~3 min)..."
wait_healthy nettap-storage-daemon
wait_healthy nettap-cyberchef
wait_healthy nettap-logstash
echo ""

echo "→ Step 5: Remove the stray 1970 index (one junk conn-summary record, owner approved)..."
if "${OS_CURL[@]}" -o /dev/null -w '%{http_code}' "https://localhost:9200/arkime_sessions3-700101" | grep -q 200; then
    "${OS_CURL[@]}" -X DELETE "https://localhost:9200/arkime_sessions3-700101" | grep -q '"acknowledged":true' \
        && echo "   ✓ Deleted arkime_sessions3-700101" || { echo "   ✗ Delete failed"; FAILED=1; }
else
    echo "   ✓ Not present"
fi
echo ""

echo "→ Step 6: Check each fix..."
DEV_COUNT=$(api /api/devices/count | grep -o '"count": *[0-9]*' | grep -o '[0-9]*$')
DEV_LIST=$(api "/api/devices?limit=500" | grep -o '"ip": *"' | wc -l | tr -d ' ')
if [ -n "$DEV_COUNT" ] && [ "$DEV_COUNT" = "$DEV_LIST" ] && [ "$DEV_COUNT" -gt 4 ]; then rc=0; else rc=1; fi; check "#2/#3 device count = list" "$rc" "count=${DEV_COUNT:-?} list=$DEV_LIST"

MACS=$(api "/api/devices?limit=500" | grep -o '"mac": *"[0-9a-f:]\{17\}"' | wc -l | tr -d ' ')
if [ "$MACS" -gt 0 ]; then rc=0; else rc=1; fi; check "#1 devices have MACs" "$rc" "$MACS of $DEV_LIST"

TOP=$(api "/api/dns/top-domains?limit=50" | grep -c '"pcap-monitor"')
if [ "$TOP" -eq 0 ]; then rc=0; else rc=1; fi; check "#4 pcap-monitor not in DNS top domains" "$rc" "occurrences=$TOP"

DNS=$(api /api/dns/stats)
echo "     dns stats: $(printf '%s' "$DNS" | grep -oE '"(total_queries|nxdomain_count|avg_resolution_ms|median_resolution_ms)": *[0-9.]+' | tr '\n' ' ')"

LS_CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 30 -H "X-NetTap-Daemon-Token: $(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)" http://localhost:8880/api/logstash/stats)
if [ "$LS_CODE" = "200" ]; then rc=0; else rc=1; fi; check "#7 Logstash panels" "$rc" "HTTP $LS_CODE"

CC=$(api /api/cyberchef/status)
if printf '%s' "$CC" | grep -qiE '"(healthy|available|running|reachable)": *true|"status": *"(healthy|running|ok)"'; then rc=0; else rc=1; fi; check "#8 CyberChef reachable" "$rc" "$(printf '%s' "$CC" | head -c 160)"

UP=$(api /api/system/health | grep -o '"uptime": *[0-9.]*' | grep -o '[0-9.]*$' | cut -d. -f1)
HOST_UP=$(cut -d. -f1 /proc/uptime)
if [ -n "$UP" ] && [ $((HOST_UP - UP)) -lt 120 ] && [ $((UP - HOST_UP)) -lt 120 ]; then rc=0; else rc=1; fi; check "#9 uptime is the machine's" "$rc" "api=${UP:-?}s host=${HOST_UP}s"

HEALTH=$("${OS_CURL[@]}" "https://localhost:9200/_cluster/health" | grep -o '"status":"[a-z]*"')
if printf '%s' "$HEALTH" | grep -q green; then rc=0; else rc=1; fi; check "#10 cluster health" "$rc" "$HEALTH"

TS=$(sudo docker exec nettap-zeek-live grep -c '^TraceSummary =$' /usr/local/zeek/etc/zeekctl.cfg 2>/dev/null)
if [ "${TS:-0}" -ge 1 ]; then rc=0; else rc=1; fi; check "#11 conn-summary disabled" "$rc" "TraceSummary lines=${TS:-0}"

RISK_CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 30 -H "X-NetTap-Daemon-Token: $(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)" http://localhost:8880/api/risk/scores)
if [ "$RISK_CODE" = "200" ]; then rc=0; else rc=1; fi; check "#12 risk scores" "$rc" "HTTP $RISK_CODE"

SUMMARY=$(api /api/traffic/summary | grep -o '"total_bytes": *[0-9.]*' | grep -o '[0-9.]*$' | cut -d. -f1)
MONTH=$(api /api/bandwidth/monthly | grep -o '"total_bytes": *[0-9.]*' | grep -o '[0-9.]*$' | cut -d. -f1)
echo "     #13 bandwidth: 24h summary=${SUMMARY:-?} month=${MONTH:-?} (should match while all data is from today)"

DEV_MS=$(curl -s -o /dev/null -w '%{time_total}' -m 60 -H "X-NetTap-Daemon-Token: $(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)" "http://localhost:8880/api/devices?limit=500")
echo "     devices endpoint time: ${DEV_MS}s"
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|zeek-live|logstash|cyberchef"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 1 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
