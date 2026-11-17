#!/usr/bin/env bash
# Deploy NET-318 (web only): resizable columns on the Devices table (drag or arrow keys, saved
# in the browser, "Reset column widths"), and Copy kept to the right of each MAC.
#
# Only nettap-web is rebuilt and recreated. Checks:
#   the built client carries the resize code; the built Devices page opts in (resizeKey "devices")
#   through nginx, with no cookie: /devices -> 302 to /login, /api/health -> 200 (liveness only)
# Prints status codes only, never a token or a cookie.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-devices-resize.sh
# To try a branch before it merges: BRANCH=feature/devices-resizable-columns bash ...
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

# reply <path> <curl -w format>: one request with no cookie, redirects not followed (-k: self-signed cert)
reply() {
    curl -sk -o /dev/null --max-time 20 -w "$2" "$BASE$1" || true
}

echo "=== Deploy: resizable Devices columns (NET-318) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code at $(git log --oneline -1)"
echo ""

echo "→ Step 2: Rebuild the web container..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
if "${COMPOSE[@]}" build nettap-web; then rc=0; else rc=1; fi
check "image built" "$rc" "nettap-web"
if [ "$rc" -ne 0 ]; then
    echo ""
    echo "=== Stopped: the build failed; the running container was left as it was ==="
    exit 1
fi
echo ""

echo "→ Step 3: Recreate the web container (the dashboard shows 502 for about 30 s)..."
"${COMPOSE[@]}" up -d --force-recreate nettap-web
echo ""

echo "→ Step 4: Wait for it to become healthy..."
WEB_STATUS=unknown
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "web healthy" "$rc" "web=$WEB_STATUS"
echo ""

echo "→ Step 5: The running app carries resizable columns..."
# The resize code lives in the shared DataTable, so it can sit in any client chunk: search them all
for TEXT in "nettap-col-widths" "col-resize" "Reset column widths"; do
    if sudo docker exec nettap-web grep -rqF "$TEXT" /app/build/client; then rc=0; else rc=1; fi
    check "client carries $TEXT" "$rc" "$([ "$rc" -eq 0 ] && echo found || echo missing)"
done
# The Devices page turns it on; the page needs a session, so read its built server chunk
PAGE=$(sudo docker exec nettap-web sh -c 'ls /app/build/server/chunks/entries/pages/devices/_page.svelte.js-*.js 2>/dev/null | grep -v "\.map$" | head -n 1')
if [ -n "$PAGE" ]; then rc=0; else rc=1; fi
check "built Devices page found" "$rc" "${PAGE:-missing}"
if [ -n "$PAGE" ]; then
    if sudo docker exec nettap-web grep -qE 'resizeKey: ?"devices"' "$PAGE"; then rc=0; else rc=1; fi
    check "Devices table opts in" "$rc" "$([ "$rc" -eq 0 ] && echo found || echo missing)"
fi
echo ""

echo "→ Step 6: The page answers, without a session, through nginx..."
OUT=$(reply /devices '%{http_code} %{redirect_url}')
case "$OUT" in "302 "*/login*) rc=0 ;; *) rc=1 ;; esac
check "/devices goes to /login" "$rc" "$OUT"
OUT=$(reply /api/health '%{http_code}')
case "$OUT" in 200) rc=0 ;; *) rc=1 ;; esac
check "/api/health answers" "$rc" "$OUT"
echo ""

echo "→ Step 7: Web log errors since the restart..."
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-nginx"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
echo "Now sign in and open Devices: drag a column edge (or focus it and use the arrow keys), and check Copy sits right of each MAC."
exit "$FAILED"
