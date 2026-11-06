#!/usr/bin/env bash
# Deploy the data accuracy audit fixes (NET-155: NET-156 Overview, NET-157 Investigate,
# NET-158 Devices, NET-159 System) and check the new behaviour on real data.
#
# The daemon and the web container are rebuilt. Then:
#   - System health is one of healthy / problem / incomplete (S5)
#   - the device count takes active_since, and an unreadable one is a 400 (D12)
#   - a device's connections take a protocol filter, reject an unknown one, and carry a direction (D5, D6)
#   - the SSL tool reports openssl's own verdict: trusted for a good site, not trusted for an expired
#     one, and a name mismatch for the wrong host (S1, S3)
#   - ping reports a real loss percentage and RTT (S2, S12)
#   - verify-figures.sh and verify-acceptance.sh compare page figures with OpenSearch
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-audit.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

daemon() {  # daemon <GET|POST> <path> <python expression on the reply `d`, or 'status'> [JSON body]
    # The expression is always a literal from this script; the token is read inside the container
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.error, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
body = sys.argv[4].encode() if len(sys.argv) > 4 else None
req = urllib.request.Request('http://localhost:8880' + sys.argv[2], data=body, method=sys.argv[1],
                             headers={'X-NetTap-Daemon-Token': token, 'Content-Type': 'application/json'})
try:
    r = urllib.request.urlopen(req, timeout=120)
    code, d = r.status, json.load(r)
except urllib.error.HTTPError as e:
    code, d = e.code, {}
print(code if sys.argv[3] == 'status' else eval(sys.argv[3]))" "$@" 2>&1 | tail -n 1
}

echo "=== Deploy: data accuracy audit (NET-155) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build and recreate the daemon and the web container..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
for svc in nettap-storage-daemon nettap-web; do
    STATUS="unknown"
    for _ in $(seq 1 36); do
        STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "unknown")
        [ "$STATUS" = "healthy" ] && break
        sleep 5
    done
    if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
    check "$svc health" "$rc" "$STATUS"
done
echo ""

echo "→ Step 3: The new behaviour on real data..."
HEALTH=$(daemon GET /api/system/health "d.get('status')")
case "$HEALTH" in healthy|problem|incomplete) rc=0 ;; *) rc=1 ;; esac
check "S5 system health is one of three states" "$rc" "$HEALTH"

SINCE=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
ONLINE=$(daemon GET "/api/devices/count?active_since=$SINCE" "d.get('count')")
if [[ "$ONLINE" =~ ^[0-9]+$ ]]; then rc=0; else rc=1; fi
check "D12 devices online in the last 15 minutes" "$rc" "$ONLINE"
BAD=$(daemon GET "/api/devices/count?active_since=not-a-time" status)
if [ "$BAD" = "400" ]; then rc=0; else rc=1; fi
check "D12 an unreadable active_since is refused" "$rc" "HTTP $BAD"

IP=$(daemon GET "/api/devices?limit=1" "(d.get('devices') or [{}])[0].get('ip', '')")
if [[ "$IP" =~ ^[0-9a-fA-F:.]+$ ]]; then
    BAD=$(daemon GET "/api/devices/$IP/connections?proto=bogus" status)
    if [ "$BAD" = "400" ]; then rc=0; else rc=1; fi
    check "D6 an unknown protocol filter is refused ($IP)" "$rc" "HTTP $BAD"
    DIRS=$(daemon GET "/api/devices/$IP/connections?proto=tcp&size=50" "sorted({str(c.get('direction')) for c in d['connections']}) if all((c.get('network') or {}).get('transport') == 'tcp' for c in d['connections']) else 'non-TCP row'")
    case "$DIRS" in "[]"|"['in']"|"['out']"|"['in', 'out']") rc=0 ;; *) rc=1 ;; esac
    check "D5/D6 TCP rows only, each with a direction" "$rc" "$DIRS"
else
    echo "   · no device listed; device connection checks skipped"
fi

GOOD=$(daemon POST /api/tools/ssl-cert "(d.get('trusted'), d.get('name_match'))" '{"host": "example.com", "port": 443}')
if [ "$GOOD" = "(True, True)" ]; then rc=0; else rc=1; fi
check "S1 example.com is trusted and matches its name" "$rc" "$GOOD"
EXPIRED=$(daemon POST /api/tools/ssl-cert "(d.get('trusted'), d.get('verify_errors'))" '{"host": "expired.badssl.com", "port": 443}')
case "$EXPIRED" in "(False, "*expired*) rc=0 ;; *) rc=1 ;; esac
check "S1 expired.badssl.com is not trusted, and says why" "$rc" "$EXPIRED"
WRONG=$(daemon POST /api/tools/ssl-cert "d.get('name_match')" '{"host": "wrong.host.badssl.com", "port": 443}')
if [ "$WRONG" = "False" ]; then rc=0; else rc=1; fi
check "S1 wrong.host.badssl.com does not match its name" "$rc" "$WRONG"

PING=$(daemon POST /api/tools/ping "(d.get('packet_loss_pct'), d.get('rtt_avg'))" '{"target": "127.0.0.1", "count": 3}')
case "$PING" in "(0, "[0-9]*")"|"(0.0, "[0-9]*")") rc=0 ;; *) rc=1 ;; esac
check "S2 ping to 127.0.0.1: 0% loss and a real RTT" "$rc" "$PING"
echo ""

echo "→ Step 4: Page figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 5: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Audit fixes deployed and verified — open Home, Live, Devices and IoT ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
