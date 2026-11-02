#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 28 (counts past 10,000) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #83 Device detail's risk score counted at most 10,000 connections, so the four busiest
#       devices showed "high" there and "critical" in the list; the list's network baseline
#       came from fewer devices than the single view's
#   #84 Device detail, its connections list and its alerts list stopped counting at 10,000
#       (the router: 10,000 connections, the device list 48,158)
#
# Only the daemon is rebuilt. Each figure is bracketed by raw OpenSearch counts taken just
# before and after it, for a fixed past day (Zeek still adds late records to a past window).
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch28.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '24 hours ago 15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
RANGE="from=$FROM_TS&to=$TO_TS"
NOISE='{"prefix":{"rule.name":"SURICATA "}}'

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

api() {  # api <path> <python expression on the reply `d`> [value for sys.argv[3]] → value
    # The expression is always a literal from this script; values from the box go in as sys.argv[3]
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + sys.argv[1], headers={'X-NetTap-Daemon-Token': token})
d = json.load(urllib.request.urlopen(req, timeout=300))
print(eval(sys.argv[2]))" "$@" 2>&1
}

raw() {  # raw <filter clauses, comma-separated> <must_not clauses> → count for the window
    sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        -H 'Content-Type: application/json' "https://localhost:9200/arkime_sessions3-*/_count" \
        -d "{\"query\":{\"bool\":{\"filter\":[{\"range\":{\"@timestamp\":{\"gte\":\"$FROM_TS\",\"lte\":\"$TO_TS\"}}},$1],\"must_not\":[$2]}}}" \
        | grep -o '"count":[0-9]*' | cut -d: -f2
}

bracket() {  # bracket "label" <filter> <must_not> <api path> <expr>: raw before ≤ API ≤ raw after
    local r1 v r2 rc
    r1=$(raw "$2" "$3"); v=$(api "$4" "$5"); r2=$(raw "$2" "$3")
    if [[ "${r1:-x}" =~ ^[0-9]+$ && "${v:-x}" =~ ^[0-9]+$ && "${r2:-x}" =~ ^[0-9]+$ ]] && [ "$r1" -le "$v" ] && [ "$v" -le "$r2" ]; then rc=0; else rc=1; fi
    check "$1" "$rc" "API $v, OpenSearch $r1 / $r2"
}

src() { echo "{\"term\":{\"source.ip\":\"$1\"}}"; }
either() { echo "{\"bool\":{\"should\":[{\"term\":{\"source.ip\":\"$1\"}},{\"term\":{\"destination.ip\":\"$1\"}}],\"minimum_should_match\":1}}"; }
CONN='{"term":{"event.provider":"zeek"}},{"term":{"event.dataset":"conn"}}'
ALERT='{"term":{"event.provider":"suricata"}},{"term":{"event.dataset":"alert"}}'

echo "=== Deploy: dashboard data accuracy, batch 28 (counts past 10,000) ==="
echo "   window: $FROM_TS → $TO_TS"
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
PULLED=1
for attempt in 1 2 3 4 5; do
    if git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; then PULLED=0; break; fi
    echo "   pull failed (attempt $attempt/5), retrying in 5 s..."
    sleep 5
done
if [ "$PULLED" -ne 0 ]; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build and recreate the daemon..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
STATUS="unknown"
for _ in $(seq 1 36); do
    STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && break
    sleep 5
done
if [ "$STATUS" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-storage-daemon health" "$rc" "$STATUS"
echo ""

echo "→ Step 3: Pick the busiest devices..."
BUSIEST=$(api "/api/risk/scores?$RANGE" "max(d['devices'], key=lambda x: x['connection_count'])['ip']")
ALERTIEST=$(api "/api/devices?$RANGE&limit=500" "max(d['devices'], key=lambda x: x.get('alert_count') or 0)['ip']")
echo "   most connections: $BUSIEST; most alerts: $ALERTIEST"
for ip in "$BUSIEST" "$ALERTIEST"; do  # they go into URLs and OpenSearch JSON below
    [[ "$ip" =~ ^[0-9a-fA-F:.]+$ ]] || { echo "   ✗ not an IP address: $ip"; exit 1; }
done
echo ""

echo "→ Step 4: Checks..."
bracket "#84 Device detail connections ($BUSIEST)" "$(src "$BUSIEST"),$CONN" "" \
    "/api/devices/$BUSIEST?$RANGE" "d['device']['connection_count']"
bracket "#84 Device connections list total ($BUSIEST)" "$(either "$BUSIEST"),$CONN" "" \
    "/api/devices/$BUSIEST/connections?$RANGE&size=1" "d['total']"
bracket "#84 Device detail alerts ($ALERTIEST)" "$(src "$ALERTIEST"),$ALERT" "$NOISE" \
    "/api/devices/$ALERTIEST?$RANGE" "d['device']['alert_count']"
bracket "#84 Device alerts list total ($ALERTIEST)" "$(either "$ALERTIEST"),$ALERT" "$NOISE" \
    "/api/devices/$ALERTIEST/alerts?$RANGE&limit=1" "d['total']"
bracket "#83 Risk score connections, single view ($BUSIEST)" "$(src "$BUSIEST"),$CONN" "" \
    "/api/risk/scores/$BUSIEST?$RANGE" "d['connection_count']"
LIST=$(api "/api/risk/scores?$RANGE" "next((x['score'], x['level']) for x in d['devices'] if x['ip'] == sys.argv[3])" "$BUSIEST")
ONE=$(api "/api/risk/scores/$BUSIEST?$RANGE" "(d['score'], d['level'])")
if [ "$LIST" = "$ONE" ]; then rc=0; else rc=1; fi
check "#83 Risk score is the same in the list and on Device detail ($BUSIEST)" "$rc" "list $LIST, detail $ONE"
echo ""

echo "→ Step 5: Page figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 28 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
