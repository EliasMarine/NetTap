#!/usr/bin/env bash
# Put back the web image that ran before the first deploy-alert-evidence.sh run (NET-355).
#
# That script recorded the image's ID in /home/nettap/.nettap-rollback-net355. This checks that
# exact image still exists before touching anything, points nettap/web:latest at it, recreates
# only nettap-web (no git pull, no build, no other container), and then confirms the running
# container uses that ID. The code checkout is left as it is: a later build would bring the
# evidence block back.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/rollback-alert-evidence.sh
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
RECORD="${RECORD:-/home/nettap/.nettap-rollback-net355}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)

echo "=== Roll back the alert evidence block (NET-355) ==="
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if [ ! -s "$RECORD" ]; then
    echo "   ✗ $RECORD is missing: there is nothing recorded to go back to"
    exit 1
fi
cat "$RECORD"
WEB_IMAGE=$(sed -n 's/^web=//p' "$RECORD")
if [ -z "$WEB_IMAGE" ] || ! sudo docker image inspect "$WEB_IMAGE" >/dev/null 2>&1; then
    echo "   ✗ The recorded image ${WEB_IMAGE:-(none)} is gone — nothing was changed"
    exit 1
fi
if ! sudo docker tag "$WEB_IMAGE" nettap/web:latest; then
    echo "   ✗ Couldn't point nettap/web:latest at $WEB_IMAGE — nothing was restarted"
    exit 1
fi
echo "   ✓ nettap/web:latest is $WEB_IMAGE"
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web; then
    echo "   ✗ docker compose up failed"
    exit 1
fi
echo "   ✓ Recreated. Waiting for it to become healthy..."
WEB_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$WEB_STATUS" = "healthy" ] && break
    echo "   waiting... web=$WEB_STATUS ($i/30)"
    sleep 5
done
RUNNING=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
if [ "$WEB_STATUS" = "healthy" ] && [ "$RUNNING" = "$WEB_IMAGE" ]; then
    echo "=== Rolled back: nettap-web is healthy on $WEB_IMAGE ==="
    echo "The record is kept. Delete it by hand once the feature is accepted: rm $RECORD"
    exit 0
fi
echo "=== Rollback finished with a problem: health=$WEB_STATUS, running=${RUNNING:-unknown}, wanted=$WEB_IMAGE ==="
echo "The record is kept in $RECORD"
exit 1
