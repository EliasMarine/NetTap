#!/usr/bin/env bash
# Deploy live bandwidth per device (NET-205) and run its release gate on the device.
#
# Rebuilds the daemon (the meter: tc counters on the capture interface, GET /api/live-bandwidth,
# the opt-in setting) and the web container (the live card on both device pages, the switch in
# Settings › Capture). Records the owner's setting, turns it on for the run and puts it back at
# the end, even after a failure. Then, inside the daemon container:
#   - kernel:    the meter's own filter lines count known frames exactly on a throwaway veth pair
#                (802.1Q, tiny and multicast frames, six watches sharing the stages, a reused slot);
#   - bench:     the filters' per-packet cost on that pair, stated (not pass/fail): the median of
#                interleaved paired rounds with its spread, as % of one core at 1 Gbit/s;
#   - lifecycle: a watch starts, stops 20 s after the last poll, the ninth device gets 503, and no
#                qdisc or filter NetTap doesn't own changes;
#   - off:       off means no counters and an off reply; turning off with eight watches removes
#                every NetTap filter within 10 s.
# Capture safety and accuracy run separately (the commands are printed at the end).
# Close every device page while this runs: an open page keeps its watch alive.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-device-live-bandwidth.sh
# To test a branch before it merges: BRANCH=feature/device-live-bandwidth bash ...
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
VERIFY="$REPO_DIR/scripts/remote/verify_live_bandwidth.py"
REFERENCE="$REPO_DIR/scripts/remote/live_bandwidth_reference.py"
FAILED=0
ORIGINAL=""
# GET (no argument) or PUT ("on"/"off") the live bandwidth setting inside the daemon container
# (the image has no curl); prints "on" or "off". The token stays inside the container.
SETTING_PY='import json, sys, urllib.request
body = json.dumps({"enabled": sys.argv[1] == "on"}).encode() if len(sys.argv) > 1 else None
token = open("/run/nettap-auth/daemon-token").read().strip()
request = urllib.request.Request(
    "http://localhost:8880/api/settings/live-bandwidth", data=body, method="PUT" if body else "GET",
    headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"})
print("on" if json.load(urllib.request.urlopen(request, timeout=10))["enabled"] else "off")'

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

run_gate() {  # run_gate MODE: one verify_live_bandwidth.py mode inside the daemon container
    # shellcheck disable=SC2024  # the script is read as this user on purpose; only docker needs sudo
    sudo docker exec -i nettap-storage-daemon python3 - "$1" < "$VERIFY" 2>&1 | grep -v "Warning"
    local status=${PIPESTATUS[0]}
    check "verify_live_bandwidth.py $1" "$status" "exit $status"
}

setting() {  # setting [on|off]
    sudo docker exec nettap-storage-daemon python3 -c "$SETTING_PY" "$@"
}

restore_setting() {  # put the owner's value back; runs on every exit once it was recorded
    trap - EXIT
    local now
    setting "$ORIGINAL" > /dev/null
    now=$(setting)
    echo "   Live bandwidth setting: was ${ORIGINAL}, now ${now:-unknown}"
    if [ "$now" != "$ORIGINAL" ]; then
        echo "   ✗ Could not put it back: set it in Settings › Capture"
        exit 1
    fi
}

echo "=== Deploy: live bandwidth per device (NET-205) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# A failed checkout or pull would rebuild the old code, so stop here instead
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Rebuild the daemon and web containers..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the daemon and web containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for the daemon and web containers to become healthy..."
WEB_STATUS="unknown"
DAEMON_STATUS="unknown"
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
    echo "   ✓ Both containers healthy"
else
    echo "   ✗ Not healthy after 150 s: web=$WEB_STATUS daemon=$DAEMON_STATUS"
    echo "     Logs: sudo docker logs nettap-storage-daemon --tail 50"
    exit 1
fi
echo ""

echo "→ Step 5: Tools and the startup clean-up..."
TC_VERSION=$(sudo docker exec nettap-storage-daemon tc -V 2>&1 | head -n 1)
check "tc in the daemon image" "$([ -n "$TC_VERSION" ] && echo 0 || echo 1)" "$TC_VERSION"
sudo docker logs nettap-storage-daemon --since 5m 2>&1 | grep -i "live bandwidth\|NetTap filter" | tail -n 5
echo ""

echo "→ Step 6: Record the owner's live bandwidth setting and turn it on for the gates..."
ORIGINAL=$(setting)
if [ "$ORIGINAL" != "on" ] && [ "$ORIGINAL" != "off" ]; then
    echo "   ✗ Could not read the setting — nothing was changed and no gate ran"
    exit 1
fi
trap restore_setting EXIT
trap 'exit 130' INT TERM
echo "   ✓ The owner's value: $ORIGINAL (put back at the end, even after a failure)"
NOW=$(setting on)
check "the setting is on for the gates" "$([ "$NOW" = "on" ] && echo 0 || echo 1)" "$NOW"
echo ""

echo "→ Step 7: Kernel semantics on a throwaway veth pair..."
run_gate kernel
echo ""

echo "→ Step 8: Per-packet cost, stated in Settings (about six minutes)..."
run_gate bench
echo ""

echo "→ Step 9: The meter end to end on the capture interface (about a minute)..."
run_gate lifecycle
echo ""

echo "→ Step 10: Turning the setting off removes every counter (about half a minute)..."
run_gate off
echo ""

echo "→ Step 11: Put the owner's setting back..."
restore_setting
echo ""

echo "→ Step 12: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

echo "Still to run by hand (each turns the setting on and puts the owner's value back):"
echo "  Capture safety (about seven minutes; start a sustained download on the dev Mac first):"
echo "    sudo docker exec -i nettap-storage-daemon python3 - capture-safety < $VERIFY"
echo "  Accuracy, once with down and once with up (curl commands: the top of $REFERENCE)."
echo "  Pick N for about 60 s of your line (1 GB is about 80 s at 100 Mbit/s):"
echo "    sudo docker exec -i nettap-storage-daemon python3 - bc:89:c1:e1:8a:d6 150 down 1000000000 < $REFERENCE > reference-down.json"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
    echo "With the setting on (Settings › Capture), a device's page shows live bandwidth every 2 seconds."
else
    echo "=== Deploy finished with failures (✗ above) ==="
    exit 1
fi
