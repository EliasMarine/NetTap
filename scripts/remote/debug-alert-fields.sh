#!/usr/bin/env bash
# Debug script: Check what fields exist in Suricata alert documents
# Run on the NetTap device: sudo bash scripts/remote/debug-alert-fields.sh

set -u

CURL_OPTS="--config /var/local/curlrc/.opensearch.primary.curlrc --cacert /usr/share/opensearch/config/certs/ca.crt --insecure -s"

echo "=== Step 1: Fetch one raw Suricata alert document ==="
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 1,
    "query": {
      "bool": {
        "filter": [
          {"term": {"event.provider": "suricata"}},
          {"term": {"event.dataset": "alert"}}
        ]
      }
    }
  }' | python3 -m json.tool 2>/dev/null | head -100

echo ""
echo "=== Step 2: Check severity field paths ==="
echo "--- suricata.severity ---"
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {"bool": {"filter": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}]}},
    "aggs": {"sev": {"terms": {"field": "suricata.severity.keyword", "size": 10}}}
  }' | python3 -m json.tool 2>/dev/null

echo ""
echo "--- suricata.alert.severity ---"
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {"bool": {"filter": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}]}},
    "aggs": {"sev": {"terms": {"field": "suricata.alert.severity", "size": 10}}}
  }' | python3 -m json.tool 2>/dev/null

echo ""
echo "--- alert.severity ---"
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {"bool": {"filter": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}]}},
    "aggs": {"sev": {"terms": {"field": "alert.severity", "size": 10}}}
  }' | python3 -m json.tool 2>/dev/null

echo ""
echo "--- rule.severity ---"
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {"bool": {"filter": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}]}},
    "aggs": {"sev": {"terms": {"field": "rule.severity", "size": 10}}}
  }' | python3 -m json.tool 2>/dev/null

echo ""
echo "=== Step 3: Check IP field paths ==="
echo "--- source.ip ---"
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {"bool": {"filter": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}]}},
    "aggs": {"ips": {"terms": {"field": "source.ip", "size": 5}}}
  }' | python3 -m json.tool 2>/dev/null

echo ""
echo "--- destination.ip ---"
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {"bool": {"filter": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}]}},
    "aggs": {"ips": {"terms": {"field": "destination.ip", "size": 5}}}
  }' | python3 -m json.tool 2>/dev/null

echo ""
echo "=== Step 4: Check signature field path ==="
echo "--- rule.name.keyword ---"
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {"bool": {"filter": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}]}},
    "aggs": {"sigs": {"terms": {"field": "rule.name.keyword", "size": 5}}}
  }' | python3 -m json.tool 2>/dev/null

echo ""
echo "=== Step 5: List all top-level field names in a Suricata alert doc ==="
sudo docker exec nettap-opensearch curl $CURL_OPTS \
  'https://localhost:9200/arkime_sessions3-*/_search' \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 1,
    "query": {"bool": {"filter": [{"term": {"event.provider": "suricata"}}, {"term": {"event.dataset": "alert"}}]}},
    "_source": true
  }' | python3 -c "
import json, sys
data = json.load(sys.stdin)
hits = data.get('hits',{}).get('hits',[])
if hits:
    src = hits[0].get('_source',{})
    print('Top-level keys:', sorted(src.keys()))
    # Print suricata sub-keys if present
    if 'suricata' in src:
        print('suricata sub-keys:', sorted(src['suricata'].keys()) if isinstance(src['suricata'], dict) else src['suricata'])
    if 'alert' in src:
        print('alert sub-keys:', sorted(src['alert'].keys()) if isinstance(src['alert'], dict) else src['alert'])
    if 'rule' in src:
        print('rule sub-keys:', sorted(src['rule'].keys()) if isinstance(src['rule'], dict) else src['rule'])
    if 'source' in src:
        print('source sub-keys:', sorted(src['source'].keys()) if isinstance(src['source'], dict) else src['source'])
    if 'destination' in src:
        print('destination sub-keys:', sorted(src['destination'].keys()) if isinstance(src['destination'], dict) else src['destination'])
else:
    print('No hits found')
" 2>/dev/null

echo ""
echo "=== Done ==="
