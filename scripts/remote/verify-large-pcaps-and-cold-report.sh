#!/usr/bin/env bash
# Read-only checks for two loose ends of the dashboard data-accuracy work.
# Tracking: tracking-fixes/2026-11-01-dashboard-data-accuracy.md
#
#   1. Every PCAP file over 600 MiB is searched to the end with exactly PCAP Search's command
#      (`http || tls`, in nettap-tshark, under the same 300 s timeout), so none runs out of
#      memory (#137: tshark needs about 120 MiB plus the file, the container has 1 GiB).
#   2. The threat report on cold caches (#139): OpenSearch's query, request and fielddata
#      caches are cleared, then the report is timed cold and warm, with the liveness check
#      timed during the cold run. Clearing caches deletes no data; it costs one slow query.
#
# The full output is also saved to ~/nettap-large-pcaps-cold-report.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/verify-large-pcaps-and-cold-report.sh
set -u
exec > >(tee "$HOME/nettap-large-pcaps-cold-report.log") 2>&1

SEARCH_TIMEOUT_S=300
REPORT_BUDGET_S=10
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

daemon_get() {  # daemon_get PATH: prints "<http code> <seconds>" and saves the body in the container
    sudo docker exec nettap-storage-daemon sh -c "curl -s -o /tmp/nettap-check.json -w '%{http_code} %{time_total}' \
        -H \"X-NetTap-Daemon-Token: \$(cat /run/nettap-auth/daemon-token)\" 'http://localhost:8880$1'"
}

echo "=== Large PCAP files and the cold threat report ==="
echo ""

echo "→ Step 1: Wait for any running PCAP search or TShark job (not interrupting it)..."
for i in $(seq 1 60); do
    BUSY=$(sudo docker exec nettap-tshark sh -c 'pgrep -x tshark | wc -l' 2>/dev/null || echo 0)
    [ "$BUSY" -eq 0 ] && break
    echo "   tshark busy ($BUSY), waiting ($i/60)"
    sleep 10
done
echo "   TShark container idle"
echo ""

echo "→ Step 2: Search every PCAP file over 600 MiB to the end, as PCAP Search does..."
PCAP_DIR=$(sudo docker volume inspect docker_pcap-data --format '{{.Mountpoint}}' 2>/dev/null)
LIMIT_MIB=$(( $(sudo docker inspect nettap-tshark --format '{{.HostConfig.Memory}}') / 1048576 ))
echo "   TShark container memory limit: ${LIMIT_MIB} MiB"
FILES=$(sudo find "$PCAP_DIR" -maxdepth 1 -type f -name 'mnetsniff-*.pcap' -size +600M -printf '%s %f\n' | sort -n)
[ -n "$FILES" ] || echo "   (no files over 600 MiB)"
while read -r BYTES NAME; do
    [ -n "${NAME:-}" ] || continue
    START=$(date +%s)
    OUT=$(sudo docker exec nettap-tshark sh -c "timeout -k 5 $SEARCH_TIMEOUT_S nice -n 19 tshark -r '/pcap/$NAME' -Y 'http || tls' -T fields -e frame.number >/tmp/nettap-out 2>/dev/null; echo \"\$? \$(wc -l < /tmp/nettap-out)\"; rm -f /tmp/nettap-out" 2>&1)
    SECS=$(( $(date +%s) - START ))
    read -r RC COUNT <<<"$OUT"
    if [ "$RC" = "0" ]; then rc=0; else rc=1; fi
    check "$NAME ($(( BYTES / 1048576 )) MiB)" "$rc" "$COUNT matches in ${SECS} s, tshark exit $RC (137 = out of memory, 124 = timeout)"
done <<<"$FILES"
PEAK=$(sudo docker exec nettap-tshark sh -c 'cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo 0')
echo "   TShark container memory peak since it started: $(( PEAK / 1048576 )) MiB of ${LIMIT_MIB} MiB"
echo ""

echo "→ Step 3: Threat report on cold OpenSearch caches..."
FROM=$(date -u -d '-24 hours' +%Y-%m-%dT%H:%M:%SZ)
TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CLEAR=$(sudo docker exec nettap-opensearch curl -s --config /var/local/curlrc/.opensearch.primary.curlrc --insecure \
    -X POST 'https://localhost:9200/_cache/clear?query=true&request=true&fielddata=true' 2>&1)
if printf '%s' "$CLEAR" | grep -q '"failed":0'; then rc=0; else rc=1; fi
check "OpenSearch caches cleared" "$rc" "$(printf '%s' "$CLEAR" | head -c 120)"
daemon_get "/api/threats/report?from=$FROM&to=$TO" > /tmp/nettap-cold.txt &
REPORT_PID=$!
sleep 1
HEALTH=$(daemon_get "/api/health")
wait "$REPORT_PID"
read -r CODE SECS < /tmp/nettap-cold.txt
rm -f /tmp/nettap-cold.txt
FAILED_CHECKS=$(sudo docker exec nettap-storage-daemon python3 -c "import json; r = json.load(open('/tmp/nettap-check.json')); print(r.get('failed_checks'), r.get('incomplete_checks'))" 2>&1)
if [ "$CODE" = "200" ] && awk "BEGIN { exit !($SECS < $REPORT_BUDGET_S) }"; then rc=0; else rc=1; fi
check "threat report, cold caches, under ${REPORT_BUDGET_S} s" "$rc" "HTTP $CODE in ${SECS} s; failed/partial checks: $FAILED_CHECKS"
read -r H_CODE H_SECS <<<"$HEALTH"
if [ "$H_CODE" = "200" ] && awk "BEGIN { exit !($H_SECS < 1) }"; then rc=0; else rc=1; fi
check "liveness check during the cold report" "$rc" "HTTP $H_CODE in ${H_SECS} s"
read -r CODE SECS <<<"$(daemon_get "/api/threats/report?from=$FROM&to=$TO")"
if [ "$CODE" = "200" ] && awk "BEGIN { exit !($SECS < $REPORT_BUDGET_S) }"; then rc=0; else rc=1; fi
check "threat report, warm" "$rc" "HTTP $CODE in ${SECS} s"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== All checks passed ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
