#!/usr/bin/env bash
# ==========================================================================
# NetTap pre-release smoke test (read-only).
#
# Changes nothing: no pull, no rebuild, no restart. Run it on the device as the
# normal user after a deploy:
#   bash scripts/remote/smoke-test-release.sh
#
# Prints one PASS / FAIL / WARN line per check and a total at the end.
# The daemon token is read inside each command and never printed.
# JSON is parsed with the daemon container's python3 (the host has none).
# ==========================================================================
set -u

REPO_DIR="/home/nettap/NetTap"
STALE_SECONDS=900
PASS=0
FAIL=0
WARN=0

pass() { echo "   PASS  $1"; PASS=$((PASS + 1)); }
fail() { echo "   FAIL  $1"; FAIL=$((FAIL + 1)); }
warn() { echo "   WARN  $1"; WARN=$((WARN + 1)); }

# py '<python expression reading d>' < json : evaluates in the daemon container
# (the expression is passed as an argument, so its quotes never meet the shell's;
# eval only ever sees the fixed expressions written in this script, never data)
PY_PROG='import json, sys
try:
    d = json.load(sys.stdin)
    print(eval(sys.argv[1]))
except Exception:
    print("PARSE_ERROR")'
py() { sudo docker exec -i nettap-storage-daemon python3 -c "$PY_PROG" "$1"; }

daemon_get() {
    local path="$1"
    local token
    token=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)
    # the header goes in on stdin, so the token never shows in ps
    printf 'X-NetTap-Daemon-Token: %s\n' "$token" | curl -s -m 60 -H @- "http://localhost:8880$path"
}

os_query() {
    sudo docker exec -i nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc \
        --cacert /usr/share/opensearch/config/certs/ca.crt --insecure \
        -H 'Content-Type: application/json' "https://localhost:9200$1" --data-binary @-
}

echo "=== NetTap pre-release smoke test ==="
cd "$REPO_DIR" || { echo "Repo not found at $REPO_DIR"; exit 1; }
echo ""

echo "→ Step 1: Revision"
echo "   commit $(git log -1 --format='%h %s' 2>/dev/null)"
if [ -z "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then pass "checkout has no local changes"; else warn "checkout has local changes"; fi
echo ""

echo "→ Step 2: Containers"
for c in nettap-opensearch nettap-logstash nettap-filebeat nettap-zeek-live nettap-suricata-live \
         nettap-pcap-capture nettap-storage-daemon nettap-web nettap-nginx; do
    state=$(sudo docker inspect --format '{{.State.Status}}{{if .State.Health}}/{{.State.Health.Status}}{{end}}' "$c" 2>/dev/null || echo "missing")
    case "$state" in
        running/healthy|running) pass "$c $state" ;;
        *) fail "$c $state" ;;
    esac
done
echo ""

echo "→ Step 3: OpenSearch"
status=$(echo '' | sudo docker exec -i nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc \
    --cacert /usr/share/opensearch/config/certs/ca.crt --insecure 'https://localhost:9200/_cluster/health' | py 'd.get("status","?")')
case "$status" in
    green) pass "cluster health green" ;;
    yellow) warn "cluster health yellow" ;;
    *) fail "cluster health '$status' (if 'Unauthorized': bash scripts/remote/fix-opensearch.sh)" ;;
esac
echo ""

echo "→ Step 4: Data freshness (is new traffic being indexed?)"
age=$(echo '{"size":0,"query":{"bool":{"filter":[{"term":{"event.provider":"zeek"}},{"range":{"@timestamp":{"gte":"now-1d"}}}]}},"aggs":{"n":{"max":{"field":"event.ingested"}}}}' \
    | os_query '/arkime_sessions3-*/_search' \
    | py 'int(__import__("time").time() - d["aggregations"]["n"]["value"]/1000) if d.get("aggregations",{}).get("n",{}).get("value") else -1')
if [ "$age" = "PARSE_ERROR" ] || [ "$age" -lt 0 ] 2>/dev/null; then fail "no Zeek records indexed in the last 24 h"
elif [ "$age" -le "$STALE_SECONDS" ]; then pass "newest Zeek record indexed ${age}s ago"
else fail "newest Zeek record indexed ${age}s ago (over ${STALE_SECONDS}s)"; fi
echo ""

