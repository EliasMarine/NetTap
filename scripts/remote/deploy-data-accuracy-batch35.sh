#!/usr/bin/env bash
# Deploy dashboard data-accuracy batch 35 (exact on every network size; a factual threat baseline) and check it.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   #94 10,000 terms per shard holds a home network's day, not a busier network's. The client
#       now re-runs any search whose terms lists a shard cut short (OpenSearch reports it), with
#       10x longer lists up to 100,000. Checked here on real data: the client starts at 5 terms
#       with OpenSearch's slicing forced on and must end exact.
#   #95 The Threats baseline appended a point per page request; now one per clock hour, live
#       network-wide views only, compared per window length.
#
# Only the daemon is rebuilt. The slicing setting is transient and always put back.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch35.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

echo "=== Deploy: dashboard data accuracy, batch 35 (any network size, factual baseline) ==="
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
BUILT=1
for attempt in 1 2; do
    if "${COMPOSE[@]}" build nettap-storage-daemon; then BUILT=0; break; fi
    echo "   build failed (attempt $attempt/2), retrying..."
done
if [ "$BUILT" -ne 0 ]; then
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

echo "→ Step 3: #94 a cut-short list is counted again until exact (real data, forced slicing)..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import os, sys
sys.path.insert(0, '/opt/nettap/daemon')
from main import _parse_curlrc_credentials
from storage import exact_terms
from storage.exact_terms import ExactTermsOpenSearch
exact_terms.EXACT_SHARD_SIZE = 5  # a network far busier than its lists
c = ExactTermsOpenSearch(os.environ['OPENSEARCH_URL'], verify_certs=False, ssl_show_warn=False, timeout=120,
                         http_auth=_parse_curlrc_credentials(os.environ['OPENSEARCH_CREDS_CONFIG_FILE']))
sent = []
real_search = exact_terms.OpenSearch.search
def spy(self, **kw):
    sent.append(kw['body']['aggs']['t']['terms']['shard_size'])
    return real_search(self, **kw)
exact_terms.OpenSearch.search = spy
q = {'bool': {'filter': [{'range': {'@timestamp': {'gte': 'now-24h'}}}, {'term': {'event.dataset': 'conn'}}]}}
body = {'size': 0, 'query': q, 'aggs': {'t': {'terms': {'field': 'destination.ip', 'size': 20, 'order': {'b': 'desc'}}, 'aggs': {'b': {'sum': {'field': 'source.bytes'}}}}}}
mode = 'search.concurrent_segment_search.mode'
c.cluster.put_settings(body={'transient': {mode: 'all'}})
try:
    got = c.search(index='arkime_sessions3-*', request_cache=False, body=body)['aggregations']['t']
finally:
    c.cluster.put_settings(body={'transient': {mode: None}})
exact_terms.OpenSearch.search = real_search
full = exact_terms.OpenSearch.search(c, index='arkime_sessions3-*', request_cache=False, body={**body, 'aggs': {'t': {'terms': {'field': 'destination.ip', 'size': 65000}, 'aggs': {'b': {'sum': {'field': 'source.bytes'}}}}}})
exact = sorted(((b['b']['value'], b['key']) for b in full['aggregations']['t']['buckets']), reverse=True)[:20]
shown = [(b['b']['value'], b['key']) for b in got['buckets']]
print(int(shown == exact and got['doc_count_error_upper_bound'] == 0), 'shard_size sent', sent, '| top 20 by bytes = exact:', shown == exact, '| error', got['doc_count_error_upper_bound'],
      '| transient after:', c.cluster.get_settings(flat_settings=True)['transient'].get(mode))
" 2>&1)
if [ "${OUT%% *}" = "1" ]; then rc=0; else rc=1; fi
check "#94 adaptive exact counts" "$rc" "${OUT#* }"
echo ""

echo "→ Step 4: #95 the Threats baseline doesn't grow with page requests..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, os, urllib.parse, urllib.request
from datetime import UTC, datetime, timedelta
token = open('/run/nettap-auth/daemon-token').read().strip()
now = datetime.now(UTC)
q = urllib.parse.urlencode({'from': (now - timedelta(hours=24)).isoformat(), 'to': now.isoformat()})
def points():
    r = json.load(urllib.request.urlopen(urllib.request.Request('http://localhost:8880/api/alerts/smart/summary?' + q, headers={'X-NetTap-Daemon-Token': token}), timeout=120))
    return (r.get('baseline') or {}).get('history_points')
seen = [points() for _ in range(5)]
path = os.path.join(os.environ.get('NETTAP_DATA_DIR', '/tmp'), 'nettap-baselines.json')
hist = json.load(open(path)).get('history', []) if os.path.exists(path) else []
ok = len(set(seen)) == 1 and all('hour' in h for h in hist) and len({(h['hour'], h['window_hours']) for h in hist}) == len(hist)
print(int(ok), f'5 requests: history_points {seen}; stored snapshots {len(hist)}, one per hour and window length: {ok}')
" 2>&1)
if [ "${OUT%% *}" = "1" ]; then rc=0; else rc=1; fi
check "#95 baseline counts hours" "$rc" "${OUT#* }"
echo ""

echo "→ Step 5: Figures don't depend on how the data is split..."
bash "$REPO_DIR/scripts/remote/verify-split-invariance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 6: Every device's figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-device-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 7: Page figures vs OpenSearch..."
bash "$REPO_DIR/scripts/remote/verify-figures.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 8: Acceptance check for the whole goal..."
bash "$REPO_DIR/scripts/remote/verify-acceptance.sh" | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Batch 35 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
