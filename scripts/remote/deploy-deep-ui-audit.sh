#!/usr/bin/env bash
# Deploy the deep UI audit fixes (NET-349) and check the served build carries them.
#
# Web only: rebuilds and recreates nettap-web alone (--no-deps; the daemon, OpenSearch and
# capture are not touched). Before the recreate it tags the web image running now as
# nettap/web:rollback-net349 and records its ID in $RECORD, so rollback-deep-ui-audit.sh can put
# that exact image back. An existing record is kept: a rerun must not replace the image to go
# back to with the new one.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-deep-ui-audit.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
RECORD="/home/nettap/.nettap-rollback-net349"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
# Text each fix adds to the client build: the DNS name row, the backup card, the quiet-window
# notice, the packet estimate's age (the drawer and phone header are checked by the visual suite)
STRINGS=(
    "DNS name"
    "the settings listed below"
    "No connections recorded for this address"
    "This estimate is from when the page last loaded its list of capture files"
)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

web_status() {  # HTTP status of a path on the web server, fetched inside its container
    sudo docker exec -e P="$1" nettap-web node -e '
        fetch("http://localhost:3000" + process.env.P, { redirect: "manual" })
            .then((r) => console.log(r.status)).catch(() => console.log("000"));' 2>/dev/null
}

echo "=== Deploy: deep UI audit fixes, NET-349 ($BRANCH) ==="
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

echo "→ Step 2: Record the running web image for a rollback..."
if [ -s "$RECORD" ]; then
    echo "   ✓ Keeping the existing record in $RECORD"
else
    WEB_IMAGE=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
    if [ -z "$WEB_IMAGE" ]; then
        echo "   ✗ Couldn't read the running web image — nothing was changed"
        exit 1
    fi
    if ! sudo docker tag "$WEB_IMAGE" nettap/web:rollback-net349; then
        echo "   ✗ Couldn't tag the running web image — nothing was changed"
        exit 1
    fi
    printf 'target=%s\nweb=%s\nrecorded=%s\n' "$TARGET" "$WEB_IMAGE" "$(date -u +%FT%TZ)" > "$RECORD"
    echo "   ✓ Tagged it as :rollback-net349 and wrote $RECORD"
fi
echo ""

echo "→ Step 3: Build the web image..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Built"
echo ""

echo "→ Step 4: Recreate nettap-web (no other container)..."
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web; then
    echo "   ✗ docker compose up failed. To go back: bash $REPO_DIR/scripts/remote/rollback-deep-ui-audit.sh"
    exit 1
fi
echo "   ✓ Recreated"
echo ""

echo "→ Step 5: Wait for it to become healthy..."
WEB_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$WEB_STATUS" = "healthy" ] && break
    echo "   waiting... web=$WEB_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ]; then check "nettap-web healthy" 0; else check "nettap-web healthy" 1 "$WEB_STATUS"; fi
echo ""

echo "→ Step 6: The served build carries the fixes..."
for s in "${STRINGS[@]}"; do
    if sudo docker exec nettap-web grep -rqF -- "$s" /app/build; then
        check "\"$s\"" 0
    else
        check "\"$s\"" 1 "not in /app/build"
    fi
done
echo ""

echo "→ Step 7: The web app answers..."
LOGIN=$(web_status /login)
if [ "$LOGIN" = "200" ]; then check "/login" 0 "200"; else check "/login" 1 "$LOGIN"; fi
ME=$(web_status /api/auth/me)
if [ "$ME" = "401" ]; then check "/api/auth/me without a session" 0 "401"; else check "/api/auth/me without a session" 1 "$ME"; fi
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy finished with failures (✗ above) ==="
    echo "To go back to the web image that ran before: bash $REPO_DIR/scripts/remote/rollback-deep-ui-audit.sh"
fi
exit "$FAILED"
