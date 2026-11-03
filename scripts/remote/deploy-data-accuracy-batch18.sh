#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 18 (device registry refresh speed, console categories) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #74 device registry: each device write waited ~1 s for an index refresh, so one registry
#       refresh took ~1 min; writes no longer wait and each listing pass refreshes once
#   #69 Devices page: Xbox / PlayStation / Roku / Chromecast hostnames are Media even when the
#       OS hint says Linux or Windows
#
# The registry is saved before the deploy and compared after the new daemon's startup refresh:
# no device may disappear or lose its vendor, and a category may only move off "unknown".
# Only the daemon restarts. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch18.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

registry() {  # one tab-separated line per registered device: mac, vendor, category
    sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880/api/devices/registry?limit=500', headers={'X-NetTap-Daemon-Token': token})
for d in sorted(json.load(urllib.request.urlopen(req, timeout=60))['devices'], key=lambda d: d['mac']):
    print('\t'.join(str(d.get(k) or '-') for k in ('mac', 'manufacturer', 'category')))
" 2>&1
}

old_refresh_seconds() {  # startup refresh time of the running daemon, from its log timestamps
    sudo docker logs --timestamps nettap-storage-daemon 2>&1 | awk '
        /Device registry loop started/ {start = $1; next}
        start && /Device registry refresh:/ {print start, $1; exit}' | while read -r a b; do
        echo $(( $(date -d "$b" +%s) - $(date -d "$a" +%s) ))
    done
}

echo "=== Deploy: dashboard data accuracy, batch 18 (registry refresh speed, console categories) ==="
echo ""

echo "→ Step 1: Save the registry and the old refresh time..."
BEFORE=$(registry | grep -P '\t' || true)
OLD_S=$(old_refresh_seconds)
echo "   ✓ $(echo "$BEFORE" | grep -c .) registered devices; the running daemon's startup refresh took ${OLD_S:-?} s"
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

echo "→ Step 4: Recreate the daemon..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
STATUS="unknown"
for i in $(seq 1 36); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    [ $((i % 6)) -eq 0 ] && echo "   waiting... nettap-storage-daemon=$STATUS ($i/36)"
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-storage-daemon health" "$rc" "$STATUS"
LINE=""
for i in $(seq 1 36); do
    LINE=$(sudo docker logs --since 10m nettap-storage-daemon 2>&1 | grep -m1 "Device registry refresh:")
    [ -n "$LINE" ] && break
    sleep 5
done
echo ""

echo "→ Step 5: Checks..."
NEW_S=$(echo "$LINE" | grep -o 'in [0-9.]* s' | grep -o '[0-9.]*')
if [ -n "$NEW_S" ] && [ "${NEW_S%.*}" -lt 15 ]; then rc=0; else rc=1; fi
check "#74 the registry refresh takes seconds, not a minute" "$rc" "${OLD_S:-?} s → ${NEW_S:-no refresh logged} s ($(echo "$LINE" | grep -o '[0-9]* LAN devices'))"
AFTER=$(registry | grep -P '\t' || true)
GONE=$(comm -23 <(echo "$BEFORE" | cut -f1) <(echo "$AFTER" | cut -f1) | grep . || true)
if [ -z "$GONE" ]; then rc=0; else rc=1; fi
check "#74 no registered device disappeared" "$rc" "$(echo "$BEFORE" | grep -c .) before, $(echo "$AFTER" | grep -c .) after${GONE:+; gone: $GONE}"
LOST=$(awk -F'\t' 'NR == FNR {v[$1] = $2; next} ($1 in v) && v[$1] != "-" && $2 == "-" {print $1}' <(echo "$BEFORE") <(echo "$AFTER"))
if [ -z "$LOST" ]; then rc=0; else rc=1; fi
check "#74 no device lost its vendor" "$rc" "$(echo "$LOST" | grep -c .) lost${LOST:+: $LOST}"
MOVED=$(awk -F'\t' 'NR == FNR {c[$1] = $3; next} ($1 in c) && c[$1] != $3 {print $1 ": " c[$1] " → " $3}' <(echo "$BEFORE") <(echo "$AFTER"))
BAD=$(echo "$MOVED" | grep . | grep -v -c ': unknown → ')
[ -n "$MOVED" ] && while IFS= read -r line; do echo "   category  $line"; done <<<"$MOVED"
if [ "$BAD" -eq 0 ]; then rc=0; else rc=1; fi
check "#74 categories only fill in Unknown" "$rc" "$(echo "$MOVED" | grep -c .) changed, $BAD not from unknown"
CATS=$(sudo docker exec nettap-storage-daemon python3 -c "
from api.devices import _device_category as c
print(c('Linux', 'Living-Room-Chromecast', 'Google, Inc.'), c('Windows 10/11', 'XboxOne', None), c('Linux', 'nas01', None))
" 2>&1)
if [ "$CATS" = "media media computer" ]; then rc=0; else rc=1; fi
check "#69 console and streamer hostnames are Media (in the running image)" "$rc" "Chromecast, Xbox, nas01 → ${CATS:-no answer}"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 18 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
