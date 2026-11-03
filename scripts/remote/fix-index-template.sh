#!/usr/bin/env bash
# Fix malcolm_template so OpenSearch indices get Malcolm's field types (Chain 24).
#
# The installer pushed malcolm_template with its index pattern still set to the
# placeholder MALCOLM_NETWORK_INDEX_PATTERN_REPLACER, so it matched no index.
# Each daily arkime_sessions3-* index then guessed its field types from the first
# records (event.id as a number, IPs as text), OpenSearch rejected Zeek records,
# and the dashboard's traffic and device views stayed empty.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/fix-index-template.sh
#       fixes the template; today's index keeps its wrong types until 00:00 UTC
#   bash /home/nettap/NetTap/scripts/remote/fix-index-template.sh --delete-today
#       also DELETES today's index (its records are lost) so it is recreated now
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/index-template-pattern"
INDEX_PATTERN="arkime_sessions3-*"
TODAY_INDEX="arkime_sessions3-$(date -u +%y%m%d)"
DELETE_TODAY=false
[ "${1:-}" = "--delete-today" ] && DELETE_TODAY=true
OS_CURL=(sudo docker exec nettap-opensearch curl -s
    --config /var/local/curlrc/.opensearch.primary.curlrc
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure)
FAILED=0

field_type() {
    "${OS_CURL[@]}" "https://localhost:9200/${TODAY_INDEX}/_mapping/field/$1" 2>/dev/null \
        | grep -o '"type":"[a-z_]*"' | head -1 | cut -d'"' -f4
}

doc_count() {
    "${OS_CURL[@]}" "https://localhost:9200/${TODAY_INDEX}/_count?q=$1" 2>/dev/null \
        | grep -o '"count":[0-9]*' | cut -d: -f2
}

echo "=== Fix: malcolm_template index pattern ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Push malcolm_template with the index pattern filled in..."
# Runs inside dashboards-helper (template file + OpenSearch credentials live there)
CODE=$(sudo docker exec nettap-dashboards-helper bash -c \
    "sed 's/MALCOLM_NETWORK_INDEX_PATTERN_REPLACER/${INDEX_PATTERN}/g' /opt/templates/malcolm_template.json \
     | curl -sk --config /var/local/curlrc/.opensearch.primary.curlrc -X PUT \
         https://opensearch:9200/_index_template/malcolm_template \
         -H 'Content-Type: application/json' -d @- -o /dev/null -w '%{http_code}'")
if [ "$CODE" = "200" ]; then
    echo "   ✓ Template pushed"
else
    echo "   ✗ Push failed (HTTP ${CODE:-none}) — nothing else was changed"
    exit 1
fi
PATTERNS=$("${OS_CURL[@]}" "https://localhost:9200/_index_template/malcolm_template?filter_path=index_templates.index_template.index_patterns")
echo "   index_patterns now: $PATTERNS"
echo ""

echo "→ Step 3: Today's index (${TODAY_INDEX})..."
echo "   records: $(doc_count '*'), event.id type: $(field_type event.id), source.ip type: $(field_type source.ip)"
if [ "$DELETE_TODAY" = "true" ]; then
    if "${OS_CURL[@]}" -X DELETE "https://localhost:9200/${TODAY_INDEX}" | grep -q '"acknowledged":true'; then
        echo "   ✓ Deleted; Logstash recreates it from the fixed template with its next batch"
    else
        echo "   ✗ Delete failed"
        FAILED=1
    fi
else
    echo "   Left as is: the fix applies from the next daily index (00:00 UTC)."
    echo "   To apply it now: bash $REPO_DIR/scripts/remote/fix-index-template.sh --delete-today"
fi
echo ""

if [ "$DELETE_TODAY" = "true" ] && [ "$FAILED" -eq 0 ]; then
    echo "→ Step 4: Wait for the new index to get Zeek connection records (up to 4 min)..."
    CONN=""
    for i in $(seq 1 48); do
        CONN=$(doc_count 'event.provider:zeek%20AND%20event.dataset:conn')
        [ -n "$CONN" ] && [ "$CONN" -gt 0 ] && break
        echo "   waiting... Zeek conn records: ${CONN:-index not created yet} ($i/48)"
        sleep 5
    done
    SRC_TYPE=$(field_type source.ip)
    ID_TYPE=$(field_type event.id)
    if [ "$SRC_TYPE" = "ip" ] && [ "$ID_TYPE" = "keyword" ]; then
        echo "   ✓ Malcolm field types: source.ip=$SRC_TYPE, event.id=$ID_TYPE"
    else
        echo "   ✗ Field types still guessed: source.ip=${SRC_TYPE:-?}, event.id=${ID_TYPE:-?}"
        FAILED=1
    fi
    if [ -n "$CONN" ] && [ "$CONN" -gt 0 ]; then
        echo "   ✓ $CONN Zeek connection records"
    else
        echo "   ✗ No Zeek connection records yet — check: sudo docker logs nettap-logstash --since 5m | grep -c 'Could not index'"
        FAILED=1
    fi
    echo ""

    echo "→ Step 5: Dashboard API (traffic summary, last 24 h)..."
    TOKEN=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)
    SUMMARY=$(curl -s -m 15 -H "X-NetTap-Daemon-Token: $TOKEN" http://localhost:8880/api/traffic/summary)
    CONNS=$(printf '%s' "$SUMMARY" | grep -o '"connection_count": *[0-9]*' | grep -o '[0-9]*$')
    if [ -n "$CONNS" ] && [ "$CONNS" -gt 0 ]; then
        echo "   ✓ $CONNS connections in the traffic summary"
    else
        echo "   ✗ Traffic summary still empty: $SUMMARY"
        FAILED=1
    fi
    echo ""
fi

if [ "$FAILED" -eq 0 ]; then
    echo "=== Done ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
