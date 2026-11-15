#!/usr/bin/env bash
# Deploy NET-286: count charts get whole-number y-axis ticks, so a small peak on /pcap reads
# "0, 1" instead of "0, 0, 0, 1, 1, 1". Web only: rebuilds and recreates nettap-web, nothing else.
#
# The axis needs a signed-in page with real counts to see, so the box checks that the new build is
# live and the pages load; the axis itself is covered by CI (Vitest and the visual suite).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-chart-ticks-net286.sh
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

echo "=== Deploy: whole-number ticks on count charts (NET-286, $BRANCH) ==="
echo ""

echo "→ Step 1: Update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web container..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
OLD_IMAGE=$(sudo docker inspect --format='{{.Image}}' nettap-web 2>/dev/null || echo none)
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Image built"
echo ""

echo "→ Step 3: Recreate the web container (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
echo ""

echo "→ Step 4: Wait for it to become healthy..."
WEB="unknown"
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$WEB" = "healthy" ] && break
    echo "   waiting... web=$WEB ($i/30)"
    sleep 5
done
if [ "$WEB" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$WEB"
NEW_IMAGE=$(sudo docker inspect --format='{{.Image}}' nettap-web 2>/dev/null || echo none)
if [ "$NEW_IMAGE" != "$OLD_IMAGE" ] && [ "$NEW_IMAGE" != "none" ]; then rc=0; else rc=1; fi
check "nettap-web runs the new image" "$rc" "${NEW_IMAGE:7:12}"
echo ""

echo "→ Step 5: The chart pages still load..."
CODE=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health" || true)
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/health answers" "$rc" "$CODE"
for path in "/pcap" "/"; do
    LOC=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code} %{redirect_url}' "$BASE$path" || true)
    case "$LOC" in "302 "*"/login"*) rc=0 ;; *) rc=1 ;; esac
    check "$path signed out goes to /login" "$rc" "$LOC"
done
echo "   To see it: sign in and open /pcap over a range with only a few captures; the y-axis reads 0, 1 (no repeated labels)."
echo ""

echo "→ Step 6: Log errors since the restart..."
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
