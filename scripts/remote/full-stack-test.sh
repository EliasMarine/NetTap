#!/usr/bin/env bash
# =============================================================================
# NetTap Full Stack Test — Phase 5 Mirror/SPAN Mode
#
# Run on the NetTap device after deploying. Tests all services, APIs, and
# new features end-to-end.
#
# Architecture note: The daemon API (port 8880) is internal to the Docker
# network — NOT published to the host. All daemon API checks use
# `docker exec` to curl from inside the container. Web UI checks go
# through nginx (ports 80/443), which is the only published entry point.
#
# Usage: sudo bash full-stack-test.sh
# =============================================================================

# Do NOT use set -e — we want the script to keep running through failures
set -uo pipefail

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------

if [ -z "${NETTAP_DIR:-}" ]; then
    if [ -d "/home/nettap/NetTap" ]; then
        NETTAP_DIR="/home/nettap/NetTap"
    elif [ -d "$HOME/NetTap" ]; then
        NETTAP_DIR="$HOME/NetTap"
    else
        echo "ERROR: Cannot find NetTap directory. Set NETTAP_DIR env var."
        exit 1
    fi
fi

COMPOSE_FILE="${NETTAP_DIR}/docker/docker-compose.yml"
DAEMON_CONTAINER="nettap-storage-daemon"
DAEMON_URL="http://localhost:8880"
PASS=0
FAIL=0
SKIP=0
ERRORS=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

green()  { echo -e "\e[32m✓ $*\e[0m"; }
red()    { echo -e "\e[31m✗ $*\e[0m"; }
yellow() { echo -e "\e[33m⊘ $*\e[0m"; }
blue()   { echo -e "\e[34m→ $*\e[0m"; }

check() {
    local desc="$1"
    shift
    if eval "$@" >/dev/null 2>&1; then
        green "$desc"
        PASS=$((PASS + 1))
    else
        red "$desc"
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}\n  - ${desc}"
    fi
}

# Daemon API check — runs curl INSIDE the daemon container via docker exec.
# This is required because port 8880 is only exposed within the Docker
# network (not published to the host).
check_api() {
    local desc="$1"
    local endpoint="$2"
    local status
    status=$(docker exec "$DAEMON_CONTAINER" \
        curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
        "${DAEMON_URL}${endpoint}" 2>/dev/null || echo "000")
    if [ "$status" = "200" ]; then
        green "$desc (HTTP $status)"
        PASS=$((PASS + 1))
    else
        red "$desc (HTTP $status)"
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}\n  - ${desc} (HTTP ${status})"
    fi
}

# Fetch JSON from daemon API via docker exec, pretty-print with python3
api_json() {
    local endpoint="$1"
    docker exec "$DAEMON_CONTAINER" \
        curl -s --max-time 5 "${DAEMON_URL}${endpoint}" 2>/dev/null
}

# Web UI check — goes through nginx (published on 80/443)
check_web() {
    local url="$1"
    local desc="$2"
    local status
    status=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
    if [ "$status" = "200" ]; then
        green "$desc (HTTP $status)"
        PASS=$((PASS + 1))
    else
        red "$desc (HTTP $status)"
        FAIL=$((FAIL + 1))
        ERRORS="${ERRORS}\n  - ${desc} (HTTP ${status})"
    fi
}

skip_check() {
    yellow "$1"
    SKIP=$((SKIP + 1))
}

header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Pretty-print JSON via python3
pjson() {
    python3 -m json.tool 2>/dev/null || echo "  (could not parse)"
}

# ---------------------------------------------------------------------------
# 0. Prerequisites
# ---------------------------------------------------------------------------

header "0. PREREQUISITES"

check "Running as root" "[ $(id -u) -eq 0 ]"
check "Docker is running" "docker info"
check "NetTap dir exists" "[ -d '$NETTAP_DIR' ]"
check "docker-compose.yml exists" "[ -f '$COMPOSE_FILE' ]"

# ---------------------------------------------------------------------------
# 1. Pull latest code & rebuild
# ---------------------------------------------------------------------------

header "1. DEPLOY LATEST CODE"

blue "Pulling latest from phase-5/mirror-span-mode..."
cd "$NETTAP_DIR"
git fetch origin || true
git checkout phase-5/mirror-span-mode 2>/dev/null || true
git pull origin phase-5/mirror-span-mode || true
echo ""

blue "Rebuilding daemon container..."
docker compose -f "$COMPOSE_FILE" build nettap-storage-daemon || {
    red "Docker build failed!"
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}\n  - Docker build failed"
}
echo ""

