#!/usr/bin/env bash
# Measure capture loss with live bandwidth off vs eight watches (NET-206).
#
# Runs verify_live_bandwidth.py's capture-safety mode in the daemon container: three pairs of
# 60 s arms, meter off and eight watches in ABA order. Each arm records the capture NIC's drop
# counters and Suricata's capture.kernel_packets / kernel_drops (`suricatasc -c dump-counters`,
# which needs the engine counters SURICATA_STATS_* in docker-compose.yml turns on; deploy
# deploy-capture-hardening.sh first). It turns the live bandwidth setting on for the run and puts
# the owner's value back at the end, even after a failure.
#
# Before you start: begin a sustained download on the dev Mac (bc:89:c1:e1:8a:d6) and keep it
# running until the verdict (about nine minutes). Close every device page: an open page keeps a
# watch alive.
#
# The output is also written to ~/nettap-capture-loss.log. Copy the per-arm lines and the two
# verdicts into tracking-fixes/2026-11-07-device-live-bandwidth.md and
# Debugging/BRIDGE-ARCHITECTURE.md §17 (the "pending device run" entries).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/measure-capture-loss.sh
# To measure a branch: BRANCH=<branch> bash …
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
VERIFY="$REPO_DIR/scripts/remote/verify_live_bandwidth.py"
SOCKET="/var/run/suricata/suricata-command.socket"
LOG="$HOME/nettap-capture-loss.log"

echo "=== Capture loss: live bandwidth off vs eight watches (NET-206, $BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was measured"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Check the daemon and Suricata's counters..."
DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
if [ "$DAEMON_STATUS" != "healthy" ]; then
    echo "   ✗ nettap-storage-daemon is $DAEMON_STATUS — run deploy-capture-hardening.sh first"
    exit 1
fi
echo "   ✓ nettap-storage-daemon healthy"
if ! sudo docker exec nettap-suricata-live suricatasc "$SOCKET" -c dump-counters 2>/dev/null | grep -q '"kernel_packets"'; then
    echo "   ✗ Suricata's dump-counters has no kernel_packets — its counters are off; run deploy-capture-hardening.sh first"
    exit 1
fi
echo "   ✓ Suricata answers dump-counters with kernel_packets"
echo ""

echo "→ Step 3: Measure (about nine minutes; keep the download on the dev Mac running)..."
echo "   Started $(date -u +%Y-%m-%dT%H:%M:%SZ); writing to $LOG"
# shellcheck disable=SC2024  # the script is read as this user on purpose; only docker needs sudo
sudo docker exec -i nettap-storage-daemon python3 - capture-safety < "$VERIFY" 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}
echo ""

echo "→ Step 4: Result..."
if [ "$STATUS" -eq 0 ]; then
    echo "   ✓ Both verdicts PASS"
else
    echo "   ✗ Exit $STATUS, see the FAIL lines above"
fi
echo ""

echo "=== Done (log: $LOG) ==="
exit "$STATUS"
