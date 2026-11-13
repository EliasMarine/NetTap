#!/usr/bin/env bash
# Deploy the six network diagnostic tools (NET-261) and check each daemon route answers.
#
# Rebuilds the daemon (iperf3 joins the image) and the web container, recreates only those two,
# then calls each new route from inside the daemon container (the token never leaves it).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-network-tools.sh
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

# Call a daemon route from inside its container with the shared token; prints "<status> <body>".
daemon_call() {  # daemon_call METHOD PATH [JSON_BODY]
    sudo docker exec -e M="$1" -e P="$2" -e B="${3:-}" nettap-storage-daemon python3 -c '
import json, os, urllib.error, urllib.request
token = open("/run/nettap-auth/daemon-token").read().strip()
body = os.environ["B"].encode() or None
req = urllib.request.Request("http://localhost:8880" + os.environ["P"], data=body, method=os.environ["M"],
                             headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print(r.status, r.read().decode()[:600])
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode()[:600])
except Exception as e:
    print("000", e)' 2>/dev/null
}

expect_200() {  # expect_200 LABEL METHOD PATH [BODY]
    local out
    out=$(daemon_call "$2" "$3" "${4:-}")
    case "$out" in 200*) check "$1" 0 "$(printf '%s' "${out#200 }" | cut -c1-160)" ;; *) check "$1" 1 "$(printf '%s' "$out" | cut -c1-200)" ;; esac
}

echo "=== Deploy: network diagnostic tools ($BRANCH) ==="
echo ""

echo "→ Step 1: Update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the daemon and web containers..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the daemon and web containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for both to become healthy..."
WEB="unknown"; DAEMON="unknown"
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$WEB" = "healthy" ] && [ "$DAEMON" = "healthy" ] && break
    echo "   waiting... web=$WEB daemon=$DAEMON ($i/30)"
    sleep 5
done
if [ "$WEB" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$WEB"
if [ "$DAEMON" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-storage-daemon health" "$rc" "$DAEMON"
echo ""

echo "→ Step 5: Check the new tools..."
if sudo docker exec nettap-storage-daemon iperf3 --version >/dev/null 2>&1; then check "iperf3 in the daemon image" 0; else check "iperf3 in the daemon image" 1; fi
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DAY_AGO=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)
TWO_DAYS_AGO=$(date -u -d '48 hours ago' +%Y-%m-%dT%H:%M:%SZ)
expect_200 "DNS resolver compare" POST /api/tools/dns-compare '{"name":"nettap.local","record_type":"A","resolvers":["192.168.1.1","9.9.9.9"]}'
# 00:00:5e:00:53:01 is a documentation MAC (RFC 7042): a 200 with no transactions proves the route
expect_200 "DHCP lease timeline" GET "/api/dhcp/timeline?mac=00:00:5e:00:53:01&from=$DAY_AGO&to=$NOW"
expect_200 "Local services" GET "/api/local-services?from=$DAY_AGO&to=$NOW"
expect_200 "Device traffic compare" GET "/api/moment/device-compare?ip=192.168.1.1&a_from=$TWO_DAYS_AGO&a_to=$DAY_AGO&b_from=$DAY_AGO&b_to=$NOW"
expect_200 "Path MTU check" POST /api/tools/mtu '{"target":"9.9.9.9"}'
# No iperf3 server is expected on the router: a 200 with a "No iperf3 server" error proves the path
expect_200 "LAN throughput test (refused path)" POST /api/tools/throughput '{"host":"192.168.1.1","port":5201,"duration":1,"direction":"upload"}'
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
    echo "Open Tools: DNS reconnaissance › Compare resolvers, DHCP lease timeline, LAN throughput test,"
    echo "Ping and traceroute › MTU; Devices › Local services; a device page › Compare periods."
else
    echo "=== Deploy finished with ✗ lines above — paste this output back ==="
fi
