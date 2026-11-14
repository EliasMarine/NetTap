#!/usr/bin/env bash
# Deploy the 2026-11-14 bug-triage fixes and check each one on the box:
#   NET-268 (daemon) DNS Lookup of a name like "ns" no longer returns the root servers
#   NET-256 (daemon) trust-score halves round up            (unit-tested; nothing to see here)
#   NET-257 (web)    an /api request another site starts gets 403
#   NET-260 (both)   the MAC device page gets a bandwidth series that adds up to its total
# NET-252 and NET-253 are installer fixes; they only run on a fresh install.
#
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and counts, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-triage-fixes-2026-11-14.sh
# To try a branch before it merges: BRANCH=fix/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

# Run a Python check inside the daemon container with the shared token as `call(method, path, body)`.
daemon_py() {  # daemon_py PYTHON_SNIPPET
    sudo docker exec -e SNIPPET="$1" nettap-storage-daemon python3 -c '
import json, os, urllib.error, urllib.request
token = open("/run/nettap-auth/daemon-token").read().strip()
def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://localhost:8880" + path, data=data, method=method,
                                 headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
try:
    exec(os.environ["SNIPPET"])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])' 2>/dev/null || echo "FAIL could not run inside the daemon container"
}

# An /api request with no cookie through nginx, as a browser would send it from SITE (-k: self-signed).
status_from() {  # status_from SITE PATH
    curl -sk -o /dev/null --max-time 20 -w '%{http_code}' -H "Sec-Fetch-Site: $1" "$BASE$2" || true
}

echo "=== Deploy: bug-triage fixes 2026-11-14 ($BRANCH) ==="
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
# A failed build must stop here: recreating would bring back the OLD images unnoticed.
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

echo "→ Step 5: NET-268, a DNS Lookup of \"ns\" asks for the name, not the root servers..."
# The old argv (`dig ns A`) read "ns" as the record type and answered with a.root-servers.net and co.
OUT=$(daemon_py '
status, body = call("POST", "/api/tools/dns-recon", {"domain": "ns", "record_types": ["A"]})
print("OK" if status == 200 and "root-servers" not in body else "FAIL", status, body[:160])')
case "$OUT" in OK*) rc=0 ;; *) rc=1 ;; esac
check "lookup of ns answers for ns" "$rc" "$OUT"
echo ""

echo "→ Step 6: NET-257, an /api request another site starts is refused..."
CODE=$(status_from cross-site /api/threats/beaconing)
if [ "$CODE" = "403" ]; then rc=0; else rc=1; fi
check "cross-site /api request gets 403" "$rc" "$CODE"
CODE=$(status_from cross-site /api/pcap/download)
if [ "$CODE" = "403" ]; then rc=0; else rc=1; fi
check "cross-site PCAP download gets 403" "$rc" "$CODE"
# Same request from NetTap's own pages: past the new check, it reaches the sign-in rule (no cookie here)
CODE=$(status_from same-origin /api/threats/beaconing)
if [ "$CODE" = "401" ]; then rc=0; else rc=1; fi
check "same-origin /api request reaches sign-in (401)" "$rc" "$CODE"
CODE=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health" || true)
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/health answers" "$rc" "$CODE"
echo ""

echo "→ Step 7: NET-260, a device's bandwidth series adds up to its total..."
OUT=$(daemon_py '
status, body = call("GET", "/api/devices/registry?limit=25")
devices = json.loads(body).get("devices", []) if status == 200 else []
result = "FAIL no device had traffic in the last 24 h (list status %s, %d devices)" % (status, len(devices))
for device in devices[:10]:
    s, b = call("GET", "/api/devices/registry/%s/traffic" % device["mac"])
    if s != 200:
        result = "FAIL traffic status %s" % s
        break
    reply = json.loads(b)
    traffic = reply["traffic"]
    series = traffic.get("bandwidth_series")
    if series is None:
        result = "FAIL no bandwidth_series in the reply"
        break
    if traffic["total_bytes"] > 0:
        summed = sum(p["bytes"] for p in series)
        verdict = "OK" if summed == traffic["total_bytes"] else "FAIL"
        result = "%s %d slots of %s, series %d bytes, total %d bytes" % (
            verdict, len(series), reply.get("bandwidth_interval"), summed, traffic["total_bytes"])
        break
print(result)')
case "$OUT" in OK*) rc=0 ;; *) rc=1 ;; esac
check "series sums to the total" "$rc" "$OUT"
echo ""

echo "→ Step 8: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 5m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
echo "Now sign in and open a device by MAC (Devices › By type): the Bandwidth over time card shows."
exit "$FAILED"
