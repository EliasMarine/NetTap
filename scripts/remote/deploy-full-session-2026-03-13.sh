#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/traffic-category-duplicate-services"

echo "=== Full Deploy — 2026-03-13 Session ==="
echo "Traffic Category v2 + Device Intelligence v2 + Smart Alerts Engine"
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "ERROR: Cannot cd to $REPO_DIR"; exit 1; }
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

echo "→ Step 4: Restart both containers..."
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

echo "→ Step 6: Test traffic category APIs..."
BW=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/traffic/categories/cloud/bandwidth?interval=1h" 2>/dev/null)
BW_POINTS=$(echo "$BW" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'bandwidth points={len(d.get(\"series\",[]))}')" 2>/dev/null || echo "error")
echo "   Category bandwidth: $BW_POINTS"

CAT_DETAIL=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/traffic/categories/cloud" 2>/dev/null)
CAT_INFO=$(echo "$CAT_DETAIL" | python3 -c "import sys,json; d=json.load(sys.stdin); svcs=d.get('services',[]); dupes=[s['name'] for s in svcs if [x['name'] for x in svcs].count(s['name'])>1]; print(f'devices={d.get(\"device_count\",0)} services={len(svcs)} dupes={len(set(dupes))}')" 2>/dev/null || echo "error")
echo "   Category detail: $CAT_INFO"
echo ""

echo "→ Step 7: Test device detail v2 APIs..."
TEST_IP="192.168.1.113"

CATEGORIES=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/devices/$TEST_IP/categories" 2>/dev/null)
CAT_COUNT=$(echo "$CATEGORIES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'categories={len(d.get(\"categories\",[]))}')" 2>/dev/null || echo "error")
echo "   Device categories: $CAT_COUNT"

ALERTS=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/devices/$TEST_IP/alerts?limit=3" 2>/dev/null)
ALERT_INFO=$(echo "$ALERTS" | python3 -c "import sys,json; d=json.load(sys.stdin); a=d.get('alerts',[]); sigs=[x.get('signature','?')[:40] for x in a[:2]]; print(f'total={d.get(\"total\",0)} samples={sigs}')" 2>/dev/null || echo "error")
echo "   Device alerts: $ALERT_INFO"

PORTS=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/devices/$TEST_IP/ports" 2>/dev/null)
PORT_COUNT=$(echo "$PORTS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'ports={len(d.get(\"ports\",[]))}')" 2>/dev/null || echo "error")
echo "   Device ports: $PORT_COUNT"

RISK=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/risk/scores/$TEST_IP" 2>/dev/null)
RISK_INFO=$(echo "$RISK" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'score={d.get(\"score\",\"?\")} level={d.get(\"level\",\"?\")} factors={len(d.get(\"factors\",[]))}')" 2>/dev/null || echo "error")
echo "   Risk score: $RISK_INFO"

DETAIL=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/devices/$TEST_IP" 2>/dev/null)
DETAIL_INFO=$(echo "$DETAIL" | python3 -c "import sys,json; d=json.load(sys.stdin).get('device',{}); print(f'orig_bytes={d.get(\"orig_bytes\",\"missing\")} unique_dests={d.get(\"unique_destinations\",\"missing\")} services={len(d.get(\"top_services\",[]))}')" 2>/dev/null || echo "error")
echo "   Enhanced detail: $DETAIL_INFO"
echo ""

echo "→ Step 8: Test smart alerts engine..."
SMART=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/alerts/smart?limit=5" 2>/dev/null)
SMART_INFO=$(echo "$SMART" | python3 -c "import sys,json; d=json.load(sys.stdin); alerts=d.get('alerts',[]); cats=set(a.get('category','?') for a in alerts); sevs=set(a.get('severity_label','?') for a in alerts); print(f'groups={len(alerts)} categories={cats} severities={sevs}')" 2>/dev/null || echo "error")
echo "   Smart alerts: $SMART_INFO"

SUMMARY=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/alerts/smart/summary" 2>/dev/null)
SUMMARY_INFO=$(echo "$SUMMARY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'threat_score={d.get(\"threat_score\",\"?\")} level={d.get(\"threat_level\",\"?\")} groups={d.get(\"total_groups\",0)} events={d.get(\"total_events\",0)}')" 2>/dev/null || echo "error")
echo "   Threat summary: $SUMMARY_INFO"

SMART_DEVICE=$(sudo docker exec nettap-storage-daemon curl -s "http://localhost:8880/api/alerts/smart?device_ip=$TEST_IP&limit=3" 2>/dev/null)
SMART_DEV_INFO=$(echo "$SMART_DEVICE" | python3 -c "import sys,json; d=json.load(sys.stdin); alerts=d.get('alerts',[]); print(f'device_alerts={len(alerts)} top_sig={alerts[0].get(\"signature\",\"?\")[:50] if alerts else \"none\"}')" 2>/dev/null || echo "error")
echo "   Smart alerts (device): $SMART_DEV_INFO"
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo ""
echo "Features deployed:"
echo "  1. Traffic Category Detail v2 — bandwidth chart, hostnames, search, auto-refresh"
echo "  2. Device Intelligence Dashboard v2 — 7 sections + TShark drill-down drawer"
echo "  3. Smart Alert Intelligence Engine — severity reclassification, dedup, suppress"
echo "  4. DualSeriesChart — Download/Upload area chart (cyan/purple)"
echo "  5. ConnectionDrawer — polished with terminal TShark output"
echo ""
echo "Test pages:"
echo "  https://nettap.bitspec.co/traffic/cloud"
echo "  https://nettap.bitspec.co/devices/192.168.1.113"
echo "  https://nettap.bitspec.co/devices/192.168.1.44"
