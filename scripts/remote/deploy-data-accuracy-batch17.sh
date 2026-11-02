#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 17 (OpenSearch Dashboards objects) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #73 dashboards-helper: its programs (idxinit, cron, maps) never started (EACCES on
#       /dev/fd/1), so OpenSearch Dashboards had no index pattern and no dashboards
#
# Only dashboards-helper is recreated. Its jobs create templates, index patterns and
# dashboards; the script checks that no index disappears, the network template still
# targets arkime_sessions3-*, and NetTap's ISM policy is untouched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch17.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

os_get() {  # os_get <path>: GET against OpenSearch from inside its container
    sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc \
        --cacert /usr/share/opensearch/config/certs/ca.crt --insecure "https://localhost:9200$1"
}

os_put() {  # os_put <path> <json>: PUT against OpenSearch, prints the HTTP status
    sudo docker exec nettap-opensearch curl -s -o /dev/null -w '%{http_code}' \
        --config /var/local/curlrc/.opensearch.primary.curlrc \
        --cacert /usr/share/opensearch/config/certs/ca.crt --insecure \
        -X PUT -H 'Content-Type: application/json' "https://localhost:9200$1" -d "$2"
}

saved_objects() {  # count of saved objects of type $1 in the Dashboards index
    os_get "/.kibana*/_count?q=type:%22$1%22" | grep -o '"count":[0-9]*' | cut -d: -f2
}

echo "=== Deploy: dashboard data accuracy, batch 17 (OpenSearch Dashboards objects) ==="
echo ""

echo "→ Step 1: Record the indices and templates before..."
INDICES_BEFORE=$(os_get "/_cat/indices?h=index" | grep -v '^\.' | sort)
echo "   ✓ $(echo "$INDICES_BEFORE" | grep -c .) data indices; index patterns $(saved_objects index-pattern || echo 0), dashboards $(saved_objects dashboard || echo 0)"
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

echo "→ Step 3: Arkime template marker (the helper waits for it; Arkime is off)..."
if os_get "/_template/arkime_sessions3_template" | grep -q mappings; then
    check "#73 arkime_sessions3_template present" 0 "already there, left alone"
else
    CODE=$(os_put "/_template/arkime_sessions3_template" '{"index_patterns":["nettap-arkime-template-marker"],"mappings":{"properties":{}}}')
    if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
    check "#73 arkime_sessions3_template marker written" "$rc" "HTTP ${CODE:-?} (matches no index)"
fi
echo ""

echo "→ Step 4: Recreate dashboards-helper..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate dashboards-helper
sleep 10
STATUS=$(sudo docker exec nettap-dashboards-helper supervisorctl -c /etc/supervisord.conf status 2>&1)
while IFS= read -r line; do echo "   $line"; done <<<"$STATUS"
if echo "$STATUS" | grep -q 'EACCES'; then rc=1; else rc=0; fi
check "#73 supervisor programs start" "$rc" "$(echo "$STATUS" | grep -c 'EACCES') EACCES"
if echo "$STATUS" | grep -E '^(cron|idxinit) ' | grep -q 'FATAL'; then rc=1; else rc=0; fi
check "#73 idxinit and cron are not FATAL" "$rc" "$(echo "$STATUS" | grep -E '^(cron|idxinit) ' | awk '{print $1 "=" $2}' | tr '\n' ' ')"
USERS=$(sudo docker exec nettap-dashboards-helper ps -eo user,args 2>/dev/null | grep -E 'supercronic|goStatic' | grep -v grep | awk '{print $1}' | sort -u | tr '\n' ' ')
if [ -n "$USERS" ] && ! echo "$USERS" | grep -qw root; then rc=0; else rc=1; fi
check "#73 the jobs run as helper, not root" "$rc" "${USERS:-no job process seen}"
echo ""

echo "→ Step 5: Wait for the index pattern and dashboards (cron runs every 2 min)..."
for i in $(seq 1 30); do
    IP=$(saved_objects index-pattern); DB=$(saved_objects dashboard)
    [ "${IP:-0}" -gt 0 ] && [ "${DB:-0}" -gt 0 ] && break
    [ $((i % 6)) -eq 0 ] && echo "   waiting... index patterns ${IP:-0}, dashboards ${DB:-0} ($i/30)"
    sleep 10
done
if [ "${IP:-0}" -gt 0 ]; then rc=0; else rc=1; fi
check "#73 Dashboards has index patterns" "$rc" "${IP:-0}"
if [ "${DB:-0}" -gt 0 ]; then rc=0; else rc=1; fi
check "#73 Dashboards has Malcolm's dashboards" "$rc" "${DB:-0}"
PATTERNS=$(os_get "/.kibana*/_search?q=type:%22index-pattern%22&size=20&_source=index-pattern.title" | grep -o '"title":"[^"]*"' | cut -d'"' -f4 | tr '\n' ' ')
echo "   index patterns: ${PATTERNS:-none}"
# The loader must also finish a whole run (detectors, alerting) without an error
OK_RUN=""
for i in $(seq 1 30); do
    RUNS=$(sudo docker logs --since 10m nettap-dashboards-helper 2>&1 | grep 'shared-object-creation' | grep -E 'job succeeded|exit status' | tail -1)
    case "$RUNS" in *"job succeeded"*) OK_RUN=yes; break ;; esac
    [ $((i % 6)) -eq 0 ] && echo "   waiting for a clean loader run... ($i/30)"
    sleep 10
done
LAST_ERR=$(sudo docker logs --since 10m nettap-dashboards-helper 2>&1 | grep -o 'line [0-9]*: [A-Z_]*: unbound variable' | tail -1)
if [ "$OK_RUN" = "yes" ]; then rc=0; else rc=1; fi
if [ "$OK_RUN" = "yes" ]; then RUN_NOTE="job succeeded"; else RUN_NOTE="${LAST_ERR:-no clean run yet}"; fi
check "#73 the object loader completes a run" "$rc" "$RUN_NOTE"
echo ""

echo "→ Step 6: Nothing else changed..."
INDICES_AFTER=$(os_get "/_cat/indices?h=index" | grep -v '^\.' | sort)
GONE=$(comm -23 <(echo "$INDICES_BEFORE") <(echo "$INDICES_AFTER") | grep . || true)
if [ -z "$GONE" ]; then rc=0; else rc=1; fi
check "#73 no data index was deleted" "$rc" "${GONE:-none gone}; $(echo "$INDICES_AFTER" | grep -c .) now"
TEMPLATE=$(os_get "/_index_template/malcolm_template" | grep -o '"index_patterns":\[[^]]*\]')
case "$TEMPLATE" in *arkime_sessions3-*) rc=0 ;; *) rc=1 ;; esac
check "Chain 24 malcolm_template still targets arkime_sessions3-*" "$rc" "${TEMPLATE:-missing}"
REFRESH=$(os_get "/_index_template/malcolm_template" | grep -o '"refresh_interval":"[^"]*"')
case "${REFRESH:-none}" in none|*'"1s"') rc=0 ;; *) rc=1 ;; esac
check "#73 new indices still refresh every second" "$rc" "${REFRESH:-not set (OpenSearch default 1s)}"
POLICY=$(os_get "/_plugins/_ism/policies/nettap-hot-policy" | grep -o '"min_index_age":"[^"]*"' | head -1)
if [ -n "$POLICY" ]; then rc=0; else rc=1; fi
check "nettap-hot-policy untouched" "$rc" "${POLICY:-missing}"
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|dashboards"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 17 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
