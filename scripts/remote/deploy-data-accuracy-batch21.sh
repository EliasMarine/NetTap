#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 21 (8-byte DHCP MAC phantom device) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #76 Home / registry: Zeek printed the UniFi U7 Pro's DHCP chaddr as 8 bytes on VLAN 40, so
#       the registry held the AP twice (the real one and a phantom "U7Pro" counted as Unknown)
#
# The daemon's startup refresh folds the long entry into the real device (IPs and names kept).
# Only the daemon restarts. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch21.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

registry() {  # "<mac>\t<ips>\t<category>" per registry entry, then "DEVICES <n>" for /api/devices
    sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
get = lambda path: json.load(urllib.request.urlopen(urllib.request.Request('http://localhost:8880' + path, headers={'X-NetTap-Daemon-Token': token}), timeout=120))
for d in sorted(get('/api/devices/registry?limit=500')['devices'], key=lambda d: d['mac']):
    print('\t'.join([d['mac'], ','.join(d.get('ips') or []), d.get('category') or '-']))
print('DEVICES', len(get('/api/devices?limit=500')['devices']))
" 2>&1
}

echo "=== Deploy: dashboard data accuracy, batch 21 (8-byte DHCP MAC) ==="
echo ""

echo "→ Step 1: The registry before..."
BEFORE=$(registry)
LONG_BEFORE=$(echo "$BEFORE" | grep -P '\t' | awk -F'\t' 'split($1, o, ":") > 6 {print $1}' | tr '\n' ' ')
echo "   $(echo "$BEFORE" | grep -cP '\t') entries, $(echo "$BEFORE" | awk '$1 == "DEVICES" {print $2}') devices listed; longer than 6 octets: ${LONG_BEFORE:-none}"
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

echo "→ Step 3: Build and recreate the daemon..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
STATUS="unknown"
for _ in $(seq 1 36); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-storage-daemon health" "$rc" "$STATUS"
for _ in $(seq 1 36); do
    sudo docker logs --since 10m nettap-storage-daemon 2>&1 | grep -q "Device registry refresh:" && break
    sleep 5
done
sudo docker logs --since 10m nettap-storage-daemon 2>&1 | grep -o "Merged registry entry .*" | sed 's/^/   /'
echo ""

echo "→ Step 4: Checks..."
AFTER=$(registry)
LONG_AFTER=$(echo "$AFTER" | grep -P '\t' | awk -F'\t' 'split($1, o, ":") > 6 {print $1}' | tr '\n' ' ')
if [ -z "$LONG_AFTER" ]; then rc=0; else rc=1; fi
check "#76 no registry entry is keyed by more than 6 octets" "$rc" "before: ${LONG_BEFORE:-none}; after: ${LONG_AFTER:-none}"
AP=$(echo "$AFTER" | awk -F'\t' '$1 == "F4:E2:C6:FF:98:21" {print $2 " " $3}')
case "$AP" in *192.168.40.198*) rc=0 ;; *) rc=1 ;; esac
check "#76 the U7 Pro is one device holding both IPs" "$rc" "F4:E2:C6:FF:98:21 → ${AP:-missing}"
NB=$(echo "$BEFORE" | grep -cP '\t'); NA=$(echo "$AFTER" | grep -cP '\t')
EXPECT=$((NB - $(echo "$LONG_BEFORE" | wc -w)))
if [ "$NA" -ge "$EXPECT" ]; then rc=0; else rc=1; fi
check "#76 only the long entries left the registry" "$rc" "$NB → $NA entries (expected ≥ $EXPECT)"
DB=$(echo "$BEFORE" | awk '$1 == "DEVICES" {print $2}'); DA=$(echo "$AFTER" | awk '$1 == "DEVICES" {print $2}')
if [ -n "$DA" ] && [ "$DA" = "$DB" ]; then rc=0; else rc=1; fi
check "#76 the device list is unchanged" "$rc" "${DB:-?} → ${DA:-?} devices"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 21 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
