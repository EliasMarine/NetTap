#!/usr/bin/env bash
# Read-only end-to-end acceptance check of a running NetTap box (mirror mode).
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# Checks, in one run, every part of the data-accuracy goal: containers, packet capture, the
# Zeek and Suricata pipeline, traffic figures against raw OpenSearch over a fixed window,
# devices, PCAP list / preview / download, TShark against tshark itself, CyberChef and
# OpenSearch Dashboards. Nothing is restarted, written or deleted.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/verify-acceptance.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="fix/dashboard-data-accuracy"
FAILED=0
# A closed window: one hour ending 15 minutes ago, so late records can't make two queries differ
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '75 minutes ago' +%Y-%m-%dT%H:%M:%SZ)

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

os_query() {  # os_query <path> [json body]: OpenSearch from inside its container
    if [ $# -gt 1 ]; then
        sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
            -H 'Content-Type: application/json' "https://localhost:9200$1" -d "$2"
    else
        sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure "https://localhost:9200$1"
    fi
}

echo "=== NetTap acceptance check (read-only) ==="
echo "   Fixed window for figure checks: $FROM_TS → $TO_TS"
echo ""

echo "→ Step 1: Code on the box..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch -q origin 2>/dev/null
echo "   $(git branch --show-current) @ $(git log -1 --format='%h %s') (origin: $(git log -1 --format='%h' "origin/$BRANCH" 2>/dev/null))"
echo ""

echo "→ Step 2: Containers..."
UNHEALTHY=$(sudo docker ps -a --filter name=nettap- --format '{{.Names}} {{.Status}}' | grep -v -E 'Up .*\(healthy\)|Up [0-9]+ (seconds|minutes|hours|days)$|Up About' | tr '\n' ';')
RUNNING=$(sudo docker ps --filter name=nettap- --format '{{.Names}}' | wc -l)
if [ -z "$UNHEALTHY" ]; then rc=0; else rc=1; fi
check "every NetTap container up and healthy" "$rc" "$RUNNING running${UNHEALTHY:+; not healthy: $UNHEALTHY}"
FATAL=""
for c in nettap-logstash nettap-dashboards-helper; do
    # fix-perms and idxinit are one-shots (autorestart=false): EXITED is their done state, and
    # their effects are checked below (indexing resumes, Malcolm's dashboards exist)
    S=$(sudo docker exec "$c" supervisorctl -c /etc/supervisord.conf status 2>&1 \
        | awk '$2 != "RUNNING" && !($1 ~ /^(fix-perms|idxinit)$/ && $2 == "EXITED") {print $1 "=" $2}' | tr '\n' ' ')
    [ -n "$S" ] && FATAL="$FATAL $c: $S"
done
if [ -z "$FATAL" ]; then rc=0; else rc=1; fi
check "Malcolm supervisor programs running" "$rc" "${FATAL:-logstash and dashboards-helper all RUNNING}"
echo ""

echo "→ Step 3: Everything else goes through the daemon API..."
OUT=$(sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, time, urllib.error, urllib.parse, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
def call(path, body=None, timeout=120, raw=False):
    req = urllib.request.Request('http://localhost:8880' + path, headers={'X-NetTap-Daemon-Token': token, 'Content-Type': 'application/json'},
        data=None if body is None else json.dumps(body).encode(), method='GET' if body is None else 'POST')
    r = urllib.request.urlopen(req, timeout=timeout)
    return r if raw else json.load(r)
def q(**kw): return '?' + urllib.parse.urlencode(kw)
frm, to = sys.argv[1], sys.argv[2]
mode = call('/api/capture/mode'); h = call('/api/capture/health'); st = call('/api/capture/stats')
print('CAPTURE', mode['mode'], h['capture_interface'], h['status'], int(h['link_up']), int(h['promisc_enabled']), st['drop_rate_pct'])
s = call('/api/traffic/summary' + q(**{'from': frm, 'to': to}))
print('SUMMARY', s['connection_count'], int(s['total_bytes']))
print('EXCLUDED', ','.join(call('/api/settings/excluded-ips')['excluded_ips']) or '-')
devs = call('/api/devices' + q(limit=500))['devices']
print('DEVICES', len(devs), sum(1 for d in devs if d.get('mac')))
pcaps = sorted(call('/api/tshark/pcaps')['pcaps'], key=lambda p: p['modified'], reverse=True)
print('NEWEST', pcaps[0]['name'], int(time.time() - pcaps[0]['modified']), len(pcaps))
target = next(p for p in pcaps[1:] if 20e6 < p['size_bytes'] < 400e6)
print('FILE', target['name'], target['path'])
t0 = time.time()
r = call('/api/tshark/analyze', {'pcap_path': target['path'], 'display_filter': 'dns', 'max_packets': 50, 'output_format': 'json'})
dns = sum('dns' in (p.get('_source', {}).get('layers') or {}) for p in r.get('packets', []))
print('TSHARK', r.get('packet_count'), dns, round(time.time() - t0, 1), r.get('error'))
listed = call('/api/pcap/files')['files']
full = next(f['file'] for f in listed if f['file'].endswith('/' + target['name']))
p = call('/api/pcap/preview' + q(file=full, filter='dns', limit=20))
print('PREVIEW', len(p.get('packets', [])), p.get('error'))
resp = call('/api/pcap/download-file' + q(file=full), raw=True, timeout=60)
print('DOWNLOAD', resp.status, resp.read(4).hex())
resp.close()
frag = [x for x in call('/api/cyberchef/recipes')['recipes'] if x['name'] == 'Base64 Decode'][0]['recipe_fragment']
print('CYBERCHEF', call('/api/cyberchef/url', {'recipe_fragment': frag, 'input_data': 'aGVsbG8gbmV0dGFw'})['url'])
" "$FROM_TS" "$TO_TS" 2>&1)
while IFS= read -r line; do echo "   $line"; done <<<"$OUT"
field() { echo "$OUT" | awk -v k="$1" '$1 == k' | cut -d' ' -f"$2"; }
echo ""

echo "→ Step 4: Packet capture..."
read -r _ MODE IFACE CSTATUS LINK PROMISC DROP <<<"$(echo "$OUT" | grep '^CAPTURE')"
if [ "${MODE:-}" = "mirror" ] && [ "${CSTATUS:-}" = "normal" ] && [ "${LINK:-0}" = "1" ] && [ "${PROMISC:-0}" = "1" ]; then rc=0; else rc=1; fi
check "capture port up, promiscuous, healthy" "$rc" "${MODE:-?} on ${IFACE:-?}, status ${CSTATUS:-?}, link ${LINK:-?}, promisc ${PROMISC:-?}"
if awk -v d="${DROP:-100}" 'BEGIN {exit !(d < 0.1)}'; then rc=0; else rc=1; fi
check "capture drop rate under 0.1%" "$rc" "${DROP:-?}%"
NEWEST_AGE=$(field NEWEST 3)
if [ -n "$NEWEST_AGE" ] && [ "$NEWEST_AGE" -lt 900 ]; then rc=0; else rc=1; fi
check "netsniff is writing PCAP" "$rc" "newest $(field NEWEST 2), written ${NEWEST_AGE:-?} s ago, $(field NEWEST 4) files"
for provider in zeek suricata; do
    N=$(os_query "/arkime_sessions3-*/_count?q=event.provider:$provider%20AND%20@timestamp:%3Enow-5m" | grep -o '"count":[0-9]*' | cut -d: -f2)
    if [ "${N:-0}" -gt 0 ]; then rc=0; else rc=1; fi
    check "$provider records reach OpenSearch (last 5 min)" "$rc" "${N:-0}"
done
echo ""

echo "→ Step 5: Figures match raw OpenSearch..."
EXCL=$(field EXCLUDED 2)
MUST_NOT="[]"
if [ -n "$EXCL" ] && [ "$EXCL" != "-" ]; then
    QUOTED=${EXCL//,/'","'}
    MUST_NOT="[{\"terms\":{\"source.ip\":[\"$QUOTED\"]}}]"
fi
RAW=$(os_query "/arkime_sessions3-*/_search" "{\"size\":0,\"track_total_hits\":true,\"query\":{\"bool\":{\"filter\":[{\"range\":{\"@timestamp\":{\"gte\":\"$FROM_TS\",\"lte\":\"$TO_TS\"}}},{\"term\":{\"event.provider\":\"zeek\"}},{\"term\":{\"event.dataset\":\"conn\"}}],\"must_not\":$MUST_NOT}},\"aggs\":{\"o\":{\"sum\":{\"field\":\"source.bytes\"}},\"r\":{\"sum\":{\"field\":\"destination.bytes\"}}}}")
RAW_CONN=$(echo "$RAW" | grep -o '"total":{"value":[0-9]*' | grep -o '[0-9]*$')
RAW_BYTES=$(echo "$RAW" | grep -o '"value":[0-9.E+]*' | tail -2 | cut -d: -f2 | awk '{s += $1} END {printf "%d", s}')
API_CONN=$(field SUMMARY 2); API_BYTES=$(field SUMMARY 3)
if [ -n "$API_CONN" ] && [ "$API_CONN" = "$RAW_CONN" ]; then rc=0; else rc=1; fi
check "traffic summary connections = OpenSearch" "$rc" "API ${API_CONN:-?}, raw ${RAW_CONN:-?}"
if [ -n "$API_BYTES" ] && [ "$API_BYTES" = "$RAW_BYTES" ]; then rc=0; else rc=1; fi
check "traffic summary bytes = OpenSearch" "$rc" "API ${API_BYTES:-?}, raw ${RAW_BYTES:-?}"
NDEV=$(field DEVICES 2); NMAC=$(field DEVICES 3)
if [ "${NDEV:-0}" -gt 0 ] && [ "$NDEV" = "$NMAC" ]; then rc=0; else rc=1; fi
check "devices listed, each with a MAC" "$rc" "${NDEV:-0} devices, ${NMAC:-0} with a MAC"
echo ""

echo "→ Step 6: PCAP and TShark..."
FILE_PATH=$(field FILE 3)
read -r _ TS_COUNT TS_DNS TS_SECS TS_ERR <<<"$(echo "$OUT" | grep '^TSHARK')"
# The tshark container mounts the PCAP directory at /pcap (the daemon maps paths the same way)
TRUTH=$(sudo docker exec nettap-tshark sh -c 'tshark -r "$1" -Y dns -T fields -e frame.number 2>/dev/null | head -n 50 | wc -l' _ "/pcap/${FILE_PATH##*/}" 2>/dev/null | tr -d ' ')
if [ -n "${TS_COUNT:-}" ] && [ "$TS_COUNT" = "${TRUTH:-x}" ] && [ "$TS_COUNT" = "${TS_DNS:-y}" ]; then rc=0; else rc=1; fi
check "TShark 'dns' filter = tshark run directly" "$rc" "API ${TS_COUNT:-?} (${TS_DNS:-?} with a DNS layer) in ${TS_SECS:-?} s, tshark ${TRUTH:-?}, error ${TS_ERR:-?}"
read -r _ PV_N PV_ERR <<<"$(echo "$OUT" | grep '^PREVIEW')"
if [ "${PV_N:-0}" -gt 0 ] && [ "${PV_ERR:-None}" = "None" ]; then rc=0; else rc=1; fi
check "PCAP preview with a DNS filter" "$rc" "${PV_N:-0} packets, error ${PV_ERR:-?}"
read -r _ DL_CODE DL_MAGIC <<<"$(echo "$OUT" | grep '^DOWNLOAD')"
case "${DL_CODE:-}:${DL_MAGIC:-}" in 200:d4c3b2a1|200:a1b2c3d4|200:4d3cb2a1|200:0a0d0d0a) rc=0 ;; *) rc=1 ;; esac
check "PCAP download is a capture file" "$rc" "HTTP ${DL_CODE:-?}, magic ${DL_MAGIC:-?}"
echo ""

echo "→ Step 7: Add-on tools through the web front door..."
CC_URL=$(field CYBERCHEF 2)
case "$CC_URL" in /cyberchef/\#recipe=*\&input=*) rc=0 ;; *) rc=1 ;; esac
check "CyberChef recipe link" "$rc" "${CC_URL:-none}"
CC_HTTP=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/cyberchef/)
CC_BODY=$(curl -sk https://localhost/cyberchef/ | grep -c -i 'cyberchef')
if [ "$CC_HTTP" = "200" ] && [ "$CC_BODY" -gt 0 ]; then rc=0; else rc=1; fi
check "CyberChef served at /cyberchef/" "$rc" "HTTP $CC_HTTP"
OSD=$(sudo docker exec nettap-dashboards curl -s --config /var/local/curlrc/.opensearch.primary.curlrc -o /dev/null -w '%{http_code}' http://localhost:5601/dashboards/api/status 2>/dev/null)
DBS=$(os_query "/.kibana*/_count?q=type:%22dashboard%22" | grep -o '"count":[0-9]*' | cut -d: -f2)
if [ "$OSD" = "200" ] && [ "${DBS:-0}" -gt 0 ]; then rc=0; else rc=1; fi
check "OpenSearch Dashboards up with Malcolm's dashboards" "$rc" "status ${OSD:-?}, ${DBS:-0} dashboards"
LOGIN=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/login)
if [ "$LOGIN" = "200" ]; then rc=0; else rc=1; fi
check "NetTap web UI answers" "$rc" "/login → HTTP $LOGIN"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Acceptance check passed ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
