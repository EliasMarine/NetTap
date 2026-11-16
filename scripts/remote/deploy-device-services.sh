#!/usr/bin/env bash
# Deploy PR B (daemon + web): each Devices row gets its commonest protocols (services) and the
# registry's first seen (known_since).
#
# nettap-storage-daemon and nettap-web are rebuilt and recreated. Checks:
#   /api/devices is timed on the old containers and again on the new ones
#   every row of the new /api/devices carries services and known_since, and services is not
#   null on every row (all null means the protocols couldn't be read)
#   the built Devices page is inside the new web container
#   through nginx, with no cookie: /devices -> 302 to /login, /api/health -> 200
# Prints counts, status codes and timings only, never a token or a cookie.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-device-services.sh
# To try a branch before it merges: BRANCH=feature/device-services bash ...
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
# The list's default window is the last 24 h; limit 500 is what the Devices page asks for
DEVICES_URL="http://localhost:8880/api/devices?limit=500"
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

# reply <path> <curl -w format>: one request with no cookie, redirects not followed (-k: self-signed cert)
reply() {
    curl -sk -o /dev/null --max-time 20 -w "$2" "$BASE$1" || true
}

# devices_call: the device list's body, then a last line "<http code> <seconds>".
# The token goes to curl on stdin, so it is never in the output or the process list.
devices_call() {
    local TOKEN
    TOKEN=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null || true)
    if [ -z "$TOKEN" ]; then
        printf '\nno-token -'
        return
    fi
    printf 'X-NetTap-Daemon-Token: %s\n' "$TOKEN" \
        | curl -s --max-time 120 -H @- -w '\n%{http_code} %{time_total}' "$DEVICES_URL" || true
    unset TOKEN
}

# count <regex>: how many times it matches in $BODY (the reply is one line of JSON)
count() {
    printf '%s' "$BODY" | grep -oE "$1" | wc -l | tr -d ' '
}

echo "=== Deploy: protocols and first seen on Devices (PR B) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code at $(git log --oneline -1)"
echo ""

echo "→ Step 2: Time /api/devices on the running (old) containers..."
OUT=$(devices_call)
BEFORE=${OUT##*$'\n'}
echo "   · before: HTTP ${BEFORE% *}, ${BEFORE#* } s"
echo ""

echo "→ Step 3: Rebuild the daemon and web containers..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
BUILD_FAILED=0
for svc in nettap-storage-daemon nettap-web; do
    if "${COMPOSE[@]}" build "$svc"; then rc=0; else rc=1; BUILD_FAILED=1; fi
    check "image built" "$rc" "$svc"
done
if [ "$BUILD_FAILED" -ne 0 ]; then
    echo ""
    echo "=== Stopped: a build failed; the running containers were left as they were ==="
    exit 1
fi
echo ""

echo "→ Step 4: Recreate both containers (the dashboard shows 502 for about 30 s)..."
"${COMPOSE[@]}" up -d --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 5: Wait for both to become healthy..."
WEB_STATUS=unknown
DAEMON_STATUS=unknown
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "both healthy" "$rc" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 6: /api/devices rows carry services and known_since..."
OUT=$(devices_call)
AFTER=${OUT##*$'\n'}
BODY=${OUT%$'\n'*}
CODE=${AFTER% *}
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/devices answers" "$rc" "HTTP $CODE"
# json.dumps writes '": "'; ': ?' matches with or without the space
ROWS=$(count '"ip": ?"')
SERVICES=$(count '"services": ?')
SERVICES_NULL=$(count '"services": ?null')
SERVICES_FILLED=$(count '"services": ?\["')
KNOWN=$(count '"known_since": ?')
KNOWN_SET=$(count '"known_since": ?"')
if [ "$ROWS" -gt 0 ]; then rc=0; else rc=1; fi
check "devices listed" "$rc" "$ROWS rows"
if [ "$SERVICES" -eq "$ROWS" ]; then rc=0; else rc=1; fi
check "every row has services" "$rc" "$SERVICES of $ROWS"
if [ "$ROWS" -gt 0 ] && [ "$SERVICES_NULL" -eq "$ROWS" ]; then
    check "protocols read" 1 "protocols couldn't be read (services null on all $ROWS rows; see the daemon log)"
else
    check "protocols read" 0 "$SERVICES_NULL of $ROWS rows unknown"
fi
if [ "$SERVICES_FILLED" -gt 0 ]; then rc=0; else rc=1; fi
check "rows with protocols" "$rc" "$SERVICES_FILLED of $ROWS"
if [ "$KNOWN" -eq "$ROWS" ]; then rc=0; else rc=1; fi
check "every row has known_since" "$rc" "$KNOWN of $ROWS"
echo "   · rows the registry knows (known_since set): $KNOWN_SET of $ROWS"
echo "   · time: before ${BEFORE#* } s, after ${AFTER#* } s"
unset BODY OUT
echo ""

echo "→ Step 7: The running app carries the Devices page..."
# The page needs a session to render, so the check reads the built Devices page inside the container.
PAGE=$(sudo docker exec nettap-web sh -c 'ls /app/build/server/chunks/entries/pages/devices/_page.svelte.js-*.js 2>/dev/null | grep -v "\.map$" | head -n 1')
if [ -n "$PAGE" ]; then rc=0; else rc=1; fi
check "built Devices page found" "$rc" "${PAGE:-missing}"
if [ -n "$PAGE" ]; then
    # one key per line: esbuild writes a long column object over several lines (NET-316's false ✗)
    for KEY in services known_since; do
        if sudo docker exec nettap-web grep -qE "key: ?\"$KEY\"" "$PAGE"; then rc=0; else rc=1; fi
        check "$KEY column built" "$rc" "$([ "$rc" -eq 0 ] && echo found || echo missing)"
    done
fi
echo ""

echo "→ Step 8: The page answers, without a session, through nginx..."
OUT=$(reply /devices '%{http_code} %{redirect_url}')
case "$OUT" in "302 "*/login*) rc=0 ;; *) rc=1 ;; esac
check "/devices goes to /login" "$rc" "$OUT"
OUT=$(reply /api/health '%{http_code}')
case "$OUT" in 200) rc=0 ;; *) rc=1 ;; esac
check "/api/health answers" "$rc" "$OUT"
echo ""

echo "→ Step 9: Log errors since the restart..."
for c in nettap-storage-daemon nettap-web; do
    echo "   $c:"
    sudo docker logs "$c" --since 5m 2>&1 | grep -iE "error|exception|protocols unavailable" | tail -n 5 || true
done
echo ""

echo "→ Step 10: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-storage-daemon|nettap-web|nettap-nginx"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
echo "Now sign in and open Devices."
exit "$FAILED"
