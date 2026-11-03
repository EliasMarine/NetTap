#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 12 (DNS heuristics) and check it on the box.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #35 Threats "DGA suspects" scores the registered name (not the leftmost hostname label),
#       skips single-label LAN hostnames and hyphenated compound names
#   #35 DNS "Suspicious" skips reverse lookups (*.in-addr.arpa, *.ip6.arpa) and Plex's
#       per-server *.plex.direct names
#
# Only the daemon restarts. Capture (netsniff, Zeek, Suricata) is not touched.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch12.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

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

echo "=== Deploy: dashboard data accuracy, batch 12 (DNS heuristics) ==="
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

echo "→ Step 2: Build the daemon image..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Image built"
echo ""

echo "→ Step 3: Recreate the daemon..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon
wait_healthy nettap-storage-daemon
echo ""

echo "→ Step 4: Check the DNS findings (last 24 h)..."
# Read inside the daemon container: the replies can be too big to pass back as an argument
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
token = open('/run/nettap-auth/daemon-token').read().strip()
now = datetime.now(timezone.utc)
q = urllib.parse.urlencode({'from': (now - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ'), 'to': now.strftime('%Y-%m-%dT%H:%M:%SZ')})
def get(path):
    req = urllib.request.Request('http://localhost:8880' + path + '?' + q, headers={'X-NetTap-Daemon-Token': token})
    return json.load(urllib.request.urlopen(req, timeout=120))
try:
    dga = [f['domain'] for f in get('/api/threats/dns-anomalies')['dga_suspects']]
    sus = [(f['type'], f['domain']) for f in get('/api/dns/suspicious')['suspicious']]
except Exception as e:
    print('ERR', e)
    raise SystemExit
for d in dga:
    print('DGA', d)
for t, d in sus:
    print('SUSPICIOUS', t, d)
bad_dga = [d for d in dga if '.' not in d or any(k in d for k in ('forter.com', 'online-metrix.net', 'figma.com', 'datadoghq.com'))]
bad_sus = [d for _, d in sus if d.rstrip('.').endswith(('.in-addr.arpa', '.ip6.arpa', '.plex.direct'))]
print('SUMMARY', len(dga), len(bad_dga), len(sus), len(bad_sus))
" 2>&1)
while IFS= read -r line; do echo "   $line"; done <<<"$OUT"
read -r _ NDGA BADDGA NSUS BADSUS <<<"$(echo "$OUT" | grep '^SUMMARY')"
if [ -n "${BADDGA:-}" ] && [ "$BADDGA" -eq 0 ]; then rc=0; else rc=1; fi
check "#35 DGA suspects: no single-label or known-real names" "$rc" "${NDGA:-?} listed, ${BADDGA:-?} false positives of the kinds fixed"
if [ -n "${BADSUS:-}" ] && [ "$BADSUS" -eq 0 ]; then rc=0; else rc=1; fi
check "#35 Suspicious DNS: no reverse lookups or plex.direct" "$rc" "${NSUS:-?} listed, ${BADSUS:-?} reverse/plex entries"
echo ""

echo "→ Step 5: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|suricata-live|zeek-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 12 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
