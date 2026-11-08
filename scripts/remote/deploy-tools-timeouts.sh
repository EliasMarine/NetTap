#!/usr/bin/env bash
# Deploy NET-203 (daemon + web):
#   - DNS reconnaissance runs its record-type lookups at the same time, and dig retries a slow
#     DNS server after 2 s instead of 5 s, so a lookup answers in seconds instead of up to 70 s;
#   - each Tools page waits 5 s past the daemon's own limit for that tool (DNS 15 s, ping 20 s,
#     traceroute 35 s, SSL certificate 25 s) instead of the 10 s default;
#   - a time limit running out reads "NetTap took too long to answer" instead of "Daemon unreachable".
#
# nettap-storage-daemon and nettap-web are rebuilt and recreated; nothing else is touched.
# Checks: both images carry the change, both containers are healthy, a DNS lookup for example.com
# through the daemon API answers in under 10 s with records, and the sign-in page answers.
#
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=fix/tools-timeouts bash /home/nettap/NetTap/scripts/remote/deploy-tools-timeouts.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy Tools time limits and concurrent DNS lookups (NET-203) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# A failed checkout or pull would rebuild the old code, so stop here instead
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code at $(git log --oneline -1)"
echo ""

echo "→ Step 2: Rebuild the daemon and web containers..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
if "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then rc=0; else rc=1; fi
check "images built" "$rc" "nettap-storage-daemon, nettap-web"
if [ "$rc" -ne 0 ]; then
    echo ""
    echo "=== Stopped: the build failed; the running containers were left as they were ==="
    exit 1
fi
echo ""

echo "→ Step 3: Recreate the daemon and web containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for both to become healthy..."
WEB_STATUS=unknown
DAEMON_STATUS=unknown
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "containers healthy" "$rc" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 5: Check both images carry the change..."
if sudo docker exec nettap-storage-daemon grep -qsF "+tries=2" /opt/nettap/daemon/services/dns_recon_service.py 2>/dev/null; then rc=0; else rc=1; fi
check "daemon: dig retries a slow server sooner" "$rc" "nettap-storage-daemon"
if sudo docker exec nettap-web sh -c "grep -rqs 'NetTap took too long to answer' /app/build" 2>/dev/null; then rc=0; else rc=1; fi
check "web: a timeout says 'took too long'" "$rc" "nettap-web"
echo ""

echo "→ Step 6: Time a DNS lookup through the daemon API..."
# Runs inside the daemon container (it has no curl): reads the token there and never prints it.
# Prints "<seconds> <HTTP status> <records> <errors>".
DNS=$(sudo docker exec nettap-storage-daemon python3 -c '
import json, time, urllib.error, urllib.request
token = open("/run/nettap-auth/daemon-token").read().strip()
req = urllib.request.Request(
    "http://127.0.0.1:8880/api/tools/dns-recon",
    data=json.dumps({"domain": "example.com"}).encode(),
    method="POST",
    headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"},
)
start = time.monotonic()
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        status, body = resp.status, json.load(resp)
except urllib.error.HTTPError as exc:
    status, body = exc.code, {}
except Exception:
    status, body = 0, {}
print("%.1f %s %s %s" % (time.monotonic() - start, status, body.get("total_records", 0), len(body.get("errors", []))))
' 2>/dev/null || echo "0 0 0 0")
read -r SECS STATUS RECORDS ERRORS <<< "$DNS"
if [ "$STATUS" = "200" ] && [ "${RECORDS:-0}" -gt 0 ] && awk "BEGIN { exit !(${SECS:-99} < 10) }"; then rc=0; else rc=1; fi
check "DNS lookup for example.com" "$rc" "HTTP $STATUS in ${SECS}s, $RECORDS records, $ERRORS errors"
echo ""

echo "→ Step 7: Check the web still serves the sign-in page..."
LOGIN=$(sudo docker exec nettap-web node -e "fetch('http://localhost:3000/login').then(r=>console.log(r.status)).catch(()=>console.log(0))")
if [ "$LOGIN" = "200" ]; then rc=0; else rc=1; fi
check "sign-in page" "$rc" "HTTP $LOGIN"
echo ""

echo "→ Step 8: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 5m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed. Open Tools › DNS reconnaissance and look up a domain. ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
exit "$FAILED"
