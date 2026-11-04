#!/usr/bin/env bash
# Deploy a UI redesign branch to the device and check the new look is served.
#
# Only the web container changes: the redesign is visual (tokens, fonts, theme
# picker, layout). Set BRANCH to the open PR's branch; after it merges, set it
# back to "main" (PLAN.md §5.3).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-ui-redesign.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="feature/ui-redesign-foundation"
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

echo "=== Deploy: UI redesign ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# A failed checkout or pull would rebuild the old code, so stop here instead
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
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
    if web_get "$CSS_PATH" 1 | grep -q "data-theme-preview"; then TOKENS_FOUND=0; break; fi
done
if [ -z "$CSS_PATHS" ]; then
    check "new design tokens in the stylesheet" 1 "no stylesheet link found"
else
    check "new design tokens in the stylesheet" "$TOKENS_FOUND"
fi
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
    echo "Open the dashboard: every page should be pure black. Settings → Display has the theme picker."
else
    echo "=== Deploy finished with ✗ lines above — paste this output back ==="
fi
