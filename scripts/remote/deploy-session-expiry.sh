#!/usr/bin/env bash
# Deploy NET-198 (a lapsed session sends the user to sign in) and check what the redirect rests on.
#
# Rebuilds only the web container. Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-session-expiry.sh
# To test a branch first: git checkout <branch> && git pull, then BRANCH=<branch> bash …
#
# The redirect itself runs in the browser, so no API call can show it. These checks show the
# parts it depends on; the manual click-through is printed at the end.
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

echo "=== Deploy: session expiry sends you to sign in ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web container..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Image built"
echo ""

echo "→ Step 3: Recreate the web container..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
echo ""

echo "→ Step 4: Wait for it to become healthy..."
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    if [ "$WEB" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB ($i/30)"
    sleep 5
done
expect "nettap-web" "$WEB" healthy
echo ""

echo "→ Step 5: The new browser code is in the image..."
sudo docker exec nettap-web grep -rl "Could not open the sign-in page" /app/build/client > /dev/null 2>&1
check "the shell's sign-in redirect is in the client build" $?
echo ""

echo "→ Step 6: With no session, the ping says \"Sign in first\" (what the redirect matches)..."
# -D - prints the headers, then the body follows
REPLY=$(curl -sk -m 15 -D - https://localhost/api/system/ping)
STATUS=$(printf '%s\n' "$REPLY" | head -n 1 | tr -d '\r' | awk '{ print $2 }')
expect "GET /api/system/ping status" "${STATUS:-none}" 401
printf '%s\n' "$REPLY" | tr -d '\r' | grep -qi '^content-type: application/json'
check "the reply is JSON" $?
BODY=$(printf '%s\n' "$REPLY" | tr -d '\r' | tail -n 1)
expect "the body" "$BODY" '{"error":"Sign in first"}'
echo ""

echo "→ Step 7: The daemon's own 401 reads differently, so it won't send anyone to sign in..."
DAEMON_BODY=$(curl -s -m 15 http://localhost:8880/api/devices)
case "$DAEMON_BODY" in
    *'Sign in first'*) check "the daemon's 401 body" 1 "$DAEMON_BODY" ;;
    *Unauthorized*) check "the daemon's 401 body" 0 "$DAEMON_BODY" ;;
    *) check "the daemon's 401 body" 1 "${DAEMON_BODY:-no reply}" ;;
esac
echo ""

echo "→ Step 8: The sign-in form posts to its own address, so ?next= reaches it..."
FORM=$(curl -sk -m 15 'https://localhost/login?next=%2Fdevices' | grep -o '<form[^>]*>' | head -n 1)
if [ -z "$FORM" ]; then
    check "the sign-in page has a form" 1 "no <form> found"
else
    case "$FORM" in
        *' action='*) check "the form has no action attribute" 1 "$FORM" ;;
        *) check "the form has no action attribute" 0 "$FORM" ;;
    esac
fi
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo ""
echo "To see the redirect (about a minute):"
echo "  1. Sign in at https://<the device> and open the Devices page."
echo "  2. In the browser's developer tools, open Application > Cookies and delete 'nettap_token'."
echo "  3. Within 30 seconds the page goes to the sign-in page, and the address ends ?next=%2Fdevices."
echo "     \"Can't reach NetTap\" should not appear."
echo "  4. Sign in again: you land back on the Devices page and the bell's live updates resume."
