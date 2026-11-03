#!/usr/bin/env bash
# Delete the two capture files PCAP Search can't finish (#137 follow-up).
# Owner decision 2026-11-03: delete those two now. Both were written before capture switched to
# 256 MB files; tshark hits the 300 s limit on them in the 1 GiB TShark container, so PCAP Search
# reports them as "not searched". Every other file finishes.
#
# Deletes exactly these two names and nothing else; a name that is missing is reported, not
# guessed at. Zeek and Suricata records are untouched.
#
# The full output is also saved to ~/nettap-delete-timed-out-pcaps.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/delete-timed-out-pcaps.sh
set -u
exec > >(tee "$HOME/nettap-delete-timed-out-pcaps.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
FILES=(mnetsniff-enp4s0_1793590387.pcap mnetsniff-enp4s0_1793583778.pcap)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Delete the two PCAP files PCAP Search can't finish ==="
echo ""

echo "→ Step 1: Find them..."
PCAP_DIR=$(sudo docker volume inspect docker_pcap-data --format '{{.Mountpoint}}' 2>/dev/null)
if [ -z "$PCAP_DIR" ] || ! sudo test -d "$PCAP_DIR"; then
    echo "   ✗ PCAP volume docker_pcap-data not found — nothing was deleted"
    exit 1
fi
for name in "${FILES[@]}"; do
    if sudo test -f "$PCAP_DIR/$name"; then
        echo "   $(sudo stat -c '%s' "$PCAP_DIR/$name" | awk '{printf "%.0f MiB", $1 / 1048576}')  $name"
    else
        echo "   (already gone)  $name"
    fi
done
echo ""

echo "→ Step 2: Delete them..."
for name in "${FILES[@]}"; do
    sudo rm -f -- "$PCAP_DIR/$name"
    if sudo test -e "$PCAP_DIR/$name"; then rc=1; else rc=0; fi
    check "$name gone" "$rc" "$PCAP_DIR"
done
echo ""

echo "→ Step 3: PCAP Search's list no longer has them..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880/api/tshark/pcaps', headers={'X-NetTap-Daemon-Token': token})
names = {p['name'] for p in json.load(urllib.request.urlopen(req, timeout=60))['pcaps']}
print(len(names), sum(n in names for n in '${FILES[*]}'.split()))
" 2>&1)
read -r LISTED STILL <<<"$OUT"
if [ "${STILL:-x}" = "0" ]; then rc=0; else rc=1; fi
check "neither file listed" "$rc" "${LISTED:-?} files listed, ${STILL:-?} of the two still there ($OUT)"
sudo df -h "$PCAP_DIR" | tail -1 | awk '{print "   disk: " $3 " used of " $2 " (" $5 ")"}'
echo ""

echo "→ Step 4: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Both files deleted and everything verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
