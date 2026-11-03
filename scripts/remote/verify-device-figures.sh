#!/usr/bin/env bash
# Read-only check that every device's own pages show what OpenSearch holds.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# For every device on the Devices page (past day, ending 15 minutes ago) it recomputes the
# Devices list row, Device detail (connections, bytes sent/received/total, chart sums, unique
# destinations, top destinations, alerts, DNS lookups), its ports, categories and risk score;
# and for every registry device, the device-by-MAC page (connections, in/out/total bytes, top
# destinations by bytes). Each figure sits between two raw OpenSearch reads with the endpoint's
# own filters. The checks run in nettap-storage-daemon (scripts/remote/verify_device_figures.py).
# Nothing is restarted, written or deleted. Takes a few minutes.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/verify-device-figures.sh
set -u

REPO_DIR="/home/nettap/NetTap"

echo "=== Per-device figures vs OpenSearch ==="
# The program goes in as an argument, not stdin: sudo -S (password on stdin) would swallow it
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_device_figures.py")" 2>&1)
RC=$?
printf '%s\n' "$OUT" | sed 's/^/   /'
echo ""
if [ "$RC" -eq 0 ]; then
    echo "=== Every device figure matches OpenSearch ==="
else
    echo "=== Finished with problems above (exit $RC) — paste this output back ==="
fi
exit "$RC"
