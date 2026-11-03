#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 52 and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #138: nginx resolved nettap-web once at startup. Batch 51 recreated the web container on a
#     new IP and every page was a 502 until nginx was reloaded. The upstreams now re-resolve
#     through Docker's DNS ("server ... resolve", nginx 1.27.3+, image pinned to 1.30-alpine).
#   The new nginx.conf is tested with the box's certificates before nginx is recreated; then
#   nettap-web is recreated on purpose to show the UI comes back without touching nginx.
#   The UI is unavailable for a few seconds twice (nginx, then web); logins survive.
#
# The full output is also saved to ~/nettap-batch52.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch52.sh
set -u
exec > >(tee "$HOME/nettap-batch52.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_login() {  # wait_login SECONDS: until https://localhost/login answers 200; prints the last code
    local code="000" i
    for i in $(seq 1 "$1"); do
        code=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/login || echo 000)
        [ "$code" = "200" ] && break
        sleep 1
    done
    echo "$code after ${i}s"
}

echo "=== Deploy: dashboard data accuracy, batch 52 (nginx re-resolves its upstreams) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Test the new nginx.conf with the box's certificates (nothing restarted yet)..."
if ! "${COMPOSE[@]}" pull nettap-nginx; then
    echo "   ✗ couldn't pull the pinned nginx image — nothing was changed"
    exit 1
fi
IMAGE=$("${COMPOSE[@]}" config --images 2>/dev/null | grep '^nginx:')
OUT=$(sudo docker run --rm --network none \
    -v "$REPO_DIR/docker/nginx.conf:/etc/nginx/nginx.conf:ro" \
    -v "$REPO_DIR/docker/ssl:/etc/nginx/ssl:ro" "$IMAGE" nginx -t 2>&1)
if printf '%s' "$OUT" | grep -q "test is successful"; then
    check "nginx -t on $IMAGE" 0 "$(sudo docker run --rm "$IMAGE" nginx -v 2>&1)"
else
    check "nginx -t on $IMAGE" 1 "$OUT"
    echo "=== Stopped before touching nginx — paste this output back ==="
    exit 1
fi
echo ""

echo "→ Step 3: Recreate nginx on the pinned image..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-nginx
R=$(wait_login 60)
case "$R" in 200*) rc=0 ;; *) rc=1 ;; esac
check "web UI answers through the new nginx" "$rc" "/login $R"
echo ""

echo "→ Step 4: Recreate nettap-web and don't touch nginx..."
OLD_IP=$(sudo docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' nettap-web)
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
STATUS="unknown"
for _ in $(seq 1 36); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    sleep 5
done
NEW_IP=$(sudo docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' nettap-web)
R=$(wait_login 30)
case "$R" in 200*) rc=0 ;; *) rc=1 ;; esac
check "web UI answers after the web container is recreated (no nginx reload)" "$rc" "/login $R; web $STATUS, IP ${OLD_IP% } -> ${NEW_IP% }"
echo ""

echo "→ Step 5: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 52 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
