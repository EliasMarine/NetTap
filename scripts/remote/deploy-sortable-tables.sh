#!/usr/bin/env bash
# Deploy the sortable-tables fix (#140) and the packet-table protocol fix (#141) from main.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #140: every table sorts by every column, both ways. IPs, ports and tshark's numeric
#     text now sort by value (10.10.0.26 before 10.10.0.235). A device's Connections table
#     sorts on the daemon, across all its connections, not just the page on screen.
#   #141: the TShark table and PCAP preview show Wireshark's own Protocol, Source and
#     Destination columns: QUIC packets read "DATA" (Wireshark: UDP), IPv6/ARP had no address.
#   Moves this box from fix/dashboard-data-accuracy to main (everything is merged there).
#   Rebuilds the web UI and the daemon; each is down for under a minute while it restarts.
#
# The full output is also saved to ~/nettap-sortable-tables.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-sortable-tables.sh
set -u
exec > >(tee "$HOME/nettap-sortable-tables.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_healthy() {  # wait_healthy CONTAINER
    local status="unknown"
    for _ in $(seq 1 30); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$1" 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && break
        sleep 5
    done
    if [ "$status" = "healthy" ]; then check "$1 health" 0 "$status"; else check "$1 health" 1 "$status"; fi
}

echo "=== Deploy: sortable tables (#140) + packet protocol column (#141) from $BRANCH ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! { git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; }; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web UI and the daemon..."
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — the running containers were not touched"
    exit 1
fi
echo "   ✓ Built"
echo ""

echo "→ Step 3: Recreate them and wait for health..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo ""

echo "→ Step 4: A device's connections sort by every column (#140)..."
sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_connection_sort.py")" 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 5: Packet tables show Wireshark's columns (#141)..."
sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_protocol_column.py")" 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 7: Logs since the restart..."
for c in nettap-storage-daemon nettap-web; do
    ERRS=$(sudo docker logs "$c" --since 10m 2>&1 | grep -cE "ERROR|Traceback")
    if [ "$ERRS" -eq 0 ]; then rc=0; else rc=1; fi
    check "no errors in the $c log" "$rc" "$ERRS ERROR/Traceback lines"
    [ "$ERRS" -eq 0 ] || sudo docker logs "$c" --since 10m 2>&1 | grep -E "ERROR|Traceback" | tail -5 | sed 's/^/     | /'
done
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== #140 and #141 deployed and verified — the box now runs $BRANCH ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
