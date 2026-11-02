#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 31 (Device detail time range, risk proxies) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #87 Device detail's 24h / 7d / 30d buttons had no handlers: every figure was always 24 h
#   #88 The risk score proxies dropped from/to/limit (web side; covered by unit tests)
#
# The daemon and the web container are rebuilt. The check reads the router's Device detail for
# the 7d window and brackets it by OpenSearch, and checks the bandwidth chart's bucket count.
# Then click 7d on /devices/192.168.1.1: the figures must change and times show dates.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch31.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
# The 7d button's window
FROM_TS=$(date -u -d '7 days ago 15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
RANGE="from=$FROM_TS&to=$TO_TS"

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

echo "=== Deploy: dashboard data accuracy, batch 31 (Device detail time range) ==="
echo "   7-day window: $FROM_TS → $TO_TS"
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

echo "→ Step 2: Build and recreate the daemon and the web container..."
for svc in nettap-storage-daemon nettap-web; do
    if ! "${COMPOSE[@]}" build "$svc"; then
        echo "   ✗ $svc build failed — nothing was restarted"
        exit 1
    fi
done
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
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

echo "→ Step 3: Checks..."
IP=192.168.1.1
bracket "#87 Device detail connections, 7 days ($IP)" "$(src "$IP"),$CONN" "" \
    "/api/devices/$IP?$RANGE" "d['device']['connection_count']"
bracket "#87 Device connections list total, 7 days ($IP)" "$(either "$IP"),$CONN" "" \
    "/api/devices/$IP/connections?$RANGE&size=1" "d['total']"
bracket "#87 Risk score connections, 7 days ($IP)" "$(src "$IP"),$CONN" "" \
    "/api/risk/scores/$IP?$RANGE" "d['connection_count']"
POINTS=$(api "/api/devices/$IP?$RANGE" "len(d['device'].get('bandwidth_series') or [])")
if [[ "${POINTS:-x}" =~ ^[0-9]+$ ]] && [ "$POINTS" -ge 160 ] && [ "$POINTS" -le 175 ]; then rc=0; else rc=1; fi
check "#87 7-day bandwidth chart uses hourly points" "$rc" "$POINTS points (5-minute points would be 2,016)"
DAY=$(api "/api/devices/$IP" "d['device']['connection_count']")
WEEK=$(api "/api/devices/$IP?$RANGE" "d['device']['connection_count']")
if [[ "${DAY:-x}" =~ ^[0-9]+$ && "${WEEK:-x}" =~ ^[0-9]+$ ]] && [ "$WEEK" -ge "$DAY" ]; then rc=0; else rc=1; fi
check "#87 7 days covers at least the last day" "$rc" "24 h $DAY, 7 d $WEEK"
echo ""

echo "→ Step 4: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 31 deployed and verified — on /devices/192.168.1.1 click 7d: figures change, times show dates ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
