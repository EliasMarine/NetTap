#!/usr/bin/env bash
# Deploy the fixes from the 23 Nov 2026 exploratory browser QA (NET-361 to NET-373) as their PRs merge.
# Safe to run after each merge: it rebuilds nettap-web and nettap-storage-daemon (compose recreates a
# container only when its image changed). It recreates nettap-nginx when its nginx.conf OR its image
# changed, and only after `nginx -t` passes on the new image in a one-off container (a single-file bind
# mount keeps the old file after a git pull, so a reload is not enough).
# NET-361: a plain restart (reboot, docker restart, crash loop) re-reads the bind-mounted nginx.conf, so the
# new conf must never sit on disk beside the old cached image: the pinned nginx image is pulled before the
# code is updated, and nginx is done right after the update, before the web and daemon builds.
#
# Before the first build it tags the running web and daemon images as :rollback-qa-1124 (kept on later
# runs). To go back, tag one over :latest and recreate it, e.g.
#   sudo docker tag nettap/web:rollback-qa-1124 nettap/web:latest
#   sudo docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-web
# Roll nginx back with its conf and image TOGETHER, never the image alone (nginx:1.30-alpine is still cached):
#   git checkout <prev-sha> -- docker/nginx.conf docker/docker-compose.yml
#   sudo docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-nginx
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

echo "→ Step 2: Pull the pinned nginx image, then update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# OLD CODE START — NET-361 (security review): the new nginx.conf landed before the pinned image was pulled
# if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
#     echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
#     exit 1
# fi
# OLD CODE END
if ! git fetch origin; then
    echo "   ✗ Could not fetch origin — nothing was changed"
    exit 1
fi
# The image the incoming compose file pins, pulled while the old nginx.conf is still on disk
NGINX_IMAGE=$(git show "origin/$BRANCH:docker/docker-compose.yml" | grep -E '^[[:space:]]+image:[[:space:]]+nginx:' | head -1 | awk '{print $2}')
if [ -z "$NGINX_IMAGE" ] || ! sudo docker pull -q "$NGINX_IMAGE" >/dev/null; then
    echo "   ✗ Couldn't pull ${NGINX_IMAGE:-the nginx image} — nothing was changed"
    exit 1
fi
echo "   ✓ Pulled $NGINX_IMAGE"
if ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Bring nginx to this nginx.conf and image (tested first)..."
# OLD CODE START — NET-361: nginx was recreated only for a changed nginx.conf, untested, and the pinned image
# change (1.30.8) went unnoticed
# if sudo docker exec nettap-nginx cat /etc/nginx/nginx.conf 2>/dev/null | cmp -s - docker/nginx.conf; then
#     echo "   ✓ nginx already has this nginx.conf — not touched"
# else
#     echo "   nginx.conf changed — recreating nettap-nginx (the dashboard drops for a few seconds)"
#     if "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-nginx; then …
# OLD CODE END
# OLD CODE: NGINX_IMAGE=$(grep -E '^[[:space:]]+image:[[:space:]]+nginx:' docker/docker-compose.yml | head -1 | awk '{print $2}') (NET-361 security review: read from origin/$BRANCH and pulled in Step 2, before the code update)
if sudo docker exec nettap-nginx cat /etc/nginx/nginx.conf 2>/dev/null | cmp -s - docker/nginx.conf \
    && [ "$(sudo docker inspect -f '{{.Config.Image}}' nettap-nginx 2>/dev/null)" = "$NGINX_IMAGE" ]; then
    echo "   ✓ nginx already runs $NGINX_IMAGE with this nginx.conf — not touched"
# A one-off container tests the new conf on the new image before the live one is replaced
elif ! "${COMPOSE[@]}" run --rm --no-deps --entrypoint nginx nettap-nginx -t; then
    # OLD CODE: echo "   ✗ nginx -t rejected the new nginx.conf on $NGINX_IMAGE — the running nginx was left as it is"; FAILED=1 (NET-361 security review: stop before the build)
    echo "   ✗ nginx -t rejected docker/nginx.conf on $NGINX_IMAGE — the running nginx was left as it is. Don't restart nettap-nginx or reboot until nginx.conf is fixed"
    exit 1
else
    echo "   nginx.conf or image changed — recreating nettap-nginx on $NGINX_IMAGE (the dashboard drops for a few seconds)"
    if "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-nginx; then
        echo "   ✓ nettap-nginx recreated"
    else
        # OLD CODE: echo "   ✗ Recreating nettap-nginx failed: sudo docker logs nettap-nginx --tail 30"; FAILED=1 (NET-361 security review: an old container left behind would pair the new conf with the old image on a restart)
        echo "   ✗ Recreating nettap-nginx failed: sudo docker logs nettap-nginx --tail 30. Don't reboot until nettap-nginx runs $NGINX_IMAGE"
        exit 1
    fi
fi
echo ""

echo "→ Step 4: Build the web and daemon containers..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
WEB_BUILT=$(image_id nettap/web:latest)
DAEMON_BUILT=$(image_id nettap/storage-daemon:latest)
echo "   ✓ Built web ${WEB_BUILT:7:12}, daemon ${DAEMON_BUILT:7:12}"
echo ""

echo "→ Step 5: Start the new images (a container is recreated only if its image changed)..."
if ! "${COMPOSE[@]}" up -d --no-deps nettap-web nettap-storage-daemon; then
    echo "   ✗ docker compose up failed — see the rollback lines at the top of this script"
    exit 1
fi
echo "   ✓ Up"
# NET-361 (security review): the nginx step moved to Step 3, before the build
echo ""

echo "→ Step 6: Wait for the containers to become healthy..."
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

echo "→ Step 7: Checks through nginx..."
check_eq "/api/health answers" "$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health")" 200
# NET-361: with "http2 on" all tabs share one connection; before that PR lands, HTTP/1.1 is expected
if grep -Eq '^[[:space:]]*http2[[:space:]]+on;' docker/nginx.conf; then WANT_HTTP=2; else WANT_HTTP=1.1; fi
check_eq "the dashboard speaks HTTP/$WANT_HTTP" "$(curl -sk --http2 -o /dev/null --max-time 20 -w '%{http_version}' "$BASE/login")" "$WANT_HTTP"
# NET-361: 1.30.7+ carries the 2026 HTTP/2 and TLS fixes; the running binary must be the pinned one
WANT_NGINX=$(printf '%s' "$NGINX_IMAGE" | sed -E 's/^nginx:([0-9.]+).*/\1/')
check_eq "nginx runs the pinned version" "$(sudo docker exec nettap-nginx nginx -v 2>&1 | sed -E 's|.*nginx/||')" "$WANT_NGINX"
PING=$(signed_in "$BASE/api/system/ping")
check_eq "signed-in /api/system/ping says ok" "$(printf '%s' "$PING" | grep -o '"status": *"ok"' | head -1 | tr -d ' ')" '"status":"ok"'
for page in / /settings?tab=integrations /infrastructure /iot /investigations /bandwidth /dns /connections /pcap /tools/subnet-calc; do
    check_eq "signed-in GET $page" "$(signed_in -o /dev/null -w '%{http_code}' "$BASE$page")" 200
done
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-nginx"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy finished with failures (✗ above) ==="
    exit 1
fi
