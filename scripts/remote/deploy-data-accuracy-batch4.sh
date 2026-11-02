#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 4 (daemon and web) and check each fix.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# Batch 4: IoT findings ignore local chatter, certificates come from Zeek x509,
# TShark hex dump. Capture is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch4.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
OS_CURL=(sudo docker exec nettap-opensearch curl -s
    --config /var/local/curlrc/.opensearch.primary.curlrc
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure
    -H "Content-Type: application/json")
FAILED=0

api() {  # api <path> [json body for POST]
    local token
    token=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)
    if [ $# -gt 1 ]; then
        curl -s -m 120 -H "X-NetTap-Daemon-Token: $token" -H "Content-Type: application/json" -d "$2" "http://localhost:8880$1"
    else
        curl -s -m 60 -H "X-NetTap-Daemon-Token: $token" "http://localhost:8880$1"
    fi
}

jq_py() {  # jq_py '<python expression over d>' — evaluates against JSON on stdin, inside the daemon container
    sudo docker exec -i nettap-storage-daemon python3 -c "import json,sys
try:
    d = json.load(sys.stdin)
    print($1)
except Exception as e:
    print('ERR', e)"
}

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

wait_healthy() {
    local name="$1" status="unknown"
    for i in $(seq 1 36); do
        status=$(sudo docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "unknown")
        [ "$status" = "healthy" ] && break
        [ $((i % 6)) -eq 0 ] && echo "   waiting... $name=$status ($i/36)"
        sleep 5
    done
    if [ "$status" = "healthy" ]; then rc=0; else rc=1; fi
    check "$name health" "$rc" "$status"
}

echo "=== Deploy: dashboard data accuracy, batch 4 ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt (re-run if it was a network timeout)"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the daemon and web images..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the daemon and web..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for health..."
wait_healthy nettap-storage-daemon
wait_healthy nettap-web
echo ""

echo "→ Step 5: Check each fix..."
AUDIT=$(api /api/iot/protocol-audit)
BAD_FINDINGS=$(printf '%s' "$AUDIT" | jq_py "sum(1 for dev in d.get('devices', []) for f in dev.get('findings', []) if f.get('type') == 'unencrypted_traffic' or f.get('port') == 0)")
if [ "$BAD_FINDINGS" = "0" ]; then rc=0; else rc=1; fi
check "#34 IoT protocol audit has no port-0 or duplicate encryption findings" "$rc" "bad findings=$BAD_FINDINGS"

ISO=$(api /api/iot/network-isolation)
ICMP_PORTS=$(printf '%s' "$ISO" | jq_py "sum(1 for p in d.get('pairs', []) if set(p.get('ports', [])) & {0, 3, 8, 11})")
if [ "$ICMP_PORTS" = "0" ]; then rc=0; else rc=1; fi
check "#34 IoT isolation shows no ICMP codes as ports" "$rc" "pairs with ICMP-code ports=$ICMP_PORTS"
echo "     isolation: $(printf '%s' "$ISO" | jq_py "'score %s, pairs by risk %s' % (d.get('segmentation_score'), {r: sum(1 for p in d.get('pairs', []) if p['risk'] == r) for r in ('critical', 'high', 'medium', 'low')})")"

STATS=$(api /api/certificates/stats)
CERT_TOTAL=$(printf '%s' "$STATS" | jq_py "d.get('total_certs')")
LIST_COUNT=$(api /api/certificates | jq_py "d.get('count')")
X509_Q='{"size":0,"query":{"bool":{"filter":[{"range":{"@timestamp":{"gte":"now-7d"}}},{"term":{"event.dataset":"x509"}},{"terms":{"zeek.x509.host_cert":["true","T"]}}]}},"aggs":{"fp":{"cardinality":{"field":"zeek.x509.fingerprint"}}}}'
TRUTH=$("${OS_CURL[@]}" "https://localhost:9200/arkime_sessions3-*/_search" -d "$X509_Q" | grep -o '"fp":{"value":[0-9]*' | grep -o '[0-9]*$')
# a few seconds apart, so allow 2 new certificates
if [ -n "$TRUTH" ] && [ "$TRUTH" -gt 0 ] && [ "${CERT_TOTAL:-x}" -ge $((TRUTH - 2)) ] 2>/dev/null && [ "$CERT_TOTAL" -le $((TRUTH + 2)) ] && [ "$LIST_COUNT" = "$CERT_TOTAL" ]; then rc=0; else rc=1; fi
check "#14 certificate count = distinct x509 certificates" "$rc" "card=${CERT_TOTAL:-?} list=${LIST_COUNT:-?} OpenSearch=${TRUTH:-?}"
echo "     certificates: $(printf '%s' "$STATS" | jq_py "'expiring %s, expired %s, self-signed %s, issuer changes %s' % (d.get('expiring_count'), d.get('expired_count'), d.get('self_signed_count'), d.get('issuer_changes_count'))")"

PCAP=$(api /api/tshark/pcaps | jq_py "d['pcaps'][0]['path'] if d.get('pcaps') else ''")
if [ -n "$PCAP" ] && [ "${PCAP#ERR}" = "$PCAP" ]; then
    HEX=$(api /api/tshark/analyze "{\"pcap_path\": \"$PCAP\", \"max_packets\": 3, \"include_hex\": true}" | jq_py "sum(1 for p in d.get('packets', []) if p.get('_source', {}).get('layers', {}).get('frame_raw'))")
    if [ "${HEX:-0}" -gt 0 ] 2>/dev/null; then rc=0; else rc=1; fi
    check "#40 TShark returns raw bytes for the hex dump" "$rc" "packets with frame_raw=$HEX ($(basename "$PCAP"))"
else
    check "#40 TShark returns raw bytes for the hex dump" 1 "no PCAP file listed ($PCAP)"
fi
echo ""

echo "→ Step 6: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 4 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
