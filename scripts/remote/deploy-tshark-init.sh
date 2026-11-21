#!/usr/bin/env bash
# Deploy the TShark container's init process (NET-347) and check it reaps.
#
# nettap-tshark ran `tail -f /dev/null` as PID 1, which never reaps. Every supervised
# job's watchdog was orphaned to it, so zombies piled up until the container hit
# pids.max and every fork failed (PCAP search, preview and packet analysis all broke).
# `init: true` puts Docker's tini in front of tail. This recreates only nettap-tshark
# (--no-deps: OpenSearch and the rest are not touched; no image is built), then checks:
#   - the container runs with an init and its PID 1 is docker-init;
#   - TShark reads a closed capture file;
#   - 20 supervised filter checks through the daemon succeed and leave no zombie behind.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-tshark-init.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

cgroup_dir() {  # the container's cgroup v2 folder on the host
    local cid
    cid=$(sudo docker inspect -f '{{.Id}}' nettap-tshark 2>/dev/null) || return 1
    find /sys/fs/cgroup -maxdepth 4 -type d -name "*${cid}*" 2>/dev/null | head -n 1
}

zombies() {  # zombie children of the container's PID 1, counted on the host
    local init_pid
    init_pid=$(sudo docker inspect -f '{{.State.Pid}}' nettap-tshark 2>/dev/null) || { echo "?"; return; }
    ps -eo ppid=,stat= | awk -v p="$init_pid" '$1 == p && $2 ~ /^Z/' | wc -l
}

echo "=== Deploy: TShark container init (NET-347, $BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
PREVIOUS=$(git rev-parse HEAD)
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo "   (started from $PREVIOUS)"
echo ""

echo "→ Step 2: Before: the old container..."
OLD_DIR=$(cgroup_dir)
echo "   pids.current: $(cat "$OLD_DIR/pids.current" 2>/dev/null || echo '?') of $(cat "$OLD_DIR/pids.max" 2>/dev/null || echo '?')"
echo "   zombies: $(zombies)"
echo ""

echo "→ Step 3: Recreate nettap-tshark with an init (no other container)..."
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-tshark; then
    echo "   ✗ docker compose up failed"
    exit 1
fi
echo "   ✓ Recreated"
echo ""

echo "→ Step 4: Wait for it to become healthy..."
STATUS="unknown"
for i in $(seq 1 30); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-tshark 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    echo "   waiting... tshark=$STATUS ($i/30)"
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then check "nettap-tshark healthy" 0; else check "nettap-tshark healthy" 1 "$STATUS"; fi
echo ""

echo "→ Step 5: The container has an init..."
INIT=$(sudo docker inspect -f '{{.HostConfig.Init}}' nettap-tshark 2>/dev/null)
if [ "$INIT" = "true" ]; then check "HostConfig.Init" 0 "true"; else check "HostConfig.Init" 1 "${INIT:-unset}"; fi
PID1=$(sudo docker exec nettap-tshark cat /proc/1/comm 2>/dev/null)
if [ "$PID1" = "docker-init" ]; then check "PID 1 in the container" 0 "$PID1"; else check "PID 1 in the container" 1 "${PID1:-unreadable}"; fi
echo ""

echo "→ Step 6: TShark reads a closed capture file..."
# The newest file not written to for 2 minutes, so it isn't the one netsniff-ng is filling
FILE=$(sudo docker exec nettap-tshark sh -c "find /pcap -type f \\( -name '*.pcap' -o -name '*.pcapng' \\) -mmin +2 -printf '%T@ %p\\n' | sort -n | tail -n 1 | cut -d' ' -f2-" 2>/dev/null)
if [ -z "$FILE" ]; then
    check "A closed capture file" 1 "none found under /pcap (is capture on?)"
else
    FIRST=$(sudo docker exec nettap-tshark tshark -r "$FILE" -c 1 -T fields -e frame.number 2>/dev/null)
    if [ "$FIRST" = "1" ]; then check "Read $(basename "$FILE")" 0 "frame 1"; else check "Read $(basename "$FILE")" 1 "got '${FIRST}'"; fi
fi
echo ""

echo "→ Step 7: 20 supervised filter checks through the daemon..."
# Run inside the daemon (host network, Python, the token file mounted), so the token never
# appears in a process list on the host
PROBE='
import json, urllib.request
token = open("/run/nettap-auth/daemon-token").read().strip()
body = json.dumps({"filter": "tcp.port == 443"}).encode()
ok = 0
for _ in range(20):
    req = urllib.request.Request(
        "http://localhost:8880/api/packets/check-filter", data=body, method="POST",
        headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as reply:
            ok += reply.status == 200
    except Exception:
        pass
print(ok)
'
BASE_PIDS=$(cat "$(cgroup_dir)/pids.current" 2>/dev/null || echo 0)
OK=$(sudo docker exec nettap-storage-daemon python3 -c "$PROBE" 2>/dev/null || echo 0)
if [ "$OK" = "20" ]; then check "Filter checks answered 200" 0 "20 of 20"; else check "Filter checks answered 200" 1 "${OK:-0} of 20"; fi
echo "   waiting 10 s for the watchdogs to be killed and reaped..."
sleep 10
Z=$(zombies)
if [ "$Z" = "0" ]; then check "Zombies after the checks" 0 "0"; else check "Zombies after the checks" 1 "$Z"; fi
NOW_PIDS=$(cat "$(cgroup_dir)/pids.current" 2>/dev/null || echo '?')
if [ "$NOW_PIDS" != "?" ] && [ "$NOW_PIDS" -le $((BASE_PIDS + 3)) ]; then
    check "pids.current back at its baseline" 0 "$NOW_PIDS (was $BASE_PIDS)"
else
    check "pids.current back at its baseline" 1 "$NOW_PIDS (was $BASE_PIDS)"
fi
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-tshark|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy finished with failures (✗ above) ==="
    echo "To undo only this change: delete the 'init: true' line under nettap-tshark in"
    echo "$REPO_DIR/docker/docker-compose.yml, then run:"
    echo "  ${COMPOSE[*]} up -d --no-deps --force-recreate nettap-tshark"
fi
exit "$FAILED"
