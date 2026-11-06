#!/usr/bin/env bash
# shellcheck disable=SC2329  # compare() calls the raw_*/api_* functions by name
# Deploy the drill-down pages (NET-160: an internet address, a domain) and check their
# figures on real data.
#
# The daemon and the web container are rebuilt. Then, read-only:
#   - /api/network/lan, the LAN rule the web app links by
#   - the name fields' mappings (case-insensitive matching needs keyword fields), and a
#     mixed-case vs lower-case count of the busiest name
#   - a busy internet address and the busiest domain: each page fetched once, every figure
#     against a direct OpenSearch count with the daemon's own filters (raw before <= page <=
#     raw after, over a past window, as verify-figures.sh does), the ports' services and the
#     threat-intel answer included
#   - how many alerts in the window carry a host name at all
#   - a bad address is a 400 and no token is a 401
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-drill-down.sh
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="main"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0
TO_TS=$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
FROM_TS=$(date -u -d '75 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
Q="from=$FROM_TS&to=$TO_TS"

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

# OLD CODE START — NET-160 review: the token stayed in reach of the eval (token, headers, req)
# daemon() {  # daemon <path> <python expression on the reply `d`, or 'status'> [notoken]
#     # The expression is always a literal from this script; the token is read inside the container
#     sudo docker exec nettap-storage-daemon python3 -c "
# import json, sys, urllib.error, urllib.request
# token = open('/run/nettap-auth/daemon-token').read().strip()
# headers = {} if len(sys.argv) > 3 else {'X-NetTap-Daemon-Token': token}
# req = urllib.request.Request('http://localhost:8880' + sys.argv[1], headers=headers)
# try:
#     r = urllib.request.urlopen(req, timeout=120)
#     code, d = r.status, json.load(r)
# except urllib.error.HTTPError as e:
#     code, d = e.code, {}
# print(code if sys.argv[2] == 'status' else eval(sys.argv[2]))" "$@" 2>&1 | tail -n 1
# }
# OLD CODE END
daemon() {  # daemon <path> <python expression on the reply `d` and status `code`, or 'status'> [notoken]
    # The expression is always a literal from this script. The token is read inside the
    # container, inside fetch(): it, the headers and the request are gone before the eval runs
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.error, urllib.request
def fetch(path, with_token):
    headers = {}
    if with_token:
        headers['X-NetTap-Daemon-Token'] = open('/run/nettap-auth/daemon-token').read().strip()
    req = urllib.request.Request('http://localhost:8880' + path, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=120)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}
code, d = fetch(sys.argv[1], len(sys.argv) <= 3)
del fetch
print(code if sys.argv[2] == 'status' else eval(sys.argv[2]))" "$@" 2>&1 | tail -n 1
}

