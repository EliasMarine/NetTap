#!/usr/bin/env bash
# Read-only: how much memory PCAP Search's tshark needs on today's 256 MB capture files (#137).
# Picks the files with the most packets among the newest 60 (packet count, not size, drives
# tshark's memory), then runs PCAP Search's own command on each in a throwaway container with
# the TShark container's memory and CPU limits, and reports time and peak memory.
#
# The full output is also saved to ~/nettap-pcap-headroom.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/measure-pcap-search-headroom.sh
set -u
exec > >(tee "$HOME/nettap-pcap-headroom.log") 2>&1

PCAP_DIR=$(sudo docker volume inspect docker_pcap-data --format '{{.Mountpoint}}')
IMAGE=$(sudo docker inspect nettap-tshark --format '{{.Config.Image}}')
MEM=$(sudo docker inspect nettap-tshark --format '{{.HostConfig.Memory}}')
CPUS=$(sudo docker inspect nettap-tshark --format '{{.HostConfig.NanoCpus}}' | awk '{printf "%.2f", $1 / 1e9}')
echo "=== PCAP Search memory headroom on 256 MB files ($IMAGE, $(( MEM / 1048576 )) MiB, $CPUS CPU) ==="
echo ""

echo "→ Step 1: Packet counts of the newest 60 files..."
NEWEST=$(sudo ls -t "$PCAP_DIR" | grep '^mnetsniff-.*\.pcap$' | sed -n '2,61p')
COUNTS=$(sudo docker run --rm --network none -v "$PCAP_DIR:/pcap:ro" --entrypoint sh "$IMAGE" -c '
    for f in "$@"; do printf "%s %s %s\n" "$(capinfos -M -c -T -r "/pcap/$f" 2>/dev/null | cut -f2)" "$(stat -c %s "/pcap/$f")" "$f"; done
' _ $NEWEST)
echo "$COUNTS" | sort -rn | head -5 | awk '{printf "   %9d packets  %4d MiB  %s\n", $1, $2 / 1048576, $3}'
echo ""

echo "→ Step 2: PCAP Search's command on the 5 busiest, same limits as nettap-tshark..."
WORST=0
while read -r PACKETS BYTES NAME; do
    [ -n "${NAME:-}" ] || continue
    OUT=$(sudo docker run --rm --network none --memory "$MEM" --memory-swap "$MEM" --cpus "$CPUS" \
        -v "$PCAP_DIR:/pcap:ro" --entrypoint sh "$IMAGE" -c '
        s=$(date +%s)
        timeout -k 5 300 nice -n 19 tshark -r "/pcap/$1" -Y "http || tls" -T fields -e frame.number >/tmp/out 2>/dev/null
        rc=$?
        echo "$rc $(wc -l < /tmp/out) $(( $(date +%s) - s )) $(( $(cat /sys/fs/cgroup/memory.peak) / 1048576 ))"
    ' _ "$NAME" 2>&1)
    read -r RC MATCHES SECS PEAK <<<"$OUT"
    [ "${PEAK:-0}" -gt "$WORST" ] && WORST=$PEAK
    echo "   $NAME: $PACKETS packets, $(( BYTES / 1048576 )) MiB -> exit $RC, $MATCHES matches, ${SECS} s, peak ${PEAK} MiB"
done <<<"$(echo "$COUNTS" | sort -rn | head -5)"
echo ""
echo "=== Worst peak ${WORST} MiB of $(( MEM / 1048576 )) MiB ==="
