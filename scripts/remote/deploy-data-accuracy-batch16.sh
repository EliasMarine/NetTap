#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 16 (Grafana off, retention tier labels) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #71 Grafana: off by default (--profile grafana); nginx keeps /grafana/ and starts without it
#   #70 Settings / setup: Suricata alerts follow the Hot tier (browser pass)
#
# nginx is the front door, so its new config is tested in a one-off container first; if that
# fails nothing is restarted. The web and nginx restart; Grafana's container is removed (its
# volume is kept). Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch16.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_healthy() {
    local name="$1" status="unknown"
    for i in $(seq 1 36); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && break
        [ $((i % 6)) -eq 0 ] && echo "   waiting... $name=$status ($i/36)"
        sleep 5
    done
    if [ "$status" = "healthy" ]; then rc=0; else rc=1; fi
    check "$name health" "$rc" "$status"
}

echo "=== Deploy: dashboard data accuracy, batch 16 (Grafana off, retention tiers) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
PULLED=1
for attempt in 1 2 3 4 5; do
    if git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; then PULLED=0; break; fi
    echo "   pull failed (attempt $attempt/5), retrying in 5 s..."
    sleep 5
done
if [ "$PULLED" -ne 0 ]; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Test the new nginx config in a one-off container..."
if ! NGINX_TEST=$("${COMPOSE[@]}" run --rm --no-deps --entrypoint nginx nettap-nginx -t 2>&1); then
    echo "$NGINX_TEST" | tail -5 | sed 's/^/   /'
    echo "   ✗ nginx -t failed — nothing was restarted"
    exit 1
fi
echo "   ✓ nginx -t: $(echo "$NGINX_TEST" | grep -o 'test is successful' || echo ok)"
echo ""

echo "→ Step 3: Build the web image..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Image built"
echo ""

echo "→ Step 4: Recreate the web and nginx, remove Grafana's container..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web nettap-nginx
sudo docker rm -f nettap-grafana >/dev/null 2>&1 || true
wait_healthy nettap-web
wait_healthy nettap-nginx
echo ""

echo "→ Step 5: Checks..."
if sudo docker ps -a --format '{{.Names}}' | grep -qx nettap-grafana; then rc=1; else rc=0; fi
check "#71 Grafana container is gone" "$rc" "$(sudo docker ps -a --format '{{.Names}}' | grep -c '^nettap-grafana$') container(s)"
if "${COMPOSE[@]}" config --services 2>/dev/null | grep -qx nettap-grafana; then rc=1; else rc=0; fi
check "#71 a plain 'up' no longer starts Grafana" "$rc" "nettap-grafana $( [ "$rc" -eq 0 ] && echo 'not' ) in the default services"
if sudo docker volume ls --format '{{.Name}}' | grep -q 'grafana-data$'; then rc=0; else rc=1; fi
check "#71 Grafana's volume is kept" "$rc" "$(sudo docker volume ls --format '{{.Name}}' | grep 'grafana-data$' || echo none)"
CODE=$(sudo docker exec nettap-nginx sh -c 'wget -q -S -O /dev/null --no-check-certificate https://localhost/login 2>&1 | grep -m1 "HTTP/" | tr -d "\r"' 2>/dev/null)
case "$CODE" in *200*) rc=0 ;; *) rc=1 ;; esac
check "#71 nginx serves the UI without Grafana" "$rc" "/login → ${CODE:-no answer}"
NGINX_ERRORS=$(sudo docker logs --since 5m nettap-nginx 2>&1 | grep -c -E '\[emerg\]|host not found' || true)
if [ "$NGINX_ERRORS" -eq 0 ]; then rc=0; else rc=1; fi
check "#71 nginx started cleanly" "$rc" "$NGINX_ERRORS emerg / host-not-found lines"
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-nginx|grafana"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 16 deployed and verified ==="
    echo "To try Grafana anyway: sudo docker compose -f docker/docker-compose.yml --profile grafana up -d nettap-grafana"
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
