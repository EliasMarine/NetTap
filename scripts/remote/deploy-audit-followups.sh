#!/usr/bin/env bash
# Deploy the release-audit follow-ups (NET-238, NET-239, NET-240, NET-242, NET-243) and check
# each one on the device.
#
# Rebuilds the web UI and the daemon, and recreates Filebeat (its entrypoint changed; the image
# didn't). Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-audit-followups.sh
# To test a branch first: git checkout <branch> && git pull, then BRANCH=<branch> bash …
# Afterwards: bash scripts/remote/smoke-test-release.sh, and
# bash scripts/remote/measure-alert-latency.sh for NET-243's numbers.
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

api() {  # api PATH EXPRESSION: GET PATH from the daemon with its token, print EXPRESSION over the reply `d`
    # The expression is always a literal from this script. The token is read inside the
    # container, inside fetch(): it, the headers and the request are gone before the eval runs
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.error, urllib.request
def fetch(path):
    headers = {'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip()}
    req = urllib.request.Request('http://localhost:8880' + path, headers=headers)
    try:
        return json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        return {'_status': e.code}
    except (urllib.error.URLError, ValueError):
        return {'_status': 'unreachable'}  # truthy, so no check passes on it
d = fetch(sys.argv[1])
del fetch
print(eval(sys.argv[2]))" "$1" "$2" 2>&1 | tail -n 1
}

echo "=== Deploy: release-audit follow-ups ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web and daemon containers..."
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the web, the daemon and Filebeat..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web nettap-storage-daemon filebeat
echo ""

echo "→ Step 4: Wait for them to become healthy..."
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB" = "healthy" ] && [ "$DAEMON" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB daemon=$DAEMON ($i/30)"
    sleep 5
done
expect "nettap-web" "$WEB" healthy
expect "nettap-storage-daemon" "$DAEMON" healthy
FB=$(sudo docker inspect --format='{{.State.Status}}' nettap-filebeat 2>/dev/null || echo "missing")
expect "nettap-filebeat" "$FB" running
echo ""

echo "→ Step 5: NET-243 — Filebeat's queue flush timeout..."
sleep 5
LINE=$(sudo docker logs nettap-filebeat 2>&1 | grep 'nettap: ' | tail -n 1)
case "$LINE" in *"set to 2s"*) check "wrapper ran" 0 "$LINE" ;; *) check "wrapper ran" 1 "${LINE:-no nettap line in the log}" ;; esac
sudo docker exec nettap-filebeat grep -q 'timeout: 2s' /usr/share/filebeat-logs/filebeat-logs.yml
check "filebeat-logs.yml has timeout: 2s" $?
RUNNING=$(sudo docker exec nettap-filebeat supervisorctl -c /etc/supervisord.conf status filebeat 2>/dev/null | awk '{ print $2 }')
expect "the filebeat program runs" "${RUNNING:-unknown}" RUNNING
echo ""

echo "→ Step 6: NET-238 — capped detections say so instead of failing..."
R=$(api /api/dns/suspicious "d.get('_status') or ('ok' if isinstance(d.get('complete'), bool) else 'no complete key')")
expect "/api/dns/suspicious has complete" "$R" ok
R=$(api /api/threats/intel "d.get('_status') or ('ok' if isinstance(d.get('complete'), bool) else 'no complete key')")
expect "/api/threats/intel has complete" "$R" ok
echo ""

echo "→ Step 7: NET-239 — the score's inputs..."
R=$(api /api/alerts/smart/summary "d.get('_status') or ('ok' if isinstance(d.get('suppressed_findings'), int) and d.get('busier_window_points') in (0, 15) and (d.get('baseline') is None or isinstance(d['baseline'].get('ready'), bool)) else 'missing keys')")
expect "/api/alerts/smart/summary has the new keys" "$R" ok
echo "   $(api /api/alerts/smart/summary "'score %s, %s suppressed findings, +%s busier, baseline %s' % (d.get('threat_score'), d.get('suppressed_findings'), d.get('busier_window_points'), (d.get('baseline') or {}).get('ready'))")"
echo ""

echo "→ Step 8: NET-240 — lateral movement reads open connections..."
R=$(api /api/threats/lateral "d.get('_status') or ('ok' if all('records_without_uid' in m for m in d.get('movements', [])) else 'missing records_without_uid')")
expect "/api/threats/lateral" "$R" ok
echo "   $(api /api/threats/lateral "'%s pairs, complete=%s' % (len(d.get('movements', [])), d.get('complete'))")"
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon|nettap-filebeat"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo "Next: bash scripts/remote/smoke-test-release.sh"
