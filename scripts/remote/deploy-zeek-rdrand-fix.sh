#!/usr/bin/env bash
# Deploy the Zeek RDRAND fix and check that Zeek records reach OpenSearch.
#
# Some AMD CPUs (the GMKtec G11) return the same RDRAND value every time, so
# every Zeek process got the same Broker ID, the Zeek cluster never connected,
# and Zeek wrote no logs. zeek-live is now built locally with a small library
# that makes std::random_device read /dev/urandom (Chain 23).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-zeek-rdrand-fix.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/zeek-rdrand-urandom"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
OS_CURL=(sudo docker exec nettap-opensearch curl -s
    --config /var/local/curlrc/.opensearch.primary.curlrc
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure)
FAILED=0

zeek_node_id() {
    sudo docker exec -w /tmp nettap-zeek-live /usr/local/zeek/bin/zeek \
        -b base/frameworks/broker -e 'print Broker::node_id();' 2>/dev/null | tail -1
}

zeek_doc_count() {
    "${OS_CURL[@]}" "https://localhost:9200/arkime_sessions3-*/_count?q=event.provider:zeek" 2>/dev/null \
        | grep -o '"count":[0-9]*' | cut -d: -f2
}

echo "=== Deploy: Zeek RDRAND fix ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# A failed checkout or pull would rebuild the old code, so stop here instead
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build zeek-live (compiles the fix and tests it inside the image)..."
if ! "${COMPOSE[@]}" build zeek-live; then
    echo "   ✗ Build failed — nothing was restarted. Look for FAIL lines above."
    exit 1
fi
echo "   ✓ zeek-live image built"
echo ""

echo "→ Step 3: Recreate zeek-live (nothing else is touched)..."
BEFORE=$(zeek_doc_count)
"${COMPOSE[@]}" up -d --no-deps --force-recreate zeek-live
echo "   ✓ zeek-live recreated (Zeek records in OpenSearch before: ${BEFORE:-unknown})"
echo ""

echo "→ Step 4: Each Zeek process now gets its own Broker ID..."
sleep 5
ID1=$(zeek_node_id)
ID2=$(zeek_node_id)
if [ -n "$ID1" ] && [ "$ID1" != "$ID2" ]; then
    echo "   ✓ Different IDs: $ID1 / $ID2"
else
    echo "   ✗ IDs are the same or missing ('$ID1' / '$ID2') — the fix is not active"
    FAILED=1
fi
echo ""

echo "→ Step 5: Wait for the Zeek cluster to connect (up to 3 min)..."
LINKS=0
for i in $(seq 1 36); do
    LINKS=$(ss -Htn state established | grep -cE ':2776[0-9]\b')
    [ "$LINKS" -gt 0 ] && break
    echo "   waiting... no Zeek cluster connections yet ($i/36)"
    sleep 5
done
if [ "$LINKS" -gt 0 ]; then
    echo "   ✓ $LINKS cluster connections (there were none before the fix)"
else
    echo "   ✗ No cluster connections — see: sudo docker logs nettap-zeek-live --tail 50"
    FAILED=1
fi
echo ""

echo "→ Step 6: Wait for Zeek to write conn.log (up to 3 min)..."
CONN=""
for i in $(seq 1 36); do
    CONN=$(sudo docker exec nettap-zeek-live sh -c 'wc -l < /zeek/live/logs/current/conn.log' 2>/dev/null)
    [ -n "$CONN" ] && [ "$CONN" -gt 0 ] && break
    echo "   waiting... no conn.log yet ($i/36)"
    sleep 5
done
if [ -n "$CONN" ] && [ "$CONN" -gt 0 ]; then
    echo "   ✓ conn.log has $CONN lines"
else
    echo "   ✗ No conn.log — Zeek is not seeing traffic"
    FAILED=1
fi
echo ""

echo "→ Step 7: Wait for Zeek records in OpenSearch (up to 5 min; Logstash sends in batches)..."
COUNT=""
for i in $(seq 1 60); do
    COUNT=$(zeek_doc_count)
    [ -n "$COUNT" ] && [ "$COUNT" -gt "${BEFORE:-0}" ] && break
    echo "   waiting... Zeek records: ${COUNT:-unreadable} ($i/60)"
    sleep 5
done
if [ -n "$COUNT" ] && [ "$COUNT" -gt "${BEFORE:-0}" ]; then
    echo "   ✓ $COUNT Zeek records in OpenSearch"
else
    echo "   ✗ No new Zeek records — check: sudo docker logs nettap-filebeat --tail 30"
    FAILED=1
fi
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|zeek-live|filebeat|logstash"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: Zeek is logging and its records reach OpenSearch ==="
    echo "Open the dashboard; connection and device pages fill in over the next few minutes."
else
    echo "=== Deploy finished with ✗ lines above — paste this output back ==="
fi
