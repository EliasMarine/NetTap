#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 10 (Suricata rules) and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #57 two decoder rules that fire on ordinary switch traffic are disabled:
#       2200121 "Ethertype unknown" (STP/LLDP) and 2231001 "QUIC error on data"
#   #58 Suricata Rules page shows the rules Suricata really runs (/api/suricata/rules/live)
#
# suricata-live restarts once (~1-2 min without IDS alerts while rules load), and the
# "Update Rules Now" check runs one rule update (the same download the nightly job does).
# Zeek and netsniff keep capturing.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch10.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
RULES="/var/lib/suricata/rules/suricata.rules"
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

api() {  # api <METHOD> <path> <timeout s> -> "<http status> <json>"
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.error, urllib.request
method, path, timeout = sys.argv[1], sys.argv[2], int(sys.argv[3])
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + path, method=method, data=b'' if method == 'POST' else None,
    headers={'X-NetTap-Daemon-Token': token})
try:
    resp = urllib.request.urlopen(req, timeout=timeout)
    print(resp.status, json.dumps(json.load(resp)))
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode()[:300])
except Exception as e:
    print('ERR', e)
" "$1" "$2" "$3"
}

field() {  # field '<json>' <key>
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys
try:
    print(json.loads(sys.argv[1])[sys.argv[2]])
except Exception:
    print('')
" "$1" "$2"
}

# "disabled" when the rule's line in suricata.rules is commented out, "enabled" if not, "absent"
sid_state() {
    sudo docker exec nettap-suricata-live sh -c '
L=$(grep -E "sid: ?$1;" "$2" | head -1)
case "$L" in "") echo absent ;; "#"*) echo disabled ;; *) echo enabled ;; esac' _ "$1" "$RULES" 2>/dev/null || echo unknown
}

rules_count() { sudo docker exec nettap-suricata-live sh -c 'grep -cE "^(alert|drop|pass|reject) " "$1"' _ "$RULES" 2>/dev/null; }
rules_mtime() { sudo docker exec nettap-suricata-live stat -c %Y "$RULES" 2>/dev/null; }

echo "=== Deploy: dashboard data accuracy, batch 10 (Suricata rules) ==="
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

echo "→ Step 3: Recreate the daemon, web and suricata-live..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web suricata-live
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
STATE=unknown
for i in $(seq 1 36); do  # the entrypoint regenerates the rules with the disabled SIDs at start
    STATE=$(sid_state 2200121)
    [ "$STATE" = "disabled" ] && break
    [ $((i % 6)) -eq 0 ] && echo "   waiting for Suricata's rules to regenerate... ($i/36)"
    sleep 5
done
echo ""

echo "→ Step 4: Check the fixes..."
if [ "$STATE" = "disabled" ]; then rc=0; else rc=1; fi
check "#57 sid 2200121 'Ethertype unknown' disabled" "$rc" "$STATE"
STATE=$(sid_state 2231001)
if [ "$STATE" = "disabled" ]; then rc=0; else rc=1; fi
check "#57 sid 2231001 'QUIC error on data' disabled" "$rc" "$STATE"

read -r CODE LIVE <<<"$(api GET /api/suricata/rules/live 60)"
ENABLED=$(field "$LIVE" enabled_rules)
DIRECT=$(rules_count)
SCHEDULE=$(field "$LIVE" schedule)
NSRC=$(sudo docker exec nettap-storage-daemon python3 -c "import json,sys; print(len(json.loads(sys.argv[1]).get('sources', [])))" "$LIVE" 2>/dev/null)
if [ "$CODE" = "200" ] && [ -n "$ENABLED" ] && [ "$ENABLED" = "$DIRECT" ] && [ "${ENABLED:-0}" -gt 1000 ] && [ "${NSRC:-0}" -ge 1 ]; then rc=0; else rc=1; fi
check "#58 rules page figures = what Suricata runs" "$rc" "HTTP $CODE: enabled=${ENABLED:-?} (rules file ${DIRECT:-?}), sources=${NSRC:-?}, schedule='${SCHEDULE:-?}'"

BEFORE=$(rules_mtime)
echo "   running Update Rules Now (downloads the rule feeds, up to ~5 min)..."
# The reply carries suricata-update's whole output: too big to pass back as an argument,
# so read just the status and the success flag inside the daemon container.
read -r CODE OK <<<"$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.error, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880/api/suricata/rules/update', method='POST', data=b'',
    headers={'X-NetTap-Daemon-Token': token})
try:
    resp = urllib.request.urlopen(req, timeout=420)
    print(resp.status, json.load(resp).get('success'))
except urllib.error.HTTPError as e:
    print(e.code, 'False')
except Exception as e:
    print('ERR', type(e).__name__)
")"
AFTER=$(rules_mtime)
if [ "$CODE" = "200" ] && [ "$OK" = "True" ] && [ -n "$AFTER" ] && [ "${AFTER}" != "${BEFORE:-x}" ]; then rc=0; else rc=1; fi
check "#58 Update Rules Now refreshes the rules" "$rc" "HTTP $CODE success=${OK:-?}, rules file $(date -u -d "@${BEFORE:-0}" +%T) → $(date -u -d "@${AFTER:-0}" +%T)"
S1=$(sid_state 2200121)
S2=$(sid_state 2231001)
if [ "$S1" = "disabled" ] && [ "$S2" = "disabled" ]; then rc=0; else rc=1; fi
check "#57 the two SIDs stay disabled after a rule update" "$rc" "2200121=$S1 2231001=$S2"

SINCE=$(date -u -d '-3 minutes' +%Y-%m-%dT%H:%M:%S)
ALERTS=$(sudo docker exec nettap-suricata-live sh -c 'F=$(ls -t /var/log/suricata/live/eve*.json | head -1); tail -c 8000000 "$F" | grep "\"event_type\":\"alert\"" | awk -F"\"" -v t="$1" "\$4 >= t" | wc -l' _ "$SINCE" 2>/dev/null)
if [ "${ALERTS:-0}" -gt 0 ]; then rc=0; else rc=1; fi
check "Suricata still raising alerts" "$rc" "${ALERTS:-0} alerts in the last 3 minutes"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|storage-daemon|suricata-live|zeek-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 10 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
