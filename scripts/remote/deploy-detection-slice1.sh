#!/usr/bin/env bash
# Deploy detection accuracy slice 1 (NET-191) and check it.
# Tracking: tracking-fixes/2026-11-06-detection-accuracy.md
#
#   Alert counts (Alerts, Home, Devices, risk, IoT) leave out what ET rates Informational or Unknown;
#   those are listed as activity (Alerts → "… informational events not counted · Show").
#   192.168.1.44 runs bandwidth-sharing tools on purpose: their rules are suppressed in Suricata for
#   that device only, via /etc/nettap/suricata-threshold.config (loaded by config/suricata/nettap.yaml).
#
# Nothing changes until the fixture replay passes with the new threshold file.
# Rollback of the suppression: write an empty /etc/nettap/suricata-threshold.config, recreate suricata-live.
# The full output is also saved to ~/nettap-detection-slice1.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-detection-slice1.sh
set -u
exec > >(tee "$HOME/nettap-detection-slice1.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="feature/detection-accuracy"
DEVICE="192.168.1.44"
THRESHOLD="/etc/nettap/suricata-threshold.config"
WORK="$HOME/nettap-replay/slice1"
BASELINE="$HOME/nettap-rules-baseline"
SURICATA_LOG="/var/log/suricata/live/suricata.log"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1: $3"; else echo "   ✗ $1: $3"; FAILED=1; fi
}

verify() {  # verify <command> <args…>: scripts/remote/verify_detection_slice1.py inside the daemon
    sudo docker exec nettap-storage-daemon python3 -c "$(cat "$REPO_DIR/scripts/remote/verify_detection_slice1.py")" "$@"
}

suricata_line() {  # suricata_line <pattern>: the last matching line of the live Suricata log
    sudo docker exec nettap-suricata-live grep "$1" "$SURICATA_LOG" 2>/dev/null | tail -1
}

echo "=== Deploy: detection accuracy slice 1 (count by ET severity, .44 suppression) ==="
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
mkdir -p "$WORK" || exit 1
echo ""

echo "→ Step 2: Alert counts before (old daemon, fixed 7-day window)..."
TO=$(date -u -d '-5 min' +%Y-%m-%dT%H:%M:%SZ)
FROM=$(date -u -d "$TO -7 days" +%Y-%m-%dT%H:%M:%SZ)
echo "   window $FROM → $TO"
BEFORE=$(verify counts "$FROM" "$TO" before 2>&1) || FAILED=1
printf '%s\n' "$BEFORE" | grep -v '^OLD_TOTAL=' | sed 's/^/   /'
OLD_TOTAL=$(printf '%s\n' "$BEFORE" | sed -n 's/^OLD_TOTAL=//p')
echo ""

echo "→ Step 3: $DEVICE's bandwidth-sharing rules (ET Informational/Unknown, last 14 days)..."
if ! FOUND=$(verify sids "$DEVICE" 2>&1); then
    printf '%s\n' "$FOUND" | sed 's/^/   /'
    echo "   ✗ Could not read $DEVICE's alerts from OpenSearch — nothing was changed"
    exit 1
fi
printf '%s\n' "$FOUND" | awk -F'\t' 'NF == 4 {printf "   %s  %7d  %-13s %s\n", $1, $2, $3, $4}'
# Plus the SIDs already suppressed for it (once suppressed they never reach OpenSearch, so they drop out of
# the list above), each kept only while the live rule is still an ET Informational/Unknown bandwidth-sharing rule
CARRIED=""
OLD_SIDS=$([ -f "$THRESHOLD" ] && sed -n "s/^suppress gen_id 1, sig_id \([0-9]*\), track by_src, ip $DEVICE\$/\1/p" "$THRESHOLD")
for sid in $OLD_SIDS; do
    RULE=$(sudo docker exec nettap-suricata-live grep -h -m1 "sid:$sid;" /var/lib/suricata/rules/suricata.rules 2>/dev/null)
    if printf '%s' "$RULE" | grep -q 'Bandwidth Sharing Tool' &&
        printf '%s' "$RULE" | grep -Eq 'signature_severity (Informational|Unknown)'; then
        CARRIED="$CARRIED $sid"
    else
        echo "   - $sid no longer suppressed: the live rule is gone or no longer an ET Informational/Unknown bandwidth-sharing rule"
    fi
