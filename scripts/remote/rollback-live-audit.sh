#!/usr/bin/env bash
# Put back the daemon and web images that ran before deploy-live-audit-fixes.sh.
#
# That script tagged them nettap/storage-daemon:rollback-net347 and nettap/web:rollback-net347
# and wrote /home/nettap/.nettap-rollback-net347. This points :latest back at both and
# recreates only those two containers (no build, no other container). The code checkout is
# left as it is: a later build would bring the fixes back.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/rollback-live-audit.sh
set -u

REPO_DIR="/home/nettap/NetTap"
RECORD="/home/nettap/.nettap-rollback-net347"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)

echo "=== Roll back the live-audit fixes ==="
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if [ ! -s "$RECORD" ]; then
    echo "   ✗ $RECORD is missing: there is nothing recorded to go back to"
    exit 1
fi
cat "$RECORD"
for image in nettap/storage-daemon nettap/web; do
    if ! sudo docker tag "$image:rollback-net347" "$image:latest"; then
        echo "   ✗ $image:rollback-net347 is missing — nothing was restarted"
        exit 1
    fi
done
echo "   ✓ :latest points at the recorded images"
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web; then
    echo "   ✗ docker compose up failed"
    exit 1
fi
echo "   ✓ Recreated. Status in 30 s:"
sleep 30
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
