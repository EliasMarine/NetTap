#!/usr/bin/env bash
# Deploy the unified detail drawer feature (daemon + web containers)
# Run on the NetTap device: sudo bash scripts/remote/deploy-detail-drawer.sh

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
elif [ "$OS_STATUS" = "unhealthy" ]; then
    echo "  -> OpenSearch is unhealthy. Restarting..."
    sudo docker restart nettap-opensearch
fi

# The healthcheck has start_period: 180s — Docker reports "starting" for that
# entire window regardless of actual readiness. We must wait long enough for
# both the start_period AND at least one successful health check (interval: 30s).
# Total budget: 240s (180s start_period + 60s for health checks to pass).
if [ "$OS_STATUS" != "healthy" ]; then
    echo "  -> Waiting for OpenSearch to become healthy (up to 240s)..."
    echo "    (healthcheck start_period is 180s — 'starting' is normal during this window)"
    for i in $(seq 1 24); do
        OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
        if [ "$OS_STATUS" = "healthy" ]; then
            echo "  -> OpenSearch is healthy after ~$((i * 10))s"
            break
        fi
        if [ "$OS_STATUS" = "unhealthy" ]; then
            echo "    [$((i * 10))s] status=$OS_STATUS — breaking early to attempt bootstrap"
            break
        fi
        echo "    [$((i * 10))s] status=$OS_STATUS ..."
        sleep 10
    done
fi

OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
if [ "$OS_STATUS" != "healthy" ]; then
    echo ""
    echo "  !!! OpenSearch not healthy ($OS_STATUS). Attempting security bootstrap..."
    # Write roles_mapping.yml
    sudo docker exec nettap-opensearch python3 -c "open('/usr/share/opensearch/config/opensearch-security/roles_mapping.yml','w').write('---\n_meta:\n  type: \"rolesmapping\"\n  config_version: 2\n\nall_access:\n  reserved: false\n  backend_roles:\n  - \"admin\"\n  description: \"Maps admin backend role to all_access\"\n')"
    # Push security config
    sudo docker exec nettap-opensearch bash -c 'JAVA_HOME=/usr/share/opensearch/jdk /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh -cd /usr/share/opensearch/config/opensearch-security/ -cacert /usr/share/opensearch/config/certs/ca.crt -cert /usr/share/opensearch/config/certs/admin.crt -key /usr/share/opensearch/config/certs/admin.key -icl -nhnv' 2>&1 | tail -5

    # After bootstrap, wait up to 90s more for health check to pass
    echo "  -> Waiting up to 90s for health check to pass after bootstrap..."
    for i in $(seq 1 9); do
        OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
        if [ "$OS_STATUS" = "healthy" ]; then
            echo "  -> OpenSearch is healthy after bootstrap + $((i * 10))s"
            break
        fi
        echo "    [$((i * 10))s] status=$OS_STATUS ..."
        sleep 10
    done

    OS_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
    if [ "$OS_STATUS" != "healthy" ]; then
        # Last resort: check if OpenSearch is actually responding even though Docker says "starting"
        echo "  -> Docker says '$OS_STATUS' but checking if OpenSearch actually responds..."
        OS_RESP=$(sudo docker exec nettap-opensearch curl -sf --config /var/local/curlrc/.opensearch.primary.curlrc --cacert /usr/share/opensearch/config/certs/ca.crt --insecure 'https://localhost:9200/_cluster/health' 2>/dev/null || echo "FAIL")
        if echo "$OS_RESP" | grep -q '"status"'; then
            echo "  -> OpenSearch IS responding (Docker health status lag). Proceeding anyway."
            echo "     $OS_RESP"
        else
            echo ""
            echo "  !!! ERROR: OpenSearch is truly unreachable. Cannot deploy daemon/web."
            echo "  !!! Check logs: sudo docker logs nettap-opensearch --tail 50"
            exit 1
        fi
    fi
fi
echo "  -> OpenSearch: ready"

echo ""
echo "=== Step 3: Rebuild and deploy daemon + web ==="
# IMPORTANT: Must include nettap-nginx in the recreate. Nginx caches upstream
# DNS at startup — if nettap-web gets a new IP, nginx keeps the old one and
# routes requests to the wrong container (e.g., Grafana instead of SvelteKit).
sudo docker compose -f "$COMPOSE" up -d --force-recreate --build nettap-storage-daemon nettap-web nettap-nginx

echo ""
echo "=== Step 4: Wait 15s for containers to start ==="
sleep 15

echo ""
echo "=== Step 5: Verify containers are running ==="
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-storage-daemon|nettap-web|nettap-opensearch|nettap-nginx"

echo ""
echo "=== Step 6: Test daemon endpoints ==="
DCURL="sudo docker exec nettap-storage-daemon curl -s"

echo "--- /api/capture/mode (was 503, should now work) ---"
$DCURL http://localhost:8880/api/capture/mode | python3 -m json.tool 2>/dev/null || echo "FAILED"

echo ""
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
echo "--- /api/lookup/whois/8.8.8.8 (new endpoint) ---"
$DCURL http://localhost:8880/api/lookup/whois/8.8.8.8 | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'WHOIS for {d.get(\"ip\",\"?\")}: error={d.get(\"error\",\"none\")}')
if d.get('parsed'):
    for k,v in list(d['parsed'].items())[:5]:
        print(f'  {k}: {v}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "--- /api/devices (drawer needs this) ---"
$DCURL http://localhost:8880/api/devices?limit=3 | python3 -c "
import json,sys
d=json.load(sys.stdin)
devs=d.get('devices',[])
print(f'Devices: {len(devs)} returned (of {d.get(\"total\",\"?\")} total)')
for dev in devs[:3]:
    print(f'  {dev[\"ip\"]} — {dev.get(\"hostname\") or \"(no hostname)\"} — {dev.get(\"manufacturer\") or \"(unknown)\"}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "=== Done! ==="
echo ""
echo "Test the drawer by opening any page and clicking a table row:"
echo "  - Logs:            http://<nettap-ip>:3000/logs"
echo "  - Connections:     http://<nettap-ip>:3000/connections"
echo "  - Alerts:          http://<nettap-ip>:3000/alerts"
echo "  - Devices:         http://<nettap-ip>:3000/devices"
echo "  - Investigations:  http://<nettap-ip>:3000/investigations"
echo ""
echo "Verify: drawer slides in from right, tabs work, ESC closes it."
echo "On Connections: TShark Analysis tab should load packets + hex dump."
echo "Block IP button should be hidden (mirror mode)."
