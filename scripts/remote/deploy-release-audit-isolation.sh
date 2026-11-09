#!/usr/bin/env bash
# Recreate TShark and nginx so the NET-229 container changes take effect.
# - nettap-tshark: no network, runs as nobody (65534).
# - nettap-nginx: /cyberchef/ needs a NetTap session.
# Run it after deploy-release-audit.sh, which recreates only the web UI and the daemon.
#
# Effect while it runs (about 30 s):
# - The dashboard is unreachable while nginx restarts.
# - PCAP filters and packet details fail while TShark restarts.
# - Capture, Zeek, Suricata and the network path are not touched.
#
# Rollback: git checkout main, then run the Step 3 command again.
#
# Run as the normal user (NOT with sudo), on the device:
#   bash scripts/remote/deploy-release-audit-isolation.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/release-audit-2026-11"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Recreate TShark and nginx from $BRANCH (NET-229) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Check the new config before touching anything..."
if ! "${COMPOSE[@]}" config --quiet; then
    echo "   ✗ docker-compose.yml doesn't parse — nothing was recreated"
    exit 1
fi
# nginx -t in a throwaway container, so a bad file never reaches the running proxy
# (every upstream uses "resolve", so no network is needed)
if ! sudo docker run --rm --network none -v "$REPO_DIR/docker/nginx.conf:/etc/nginx/nginx.conf:ro" \
        -v "$REPO_DIR/docker/ssl:/etc/nginx/ssl:ro" nginx:1.30-alpine nginx -t -q; then
    echo "   ✗ nginx rejects the new nginx.conf — nothing was recreated"
    exit 1
fi
echo "   ✓ Compose file and nginx.conf are valid"
echo ""

echo "→ Step 3: Recreate TShark and nginx..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-tshark nettap-nginx
echo "   ✓ Containers recreated"
echo ""

echo "→ Step 4: Wait for containers to become healthy..."
for i in $(seq 1 30); do
    TSHARK_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-tshark 2>/dev/null || echo "unknown")
    NGINX_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-nginx 2>/dev/null || echo "unknown")
    if [ "$TSHARK_STATUS" = "healthy" ] && [ "$NGINX_STATUS" = "healthy" ]; then
        echo "   ✓ Both containers healthy"
        break
    fi
    echo "   waiting... tshark=$TSHARK_STATUS nginx=$NGINX_STATUS ($i/30)"
    sleep 5
done
[ "$TSHARK_STATUS" = "healthy" ] && [ "$NGINX_STATUS" = "healthy" ] || check "containers healthy" 1 "tshark=$TSHARK_STATUS nginx=$NGINX_STATUS"
echo ""

echo "→ Step 5: TShark still reads the captures as nobody..."
# the newest file the capture wrote; capinfos opens it the same way PCAP Search does
NEWEST=$(sudo docker exec nettap-tshark sh -c 'ls -t $(find /pcap -type f -name "*.pcap*" -mmin -60 2>/dev/null) 2>/dev/null | head -1')
if [ -z "$NEWEST" ]; then
    check "TShark reads a capture" 1 "no capture file written in the last hour under /pcap"
elif sudo docker exec nettap-tshark capinfos -c "$NEWEST" >/dev/null 2>&1; then
    check "TShark reads a capture" 0 "capinfos opened the newest file as $(sudo docker exec nettap-tshark id -u)"
else
    check "TShark reads a capture" 1 "capinfos could not open the newest file (permissions?)"
fi
echo ""

echo "→ Step 6: The dashboard answers through the new nginx..."
code=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/)
case "$code" in
    200|302|303) check "Dashboard reachable" 0 "https://localhost/ answered $code" ;;
    *) check "Dashboard reachable" 1 "https://localhost/ answered $code" ;;
esac
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-tshark|nettap-nginx"
echo ""

echo "→ Step 8: Smoke test (read-only), including TShark isolation and CyberChef's login..."
if ! (set -o pipefail; bash "$REPO_DIR/scripts/remote/smoke-test-release.sh" | sed 's/^/   /'); then
    FAILED=1
fi
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Recreate Complete: every check passed ==="
else
    echo "=== Recreate finished with failed checks (✗ above) ==="
fi
[ "$FAILED" -eq 0 ]
