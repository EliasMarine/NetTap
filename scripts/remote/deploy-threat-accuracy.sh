#!/usr/bin/env bash
# Deploy NET-209: threat and risk scores count only real threats; internet addresses are never devices.
#
# Rebuilds and recreates nettap-storage-daemon and nettap-web. Before the rebuild it records the
# old figures from the running daemon, so the end of the run shows them next to the new ones.
# Checks (scripts/remote/verify_threat_accuracy.py, run inside the daemon container):
#   /api/devices/91.92.40.12 and /api/risk/scores/91.92.40.12 -> 404
#   the 24 h and 7 d threat summaries answer; every kill chain is a LAN device
#   every device's risk score has the three factors (alerts, connection anomaly, upload spike)
#   the 7-day history ranges match independent searches for the two busiest devices
#   web: the built app carries the new score explanation; /threats -> /login without a session
# Reads only. The daemon token is read inside the container and never printed.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-threat-accuracy.sh
# To try a branch before it merges: BRANCH=fix/threat-score-accuracy bash ...
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
VERIFY="scripts/remote/verify_threat_accuracy.py"
BEFORE_IN_CONTAINER="/tmp/nettap-threat-before.json"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: accurate threat and risk scores (NET-209) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code at $(git log --oneline -1)"
echo ""

echo "→ Step 2: Record the current figures (old daemon)..."
# shellcheck disable=SC2024  # the files are ours; only the container side needs root
if sudo docker exec -i nettap-storage-daemon python3 - snapshot < "$VERIFY" > "$WORK/before.json" 2> "$WORK/before.err"; then
    check "old figures recorded" 0 "$(wc -c < "$WORK/before.json" | tr -d ' ') bytes"
else
    echo '{}' > "$WORK/before.json"
    check "old figures recorded" 0 "skipped ($(tail -n 1 "$WORK/before.err")); the table will show None"
fi
echo ""

echo "→ Step 3: Rebuild the daemon and web containers..."
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
check "containers healthy" "$rc" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 6: The new scores on this network (reads only; can take a minute)..."
# shellcheck disable=SC2024  # the file is ours; only the container side needs root
sudo docker exec -i nettap-storage-daemon sh -c "cat > $BEFORE_IN_CONTAINER" < "$WORK/before.json"
# shellcheck disable=SC2024
if sudo docker exec -i nettap-storage-daemon python3 - check "$BEFORE_IN_CONTAINER" < "$VERIFY"; then rc=0; else rc=1; fi
check "score checks" "$rc" "$([ "$rc" -eq 0 ] && echo "all passed" || echo "see ✗ above")"
echo ""

echo "→ Step 7: The running web app and its pages..."
if sudo docker exec nettap-web grep -rqF -- "An attempt from the internet against a device adds at most 0.5" /app/build; then rc=0; else rc=1; fi
check "built app has the new score explanation" "$rc" "$([ "$rc" -eq 0 ] && echo found || echo missing)"
OUT=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code} %{redirect_url}' "https://localhost/threats" || true)
case "$OUT" in "302 "*/login) rc=0 ;; *) rc=1 ;; esac
check "/threats goes to /login" "$rc" "$OUT"
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
echo "Open Threats: the score now counts each problem once per device, and attempts from the internet barely move it."
exit "$FAILED"
