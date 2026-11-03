#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 19 (backup guide check, gateway port node) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #72 docs/admin-guide/backup-restore.md: runs the guide's own commands for the config,
#       records and logins archives, and an OpenSearch snapshot plus a restore under a new name
#   #75 Infrastructure: DHCP gateway mode shows its gateway port, not br0 (web rebuild; this
#       box is in mirror mode, so the page must still show its mirror port)
#
# Everything the check creates is removed at the end: the archives, the snapshot, the restored
# copy of nettap-devices and the snapshot repository. No live index is closed or overwritten.
# Only the web restarts. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch19.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
NETTAP_DIR="$REPO_DIR"
CHECK_DIR="/var/backups/nettap-doc-check"
SNAP="doc-check-$(date +%Y%m%d%H%M%S)"
REPO_FILES="/var/lib/docker/volumes/docker_opensearch-backup/_data/nettap"

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

# The guide's helper, word for word
osapi() { sudo docker exec nettap-opensearch curl -sk --config /var/local/curlrc/.opensearch.primary.curlrc "$@"; }

echo "=== Deploy: dashboard data accuracy, batch 19 (backup guide check, gateway port node) ==="
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

echo "→ Step 2: Build and restart the web..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
STATUS="unknown"
for i in $(seq 1 36); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    [ $((i % 6)) -eq 0 ] && echo "   waiting... nettap-web=$STATUS ($i/36)"
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$STATUS"
MODE=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880/api/capture/mode', headers={'X-NetTap-Daemon-Token': token})
print(json.load(urllib.request.urlopen(req, timeout=10))['mode'])" 2>&1)
if [ "$MODE" = "mirror" ]; then rc=0; else rc=1; fi
check "#75 this box reports mirror mode (its first node stays Mirror Port)" "$rc" "${MODE:-no answer}"
echo ""

echo "→ Step 3: The guide's configuration and records archives..."
sudo mkdir -p "$CHECK_DIR"
sudo tar czf "$CHECK_DIR/config-$(date +%Y%m%d).tar.gz" -C "$NETTAP_DIR" \
  .env docker/.env docker/auth docker/curlrc docker/certs docker/ssl
sudo chmod 600 "$CHECK_DIR"/config-*.tar.gz
CONFIG=$(sudo tar tzf "$CHECK_DIR/config-$(date +%Y%m%d).tar.gz" 2>&1)
MISSING=""
for want in .env docker/.env docker/auth/htpasswd docker/curlrc/.opensearch.primary.curlrc docker/certs/ca.crt docker/ssl/nettap.key; do
    echo "$CONFIG" | grep -qx "$want" || MISSING="$MISSING $want"
done
if [ -z "$MISSING" ]; then rc=0; else rc=1; fi
check "#72 config archive has docker/.env, logins, certs and TLS keys" "$rc" "$(echo "$CONFIG" | grep -c .) entries${MISSING:+; missing:$MISSING}"
MODE_BITS=$(sudo stat -c '%a' "$CHECK_DIR/config-$(date +%Y%m%d).tar.gz")
if [ "$MODE_BITS" = "600" ]; then rc=0; else rc=1; fi
check "#72 config archive is private" "$rc" "mode $MODE_BITS"
sudo sh -c "docker exec nettap-storage-daemon tar czf - -C /opt/nettap/data . > $CHECK_DIR/appdata-\$(date +%Y%m%d).tar.gz"
sudo sh -c "docker exec nettap-web tar czf - -C /var/lib/nettap-web . > $CHECK_DIR/webdata-\$(date +%Y%m%d).tar.gz"
APP=$(sudo tar tzf "$CHECK_DIR/appdata-$(date +%Y%m%d).tar.gz" 2>&1 | tr '\n' ' ')
WEB=$(sudo tar tzf "$CHECK_DIR/webdata-$(date +%Y%m%d).tar.gz" 2>&1 | tr '\n' ' ')
case "$APP" in *retention.json*) rc=0 ;; *) rc=1 ;; esac
check "#72 records archive comes from the daemon's volume" "$rc" "${APP:-empty}"
case "$WEB" in *users.json*) rc=0 ;; *) rc=1 ;; esac
check "#72 logins archive has the web accounts" "$rc" "$(echo "$WEB" | grep -o 'users.json\|jwt-secret.txt' | tr '\n' ' ')"
echo ""

echo "→ Step 4: The guide's OpenSearch snapshot..."
CODE=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost:9200/)
if [ "$CODE" = "401" ]; then rc=0; else rc=1; fi
check "#72 a plain host curl is refused (why the guide uses osapi)" "$rc" "HTTP $CODE"
REG=$(osapi -X PUT "https://localhost:9200/_snapshot/nettap_backup" \
  -H "Content-Type: application/json" \
  -d '{"type": "fs", "settings": {"location": "/opt/opensearch/backup/nettap", "compress": true}}')
