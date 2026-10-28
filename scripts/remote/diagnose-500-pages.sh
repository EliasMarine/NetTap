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
echo "=== Step 3: HTTP status + body from inside web container (bypasses auth) ==="
echo "Using node fetch since curl is not available in the web container."
echo ""

for page in certificates tools infrastructure settings logs; do
    echo "--- /$page ---"
    sudo docker exec nettap-web node -e "
        fetch('http://localhost:3000/$page', { redirect: 'manual' })
            .then(async r => {
                console.log('HTTP ' + r.status);
                if (r.status >= 400) {
                    const body = await r.text();
                    console.log(body.substring(0, 2000));
                }
            })
            .catch(e => console.log('FETCH ERROR: ' + e.message));
    " 2>&1
    echo ""
done

echo ""
echo "=== Step 4: Daemon API checks from inside daemon container ==="
DCURL="sudo docker exec nettap-storage-daemon curl -s"
for endpoint in /api/certificates/stats /api/system/health /api/bridge/health /api/storage/status /api/smart/health; do
    RESP=$($DCURL -o /dev/null -w "%{http_code}" http://localhost:8880$endpoint)
    echo "  daemon $endpoint -> HTTP $RESP"
done

echo ""
echo "=== Step 5: SvelteKit API proxy from inside web container ==="
for endpoint in /api/opensearch/cluster /api/notifications/config /api/system/health /api/certificates/stats; do
    echo "--- $endpoint ---"
    sudo docker exec nettap-web node -e "
        fetch('http://localhost:3000$endpoint')
            .then(async r => {
                console.log('HTTP ' + r.status);
                if (r.status >= 400) {
                    const body = await r.text();
                    console.log(body.substring(0, 500));
                }
            })
            .catch(e => console.log('FETCH ERROR: ' + e.message));
    " 2>&1
    echo ""
done

echo ""
echo "=== Step 6: Nginx error log ==="
sudo docker logs nettap-nginx --tail 30 2>&1 | grep -iE "error|502|500|upstream" | tail -15

echo ""
echo "=== Step 7: Web container full recent log (last 50 lines) ==="
sudo docker logs nettap-web --tail 50 2>&1

echo ""
echo "=== Done ==="
echo "Paste the FULL output above back to Claude for analysis."