echo "→ Step 5: Daemon API"
code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8880/api/devices)
if [ "$code" = "401" ]; then pass "daemon rejects requests without the token"; else fail "daemon /api/devices without token returned $code"; fi
health=$(daemon_get /api/system/health | py 'd.get("status","?")')
case "$health" in
    healthy) pass "system health: healthy" ;;
    *) fail "system health: $health" ;;
esac
pipeline=$(daemon_get /api/system/health | py '(d.get("pipeline") or {}).get("state","absent")')
case "$pipeline" in
    fresh) pass "health reports fresh data and running sensors" ;;
    absent|PARSE_ERROR) warn "health has no pipeline check (needs the release-audit fix)" ;;
    *) fail "health pipeline state: $pipeline" ;;
esac
cap=$(daemon_get /api/capture/health | py 'd.get("status","?")')
if [ "$cap" = "normal" ]; then pass "capture health: normal"; else fail "capture health: $cap"; fi
# "window" is null for the first minutes after a daemon restart (loss_window.py)
loss=$(daemon_get /api/capture/stats | py '"%.4f%%" % ((d.get("loss_window") or {}).get("window") or {})["drop_rate_pct"] if ((d.get("loss_window") or {}).get("window") or {}).get("drop_rate_pct") is not None else "not measured yet (window still filling)"')
echo "   info  packet loss in the current window: ${loss}"
echo ""

echo "→ Step 6: Traffic totals reconcile with Zeek (last full hour)"
FROM=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:00:00Z)
TO=$(date -u +%Y-%m-%dT%H:00:00Z)
excluded=$(daemon_get "/api/traffic/summary?from=$FROM&to=$TO" | py 'json.dumps(d.get("excluded_ips",[]))')
zeek_sum() {  # Zeek's final conn records in the window (conn_long.log holds the interim ones)
    echo "{\"size\":0,\"query\":{\"bool\":{\"filter\":[{\"range\":{\"@timestamp\":{\"gte\":\"$FROM\",\"lte\":\"$TO\"}}},{\"term\":{\"event.provider\":\"zeek\"}},{\"term\":{\"event.dataset\":\"conn\"}}],\"must_not\":[{\"term\":{\"log.file.path\":\"conn_long.log\"}},{\"terms\":{\"source.ip\":$excluded}}]}},\"aggs\":{\"o\":{\"sum\":{\"field\":\"zeek.conn.orig_ip_bytes\"}},\"r\":{\"sum\":{\"field\":\"zeek.conn.resp_ip_bytes\"}}}}" \
        | os_query '/arkime_sessions3-*/_search' | py 'int(d["aggregations"]["o"]["value"]+d["aggregations"]["r"]["value"])'
}
# A connection that started in the window and closes now still lands in it (its record carries
# the start time), so the window can grow while we look: bracket the API call with two sums.
src_before=$(zeek_sum)
api_bytes=$(daemon_get "/api/traffic/summary?from=$FROM&to=$TO" | py 'int(d.get("total_bytes",-1))')
src_after=$(zeek_sum)
echo "   info  window $FROM .. $TO: API $api_bytes B, Zeek final records $src_before..$src_after B"
if [ "$src_before" -le "$api_bytes" ] 2>/dev/null && [ "$api_bytes" -le "$src_after" ] 2>/dev/null; then
    pass "traffic summary equals the independent Zeek sum"
else
    fail "traffic summary differs from the independent Zeek sum (interim long-connection records counted?)"
fi
echo ""

echo "→ Step 7: Web app"
code=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/api/traffic/summary)
if [ "$code" = "401" ]; then pass "web API rejects requests without a session"; else fail "web /api/traffic/summary without a session returned $code"; fi
if curl -sk https://localhost/api/health | grep -q '"serial"'; then fail "public /api/health exposes hardware detail"; else pass "public /api/health exposes no hardware detail"; fi
echo ""

echo "→ Step 8: Storage"
daemon_get /api/storage/status | py '"   info  disk %s%% used, PCAP cap applies at 25%% of the disk" % d.get("disk_usage_percent")'
echo ""

echo "=== Result: $PASS passed, $FAIL failed, $WARN warnings ==="
[ "$FAIL" -eq 0 ]
