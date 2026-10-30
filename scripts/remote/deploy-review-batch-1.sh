#!/usr/bin/env bash
# Deploy code review batch 1 (fix-first findings) and check each fix on the device.
# Run as the normal user: bash scripts/remote/deploy-review-batch-1.sh
# It never enables DHCP gateway mode and never builds or changes the bridge.
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/code-review-batch-1"
COMPOSE="docker/docker-compose.yml"
ENV_FILE="docker/.env"
DAEMON="nettap-storage-daemon"
UNIT="/etc/systemd/system/nettap.service"
WANTS="/etc/systemd/system/multi-user.target.wants"
CURLRC="/var/local/curlrc/.opensearch.primary.curlrc"
OS_CA="/usr/share/opensearch/config/certs/ca.crt"

echo "=== Deploy code review batch 1 ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin || echo "   ✗ git fetch failed"
git checkout "$BRANCH" || echo "   ✗ git checkout $BRANCH failed"
git pull origin "$BRANCH" || echo "   ✗ git pull failed"
echo "   ✓ Code updated: $(git log --oneline -1)"
echo ""

echo "→ Step 2: Make sure docker/.env has the Arkime and Grafana secrets (CR-021, CR-022)..."
# The compose file no longer has built-in fallbacks for these, so every compose
# command fails until both are set. Values are never printed.
ensure_secret() {
    local key="$1"
    if sudo grep -q "^${key}=." "$ENV_FILE" 2>/dev/null; then
        echo "   ✓ $key already set"
        return
    fi
    sudo sed -i "/^${key}=\$/d" "$ENV_FILE" 2>/dev/null || true
    echo "${key}=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')" | sudo tee -a "$ENV_FILE" >/dev/null \
        && echo "   ✓ $key generated" || echo "   ✗ could not write $key to $ENV_FILE"
}
ensure_secret ARKIME_SECRET
ensure_secret GRAFANA_ADMIN_PASSWORD
if sudo docker compose -f "$COMPOSE" config -q; then
    echo "   ✓ Compose file validates"
else
    echo "   ✗ Compose file does not validate — stopping before anything is restarted"
    exit 1
fi
echo ""

echo "→ Step 3: Boot unit stops containers instead of removing them (CR-025)..."
if [ -f "$UNIT" ]; then
    if sudo grep -qE '^ExecStop=.* down$' "$UNIT"; then
        sudo sed -i -E 's/^(ExecStop=.*) down$/\1 stop/' "$UNIT" && echo "   ✓ ExecStop now uses stop"
    else
        echo "   ✓ ExecStop already OK"
    fi
    sudo grep -E '^ExecStop=' "$UNIT" | sed 's/^/     /'
else
    echo "   ! $UNIT not installed — skipped"
fi
echo ""

echo "→ Step 4: Bridge/mirror boot links point at the host unit (LD-001)..."
# The daemon wrote these from inside its container with a /host/... target that
# doesn't exist on the host. Same relative link the fixed daemon now writes.
for name in nettap-bridge nettap-mirror; do
    link="$WANTS/$name.service"
    if [ ! -L "$link" ]; then
        echo "   - $name: not enabled (nothing to fix)"
    elif [ -e "$link" ]; then
        echo "   ✓ $name: link resolves ($(readlink "$link"))"
    elif [ -f "/etc/systemd/system/$name.service" ]; then
        sudo ln -sfn "../$name.service" "$link" && echo "   ✓ $name: fixed dangling link ($(readlink "$link"))"
    else
        echo "   ! $name: dangling link and no unit file — left alone"
    fi
done
sudo systemctl daemon-reload || echo "   ✗ systemctl daemon-reload failed"
echo ""

echo "→ Step 5: Rebuild daemon and web containers..."
sudo docker compose -f "$COMPOSE" build nettap-storage-daemon nettap-web || echo "   ✗ build failed"
echo "   ✓ Images rebuilt"
echo ""

