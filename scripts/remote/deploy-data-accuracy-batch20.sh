#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 20 (LAN subnet detection) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #47 LAN auto-detection kept a subnet only at 10% of the busiest one, so the IoT VLAN
#       flipped in and out between restarts and a one-device VLAN never counted; every page
#       that filters to "LAN devices" moved with it. Now: 1% of all private-source traffic.
#
# The daemon is restarted twice; both starts must detect the same subnets, and the device
# list must only hold addresses inside them. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch20.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
EXPECTED="192.168.1.0/24, 10.10.0.0/24, 192.168.40.0/24"  # the owner's subnets (#47)

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

detected() {  # the subnets the running daemon detected at its start
    sudo docker logs nettap-storage-daemon 2>&1 | grep -o 'LAN detection: found [0-9]* subnet(s): .*' | tail -1 | sed 's/.*: //'
}

restart_daemon() {
    "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
    local status="unknown"
    for i in $(seq 1 36); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && break
        [ $((i % 6)) -eq 0 ] && echo "   waiting... nettap-storage-daemon=$status ($i/36)"
        sleep 5
    done
    if [ "$status" = "healthy" ]; then rc=0; else rc=1; fi
    check "nettap-storage-daemon health" "$rc" "$status"
}

devices_by_subnet() {  # "<count> <subnet>" lines for /api/devices over 24 h
    sudo docker exec nettap-storage-daemon python3 -c "
import collections, json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880/api/devices?limit=500', headers={'X-NetTap-Daemon-Token': token})
ips = [d['ip'] for d in json.load(urllib.request.urlopen(req, timeout=120))['devices']]
for subnet, n in collections.Counter('.'.join(ip.split('.')[:3]) + '.0/24' for ip in ips).most_common():
    print(n, subnet)
" 2>&1
}

echo "=== Deploy: dashboard data accuracy, batch 20 (LAN subnet detection) ==="
echo ""

echo "→ Step 1: What the running daemon uses..."
OVERRIDE=$(sudo docker exec nettap-storage-daemon printenv LAN_SUBNETS 2>/dev/null || true)
BEFORE=$(detected)
BEFORE_DEV=$(devices_by_subnet)
echo "   LAN_SUBNETS override: ${OVERRIDE:-not set}"
echo "   detected at its start: ${BEFORE:-none logged}"
echo "   devices: $(echo "$BEFORE_DEV" | awk '{s += $1} END {print s+0}') ($(echo "$BEFORE_DEV" | tr '\n' ' '))"
echo ""

echo "→ Step 2: Pull latest code..."
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

echo "→ Step 3: Build the daemon image..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Image built"
echo ""

echo "→ Step 4: Start it twice..."
restart_daemon
FIRST=$(detected)
restart_daemon
SECOND=$(detected)
echo ""

echo "→ Step 5: Checks..."
if [ -z "$OVERRIDE" ]; then rc=0; else rc=1; fi
check "#47 detection is what's tested (no LAN_SUBNETS override)" "$rc" "${OVERRIDE:-not set}"
if [ "$FIRST" = "$EXPECTED" ]; then rc=0; else rc=1; fi
check "#47 all three of the owner's subnets detected" "$rc" "${BEFORE:-?} → ${FIRST:-none logged}"
if [ -n "$FIRST" ] && [ "$FIRST" = "$SECOND" ]; then rc=0; else rc=1; fi
check "#47 the same subnets after another restart" "$rc" "${SECOND:-none logged}"
AFTER_DEV=$(devices_by_subnet)
OUTSIDE=$(echo "$AFTER_DEV" | awk -v ok="$EXPECTED" 'index(ok, $2) == 0 {print $2}' | tr '\n' ' ')
if [ -z "$OUTSIDE" ]; then rc=0; else rc=1; fi
check "#47 every listed device is inside a detected subnet" "$rc" "$(echo "$AFTER_DEV" | tr '\n' ' ')${OUTSIDE:+; outside: $OUTSIDE}"
VLAN40=$(echo "$AFTER_DEV" | awk '$2 == "192.168.40.0/24" {print $1}')
if [ "${VLAN40:-0}" -gt 0 ]; then rc=0; else rc=1; fi
check "#47 the 192.168.40.0/24 device is listed now" "$rc" "${VLAN40:-0} device(s)"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 20 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