blue "Recreating daemon container..."
docker compose -f "$COMPOSE_FILE" up -d nettap-storage-daemon --force-recreate || {
    red "Docker up failed!"
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}\n  - Docker up failed"
}
echo ""

blue "Waiting 20s for daemon to start..."
sleep 20

# Quick crash-loop check — if daemon is restarting, show logs and warn
DAEMON_STATUS=$(docker ps --format '{{.Status}}' --filter "name=^${DAEMON_CONTAINER}$" 2>/dev/null || echo "")
if echo "$DAEMON_STATUS" | grep -qi "restarting"; then
    echo ""
    red "DAEMON IS CRASH-LOOPING — last 30 log lines:"
    echo "────────────────────────────────────────"
    docker logs "$DAEMON_CONTAINER" --tail 30 2>&1 || true
    echo "────────────────────────────────────────"
    echo ""
    red "Fix the daemon crash before API tests can pass."
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}\n  - Daemon crash-loop detected"
fi

# ---------------------------------------------------------------------------
# 2. Container Health
# ---------------------------------------------------------------------------

header "2. CONTAINER HEALTH"

blue "Container status:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "nettap|NAME" || true
echo ""

check "Daemon container running (not restarting)" \
    "docker ps --format '{{.Names}}\t{{.Status}}' | grep $DAEMON_CONTAINER | grep -qv Restarting"
check "OpenSearch container running" \
    "docker ps --format '{{.Names}}' | grep -q nettap-opensearch"

# Capture containers (optional)
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qE "zeek-live|suricata-live"; then
    check "Zeek container running" "docker ps --format '{{.Names}}' | grep -q zeek-live"
    check "Suricata container running" "docker ps --format '{{.Names}}' | grep -q suricata-live"
else
    skip_check "Capture containers not running (expected if bridge/mirror not configured)"
    SKIP=$((SKIP + 1))
fi

# Verify curl is available inside daemon container
if ! docker exec "$DAEMON_CONTAINER" which curl >/dev/null 2>&1; then
    echo ""
    red "curl not found in daemon container — Dockerfile needs 'curl' in apt-get install."
    red "All API checks will fail. Rebuild with updated Dockerfile."
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}\n  - curl missing from daemon container"
fi

# ---------------------------------------------------------------------------
# 3. Core API Endpoints
# ---------------------------------------------------------------------------

header "3. CORE API ENDPOINTS"

check_api "GET /api/health" "/api/health"
check_api "GET /api/storage/status" "/api/storage/status"
check_api "GET /api/smart/health" "/api/smart/health"
check_api "GET /api/smart/diagnostics" "/api/smart/diagnostics"
check_api "GET /api/indices" "/api/indices"
check_api "GET /api/system/health" "/api/system/health"

# ---------------------------------------------------------------------------
# 4. Capture Mode API (Phase A)
# ---------------------------------------------------------------------------

header "4. CAPTURE MODE API (Phase A)"

check_api "GET /api/capture/mode" "/api/capture/mode"
check_api "GET /api/capture/health" "/api/capture/health"
check_api "GET /api/capture/stats" "/api/capture/stats"
check_api "GET /api/capture/interface" "/api/capture/interface"

blue "Current capture mode:"
api_json "/api/capture/mode" | pjson

# ---------------------------------------------------------------------------
# 5. SMART Health (Phase B)
# ---------------------------------------------------------------------------

header "5. SMART HEALTH (Phase B)"

blue "SMART health data:"
api_json "/api/smart/health" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'  Drive:       {d.get(\"model\", \"unknown\")}')
    print(f'  Temperature: {d.get(\"temperature\", \"N/A\")}')
    print(f'  Wear:        {d.get(\"percentage_used\", \"N/A\")}%')
    print(f'  Power Hours: {d.get(\"power_on_hours\", \"N/A\")}')
except: print('  (could not parse)')
" 2>/dev/null || echo "  (daemon unreachable)"

# ---------------------------------------------------------------------------
# 6. Storage (Phase C)
# ---------------------------------------------------------------------------

header "6. STORAGE HARDENING (Phase C)"

blue "Disk usage:"
api_json "/api/storage/status" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    disk = d.get('disk', d)
    used = disk.get('disk_used_gb', disk.get('used_gb', '?'))
    total = disk.get('disk_total_gb', disk.get('total_gb', '?'))
    pct = disk.get('disk_usage_percent', disk.get('usage_percent', '?'))
    print(f'  Used: {used} GB / {total} GB ({pct}%)')
except: print('  (could not parse)')
" 2>/dev/null || echo "  (daemon unreachable)"

