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

api_eval() {  # api_eval <path> '<python expression over d>' [json body to POST]
    # Fetches and parses inside the daemon container: no host python3, and nothing
    # is piped into sudo (its stdin may carry the password).
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
path, expr = sys.argv[1], sys.argv[2]
body = sys.argv[3].encode() if len(sys.argv) > 3 else None
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + path, data=body,
    headers={'X-NetTap-Daemon-Token': token, 'Content-Type': 'application/json'})
try:
    d = json.load(urllib.request.urlopen(req, timeout=120))
    print(eval(expr))
except Exception as e:
    print('ERR', e)
" "$@"
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
BAD_FINDINGS=$(api_eval /api/iot/protocol-audit "sum(1 for dev in d.get('devices', []) for f in dev.get('findings', []) if f.get('type') == 'unencrypted_traffic' or f.get('port') == 0)")
if [ "$BAD_FINDINGS" = "0" ]; then rc=0; else rc=1; fi
check "#34 IoT protocol audit has no port-0 or duplicate encryption findings" "$rc" "bad findings=$BAD_FINDINGS"

ICMP_PORTS=$(api_eval /api/iot/network-isolation "sum(1 for p in d.get('pairs', []) if set(p.get('ports', [])) & {0, 3, 8, 11})")
if [ "$ICMP_PORTS" = "0" ]; then rc=0; else rc=1; fi
check "#34 IoT isolation shows no ICMP codes as ports" "$rc" "pairs with ICMP-code ports=$ICMP_PORTS"
echo "     isolation: $(api_eval /api/iot/network-isolation "'score %s, pairs by risk %s' % (d.get('segmentation_score'), {r: sum(1 for p in d.get('pairs', []) if p['risk'] == r) for r in ('critical', 'high', 'medium', 'low')})")"

CERT_TOTAL=$(api_eval /api/certificates/stats "d.get('total_certs')")
LIST_COUNT=$(api_eval /api/certificates "d.get('count')")
X509_Q='{"size":0,"query":{"bool":{"filter":[{"range":{"@timestamp":{"gte":"now-7d"}}},{"term":{"event.dataset":"x509"}},{"terms":{"zeek.x509.host_cert":["true","T"]}}]}},"aggs":{"fp":{"cardinality":{"field":"zeek.x509.fingerprint"}}}}'
TRUTH=$("${OS_CURL[@]}" "https://localhost:9200/arkime_sessions3-*/_search" -d "$X509_Q" | grep -o '"fp":{"value":[0-9]*' | grep -o '[0-9]*$')
# a few seconds apart, so allow 2 new certificates
if [ -n "$TRUTH" ] && [ "$TRUTH" -gt 0 ] && [ "${CERT_TOTAL:-x}" -ge $((TRUTH - 2)) ] 2>/dev/null && [ "$CERT_TOTAL" -le $((TRUTH + 2)) ] && [ "$LIST_COUNT" = "$CERT_TOTAL" ]; then rc=0; else rc=1; fi
check "#14 certificate count = distinct x509 certificates" "$rc" "card=${CERT_TOTAL:-?} list=${LIST_COUNT:-?} OpenSearch=${TRUTH:-?}"
echo "     certificates: $(api_eval /api/certificates/stats "'expiring %s, expired %s, self-signed %s, issuer changes %s' % (d.get('expiring_count'), d.get('expired_count'), d.get('self_signed_count'), d.get('issuer_changes_count'))")"

PCAP=$(api_eval /api/tshark/pcaps "d['pcaps'][0]['path'] if d.get('pcaps') else ''")
if [ -n "$PCAP" ] && [ "${PCAP#ERR}" = "$PCAP" ]; then
    HEX=$(api_eval /api/tshark/analyze "sum(1 for p in d.get('packets', []) if p.get('_source', {}).get('layers', {}).get('frame_raw'))" "{\"pcap_path\": \"$PCAP\", \"max_packets\": 3, \"include_hex\": true}")
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
