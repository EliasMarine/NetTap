#!/usr/bin/env bash
# Measure capture loss with live bandwidth off vs eight watches (NET-206).
#
# Runs verify_live_bandwidth.py's capture-safety mode in the daemon container: three pairs of
# 60 s arms, meter off and eight watches in ABA order. Each arm records the capture NIC's drop
# counters and Suricata's capture.kernel_packets / kernel_drops (`suricatasc -c dump-counters`,
# which needs the stats block deployed by deploy-capture-hardening.sh). It turns the live bandwidth
# setting on for the run and puts the owner's value back at the end, even after a failure.
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
set -u

REPO_DIR="/home/nettap/NetTap"
VERIFY="$REPO_DIR/scripts/remote/verify_live_bandwidth.py"
LOG="$HOME/nettap-capture-loss.log"

echo "=== Capture loss: live bandwidth off vs eight watches (NET-206) ==="
echo "Started $(date -u +%Y-%m-%dT%H:%M:%SZ); writing to $LOG"
echo ""
# shellcheck disable=SC2024  # the script is read as this user on purpose; only docker needs sudo
sudo docker exec -i nettap-storage-daemon python3 - capture-safety < "$VERIFY" 2>&1 | tee "$LOG"
STATUS=${PIPESTATUS[0]}
echo ""
if [ "$STATUS" -eq 0 ]; then
    echo "=== Done: both verdicts PASS (log: $LOG) ==="
else
    echo "=== Done: exit $STATUS, see the FAIL lines above (log: $LOG) ==="
fi
exit "$STATUS"
