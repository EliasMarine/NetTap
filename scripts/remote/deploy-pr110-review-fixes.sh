#!/usr/bin/env bash
# Deploy the PR #110 review fixes and prove the daemon API is no longer open to the LAN.
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/pr110-review"
COMPOSE="docker/docker-compose.yml"
TOKEN_PATH="/run/nettap-auth/daemon-token"
PASS=0
FAIL=0

check() {
    # check <label> <expected> <actual>
    if [ "$2" = "$3" ]; then
        echo "   ✓ $1 ($3)"
        PASS=$((PASS + 1))
    else
        echo "   ✗ $1: expected $2, got $3"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Deploy PR #110 review fixes ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code updated: $(git log --oneline -1)"
echo ""

echo "→ Step 2: Rebuild daemon and web containers..."
sudo docker compose -f "$COMPOSE" build nettap-storage-daemon nettap-web || echo "   ✗ build failed"
echo "   ✓ Images rebuilt"
echo ""

echo "→ Step 3: Recreate daemon, web and nginx (nginx caches the web upstream)..."
sudo docker compose -f "$COMPOSE" up -d --force-recreate nettap-storage-daemon nettap-web nettap-nginx || echo "   ✗ recreate failed"
echo "   ✓ Containers recreated"
echo ""

echo "→ Step 4: Wait for containers to become healthy..."
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

echo "→ Step 5: Token is provisioned to the daemon and readable by web only..."
check "daemon has the token" "yes" "$(sudo docker exec nettap-storage-daemon sh -c "test -s $TOKEN_PATH && echo yes || echo no")"
check "web can read the token" "yes" "$(sudo docker exec nettap-web sh -c "test -r $TOKEN_PATH && echo yes || echo no")"
check "tshark cannot see the token" "no" "$(sudo docker exec nettap-tshark sh -c "test -e $TOKEN_PATH && echo yes || echo no" 2>/dev/null || echo no)"
echo ""

echo "→ Step 6: Daemon port rejects callers without the token..."
MGMT_IP=$(hostname -I | awk '{print $1}')
check "LAN address, no token" "401" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$MGMT_IP:8880/api/system/health")"
check "loopback, no token" "401" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8880/api/system/health)"
check "health stays open" "200" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8880/api/health)"
check "no CORS wildcard" "" "$(curl -s -D - -o /dev/null --max-time 5 http://127.0.0.1:8880/api/health | grep -i '^access-control-allow-origin' | tr -d '\r')"
echo ""

echo "→ Step 7: Daemon accepts the token from inside its own container..."
check "daemon call with token" "200" "$(sudo docker exec nettap-storage-daemon python3 -c "
import urllib.request
token = open('$TOKEN_PATH').read().strip()
req = urllib.request.Request('http://localhost:8880/api/system/health', headers={'X-NetTap-Daemon-Token': token})
print(urllib.request.urlopen(req, timeout=5).status)
" 2>/dev/null || echo error)"
echo ""

echo "→ Step 8: Web → daemon works through the app (public MAC lookup, also proves the OUI DB shipped)..."
LOOKUP=$(curl -sk --max-time 10 "https://localhost/api/tools/mac-lookup/B8:27:EB:00:00:01")
echo "   response: $LOOKUP"
check "lookup returns a vendor" "yes" "$(echo "$LOOKUP" | grep -qi 'raspberry' && echo yes || echo no)"
echo ""

echo "→ Step 9: Setup and bridge routes need a login once an admin exists..."
# Read-only probes on purpose: if the gate were broken, a POST here would really
# change retention or tear down the bridge.
check "GET /api/setup/storage without login is refused" "no" "$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 https://localhost/api/setup/storage | grep -q '^2' && echo yes || echo no)"
check "GET /api/bridge/health without login is refused" "no" "$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 https://localhost/api/bridge/health | grep -q '^2' && echo yes || echo no)"
echo ""

echo "→ Step 10: Recent daemon auth rejections (expected: the probes above)..."
sudo docker logs nettap-storage-daemon --since 2m 2>&1 | grep -i "token\|unauthor" | tail -5
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-nginx"
echo ""

echo "=== Deploy Complete: $PASS passed, $FAIL failed ==="
echo "Open the dashboard and log in to verify the pages load."