os_auth_ok() {
    sudo docker exec nettap-opensearch curl -s --max-time 10 --config "$CURLRC" --cacert "$OS_CA" --insecure \
        'https://localhost:9200/_cluster/health' 2>/dev/null | grep -q '"cluster_name"'
}

echo "→ Step 6: Recreate OpenSearch with its ROLE_* settings (MS-001)..."
# This used to wipe the role mapping and break auth until a manual bootstrap.
# With MS-001 OpenSearch rebuilds the mapping itself on every start.
sudo docker compose -f "$COMPOSE" up -d --no-deps opensearch || echo "   ✗ recreate failed"
if sudo docker exec nettap-opensearch printenv ROLE_ADMIN >/dev/null 2>&1; then
    echo "   ✓ ROLE_ADMIN is set in the container"
else
    echo "   ✗ ROLE_ADMIN is missing in the container"
fi
OS_OK="false"
for i in $(seq 1 36); do
    if os_auth_ok; then
        OS_OK="true"
        echo "   ✓ OpenSearch auth works with no manual bootstrap (MS-001 confirmed)"
        break
    fi
    echo "   waiting for OpenSearch auth... ($i/36)"
    sleep 5
done
if [ "$OS_OK" != "true" ]; then
    echo "   ✗ Auth still failing after 3 minutes — MS-001 NOT confirmed. Running the old bootstrap as a fallback..."
    bash scripts/remote/fix-opensearch.sh || echo "   ✗ fix-opensearch.sh failed"
fi
sudo docker compose -f "$COMPOSE" restart logstash filebeat || echo "   ✗ logstash/filebeat restart failed"
echo ""

echo "→ Step 7: Recreate the changed services..."
# --no-deps: never recreate OpenSearch again here.
# arkime-live must be recreated, not restarted: Arkime applies passwordSecret
# only when it first writes config.ini inside the container.
sudo docker compose -f "$COMPOSE" up -d --no-deps --force-recreate \
    nettap-storage-daemon nettap-web nettap-nginx nettap-grafana arkime-live \
    || echo "   ✗ recreate failed"
echo "   ✓ Containers recreated"
echo ""

echo "→ Step 8: Wait for containers to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' "$DAEMON" 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        echo "   ✓ Both containers healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
echo ""

echo "→ Step 9: Grafana admin password = GRAFANA_ADMIN_PASSWORD from docker/.env (CR-022)..."
# Grafana only reads GF_SECURITY_ADMIN_PASSWORD when its database is new, so an
# existing install keeps the old default until it is reset. Sent on stdin, never printed.
GRAFANA_RESET="false"
for i in $(seq 1 12); do
    if sudo grep '^GRAFANA_ADMIN_PASSWORD=' "$ENV_FILE" | tail -1 | cut -d= -f2- \
        | sudo docker exec -i nettap-grafana grafana cli admin reset-admin-password --password-from-stdin >/dev/null 2>&1; then
        GRAFANA_RESET="true"
        break
    fi
    sleep 5
done
if [ "$GRAFANA_RESET" = "true" ]; then
    echo "   ✓ Grafana admin password reset (read it with: sudo grep GRAFANA_ADMIN_PASSWORD $REPO_DIR/$ENV_FILE)"
else
    echo "   ✗ Could not reset the Grafana admin password (check: sudo docker logs nettap-grafana --tail 50)"
fi
echo ""

echo "→ Step 10: nginx config (CR-003, CR-022)..."
sudo docker exec nettap-nginx nginx -t 2>&1 | sed 's/^/     /'
echo ""

# HTTP status of an HTTPS request to nginx on this machine (no cookie = logged out).
http_code() {
    curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "$@" 2>/dev/null || echo "000"
}

# Print ✓ when $2 matches the regex $3, ✗ otherwise.
expect() {
    if echo "$2" | grep -qE "^($3)$"; then
        echo "   ✓ $1: $2"
    else
        echo "   ✗ $1: $2 (expected $3)"
    fi
}

