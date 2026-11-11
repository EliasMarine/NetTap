#!/usr/bin/env bash
# NET-243: how long a Suricata alert takes to become searchable, and what indexing writes.
#
#   bash scripts/remote/measure-alert-latency.sh [SINCE]
#
# Read-only apart from 12 UDP datagrams carrying "uid=0(root)" (matches ET 2100498, which ET
# rates Informational) to 192.0.2.1, a documentation address nothing answers. Not HTTP: the
# router's own IPS blocks a web host after its first matches, and a blocked handshake never
# carries the payload; the mirror sees a datagram before the router can drop it.
# Run it before and after a Filebeat change and compare. SINCE (ISO time, default 1 hour ago)
# bounds step 2's sample.
#  1. Trigger to first search hit, one trigger at a time, each on its own source port, so the
#     alert matched is that trigger's own packet. Pass: all 12 searchable in under 10 s
#     (the time includes about 0.3 s of docker exec start-up, so it slightly overstates).
#  2. event.ingested - @timestamp over every alert since SINCE (a diagnostic distribution).
#  3. Ten minutes of the data disk's written sectors and OpenSearch's write thread-pool count.
set -u

SINCE="${1:-$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)}"
TRIGGERS=12
FIRST_PORT=41001
TIMEOUT_S=30
GOAL_S=10
SAMPLE_S=600
DISK="${DISK:-nvme0n1}"
SIGNATURE=2100498
TARGET=192.0.2.1  # TEST-NET-1 (RFC 5737)

send_trigger() {
	# one datagram from local port $1, sent by the daemon container (host networking; the host has no python)
	sudo docker exec nettap-storage-daemon python3 -c '
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("", int(sys.argv[1])))
s.sendto(b"nettap latency test uid=0(root)", (sys.argv[2], 9))' "$1" "$TARGET"
}

os() {
	# a search against OpenSearch from inside its container (the host has no client certs)
	sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc \
		--cacert /usr/share/opensearch/config/certs/ca.crt --insecure \
		-H 'Content-Type: application/json' "https://localhost:9200/$1" ${2:+-d "$2"}
}

hits_for_port() {
	# alerts for the signature since $2 on flow port $1 (either direction), as searchable now
	os "arkime_sessions3-*/_count" "{\"query\":{\"bool\":{\"filter\":[
		{\"term\":{\"event.provider\":\"suricata\"}},{\"term\":{\"event.dataset\":\"alert\"}},
		{\"term\":{\"rule.id\":\"$SIGNATURE\"}},{\"range\":{\"@timestamp\":{\"gte\":\"$2\"}}},
		{\"bool\":{\"should\":[{\"term\":{\"source.port\":$1}},{\"term\":{\"destination.port\":$1}}],\"minimum_should_match\":1}}]}}}" |
		grep -o '"count":[0-9]*' | cut -d: -f2
}

echo "=== Alert latency (NET-243) ==="
echo ""

echo "→ Step 1: ${TRIGGERS} triggers, trigger to first search hit (goal under ${GOAL_S} s)..."
measured=0
passed=0
results=""
for i in $(seq 0 $((TRIGGERS - 1))); do
	port=$((FIRST_PORT + i))
	sent_iso=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)
	sent=$(date +%s.%N)
	if ! send_trigger "$port"; then
		echo "   ✗ trigger $((i + 1)) (port $port): couldn't send it, skipped"
		continue
	fi
	found=""
	while :; do
		now=$(date +%s.%N)
		if awk -v n="$now" -v s="$sent" -v t="$TIMEOUT_S" 'BEGIN { exit !(n - s > t) }'; then break; fi
		count=$(hits_for_port "$port" "$sent_iso")
		if [ "${count:-0}" -gt 0 ]; then
			found=$(awk -v n="$now" -v s="$sent" 'BEGIN { printf "%.1f", n - s }')
			break
		fi
		sleep 0.5
	done
	measured=$((measured + 1))
	if [ -z "$found" ]; then
		echo "   ✗ trigger $((i + 1)) (port $port): not searchable within ${TIMEOUT_S} s"
		continue
	fi
	results="$results $found"
	if awk -v f="$found" -v g="$GOAL_S" 'BEGIN { exit !(f < g) }'; then
		passed=$((passed + 1))
		echo "   ✓ trigger $((i + 1)) (port $port): searchable after ${found} s"
	else
		echo "   ✗ trigger $((i + 1)) (port $port): searchable after ${found} s (over ${GOAL_S} s)"
	fi
	sleep 3
done
echo "   times (s):${results}"
if [ "$measured" -ge 10 ] && [ "$passed" -eq "$measured" ]; then
	echo "   ✓ PASS: ${passed}/${measured} searchable in under ${GOAL_S} s"
else
	echo "   ✗ FAIL: ${passed}/${measured} searchable in under ${GOAL_S} s (needs at least 10 measured, all under)"
fi
echo ""

echo "→ Step 2: event.ingested - @timestamp for every alert since ${SINCE}..."
os "arkime_sessions3-*/_search" "{\"size\":5000,\"_source\":[\"@timestamp\",\"event.ingested\"],
	\"query\":{\"bool\":{\"filter\":[{\"term\":{\"event.provider\":\"suricata\"}},
	{\"term\":{\"event.dataset\":\"alert\"}},{\"range\":{\"@timestamp\":{\"gte\":\"$SINCE\"}}}]}}}" |
	sudo docker exec -i nettap-storage-daemon python3 -c '
import json, sys
from datetime import datetime
hits = json.load(sys.stdin).get("hits", {}).get("hits", [])
at = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
lat = sorted(
    (at(h["_source"]["event"]["ingested"]) - at(h["_source"]["@timestamp"])).total_seconds()
    for h in hits
    if (h["_source"].get("event") or {}).get("ingested") and h["_source"].get("@timestamp")
)
if not lat:
    print("   no alerts in the window")
    sys.exit()
q = lambda f: lat[min(len(lat) - 1, int(f * len(lat)))]
over = sum(x > 10 for x in lat)
print(f"   {len(lat)} alerts: median {q(.5):.1f} s, p90 {q(.9):.1f} s, p99 {q(.99):.1f} s, max {lat[-1]:.1f} s; over 10 s: {over} ({over / len(lat):.1%})")
'
echo ""

echo "→ Step 3: ${SAMPLE_S} s of disk writes (${DISK}) and OpenSearch write operations..."
snap() {
	sectors=$(awk '{ print $7 }' "/sys/block/${DISK}/stat")
	writes=$(os "_nodes/stats/thread_pool?filter_path=nodes.*.thread_pool.write.completed" | grep -o '"completed":[0-9]*' | cut -d: -f2)
	echo "$sectors ${writes:-0}"
}
read -r s0 w0 < <(snap)
sleep "$SAMPLE_S"
read -r s1 w1 < <(snap)
echo "   written: $(( (s1 - s0) * 512 / 1048576 )) MiB in ${SAMPLE_S} s (PCAP capture included)"
echo "   OpenSearch write operations: $((w1 - w0)) ($(awk -v w=$((w1 - w0)) -v t="$SAMPLE_S" 'BEGIN { printf "%.2f", w / t }') a second)"
echo ""

echo "→ Step 4: Filebeat's flush setting..."
sudo docker logs nettap-filebeat 2>&1 | grep 'nettap: ' | tail -1 || true
sudo docker exec nettap-filebeat sh -c "grep -A3 '^queue:' /usr/share/filebeat-logs/filebeat-logs.yml" || echo "   (no queue setting: Filebeat's 10 s default)"
echo ""
echo "=== Done ==="