# ---------------------------------------------------------------------------
# 7. Device Registry (Phase D)
# ---------------------------------------------------------------------------

header "7. DEVICE REGISTRY (Phase D)"

check_api "GET /api/devices/registry" "/api/devices/registry"
check_api "GET /api/integrations/unifi/status" "/api/integrations/unifi/status"

blue "Discovered devices:"
api_json "/api/devices/registry?limit=10" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    devices = d if isinstance(d, list) else d.get('devices', [])
    print(f'  Total: {len(devices)} devices')
    for dev in devices[:5]:
        name = dev.get('friendly_name') or dev.get('manufacturer') or dev.get('mac', 'unknown')
        ip = ', '.join(dev.get('ips', [])) if dev.get('ips') else dev.get('ip', '?')
        print(f'  - {name} ({ip})')
except: print('  (no devices yet or could not parse)')
" 2>/dev/null || echo "  (daemon unreachable)"

# ---------------------------------------------------------------------------
# 8. Live Connections (Phase G)
# ---------------------------------------------------------------------------

header "8. LIVE CONNECTIONS (Phase G)"

check_api "GET /api/live/connections" "/api/live/connections"
check_api "GET /api/live/rate" "/api/live/rate"

blue "Connection rate:"
api_json "/api/live/rate" | pjson

# ---------------------------------------------------------------------------
# 9. Bandwidth (Phase G)
# ---------------------------------------------------------------------------

header "9. BANDWIDTH TRACKER (Phase G)"

check_api "GET /api/bandwidth/cap" "/api/bandwidth/cap"
check_api "GET /api/bandwidth/daily" "/api/bandwidth/daily"
check_api "GET /api/bandwidth/devices" "/api/bandwidth/devices"

# ---------------------------------------------------------------------------
# 10. DNS Analytics (Phase H)
# ---------------------------------------------------------------------------

header "10. DNS ANALYTICS (Phase H)"

check_api "GET /api/dns/stats" "/api/dns/stats"
check_api "GET /api/dns/top-domains" "/api/dns/top-domains"
check_api "GET /api/dns/nxdomain" "/api/dns/nxdomain"
check_api "GET /api/dns/suspicious" "/api/dns/suspicious"

# ---------------------------------------------------------------------------
# 11. IoT & LAN Security (Phase H)
# ---------------------------------------------------------------------------

header "11. IoT & LAN SECURITY (Phase H)"

check_api "GET /api/iot/devices" "/api/iot/devices"
check_api "GET /api/iot/anomalies" "/api/iot/anomalies"
check_api "GET /api/lan/anomalies" "/api/lan/anomalies"
check_api "GET /api/lan/arp-spoofing" "/api/lan/arp-spoofing"
check_api "GET /api/lan/rogue-dhcp" "/api/lan/rogue-dhcp"

# ---------------------------------------------------------------------------
# 12. Notifications (Phase I)
# ---------------------------------------------------------------------------

header "12. NOTIFICATIONS (Phase I)"

check_api "GET /api/notifications/channels" "/api/notifications/channels"
check_api "GET /api/notifications/rules" "/api/notifications/rules"

# ---------------------------------------------------------------------------
# 13. Changelog (Phase I)
# ---------------------------------------------------------------------------

header "13. CHANGELOG (Phase I)"

check_api "GET /api/changelog" "/api/changelog"
check_api "GET /api/changelog/types" "/api/changelog/types"

# ---------------------------------------------------------------------------
# 14. Certificates (Phase I)
# ---------------------------------------------------------------------------

header "14. CERTIFICATES (Phase I)"

check_api "GET /api/certificates/stats" "/api/certificates/stats"
check_api "GET /api/certificates/expiring" "/api/certificates/expiring"

# ---------------------------------------------------------------------------
# 15. MAC Correlation (Phase J)
# ---------------------------------------------------------------------------

header "15. MAC CORRELATION (Phase J)"

check_api "GET /api/mac/merge-history" "/api/mac/merge-history"

# ---------------------------------------------------------------------------
# 16. PCAP Search (Phase J)
# ---------------------------------------------------------------------------

header "16. PCAP SEARCH (Phase J)"

check_api "GET /api/pcap/files" "/api/pcap/files"

# ---------------------------------------------------------------------------
# 17. Config Backup (Phase J)
# ---------------------------------------------------------------------------

header "17. CONFIG BACKUP (Phase J)"

check_api "GET /api/backup/export" "/api/backup/export"

# ---------------------------------------------------------------------------
# 18. Suricata Rules (Phase K)
# ---------------------------------------------------------------------------

header "18. SURICATA RULES (Phase K)"

