#!/usr/bin/env bash
# Deploy packet analysis (NET-188 PR 1: the daemon's /api/packets routes and their web proxies)
# and check them on real captures against an independent reading of the files.
#
# The daemon and web containers are rebuilt and recreated; nothing else is touched. On the
# first run, and after the index format changes (version 2: records stamped before 2000 are
# a crash's zeroed tail, not packets), the daemon indexes every capture file (about 0.35 s
# per 100 MB file), so Step 5 may wait several minutes. Then, read-only,
# verify-packet-analysis.py:
#   - compares the index's packet times with a fresh capinfos (3 random files), and every
#     cut-short file's times and packet count with TShark reading it whole
#   - searches a 60 s window across a file boundary, and a window across each cut-short
#     file's end into the next file, and checks the files read and every row against
#     each file read whole by TShark (no mergecap, no editcap)
#   - downloads that search and reads it back; opens one packet's detail
#   - checks field suggestions, the filter check and a hostile filter
#   - checks a search over the last 60 s is marked provisional
#   - checks no job or FIFO is left behind in nettap-tshark
#
# Run as the normal user (NOT with sudo). BRANCH defaults to main; to try a branch first:
#   BRANCH=feature/packet-analysis-redesign bash /home/nettap/NetTap/scripts/remote/deploy-packet-analysis.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy packet analysis (NET-188) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "   ✓ Code at $(git log --oneline -1)"
echo ""

echo "→ Step 2: Rebuild the daemon and web containers..."
"${COMPOSE[@]}" build nettap-storage-daemon nettap-web
echo ""

echo "→ Step 3: Recreate the two containers..."
"${COMPOSE[@]}" up -d --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for both containers to become healthy..."
WEB_STATUS=unknown
DAEMON_STATUS=unknown
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "containers healthy" "$rc" "web=$WEB_STATUS daemon=$DAEMON_STATUS"
echo ""

echo "→ Step 5: Check against an independent reading (waits for the first indexing)..."
# shellcheck disable=SC2024  # the file is the repo's, readable without sudo
sudo docker exec -i nettap-storage-daemon python3 - < "$REPO_DIR/scripts/remote/verify-packet-analysis.py" 2>&1 | grep -v "Warning"
rc=${PIPESTATUS[0]}
check "independent check" "$rc" "verify-packet-analysis.py exited $rc"
echo ""

echo "→ Step 6: Daemon log lines for packet analysis..."
sudo docker logs nettap-storage-daemon --since 30m 2>&1 | grep -E "packet (search|download)|Capture index|capinfos batch|packet request failed" | tail -n 8
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon|nettap-tshark"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (see ✗ above) ==="
fi
exit "$FAILED"
