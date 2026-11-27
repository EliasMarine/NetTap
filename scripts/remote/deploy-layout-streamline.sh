#!/usr/bin/env bash
# Deploy the wide-desktop layout streamline (NET-375: phases NET-376…NET-379) as each phase merges.
# Web only: it rebuilds nettap-web, waits for it to be healthy, and checks the touched pages load for a
# signed-in user. The layout itself (card heights, the Live column) is checked from a desktop browser
# with Playwright, since the device has none; see tracking-fixes/2026-11-27-wide-desktop-layout.md.
#
# Before the build it tags the running web image as :rollback-layout-<its image id> (named after the
# image, not the code: the usual command pulls before this script runs). To go back:
#   sudo docker tag nettap/web:rollback-layout-<id> nettap/web:latest
#   sudo docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-web
# Delete old rollback tags once a phase is accepted:
#   sudo docker image rm nettap/web:rollback-layout-<id>
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-layout-streamline.sh
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
MINT="$REPO_DIR/scripts/remote/mint-session.cjs"
PAGES=(/ /live /connections /logs /dns /pcap /alerts /infrastructure /iot /threats /system)
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

check_eq() {  # check_eq LABEL ACTUAL EXPECTED
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2, expected $3"; fi
}

signed_in() {  # signed_in CURL_ARGS...: one curl through nginx with a fresh 60 s session; prints nosession if none
    local session
    # Never printed and never on a command line: printf is a builtin and curl reads the header from stdin
    # shellcheck disable=SC2024  # the user reads the file; only docker needs sudo
    session=$(sudo docker exec -i -w /app nettap-web node - < "$MINT")
    if [ -z "$session" ]; then echo "nosession"; return; fi
    printf 'Cookie: nettap_token=%s\n' "$session" | curl -sk --max-time 30 -H @- "$@"
}

echo "=== Deploy: wide-desktop layout streamline (NET-375, $BRANCH) ==="
echo ""

cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }

echo "→ Step 1: Record the running web image to roll back to..."
running=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
if [ -z "$running" ]; then
    echo "   ✗ Couldn't read the running nettap-web image — nothing was changed"
    exit 1
fi
ROLLBACK="nettap/web:rollback-layout-${running:7:12}"
if sudo docker image inspect "$ROLLBACK" >/dev/null 2>&1; then
    echo "   ✓ $ROLLBACK already tagged"
elif sudo docker tag "$running" "$ROLLBACK"; then
    echo "   ✓ Tagged the running nettap-web image as $ROLLBACK"
else
    echo "   ✗ Couldn't tag the running nettap-web image — nothing was changed"
    exit 1
fi
echo ""

echo "→ Step 2: Update the code..."
if ! git fetch -q origin || ! git checkout -q "$BRANCH" || ! git pull -q origin "$BRANCH"; then
    echo "   ✗ git fetch/checkout/pull failed — nothing was rebuilt"
    exit 1
fi
echo "   ✓ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Build the web container..."
if ! "${COMPOSE[@]}" build -q nettap-web; then
    echo "   ✗ Build failed — the running container was left as it is"
    exit 1
fi
BUILT=$(sudo docker image inspect -f '{{.Id}}' nettap/web:latest 2>/dev/null)
echo "   ✓ Built ${BUILT:7:12}"
echo ""

echo "→ Step 4: Start the new image (recreated only if it changed)..."
if ! "${COMPOSE[@]}" up -d --no-deps nettap-web; then
    echo "   ✗ Starting nettap-web failed: sudo docker logs nettap-web --tail 30"
    exit 1
fi
echo ""

echo "→ Step 5: Wait for nettap-web to become healthy..."
WEB=unknown
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo unknown)
    [ "$WEB" = healthy ] && break
    echo "   waiting... web=$WEB ($i/30)"
    sleep 5
done
check_eq "nettap-web health" "$WEB" healthy
check_eq "nettap-web runs the image just built" "$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)" "$BUILT"
echo ""

echo "→ Step 6: Checks through nginx..."
check_eq "/api/health answers" "$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health")" 200
for page in "${PAGES[@]}"; do
    check_eq "signed-in GET $page" "$(signed_in -o /dev/null -w '%{http_code}' "$BASE$page")" 200
done
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-nginx|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
    echo "Roll back with: sudo docker tag $ROLLBACK nettap/web:latest, then recreate nettap-web (see the header)."
else
    echo "=== Deploy finished with failures (✗ above) ==="
    echo "Roll back with: sudo docker tag $ROLLBACK nettap/web:latest, then recreate nettap-web (see the header)."
    exit 1
fi
