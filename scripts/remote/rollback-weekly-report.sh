#!/usr/bin/env bash
# Put back the daemon and web images that ran before deploy-weekly-report.sh (NET-340).
#
# That script tagged them :rollback-net340 and recorded their IDs in
# /home/nettap/.nettap-rollback-net340. This checks both tags still point at the recorded IDs
# before touching anything, points :latest at them, recreates only nettap-storage-daemon and
# nettap-web (no build), and then confirms the running containers use those IDs.
#
# The old daemon reads report_schedules.json unchanged, ignores report_schedule_meta.json and the
# reports directory, and sends nothing. The code checkout is left as it is: a later build would
# bring the weekly report back.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/rollback-weekly-report.sh
set -u

REPO_DIR="/home/nettap/NetTap"
RECORD="/home/nettap/.nettap-rollback-net340"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)

echo "=== Roll back the weekly report (NET-340) ==="
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if [ ! -s "$RECORD" ]; then
    echo "   ✗ $RECORD is missing: there is nothing recorded to go back to"
    exit 1
fi
cat "$RECORD"
DAEMON_IMAGE=$(sed -n 's/^daemon=//p' "$RECORD")
WEB_IMAGE=$(sed -n 's/^web=//p' "$RECORD")
TAG_DAEMON=$(sudo docker image inspect -f '{{.Id}}' nettap/storage-daemon:rollback-net340 2>/dev/null)
TAG_WEB=$(sudo docker image inspect -f '{{.Id}}' nettap/web:rollback-net340 2>/dev/null)
if [ -z "$DAEMON_IMAGE" ] || [ -z "$WEB_IMAGE" ] || [ "$TAG_DAEMON" != "$DAEMON_IMAGE" ] || [ "$TAG_WEB" != "$WEB_IMAGE" ]; then
    echo "   ✗ The :rollback-net340 tags don't point at the recorded images — nothing was changed"
    echo "     daemon: tag=${TAG_DAEMON:-(none)} recorded=${DAEMON_IMAGE:-(none)}"
    echo "     web:    tag=${TAG_WEB:-(none)} recorded=${WEB_IMAGE:-(none)}"
    exit 1
fi
if ! sudo docker tag "$DAEMON_IMAGE" nettap/storage-daemon:latest || ! sudo docker tag "$WEB_IMAGE" nettap/web:latest; then
    echo "   ✗ Couldn't point :latest at the recorded images — nothing was restarted"
    exit 1
fi
echo "   ✓ nettap/storage-daemon:latest is $DAEMON_IMAGE"
echo "   ✓ nettap/web:latest is $WEB_IMAGE"
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web; then
    echo "   ✗ docker compose up failed"
    exit 1
fi
echo "   ✓ Recreated. Waiting for both to become healthy..."
WEB_STATUS="unknown"; DAEMON_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
RUN_DAEMON=$(sudo docker inspect -f '{{.Image}}' nettap-storage-daemon 2>/dev/null)
RUN_WEB=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ] && [ "$RUN_DAEMON" = "$DAEMON_IMAGE" ] && [ "$RUN_WEB" = "$WEB_IMAGE" ]; then
    echo "=== Rolled back: both containers are healthy on the recorded images ==="
    exit 0
fi
echo "=== Rollback finished with a problem: daemon=$DAEMON_STATUS on ${RUN_DAEMON:-unknown}, web=$WEB_STATUS on ${RUN_WEB:-unknown} ==="
exit 1
