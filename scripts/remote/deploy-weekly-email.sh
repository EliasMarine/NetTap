#!/usr/bin/env bash
# Deploy NET-381 (the branded HTML weekly report email) and check it on the box:
#   - the logo ships in the daemon image;
#   - inside the daemon container, a synthetic report composes to text + HTML + logo through the
#     sender's own composer, and the newest stored report composes too (tree and size only);
#   - the Settings card's copy no longer says "plain-text email".
# It sends no email and writes no report data: the composer has no route to SMTP. The first real
# email comes from the schedule at its next hour. Rebuilds and recreates only
# nettap-storage-daemon and nettap-web; rollback-weekly-email.sh puts the recorded images back.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-weekly-email.sh
# To try a branch before it merges: BRANCH=feature/weekly-email-html bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
RECORD="/home/nettap/.nettap-rollback-net381"
TAG="rollback-net381"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
SERVICES=(nettap-storage-daemon nettap-web)
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

echo "=== Deploy: branded weekly report email, NET-381 ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
TARGET=$(git rev-parse HEAD)
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Record the running images for a rollback..."
if [ -s "$RECORD" ]; then
    REC_DAEMON=$(sed -n 's/^daemon=//p' "$RECORD")
    REC_WEB=$(sed -n 's/^web=//p' "$RECORD")
    TAG_DAEMON=$(sudo docker image inspect -f '{{.Id}}' "nettap/storage-daemon:$TAG" 2>/dev/null)
    TAG_WEB=$(sudo docker image inspect -f '{{.Id}}' "nettap/web:$TAG" 2>/dev/null)
    if [ "$TAG_DAEMON" != "$REC_DAEMON" ] || [ "$TAG_WEB" != "$REC_WEB" ]; then
        echo "   ✗ The :$TAG tags no longer point at the images in $RECORD — nothing was changed"
        exit 1
    fi
    echo "   ✓ Keeping the existing record in $RECORD (tags still match)"
else
    DAEMON_IMAGE=$(sudo docker inspect -f '{{.Image}}' nettap-storage-daemon 2>/dev/null)
    WEB_IMAGE=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
    if [ -z "$DAEMON_IMAGE" ] || [ -z "$WEB_IMAGE" ]; then
        echo "   ✗ Couldn't read the running images — nothing was changed"
        exit 1
    fi
    if ! sudo docker tag "$DAEMON_IMAGE" "nettap/storage-daemon:$TAG" \
        || ! sudo docker tag "$WEB_IMAGE" "nettap/web:$TAG"; then
        echo "   ✗ Couldn't tag the running images — nothing was changed"
        exit 1
    fi
    printf 'target=%s\ndaemon=%s\nweb=%s\nrecorded=%s\n' "$TARGET" "$DAEMON_IMAGE" "$WEB_IMAGE" "$(date -u +%FT%TZ)" > "$RECORD"
    echo "   ✓ Tagged both as :$TAG and wrote $RECORD"
fi
echo ""

echo "→ Step 3: Build and recreate the daemon and web..."
if ! "${COMPOSE[@]}" build "${SERVICES[@]}"; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate "${SERVICES[@]}"; then
    echo "   ✗ docker compose up failed"
    exit 1
fi
WEB_STATUS="unknown"; DAEMON_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
check "Both containers healthy" "$([ "$WEB_STATUS" = healthy ] && [ "$DAEMON_STATUS" = healthy ] && echo 0 || echo 1)" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 4: The logo ships in the daemon image..."
sudo docker exec nettap-storage-daemon test -s /opt/nettap/daemon/assets/report-logo.png
check "assets/report-logo.png present" "$?"
echo ""

echo "→ Step 5: Compose the email inside the daemon (sends nothing)..."
# shellcheck disable=SC2024  # the repo file is ours to read; only docker needs sudo
sudo docker exec -i nettap-storage-daemon python3 - < scripts/remote/report-email-preview.py 2>/dev/null | sed 's/^/   /'
check "Synthetic report keeps its HTML part and logo" "${PIPESTATUS[0]}"
echo ""

echo "→ Step 6: The Settings card's copy..."
if sudo docker exec nettap-web grep -rqs "by email to these addresses" /app/build; then
    check "Settings says \"by email to these addresses\"" 0
else
    check "Settings says \"by email to these addresses\"" 1 "not found in /app/build"
fi
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -ne 0 ]; then
    echo "=== Deploy finished with failures (✗ above): stop and review. Roll back with: bash scripts/remote/rollback-weekly-email.sh ==="
    exit 1
fi
echo "=== Deploy complete: every check passed. The next scheduled weekly report arrives as the branded email. ==="
