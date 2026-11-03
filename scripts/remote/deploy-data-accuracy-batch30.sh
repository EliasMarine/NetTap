#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 30 (Security Posture encryption and DNS) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #86 Security Posture judged encryption by Zeek service names (QUIC and unparsed TLS on 443
#       counted as plaintext; pings and discovery in the denominator: 19% on the G11), and DNS
#       Security could never pass 0%. The protocols endpoint now returns both figures with the
#       IoT pages' encryption rule, and the page uses them.
#
# The daemon and the web container are rebuilt. Each figure is bracketed by an OpenSearch count
# built from the same rule, for a fixed past day.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch30.sh
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

count_body() {  # count_body <encryption|encrypted|dns_plain|dns_over_tls> → _count body built from the daemon's rule
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys
from services.iot_monitor import ENCRYPTED_CONN_FILTER, LOCAL_CHATTER_EXCLUSION, NO_PAYLOAD_PROTOCOLS
from services.dns_analytics import LOCAL_NAME_SERVICE_PORTS
base = [{'range': {'@timestamp': {'gte': sys.argv[2], 'lte': sys.argv[3]}}},
        {'term': {'event.provider': 'zeek'}}, {'term': {'event.dataset': 'conn'}}]
eligible_out = [*LOCAL_CHATTER_EXCLUSION, {'terms': {'network.protocol': NO_PAYLOAD_PROTOCOLS}}]
q = {
    'encryption': {'filter': base, 'must_not': eligible_out},
    'encrypted': {'filter': [*base, ENCRYPTED_CONN_FILTER], 'must_not': eligible_out},
    'dns_plain': {'filter': [*base, {'term': {'network.protocol': 'dns'}}],
                  'must_not': [{'terms': {'destination.port': LOCAL_NAME_SERVICE_PORTS}}]},
    'dns_over_tls': {'filter': [*base, {'term': {'destination.port': 853}}]},
}[sys.argv[1]]
print(json.dumps({'query': {'bool': q}}))" "$1" "$FROM_TS" "$TO_TS" 2>&1
}

raw() {  # raw <figure> → OpenSearch count
    sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        -H 'Content-Type: application/json' "https://localhost:9200/arkime_sessions3-*/_count" -d "$(count_body "$1")" \
        | grep -o '"count":[0-9]*' | cut -d: -f2
}

VALUE=""
bracket() {  # bracket "label" <figure> <expr on the reply d>: raw before ≤ API ≤ raw after; sets VALUE
    local r1 v r2 rc
    r1=$(raw "$2"); v=$(api "/api/traffic/protocols?$RANGE" "$3"); r2=$(raw "$2")
    if [[ "${r1:-x}" =~ ^[0-9]+$ && "${v:-x}" =~ ^[0-9]+$ && "${r2:-x}" =~ ^[0-9]+$ ]] && [ "$r1" -le "$v" ] && [ "$v" -le "$r2" ]; then rc=0; else rc=1; fi
    check "$1" "$rc" "API $v, OpenSearch $r1 / $r2"
    VALUE="$v"
}

echo "=== Deploy: dashboard data accuracy, batch 30 (Security Posture encryption and DNS) ==="
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
bracket "#86 connections that can be encrypted" encryption "d['encryption']['eligible']"; ELIGIBLE=$VALUE
bracket "#86 encrypted connections" encrypted "d['encryption']['encrypted']"; ENCRYPTED=$VALUE
bracket "#86 plain DNS lookups" dns_plain "d['dns']['plain']"; PLAIN=$VALUE
bracket "#86 DNS-over-TLS connections" dns_over_tls "d['dns']['over_tls']"; DOT=$VALUE
if [[ "${ELIGIBLE:-x}" =~ ^[0-9]+$ && "${ENCRYPTED:-x}" =~ ^[0-9]+$ && "${PLAIN:-x}" =~ ^[0-9]+$ && "${DOT:-x}" =~ ^[0-9]+$ ]]; then
    echo "   → Security Posture will show: Encryption $(( ELIGIBLE > 0 ? (200 * ENCRYPTED / ELIGIBLE + 1) / 2 : 100 ))%, DNS Security $(( PLAIN + DOT > 0 ? (200 * DOT / (PLAIN + DOT) + 1) / 2 : 100 ))%"
fi
CODE=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/compliance)
case "$CODE" in 200|302|303) rc=0 ;; *) rc=1 ;; esac
check "/compliance answers" "$rc" "HTTP $CODE"
echo ""

echo "→ Step 4: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 30 deployed and verified — open /compliance to see the new Encryption and DNS cards ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
