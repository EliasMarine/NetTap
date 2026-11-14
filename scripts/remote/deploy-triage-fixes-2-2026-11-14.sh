#!/usr/bin/env bash
# Deploy the second round of 2026-11-14 bug-triage fixes and check each one on the box:
#   NET-275 (daemon) a time window outside 1970-9998 gets 400, not 500; two chart routes keep the slot budget
#   NET-277 (web)    Go Live before the first admin goes to /setup  (the G11 has an admin: only the
#                    unchanged signed-out redirect can be checked here; CI's first-run job covers the rest)
#   NET-276 (web)    a Packets link opened from outside NetTap fills the search but waits for Run
#
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and counts, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-triage-fixes-2-2026-11-14.sh
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
import json, os, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
token = open("/run/nettap-auth/daemon-token").read().strip()
def call(method, path):
    req = urllib.request.Request("http://localhost:8880" + path, method=method,
                                 headers={"X-NetTap-Daemon-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
def window(start, end=None):
    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return urllib.parse.urlencode({"from": start, "to": end})
try:
    exec(os.environ["SNIPPET"])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])' 2>/dev/null || echo "FAIL could not run inside the daemon container"
}

# expect CODE: prints OK/FAIL, the status and the start of the body for one daemon call
expect_status() {  # expect_status LABEL CODE PATH_EXPR
    local out rc
    out=$(daemon_py "
status, body = call('GET', $3)
print('OK' if status == $2 else 'FAIL', status, body[:120])")
    case "$out" in OK*) rc=0 ;; *) rc=1 ;; esac
    check "$1" "$rc" "$out"
}

echo "=== Deploy: bug-triage fixes, round 2, 2026-11-14 ($BRANCH) ==="
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

echo "→ Step 5: NET-275, out-of-range years get 400 instead of 500..."
expect_status "year 1 on /api/traffic/summary gets 400" 400 \
    '"/api/traffic/summary?" + window("0001-01-01T00:00:00Z")'
expect_status "year 9999 on /api/traffic/summary gets 400" 400 \
    '"/api/traffic/summary?" + window("2026-01-01T00:00:00Z", "9999-12-31T23:59:59Z")'
expect_status "year 1 since on /api/devices/registry/new-count gets 400" 400 \
    '"/api/devices/registry/new-count?since=0001-01-01T00:00:00%2B14:00"'
echo ""

echo "→ Step 6: NET-275, the two chart routes that skipped the slot budget now refuse a 1970 window..."
expect_status "1970 window on /api/alerts/categories gets 400" 400 \
    '"/api/alerts/categories?" + window("1970-01-01T00:00:00Z")'
expect_status "1970 window on /api/bandwidth/daily gets 400" 400 \
    '"/api/bandwidth/daily?" + window("1970-01-01T00:00:00Z")'
# The pages send recent windows; those must still answer
expect_status "last 24 h on /api/alerts/categories still answers" 200 \
    '"/api/alerts/categories?" + window((datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))'
expect_status "last 30 days on /api/bandwidth/daily still answers" 200 \
    '"/api/bandwidth/daily?" + window((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))'
echo ""

echo "→ Step 7: NET-277, Go Live signed out still goes to sign-in (this box has an admin)..."
LOC=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code} %{redirect_url}' "$BASE/go-live" || true)
case "$LOC" in "302 "*"/login"*) rc=0 ;; *) rc=1 ;; esac
check "/go-live goes to /login" "$rc" "$LOC"
CODE=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health" || true)
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/health answers" "$rc" "$CODE"
echo ""

echo "→ Step 8: NET-276, the Packets page's waiting state is in the new build..."
# The page needs a session to render, so the check reads the built app inside the container.
# Only text this change adds proves the new build.
TARGET="A search opened from a link, a bookmark or a reload"
if sudo docker exec nettap-web grep -rqF -- "$TARGET" /app/build; then rc=0; else rc=1; fi
check "built app has the waiting message" "$rc" "$([ "$rc" -eq 0 ] && echo found || echo missing)"
LOC=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code} %{redirect_url}' "$BASE/packets?filter=tcp" || true)
case "$LOC" in "302 "*"/login"*) rc=0 ;; *) rc=1 ;; esac
check "/packets with a search, signed out, goes to /login" "$rc" "$LOC"
echo "   To see it: paste a /packets?… link into a new tab while signed in; it waits for Run the search."
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
