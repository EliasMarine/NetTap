#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/connections-v3"

echo "=== Deploy Connections v3 Redesign ==="
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

echo "→ Step 3: Rebuild daemon container..."
sudo docker compose -f docker/docker-compose.yml build nettap-storage-daemon
echo "   ✓ Daemon container rebuilt"
echo ""

echo "→ Step 4: Restart containers..."
sudo docker compose -f docker/docker-compose.yml up -d nettap-web nettap-storage-daemon --force-recreate
echo "   ✓ Containers restarted"
echo ""

echo "→ Step 5: Wait for containers to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        echo "   ✓ Both containers healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
echo ""

echo "→ Step 6: Test connections stats endpoint..."
sudo docker exec nettap-storage-daemon python3 -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('http://localhost:8880/api/traffic/connections/stats', timeout=10)
    d = json.loads(r.read())
    print('   total_sessions:', d.get('total_sessions', 'N/A'))
    print('   bytes_in:', d.get('bytes_in', 'N/A'))
    print('   bytes_out:', d.get('bytes_out', 'N/A'))
    print('   alert_sessions:', d.get('alert_sessions', 'N/A'))
    print('   protocols:', len(d.get('protocols', [])), 'entries')
    print('   top_sources:', len(d.get('top_sources', [])), 'entries')
    print('   top_destinations:', len(d.get('top_destinations', [])), 'entries')
    print('   ✓ Stats endpoint working')
except Exception as e:
    print('   ✗ Stats endpoint error:', e)
"
echo ""

echo "→ Step 7: Test connections sankey endpoint..."
sudo docker exec nettap-storage-daemon python3 -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('http://localhost:8880/api/traffic/connections/sankey?limit=5', timeout=10)
    d = json.loads(r.read())
    nodes = d.get('nodes', {})
    print('   sources:', len(nodes.get('sources', [])))
    print('   protocols:', len(nodes.get('protocols', [])))
    print('   destinations:', len(nodes.get('destinations', [])))
    print('   links:', len(d.get('links', [])))
    print('   ✓ Sankey endpoint working')
except Exception as e:
    print('   ✗ Sankey endpoint error:', e)
"
echo ""

echo "→ Step 8: Test connections timeline endpoint..."
sudo docker exec nettap-storage-daemon python3 -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('http://localhost:8880/api/traffic/connections/timeline?interval=1h', timeout=10)
    d = json.loads(r.read())
    print('   interval:', d.get('interval', 'N/A'))
    print('   buckets:', len(d.get('buckets', [])))
    if d.get('buckets'):
        b = d['buckets'][0]
        print('   first bucket protocols:', list(b.get('protocols', {}).keys()))
    print('   ✓ Timeline endpoint working')
except Exception as e:
    print('   ✗ Timeline endpoint error:', e)
"
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard and navigate to /connections to verify the redesign."
