#!/usr/bin/env bash
# nettap-pcap-capture was found "Exited (0)" on the G11 (2026-11-06, no PCAP for 21 h).
# With `restart: unless-stopped` a container that exits by itself is restarted, so a lasting
# Exited means something ran `docker stop`. This script shows who could have, then starts the
# capture again ONLY when NetTap's own settings want it on:
#   - PCAP capture enabled in Settings (PCAP_CAPTURE_ENABLED, via /api/capture/status), and
#   - no storage stop flag (the storage manager stops capture at critical disk, CR-018).
# Otherwise it starts nothing and says which setting keeps capture off.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/fix-pcap-capture-stopped.sh
set -u

REPO_DIR="/home/nettap/NetTap"
CONTAINER="nettap-pcap-capture"
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

api() {  # api <path> <python expression over the reply `d`>: GET a daemon route with the token
    # The path and expression are always literals from this script. The token is read inside the
    # container, inside fetch(): it, the headers and the request are gone before the eval runs
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, time, urllib.error, urllib.request
def fetch(path):
    headers = {'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip()}
    req = urllib.request.Request('http://localhost:8880' + path, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return json.load(r)
    except (urllib.error.URLError, ValueError):
        return {}
d = fetch(sys.argv[1])
del fetch
print(eval(sys.argv[2]))" "$1" "$2" 2>&1 | tail -n 1
}

newest_age() {  # seconds since the newest PCAP file was written, or "none"
    api /api/tshark/pcaps "(lambda ps: int(time.time() - max(p['modified'] for p in ps)) if ps else 'none')(d.get('pcaps', []))"
}

echo "=== PCAP capture stopped: find out why, start it if Settings want it on ==="
echo ""
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }

echo "→ Step 1: The container's own record..."
STATE=$(sudo docker inspect --format '{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} restarts={{.RestartCount}}' "$CONTAINER" 2>&1)
echo "   $STATE"
echo "   Restart policy: $(sudo docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$CONTAINER" 2>&1)"
echo ""

echo "→ Step 2: Its last log lines (a stop shows supervisord receiving SIGTERM)..."
sudo docker logs --tail 25 --timestamps "$CONTAINER" 2>&1 | sed 's/^/   /'
echo ""

echo "→ Step 3: Docker's events for it in the last 48 h (kept in memory since Docker last started)..."
EVENTS=$(sudo docker events --since 48h --until "$(date +%s)" --filter "container=$CONTAINER" --format '{{.Time}} {{.Action}}' 2>&1 | tail -n 20)
if [ -n "$EVENTS" ]; then
    echo "$EVENTS" | while read -r t action; do echo "   $(date -u -d "@$t" '+%Y-%m-%d %H:%M:%S UTC') $action"; done
else
    echo "   (none kept)"
fi
echo ""

echo "→ Step 4: Who on the host ran docker stop (shell history and sudo log, last 48 h)..."
sudo journalctl --since "48 hours ago" _COMM=sudo 2>/dev/null | grep -E "docker (compose .*)?(stop|down|kill)" | grep -v "grep" | tail -n 10 | sed 's/^/   /'
echo "   (blank = no sudo docker stop/down/kill in the journal)"
echo ""

echo "→ Step 5: NetTap's own settings..."
ENABLED=$(api /api/capture/status "d.get('enabled')")
echo "   PCAP capture enabled in Settings: $ENABLED"
if sudo docker exec nettap-storage-daemon test -e /opt/nettap/data/storage-stopped-capture 2>/dev/null; then
    FLAG="present"
else
    FLAG="absent"
fi
echo "   Storage stop flag (critical disk, CR-018): $FLAG"
echo "   Disk: $(df -h / | awk 'NR==2 {print $5 " used of " $2}')"
echo "   Newest PCAP written $(newest_age) s ago"
echo ""

echo "→ Step 6: Start capture again if the settings want it on..."
RUNNING=$(sudo docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || echo "unknown")
if [ "$RUNNING" = "true" ]; then
    echo "   It is already running; nothing to start."
elif [ "$ENABLED" != "True" ]; then
    check "capture left off" 1 "Settings say PCAP capture is off ($ENABLED). Turn it on in Settings if you want PCAP; nothing was started"
elif [ "$FLAG" = "present" ]; then
    check "capture left off" 1 "the storage manager stopped it for disk space and will start it when usage drops; nothing was started"
else
    if sudo docker start "$CONTAINER" >/dev/null; then
        echo "   Started $CONTAINER. Waiting 90 s for netsniff to write a file..."
        sleep 90
        AGE=$(newest_age)
        case "$AGE" in ''|none|*[!0-9]*) rc=1 ;; *) if [ "$AGE" -le 120 ]; then rc=0; else rc=1; fi ;; esac
        check "netsniff is writing PCAP again" "$rc" "newest file written ${AGE} s ago"
        STATUS=$(sudo docker inspect --format '{{.State.Status}} restarts={{.RestartCount}}' "$CONTAINER" 2>&1)
        case "$STATUS" in running*) rc=0 ;; *) rc=1 ;; esac
        check "$CONTAINER stays up" "$rc" "$STATUS"
    else
        check "docker start $CONTAINER" 1 "failed; see: sudo docker logs --tail 50 $CONTAINER"
    fi
fi
echo ""

echo "→ Step 7: Container status..."
sudo docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-pcap-capture|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Done: paste this output back (Steps 1-4 say what stopped it) ==="
else
    echo "=== Finished with ✗ lines above: paste this output back ==="
fi
