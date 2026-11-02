#!/usr/bin/env bash
# shellcheck disable=SC2329  # compare() calls the raw_*/api_* functions by name
# Read-only check that each data page's headline figures equal a raw OpenSearch query.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
# For each figure the daemon API (what the page shows) is read between two raw OpenSearch
# reads with the same filters, over the same past window: raw before <= API <= raw after.
# (Zeek logs a connection when it ends, stamped with its start, so a past window can grow.)
# Nothing is restarted, written or deleted.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/verify-figures.sh
set -u

FAILED=0
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '75 minutes ago' +%Y-%m-%dT%H:%M:%SZ)

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

os_query() {  # os_query <path> <json body>: OpenSearch from inside its container
    sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
        -H 'Content-Type: application/json' "https://localhost:9200$1" -d "$2"
}

api() {  # api <path> <python expression over the JSON response `r`>: what the page shows
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.request
token = open('/run/nettap-auth/daemon-token').read().strip()
req = urllib.request.Request('http://localhost:8880' + sys.argv[1], headers={'X-NetTap-Daemon-Token': token})
r = json.load(urllib.request.urlopen(req, timeout=120))
print($2)" "$1" 2>&1
}

json_get() {  # json_get <python expression over `r`>: one value from the JSON on stdin (python in a container)
    sudo docker exec -i nettap-storage-daemon python3 -c "import json, sys; r = json.load(sys.stdin); print($1)" 2>&1
}

between() { [[ "${1:-}" =~ ^[0-9]+$ && "${2:-}" =~ ^[0-9]+$ && "${3:-}" =~ ^[0-9]+$ ]] && [ "$1" -le "$2" ] && [ "$2" -le "$3" ]; }

compare() {  # compare "label" <raw function> <api function>: raw before <= API <= raw after
    local r1 a r2 rc
    r1=$($2); a=$($3); r2=$($2)
    if between "$r1" "$a" "$r2"; then rc=0; else rc=1; fi
    check "$1" "$rc" "page ${a:-?}, OpenSearch ${r1:-?} before / ${r2:-?} after"
}

raw() {  # raw <bool clause> <aggs or {}> <python expression over `r`>
    os_query "/arkime_sessions3-*/_search" "{\"size\":0,\"track_total_hits\":true,\"query\":{\"bool\":$1},\"aggs\":$2}" | json_get "$3"
}

# --- What each endpoint filters on (daemon/api/*.py, daemon/services/*.py) ---
Q="from=$FROM_TS&to=$TO_TS"
T="{\"range\":{\"@timestamp\":{\"gte\":\"$FROM_TS\",\"lte\":\"$TO_TS\",\"format\":\"strict_date_optional_time\"}}}"
CONN='{"term":{"event.provider":"zeek"}},{"term":{"event.dataset":"conn"}}'
TOTAL='int(r["hits"]["total"]["value"])'
BYTES='{"o":{"sum":{"field":"source.bytes"}},"r":{"sum":{"field":"destination.bytes"}}}'
BYTES_SUM='int(r["aggregations"]["o"]["value"] + r["aggregations"]["r"]["value"])'

echo "=== NetTap page figures vs OpenSearch (read-only) ==="
echo "   Window: $FROM_TS → $TO_TS"
EXCL=$(api /api/settings/excluded-ips 'json.dumps(r["excluded_ips"])')
case "$EXCL" in \[*\]) ;; *) echo "   ✗ could not read the excluded IPs: $EXCL"; exit 1 ;; esac
echo "   Excluded IPs (hidden from device and traffic views only): $EXCL"
SRC_EXCL="{\"terms\":{\"source.ip\":$EXCL}}"
echo ""

echo "→ Alerts (Home card, Alerts page): excluded IPs stay visible, engine events left out"
ALERTS="{\"filter\":[$T,{\"term\":{\"event.provider\":\"suricata\"}},{\"term\":{\"event.dataset\":\"alert\"}}],\"must_not\":[{\"prefix\":{\"rule.name\":\"SURICATA \"}}]}"
raw_alerts() { raw "$ALERTS" '{}' "$TOTAL"; }
api_alerts() { api "/api/alerts/count?$Q" 'r["counts"]["total"]'; }
compare "alert total" raw_alerts api_alerts
raw_high() { raw "$ALERTS" '{"s":{"terms":{"field":"suricata.alert.severity","size":10}}}' 'sum(b["doc_count"] for b in r["aggregations"]["s"]["buckets"] if int(b["key"]) == 1)'; }
api_high() { api "/api/alerts/count?$Q" 'r["counts"]["high"]'; }
compare "high-severity alerts" raw_high api_high
echo ""

