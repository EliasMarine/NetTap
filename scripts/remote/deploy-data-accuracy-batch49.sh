#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 49 and check it, on the Malcolm release the box runs.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #132/#133: filebeat and the api get Valkey's env names; the api's healthcheck uses /mapi/ping.
#   #134: dashboards-helper's idxinit runs on 26.02.0 and 26.10.0 (it went FATAL after a rollback).
#   #135: a Malcolm update's rollback waits for records and PCAP to arrive again.
#   Rebuilds the daemon, recreates dashboards-helper, filebeat and api on the running release,
#   waits for idxinit to finish, then runs the acceptance check.
#
# The full output is also saved to ~/nettap-batch49.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch49.sh
set -u
exec > >(tee "$HOME/nettap-batch49.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

health() {
    sudo docker inspect --format='{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1" 2>/dev/null || echo "missing"
}

wait_up() {  # wait_up CONTAINER...: running and healthy (or running without a healthcheck)
    local c s
    for c in "$@"; do
        s="unknown"
        for _ in $(seq 1 60); do
            s=$(health "$c")
            case "$s" in running/healthy|running/none) break ;; esac
            sleep 5
        done
        case "$s" in
            running/healthy|running/none) echo "   ✓ $c: $s" ;;
            *) echo "   ✗ $c: $s"; FAILED=1 ;;
        esac
    done
}

echo "=== Deploy: dashboard data accuracy, batch 49 (Valkey env, idxinit on both releases, rollback waits) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
TAG=$(sudo grep -h '^MALCOLM_IMAGE_TAG=' docker/.env 2>/dev/null | tail -1 | cut -d= -f2)
echo "   Malcolm release in docker/.env: ${TAG:-unknown}"
echo ""

echo "→ Step 2: Build and recreate the daemon..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon; then
    echo "   ✗ daemon build failed — nothing was restarted"
    exit 1
fi
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
wait_up nettap-storage-daemon
echo ""

echo "→ Step 3: Recreate dashboards-helper, filebeat and api on Malcolm ${TAG:-?}..."
SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
"${COMPOSE[@]}" up -d --no-deps --force-recreate dashboards-helper filebeat api
wait_up nettap-dashboards-helper nettap-filebeat nettap-api
for c in nettap-dashboards-helper nettap-filebeat nettap-api; do
    echo "   $c image: $(sudo docker inspect --format='{{.Config.Image}}' "$c" 2>/dev/null)"
done
echo ""

echo "→ Step 4: idxinit finishes (it sleeps 180 s first)..."
STATE="unknown"
for i in $(seq 1 60); do
    STATE=$(sudo docker exec nettap-dashboards-helper supervisorctl -c /etc/supervisord.conf status idxinit 2>&1 | awk '{print $2}')
    case "$STATE" in RUNNING|STARTING) ;; *) break ;; esac
    [ $((i % 6)) -eq 0 ] && echo "   still $STATE ($((i * 10)) s)"
    sleep 10
done
LOG=$(sudo docker logs --since "$SINCE" nettap-dashboards-helper 2>&1)
if [ "$STATE" = "EXITED" ] && ! printf '%s' "$LOG" | grep -q "Traceback"; then
    echo "   ✓ idxinit EXITED, no Python traceback in the helper's log"
else
    echo "   ✗ idxinit: $STATE$(printf '%s' "$LOG" | grep -q Traceback && echo ', traceback in the log')"
    FAILED=1
fi
printf '%s\n' "$LOG" | grep -v '^\s*$' | tail -8 | sed 's/^/     | /'
echo ""

echo "→ Step 5: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 49 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
