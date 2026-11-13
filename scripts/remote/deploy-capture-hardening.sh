#!/usr/bin/env bash
# Deploy the capture-container fixes (NET-220, NET-206, NET-189) and check each one on the device.
#
# Rebuilds zeek-live (its binaries keep CAP_NET_RAW only), the daemon (the streamed filtered
# download) and the web UI (the download window on PCAP Search). Recreates those three plus
# suricata-live (its engine counters are on). Records the revision it started from and prints
# the rollback commands at the end.
#   - NET-220: zeek holds CAP_NET_RAW only (file capability, every process, the container's
#              cap_add), has a 3 GiB memory limit, and still captures (conn.log grows, no
#              "Operation not permitted", the same zeek processes for 3 minutes);
#   - NET-206: Suricata answers dump-counters, its kernel packet counter grows, and the merged
#              config has stats on every 10 s with no stats.log written;
#   - NET-189: a filtered download over a window spanning two capture files streams both files'
#              packets, sent the way the page's download window sends it (verify_pcap_download.py);
#              a second download while one runs is turned away; the page's default request;
#              afterwards nettap-tshark's /tmp holds nothing (no FIFO, no merged file).
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-capture-hardening.sh
# To test a branch first: BRANCH=<branch> bash …
# Afterwards, with a sustained download on the dev Mac: bash scripts/remote/measure-capture-loss.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
VERIFY_DOWNLOAD="$REPO_DIR/scripts/remote/verify_pcap_download.py"
SOCKET="/var/run/suricata/suricata-command.socket"
CONN_LOG="/zeek/live/spool/logger-1/conn.log"
STABLE_SECONDS=180
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

zeek_pids() {  # the zeek processes' host PIDs, sorted, on one line
    sudo docker top nettap-zeek-live -eo pid,comm 2>/dev/null | awk '$2 == "zeek" { print $1 }' | sort -n | tr '\n' ' '
}

kernel_packets() {  # Suricata's total capture.kernel_packets (the first, before the per-thread ones)
    sudo docker exec nettap-suricata-live suricatasc "$SOCKET" -c dump-counters 2>/dev/null \
        | grep -o '"kernel_packets": *[0-9]*' | head -n 1 | grep -o '[0-9]*$'
}

echo "=== Deploy: capture hardening, Suricata counters, filtered download ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
PREVIOUS=$(git rev-parse HEAD)
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo "   (started from $PREVIOUS)"
echo ""

