#!/usr/bin/env bash
# Deploy detection slice 2 (NET-191): more free rule sources, the optional ET Pro code, one rules lock,
# last-good recovery and an update status record. Tracking: tracking-fixes/2026-11-06-detection-accuracy.md
#
#   Sources: et/open, abuse.ch/sslbl-blacklist, echap/stalkerware, ipfire/dbl (IPFire: only the Malware
#   and Phishing categories, via SURICATA_DISABLE_SIDS). Every rule update (startup, nightly, "Update now")
#   runs config/suricata/nettap-rules-update.sh inside one lock on the nettap-rules-state volume.
#
# The gate runs first (gate-detection-slice2.sh): if it fails, nothing is built or restarted.
# suricata-live is recreated holding the rules lock (scripts/remote/rules-lock.sh) so no update is cut off.
# Rollback: bash /home/nettap/NetTap/scripts/remote/rollback-detection-slice2.sh
# Then, separately (they change the device on purpose):
#   bash /home/nettap/NetTap/scripts/remote/check-etpro-canary.sh
#   bash /home/nettap/NetTap/scripts/remote/check-rules-update-safety.sh
# The full output is also saved to ~/nettap-detection-slice2.log.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-detection-slice2.sh
set -u
exec > >(tee "$HOME/nettap-detection-slice2.log") 2>&1

REPO_DIR="/home/nettap/NetTap"
BRANCH="feature/detection-slice2"  # set to main once the PR is merged
BASELINE="$HOME/nettap-rules-baseline"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)

echo "=== Deploy: detection slice 2 (rule sources, ET Pro code, rules lock) ==="
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
# shellcheck source=scripts/remote/rules-checks.sh
. "$REPO_DIR/scripts/remote/rules-checks.sh"
# shellcheck source=scripts/remote/rules-lock.sh
. "$REPO_DIR/scripts/remote/rules-lock.sh"
trap rules_lock_release EXIT
echo ""

echo "→ Step 2: Timing..."
if [ -z "$(sudo docker inspect -f '{{range .Mounts}}{{if eq .Destination "/run/nettap-rules"}}{{.Name}}{{end}}{{end}}' "$LIVE" 2>/dev/null)" ]; then
    # First deploy: the running suricata-live has no rules lock; stay clear of Malcolm's 00:00 UTC update
    NOW_HHMM=$((10#$(date -u +%H%M)))
    if [ "$NOW_HHMM" -ge 2300 ] || [ "$NOW_HHMM" -lt 30 ]; then
        echo "   ✗ $(date -u +%H:%M) UTC is inside 23:00-00:30, around the nightly rule update. Run after 00:30 UTC."
        exit 1
    fi
    echo "   ✓ no rules lock yet (first deploy); outside the nightly update window"
else
    echo "   ✓ suricata-live already has the rules lock; the recreate below holds it"
fi
RSS_BEFORE=$(sudo docker stats --no-stream --format '{{.MemUsage}}' "$LIVE" 2>/dev/null | cut -d/ -f1)
echo "   suricata-live memory before: ${RSS_BEFORE:-n/a}"
echo ""

echo "→ Step 3: Gate — try the new sources in throwaway containers (nothing live changes)..."
bash "$REPO_DIR/scripts/remote/gate-detection-slice2.sh" | sed 's/^/   /'
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
    echo "   ✗ Gate failed — nothing was built or restarted"
    exit 1
fi
echo ""

echo "→ Step 4: Keep the current rules as a baseline..."
if [ -d "$BASELINE/rules" ]; then
    echo "   - $BASELINE/rules already saved ($(du -sh "$BASELINE/rules" | cut -f1)), kept"
else
    mkdir -p "$BASELINE"
    if sudo docker cp "$LIVE:/var/lib/suricata/rules" - | tar -xf - -C "$BASELINE"; then
        echo "   ✓ $BASELINE/rules ($(du -sh "$BASELINE/rules" | cut -f1))"
    else
        check "rules baseline" 1 "could not copy /var/lib/suricata/rules out of $LIVE"
    fi
fi
echo ""

echo "→ Step 5: Build the daemon and the web container..."
for svc in nettap-storage-daemon nettap-web; do
    if ! "${COMPOSE[@]}" build "$svc"; then
        echo "   ✗ $svc build failed — nothing was restarted"
        exit 1
    fi
done
echo ""

echo "→ Step 6: Recreate the daemon and the web container..."
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S')
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
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

echo "→ Step 7: Recreate suricata-live holding the rules lock..."
rules_lock_take "$LIVE"
case $? in
    0) echo "   ✓ holding the rules lock" ;;
    2) echo "   - no rules lock on the running container yet (first deploy)" ;;
    *) echo "   ✗ A rule update held the lock for 15 minutes — suricata-live was not recreated; run this again"; exit 1 ;;
esac
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S')
"${COMPOSE[@]}" up -d --no-deps --force-recreate suricata-live
rules_lock_release
echo "   ✓ recreated at $STARTED UTC; lock released, so its startup update can take it"
echo ""

echo "→ Step 8: Wait for the startup rule update and the engine (≤ 15 min)..."
if ACTIVATED=$(engine_started_since "$STARTED" 90); then
    check "suricata-live" 0 "engine started at $ACTIVATED"
else
    check "suricata-live" 1 "no 'Engine started' in $SURICATA_LOG since $STARTED UTC"
fi
echo ""