check_api "GET /api/suricata/rules/sources" "/api/suricata/rules/sources"
check_api "GET /api/suricata/rules/stats" "/api/suricata/rules/stats"
check_api "GET /api/suricata/rules/schedule" "/api/suricata/rules/schedule"

blue "Rule sources:"
api_json "/api/suricata/rules/sources" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    sources = d if isinstance(d, list) else d.get('sources', [])
    for s in sources:
        status = '✓' if s.get('enabled') else '✗'
        print(f'  {status} {s.get(\"id\", \"?\")} — {s.get(\"description\", \"\")}')
except: print('  (could not parse)')
" 2>/dev/null || echo "  (daemon unreachable)"

# ---------------------------------------------------------------------------
# 19. Web UI (through nginx on ports 80/443)
# ---------------------------------------------------------------------------

header "19. WEB UI (via nginx)"

# Nginx is the only published entry point (ports 80/443).
# Try HTTPS first (self-signed cert, so use -k), then HTTP.
WEB_URL=""
for candidate in "https://localhost" "http://localhost"; do
    status=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 3 "$candidate" 2>/dev/null || echo "000")
    if [ "$status" = "200" ] || [ "$status" = "302" ] || [ "$status" = "301" ]; then
        WEB_URL="$candidate"
        blue "Web UI reachable at ${WEB_URL} (HTTP $status)"
        break
    fi
done

if [ -n "$WEB_URL" ]; then
    check_web "$WEB_URL/" "Web UI root"
    check_web "$WEB_URL/live" "Live connections page"
    check_web "$WEB_URL/bandwidth" "Bandwidth page"
    check_web "$WEB_URL/dns" "DNS analytics page"
    check_web "$WEB_URL/iot" "IoT monitor page"
    check_web "$WEB_URL/changelog" "Changelog page"
    check_web "$WEB_URL/certificates" "Certificates page"
    check_web "$WEB_URL/pcap" "PCAP search page"
    check_web "$WEB_URL/settings/notifications" "Notification settings"
    check_web "$WEB_URL/settings/backup" "Backup settings"
    check_web "$WEB_URL/settings/suricata-rules" "Suricata rules settings"
    check_web "$WEB_URL/setup" "Setup wizard"
else
    skip_check "Web UI not reachable via nginx (ports 80/443)"
    SKIP=$((SKIP + 11))
fi

# ---------------------------------------------------------------------------
# 20. OpenSearch Health
# ---------------------------------------------------------------------------

header "20. OPENSEARCH HEALTH"

OS_HEALTH=$(docker exec nettap-opensearch curl --config /var/local/curlrc/.opensearch.primary.curlrc \
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure -s \
    'https://localhost:9200/_cluster/health' 2>/dev/null || echo "{}")

blue "Cluster health:"
echo "$OS_HEALTH" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'  Status:  {d.get(\"status\", \"unknown\")}')
    print(f'  Nodes:   {d.get(\"number_of_nodes\", \"?\")}')
    print(f'  Indices: {d.get(\"active_primary_shards\", \"?\")} primary shards')
except: print('  (could not parse)')
" 2>/dev/null

OS_STATUS=$(echo "$OS_HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
if [ "$OS_STATUS" = "green" ] || [ "$OS_STATUS" = "yellow" ]; then
    green "OpenSearch cluster health: $OS_STATUS"
    PASS=$((PASS + 1))
else
    red "OpenSearch cluster health: ${OS_STATUS:-unreachable}"
    FAIL=$((FAIL + 1))
    ERRORS="${ERRORS}\n  - OpenSearch cluster health: ${OS_STATUS:-unreachable}"
fi

# ---------------------------------------------------------------------------
# 21. Daemon Logs (always show tail for debugging)
# ---------------------------------------------------------------------------

header "21. DAEMON LOG TAIL"

blue "Last 15 daemon log lines:"
echo "────────────────────────────────────────"
docker logs "$DAEMON_CONTAINER" --tail 15 2>&1 || echo "  (could not fetch logs)"
echo "────────────────────────────────────────"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

header "RESULTS"

TOTAL=$((PASS + FAIL + SKIP))
echo ""
echo "  Passed:  $PASS"
echo "  Failed:  $FAIL"
echo "  Skipped: $SKIP"
echo "  Total:   $TOTAL"
echo ""

if [ "$FAIL" -gt 0 ]; then
    red "$FAIL CHECK(S) FAILED:"
    echo -e "$ERRORS"
    echo ""
fi

if [ "$FAIL" -eq 0 ]; then
    green "ALL CHECKS PASSED!"
    exit 0
else
    exit 1
fi
