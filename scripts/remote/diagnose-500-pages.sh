#!/usr/bin/env bash
# Diagnose 500 errors on certificates, tools, infrastructure, settings pages
# Run on the NetTap device: sudo bash scripts/remote/diagnose-500-pages.sh

set -u

echo "=== NetTap 500 Error Diagnostics ==="
echo "Date: $(date)"
echo ""

echo "=== Step 1: Container status ==="
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-nginx|nettap-opensearch"

echo ""
echo "=== Step 2: Web container recent errors ==="
sudo docker logs nettap-web --tail 200 2>&1 | grep -iE "error|500|crash|fail|exception|ERR_|ECONNREFUSED|TypeError|ReferenceError" | tail -40

echo ""
echo "=== Step 3: HTTP status codes for each broken page ==="
for page in certificates tools infrastructure settings; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/$page)
    echo "  /$page -> HTTP $STATUS"
done

echo ""
echo "=== Step 4: Full error body from /certificates ==="
curl -s http://localhost:3000/certificates 2>&1 | tail -50

echo ""
echo "=== Step 5: Full error body from /infrastructure ==="
curl -s http://localhost:3000/infrastructure 2>&1 | tail -50

echo ""
echo "=== Step 6: Full error body from /settings ==="
curl -s http://localhost:3000/settings 2>&1 | tail -50

echo ""
echo "=== Step 7: Full error body from /tools ==="
curl -s http://localhost:3000/tools 2>&1 | tail -50

echo ""
echo "=== Step 8: Daemon API endpoint checks (port 8880) ==="
for endpoint in /api/certificates/stats /api/system/health /api/bridge/health /api/storage/status /api/smart/health; do
    RESP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8880$endpoint)
    echo "  daemon $endpoint -> HTTP $RESP"
done

echo ""
echo "=== Step 9: SvelteKit API proxy checks (port 3000) ==="
for endpoint in /api/opensearch/cluster /api/notifications/config /api/system/health /api/certificates/stats; do
    RESP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000$endpoint)
    echo "  sveltekit $endpoint -> HTTP $RESP"
done

echo ""
echo "=== Step 10: Check working pages for comparison ==="
for page in logs alerts connections devices; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/$page)
    echo "  /$page -> HTTP $STATUS"
done

echo ""
echo "=== Step 11: Web container full recent log (last 50 lines) ==="
sudo docker logs nettap-web --tail 50 2>&1

echo ""
echo "=== Done ==="
echo "Paste the FULL output above back to Claude for analysis."
