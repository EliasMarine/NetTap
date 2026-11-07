#!/usr/bin/env bash
# Deploy NET-197 (web only): an API call without a session answers 401 JSON, not a redirect to /login.
#
# Only nettap-web is rebuilt and recreated. Checks through nginx, with no cookie:
#   /api/suricata/rules/live -> 401 application/json
#   the same address opened as a page (Sec-Fetch-Dest: document) -> 302 to /login
#   /alerts                  -> 302 to /login
#   /api/health              -> 200
# Prints status codes and content types only, never a token or a cookie.
# Then sign in on the dashboard and open Settings to check signed-in pages still load.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-api-401.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/api-401-expired-session"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

# reply <path> <curl -w format> [curl args]: one request with no cookie, redirects not followed (-k: self-signed cert)
reply() {
    local path=$1 format=$2
    shift 2
    curl -sk -o /dev/null --max-time 20 -w "$format" "$@" "$BASE$path" || true
}

echo "=== Deploy: API calls without a session answer 401 (NET-197) from $BRANCH ==="
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

echo "→ Step 3: Recreate the web container..."
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

echo "→ Step 5: Without a session, through nginx..."
OUT=$(reply /api/suricata/rules/live '%{http_code} %{content_type}')
case "$OUT" in "401 application/json"*) rc=0 ;; *) rc=1 ;; esac
check "/api/suricata/rules/live answers 401 JSON" "$rc" "$OUT"

OUT=$(reply /api/suricata/rules/live '%{http_code} %{redirect_url}' -H 'Sec-Fetch-Dest: document')
case "$OUT" in "302 "*/login) rc=0 ;; *) rc=1 ;; esac
check "the same address opened as a page goes to /login" "$rc" "$OUT"

OUT=$(reply /alerts '%{http_code} %{redirect_url}')
case "$OUT" in "302 "*/login) rc=0 ;; *) rc=1 ;; esac
check "/alerts still goes to /login" "$rc" "$OUT"

OUT=$(reply /api/health '%{http_code} %{content_type}')
case "$OUT" in "200 "*) rc=0 ;; *) rc=1 ;; esac
check "/api/health still open" "$rc" "$OUT"
echo ""

echo "→ Step 6: Web log errors since the restart..."
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-nginx"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed. Sign in and open Settings to check signed-in pages still load. ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
exit "$FAILED"
