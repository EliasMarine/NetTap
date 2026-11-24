#!/usr/bin/env bash
# Deploy the fixes from the 23 Nov 2026 exploratory browser QA (NET-361 to NET-373) as their PRs merge.
# Safe to run after each merge: it rebuilds nettap-web and nettap-storage-daemon (compose recreates a
# container only when its image changed) and recreates nettap-nginx only when docker/nginx.conf on disk
# differs from the one the running container has (a single-file bind mount keeps the old file after a
# git pull, so a reload is not enough).
#
# Before the first build it tags the running web and daemon images as :rollback-qa-1124 (kept on later
# runs). To go back, tag one over :latest and recreate it, e.g.
#   sudo docker tag nettap/web:rollback-qa-1124 nettap/web:latest
#   sudo docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-web
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-qa-fixes-2026-11-23.sh
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
MINT="$REPO_DIR/scripts/remote/mint-session.cjs"
ROLLBACK_TAG="rollback-qa-1124"
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

check_eq() {  # check_eq LABEL ACTUAL EXPECTED
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2, expected $3"; fi
}

image_id() { sudo docker image inspect -f '{{.Id}}' "$1" 2>/dev/null; }

signed_in() {  # signed_in CURL_ARGS...: one curl through nginx with a fresh 60 s session; prints nosession if none
    local session
    # Never printed and never on a command line: printf is a builtin and curl reads the header from stdin
    # shellcheck disable=SC2024  # the user reads the file; only docker needs sudo
    session=$(sudo docker exec -i -w /app nettap-web node - < "$MINT")
    if [ -z "$session" ]; then echo "nosession"; return; fi
    printf 'Cookie: nettap_token=%s\n' "$session" | curl -sk --max-time 30 -H @- "$@"
}

echo "=== Deploy: browser QA fixes, 23 Nov 2026 (NET-361…373, $BRANCH) ==="
echo ""

echo "→ Step 1: Record the running images to roll back to..."
for svc in web storage-daemon; do
    if [ -n "$(image_id "nettap/$svc:$ROLLBACK_TAG")" ]; then
        echo "   ✓ nettap/$svc:$ROLLBACK_TAG kept from the first run"
    elif running=$(sudo docker inspect -f '{{.Image}}' "nettap-$svc" 2>/dev/null) && [ -n "$running" ] \
        && sudo docker tag "$running" "nettap/$svc:$ROLLBACK_TAG"; then
        echo "   ✓ Tagged the running nettap-$svc image ${running:7:12} as :$ROLLBACK_TAG"
    else
        echo "   ✗ Couldn't tag the running nettap-$svc image — nothing was changed"
        exit 1
    fi
done
echo ""

echo "→ Step 2: Update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Build the web and daemon containers..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
WEB_BUILT=$(image_id nettap/web:latest)
DAEMON_BUILT=$(image_id nettap/storage-daemon:latest)
echo "   ✓ Built web ${WEB_BUILT:7:12}, daemon ${DAEMON_BUILT:7:12}"
echo ""

echo "→ Step 4: Start the new images (a container is recreated only if its image changed)..."
if ! "${COMPOSE[@]}" up -d --no-deps nettap-web nettap-storage-daemon; then
    echo "   ✗ docker compose up failed — see the rollback lines at the top of this script"
    exit 1
fi
echo "   ✓ Up"
if sudo docker exec nettap-nginx cat /etc/nginx/nginx.conf 2>/dev/null | cmp -s - docker/nginx.conf; then
    echo "   ✓ nginx already has this nginx.conf — not touched"
else
    echo "   nginx.conf changed — recreating nettap-nginx (the dashboard drops for a few seconds)"
    if "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-nginx; then
        echo "   ✓ nettap-nginx recreated"
    else
        echo "   ✗ Recreating nettap-nginx failed: sudo docker logs nettap-nginx --tail 30"
        FAILED=1
    fi
fi
echo ""

echo "→ Step 5: Wait for the containers to become healthy..."
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo unknown)
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo unknown)
    NGINX=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-nginx 2>/dev/null || echo unknown)
    [ "$WEB" = healthy ] && [ "$DAEMON" = healthy ] && [ "$NGINX" = healthy ] && break
    echo "   waiting... web=$WEB daemon=$DAEMON nginx=$NGINX ($i/30)"
    sleep 5
done
check_eq "nettap-web health" "$WEB" healthy
check_eq "nettap-storage-daemon health" "$DAEMON" healthy
check_eq "nettap-nginx health" "$NGINX" healthy
check_eq "nettap-web runs the image just built" "$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null | cut -c8-19)" "${WEB_BUILT:7:12}"
check_eq "nettap-storage-daemon runs the image just built" "$(sudo docker inspect -f '{{.Image}}' nettap-storage-daemon 2>/dev/null | cut -c8-19)" "${DAEMON_BUILT:7:12}"
echo ""

echo "→ Step 6: Checks through nginx..."
check_eq "/api/health answers" "$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health")" 200
# NET-361: with "http2 on" all tabs share one connection; before that PR lands, HTTP/1.1 is expected
if grep -Eq '^[[:space:]]*http2[[:space:]]+on;' docker/nginx.conf; then WANT_HTTP=2; else WANT_HTTP=1.1; fi
check_eq "the dashboard speaks HTTP/$WANT_HTTP" "$(curl -sk --http2 -o /dev/null --max-time 20 -w '%{http_version}' "$BASE/login")" "$WANT_HTTP"
PING=$(signed_in "$BASE/api/system/ping")
check_eq "signed-in /api/system/ping says ok" "$(printf '%s' "$PING" | grep -o '"status": *"ok"' | head -1 | tr -d ' ')" '"status":"ok"'
for page in / /settings?tab=integrations /infrastructure /iot /investigations /bandwidth /dns /connections /pcap /tools/subnet-calc; do
    check_eq "signed-in GET $page" "$(signed_in -o /dev/null -w '%{http_code}' "$BASE$page")" 200
done
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-nginx"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy finished with failures (✗ above) ==="
    exit 1
fi