done
# shellcheck disable=SC2086  # CARRIED is a space-separated SID list
SIDS=$({
    printf '%s\n' "$FOUND" | awk -F'\t' '$1 ~ /^[0-9]+$/ {print $1}'
    printf '%s\n' $CARRIED
} | grep -E '^[0-9]+$' | sort -un)
{
    echo "# NetTap device-local Suricata suppressions (NET-191), written by deploy-detection-slice1.sh $(date -u +%Y-%m-%dT%H:%M:%SZ)."
    echo "# $DEVICE runs bandwidth-sharing tools on purpose; ET rates these rules Informational/Unknown."
    for sid in $SIDS; do echo "suppress gen_id 1, sig_id $sid, track by_src, ip $DEVICE"; done
} > "$WORK/threshold.config"
SUPPRESS_COUNT=$(grep -c '^suppress' "$WORK/threshold.config")
if grep -q 'sig_id 2013075,' "$WORK/threshold.config"; then
    echo "   ✗ 2013075 (Major) would be suppressed — nothing was changed"
    exit 1
fi
echo "   ✓ $SUPPRESS_COUNT suppress line(s) in $WORK/threshold.config (2013075 not among them)"
echo ""

echo "→ Step 4: Replay the fixtures with the new threshold file (nothing live changes)..."
bash "$REPO_DIR/scripts/remote/verify-detection.sh" fixtures --threshold "$WORK/threshold.config" | sed 's/^/   /'
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
    echo "   ✗ Fixture replay failed — nothing was changed"
    exit 1
fi
echo ""

echo "→ Step 5: Save the current rules for slice 2's comparison..."
if [ -d "$BASELINE/rules" ]; then
    echo "   - $BASELINE/rules already saved ($(du -sh "$BASELINE/rules" | cut -f1)), kept"
else
    mkdir -p "$BASELINE"
    if sudo docker cp nettap-suricata-live:/var/lib/suricata/rules - | tar -xf - -C "$BASELINE"; then
        echo "   ✓ $BASELINE/rules ($(du -sh "$BASELINE/rules" | cut -f1))"
    else
        check "rules baseline" 1 "could not copy /var/lib/suricata/rules out of nettap-suricata-live"
    fi
fi
echo ""

echo "→ Step 6: Build the daemon and the web container..."
for svc in nettap-storage-daemon nettap-web; do
    if ! "${COMPOSE[@]}" build "$svc"; then
        echo "   ✗ $svc build failed — nothing was restarted"
        exit 1
    fi
done
echo ""

echo "→ Step 7: Install $THRESHOLD..."
[ -f "$THRESHOLD" ] && cp "$THRESHOLD" "$WORK/threshold.prev" && echo "   previous copy kept in $WORK/threshold.prev"
# /etc/nettap is root's; the daemon (root, /etc/nettap mounted rw) writes it, then renames it into place.
# shellcheck disable=SC2024  # the file is ours; only the daemon's side needs root
sudo docker exec -i nettap-storage-daemon sh -c \
    "cat > $THRESHOLD.new && chmod 644 $THRESHOLD.new && mv $THRESHOLD.new $THRESHOLD" < "$WORK/threshold.config"
if cmp -s "$WORK/threshold.config" "$THRESHOLD"; then rc=0; else rc=1; fi
check "threshold file" "$rc" "$THRESHOLD ($SUPPRESS_COUNT suppress lines)"
[ "$rc" -eq 0 ] || { echo "   ✗ Not installed — nothing was restarted"; exit 1; }
echo ""

