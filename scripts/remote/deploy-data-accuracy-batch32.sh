#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 32 (device-by-MAC page) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #89 /devices/mac/<mac> crashed on every visit (the client read the {device} and {traffic}
#       wrappers) and its in/out and per-destination bytes were missing from the daemon reply
#
# The daemon and the web container are rebuilt. The check reads the router MAC's traffic for a
# fixed past day: in + out = total, and the connection and top-destination figures are
# bracketed by OpenSearch with the same filter. Then open /devices/mac/d0:21:f9:5e:35:32.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch32.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '24 hours ago 15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
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

MAC="D0:21:F9:5E:35:32"
MAC_PATH="/api/devices/registry/$MAC/traffic?$RANGE"

echo "=== Deploy: dashboard data accuracy, batch 32 (device-by-MAC page) ==="
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
IPS=$(api "/api/devices/registry/$MAC" "json.dumps(d['device']['ips'])")
case "$IPS" in \[*\]) ;; *) echo "   ✗ could not read the device: $IPS"; exit 1 ;; esac
# The daemon's filter: the MAC in either case, or any of the device's IPs, as source
WHO=$(api "/api/devices/registry/$MAC" "json.dumps({'bool': {'should': [{'term': {'source.mac': sys.argv[3]}}, {'term': {'source.mac': sys.argv[3].lower()}}] + [{'term': {'source.ip': ip}} for ip in d['device']['ips']], 'minimum_should_match': 1}})" "$MAC")
CONN_ONLY='{"term":{"event.dataset":"conn"}}'
SUMS=$(api "$MAC_PATH" "(d['traffic']['inbound_bytes'] + d['traffic']['outbound_bytes'], int(d['traffic']['total_bytes']))")
IN_OUT=$(printf '%s' "$SUMS" | tr -d '() ' | cut -d, -f1)
TOTAL=$(printf '%s' "$SUMS" | tr -d '() ' | cut -d, -f2)
if [[ "${IN_OUT:-x}" =~ ^[0-9]+$ ]] && [ "$IN_OUT" = "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then rc=0; else rc=1; fi
check "#89 inbound + outbound = total" "$rc" "in + out $IN_OUT, total $TOTAL"
bracket "#89 connections for $MAC" "$WHO,$CONN_ONLY" "" "$MAC_PATH" "d['traffic']['connection_count']"
TOP=$(api "$MAC_PATH" "d['traffic']['top_destinations'][0]['ip']")
[[ "$TOP" =~ ^[0-9a-fA-F:.]+$ ]] || { echo "   ✗ no top destination: $TOP"; exit 1; }
raw_bytes() {  # sums the two "value" fields; track_total_hits false keeps hits.total's out of the reply
    sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        -H 'Content-Type: application/json' "https://localhost:9200/arkime_sessions3-*/_search" \
        -d "{\"size\":0,\"track_total_hits\":false,\"query\":{\"bool\":{\"filter\":[{\"range\":{\"@timestamp\":{\"gte\":\"$FROM_TS\",\"lte\":\"$TO_TS\"}}},$WHO,$CONN_ONLY,{\"term\":{\"destination.ip\":\"$TOP\"}}]}},\"aggs\":{\"o\":{\"sum\":{\"field\":\"source.bytes\"}},\"i\":{\"sum\":{\"field\":\"destination.bytes\"}}}}" \
        | grep -o '"value":[0-9.]*' | cut -d: -f2 | awk '{s += $1} END {printf "%d", s}'
}
R1=$(raw_bytes); V=$(api "$MAC_PATH" "d['traffic']['top_destinations'][0]['bytes']"); R2=$(raw_bytes)
if [[ "${R1:-x}" =~ ^[0-9]+$ && "${V:-x}" =~ ^[0-9]+$ && "${R2:-x}" =~ ^[0-9]+$ ]] && [ "$R1" -le "$V" ] && [ "$V" -le "$R2" ]; then rc=0; else rc=1; fi
check "#89 top destination bytes ($TOP)" "$rc" "API $V, OpenSearch $R1 / $R2"
CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://localhost/devices/mac/$MAC")
case "$CODE" in 200|302|303) rc=0 ;; *) rc=1 ;; esac
check "/devices/mac/$MAC answers" "$rc" "HTTP $CODE"
echo ""

echo "→ Step 4: Page figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 5: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 32 deployed and verified — open /devices/mac/d0:21:f9:5e:35:32 ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
