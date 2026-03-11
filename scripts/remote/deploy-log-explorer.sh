#!/usr/bin/env bash
# Deploy the Log Explorer redesign (daemon + web containers)
# Run on the NetTap device: sudo bash scripts/remote/deploy-log-explorer.sh

set -u

BRANCH="phase-5/mirror-span-mode"
COMPOSE="docker/docker-compose.yml"
NETTAP_DIR="/home/nettap/NetTap"

echo "=== Step 1: Pull latest code ==="
cd "$NETTAP_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
git pull origin "$BRANCH"

echo ""
echo "=== Step 2: Check OpenSearch health (daemon + web depend on it) ==="
OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "missing")
OS_RUNNING=$(sudo docker inspect --format='{{.State.Running}}' nettap-opensearch 2>/dev/null || echo "false")
echo "  OpenSearch container: running=$OS_RUNNING, health=$OS_STATUS"

if [ "$OS_RUNNING" != "true" ]; then
    echo "  -> OpenSearch not running. Starting it..."
    sudo docker compose -f "$COMPOSE" up -d opensearch
    echo "  -> Waiting 30s for OpenSearch to initialize..."
    sleep 30
elif [ "$OS_STATUS" = "unhealthy" ]; then
    echo "  -> OpenSearch is unhealthy. Restarting..."
    sudo docker restart nettap-opensearch
    echo "  -> Waiting 30s for OpenSearch to recover..."
    sleep 30
fi

# Wait for OpenSearch to become healthy (up to 180s)
if [ "$OS_STATUS" != "healthy" ]; then
    echo "  -> Waiting for OpenSearch to become healthy (up to 180s)..."
    for i in $(seq 1 18); do
        OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
        if [ "$OS_STATUS" = "healthy" ]; then
            echo "  -> OpenSearch is healthy after ~$((i * 10))s"
            break
        fi
        echo "    [$((i * 10))s] status=$OS_STATUS ..."
        sleep 10
    done
fi

OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
if [ "$OS_STATUS" != "healthy" ]; then
    echo ""
    echo "  !!! OpenSearch still unhealthy after waiting. Attempting security bootstrap..."
    # Write roles_mapping.yml
    sudo docker exec nettap-opensearch python3 -c "open('/usr/share/opensearch/config/opensearch-security/roles_mapping.yml','w').write('---\n_meta:\n  type: \"rolesmapping\"\n  config_version: 2\n\nall_access:\n  reserved: false\n  backend_roles:\n  - \"admin\"\n  description: \"Maps admin backend role to all_access\"\n')"
    # Push security config
    sudo docker exec nettap-opensearch bash -c 'JAVA_HOME=/usr/share/opensearch/jdk /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh -cd /usr/share/opensearch/config/opensearch-security/ -cacert /usr/share/opensearch/config/certs/ca.crt -cert /usr/share/opensearch/config/certs/admin.crt -key /usr/share/opensearch/config/certs/admin.key -icl -nhnv' 2>&1 | tail -5
    echo "  -> Waiting 15s after security bootstrap..."
    sleep 15

    # Check once more
    OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
    if [ "$OS_STATUS" != "healthy" ]; then
        echo ""
        echo "  !!! ERROR: OpenSearch is still $OS_STATUS. Cannot deploy daemon/web."
        echo "  !!! Check logs: sudo docker logs nettap-opensearch --tail 50"
        exit 1
    fi
fi
echo "  -> OpenSearch: $OS_STATUS"

echo ""
echo "=== Step 3: Rebuild and deploy daemon + web ==="
sudo docker compose -f "$COMPOSE" up -d --force-recreate --build nettap-storage-daemon nettap-web

echo ""
echo "=== Step 4: Wait 15s for containers to start ==="
sleep 15

echo ""
echo "=== Step 5: Verify containers are running ==="
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-storage-daemon|nettap-web|nettap-opensearch"

echo ""
echo "=== Step 6: Test daemon log endpoints (from inside container) ==="
DCURL="sudo docker exec nettap-storage-daemon curl -s"

echo "--- /api/logs/stats ---"
$DCURL http://localhost:8880/api/logs/stats | python3 -m json.tool 2>/dev/null | head -10 || echo "FAILED"

echo ""
echo "--- /api/logs/timeline ---"
$DCURL http://localhost:8880/api/logs/timeline | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'Timeline: {len(d.get(\"buckets\",[]))} buckets, interval={d.get(\"interval\",\"?\")}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "--- /api/logs/protocol-breakdown ---"
$DCURL http://localhost:8880/api/logs/protocol-breakdown | python3 -c "
import json,sys
d=json.load(sys.stdin)
for p in d.get('protocols',[]):
    print(f'  {p[\"label\"]}: {p[\"count\"]:,}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "--- /api/logs/top-talkers ---"
$DCURL http://localhost:8880/api/logs/top-talkers | python3 -c "
import json,sys
d=json.load(sys.stdin)
for t in d.get('talkers',[])[:5]:
    print(f'  {t[\"ip\"]}: {t[\"count\"]:,}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "--- /api/logs/top-dns ---"
$DCURL http://localhost:8880/api/logs/top-dns | python3 -c "
import json,sys
d=json.load(sys.stdin)
for q in d.get('queries',[])[:5]:
    print(f'  {q[\"domain\"]}: {q[\"count\"]:,}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "=== Done! Open the Log Explorer page in your browser to verify the UI. ==="
