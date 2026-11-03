#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 24 (NetTap's own address in the figures) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #79 .env.example ships MGMT_IP=192.168.1.100; the daemon trusted it, excluded that placeholder
#       (and saved it into the owner's list), and counted the box's own address everywhere
#
# The saved list is reset only if it holds exactly the placeholder, which the bug wrote at the
# daemon's first start. Only the daemon is rebuilt. Ends with the read-only acceptance check.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch24.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
PLACEHOLDER="192.168.1.100"
SAVED=/opt/nettap/data/excluded_ips.json

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

state() {  # EXCLUDED <list> / DEVICES <n> <ips> / TALKERS <top-20 ips>
    sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
get = lambda p: json.load(urllib.request.urlopen(urllib.request.Request('http://localhost:8880' + p, headers={'X-NetTap-Daemon-Token': token}), timeout=120))
print('EXCLUDED', ','.join(get('/api/settings/excluded-ips')['excluded_ips']) or '-')
ips = [d.get('ip') or '' for d in get('/api/devices?limit=500')['devices']]
print('DEVICES', len(ips), ','.join(ips))
print('TALKERS', ','.join(t['ip'] for t in get('/api/traffic/top-talkers?limit=20')['top_talkers']))
" 2>&1
}
field() { echo "$1" | awk -v k="$2" '$1 == k {print $'"$3"'}'; }
has() { case ",$1," in *",$2,"*) return 0 ;; *) return 1 ;; esac; }

echo "=== Deploy: dashboard data accuracy, batch 24 (NetTap's own address) ==="
echo ""

echo "→ Step 1: Before..."
SELF=$(ip -4 -o addr show "$(ip route show default | awk '{print $5; exit}')" | awk '{print $4}' | cut -d/ -f1 | head -n 1)
BEFORE=$(state)
while IFS= read -r line; do echo "   ${line:0:160}"; done <<<"$BEFORE"
echo "   this box's address (default route): ${SELF:-unknown}"
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

echo "→ Step 3: Remove the saved placeholder (only if it is the whole list)..."
OLD_LIST=$(sudo docker exec nettap-storage-daemon cat "$SAVED" 2>/dev/null | tr -d ' \n')
if [ "$OLD_LIST" = "[\"$PLACEHOLDER\"]" ]; then
    sudo docker exec nettap-storage-daemon sh -c "printf '[]\n' > $SAVED"
    echo "   reset $SAVED from $OLD_LIST to []"
    echo "   undo: echo '[\"$PLACEHOLDER\"]' | sudo docker exec -i nettap-storage-daemon tee $SAVED"
else
    echo "   left as is: ${OLD_LIST:-missing}"
fi
echo ""

echo "→ Step 4: Build and recreate the daemon..."
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
echo ""

echo "→ Step 5: Checks..."
AFTER=$(state)
LOGGED=$(sudo docker logs --since 10m nettap-storage-daemon 2>&1 | grep -o -E "Auto-excluded appliance management IP: [0-9.]+|MGMT_IP [0-9.]+ is not an address of this host" | sort -u | tr '\n' ';')
echo "   daemon log: ${LOGGED:-nothing}"
EX_AFTER=$(field "$AFTER" EXCLUDED 2)
if [ -n "$SELF" ] && has "$EX_AFTER" "$SELF" && ! has "$EX_AFTER" "$PLACEHOLDER"; then rc=0; else rc=1; fi
check "#79 the box's own address is excluded, the placeholder is not" "$rc" "$(field "$BEFORE" EXCLUDED 2) → $EX_AFTER (this box: ${SELF:-?})"
ON_DISK=$(sudo docker exec nettap-storage-daemon cat "$SAVED" 2>/dev/null | tr -d ' \n')
case "$ON_DISK" in *"$SELF"*) rc=1 ;; *) rc=0 ;; esac
check "#79 the detected address is not written into the saved list" "$rc" "$SAVED: ${ON_DISK:-missing}"
DB=$(field "$BEFORE" DEVICES 2); DA=$(field "$AFTER" DEVICES 2)
if ! has "$(field "$AFTER" DEVICES 3)" "$SELF"; then rc=0; else rc=1; fi
check "#79 NetTap is no longer listed as one of the devices" "$rc" "$DB → $DA devices; $SELF listed before: $(has "$(field "$BEFORE" DEVICES 3)" "$SELF" && echo yes || echo no)"
if ! has "$(field "$AFTER" TALKERS 2)" "$SELF"; then rc=0; else rc=1; fi
check "#79 NetTap is not among the top talkers" "$rc" "in the top 20 before: $(has "$(field "$BEFORE" TALKERS 2)" "$SELF" && echo yes || echo no), after: no"
echo ""

echo "→ Step 6: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 24 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