os_query() {  # os_query <path> [json body]: OpenSearch from inside its container
    if [ $# -gt 1 ]; then
        sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc \
            --insecure -H 'Content-Type: application/json' "https://localhost:9200$1" -d "$2"
    else
        sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc \
            --insecure "https://localhost:9200$1"
    fi
}

json_get() {  # json_get <json> <python expression over `r`>: python runs in a container
    # The expression is always a literal from this script; the JSON is only ever data
    sudo docker exec nettap-storage-daemon python3 -c "import json, sys; r = json.loads(sys.argv[1]); print(eval(sys.argv[2]))" "$1" "$2" 2>&1 | tail -n 1
}

json_stdin() {  # <json> | json_stdin <python expression over `r`>: for replies too big for argv
    sudo docker exec -i nettap-storage-daemon python3 -c "import json, sys; r = json.load(sys.stdin); print(eval(sys.argv[1]))" "$1" 2>&1 | tail -n 1
}

daemon_json() {  # daemon_json <module> <name>: a daemon constant as JSON, so the checks use its own filters
    sudo docker exec nettap-storage-daemon python3 -c "import importlib, json, sys; print(json.dumps(getattr(importlib.import_module(sys.argv[1]), sys.argv[2])))" "$1" "$2" 2>&1 | tail -n 1
}

raw() {  # raw <bool clause> <aggs or {}> <python expression over `r`>
    local out
    out=$(os_query "/arkime_sessions3-*/_search" "{\"size\":0,\"track_total_hits\":true,\"query\":{\"bool\":$1},\"aggs\":$2}")
    json_get "$out" "$3"
}

between() { [[ "${1:-}" =~ ^[0-9]+$ && "${2:-}" =~ ^[0-9]+$ && "${3:-}" =~ ^[0-9]+$ ]] && [ "$1" -le "$2" ] && [ "$2" -le "$3" ]; }

compare() {  # compare "label" <raw function> <api function>: raw before <= page <= raw after
    local r1 a r2 rc
    r1=$($2); a=$($3); r2=$($2)
    if between "$r1" "$a" "$r2"; then rc=0; else rc=1; fi
    check "$1" "$rc" "page ${a:-?}, OpenSearch ${r1:-?} before / ${r2:-?} after"
}

page_vs_raw() {  # page_vs_raw <path> "label|raw function|python expression over r"...
    # Every raw count before, the page once, every raw count after: raw before <= page <= raw
    # after. The reply stays in PAGE as {"status", "body"} for the lines that follow.
    local path=$1 spec label fn expr a r2 rc start i=0
    local -a before=()
    shift
    for spec in "$@"; do
        IFS='|' read -r label fn expr <<< "$spec"
        before+=("$($fn)")
    done
    start=$SECONDS
    PAGE=$(daemon "$path" "json.dumps({'status': code, 'body': d})")
    a=$(echo "$PAGE" | json_stdin "r['status']")
    if [ "$a" = "200" ]; then rc=0; else rc=1; fi
    check "${path%%\?*} answers" "$rc" "HTTP $a in $((SECONDS - start)) s"
    for spec in "$@"; do
        IFS='|' read -r label fn expr <<< "$spec"
        a=$(echo "$PAGE" | json_stdin "$expr")
        r2=$($fn)
        if between "${before[$i]}" "$a" "$r2"; then rc=0; else rc=1; fi
        check "$label" "$rc" "page ${a:-?}, OpenSearch ${before[$i]:-?} before / ${r2:-?} after"
        i=$((i + 1))
    done
}

page() { echo "$PAGE" | json_stdin "$1"; }  # page <python expression over r>

ci_name() {  # ci_name <field> <canonical name>: the field equal to name or name., any case
    echo "{\"bool\":{\"should\":[{\"term\":{\"$1\":{\"value\":\"$2\",\"case_insensitive\":true}}},{\"term\":{\"$1\":{\"value\":\"$2.\",\"case_insensitive\":true}}}],\"minimum_should_match\":1}}"
}

# --- The filters each endpoint uses (daemon/api/addresses.py, daemon/api/domains.py) ---
T="{\"range\":{\"@timestamp\":{\"gte\":\"$FROM_TS\",\"lte\":\"$TO_TS\",\"format\":\"strict_date_optional_time\"}}}"
zeek() { echo "{\"term\":{\"event.provider\":\"zeek\"}},{\"term\":{\"event.dataset\":\"$1\"}}"; }
TOTAL='int(r["hits"]["total"]["value"])'
SURICATA='{"term":{"event.provider":"suricata"}},{"term":{"event.dataset":"alert"}}'
NOISE='{"prefix":{"rule.name":"SURICATA "}}'
# OLD CODE START — NET-160 review: read from the daemon (Step 4), so it can't drift
# # services/dns_analytics.py DNS_LOOKUP_EXCLUSION: pcap-monitor, and local name services
# DNS_EXCL='{"term":{"zeek.dns.query":"pcap-monitor"}},{"bool":{"filter":[{"terms":{"destination.port":[5353,5355,137]}},{"terms":{"destination.ip":["224.0.0.0/4","ff00::/8","255.255.255.255","10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","169.254.0.0/16","fe80::/10"]}}]}}'
# OLD CODE END
NAME_FIELDS="zeek.dns.query,zeek.ssl.server_name,zeek.http.host,related.hosts,dns.question.name,tls.client.server_name,url.domain"

echo "=== Deploy: drill-down pages (NET-160) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build and recreate the daemon and the web container..."
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
# OLD CODE START — NET-160 review: a failed recreate went on to the health wait
# "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
# OLD CODE END
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web; then
    echo "   ✗ Could not recreate the containers"
    exit 1
fi
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

echo "→ Step 3: The LAN rule the web app links by..."
LAN=$(daemon /api/network/lan "json.dumps(d)")
case "$LAN" in *'"source": "env"'*|*'"source": "detected"'*|*'"source": "rfc1918"'*) rc=0 ;; *) rc=1 ;; esac
check "/api/network/lan" "$rc" "$LAN"
echo ""