echo "→ Step 9: What the new container runs..."
EXPECTED="$FREE_SOURCES"
if sudo docker exec "$DAEMON" test -f /etc/nettap/suricata.env; then
    EXPECTED=$(tr , '\n' <<<"$FREE_SOURCES" | sed 's#^et/open$#et/pro#' | sort | paste -sd, -)
    echo "   (an ET Pro code is saved: et/pro instead of et/open)"
fi
GOT=$(enabled_sources)
if [ "$GOT" = "$EXPECTED" ]; then rc=0; else rc=1; fi
check "enabled sources" "$rc" "${GOT:-none} (want $EXPECTED)"
if sudo docker exec "$LIVE" grep -qF 're:msg:"IPFire DBL \[(?!Malware\]|Phishing\])' /etc/suricata/disable.conf; then rc=0; else rc=1; fi
check "IPFire allowlist" "$rc" "in /etc/suricata/disable.conf"
if sudo docker exec "$LIVE" grep -q 'nettap-rules-update shim' /usr/local/bin/suricata-update-rules.sh &&
    sudo docker exec "$LIVE" test -s /usr/local/bin/malcolm-suricata-update-rules.sh; then rc=0; else rc=1; fi
check "update shim" "$rc" "suricata-update-rules.sh → nettap-rules-update.sh; Malcolm's kept as malcolm-suricata-update-rules.sh"
STATE=$(status_field state)
ATTEMPT=$(status_field attempt)
if [[ "$STATE" =~ ^(active|prepared)$ ]] && ! [[ "${ATTEMPT/T/ }" < "$STARTED" ]] && ! marker_present; then rc=0; else rc=1; fi
check "startup update" "$rc" "${STATE:-no status record} at ${ATTEMPT:-?} $(status_field reason)"
if sudo docker exec "$LIVE" test -L /run/nettap-rules/last-good; then rc=0; else rc=1; fi
check "last good rules" "$rc" "/run/nettap-rules/$(sudo docker exec "$LIVE" readlink /run/nettap-rules/last-good 2>/dev/null)"
read -r LOADED NFAILED <<<"$(engine_stats)"
if [ "${LOADED:-0}" -gt 0 ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
check "engine" "$rc" "${LOADED:-?} rules loaded, ${NFAILED:-?} failed"
LIVE_STATUS=$(api GET /api/suricata/rules/live)
UPDATE_STATE=$(json_get "${LIVE_STATUS#* }" '.update.state // "none"')
if [ "${LIVE_STATUS%% *}" = 200 ] && [ "$UPDATE_STATE" = active ]; then rc=0; else rc=1; fi
check "Settings live status" "$rc" "HTTP ${LIVE_STATUS%% *}, update $UPDATE_STATE, $(json_get "${LIVE_STATUS#* }" '"engine \(.engine.loaded) loaded / \(.engine.failed) failed, ET Pro rules \(.etpro_rules)"')"
echo ""

echo "→ Step 10: Memory and capture..."
echo "   suricata-live memory: ${RSS_BEFORE:-n/a} before → $(sudo docker stats --no-stream --format '{{.MemUsage}}' "$LIVE" 2>/dev/null | cut -d/ -f1)"
echo "   host MemAvailable: $(awk '/^MemAvailable:/ {printf "%.0f MiB", $2 / 1024}' /proc/meminfo)"
echo "   capture since start: $(live_jq dump-counters '.message.capture | "\(.kernel_packets) packets, \(.kernel_drops) dropped"')"
echo ""

echo "→ Step 11: Replay the fixtures against the live rules..."
REPORT=$(bash "$REPO_DIR/scripts/remote/verify-detection.sh" fixtures 2>&1)
RC=$?
# shellcheck disable=SC2001
sed 's/^/   /' <<<"$REPORT"
check "fixture replay" "$RC" "exit $RC"
for name in ipfire-malware ipfire-phishing ipfire-disabled-doh echap-stalkerware; do
    if grep -q "PASS     $name\$" <<<"$REPORT"; then rc=0; else rc=1; fi
    check "$name" "$rc" "$(grep -m1 -E "(PASS|FAIL|SKIPPED) +$name" <<<"$REPORT" | sed 's/^ *//')"
done
echo ""

echo "→ Step 12: \"Update now\" through the daemon (≤ 15 min)..."
BEFORE_ATTEMPT=$(status_field attempt)
RESULT=$(api POST /api/suricata/rules/update '{}')
echo "   HTTP ${RESULT%% *}: $(json_get "${RESULT#* }" '"success \(.success), running \(.running // false), \(.reload_output // .error // "")"')"
if wait_update_finished "$BEFORE_ATTEMPT" 90; then
    read -r LOADED NFAILED <<<"$(engine_stats)"
    if [ "$(status_field state)" = active ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
    check "Update now" "$rc" "$(status_field state) at $(status_field attempt), activated $(status_field last_activation); ${LOADED:-?} loaded, ${NFAILED:-?} failed $(status_field reason)"
else
    check "Update now" 1 "no finished update recorded after 15 minutes"
fi
echo ""

echo "→ Step 13: Daemon errors since the restart, container status..."
ERRS=$(sudo docker logs --since "${STARTED/ /T}Z" "$DAEMON" 2>&1 | grep -E "Traceback|ERROR" | sed 's/^[0-9T:., -]*//' | sort | uniq -c | sort -rn | head -10)
if [ -z "$ERRS" ]; then
    check "daemon log" 0 "no errors or tracebacks since $STARTED UTC"
else
    check "daemon log" 1 "errors since $STARTED UTC:"
    echo "      ${ERRS//$'\n'/$'\n'      }"
fi
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|storage-daemon|nettap-web|suricata-live"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Detection slice 2 deployed and verified ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