echo "→ Step 2: Build zeek-live, the daemon and the web UI..."
if ! "${COMPOSE[@]}" build zeek-live nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted (the zeek-live build stops if Malcolm's setcap lines changed)"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate zeek-live, suricata-live, the daemon and the web UI..."
SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RECREATED=$(date +%s)
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web zeek-live suricata-live
echo ""

echo "→ Step 4: Wait for the daemon and the web UI to become healthy..."
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB" = "healthy" ] && [ "$DAEMON" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB daemon=$DAEMON ($i/30)"
    sleep 5
done
expect "nettap-web" "$WEB" healthy
expect "nettap-storage-daemon" "$DAEMON" healthy
for c in nettap-zeek-live nettap-suricata-live; do
    expect "$c running" "$(sudo docker inspect --format='{{.State.Status}}' "$c" 2>/dev/null || echo missing)" running
done
sudo docker exec nettap-web grep -rlq "Download from" /app/build
check "the web bundle has PCAP Search's download window" $?
echo ""

echo "→ Step 5: NET-220 — zeek holds CAP_NET_RAW only, with a memory limit..."
expect "getcap zeek" "$(sudo docker exec nettap-zeek-live getcap /usr/local/zeek/bin/zeek)" "/usr/local/zeek/bin/zeek cap_net_raw=eip"
expect "getcap capstats" "$(sudo docker exec nettap-zeek-live getcap /usr/local/zeek/bin/capstats)" "/usr/local/zeek/bin/capstats cap_net_raw=eip"
expect "cap_add" "$(sudo docker inspect --format='{{json .HostConfig.CapAdd}}' nettap-zeek-live)" '["CAP_NET_RAW"]'
expect "memory limit" "$(sudo docker inspect --format='{{.HostConfig.Memory}}' nettap-zeek-live)" 3221225472
echo "   waiting up to 3 minutes for Zeek to write conn.log..."
GREW=1
for i in $(seq 1 36); do
    MTIME=$(sudo docker exec nettap-zeek-live stat -c %Y "$CONN_LOG" 2>/dev/null || echo 0)
    if [ "$MTIME" -gt "$RECREATED" ]; then GREW=0; break; fi
    sleep 5
done
check "conn.log written since the recreate" "$GREW" "mtime $MTIME, recreated $RECREATED"
PIDS=$(zeek_pids)
STABLE_FROM=$(date +%s)
if [ -z "$PIDS" ]; then check "zeek processes" 1 "none running"; fi
for pid in $PIDS; do
    expect "zeek $pid CapEff" "$(awk '/^CapEff/ { print $2 }' "/proc/$pid/status" 2>/dev/null)" 0000000000002000
done
DENIED=$(sudo docker logs --since "$SINCE" nettap-zeek-live 2>&1 | grep -c "Operation not permitted")
expect "\"Operation not permitted\" in the zeek-live log" "$DENIED" 0
echo ""

echo "→ Step 6: NET-206 — Suricata's engine counters..."
echo "   waiting up to 3 minutes for Suricata to load its rules and answer..."
FIRST=""
for i in $(seq 1 36); do
    FIRST=$(kernel_packets)
    if [ -n "$FIRST" ]; then break; fi
    sleep 5
done
if [ -z "$FIRST" ]; then
    check "dump-counters answers" 1 "$(sudo docker exec nettap-suricata-live suricatasc "$SOCKET" -c dump-counters 2>&1 | head -c 200)"
else
    check "dump-counters answers" 0 "kernel_packets $FIRST"
    sleep 15
    SECOND=$(kernel_packets)
    if [ -n "$SECOND" ] && [ "$SECOND" -gt "$FIRST" ]; then GROWS=0; else GROWS=1; fi
    check "capture.kernel_packets grows over 15 s" "$GROWS" "$FIRST -> ${SECOND:-none}"
fi
CONFIG=$(sudo docker exec nettap-suricata-live suricata --dump-config -c /etc/suricata/suricata.yaml 2>/dev/null)
expect "stats.enabled" "$(echo "$CONFIG" | awk -F' = ' '$1 == "stats.enabled" { print $2 }')" yes
expect "stats.interval" "$(echo "$CONFIG" | awk -F' = ' '$1 == "stats.interval" { print $2 }')" 10
STATS_LOGS=$(sudo docker exec nettap-suricata-live find /var/log/suricata -name 'stats.log*' | wc -l)
expect "stats.log files written" "$STATS_LOGS" 0
echo ""

echo "→ Step 7: NET-189 — the filtered download..."
# shellcheck disable=SC2024  # the script is read as this user on purpose; only docker needs sudo
sudo docker exec -i nettap-storage-daemon python3 - < "$VERIFY_DOWNLOAD" 2>&1 | grep -v "Warning"
STATUS=${PIPESTATUS[0]}
check "verify_pcap_download.py" "$STATUS" "exit $STATUS"
echo ""

echo "→ Step 8: NET-220 — zeek keeps running..."
WAITED=$(( $(date +%s) - STABLE_FROM ))
if [ "$WAITED" -lt "$STABLE_SECONDS" ]; then
    echo "   waiting $(( STABLE_SECONDS - WAITED )) s more (3 minutes in all)..."
    sleep $(( STABLE_SECONDS - WAITED ))
fi
expect "the same zeek processes after 3 minutes" "$(zeek_pids)" "$PIDS"
expect "zeek-live restarts" "$(sudo docker inspect --format='{{.RestartCount}}' nettap-zeek-live)" 0
MTIME=$(sudo docker exec nettap-zeek-live stat -c %Y "$CONN_LOG" 2>/dev/null || echo 0)
if [ $(( $(date +%s) - MTIME )) -lt 120 ]; then FRESH=0; else FRESH=1; fi
check "conn.log still being written" "$FRESH" "last write $(( $(date +%s) - MTIME )) s ago"
echo "   memory.peak since the recreate: $(sudo docker exec nettap-zeek-live cat /sys/fs/cgroup/memory.peak 2>/dev/null) bytes"
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon|nettap-zeek-live|nettap-suricata-live"
echo ""

echo "By hand, in a browser: PCAP Search › type the filter tcp › check \"Download from\" and \"to\" show ›"
echo "set a 20 s window from a few minutes ago › Download filtered › open the file in Wireshark: its"
echo "packets are inside the window and come from both capture files around it."
echo ""
echo "Rollback (zeek-live's image and compose roll back together):"
echo "  git -C $REPO_DIR checkout $PREVIOUS"
echo "  cd $REPO_DIR && sudo docker compose -f docker/docker-compose.yml build zeek-live nettap-storage-daemon nettap-web"
echo "  cd $REPO_DIR && sudo docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-storage-daemon nettap-web zeek-live suricata-live"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo "Next, with a sustained download running on the dev Mac: bash scripts/remote/measure-capture-loss.sh"