echo "→ Step 4: Name fields are keyword (case-insensitive matching needs it)..."
# One mapping per daily index: piped, as it can pass the 128 KB limit of one argument
# OLD CODE START — NET-160 review: passed with every field unmapped; took stored CIDRs the
# daemon skips as excluded IPs
# TYPES=$(os_query "/arkime_sessions3-*/_mapping/field/$NAME_FIELDS?filter_path=*.mappings.*.mapping.*.type" \
#     | json_stdin "(lambda t: ('OK ' if all(v in ([], ['keyword']) for v in t.values()) else 'NOT-KEYWORD ') + json.dumps(t))({f: sorted({m['mapping'][f.rsplit('.', 1)[-1]]['type'] for i in r.values() for g, m in (i.get('mappings') or {}).items() if g == f}) for f in '$NAME_FIELDS'.split(',')})")
# case "$TYPES" in "OK "*) rc=0 ;; *) rc=1 ;; esac
# check "every name field is keyword where it is mapped ([] = unmapped)" "$rc" "$TYPES"
# echo "   Window: $FROM_TS → $TO_TS"
# EXCL=$(daemon /api/settings/excluded-ips "json.dumps(d['excluded_ips'])")
# case "$EXCL" in \[*\]) ;; *) echo "   ✗ could not read the excluded IPs: $EXCL"; exit 1 ;; esac
# OLD CODE END
TYPES=$(os_query "/arkime_sessions3-*/_mapping/field/$NAME_FIELDS?filter_path=*.mappings.*.mapping.*.type" \
    | json_stdin "(lambda t: ('OK ' if any(t.values()) and all(v in ([], ['keyword']) for v in t.values()) else 'NOT-KEYWORD ') + json.dumps(t))({f: sorted({m['mapping'][f.rsplit('.', 1)[-1]]['type'] for i in r.values() for g, m in (i.get('mappings') or {}).items() if g == f}) for f in '$NAME_FIELDS'.split(',')})")
