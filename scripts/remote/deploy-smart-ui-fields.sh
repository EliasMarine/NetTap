#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/smart-ui-fields"

echo "=== Deploy SMART UI Fields Fix ==="
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

echo "→ Step 3: Restart web container..."
sudo docker compose -f docker/docker-compose.yml up -d nettap-web --force-recreate
echo "   ✓ Web container restarted"
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

echo "→ Step 5: Verify SMART health API returns all fields..."
sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/smart/health | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    fields = ['device', 'device_type', 'model', 'serial', 'temperature_c',
              'percentage_used', 'power_on_hours', 'total_bytes_written',
              'total_bytes_read', 'media_errors', 'reallocated_sectors',
              'healthy', 'warnings', 'timestamp']
    print('   Field check:')
    for f in fields:
        val = d.get(f, '<<MISSING>>')
        if f == 'total_bytes_written' and isinstance(val, (int, float)) and val is not None:
            tb = val / (1024**4)
            print(f'   {f:>25s}: {val} ({tb:.2f} TB)')
        elif f == 'total_bytes_read' and isinstance(val, (int, float)) and val is not None:
            tb = val / (1024**4)
            print(f'   {f:>25s}: {val} ({tb:.2f} TB)')
        else:
            print(f'   {f:>25s}: {val}')
    missing = [f for f in fields if f not in d]
    if missing:
        print(f'   MISSING from API: {missing}')
    else:
        print('   ✓ All 14 fields present in API response')
except Exception as e:
    print(f'   Parse error: {e}')
" 2>/dev/null
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard → System page → Drive Health card."
echo "You should now see: Total Written, Total Read, Media Errors, Serial, Type, Last Updated."
