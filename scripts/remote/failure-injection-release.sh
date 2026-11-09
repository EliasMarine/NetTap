#!/usr/bin/env bash
# ==========================================================================
# Release check: does NetTap report a failure honestly, and does it recover?
# Run it only with the owner's approval. It stops and restarts parts of the stack:
#   1. stop Suricata    -> health must say "sensor_stopped"; start it -> "fresh" again
#   2. stop Zeek        -> the same
#   3. restart OpenSearch -> health must report it; after it is back, auth, ingestion
#                            and the pipeline must recover with nobody's help
# Effect: no IDS (1) or no connection logs (2) for about two minutes each, and no
# dashboard data while OpenSearch restarts (3). The network path is never touched.
# Each failure is held for HOLD_S seconds so the UI can be looked at.
#
# Run as the normal user (NOT with sudo), on the device:
#   bash scripts/remote/failure-injection-release.sh
# ==========================================================================
set -u

REPO_DIR="/home/nettap/NetTap"
HOLD_S=60
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}
stamp() { date -u '+%H:%M:%S'; }

# as in smoke-test-release.sh: JSON parsed by the daemon container's python3 (the host has none);
# eval only ever sees the fixed expressions written in this script, never data
PY_PROG='import json, sys
try:
    d = json.load(sys.stdin)
    print(eval(sys.argv[1]))
except Exception:
    print("PARSE_ERROR")'
py() { sudo docker exec -i nettap-storage-daemon python3 -c "$PY_PROG" "$1"; }
daemon_get() {
    local token
    token=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)
    # the header goes in on stdin, so the token never shows in ps
    printf 'X-NetTap-Daemon-Token: %s\n' "$token" | curl -s -m 30 -H @- "http://localhost:8880$1"
}

# "<status> <pipeline state> <sensor=state,...>" from the daemon's health
health() {
    daemon_get /api/system/health | py '"%s %s %s" % (d.get("status", "?"), (d.get("pipeline") or {}).get("state", "absent"), ",".join("%s=%s" % (k.replace("nettap-", ""), v) for k, v in sorted(((d.get("pipeline") or {}).get("sensors") or {}).items())))'
}

# wait_for <pipeline state> <max seconds>: prints how long it took, returns 1 on timeout
wait_for() {
    local want="$1" max="$2" start now line
    start=$(date +%s)
    while :; do
        line=$(health)
        now=$(date +%s)
        if [ "$(echo "$line" | cut -d' ' -f2)" = "$want" ]; then
            echo "   $(stamp) after $((now - start))s: $line"
            return 0
        fi
        if [ $((now - start)) -ge "$max" ]; then
            echo "   $(stamp) still not $want after ${max}s: $line"
            return 1
        fi
        sleep 5
    done
}

hold() { echo "   HOLD $1 until $(date -u -d "+${HOLD_S} seconds" '+%H:%M:%S') UTC"; sleep "$HOLD_S"; }

sensor_round() {  # sensor_round <step> <container> <label>
    echo "→ Step $1: Stop $3 ($2)..."
    sudo docker stop "$2" >/dev/null && echo "   $(stamp) stopped"
    wait_for sensor_stopped 60; check "$3 stopped is reported" $? "health says sensor_stopped"
    status=$(health | cut -d' ' -f1)
    check "$3 stopped makes health a problem" "$([ "$status" = "problem" ] && echo 0 || echo 1)" "status $status"
    hold "$3 stopped"
    sudo docker start "$2" >/dev/null && echo "   $(stamp) started again"
    wait_for fresh 180; check "$3 recovery is reported" $? "health back to fresh"
    echo ""
}

echo "=== Failure injection: is a failure reported, and does NetTap recover? ==="
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
echo "   commit $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 1: Baseline..."
wait_for fresh 30; check "baseline" $? "pipeline fresh before anything is stopped"
if [ "$FAILED" -ne 0 ]; then echo "   The pipeline isn't fresh to begin with: nothing was stopped"; exit 1; fi
echo ""

sensor_round 2 nettap-suricata-live Suricata
sensor_round 3 nettap-zeek-live Zeek

echo "→ Step 4: Restart OpenSearch..."
sudo docker restart nettap-opensearch >/dev/null &
RESTART_PID=$!
sleep 5
echo "   $(stamp) during the restart: $(health)"
echo "   $(stamp) web /api/health: $(curl -sk -m 10 https://localhost/api/health)"
hold "OpenSearch restarting"
wait "$RESTART_PID"
for _ in $(seq 1 60); do
    os=$(sudo docker inspect --format '{{.State.Health.Status}}' nettap-opensearch 2>/dev/null)
    [ "$os" = "healthy" ] && break
    sleep 5
done
check "OpenSearch healthy again" "$([ "$os" = "healthy" ] && echo 0 || echo 1)" "docker health $os at $(stamp)"
# the role mapping must survive a restart (Chain 21): an unauthorised reply means services are locked out
auth=$(echo '' | sudo docker exec -i nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc \
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure 'https://localhost:9200/_cluster/health' \
    | py 'd.get("status", "?")')
case "$auth" in
    green|yellow) check "OpenSearch auth after the restart" 0 "cluster health $auth" ;;
    *) check "OpenSearch auth after the restart" 1 "got '$auth' (Unauthorized? see Chain 11/21: bash scripts/remote/fix-opensearch.sh)" ;;
esac
wait_for fresh 600; check "ingestion recovers after OpenSearch" $? "new records indexed and pipeline fresh"
echo ""

echo "→ Step 5: Smoke test (read-only)..."
if ! (set -o pipefail; bash "$REPO_DIR/scripts/remote/smoke-test-release.sh" | sed 's/^/   /'); then
    FAILED=1
fi
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Failure injection complete: every failure was reported and recovered ==="
else
    echo "=== Failure injection finished with failed checks (✗ above) ==="
fi
[ "$FAILED" -eq 0 ]
