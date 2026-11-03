#!/usr/bin/env bash
# Check that no page's figures depend on how OpenSearch splits the data (#93).
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# A window spanning several daily indices is counted per index and merged. To test that before
# the data spans several days, every data endpoint is read normally, then with OpenSearch's
# concurrent segment search forced to "all" (each shard cut into slices that are counted and
# merged the same way), then normally again; the two normal reads must agree and the sliced
# read must equal them. The setting is transient and always put back. No data is written.
# The checks run in nettap-storage-daemon (scripts/remote/verify_split_invariance.py).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/verify-split-invariance.sh
set -u

REPO_DIR="/home/nettap/NetTap"

echo "=== Page figures do not depend on how the data is split ==="
# The program goes in as an argument, not stdin: sudo -S (password on stdin) would swallow it
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_split_invariance.py")" 2>&1)
RC=$?
printf '%s\n' "$OUT" | sed 's/^/   /'
echo ""
if [ "$RC" -eq 0 ]; then
    echo "=== Every compared endpoint gives the same figures however the data is split ==="
else
    echo "=== Finished with problems above (exit $RC) — paste this output back ==="
fi
exit "$RC"
