#!/usr/bin/env bash
# Put back the web image that ran before the first deploy-change-password.sh run (NET-357 + NET-358).
#
# That script recorded the image's ID in /home/nettap/.nettap-rollback-net358. This checks that exact
# image still exists before touching anything, points nettap/web:latest at it, recreates only
# nettap-web (no git pull, no build, no other container), and then confirms the running container
# uses that ID. The code checkout is left as it is: a later build would bring the feature back.
#
# No key handling is needed (plan step 10): every start of the new release replaced jwt-secret.txt,
# the only key the older build reads, so no session from before this rollback works there, including
# any a password change revoked. Everyone signs in again. Passwords changed in the new release stay.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/rollback-change-password.sh
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
RECORD="${RECORD:-/home/nettap/.nettap-rollback-net358}"  # deploy-change-password.sh also tags it nettap/web:rollback-net358
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)

echo "=== Roll back change password and the signed-out pages (NET-357 + NET-358) ==="
echo ""

echo "→ Step 1: Check the recorded image..."
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
echo "   ✓ The recorded image ${WEB_IMAGE:7:12} exists"
echo ""

echo "→ Step 2: Point nettap/web:latest at it and recreate nettap-web..."
if ! sudo docker tag "$WEB_IMAGE" nettap/web:latest; then
    echo "   ✗ Couldn't point nettap/web:latest at $WEB_IMAGE — nothing was restarted"
    exit 1
fi
echo "   ✓ nettap/web:latest is ${WEB_IMAGE:7:12}"
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web; then
    echo "   ✗ docker compose up failed"
    exit 1
fi
echo "   ✓ Recreated"
echo ""

echo "→ Step 3: Wait for it to become healthy..."
WEB_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$WEB_STATUS" = "healthy" ] && break
    echo "   waiting... web=$WEB_STATUS ($i/30)"
    sleep 5
done
RUNNING=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
echo ""

echo "→ Step 4: The restored container's key setting..."
# Names only: the value is never printed.
if sudo docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' nettap-web 2>/dev/null | grep -q '^JWT_SECRET='; then
    echo "   Warning: the restored nettap-web has JWT_SECRET set. This older NetTap signs with it and trusts"
    echo "   every session signed with that value, including any a password change revoked. Give JWT_SECRET"
    echo "   a fresh value that was never used before (in the file that sets it for the web container), then run:"
    echo "     cd $REPO_DIR"
    echo "     sudo docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-web"
else
    echo "   ✓ No JWT_SECRET: it signs with jwt-secret.txt, which the new release replaced at its last start"
fi
echo ""

echo "Everyone signs in again: sessions from the newer release don't work on this one."
echo "Don't roll back past March 2026 (aa234d73): those builds sign sessions with a public key."
echo ""
if [ "$WEB_STATUS" = "healthy" ] && [ "$RUNNING" = "$WEB_IMAGE" ]; then
    echo "=== Rolled back: nettap-web is healthy on ${WEB_IMAGE:7:12} ==="
    echo "The record is kept. Delete it by hand once the feature is accepted: rm $RECORD"
    exit 0
fi
echo "=== Rollback finished with a problem: health=$WEB_STATUS, running=${RUNNING:-unknown}, wanted=$WEB_IMAGE ==="
echo "The record is kept in $RECORD"
exit 1