echo "→ DNS page: lookups only (no pcap-monitor, mDNS/LLMNR/NetBIOS), excluded IPs hidden"
DNS="{\"filter\":[$T,{\"term\":{\"event.provider\":\"zeek\"}},{\"term\":{\"event.dataset\":\"dns\"}}],\"must_not\":[{\"term\":{\"zeek.dns.query\":\"pcap-monitor\"}},{\"bool\":{\"filter\":[{\"terms\":{\"destination.port\":[5353,5355,137]}},{\"terms\":{\"destination.ip\":[\"224.0.0.0/4\",\"ff00::/8\",\"255.255.255.255\",\"10.0.0.0/8\",\"172.16.0.0/12\",\"192.168.0.0/16\",\"169.254.0.0/16\",\"fe80::/10\"]}}]}},$SRC_EXCL]}"
raw_dns() { raw "$DNS" '{}' "$TOTAL"; }
api_dns() { api "/api/dns/stats?$Q" 'r["total_queries"]'; }
compare "DNS queries" raw_dns api_dns
raw_nx() { raw "$DNS" '{"n":{"filter":{"term":{"zeek.dns.rcode_name":"NXDOMAIN"}}}}' 'r["aggregations"]["n"]["doc_count"]'; }
api_nx() { api "/api/dns/stats?$Q" 'r["nxdomain_count"]'; }
compare "NXDOMAIN answers" raw_nx api_nx
echo ""

echo "→ Traffic and Bandwidth pages: the top entry's bytes = an exact sum for that IP"
TALKER=$(api "/api/traffic/top-talkers?$Q&limit=1" 'r["top_talkers"][0]["ip"]')
raw_talker() { raw "{\"filter\":[$T,$CONN,{\"term\":{\"source.ip\":\"$TALKER\"}}]}" "$BYTES" "$BYTES_SUM"; }
api_talker() { api "/api/traffic/top-talkers?$Q&limit=1" 'int(r["top_talkers"][0]["total_bytes"])'; }
compare "Top Talkers #1 ($TALKER)" raw_talker api_talker
DEST=$(api "/api/traffic/top-destinations?$Q&limit=1" 'r["top_destinations"][0]["ip"]')
raw_dest() { raw "{\"filter\":[$T,$CONN,{\"term\":{\"destination.ip\":\"$DEST\"}}],\"must_not\":[$SRC_EXCL]}" "$BYTES" "$BYTES_SUM"; }
api_dest() { api "/api/traffic/top-destinations?$Q&limit=1" 'int(r["top_destinations"][0]["total_bytes"])'; }
compare "Top Destinations #1 ($DEST)" raw_dest api_dest
BWDEV=$(api "/api/bandwidth/devices?$Q&limit=1" 'r["devices"][0]["ip"]')
raw_bw() { raw "{\"filter\":[$T,$CONN,{\"term\":{\"source.ip\":\"$BWDEV\"}}]}" "$BYTES" "$BYTES_SUM"; }
api_bw() { api "/api/bandwidth/devices?$Q&limit=1" 'int(r["devices"][0]["total_bytes"])'; }
compare "Bandwidth top device ($BWDEV)" raw_bw api_bw
case ",$(echo "$EXCL" | tr -d '[]" '),"  in *",$TALKER,"*|*",$BWDEV,"*) rc=1 ;; *) rc=0 ;; esac
check "no excluded IP leads Top Talkers or Bandwidth" "$rc" "talker $TALKER, bandwidth $BWDEV"
echo ""

echo "→ Connections page and Log Explorer: raw records, excluded IPs visible"
raw_conns() { raw "{\"filter\":[$T,$CONN]}" '{}' "$TOTAL"; }
api_conns() { api "/api/traffic/connections?$Q&size=1" 'r["total"]'; }
compare "Connections total" raw_conns api_conns
LOGDNS="{\"filter\":[{\"range\":{\"@timestamp\":{\"gte\":\"$FROM_TS\",\"lte\":\"$TO_TS\"}}},{\"term\":{\"event.provider\":\"zeek\"}},{\"term\":{\"event.dataset\":\"dns\"}}],\"must_not\":[{\"term\":{\"zeek.dns.query\":\"pcap-monitor\"}},{\"term\":{\"event.dataset\":\"alert\"}}]}"
raw_logs() { raw "$LOGDNS" '{}' "$TOTAL"; }
api_logs() { api "/api/logs/search?$Q&log_type=zeek.dns&size=1" 'r["total"]'; }
compare "Log Explorer zeek.dns total" raw_logs api_logs
echo ""

echo "→ Certificates page: distinct server certificates"
CERTS="{\"filter\":[$T,{\"term\":{\"event.provider\":\"zeek\"}},{\"term\":{\"event.dataset\":\"x509\"}},{\"terms\":{\"zeek.x509.host_cert\":[\"true\",\"T\"]}}]}"
raw_certs() { raw "$CERTS" '{"c":{"cardinality":{"field":"zeek.x509.fingerprint","precision_threshold":40000}}}' 'int(r["aggregations"]["c"]["value"])'; }
api_certs() { api "/api/certificates/stats?$Q" 'r["total_certs"]'; }
compare "certificates" raw_certs api_certs
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Every page figure matches OpenSearch ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
