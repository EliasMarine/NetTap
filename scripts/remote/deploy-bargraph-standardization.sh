#!/usr/bin/env bash
# Deploy HorizontalBarList bar graph standardization and verify.
# Run on the NetTap device: sudo bash scripts/remote/deploy-bargraph-standardization.sh
set -u
REPO_DIR="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)/NetTap"
COMPOSE="docker compose -f $REPO_DIR/docker/docker-compose.yml"
BRANCH="claude/angry-payne"

echo "=== NetTap: Deploy Bar Graph Standardization ==="
echo "Date: $(date)"
echo ""

# --- Step 1: Pull latest code ---
echo "→ Step 1: Pulling latest code from $BRANCH..."
cd "$REPO_DIR" || { echo "FAIL: $REPO_DIR not found"; exit 1; }
git fetch origin "$BRANCH" || { echo "FAIL: git fetch failed"; exit 1; }
git checkout "$BRANCH" || { echo "FAIL: git checkout failed"; exit 1; }
git pull origin "$BRANCH" || { echo "FAIL: git pull failed"; exit 1; }
echo "  OK"
echo ""

# --- Step 2: Verify new component file exists ---
echo "→ Step 2: Verifying HorizontalBarList.svelte exists..."
if [ -f "$REPO_DIR/web/src/lib/components/HorizontalBarList.svelte" ]; then
    echo "  OK — HorizontalBarList.svelte found"
else
    echo "  FAIL: HorizontalBarList.svelte not found. Did git pull work?"
    exit 1
fi
echo ""

# --- Step 3: Rebuild web container ---
echo "→ Step 3: Rebuilding nettap-web image..."
sudo $COMPOSE build nettap-web || { echo "FAIL: build failed"; exit 1; }
echo "  OK"
echo ""

# --- Step 4: Recreate web container ---
echo "→ Step 4: Recreating nettap-web container..."
sudo $COMPOSE up -d nettap-web --force-recreate || { echo "FAIL: up failed"; exit 1; }
echo "  OK"
echo ""

# --- Step 5: Wait for web container to be healthy ---
echo "→ Step 5: Waiting for web container health (up to 30s)..."
for i in $(seq 1 6); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    echo "  Attempt $i/6: $STATUS"
    if [ "$STATUS" = "healthy" ]; then
        break
    fi
    sleep 5
done
FINAL_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
if [ "$FINAL_STATUS" != "healthy" ]; then
    echo "  WARNING: Web container not healthy after 30s (status: $FINAL_STATUS)"
    echo "  Continuing with verification anyway..."
fi
echo ""

# --- Step 6: Verify web container is responding ---
echo "→ Step 6: Testing web endpoint..."
HTTP_CODE=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost:3000/api/health 2>/dev/null || echo "000")
echo "  Health endpoint: HTTP $HTTP_CODE"
if [ "$HTTP_CODE" = "200" ]; then
    echo "  OK — Web server is responding"
elif [ "$HTTP_CODE" = "000" ]; then
    # Try without TLS
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/health 2>/dev/null || echo "000")
    echo "  Health endpoint (HTTP): HTTP $HTTP_CODE"
fi
echo ""

# --- Step 7: Check web container logs for errors ---
echo "→ Step 7: Web container recent logs (last 20 lines)..."
sudo docker logs nettap-web --tail 20 2>&1
echo ""

# --- Summary ---
echo "=== Deploy Complete ==="
echo ""
echo "What changed:"
echo "  - All horizontal bar graphs now use shared HorizontalBarList component"
echo "  - Bars are left-aligned with fixed-width label columns"
echo "  - Consistent 12px bar height across all pages"
echo "  - Drill-down: IP bars link to /devices/{ip}"
echo "  - Query params: ?protocol, ?signature, ?category, ?domain, ?type"
echo ""
echo "Pages to verify at https://nettap.bitspec.co:"
echo "  1. Home — Traffic Categories + Top Talkers"
echo "  2. Alerts — Top Signatures, Categories, Attacked IPs, Source IPs"
echo "  3. Logs — Protocol Breakdown, Source IPs, Contacted Servers, DNS Queries"
echo "  4. DNS — Query Type Distribution"
echo "  5. Bandwidth — Top Consumers"
echo ""
echo "Tell Claude to test when ready."
