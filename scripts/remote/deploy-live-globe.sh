#!/usr/bin/env bash
# Deploy NET-207: the Live monitor's 3D globe, the network location in Settings, and inbound rows
# located at their remote end.
#
# Rebuilds and recreates nettap-storage-daemon and nettap-web. Checks:
#   both containers healthy
#   daemon: GET /api/settings/home-location answers {"home": …}; a bad latitude is refused (400);
#           /api/live/dashboard rows carry geo_ip; the detail route refuses a geo= that is neither end
#   web: the built app carries the globe card and the location card; /live and /settings -> /login
# Never saves or clears the location, and never calls the outside WAN look-up (that is the owner's button).
# The daemon token is read into a variable and never printed.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-live-globe.sh
# To try a branch before it merges: BRANCH=feature/live-globe bash ...
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
DAEMON="http://localhost:8880"
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

# reply <path> <curl -w format>: one request through nginx with no cookie (-k: self-signed cert)
reply() {
    curl -sk -o /dev/null --max-time 20 -w "$2" "$BASE$1" || true
}

echo "=== Deploy: the Live globe (NET-207) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code at $(git log --oneline -1)"
echo ""

echo "→ Step 2: Rebuild the daemon and web containers..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
for svc in nettap-storage-daemon nettap-web; do
    if "${COMPOSE[@]}" build "$svc"; then rc=0; else rc=1; fi
    check "image built" "$rc" "$svc"
    if [ "$rc" -ne 0 ]; then
        echo ""
        echo "=== Stopped: the $svc build failed; the running containers were left as they were ==="
        exit 1
    fi
done
echo ""

echo "→ Step 3: Recreate both containers (the dashboard shows 502 for about 30 s)..."
"${COMPOSE[@]}" up -d --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for both to become healthy..."
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
check "containers healthy" "$rc" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 5: The daemon's new routes..."
TOKEN=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null || true)
if [ -z "$TOKEN" ]; then
    check "daemon token readable" 1 "empty"
else
    api() {  # api <method> <path> [body]: prints "<status> <body>"
        if [ $# -ge 3 ]; then
            # OLD CODE (NET-237: the token was on the command line, visible in ps): curl ... -H "X-NetTap-Daemon-Token: $TOKEN" ...
            printf 'X-NetTap-Daemon-Token: %s\n' "$TOKEN" | curl -s --max-time 30 -X "$1" -H @- -H "Content-Type: application/json" \
                -d "$3" -w ' %{http_code}' "$DAEMON$2" || true
        else
            printf 'X-NetTap-Daemon-Token: %s\n' "$TOKEN" | curl -s --max-time 30 -X "$1" -H @- -w ' %{http_code}' "$DAEMON$2" || true
        fi
    }

    OUT=$(api GET /api/settings/home-location)
    case "$OUT" in *'"home": null'*" 200"|*'"home":null'*" 200") rc=0; HOME_STATE="not set yet" ;;
                   *'"home"'*'"lat"'*" 200") rc=0; HOME_STATE="set" ;;
                   *) rc=1; HOME_STATE="HTTP ${OUT##* }" ;; esac
    check "GET /api/settings/home-location" "$rc" "$HOME_STATE"

    OUT=$(api PUT /api/settings/home-location '{"lat": 95, "lon": 0, "label": "deploy check"}')
    case "$OUT" in *" 400") rc=0 ;; *) rc=1 ;; esac
    check "a latitude of 95 is refused" "$rc" "HTTP ${OUT##* }"

    OUT=$(api GET "/api/live/dashboard?limit=20")
    case "$OUT" in *'"geo_ip"'*" 200") rc=0; DETAIL="rows carry geo_ip" ;;
                   *'"connections": []'*" 200"|*'"connections":[]'*" 200") rc=0; DETAIL="no rows right now (nothing to check)" ;;
                   *) rc=1; DETAIL="HTTP ${OUT##* }, no geo_ip" ;; esac
    check "/api/live/dashboard" "$rc" "$DETAIL"
    INBOUND=$(printf '%s' "$OUT" | grep -o '"direction": *"in"' | wc -l | tr -d ' ')
    echo "   inbound rows in the newest 20: $INBOUND"

    OUT=$(api GET "/api/live/connection/detail?src=192.0.2.1&dst=192.0.2.2&geo=192.0.2.3")
    case "$OUT" in *" 400") rc=0 ;; *) rc=1 ;; esac
    check "detail refuses a geo= that is neither end" "$rc" "HTTP ${OUT##* }"
    unset TOKEN
fi
echo ""

echo "→ Step 6: The running web app carries the globe and the location card..."
for target in "Where your traffic goes" "Network location" "Use my WAN location"; do
    if sudo docker exec nettap-web grep -rqF -- "$target" /app/build; then rc=0; else rc=1; fi
    check "built app has \"$target\"" "$rc" "$([ "$rc" -eq 0 ] && echo found || echo missing)"
done
echo ""

echo "→ Step 7: The pages answer, without a session, through nginx..."
for path in /live /settings; do
    OUT=$(reply "$path" '%{http_code} %{redirect_url}')
    case "$OUT" in "302 "*/login) rc=0 ;; *) rc=1 ;; esac
    check "$path goes to /login" "$rc" "$OUT"
done
OUT=$(reply /api/health '%{http_code}')
case "$OUT" in 200) rc=0 ;; *) rc=1 ;; esac
check "/api/health answers" "$rc" "$OUT"
echo ""

echo "→ Step 8: Errors since the restart..."
for c in nettap-storage-daemon nettap-web; do
    echo "   $c:"
    sudo docker logs "$c" --since 5m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
done
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-nginx"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
echo "Next: Settings › Network › Network location: press \"Use my WAN location\" (or type it), then Save."
echo "Then open Live monitor: the globe flies packets from your network. Settings › Display › Live map switches to the flat map."
exit "$FAILED"
