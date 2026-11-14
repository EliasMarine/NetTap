#!/usr/bin/env bash
# Deploy NET-273 (web only): one Settings page. Suricata rules, notification channels and backup are
# tabs now, grouped in a side menu; the old sub-page addresses redirect to their tab.
#
# Only nettap-web is rebuilt and recreated. Checks:
#   the built app inside the new container carries the new Settings page
#   through nginx, with no cookie: /settings and each old sub-page -> 302 to /login, /api/health -> 200
# Prints status codes only, never a token or a cookie.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-settings-hub.sh
# To try a branch before it merges: BRANCH=feature/settings-hub bash ...
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

echo "=== Deploy: one Settings page (NET-273) from $BRANCH ==="
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

echo "→ Step 5: The running app carries the new build..."
# The page needs a session to render, so the check reads the built app inside the container.
# Only text this change adds proves the new build.
for target in "Everything you can set on this NetTap" "before leaving the tab"; do
    if sudo docker exec nettap-web grep -rqF -- "$target" /app/build; then rc=0; else rc=1; fi
    check "built app has \"$target\"" "$rc" "$([ "$rc" -eq 0 ] && echo found || echo missing)"
done
echo ""

echo "→ Step 6: The pages answer, without a session, through nginx..."
for path in /settings /settings/suricata-rules /settings/notifications /settings/backup; do
    OUT=$(reply "$path" '%{http_code} %{redirect_url}')
    case "$OUT" in "302 "*/login) rc=0 ;; *) rc=1 ;; esac
    check "$path goes to /login" "$rc" "$OUT"
done
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
echo "Now sign in and open Settings: the side menu groups every tab; /settings/backup lands on the Backup & restore tab."
exit "$FAILED"
