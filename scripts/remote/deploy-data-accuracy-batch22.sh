#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 22 (secret file permissions) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #77 docker/curlrc/.opensearch.primary.curlrc (the OpenSearch login every Malcolm service
#       uses) was root:root 644, readable by every local account; docker/auth/htpasswd and the
#       repo-root .env (SMTP_PASS) the same
#
# The login file goes to the compose PUID with mode 600 (Malcolm drops to PUID before reading
# it); htpasswd (no container mounts it) and the root .env (only the installer reads it) go to
# root 600. Every non-root user in every container that mounts curlrc must still read it; then
# logstash, filebeat, dashboards-helper, the Malcolm api and the daemon restart and must still
# log in. OpenSearch itself is not restarted (its user is covered by the read check).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch22.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
CURLRC="$REPO_DIR/docker/curlrc/.opensearch.primary.curlrc"
CONSUMERS="nettap-opensearch nettap-dashboards-helper nettap-dashboards nettap-logstash nettap-filebeat nettap-api nettap-storage-daemon"

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

recent_docs() {  # documents indexed in the last 2 minutes
    sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        "https://localhost:9200/arkime_sessions3-*/_count?q=@timestamp:%3Enow-2m" | grep -o '"count":[0-9]*' | cut -d: -f2
}

echo "=== Deploy: dashboard data accuracy, batch 22 (secret file permissions) ==="
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

echo "→ Step 2: Lock the files..."
PUID=$(sudo grep -oE '^PUID=[0-9]+' docker/.env | cut -d= -f2)
PGID=$(sudo grep -oE '^PGID=[0-9]+' docker/.env | cut -d= -f2)
if [ -z "$PUID" ] || [ -z "$PGID" ] || [ "$PUID" = "0" ]; then
    echo "   ✗ PUID/PGID not found in docker/.env (got '${PUID}:${PGID}') — nothing was changed"
    exit 1
fi
echo "   before: $(sudo stat -c '%U:%G %a %n' "$CURLRC" docker/auth/htpasswd .env | tr '\n' ';')"
sudo chown "$PUID:$PGID" "$CURLRC" && sudo chmod 600 "$CURLRC"
sudo chmod 600 docker/auth/htpasswd .env
echo "   after:  $(sudo stat -c '%U:%G %a %n' "$CURLRC" docker/auth/htpasswd .env | tr '\n' ';')"
MODES=$(sudo stat -c '%u:%g %a' "$CURLRC")
if [ "$MODES" = "$PUID:$PGID 600" ]; then rc=0; else rc=1; fi
check "#77 OpenSearch login file is PUID-owned, mode 600" "$rc" "$MODES (PUID $PUID)"
OTHERS=$(sudo stat -c '%a' docker/auth/htpasswd .env | tr '\n' ' ')
if [ "$OTHERS" = "600 600 " ]; then rc=0; else rc=1; fi
check "#77 htpasswd and the root .env are private" "$rc" "$OTHERS"
if sudo -u nobody test -r "$CURLRC" 2>/dev/null; then rc=1; else rc=0; fi
check "#77 another local account can no longer read the login" "$rc" "nobody: $( [ "$rc" -eq 0 ] && echo denied || echo READABLE)"
echo ""

echo "→ Step 3: Every container user can still read it..."
for c in $CONSUMERS; do
    # docker top lists only the container's processes (/proc would show the host's with pid: host)
    UIDS=$(sudo docker top "$c" -eo uid 2>/dev/null | sed 1d | sort -un | tr '\n' ' ')
    BAD=""
    for u in $UIDS; do
        sudo docker exec -u "$u" "$c" test -r /var/local/curlrc/.opensearch.primary.curlrc || BAD="$BAD $u"
    done
    if [ -z "$BAD" ]; then rc=0; else rc=1; fi
    check "#77 $c reads the login" "$rc" "uids ${UIDS:-none}${BAD:+; cannot read as:$BAD}"
done
echo ""

echo "→ Step 4: Restart the services that read it at start..."
"${COMPOSE[@]}" restart logstash filebeat dashboards-helper api
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
for i in $(seq 1 36); do
    D=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null)
    L=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-logstash 2>/dev/null)
    [ "$D" = "healthy" ] && [ "$L" = "healthy" ] && break
    [ $((i % 6)) -eq 0 ] && echo "   waiting... daemon=$D logstash=$L ($i/36)"
    sleep 5
done
echo "   waiting for indexing to resume (logstash takes ~1 min to start its pipelines)..."
N=0
for _ in $(seq 1 18); do
    N=$(recent_docs)
    [ "${N:-0}" -gt 0 ] && break
    sleep 10
done
echo ""

echo "→ Step 5: They still log in..."
if [ "${N:-0}" -gt 0 ]; then rc=0; else rc=1; fi
check "#77 logstash + filebeat still index (last 2 min)" "$rc" "${N:-0} documents"
# OpenSearch refusals only (supervisord logs an unrelated "without any HTTP authentication" line)
AUTHERR=$(sudo docker logs --since 5m nettap-logstash 2>&1 | grep -c -E "response code '40[13]'|security_exception|401 Unauthorized" || true)
if [ "$AUTHERR" -eq 0 ]; then rc=0; else rc=1; fi
check "#77 logstash has no auth errors since the restart" "$rc" "$AUTHERR lines"
HELPER=$(sudo docker exec nettap-dashboards-helper supervisorctl -c /etc/supervisord.conf status 2>&1 | awk '{print $1 "=" $2}' | tr '\n' ' ')
case "$HELPER" in *FATAL*|*BACKOFF*|"") rc=1 ;; *) rc=0 ;; esac
check "#77 dashboards-helper programs run" "$rc" "$HELPER"
API=$(sudo docker exec nettap-api sh -c 'curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/mapi/ping' 2>/dev/null)
case "$API" in 200) rc=0 ;; *) rc=1 ;; esac
check "#77 Malcolm api answers" "$rc" "/mapi/ping → ${API:-no answer}"
DEV=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880/api/devices?limit=500', headers={'X-NetTap-Daemon-Token': token})
print(len(json.load(urllib.request.urlopen(req, timeout=60))['devices']))" 2>&1)
case "$DEV" in ''|*[!0-9]*) rc=1 ;; 0) rc=1 ;; *) rc=0 ;; esac
check "#77 the daemon still queries OpenSearch" "$rc" "/api/devices → ${DEV} devices"
OSD=$(sudo docker exec nettap-dashboards curl -s --config /var/local/curlrc/.opensearch.primary.curlrc -o /dev/null -w '%{http_code}' http://localhost:5601/dashboards/api/status 2>/dev/null)
case "$OSD" in 200) rc=0 ;; *) rc=1 ;; esac
check "#77 OpenSearch Dashboards accepts the stored login" "$rc" "/dashboards/api/status → ${OSD:-no answer}"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|logstash|filebeat|helper|nettap-api|storage-daemon|dashboards|opensearch"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 22 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
    echo "Undo (restores the old modes): sudo chmod 644 $CURLRC $REPO_DIR/docker/auth/htpasswd $REPO_DIR/.env"
fi
