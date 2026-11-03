#!/usr/bin/env bash
# Deploy the Connections and Alerts accuracy fixes (#144–#147) from main. Rebuilds the web UI and the daemon.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #144: connection durations — Malcolm 26.x writes event start/end as epoch-ms text, so
#     Connections and the device page showed "--" on every row, Live reported 0 s, and the
#     Connections drawer read nanoseconds as seconds. They now read `length`.
#   #145: the Connections table sorts and filters by State across every page (it reordered or
#     filtered only the 50 rows on screen), and its Service column shows dns/ssl/http, not udp/tcp.
#   #146: Alerts and alert categories sort every page on the daemon: "most severe first" ranked
#     only the 50 newest alerts, so a range with 368 high alerts showed a medium one on top.
#   #147: a category's alert list holds exactly the alerts its header counts (Exploit listed 99
#     under a 6-alert header), and picking a sub-category really filters the table.
#   The web UI and the daemon are down for under a minute while they restart.
#
# The full output is also saved to ~/nettap-connections-accuracy.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-connections-accuracy.sh
set -u
exec > >(tee "$HOME/nettap-connections-accuracy.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_healthy() {  # wait_healthy CONTAINER
    local status="unknown"
    for _ in $(seq 1 30); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$1" 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && break
        sleep 5
    done
    if [ "$status" = "healthy" ]; then check "$1 health" 0 "$status"; else check "$1 health" 1 "$status"; fi
}

echo "=== Deploy: Connections and Alerts accuracy (#144–#147) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web UI and the daemon..."
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — the running containers were not touched"
    exit 1
fi
echo "   ✓ Built"
echo ""

echo "→ Step 3: Recreate them and wait for health..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo ""

echo "→ Step 4: Connections list sorts and filters every page; durations are real (#144, #145)..."
sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_connection_list.py")" 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 4b: Alert tables sort every page (#146); category lists match their headers (#147)..."
sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_alert_sort.py")" 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 5: A device's connections still sort by every column (#140, shared sort map)..."
sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_connection_sort.py")" 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 7: Logs since the restart..."
for c in nettap-storage-daemon nettap-web; do
    ERRS=$(sudo docker logs "$c" --since 10m 2>&1 | grep -cE "ERROR|Traceback")
    if [ "$ERRS" -eq 0 ]; then rc=0; else rc=1; fi
    check "no errors in the $c log" "$rc" "$ERRS ERROR/Traceback lines"
    [ "$ERRS" -eq 0 ] || sudo docker logs "$c" --since 10m 2>&1 | grep -E "ERROR|Traceback" | tail -5 | sed 's/^/     | /'
done
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== #144–#147 deployed and verified — open Connections and click Duration, then Alerts and click Severity ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
