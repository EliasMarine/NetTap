#!/usr/bin/env bash
# Deploy the Log Explorer redesign (daemon + web containers)
# Run on the NetTap device: sudo bash scripts/remote/deploy-log-explorer.sh

set -u

BRANCH="phase-5/mirror-span-mode"
COMPOSE="docker/docker-compose.yml"

echo "=== Step 1: Pull latest code ==="
cd ~/NetTap
git fetch origin "$BRANCH"
git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
git pull origin "$BRANCH"

echo ""
echo "=== Step 2: Rebuild and deploy daemon + web ==="
sudo docker compose -f "$COMPOSE" up -d --force-recreate --build nettap-storage-daemon nettap-web

echo ""
echo "=== Step 3: Wait 15s for containers to start ==="
sleep 15

echo ""
echo "=== Step 4: Verify containers are running ==="
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-storage-daemon|nettap-web"

echo ""
echo "=== Step 5: Test daemon log endpoints ==="
echo "--- /api/logs/stats ---"
curl -s http://localhost:8880/api/logs/stats 2>/dev/null | python3 -m json.tool 2>/dev/null | head -10 || echo "FAILED"

echo ""
echo "--- /api/logs/timeline ---"
curl -s http://localhost:8880/api/logs/timeline 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f'Timeline: {len(d.get(\"buckets\",[]))} buckets, interval={d.get(\"interval\",\"?\")}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "--- /api/logs/protocol-breakdown ---"
curl -s http://localhost:8880/api/logs/protocol-breakdown 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
for p in d.get('protocols',[]):
    print(f'  {p[\"label\"]}: {p[\"count\"]:,}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "--- /api/logs/top-talkers ---"
curl -s http://localhost:8880/api/logs/top-talkers 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
for t in d.get('talkers',[])[:5]:
    print(f'  {t[\"ip\"]}: {t[\"count\"]:,}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "--- /api/logs/top-dns ---"
curl -s http://localhost:8880/api/logs/top-dns 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
for q in d.get('queries',[])[:5]:
    print(f'  {q[\"domain\"]}: {q[\"count\"]:,}')
" 2>/dev/null || echo "FAILED"

echo ""
echo "=== Done! Open the Log Explorer page in your browser to verify the UI. ==="
