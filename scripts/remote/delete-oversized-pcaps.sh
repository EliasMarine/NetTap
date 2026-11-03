#!/usr/bin/env bash
# Delete the capture files the G11 wrote before capture switched to 256 MB files (#137).
# Owner decision 2026-11-03: delete them now. Each was too big for PCAP Search (tshark needs
# about 120 MiB plus the file's size), so a search that reached one said "ran out of memory".
#
# Only files over 850 MiB last written before 2026-11-03 02:40 UTC are deleted; capture has
# rotated at 256 MB since, so nothing newer can match. It stops without deleting anything if
# the list isn't the 51 files the owner approved. Zeek and Suricata records are untouched.
#
# The full output is also saved to ~/nettap-delete-oversized-pcaps.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/delete-oversized-pcaps.sh
set -u
exec > >(tee "$HOME/nettap-delete-oversized-pcaps.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
EXPECTED_FILES=51
CUTOFF="2026-11-03 02:40:00"
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

candidates() {  # every file this script may delete, one "bytes path" per line
    sudo env TZ=UTC find "$PCAP_DIR" -maxdepth 1 -type f -name 'mnetsniff-*.pcap' -size +850M \
        ! -newermt "$CUTOFF" -printf '%s %p\n' | sort -k2
}

echo "=== Delete PCAP files from before the 256 MB change ==="
echo ""

echo "→ Step 1: Find the files..."
PCAP_DIR=$(sudo docker volume inspect docker_pcap-data --format '{{.Mountpoint}}' 2>/dev/null)
if [ -z "$PCAP_DIR" ] || ! sudo test -d "$PCAP_DIR"; then
    echo "   ✗ PCAP volume docker_pcap-data not found — nothing was deleted"
    exit 1
fi
LIST=$(candidates)
COUNT=$(printf '%s\n' "$LIST" | grep -c . || true)
BYTES=$(printf '%s\n' "$LIST" | awk '{s += $1} END {printf "%.1f GB", s / 1e9}')
echo "   $COUNT files, $BYTES, in $PCAP_DIR"
printf '%s\n' "$LIST" | awk '{printf "     %6.2f GB  %s\n", $1 / 1e9, $2}' | sed "s#$PCAP_DIR/##"
if [ "$COUNT" -eq 0 ]; then
    echo "   ✓ nothing to delete (already done)"
elif [ "$COUNT" -ne "$EXPECTED_FILES" ]; then
    echo "   ✗ expected the $EXPECTED_FILES files the owner approved, found $COUNT — nothing was deleted"
    exit 1
else
    echo ""
    echo "→ Step 2: Delete them..."
    printf '%s\n' "$LIST" | cut -d' ' -f2- | while IFS= read -r f; do sudo rm -f -- "$f"; done
    LEFT=$(candidates | grep -c . || true)
    if [ "$LEFT" -eq 0 ]; then rc=0; else rc=1; fi
    check "deleted" "$rc" "$COUNT files ($BYTES); $LEFT left"
fi
echo ""

echo "→ Step 3: Capture and PCAP Search still work..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
def call(path):
    req = urllib.request.Request('http://localhost:8880' + path, headers={'X-NetTap-Daemon-Token': token})
    return json.load(urllib.request.urlopen(req, timeout=60))
pcaps = call('/api/tshark/pcaps')['pcaps']
big = [p['name'] for p in pcaps if p['size_bytes'] > 850 * 1048576]
print(len(pcaps), len(big), max(p['size_bytes'] for p in pcaps) // 1_000_000)
" 2>&1)
read -r LISTED BIG LARGEST_MB <<<"$OUT"
if [ "${BIG:-x}" = "0" ]; then rc=0; else rc=1; fi
check "no file over 850 MiB left in PCAP Search's list" "$rc" "${LISTED:-?} files listed, $BIG over 850 MiB, largest ${LARGEST_MB:-?} MB ($OUT)"
sudo df -h "$PCAP_DIR" | tail -1 | awk '{print "   disk: " $3 " used of " $2 " (" $5 ")"}'
echo ""

echo "→ Step 4: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Old PCAP files deleted and everything verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
