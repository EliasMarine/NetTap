#!/usr/bin/env bash
# Replay PCAPs through a throwaway copy of the live Suricata and report what it alerts on (NET-191).
# Plan: .codex-review/2026-11-06-detection-accuracy/PLAN.md, "Shared tool".
#
# Nothing live changes. The live container's config and rules are copied out (docker cp) into an
# immutable snapshot; a throwaway container of the same image (no network, 1 GiB, 1 CPU, live
# UID/GID, snapshot mounted read-only at the live paths) replays PCAPs against it. The Python
# half (scripts/remote/verify_detection.py) runs in throwaway containers of that image, never
# on the host.
#
# Run as the normal user (NOT with sudo):
#   bash scripts/remote/verify-detection.sh fixtures              # fixture PCAPs + checks; exit 1 if one fails
#   bash scripts/remote/verify-detection.sh own <pcap-dir>        # replay real PCAPs, report only
# Options after the mode:
#   --rules <dir>        use this rules dir instead of the snapshot's /var/lib/suricata/rules (staged ruleset)
#   --threshold <file>   use this threshold file instead of the device's and make Suricata load it
#                        (tests a threshold file before suricata-live is recreated with it)
# Each run keeps /home/nettap/nettap-replay/<run-id>/ (snapshot/ ~50 MB, pcap/, out/ with report.txt
# and engine/ with eve and suricata.log) so a failed fixture can be inspected.
# Exit: 0 ok, 1 a fixture failed, 2 bad usage or the replay failed, 3 refused to start.
set -u

REPLAY_ROOT="/home/nettap/nettap-replay"
LIVE="nettap-suricata-live"
TIMEOUT_S=600
MIN_AVAILABLE_KIB=$((1536 * 1024))
THRESHOLD_FILE="/etc/nettap/suricata-threshold.config"
MEMINFO="${NETTAP_MEMINFO:-/proc/meminfo}"  # override for tests only
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/verify_detection.py"

usage() {
    sed -n '11,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
}

MODE="${1:-}"
[ $# -gt 0 ] && shift
PCAP_SRC=""
RULES_OVERRIDE=""
THRESHOLD_OVERRIDE=""
case "$MODE" in
    fixtures) ;;
    own) PCAP_SRC="${1:-}"; [ -n "$PCAP_SRC" ] || usage; shift ;;
    *) usage ;;
esac
while [ $# -gt 0 ]; do
    case "$1" in
        --rules) RULES_OVERRIDE="${2:-}"; [ -d "$RULES_OVERRIDE" ] || usage; shift 2 ;;
        --threshold) THRESHOLD_OVERRIDE="${2:-}"; [ -f "$THRESHOLD_OVERRIDE" ] || usage; shift 2 ;;
        *) usage ;;
    esac
done

echo "=== Detection replay ($MODE) ==="
echo ""

echo "→ Step 1: Preflight..."
AVAILABLE_KIB=$(awk '/^MemAvailable:/ {print $2}' "$MEMINFO")
if [ "${AVAILABLE_KIB:-0}" -lt "$MIN_AVAILABLE_KIB" ]; then
    echo "   ✗ Only $((AVAILABLE_KIB / 1024)) MiB available; need 1536 MiB. Not starting."
    exit 3
