#!/usr/bin/env bash
# Fix OpenSearch security bootstrap + restart dependent containers
set -u

COMPOSE="docker/docker-compose.yml"

echo "=== Fix OpenSearch Security Bootstrap ==="
echo ""

echo "→ Step 1: Write roles_mapping.yml..."
sudo docker exec nettap-opensearch bash -c 'cat > /usr/share/opensearch/config/opensearch-security/roles_mapping.yml <<YAMLEOF
---
_meta:
  type: "rolesmapping"
  config_version: 2

all_access:
  reserved: false
  backend_roles:
    - "admin"
  description: "Maps admin backend role to all_access"
YAMLEOF'
echo "   ✓ roles_mapping.yml written"
echo ""

echo "→ Step 2: Push security config to OpenSearch..."
sudo docker exec nettap-opensearch bash -c \
  'JAVA_HOME=/usr/share/opensearch/jdk /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh \
  -cd /usr/share/opensearch/config/opensearch-security/ \
  -cacert /usr/share/opensearch/config/certs/ca.crt \
  -cert /usr/share/opensearch/config/certs/admin.crt \
  -key /usr/share/opensearch/config/certs/admin.key \
  -icl -nhnv'
echo "   ✓ Security config pushed"
echo ""

echo "→ Step 3: Verify auth works..."
AUTH_TEST=$(sudo docker exec nettap-opensearch curl --config /var/local/curlrc/.opensearch.primary.curlrc --cacert /usr/share/opensearch/config/certs/ca.crt --insecure -s 'https://localhost:9200/_cluster/health' 2>&1)
if echo "$AUTH_TEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   Cluster: {d[\"cluster_name\"]}, status: {d[\"status\"]}')" 2>/dev/null; then
    echo "   ✓ Auth working"
else
    echo "   ✗ Auth still broken: ${AUTH_TEST:0:200}"
    echo "   Aborting — fix the auth issue before restarting containers"
    exit 1
fi
echo ""

echo "→ Step 4: Restart dependent containers..."
sudo docker compose -f "$COMPOSE" restart logstash filebeat
echo "   ✓ logstash + filebeat restarted"
echo ""

echo "→ Step 5: Recreate web + daemon + nginx (were stuck waiting on healthy opensearch)..."
sudo docker compose -f "$COMPOSE" up -d nettap-web nettap-storage-daemon nettap-nginx --force-recreate
echo "   ✓ web + daemon + nginx recreated"
echo ""

echo "→ Step 6: Wait for containers to become healthy..."
for i in $(seq 1 30); do
    OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$OS_STATUS" = "healthy" ] && [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        echo "   ✓ All containers healthy"
        break
    fi
    echo "   waiting... opensearch=$OS_STATUS web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
echo ""

echo "→ Step 7: Final status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep nettap
echo ""

echo "=== Fix Complete ==="
