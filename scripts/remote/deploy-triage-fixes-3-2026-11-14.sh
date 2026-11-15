#!/usr/bin/env bash
# Deploy the third round of 2026-11-14 bug fixes and check each one on the box:
#   NET-280 (web)    /api/bridge/* needs a session before the first admin exists (the G11 has an
#                    admin: only the unchanged signed-out 401 can be checked here; CI's first-run job
#                    covers the pre-admin case)
#   NET-283 (web)    Packets "All traffic" plan line ends in a full stop
#   NET-284 (web)    DHCP timeline fits its card at 1440 px (layout: CI's table-fit visual test)
#   NET-285 (web)    Changelog Events table fits its card at 1440 px (same)
#   NET-288 (daemon) /api/system/versions: nettap-daemon is the only core row, nettap-web appears
#                    once, nettap-config is gone (404)
#
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and counts, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-triage-fixes-3-2026-11-14.sh
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

# Run a Python check inside the daemon container with the shared token as `call(method, path)`.
daemon_py() {  # daemon_py PYTHON_SNIPPET
    sudo docker exec -e SNIPPET="$1" nettap-storage-daemon python3 -c '
import json, os, urllib.error, urllib.request
token = open("/run/nettap-auth/daemon-token").read().strip()
def call(method, path):
    req = urllib.request.Request("http://localhost:8880" + path, method=method,
                                 headers={"X-NetTap-Daemon-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
try:
    exec(os.environ["SNIPPET"])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])' 2>/dev/null || echo "FAIL could not run inside the daemon container"
}

# result OUT: OK… passes, anything else fails
result() {  # result LABEL OUTPUT
    local rc
    case "$2" in OK*) rc=0 ;; *) rc=1 ;; esac
    check "$1" "$rc" "$2"
}

echo "=== Deploy: bug fixes, round 3, 2026-11-14 ($BRANCH) ==="
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

echo "→ Step 5: NET-280, a signed-out bridge call gets 401 JSON..."
OUT=$(curl -sk -X POST --max-time 20 -w ' %{http_code}' "$BASE/api/bridge/create" || true)
case "$OUT" in *"Sign in first"*" 401") rc=0 ;; *) rc=1 ;; esac
check "POST /api/bridge/create without a session gets 401" "$rc" "${OUT: -3}"
CODE=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health" || true)
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/health answers" "$rc" "$CODE"
echo ""

echo "→ Step 6: NET-283, the Packets plan line's full stop is in the new build..."
# The page needs a session to render, so the check reads the built app inside the container.
TARGET="no filter, so every packet."
if sudo docker exec nettap-web grep -rqF -- "$TARGET" /app/build; then rc=0; else rc=1; fi
check "built app has the full-stop plan line" "$rc" "$([ "$rc" -eq 0 ] && echo found || echo missing)"
echo ""

echo "→ Step 7: NET-284 / NET-285, the two pages still load (layout is checked by CI at 1440 px)..."
for path in "/tools/dhcp-timeline" "/changelog"; do
    LOC=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code} %{redirect_url}' "$BASE$path" || true)
    case "$LOC" in "302 "*"/login"*) rc=0 ;; *) rc=1 ;; esac
    check "$path signed out goes to /login" "$rc" "$LOC"
done
echo "   To see it: open /tools/dhcp-timeline for a device and /changelog in a 1440 px window; no column runs past its card."
echo ""

echo "→ Step 8: NET-288, the versions list has no always-unknown core rows..."
result "fresh scan: core rows are nettap-daemon only, nettap-web once" "$(daemon_py "
status, body = call('POST', '/api/system/versions/scan')
rows = json.loads(body).get('versions', []) if status == 200 else []
core = sorted(r['name'] for r in rows if r.get('category') == 'core')
web = sum(1 for r in rows if r.get('name') == 'nettap-web')
ok = status == 200 and core == ['nettap-daemon'] and web == 1
print('OK' if ok else 'FAIL', status, 'core=' + ','.join(core), 'nettap-web rows=' + str(web))")"
result "GET /api/system/versions/nettap-config is 404" "$(daemon_py "
status, _ = call('GET', '/api/system/versions/nettap-config')
print('OK' if status == 404 else 'FAIL', status)")"
echo ""

echo "→ Step 9: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 5m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 10: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
