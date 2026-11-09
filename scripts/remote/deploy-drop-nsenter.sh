#!/usr/bin/env bash
# Deploy the "drop nsenter" daemon fix to a mirror-mode box and verify it.
#
# Ubuntu's docker-default AppArmor profile blocked the daemon's
# `nsenter -t 1 -n`, so mirror setup never ran (port left down, no netplan
# file, no boot unit). The daemon now runs host network commands directly.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-drop-nsenter.sh
set -u

REPO_DIR="/home/nettap/NetTap"
# OLD CODE START — 2026-11-08: fix/daemon-drop-nsenter is merged; the device runs main (NET-214)
# BRANCH="fix/daemon-drop-nsenter"
# OLD CODE END
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)

echo "=== Deploy: daemon runs host network commands without nsenter ==="
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

echo "→ Step 2: Rebuild the daemon image..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Daemon image rebuilt"
echo ""

echo "→ Step 3: Recreate the daemon (only the daemon; OpenSearch is not touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
# Count AppArmor refusals from here on; the old daemon logged one every 30 s until now
START=$(date '+%Y-%m-%d %H:%M:%S')
echo "   ✓ Daemon recreated"
echo ""

echo "→ Step 4: Wait for the daemon to become healthy..."
STATUS="unknown"
for i in $(seq 1 30); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$STATUS" = "healthy" ]; then
        echo "   ✓ Daemon healthy"
        break
    fi
    echo "   waiting... daemon=$STATUS ($i/30)"
    sleep 5
done
[ "$STATUS" = "healthy" ] || echo "   ✗ Daemon not healthy after 150s — see: sudo docker logs nettap-storage-daemon --tail 50"
echo ""

echo "→ Step 5: Mirror setup result in the daemon log..."
sudo docker logs nettap-storage-daemon 2>&1 | grep -iE "mirror" | tail -10 | sed 's/^/     /'
if sudo docker logs nettap-storage-daemon 2>&1 | grep -q "Mirror interface .* configured successfully"; then
    echo "   ✓ Mirror setup ran"
else
    echo "   ✗ No 'configured successfully' line — read the lines above"
fi
echo ""

echo "→ Step 6: AppArmor refusals since this deploy started..."
if ! KLOG=$(sudo journalctl -k --since "$START" --no-pager 2>&1); then
    echo "   ? Couldn't read the kernel log: $KLOG"
else
    DENIED=$(printf '%s\n' "$KLOG" | grep -c 'apparmor="DENIED".*comm="nsenter"')
    if [ "$DENIED" = "0" ]; then
        echo "   ✓ None (was one every 30s before the fix)"
    else
        echo "   ✗ $DENIED nsenter refusals — the old image may still be running"
    fi
fi
echo ""

echo "→ Step 7: Start the boot unit the daemon wrote (also turns IPv6 off on the capture port)..."
sudo systemctl daemon-reload
if sudo docker logs nettap-storage-daemon 2>&1 | grep -q "Mirror setup skipped"; then
    echo "   ✗ Not started: the daemon refused this NIC (see Step 5), so its boot unit may be stale"
elif systemctl cat nettap-mirror.service >/dev/null 2>&1; then
    if sudo systemctl restart nettap-mirror.service; then
        echo "   ✓ nettap-mirror.service ran: $(systemctl is-active nettap-mirror.service), $(systemctl is-enabled nettap-mirror.service)"
    else
        echo "   ✗ nettap-mirror.service failed:"
        sudo journalctl -u nettap-mirror.service -n 15 --no-pager | sed 's/^/     /'
    fi
else
    echo "   ✗ nettap-mirror.service was not written — see Step 5"
fi
echo ""

echo "→ Step 8: Full mirror verification..."
bash "$REPO_DIR/scripts/remote/verify-mirror-mode.sh"
echo ""

echo "=== Deploy complete ==="
echo "If Step 8 shows no ✗ lines, reboot (sudo reboot) and run the verify script once more:"
echo "  bash $REPO_DIR/scripts/remote/verify-mirror-mode.sh"