echo "→ Step 11: Login gate on Dashboards and Grafana (CR-003, CR-022)..."
expect "/dashboards/ logged out" "$(http_code https://localhost/dashboards/)" "302"
expect "/dashboards/ with forged X-Forwarded-User: admin" \
    "$(http_code -H 'X-Forwarded-User: admin' -H 'X-Forwarded-Roles: admin' https://localhost/dashboards/api/status)" "302"
expect "/grafana/ logged out" "$(http_code https://localhost/grafana/)" "302"
echo ""

echo "→ Step 12: Arkime viewer listens on loopback only (CR-021)..."
ARKIME_LISTEN=$(sudo ss -ltnH 'sport = :8005' 2>/dev/null | awk '{print $4}' | sort -u | tr '\n' ' ')
case "$ARKIME_LISTEN" in
    "") echo "   ! nothing listening on 8005 (viewer not running?)" ;;
    *0.0.0.0:8005* | *\[::\]:8005* | *\*:8005*) echo "   ✗ viewer still on all interfaces: $ARKIME_LISTEN" ;;
    *) echo "   ✓ viewer listens on: $ARKIME_LISTEN" ;;
esac
echo ""

echo "→ Step 13: Login throttling (CR-034)..."
# A made-up username, so the real admin account is never locked.
PROBE_USER="nettap-probe-$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
CODES=""
for i in 1 2 3 4 5 6; do
    CODES="$CODES $(http_code -X POST -H 'Content-Type: application/json' \
        -d "{\"username\":\"$PROBE_USER\",\"password\":\"wrong\"}" https://localhost/api/auth/login)"
done
echo "   6 wrong logins from this machine:$CODES"
expect "6th attempt" "${CODES##* }" "429"
echo "   (logins from this machine are blocked for up to a minute now)"
echo ""

echo "→ Step 14: Read the daemon API token..."
TOKEN=$(sudo docker exec "$DAEMON" cat /run/nettap-auth/daemon-token 2>/dev/null || echo "")
if [ -n "$TOKEN" ]; then
    echo "   ✓ Token read"
else
    echo "   ✗ Could not read /run/nettap-auth/daemon-token (API checks below will fail)"
fi
echo ""

echo "→ Step 15: Wizard bridge check is read-only (CR-004)..."
MGMT_NIC=$(ip -4 route show default 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "dev") print $(i + 1)}' | head -1)
BR_BEFORE=$(ip -br link show type bridge 2>/dev/null | awk '{print $1}' | sort | tr '\n' ' ')
if [ -n "$MGMT_NIC" ]; then
    RESP=$(sudo docker exec "$DAEMON" curl -s --max-time 20 -o - -w ' HTTP %{http_code}' \
        -H "X-NetTap-Daemon-Token: $TOKEN" -H 'Content-Type: application/json' \
        -d "{\"wan_interface\":\"$MGMT_NIC\",\"lan_interface\":\"nettapnone0\"}" \
        http://localhost:8880/api/setup/bridge/preview 2>/dev/null || echo "")
    echo "   preview with the management NIC ($MGMT_NIC): ${RESP:-<no response>}"
    expect "refused" "${RESP##* }" "400"
else
    echo "   ! no default route found — skipped"
fi
BR_AFTER=$(ip -br link show type bridge 2>/dev/null | awk '{print $1}' | sort | tr '\n' ' ')
if [ "$BR_BEFORE" = "$BR_AFTER" ]; then
    echo "   ✓ bridges unchanged: ${BR_AFTER:-none}"
else
    echo "   ✗ bridges changed: before=[$BR_BEFORE] after=[$BR_AFTER]"
fi
echo ""

echo "→ Step 16: Retention policy manages the real indices (CR-017, CR-038)..."
# The daemon applies and attaches nettap-hot-policy on startup; give it a minute.
ISM_LINE=""
for i in $(seq 1 12); do
    ISM_LINE=$(sudo docker exec nettap-opensearch curl -s --max-time 20 --config "$CURLRC" --cacert "$OS_CA" --insecure \
        'https://localhost:9200/_plugins/_ism/explain/arkime_sessions3-*,malcolm_beats_*' 2>/dev/null \
        | sudo docker exec -i "$DAEMON" python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("no-json 0 0")
    sys.exit(0)
idx = {k: v for k, v in d.items() if isinstance(v, dict)}
ok = [k for k, v in idx.items() if "nettap-hot-policy" in (v.get("policy_id"), v.get("index.plugins.index_state_management.policy_id"))]
print("ok %d %d" % (len(ok), len(idx)))
' 2>/dev/null || echo "error 0 0")
    read -r ISM_STATE ISM_OK ISM_TOTAL <<< "${ISM_LINE:-error 0 0}"
    [ "$ISM_STATE" = "ok" ] && [ "$ISM_OK" = "$ISM_TOTAL" ] && [ "$ISM_TOTAL" != "0" ] && break
    sleep 5
done
read -r ISM_STATE ISM_OK ISM_TOTAL <<< "${ISM_LINE:-error 0 0}"
if [ "$ISM_STATE" = "ok" ] && [ "$ISM_OK" = "$ISM_TOTAL" ] && [ "$ISM_TOTAL" != "0" ]; then
    echo "   ✓ nettap-hot-policy manages all $ISM_TOTAL network indices"
else
    echo "   ✗ nettap-hot-policy manages $ISM_OK of $ISM_TOTAL network indices ($ISM_STATE)"
    echo "     check: sudo docker logs $DAEMON 2>&1 | grep -i ism | tail -20"
fi
echo ""

echo "→ Step 17: PCAP has one writer and the daemon can delete it (CR-001, CR-018, CR-020, MS-002)..."
WRITE_METHOD=$(sudo docker exec nettap-arkime-live grep -h '^pcapWriteMethod' /opt/arkime/etc/config.ini 2>/dev/null | tail -1)
expect "Arkime pcapWriteMethod" "${WRITE_METHOD#pcapWriteMethod=}" "null"
CAPS=$(sudo docker inspect --format '{{.HostConfig.CapAdd}}' "$DAEMON" 2>/dev/null || echo "")
case "$CAPS" in
    *DAC_OVERRIDE*) echo "   ✓ daemon has DAC_OVERRIDE" ;;
    *) echo "   ✗ daemon is missing DAC_OVERRIDE: $CAPS" ;;
