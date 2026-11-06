#!/usr/bin/env bash
# Deploy NET-167, capture packet loss over the last hour instead of since the counters reset.
# Then check the daemon's loss window on the device:
#   - right after the restart it says "measuring" (never a figure from one reading)
#   - after 70 s it is "ok", spans 60-3600 s, never counts more lost than arrived, and never
#     more than the interface has counted since it was created
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-capture-loss-window.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

loss() {  # loss <python expression over the reply `d`>: GET /api/capture/stats with the token
    # The expression is always a literal from this script. The token is read inside the
    # container, inside fetch(): it, the headers and the request are gone before the eval runs
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.error, urllib.request
def fetch(path):
    headers = {'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip()}
    req = urllib.request.Request('http://localhost:8880' + path, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return json.load(r)
    except (urllib.error.URLError, ValueError):
        return {}
d = fetch('/api/capture/stats')
del fetch
print(eval(sys.argv[1]))" "$1" 2>&1 | tail -n 1
}

echo "=== Deploy: capture loss over the last hour (NET-167) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build and recreate the daemon and the web container..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web; then
    echo "   ✗ Could not recreate the containers"
    exit 1
fi
for svc in nettap-storage-daemon nettap-web; do
    STATUS="unknown"
    for _ in $(seq 1 36); do
        STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "unknown")
        [ "$STATUS" = "healthy" ] && break
        sleep 5
    done
    if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
    check "$svc health" "$rc" "$STATUS"
done
echo ""

echo "→ Step 3: Straight after the restart..."
FIRST=$(loss "json.dumps(d.get('loss_window'))")
case "$FIRST" in *'"state": "measuring"'*|*'"state": "ok"'*) rc=0 ;; *) rc=1 ;; esac
check "loss_window answers (measuring, or ok if the sampler already ran twice)" "$rc" "$FIRST"
echo ""

echo "→ Step 4: Waiting 70 s for a window of at least a minute..."
sleep 70
WINDOW=$(loss "json.dumps(d.get('loss_window'))")
echo "   $WINDOW"
VERDICT=$(loss "(lambda w, c: 'OK' if w and w['state'] == 'ok' and 60 <= w['window']['seconds'] <= 3600 and min(w['window']['arrived'], w['window']['lost']) >= 0 and w['window']['lost'] <= w['window']['arrived'] and w['window']['arrived'] <= c and w['interface'] == d.get('capture_interface') else 'BAD')(d.get('loss_window'), d.get('rx_packets', 0) + d.get('rx_missed_errors', 0))")
if [ "$VERDICT" = "OK" ]; then rc=0; else rc=1; fi
check "window is ok, 60-3600 s, lost <= arrived <= the interface's own count, on the capture interface" "$rc" "$VERDICT"
RATE=$(loss "(lambda w: 'none (no packets)' if w['drop_rate_pct'] is None else '%.4f%% of %d packets over %d s' % (w['drop_rate_pct'], w['arrived'], w['seconds']))(d['loss_window']['window'])")
echo "   Loss in the window: $RATE"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed. Open Home and Infrastructure: packet loss now says \"in the last N min\". ==="
else
    echo "=== Deploy complete with ✗ lines above: paste them back. ==="
fi
