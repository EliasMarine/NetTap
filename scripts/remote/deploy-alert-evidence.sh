#!/usr/bin/env bash
# Deploy NET-355: the alert drawer shows evidence: the fields Suricata recorded, the Zeek records
# that share the alert's community ID, and, on a click, the packets near the alert time.
#
# Web only: rebuilds and recreates nettap-web alone (--no-deps; the daemon, OpenSearch and capture
# are not touched).
#
# Step 1 runs before any git or docker change. It tags the web image running now as
# nettap/web:rollback-net355 and records its ID in $RECORD, so rollback-alert-evidence.sh can put
# that exact image back. The record keeps the image from before the FIRST run: a later run (say the
# BRANCH=main deploy after the merge, while the feature image is running) only checks that the
# record still matches the tag, so it can still roll back to the image from before the feature.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-alert-evidence.sh
# To try the branch before it merges:
#   BRANCH=feature/alert-evidence bash /home/nettap/NetTap/scripts/remote/deploy-alert-evidence.sh
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
RECORD="${RECORD:-/home/nettap/.nettap-rollback-net355}"
TAG="nettap/web:rollback-net355"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

unchanged() {  # stop before anything was changed
    echo "   ✗ $1 — nothing was changed"
    exit 1
}

record_id() { sed -n 's/^web=//p' "$RECORD" 2>/dev/null; }
tag_id() { sudo docker image inspect -f '{{.Id}}' "$TAG" 2>/dev/null; }

echo "=== Deploy: evidence in the alert drawer (NET-355, $BRANCH) ==="
echo ""

echo "→ Step 1: Record the web image to roll back to..."
if [ -s "$RECORD" ]; then
    # A later run: the running image may already be the feature, so only the record and tag must agree.
    REC=$(record_id)
    TAGGED=$(tag_id)
    if [ -z "$REC" ] || [ "$REC" != "$TAGGED" ]; then
        unchanged "$RECORD says ${REC:-(no web= line)} but $TAG is ${TAGGED:-missing}"
    fi
    echo "   ✓ Keeping the record from the first run: $TAG is ${REC:7:12}"
else
    RUNNING=$(sudo docker inspect -f '{{.Image}}' nettap-web 2>/dev/null)
    [ -n "$RUNNING" ] || unchanged "Couldn't read the running web image"
    sudo docker tag "$RUNNING" "$TAG" || unchanged "Couldn't tag the running web image as $TAG"
    printf 'web=%s\n' "$RUNNING" > "$RECORD" || unchanged "Couldn't write $RECORD"
    REC=$(record_id)
    TAGGED=$(tag_id)
    if [ -z "$REC" ] || [ "$REC" != "$RUNNING" ] || [ "$TAGGED" != "$RUNNING" ]; then
        unchanged "Record (${REC:-empty}), running image ($RUNNING) and $TAG (${TAGGED:-missing}) differ"
    fi
    echo "   ✓ Tagged the running image ${RUNNING:7:12} as $TAG and wrote $RECORD"
fi
echo ""

echo "→ Step 2: Update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Build the web container..."
# A failed build must stop here: recreating would bring back the OLD image unnoticed.
OLD_IMAGE=$(sudo docker inspect --format='{{.Image}}' nettap-web 2>/dev/null || echo none)
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Image built"
echo ""

echo "→ Step 4: Recreate the web container (nothing else is touched)..."
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web; then
    echo "   ✗ docker compose up failed. To go back: bash $REPO_DIR/scripts/remote/rollback-alert-evidence.sh"
    exit 1
fi
echo "   ✓ Recreated"
echo ""

echo "→ Step 5: Wait for it to become healthy..."
WEB="unknown"
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$WEB" = "healthy" ] && break
    echo "   waiting... web=$WEB ($i/30)"
    sleep 5
done
if [ "$WEB" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$WEB"
NEW_IMAGE=$(sudo docker inspect --format='{{.Image}}' nettap-web 2>/dev/null || echo none)
if [ "$NEW_IMAGE" != "$OLD_IMAGE" ] && [ "$NEW_IMAGE" != "none" ]; then rc=0; else rc=1; fi
check "nettap-web runs the new image" "$rc" "${NEW_IMAGE:7:12}"
echo ""

echo "→ Step 6: The pages still load..."
CODE=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health" || true)
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/health answers" "$rc" "$CODE"
for path in "/" "/alerts"; do
    LOC=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code} %{redirect_url}' "$BASE$path" || true)
    case "$LOC" in "302 "*"/login"*) rc=0 ;; *) rc=1 ;; esac
    check "$path signed out goes to /login" "$rc" "$LOC"
done
echo "   To see it: sign in, open Alerts, click an alert: the Evidence block shows what Suricata saw and recorded, the Zeek records sharing its community ID, and Show packets."
echo ""

echo "→ Step 7: Log errors since the restart..."
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
fi
echo "To go back to the web image from before the first run: bash $REPO_DIR/scripts/remote/rollback-alert-evidence.sh"
exit "$FAILED"