esac
if sudo docker exec "$DAEMON" sh -c 'f=/opt/nettap/pcap/.nettap-write-test; touch "$f" && rm "$f"' 2>/dev/null; then
    echo "   ✓ daemon can write and delete in /opt/nettap/pcap"
else
    echo "   ✗ daemon cannot write in /opt/nettap/pcap (PCAP retention will fail)"
fi
PCAP_ALL=$(sudo docker exec "$DAEMON" find /opt/nettap/pcap -type f -name '*.pcap' 2>/dev/null | wc -l)
PCAP_ARKIME=$(sudo docker exec "$DAEMON" find /opt/nettap/pcap/arkime-live -type f -name '*.pcap' 2>/dev/null | wc -l)
PCAP_SIZE=$(sudo docker exec "$DAEMON" du -sh /opt/nettap/pcap 2>/dev/null | cut -f1)
echo "   PCAP on disk: $PCAP_ALL files, $PCAP_ARKIME of them old Arkime files in arkime-live/, ${PCAP_SIZE:-?} in total"
echo "   (PCAP older than cold_days, Arkime's included, is deleted on the next storage cycle)"
if sudo docker exec "$DAEMON" test -e /opt/nettap/data/storage-stopped-capture 2>/dev/null; then
    echo "   ! the storage manager has stopped capture for low disk space (flag set)"
else
    echo "   ✓ capture not stopped by the storage manager"
fi
echo ""

echo "→ Step 18: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" \
    | grep -E "nettap-(web|storage-daemon|nginx|grafana|opensearch|arkime-live|pcap-capture|logstash|filebeat)"
echo ""

echo "=== Deploy Complete ==="
echo "Log in to NetTap, then open /dashboards/ and /grafana/ from the dashboard."
