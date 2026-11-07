#!/usr/bin/env bash
# Deploy NET-193 (web only): the network tools and lookups need a login.
#
# Only nettap-web is rebuilt and recreated. Checks, with no session: every tools and lookup
# page and API answers a redirect to /login; /login and /api/health still answer 200.
# Then sign in on the dashboard and open Tools to check they still work.
#
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=fix/tools-require-login bash /home/nettap/NetTap/scripts/remote/deploy-tools-login.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: the tools and lookups need a login (NET-193) from $BRANCH ==="
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

echo "→ Step 5: Without a session, the tools and lookups send you to /login..."
status() {  # status <path>: "<code> <location>" for a request with no cookie, redirects not followed
    sudo docker exec nettap-web node -e "fetch('http://localhost:3000$1', {redirect: 'manual'}).then(r => console.log(r.status, r.headers.get('location') || '-')).catch(() => console.log('0 -'))"
}
for path in /tools /tools/ping /lookup/whois /api/tools/ping /api/tools/mac-lookup/00:00:00:00:00:00 /api/lookup/dns/1.1.1.1 /api/lookup/whois/1.1.1.1 /api/auth/other /api/auth/me/x /api/auth/..%2Ftools%2Fping; do
    OUT=$(status "$path")
    if [ "${OUT%% *}" = "302" ] && [ "${OUT#* }" = "/login" ]; then rc=0; else rc=1; fi
    check "$path without a session" "$rc" "$OUT"
done
for path in /login /api/health; do
    OUT=$(status "$path")
    if [ "${OUT%% *}" = "200" ]; then rc=0; else rc=1; fi
    check "$path still open" "$rc" "$OUT"
done
# /api/auth/me reaches its route and answers 401 itself (not a redirect)
OUT=$(status /api/auth/me)
if [ "$OUT" = "401 -" ]; then rc=0; else rc=1; fi
check "/api/auth/me answers for itself" "$rc" "$OUT"
echo ""

echo "→ Step 6: Web log errors since the restart..."
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed. Sign in and open Tools (ping, DNS recon, MAC lookup) to check they still work. ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
exit "$FAILED"
