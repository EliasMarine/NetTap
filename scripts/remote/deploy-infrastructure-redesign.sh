#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/infrastructure-redesign"

echo "=== Deploy Infrastructure Page Redesign ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code updated"
echo ""

echo "→ Step 2: Rebuild web container..."
sudo docker compose -f docker/docker-compose.yml build nettap-web
echo "   ✓ Web container rebuilt"
echo ""

echo "→ Step 3: Restart web + nginx containers..."
sudo docker compose -f docker/docker-compose.yml up -d nettap-web --force-recreate
sudo docker compose -f docker/docker-compose.yml restart nettap-nginx
echo "   ✓ Containers restarted"
echo ""

echo "→ Step 4: Wait for web container to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ]; then
        echo "   ✓ Web container healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS ($i/30)"
    sleep 5
done
echo ""

echo "→ Step 5: Test infrastructure API endpoints..."
echo "   OpenSearch cluster:"
sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/opensearch/cluster | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'     Status: {d.get(\"status\", \"?\")}, Nodes: {d.get(\"number_of_nodes\", \"?\")}, Shards: {d.get(\"active_shards\", \"?\")}')
except:
    print('     Could not parse response')
" 2>/dev/null

echo "   Logstash stats:"
sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/logstash/stats | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ev = d.get('events', d)
    ein = ev.get('in', ev.get('events_in', '?'))
    eout = ev.get('out', ev.get('events_out', '?'))
    print(f'     Events in: {ein}, Events out: {eout}')
except:
    print('     Could not parse response (Logstash may not be reachable)')
" 2>/dev/null

echo "   Bridge health:"
sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/bridge/health | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'     State: {d.get(\"bridge_state\", \"?\")}, Health: {d.get(\"health_status\", \"?\")}')
except:
    print('     Could not parse response')
" 2>/dev/null
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-nginx|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard → Infrastructure page to see the Pipeline Operations Center."
echo "Click each node in the topology to expand its detail panel."
