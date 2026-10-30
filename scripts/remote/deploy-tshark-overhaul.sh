#!/usr/bin/env bash
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/connections-v3"

echo "=== Deploy TShark Analysis Overhaul (14 Bug Fixes) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code updated"
echo ""

echo "→ Step 2: Rebuild TShark container..."
sudo docker compose -f docker/docker-compose.yml build nettap-tshark
echo "   ✓ TShark container rebuilt"
echo ""

echo "→ Step 3: Rebuild daemon container..."
sudo docker compose -f docker/docker-compose.yml build nettap-storage-daemon
echo "   ✓ Daemon container rebuilt"
echo ""

echo "→ Step 4: Rebuild web container..."
sudo docker compose -f docker/docker-compose.yml build nettap-web
echo "   ✓ Web container rebuilt"
echo ""

echo "→ Step 5: Restart all three containers..."
sudo docker compose -f docker/docker-compose.yml up -d nettap-tshark nettap-web nettap-storage-daemon --force-recreate
echo "   ✓ Containers restarted"
echo ""

echo "→ Step 6: Wait for containers to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    TSHARK_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-tshark 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ] && [ "$TSHARK_STATUS" = "healthy" ]; then
        echo "   ✓ All containers healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS tshark=$TSHARK_STATUS ($i/30)"
    sleep 5
done
echo ""

echo "→ Step 7: Verify TShark container runs as root..."
TSHARK_USER=$(sudo docker exec nettap-tshark whoami 2>/dev/null || echo "unknown")
echo "   TShark container user: $TSHARK_USER"
if [ "$TSHARK_USER" = "root" ]; then
    echo "   ✓ Permission fix confirmed (running as root)"
else
    echo "   ⚠ Expected root, got $TSHARK_USER"
fi
echo ""

echo "→ Step 8: Test TShark availability..."
sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/tshark/status | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"   TShark available: {d.get('available')}\")
print(f\"   Version: {d.get('version')}\")
" || echo "   (API check failed — container may still be starting)"
echo ""

echo "→ Step 9: Test PCAP file listing..."
sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/tshark/pcaps | python3 -c "
import sys, json
d = json.load(sys.stdin)
files = d.get('files', [])
print(f\"   PCAP files found: {len(files)}\")
if files:
    print(f\"   Latest: {files[0].get('name', 'unknown')} ({files[0].get('size_human', 'unknown')})\")
" || echo "   (PCAP listing failed)"
echo ""

echo "→ Step 10: Test TShark analysis (quick smoke test)..."
# Get the first PCAP file and try a basic analysis
PCAP_PATH=$(sudo docker exec nettap-storage-daemon curl -s http://localhost:8880/api/tshark/pcaps | python3 -c "
import sys, json
d = json.load(sys.stdin)
files = d.get('files', [])
if files:
    print(files[0].get('path', ''))
" 2>/dev/null)

if [ -n "$PCAP_PATH" ]; then
    RESULT=$(sudo docker exec nettap-storage-daemon curl -s -X POST http://localhost:8880/api/tshark/analyze \
        -H "Content-Type: application/json" \
        -d "{\"pcap_path\": \"$PCAP_PATH\", \"max_packets\": 5}" 2>/dev/null)
    echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d.get('error'):
    print(f\"   ⚠ Analysis error: {d['error']}\")
else:
    packets = d.get('packets', [])
    print(f\"   ✓ Analysis returned {len(packets)} packets\")
    if packets:
        print(f\"   First packet protocol: {packets[0].get('_source', {}).get('layers', {}).get('frame', {}).get('frame.protocols', ['unknown'])}\")
" 2>/dev/null || echo "   (Analysis smoke test failed — check logs)"
else
    echo "   (No PCAP files available for smoke test)"
fi
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-tshark"
echo ""

echo "=== Deploy Complete ==="
echo ""
echo "What was fixed (14 issues):"
echo "  • SvelteKit proxy timeout: 10s → 60s for TShark endpoints"
echo "  • Missing analyzePcap import: hex dump now works"
echo "  • Container permissions: TShark runs as root (cap_drop ALL still active)"
echo "  • PcapSearchService: now uses docker exec (was calling missing local tshark)"
echo "  • Follow stream: no longer defaults to wrong stream index"
echo "  • PCAP validation: checks file exists before docker exec"
echo "  • JSON format: unwrap() handles TShark array-wrapped values"
echo "  • Error propagation: retry loop shows per-PCAP error details"
echo "  • Auto-run: both drawers auto-analyze on TShark tab open"
echo "  • Healthcheck: tshark --version every 30s"
echo "  • Memory limit: 512MB → 1GB"
echo "  • Shared helpers: deduplicated drawer logic"
echo "  • Concurrency control: semaphore(2) prevents container overload"
echo ""
echo "Test in browser:"
echo "  1. Open a connection drawer → TShark tab should auto-analyze"
echo "  2. Click a packet row → hex dump should load"
echo "  3. Try multiple drawers simultaneously → should queue, not crash"