case "$TYPES" in "OK "*) rc=0 ;; *) rc=1 ;; esac
check "name fields are keyword wherever mapped, and at least one is ([] = unmapped)" "$rc" "$TYPES"
echo "   Window: $FROM_TS → $TO_TS"
# Single addresses only, as build_excluded_ips_filter takes them (it skips stored CIDRs)
EXCL=$(daemon /api/settings/excluded-ips "json.dumps([ip for ip in map(__import__('services.excluded_ips', fromlist=['x']).parse_single_ip, d['excluded_ips']) if ip])")
case "$EXCL" in \[*\]) ;; *) echo "   ✗ could not read the excluded IPs: $EXCL"; exit 1 ;; esac
DNS_EXCL=$(daemon_json services.dns_analytics DNS_LOOKUP_EXCLUSION)
LISTING=$(daemon_json services.threat_intel LISTING_RULES)
case "$DNS_EXCL$LISTING" in \[*\]\{*\}) ;; *) echo "   ✗ could not read the daemon's filters: $DNS_EXCL $LISTING"; exit 1 ;; esac
DNS_EXCL=${DNS_EXCL:1:${#DNS_EXCL}-2}  # the clauses, without their list brackets
echo ""

echo "→ Step 5: The busiest domain, mixed case vs lower case..."
NAME=$(daemon "/api/dns/top-domains?$Q&limit=1" "((d.get('domains') or [{}])[0].get('domain') or '').lower().rstrip('.')")
if [[ "$NAME" =~ ^[a-z0-9._-]+$ ]]; then
    UPPER=$(echo "$NAME" | tr '[:lower:]' '[:upper:]')
    one_term() { raw "{\"filter\":[$T,$(zeek dns),{\"term\":{\"zeek.dns.query\":{\"value\":\"$1\",\"case_insensitive\":true}}}]}" '{}' "$TOTAL"; }
    raw_upper() { one_term "$UPPER"; }
    raw_lower() { one_term "$NAME"; }
    compare "a case-insensitive count of $UPPER equals $NAME's" raw_upper raw_lower
    EXACT=$(raw "{\"filter\":[$T,$(zeek dns),{\"term\":{\"zeek.dns.query\":\"$NAME\"}}]}" '{}' "$TOTAL")
    echo "   · exact-case records of $NAME: $EXACT"

    echo ""
    echo "→ Step 6: /api/domains/$NAME vs OpenSearch..."
    # OLD CODE START — NET-160 review: the page was fetched once per figure
    # D="/api/domains/$NAME?$Q"
    # START=$SECONDS
    # STATUS=$(daemon "$D" status)
    # if [ "$STATUS" = "200" ]; then rc=0; else rc=1; fi
    # check "domain page answers" "$rc" "HTTP $STATUS in $((SECONDS - START)) s"
    # raw_lookups() { raw "{\"filter\":[$T,$(zeek dns),$(ci_name zeek.dns.query "$NAME")],\"must_not\":[$DNS_EXCL,{\"terms\":{\"source.ip\":$EXCL}}]}" '{}' "$TOTAL"; }
    # api_lookups() { daemon "$D" "d['dns']['lookups']"; }
    # compare "lookups (DNS page rules)" raw_lookups api_lookups
    # raw_tls() { raw "{\"filter\":[$T,$(zeek ssl),$(ci_name zeek.ssl.server_name "$NAME")]}" '{}' "$TOTAL"; }
    # api_tls() { daemon "$D" "d['tls']['sessions']"; }
    # compare "TLS sessions" raw_tls api_tls
    # raw_http() { raw "{\"filter\":[$T,$(zeek http),$(ci_name zeek.http.host "$NAME")]}" '{}' "$TOTAL"; }
    # api_http() { daemon "$D" "d['http']['requests']"; }
    # compare "HTTP requests" raw_http api_http
    # echo "   · alert host-name coverage: $(daemon "$D" "d['alerts']")"
    # echo "   · answers: $(daemon "$D" "(d['dns']['addresses'], d['dns']['answers_complete'], [(a['kind'], a['value']) for a in d['dns']['answers'][:5]])")"
    # OLD CODE END
    D="/api/domains/$NAME?$Q"
    raw_lookups() { raw "{\"filter\":[$T,$(zeek dns),$(ci_name zeek.dns.query "$NAME")],\"must_not\":[$DNS_EXCL,{\"terms\":{\"source.ip\":$EXCL}}]}" '{}' "$TOTAL"; }
    raw_tls() { raw "{\"filter\":[$T,$(zeek ssl),$(ci_name zeek.ssl.server_name "$NAME")]}" '{}' "$TOTAL"; }
    raw_http() { raw "{\"filter\":[$T,$(zeek http),$(ci_name zeek.http.host "$NAME")]}" '{}' "$TOTAL"; }
    page_vs_raw "$D" \
        "lookups (DNS page rules)|raw_lookups|r['body']['dns']['lookups']" \
        "TLS sessions|raw_tls|r['body']['tls']['sessions']" \
        "HTTP requests|raw_http|r['body']['http']['requests']"
    echo "   · alert host-name coverage: $(page "r['body']['alerts']")"
    echo "   · answers: $(page "(r['body']['dns']['addresses'], r['body']['dns']['answers_complete'], [(a['kind'], a['value'], a['lookups']) for a in r['body']['dns']['answers'][:5]])")"
    DUP=$(page "len(r['body']['dns']['answers']) - len({(a['kind'], a['value']) for a in r['body']['dns']['answers']})")
    if [ "$DUP" = "0" ]; then rc=0; else rc=1; fi
    check "one row per answer" "$rc" "$DUP duplicate rows"
    CERT=$(daemon "/api/certificates/overview?$Q&site=$NAME" "d.get('summary', {}).get('sessions', 'error')")
    if [[ "$CERT" =~ ^[0-9]+$ ]]; then rc=0; else rc=1; fi
    check "certificates narrowed to $NAME" "$rc" "$CERT sessions with a certificate"
else
    echo "   · no domain looked up in the window; domain checks skipped ($NAME)"
fi
echo ""

echo "→ Step 7: A busy internet address vs OpenSearch..."
PRIVATE='["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","100.64.0.0/10","127.0.0.0/8","169.254.0.0/16","224.0.0.0/4","255.255.255.255","fc00::/7","fe80::/10","ff00::/8"]'
ADDR=$(raw "{\"filter\":[$T,$(zeek conn)],\"must_not\":[{\"terms\":{\"destination.ip\":$PRIVATE}}]}" '{"top":{"terms":{"field":"destination.ip","size":1}}}' "(r['aggregations']['top']['buckets'] or [{}])[0].get('key', '')")
if [[ "$ADDR" =~ ^[0-9a-fA-F:.]+$ ]]; then
    # OLD CODE START — NET-160 review: the page was fetched once per figure
    # A="/api/addresses/$ADDR?$Q"
    # START=$SECONDS
    # STATUS=$(daemon "$A" status)
    # if [ "$STATUS" = "200" ]; then rc=0; else rc=1; fi
    # check "address page for $ADDR answers" "$rc" "HTTP $STATUS in $((SECONDS - START)) s"
    # EITHER="{\"bool\":{\"should\":[{\"term\":{\"source.ip\":\"$ADDR\"}},{\"term\":{\"destination.ip\":\"$ADDR\"}}],\"minimum_should_match\":1}}"
    # raw_conns() { raw "{\"filter\":[$T,$(zeek conn),$EITHER]}" '{}' "$TOTAL"; }
    # api_conns() { daemon "$A" "d['connections']"; }
    # compare "connections (either side, no exclusions)" raw_conns api_conns
    # api_table() { daemon "/api/traffic/connections?$Q&ip=$ADDR&size=1" "d['total']"; }
    # compare "Connections page ?ip= total" raw_conns api_table
    # TO_IT="{\"filter\":{\"term\":{\"destination.ip\":\"$ADDR\"}},\"aggs\":{\"b\":{\"sum\":{\"field\":\"source.bytes\"}}}}"
    # FROM_IT="{\"filter\":{\"bool\":{\"filter\":[{\"term\":{\"source.ip\":\"$ADDR\"}}],\"must_not\":[{\"term\":{\"destination.ip\":\"$ADDR\"}}]}},\"aggs\":{\"b\":{\"sum\":{\"field\":\"destination.bytes\"}}}}"
    # raw_bytes_to() { raw "{\"filter\":[$T,$(zeek conn),$EITHER]}" "{\"to\":$TO_IT,\"from\":$FROM_IT}" "int(r['aggregations']['to']['b']['value'] + r['aggregations']['from']['b']['value'])"; }
    # api_bytes_to() { daemon "$A" "d['bytes_to']['total']"; }
    # compare "data sent to it" raw_bytes_to api_bytes_to
    # raw_alerts() { raw "{\"filter\":[$T,$SURICATA,$EITHER],\"must_not\":[$NOISE]}" '{}' "$TOTAL"; }
    # api_alerts() { daemon "$A" "d['alerts']"; }
    # compare "alerts (either side)" raw_alerts api_alerts
    # echo "   · peers: $(daemon "$A" "(len(d['peers']), d['peers_complete'], d['bytes_to']['partial'], d['threat_intel'] is not None)") (count, complete, bytes partial, threat intel loaded)"
    # OLD CODE END
    A="/api/addresses/$ADDR?$Q"
    EITHER="{\"bool\":{\"should\":[{\"term\":{\"source.ip\":\"$ADDR\"}},{\"term\":{\"destination.ip\":\"$ADDR\"}}],\"minimum_should_match\":1}}"
    raw_conns() { raw "{\"filter\":[$T,$(zeek conn),$EITHER]}" '{}' "$TOTAL"; }
    raw_to_it() { raw "{\"filter\":[$T,$(zeek conn),{\"term\":{\"destination.ip\":\"$ADDR\"}}]}" '{}' "$TOTAL"; }
    TO_IT="{\"filter\":{\"term\":{\"destination.ip\":\"$ADDR\"}},\"aggs\":{\"b\":{\"sum\":{\"field\":\"source.bytes\"}}}}"
    FROM_IT="{\"filter\":{\"bool\":{\"filter\":[{\"term\":{\"source.ip\":\"$ADDR\"}}],\"must_not\":[{\"term\":{\"destination.ip\":\"$ADDR\"}}]}},\"aggs\":{\"b\":{\"sum\":{\"field\":\"destination.bytes\"}}}}"
    raw_bytes_to() { raw "{\"filter\":[$T,$(zeek conn),$EITHER]}" "{\"to\":$TO_IT,\"from\":$FROM_IT}" "int(r['aggregations']['to']['b']['value'] + r['aggregations']['from']['b']['value'])"; }
    raw_alerts() { raw "{\"filter\":[$T,$SURICATA,$EITHER],\"must_not\":[$NOISE]}" '{}' "$TOTAL"; }
    page_vs_raw "$A" \
        "connections (either side, no exclusions)|raw_conns|r['body']['connections']" \
        "data sent to it|raw_bytes_to|r['body']['bytes_to']['total']" \
        "alerts (either side)|raw_alerts|r['body']['alerts']" \
        "ports add up to the connections to it, once each|raw_to_it|sum(p['connections'] for p in r['body']['ports'])"
    echo "   · ports: $(page "[(p['port'], p['transport'], p['services'], p['connections']) for p in r['body']['ports'][:5]]")"
    echo "   · peers: $(page "(len(r['body']['peers']), r['body']['peers_complete'], r['body']['bytes_to']['partial'])") (count, complete, bytes partial)"
    SELF=$(page "'$ADDR' in [p['ip'] for p in r['body']['peers']]")
    if [ "$SELF" = "False" ]; then rc=0; else rc=1; fi
    check "the address is not its own peer" "$rc" "$SELF"
    # A listing-rule alert with $ADDR on one side and a private address on the other names
    # $ADDR as the listed host, so the page must say it is on a list
    OTHER_PRIVATE="{\"bool\":{\"should\":[{\"bool\":{\"filter\":[{\"term\":{\"destination.ip\":\"$ADDR\"}},{\"terms\":{\"source.ip\":$PRIVATE}}]}},{\"bool\":{\"filter\":[{\"term\":{\"source.ip\":\"$ADDR\"}},{\"terms\":{\"destination.ip\":$PRIVATE}}]}}],\"minimum_should_match\":1}}"
    LISTED=$(raw "{\"filter\":[$T,$SURICATA,$LISTING,$OTHER_PRIVATE]}" '{}' "$TOTAL")
    TI=$(page "r['body']['threat_intel']")
    MATCHED=$(page "(r['body']['threat_intel'] or {}).get('matched')")
    if [ "$LISTED" = "0" ] || [ "$MATCHED" = "True" ]; then rc=0; else rc=1; fi
    check "threat intel agrees with this window's listing alerts ($LISTED)" "$rc" "$TI"
    api_table() { daemon "/api/traffic/connections?$Q&ip=$ADDR&size=1" "d['total']"; }
    compare "Connections page ?ip= total" raw_conns api_table
else
    echo "   · no internet destination in the window; address checks skipped ($ADDR)"
fi
echo ""

echo "→ Step 8: Validation and the token..."
BAD=$(daemon "/api/addresses/not-an-ip" status)
if [ "$BAD" = "400" ]; then rc=0; else rc=1; fi
check "a bad address is refused" "$rc" "HTTP $BAD"
BAD=$(daemon "/api/domains/bad..name" status)
if [ "$BAD" = "400" ]; then rc=0; else rc=1; fi
check "a bad name is refused" "$rc" "HTTP $BAD"
OPEN=$(daemon "/api/network/lan" status notoken)
if [ "$OPEN" = "401" ]; then rc=0; else rc=1; fi
check "no token is refused" "$rc" "HTTP $OPEN"
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Drill-downs deployed and verified — open an address and a domain page ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