echo "→ Step 8: Recreate the daemon, the web container and suricata-live..."
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S')
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web suricata-live
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
# Suricata runs its startup rule update (up to 300 s) before loading rules, so allow 12 minutes
ACTIVATED=""
for _ in $(seq 1 72); do
    LINE=$(suricata_line "Engine started")  # "[78 - Suricata-Main] 2026-11-07 02:54:36 Notice: …" (UTC)
    TS=${LINE#*] }
    TS=${TS:0:19}
    if [ -n "$LINE" ] && ! [[ "$TS" < "$STARTED" ]]; then ACTIVATED="${TS/ /T}Z"; break; fi
    sleep 10
done
if [ -n "$ACTIVATED" ]; then
    check "suricata-live" 0 "engine started at $ACTIVATED"
else
    check "suricata-live" 1 "no 'Engine started' in $SURICATA_LOG since $STARTED UTC"
fi
echo ""

echo "→ Step 9: Suricata loaded the threshold file and the rules..."
if sudo docker exec nettap-suricata-live grep -q "include-configs/nettap.yaml" /etc/suricata/suricata.yaml; then rc=0; else rc=1; fi
check "suricata.yaml includes nettap.yaml" "$rc" "/opt/suricata/include-configs/nettap.yaml"
PARSED=$(suricata_line "Threshold config parsed")
if [ -n "$ACTIVATED" ] && [[ "$PARSED" == *"parsed: $SUPPRESS_COUNT rule(s) found"* ]]; then rc=0; else rc=1; fi
check "threshold file parsed" "$rc" "${PARSED#*threshold-config: } (want $SUPPRESS_COUNT)"
LOADED=$(suricata_line "rules successfully loaded")
if [[ "$LOADED" == *" 0 rules failed"* ]]; then rc=0; else rc=1; fi
check "rules" "$rc" "${LOADED#*detect: }"
echo ""

echo "→ Step 10: Replay the fixtures against the live config..."
bash "$REPO_DIR/scripts/remote/verify-detection.sh" fixtures | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 11: Counts after (same window)..."
verify counts "$FROM" "$TO" after "$OLD_TOTAL" 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 12: Pages that count alerts..."
verify pages "$FROM" "$TO" 2>&1 | sed 's/^/   /'
[ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
echo ""

echo "→ Step 13: $DEVICE's suppressed rules since the engine started..."
if [ -n "$ACTIVATED" ] && [ -n "$SIDS" ]; then
    # Before this deploy these rules fired about 11 times a minute from $DEVICE; give them 5 minutes
    WAIT=$(( $(date -u -d "$ACTIVATED" +%s) + 300 - $(date -u +%s) ))
    [ "$WAIT" -gt 0 ] && echo "   waiting ${WAIT}s so 5 minutes of traffic are indexed..." && sleep "$WAIT"
    verify live "$DEVICE" "$ACTIVATED" "$(printf '%s\n' "$SIDS" | paste -sd, -)" 2>&1 | sed 's/^/   /'
    [ "${PIPESTATUS[0]}" -eq 0 ] || FAILED=1
else
    check "live suppression" 1 "skipped: no engine start time or no SIDs"
fi
echo ""

echo "→ Step 14: Daemon errors since the restart, container status..."
ERRS=$(sudo docker logs --since "${STARTED/ /T}Z" nettap-storage-daemon 2>&1 | grep -E "Traceback|ERROR" | sed 's/^[0-9T:., -]*//' | sort | uniq -c | sort -rn | head -10)
if [ -z "$ERRS" ]; then
    check "daemon log" 0 "no errors or tracebacks since $STARTED UTC"
else
    check "daemon log" 1 "errors since $STARTED UTC:"
    echo "      ${ERRS//$'\n'/$'\n'      }"
fi
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|suricata-live"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Detection accuracy slice 1 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