case "$REG" in *'"acknowledged":true'*) rc=0 ;; *) rc=1 ;; esac
check "#72 snapshot repository registers" "$rc" "$REG"
SNAP_OUT=$(osapi -X PUT "https://localhost:9200/_snapshot/nettap_backup/$SNAP?wait_for_completion=true" \
  -H "Content-Type: application/json" \
  -d '{"indices": "arkime_sessions3-*,malcolm_beats_*,nettap-*", "ignore_unavailable": true, "include_global_state": false}')
STATE=$(echo "$SNAP_OUT" | grep -o '"state":"[A-Z_]*"' | head -1)
SHARDS=$(echo "$SNAP_OUT" | grep -o '"shards":{[^}]*}')
case "$STATE$SHARDS" in *SUCCESS*'"failed":0'*) rc=0 ;; *) rc=1 ;; esac
check "#72 snapshot succeeds" "$rc" "${STATE:-no state} ${SHARDS:-$SNAP_OUT}"
TODAY_INDEX="arkime_sessions3-$(date -u +%y%m%d)"
INDICES=$(echo "$SNAP_OUT" | grep -o '"indices":\[[^]]*\]')
case "$INDICES" in *"$TODAY_INDEX"*nettap-devices*|*nettap-devices*"$TODAY_INDEX"*) rc=0 ;; *) rc=1 ;; esac
check "#72 snapshot holds today's records and the device registry" "$rc" "${INDICES:-none}"
LISTED=$(osapi "https://localhost:9200/_cat/snapshots/nettap_backup?h=id,status" | grep "$SNAP")
case "$LISTED" in *SUCCESS*) rc=0 ;; *) rc=1 ;; esac
check "#72 the guide's list command shows it" "$rc" "${LISTED:-not listed}"
if sudo test -d "$REPO_FILES"; then rc=0; else rc=1; fi
check "#72 the files are where the guide says" "$rc" "$REPO_FILES ($(sudo du -sh "$REPO_FILES" 2>/dev/null | cut -f1))"
echo ""

echo "→ Step 5: The guide's restore under a new name..."
# shellcheck disable=SC2016  # $1 is OpenSearch's rename group, not a shell variable
RESTORE=$(osapi -X POST "https://localhost:9200/_snapshot/nettap_backup/$SNAP/_restore?wait_for_completion=true" \
  -H "Content-Type: application/json" \
  -d '{"indices": "nettap-devices", "rename_pattern": "(.+)", "rename_replacement": "restored-$1", "include_global_state": false}')
case "$RESTORE" in *'"failed":0'*) rc=0 ;; *) rc=1 ;; esac
check "#72 restore under a new name finishes" "$rc" "$(echo "$RESTORE" | grep -o '"shards":{[^}]*}' || echo "$RESTORE")"
COUNTS=$(osapi "https://localhost:9200/_cat/indices/nettap-devices,restored-nettap-devices?h=index,docs.count" | sort)
LIVE=$(echo "$COUNTS" | awk '$1 == "nettap-devices" {print $2}')
RESTORED=$(echo "$COUNTS" | awk '$1 == "restored-nettap-devices" {print $2}')
if [ -n "$RESTORED" ] && [ "$RESTORED" -gt 0 ] && [ "$RESTORED" = "$LIVE" ]; then rc=0; else rc=1; fi
check "#72 restored copy has the registry's devices" "$rc" "live ${LIVE:-?}, restored ${RESTORED:-none}"
echo ""

echo "→ Step 6: Remove everything this check created..."
DEL_IDX=$(osapi -X DELETE "https://localhost:9200/restored-nettap-devices")
DEL_SNAP=$(osapi -X DELETE "https://localhost:9200/_snapshot/nettap_backup/$SNAP")
DEL_REPO=$(osapi -X DELETE "https://localhost:9200/_snapshot/nettap_backup")
sudo rm -rf "$REPO_FILES" "$CHECK_DIR"
case "$DEL_IDX$DEL_SNAP$DEL_REPO" in *'"acknowledged":true'*'"acknowledged":true'*'"acknowledged":true'*) rc=0 ;; *) rc=1 ;; esac
check "check artifacts removed" "$rc" "restored index, snapshot, repository, archives"
LEFT=$(osapi "https://localhost:9200/_cat/indices?h=index" | grep -c '^restored-')
REPOS=$(osapi "https://localhost:9200/_snapshot" | grep -o '"[a-z_]*":{"type"' | cut -d'"' -f2 | tr '\n' ' ')
if [ "$LEFT" -eq 0 ]; then rc=0; else rc=1; fi
check "no restored-* index left; repositories as before" "$rc" "$LEFT restored-*, repositories: ${REPOS:-none}"
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|opensearch"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 19 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
