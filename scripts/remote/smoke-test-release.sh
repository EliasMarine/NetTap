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
# NET-227: a disk-full pause is surfaced, ILM failures are reported, growth is measured
st=$(daemon_get /api/storage/status | py '"%s|%s|%s" % (d.get("capture_paused_disk_full"), (d.get("ilm_status") or {}).get("last_error"), "growth_estimate" in d)')
case "$st" in
    False\|None\|True) pass "storage: capture not paused for disk, ILM synced, growth estimate reported" ;;
    True\|*) fail "packet capture is paused: disk full" ;;
    False\|*\|True) warn "ILM policy not synced: ${st#*|}" ;;
    *) fail "storage status lacks the NET-227 fields: $st" ;;
esac
echo ""

echo "→ Step 9: Release-audit blocker fixes (NET-224 to NET-229, NET-237)"
# NET-224: notification settings never come back with a URL or password
secrets=$(daemon_get /api/notifications/config | py '"missing" if not isinstance(d, dict) or "email" not in d else ",".join(k for k in ("url", "password", "smtp_password", "token") if ("\"%s\":" % k) in json.dumps(d)) or "none"')
case "$secrets" in
    none) pass "notification settings reply holds no URL or password" ;;
    missing|PARSE_ERROR) fail "notification settings reply missing or unreadable (NET-224 not deployed?)" ;;
    *) fail "notification settings reply exposes: $secrets" ;;
esac
# NET-225: DNS shows the median, not only the mean
med=$(daemon_get /api/dns/stats | py '"absent" if "median_resolution_ms" not in d else ("null" if d["median_resolution_ms"] is None else "ok")')
case "$med" in
    ok) pass "DNS stats report the median lookup time" ;;
    null) warn "DNS stats report no median (no answered lookups in the window)" ;;
    *) fail "DNS stats have no median field (NET-225 not deployed?)" ;;
esac
# NET-228: a category trend is a comparison with enough data, or says it can't be one
trends=$(daemon_get "/api/alerts/categories?from=now-24h&to=now" | py '",".join(sorted({str(c.get("trend")) for c in (d.get("categories") or [])} - {"increasing", "decreasing", "stable", "not_enough_data"})) or "ok"')
if [ "$trends" = "ok" ]; then pass "alert category trends are increasing/decreasing/stable/not_enough_data only"; else fail "unexpected alert trend values: $trends"; fi
# NET-229: an install with an admin has no setup code lying around
if sudo docker exec nettap-web test -e /var/lib/nettap-web/setup-code 2>/dev/null; then
    warn "a setup code exists: no admin yet, or it wasn't removed after the admin was created"
else
    pass "no setup code on an install that already has an admin"
fi
# NET-229: TShark parses hostile packets with no network and no root
tshark_cfg=$(sudo docker inspect nettap-tshark --format '{{.HostConfig.NetworkMode}} {{.Config.User}}' 2>/dev/null || echo "missing")
case "$tshark_cfg" in
    "none 65534:65534") pass "TShark has no network and runs as nobody" ;;
    missing) warn "nettap-tshark container not found" ;;
    *) fail "TShark runs with '$tshark_cfg' (expected 'none 65534:65534'): recreate nettap-tshark" ;;
esac
# NET-229: CyberChef needs a login
cc=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/cyberchef/)
case "$cc" in
    302|401) pass "CyberChef needs a login ($cc)" ;;
    *) fail "CyberChef answered $cc without a session: recreate nettap-nginx" ;;
esac
# NET-237: GeoIP for an anycast address names its source and gives no pin
geo=$(daemon_get /api/geoip/1.1.1.1 | py '"ok" if d.get("anycast") and d.get("latitude") is None and d.get("source") else "bad:%s/%s/%s" % (d.get("anycast"), d.get("latitude"), bool(d.get("source")))')
if [ "$geo" = "ok" ]; then pass "GeoIP marks anycast, gives no pin and names its source"; else fail "GeoIP anycast answer: $geo"; fi
echo ""

echo "→ Step 10: Device totals count both sides of a connection (NET-226)"
# The busiest answering device in Step 6's hour, counted straight from OpenSearch: its listed
# connections must be started + answered + its IPv6, and more than started alone.
nt_lan=$(daemon_get "/api/network/lan" | py '",".join("\"%s\"" % s for s in d["subnets"])')
nt_devices=$(daemon_get "/api/devices?from=$FROM&to=$TO&limit=500")
nt_base='{"range":{"@timestamp":{"gte":"'"$FROM"'","lte":"'"$TO"'","format":"strict_date_optional_time"}}},{"term":{"event.provider":"zeek"}},{"term":{"event.dataset":"conn"}}'
nt_not_long='"must_not":[{"term":{"log.file.path":"conn_long.log"}}]'
nt_listed=$(printf '%s' "$nt_devices" | py '"\n".join(x["ip"] for x in d.get("devices", []))')
nt_ip=$(printf '%s' '{"size":0,"query":{"bool":{"filter":['"$nt_base"',{"terms":{"destination.ip":['"$nt_lan"']}}],'"$nt_not_long"'}},"aggs":{"ip":{"terms":{"field":"destination.ip","size":50}}}}' \
    | os_query "/arkime_sessions3-*/_search" \
    | py '"\n".join(b["key"] for b in d["aggregations"]["ip"]["buckets"])' \
    | grep -Fx -f <(printf '%s\n' "$nt_listed") | head -1)
nt_count() {
    printf '%s' '{"size":0,"track_total_hits":true,"query":{"bool":{"filter":['"$nt_base"',{"term":{"'"$1"'.ip":"'"$nt_ip"'"}}],'"$nt_not_long"'}}}' \
        | os_query "/arkime_sessions3-*/_search" | py 'd["hits"]["total"]["value"]'
}
if [ -z "$nt_ip" ]; then
    warn "no listed device answered a connection in $FROM..$TO; both-sides check skipped"
else
    nt_started=$(nt_count source)
    nt_answered=$(nt_count destination)
    # the row is picked in the shell, so eval never sees data
    nt_row=$(printf '%s' "$nt_devices" \
        | py '"\n".join("%s %s %s" % (x["ip"], x["connection_count"], x.get("ipv6_connections", 0)) for x in d["devices"])' \
        | awk -v ip="$nt_ip" '$1 == ip {print $2, $3}')
    nt_conns=${nt_row% *}
    nt_v6=${nt_row#* }
    if [ -n "$nt_row" ] && [ "$nt_started" -eq "$nt_started" ] 2>/dev/null && [ "$nt_answered" -eq "$nt_answered" ] 2>/dev/null; then
        nt_want=$((nt_started + nt_answered + nt_v6))
        if [ "$nt_conns" = "$nt_want" ] && [ "$nt_conns" -gt "$nt_started" ]; then
            pass "device-A's connections are both sides: $nt_conns = $nt_started started + $nt_answered answered + $nt_v6 IPv6"
        elif [ "$nt_conns" = "$nt_started" ]; then
            fail "the device list counts only started connections ($nt_conns; answered $nt_answered): NET-226 not deployed"
        else
            warn "device list $nt_conns vs $nt_want (started $nt_started + answered $nt_answered + IPv6 $nt_v6); records may still be arriving, rerun"
        fi
    else
        fail "couldn't read the device row or the OpenSearch counts for the both-sides check"
    fi
fi
echo ""

echo "=== Result: $PASS passed, $FAIL failed, $WARN warnings ==="
[ "$FAIL" -eq 0 ]
