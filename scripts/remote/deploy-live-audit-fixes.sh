#!/usr/bin/env bash
# Deploy the live-audit fixes (NET-347 PCAP search, NET-348 UI, NET-315 SvelteKit 3) and check them.
#
# Rebuilds and recreates only nettap-storage-daemon and nettap-web (--no-deps: OpenSearch,
# capture and the rest are not touched). Before the first recreate it tags the images that
# are running now as :rollback-net347 and records them in $RECORD, so
# rollback-live-audit.sh can put both back together. An existing record is kept: a rerun
# must not replace the images to go back to with the new ones.
#
# Checks: a filter TShark refuses is refused; a known-answer search over closed captures
# matches TShark's own counts; no zombie in nettap-tshark; the web app serves /login and
# refuses /api/auth/me without a session.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-live-audit-fixes.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
RECORD="/home/nettap/.nettap-rollback-net347"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
SERVICES=(nettap-storage-daemon nettap-web)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

web_status() {  # HTTP status of a path on the web server, fetched inside its container
    sudo docker exec -e P="$1" nettap-web node -e '
        fetch("http://localhost:3000" + process.env.P, { redirect: "manual" })
            .then((r) => console.log(r.status)).catch(() => console.log("000"));' 2>/dev/null
}

echo "=== Deploy: live-audit fixes ($BRANCH) ==="
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
    echo "   ✓ Keeping the existing record in $RECORD"
else
    DAEMON_IMAGE=$(sudo docker inspect -f '{{.Image}}' nettap-storage-daemon 2>/dev/null)
    WEB_IMAGE=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
    if [ -z "$DAEMON_IMAGE" ] || [ -z "$WEB_IMAGE" ]; then
        echo "   ✗ Couldn't read the running images — nothing was changed"
        exit 1
    fi
    if ! sudo docker tag "$DAEMON_IMAGE" nettap/storage-daemon:rollback-net347 \
        || ! sudo docker tag "$WEB_IMAGE" nettap/web:rollback-net347; then
        echo "   ✗ Couldn't tag the running images — nothing was changed"
        exit 1
    fi
    printf 'target=%s\ndaemon=%s\nweb=%s\nrecorded=%s\n' "$TARGET" "$DAEMON_IMAGE" "$WEB_IMAGE" "$(date -u +%FT%TZ)" > "$RECORD"
    echo "   ✓ Tagged both as :rollback-net347 and wrote $RECORD"
fi
echo ""

echo "→ Step 3: Build the daemon and web images..."
if ! "${COMPOSE[@]}" build "${SERVICES[@]}"; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Built"
echo ""

echo "→ Step 4: Recreate them (no other container)..."
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate "${SERVICES[@]}"; then
    echo "   ✗ docker compose up failed. To go back: bash $REPO_DIR/scripts/remote/rollback-live-audit.sh"
    exit 1
fi
echo "   ✓ Recreated"
echo ""

echo "→ Step 5: Wait for both to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ] && break
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
    check "Both healthy" 0
else
    check "Both healthy" 1 "web=$WEB_STATUS daemon=$DAEMON_STATUS"
fi
echo ""

echo "→ Step 6: PCAP search checks (inside the daemon; can take several minutes)..."
# The script is read by this user (the repo's owner) and fed to python3 in the container
# shellcheck disable=SC2024
if ! sudo docker exec -i nettap-storage-daemon python3 - < scripts/remote/verify_pcap_search.py; then
    check "PCAP search checks" 1 "see ✗ above"
fi
echo ""

echo "→ Step 7: No zombie left in nettap-tshark..."
INIT_PID=$(sudo docker inspect -f '{{.State.Pid}}' nettap-tshark 2>/dev/null)
Z=$(ps -eo ppid=,stat= | awk -v p="${INIT_PID:-0}" '$1 == p && $2 ~ /^Z/' | wc -l)
if [ -n "$INIT_PID" ] && [ "$Z" -eq 0 ]; then check "Zombies" 0 "0"; else check "Zombies" 1 "${Z} (tshark PID ${INIT_PID:-unknown})"; fi
echo ""

echo "→ Step 8: The web app answers..."
LOGIN=$(web_status /login)
if [ "$LOGIN" = "200" ]; then check "/login" 0 "200"; else check "/login" 1 "$LOGIN"; fi
ME=$(web_status /api/auth/me)
if [ "$ME" = "401" ]; then check "/api/auth/me without a session" 0 "401"; else check "/api/auth/me without a session" 1 "$ME"; fi
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon|nettap-tshark"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy finished with failures (✗ above) ==="
    echo "To go back to the images that ran before: bash $REPO_DIR/scripts/remote/rollback-live-audit.sh"
fi
exit "$FAILED"