fi
# shortcut: no rules lock yet (slice 2 adds it), so stay clear of Malcolm's 00:00 UTC rule update
NOW_HHMM=$((10#$(date -u +%H%M)))
if [ "$NOW_HHMM" -ge 2350 ] || [ "$NOW_HHMM" -lt 30 ]; then
    echo "   ✗ $(date -u +%H:%M) UTC is inside 23:50-00:30, around the nightly rule update. Try after 00:30 UTC."
    exit 3
fi
if ! IMAGE=$(sudo docker inspect -f '{{.Config.Image}}' "$LIVE" 2>/dev/null); then
    echo "   ✗ $LIVE not found"
    exit 3
fi
LIVE_ENV=$(sudo docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$LIVE")
PUID=$(printf '%s\n' "$LIVE_ENV" | sed -n 's/^PUID=//p')
PGID=$(printf '%s\n' "$LIVE_ENV" | sed -n 's/^PGID=//p')
PUID=${PUID:-1000}
PGID=${PGID:-1000}
if [ "$(id -u)" != "$PUID" ]; then
    echo "   ✗ Run this as the user with UID $PUID (the live Suricata's), not $(id -un): the replay writes into your run dir as that UID."
    exit 3
fi
echo "   ✓ $((AVAILABLE_KIB / 1024)) MiB available; image $IMAGE; UID:GID $PUID:$PGID"
echo ""

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(cut -c1-8 /proc/sys/kernel/random/uuid)"
RUNNER="nettap-sv-$RUN_ID"
# Ctrl-C or kill: the runner container must not outlive the script
trap 'echo ""; echo "   interrupted, removing $RUNNER"; sudo docker rm -f "$RUNNER" >/dev/null 2>&1; exit 130' INT TERM
RUN="$REPLAY_ROOT/$RUN_ID"
SNAP="$RUN/snapshot"
OUT="$RUN/out"
# The runner writes only $ENGINE (eve, suricata.log, memory.peak). Every file this script writes stays
# in $OUT, so a link the runner plants can't redirect a host write (report.txt, a threshold file).
ENGINE="$OUT/engine"
mkdir -p "$SNAP" "$RUN/pcap" "$ENGINE" || exit 3

echo "→ Step 2: Snapshot the live config and rules into $SNAP..."
# $1 = path in the live container, copied to $SNAP$1. A tar stream keeps the files ours, not root's.
snap_copy() {
    mkdir -p "$SNAP$(dirname "$1")"
    sudo docker cp "$LIVE:$1" - 2>/dev/null | tar -xf - -C "$SNAP$(dirname "$1")" 2>/dev/null
    local rc=("${PIPESTATUS[@]}")
    [ "${rc[0]}" -eq 0 ] && [ "${rc[1]}" -eq 0 ]
}
for path in /etc/suricata /opt/suricata/include-configs /var/lib/suricata/rules; do
    if ! snap_copy "$path"; then
        echo "   ✗ Could not copy $path out of $LIVE"
        exit 2
    fi
    echo "   ✓ $path"
done
# Malcolm's SURICATA_CUSTOM_RULES_DIR: it globs /opt/suricata/rules/**/*.rules (slice 3 mounts custom/ there)
if snap_copy /opt/suricata/rules; then
    echo "   ✓ /opt/suricata/rules (custom rules)"
else
    rm -rf "$SNAP/opt/suricata/rules"
    echo "   - /opt/suricata/rules not present"
fi
mkdir -p "$SNAP/etc/nettap"
if [ -n "$THRESHOLD_OVERRIDE" ]; then
    cp "$THRESHOLD_OVERRIDE" "$SNAP$THRESHOLD_FILE" || exit 2
    echo "   ✓ $THRESHOLD_FILE ← $THRESHOLD_OVERRIDE (override)"
elif [ -f "$THRESHOLD_FILE" ]; then
    cp "$THRESHOLD_FILE" "$SNAP$THRESHOLD_FILE" || exit 2
    echo "   ✓ $THRESHOLD_FILE (host)"
else
    echo "   - $THRESHOLD_FILE not on the host"
fi
echo ""

echo "→ Step 3: PCAPs..."
PY_RUN=(sudo docker run --rm --network none --memory 512m --cpus 1 --user "$PUID:$PGID"
    --cap-drop ALL --security-opt no-new-privileges
    -v "$PY:/opt/verify_detection.py:ro" --entrypoint python3)
if [ "$MODE" = "fixtures" ]; then
    PCAP_DIR="$RUN/pcap"
    "${PY_RUN[@]}" -v "$PCAP_DIR:/pcap" "$IMAGE" /opt/verify_detection.py write-fixtures /pcap || exit 2
else
    PCAP_DIR="$(cd "$PCAP_SRC" 2>/dev/null && pwd)" || { echo "   ✗ $PCAP_SRC is not a directory"; exit 2; }
    COUNT=$(find "$PCAP_DIR" -maxdepth 1 -type f | wc -l)
    [ "$COUNT" -gt 0 ] || { echo "   ✗ No files in $PCAP_DIR"; exit 2; }
    echo "   ✓ $COUNT file(s) in $PCAP_DIR ($(du -sh "$PCAP_DIR" | cut -f1))"
fi
echo ""

RULES_DIR="${RULES_OVERRIDE:+$(cd "$RULES_OVERRIDE" && pwd)}"
RULES_DIR="${RULES_DIR:-$SNAP/var/lib/suricata/rules}"

echo "→ Step 4: Hash every input..."
hash_dir() {  # $1 = label, $2 = dir
    echo "# $1 ($2)"
    (cd "$2" && find . -maxdepth "${3:-64}" -type f -print0 | sort -z | xargs -0 -r sha256sum)
}
{
    hash_dir snapshot "$SNAP"
    [ -n "$RULES_OVERRIDE" ] && hash_dir "rules override, used instead of the snapshot's" "$RULES_DIR"
    hash_dir pcap "$PCAP_DIR" 1
} > "$OUT/sha256.txt"
echo "   ✓ $(grep -vc '^#' "$OUT/sha256.txt") files hashed"
echo ""

# Overrides on the generated suricata.yaml (everything else is used as the device has it):
#   unix-command.enabled=no      the live socket dir (/var/run/suricata) doesn't exist here; no socket wanted
#   detect.sgh-mpm-caching=no    the Hyperscan cache dir (/var/lib/suricata/cache) isn't writable here; only
#                                startup time changes, not detection
#   threshold-file=...           only with --threshold: tests a threshold file before the live include loads it
SETS=(--set unix-command.enabled=no --set detect.sgh-mpm-caching=no)
[ -n "$THRESHOLD_OVERRIDE" ] && SETS+=(--set "threshold-file=$THRESHOLD_FILE")
# Does this run load the device threshold file? Fixtures that need it are SKIPPED otherwise.
if [ ! -f "$SNAP$THRESHOLD_FILE" ]; then
    THRESHOLD_STATE="no $THRESHOLD_FILE on the device yet"
elif [ -n "$THRESHOLD_OVERRIDE" ]; then
    THRESHOLD_STATE="active (--threshold $THRESHOLD_OVERRIDE)"
elif grep -qs "include-configs/nettap.yaml" "$SNAP/etc/suricata/suricata.yaml" &&
    grep -qs "^threshold-file: *$THRESHOLD_FILE" "$SNAP/opt/suricata/include-configs/nettap.yaml"; then
    THRESHOLD_STATE="active (include-configs/nettap.yaml)"
else
    THRESHOLD_STATE="the live suricata.yaml doesn't load $THRESHOLD_FILE yet (suricata-live not recreated with the include)"
fi
echo "$THRESHOLD_STATE" > "$OUT/threshold-state"

echo "→ Step 5: Replay in $RUNNER (no network, 1 GiB, 1 CPU, ${TIMEOUT_S}s max)..."
MOUNTS=(-v "$SNAP/etc/suricata:/etc/suricata:ro"
    -v "$SNAP/opt/suricata/include-configs:/opt/suricata/include-configs:ro"
    -v "$RULES_DIR:/var/lib/suricata/rules:ro"
    -v "$SNAP/etc/nettap:/etc/nettap:ro"
    -v "$PCAP_DIR:/pcap:ro"
    -v "$ENGINE:/out")
if [ -d "$SNAP/opt/suricata/rules" ]; then
    MOUNTS+=(-v "$SNAP/opt/suricata/rules:/opt/suricata/rules:ro")
fi
# /usr/bin/suricata carries file capabilities (net_admin, net_raw, ipc_lock); exec fails with EPERM
# unless they are in the bounding set. no-new-privileges means the process never actually gets them.
# memory.peak is read inside the container before it exits (cgroup v2; includes page cache).
# shellcheck disable=SC2016  # expanded by the container's sh, not here
RUNNER_SH='timeout -k 5 "$0" /usr/bin/suricata "$@"; rc=$?; cat /sys/fs/cgroup/memory.peak > /out/memory.peak 2>/dev/null; exit $rc'
START=$(date +%s)
# shellcheck disable=SC2024  # the console log is written as us, on purpose
sudo docker run --rm --name "$RUNNER" --network none --memory 1g --memory-swap 1g --cpus 1 \
    --user "$PUID:$PGID" --cap-drop ALL --cap-add NET_ADMIN --cap-add NET_RAW --cap-add IPC_LOCK \
    --security-opt no-new-privileges "${MOUNTS[@]}" --entrypoint /bin/sh "$IMAGE" -c "$RUNNER_SH" "$TIMEOUT_S" \
    -c /etc/suricata/suricata.yaml -r /pcap -l /out -k none --runmode single "${SETS[@]}" > "$OUT/runner-console.log" 2>&1 &
# In the background so a signal runs the trap at once (bash defers traps until a foreground command ends)
wait $!
RUNNER_RC=$?
echo "$RUNNER_RC" > "$OUT/runner-exit"
sudo docker rm -f "$RUNNER" >/dev/null 2>&1
if [ "$RUNNER_RC" -eq 0 ]; then
    echo "   ✓ Finished in $(($(date +%s) - START))s"
elif [ "$RUNNER_RC" -eq 124 ] || [ "$RUNNER_RC" -eq 137 ]; then
    echo "   ✗ Timed out after ${TIMEOUT_S}s (exit $RUNNER_RC); see $OUT/runner-console.log"
else
    echo "   ✗ Suricata exited $RUNNER_RC after $(($(date +%s) - START))s; see $OUT/runner-console.log"
fi
echo ""

echo "→ Step 6: Report..."
echo ""
"${PY_RUN[@]}" -v "$OUT:/out:ro" "$IMAGE" /opt/verify_detection.py report "$MODE" /out | tee "$OUT/report.txt"
REPORT_RC=${PIPESTATUS[0]}
echo ""
echo "Run kept in $RUN (report: $OUT/report.txt)"
if [ "$REPORT_RC" -eq 0 ]; then
    echo "=== Replay finished ==="
else
    echo "=== Replay finished with problems (exit $REPORT_RC) — paste this output back ==="
fi
exit "$REPORT_RC"
