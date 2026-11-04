#!/usr/bin/env bash
# Deploy the UI redesign branch to the device and check the new look is served.
#
# Only the web container changes: the redesign is the web UI (design system,
# shell, every page). Set BRANCH to the open PR's branch; after it merges, set it
# back to "main" (PLAN.md §6 step C.6).
#
# Before updating, it records the deployed commit in $LAST_DEPLOY_FILE, so
# rollback-ui-redesign.sh can go back to it.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-ui-redesign.sh
# rollback-ui-redesign.sh runs this script with TARGET_SHA set: it then checks that
# commit out (detached, no pull) and skips the redesign-only checks.
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="feature/ui-redesign-full"
LAST_DEPLOY_FILE="${LAST_DEPLOY_FILE:-/home/nettap/.nettap-last-deploy}"
TARGET_SHA="${TARGET_SHA:-}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

# Fetch a path from the web server inside its container (the device has no node or curl
# guarantees on the host). Prints "<status> <body bytes>" or "<status> <body>" with BODY=1.
web_get() {  # web_get PATH [BODY]
    sudo docker exec -e P="$1" -e B="${2:-0}" nettap-web node -e '
        fetch("http://localhost:3000" + process.env.P, { redirect: "manual" })
            .then(async (r) => { const t = await r.text(); console.log(r.status + " " + (process.env.B === "1" ? t : t.length)); })
            .catch((e) => console.log("000 " + e.message));' 2>/dev/null
}

if [ -n "$TARGET_SHA" ]; then echo "=== Roll back the UI to $TARGET_SHA ==="; else echo "=== Deploy: UI redesign ($BRANCH) ==="; fi
echo ""

echo "→ Step 1: Update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if [ -n "$TARGET_SHA" ]; then
    if ! git fetch origin || ! git checkout --detach "$TARGET_SHA"; then
        echo "   ✗ Could not check out $TARGET_SHA — nothing was rebuilt"
        exit 1
    fi
else
    # Record what is deployed now, unless this branch is already deployed (a re-run
    # must not overwrite the pre-redesign commit with a redesign one)
    if [ "$(git branch --show-current)" != "$BRANCH" ]; then
        git rev-parse HEAD > "$LAST_DEPLOY_FILE" && echo "   ✓ Recorded the deployed commit $(cut -c1-8 "$LAST_DEPLOY_FILE") in $LAST_DEPLOY_FILE"
    else
        echo "   ✓ $BRANCH is already deployed; keeping the recorded rollback commit"
    fi
    # A failed checkout or pull would rebuild the old code, so stop here instead
    if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
        echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
        exit 1
    fi
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web container..."
if ! "${COMPOSE[@]}" build nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ nettap-web image built"
echo ""

echo "→ Step 3: Recreate the web container (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web
echo ""

echo "→ Step 4: Wait for it to become healthy..."
STATUS="unknown"
for i in $(seq 1 30); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    echo "   waiting... nettap-web=$STATUS ($i/30)"
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then check "nettap-web health" 0 "$STATUS"; else check "nettap-web health" 1 "$STATUS"; fi
echo ""

echo "→ Step 5: Check the redesign is what's being served..."
LOGIN=$(web_get /login 1)
case "$LOGIN" in 200*) check "login page" 0 "HTTP 200" ;; *) check "login page" 1 "HTTP ${LOGIN%% *}" ;; esac
if [ -n "$TARGET_SHA" ]; then
    echo "   (rollback: the redesign checks are skipped)"
else
if printf '%s' "$LOGIN" | grep -q "nettap-theme"; then check "theme bootstrap script in the page" 0; else check "theme bootstrap script in the page" 1; fi
if printf '%s' "$LOGIN" | grep -q "fonts.googleapis.com"; then check "no Google Fonts link" 1 "still linked"; else check "no Google Fonts link" 0; fi
for f in sora/Sora-Variable manrope/Manrope-Variable jetbrains-mono/JetBrainsMono-Variable; do
    R=$(web_get "/fonts/$f.woff2")
    case "$R" in 200*) check "font $f" 0 "${R#* } bytes" ;; *) check "font $f" 1 "HTTP ${R%% *}" ;; esac
done
# The tokens can be in any of the page's stylesheets, so check each one
CSS_PATHS=$(printf '%s' "$LOGIN" | grep -o '/_app/immutable/assets/[^"]*\.css' | sort -u)
TOKENS_FOUND=1
for CSS_PATH in $CSS_PATHS; do
    # the new theme contract (PLAN.md §5.1); a minifier may drop the quotes
    if web_get "$CSS_PATH" 1 | grep -qE 'data-theme="?graphite'; then TOKENS_FOUND=0; break; fi
done
if [ -z "$CSS_PATHS" ]; then
    check "new design tokens in the stylesheet" 1 "no stylesheet link found"
else
    check "new design tokens in the stylesheet" "$TOKENS_FOUND"
fi
fi
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
    if [ -n "$TARGET_SHA" ]; then
        echo "Rolled back to $TARGET_SHA. Open the dashboard to check."
    else
        echo "Open the dashboard: the sidebar shell, Home without device cards, and every page in the new design."
        echo "Settings → Display switches between Ember, Graphite and Spectrum."
        echo "To go back: bash $REPO_DIR/scripts/remote/rollback-ui-redesign.sh"
    fi
else
    echo "=== Deploy finished with ✗ lines above — paste this output back ==="
fi
