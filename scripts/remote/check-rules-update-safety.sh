#!/usr/bin/env bash
# Rule update safety checks on the device (NET-191 slice 2, plan "Verification plan"). Run after
# deploy-detection-slice2.sh (and after check-etpro-canary.sh if you run both).
#
#   A. A failing update keeps the previous rules: "Update now" with an unreachable extra source, then with an
#      extra source holding a broken rule (Suricata's test must refuse it). Each time: status "failed", the
#      rules file and the loaded count unchanged, 0 failed rules. Both test sources are removed after.
#   B. Overlap: while "Update now" runs, the daemon can't take the rules lock, and a lock taker on the host
#      gets it only after the update recorded its result.
#   C. suricata-live is recreated (the deploy path, holding the lock) while two manual updates are running or
#      queued: none is cut off mid-write (no in-progress marker left, no "interrupted" status), and the new
#      container's own update completes.
# Downloads the rule sources four times and recreates suricata-live once (~20-30 min in all).
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/check-rules-update-safety.sh
set -u

REPO_DIR="/home/nettap/NetTap"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
SU=(--suricata /usr/bin/suricata-offline --data-dir /var/lib/suricata --config /etc/suricata/update.yaml
    --suricata-conf /etc/suricata/suricata.yaml)
WORK="$HOME/nettap-replay/update-safety-$(date -u +%Y%m%dT%H%M%SZ)"
cd "$REPO_DIR" || { echo "✗ $REPO_DIR not found"; exit 1; }
# shellcheck source=scripts/remote/rules-checks.sh
. "$REPO_DIR/scripts/remote/rules-checks.sh"
# shellcheck source=scripts/remote/rules-lock.sh
. "$REPO_DIR/scripts/remote/rules-lock.sh"
cleanup() {
    rules_lock_release
    sudo docker exec -u suricata "$LIVE" suricata-update remove-source nettap-test-unreachable --quiet "${SU[@]}" >/dev/null 2>&1
    sudo docker exec -u suricata "$LIVE" suricata-update remove-source nettap-test-broken --quiet "${SU[@]}" >/dev/null 2>&1
}
trap cleanup EXIT
mkdir -p "$WORK" || exit 1

update_now() {  # update_now <label>: "Update now" through the daemon, then wait for the status record
    local before result
    before=$(status_field attempt)
    result=$(api POST /api/suricata/rules/update '{}')
    echo "   $1: HTTP ${result%% *}, $(json_get "${result#* }" '"success \(.success), \(.reload_output // .error // "")"')"
    wait_update_finished "$before" 90 || check "$1" 1 "no finished update recorded after 15 minutes"
}

expect_kept() {  # expect_kept <label>: failed, nothing changed
    local state
    state=$(status_field state)
    if [ "$state" = failed ]; then rc=0; else rc=1; fi
    check "$1 status" "$rc" "${state:-none}: $(status_field reason)"
    read -r LOADED NFAILED <<<"$(engine_stats)"
    if [ "$(rules_sha)" = "$SHA_BEFORE" ] && [ "${LOADED:-0}" = "$LOADED_BEFORE" ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
    check "$1 previous rules kept" "$rc" "rules file $(rules_sha) (before $SHA_BEFORE), ${LOADED:-?} loaded (before $LOADED_BEFORE), ${NFAILED:-?} failed"
    if marker_present; then rc=1; else rc=0; fi
    check "$1 no update left half-done" "$rc" "in-progress marker $([ "$rc" -eq 0 ] && echo absent || echo present)"
}

echo "=== Rule update safety checks ==="
echo ""

echo "→ Step 1: Preflight..."
preflight_clean ""
echo ""

echo "→ Step 2 (A1): An unreachable extra source..."
sudo docker exec -u suricata "$LIVE" suricata-update add-source nettap-test-unreachable \
    https://nettap-test.invalid/rules.tar.gz --quiet "${SU[@]}" >/dev/null 2>&1
update_now "unreachable source"
expect_kept "unreachable source"
sudo docker exec -u suricata "$LIVE" suricata-update remove-source nettap-test-unreachable --quiet "${SU[@]}" >/dev/null 2>&1
echo ""

echo "→ Step 3 (A2): An extra source with a broken rule..."
# shellcheck disable=SC2016
sudo docker exec -u suricata "$LIVE" sh -c 'printf "%s\n" "alert tcp any any -> any any (msg:\"NetTap broken test rule\"; content:; sid:1999999; rev:1;)" > /tmp/nettap-test-broken.rules'
sudo docker exec -u suricata "$LIVE" suricata-update add-source nettap-test-broken \
    file:///tmp/nettap-test-broken.rules --quiet "${SU[@]}" >/dev/null 2>&1
update_now "broken rule"
expect_kept "broken rule"
sudo docker exec -u suricata "$LIVE" suricata-update remove-source nettap-test-broken --quiet "${SU[@]}" >/dev/null 2>&1
echo ""

echo "→ Step 4 (B): Overlap — the lock while \"Update now\" runs..."
BEFORE=$(status_field attempt)
api POST /api/suricata/rules/update '{}' > "$WORK/overlap-update.txt" &
API_PID=$!
for _ in $(seq 1 60); do marker_present && break; sleep 1; done
if marker_present; then
    # shellcheck disable=SC2016
    TRY=$(sudo docker exec "$DAEMON" python3 -c '
import fcntl, os
fd = os.open("/var/run/nettap-rules/rules.lock", os.O_RDONLY)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("free")
except BlockingIOError:
    print("busy")
' 2>&1)
    if [ "$TRY" = busy ]; then rc=0; else rc=1; fi
    check "daemon sees the lock held" "$rc" "$TRY"
    rules_lock_take "$LIVE"
    TAKEN=$?
    ATTEMPT=$(status_field attempt)
    if [ "$TAKEN" -eq 0 ] && ! marker_present && [ "$ATTEMPT" != "$BEFORE" ] && [ "$(status_field state)" = active ]; then rc=0; else rc=1; fi
    check "lock taker waited for the update" "$rc" "lock $([ "$TAKEN" -eq 0 ] && echo taken || echo "not taken ($TAKEN)") after the update recorded $(status_field state) at ${ATTEMPT:-?}"
    rules_lock_release
else
    check "update started" 1 "no in-progress marker within 60 s"
fi
wait "$API_PID"
echo "   \"Update now\" answered HTTP $(cut -d' ' -f1 "$WORK/overlap-update.txt")"
echo ""

echo "→ Step 5 (C): Recreate suricata-live while manual updates run..."
UPDATE=(sudo docker exec -u suricata "$LIVE" /usr/local/bin/suricata-update-rules.sh)
"${UPDATE[@]}" > "$WORK/manual-1.log" 2>&1 &
PID1=$!
for _ in $(seq 1 60); do marker_present && break; sleep 1; done
"${UPDATE[@]}" > "$WORK/manual-2.log" 2>&1 &
PID2=$!
sleep 5
rules_lock_take "$LIVE"
TAKEN=$?
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S')
if [ "$TAKEN" -eq 0 ]; then
    "${COMPOSE[@]}" up -d --no-deps --force-recreate suricata-live
fi
rules_lock_release
wait "$PID1"
RC1=$?
wait "$PID2"
RC2=$?
echo "   manual update 1 exit $RC1, manual update 2 exit $RC2 (one waiting for the lock is stopped with the old container)"
if [ "$TAKEN" -eq 0 ] && ACTIVATED=$(engine_started_since "$STARTED" 90); then rc=0; else rc=1; fi
check "recreated" "$rc" "lock $([ "$TAKEN" -eq 0 ] && echo held || echo "not taken ($TAKEN)"), engine started ${ACTIVATED:-not seen}"
STATE=$(status_field state)
ATTEMPT=$(status_field attempt)
if [[ "$STATE" =~ ^(active|prepared)$ ]] && ! [[ "${ATTEMPT/T/ }" < "$STARTED" ]] && ! marker_present; then rc=0; else rc=1; fi
check "new container's update completed" "$rc" "${STATE:-none} at ${ATTEMPT:-?} (recreated $STARTED UTC), marker $(marker_present && echo present || echo absent)"
read -r LOADED NFAILED <<<"$(engine_stats)"
if [ "${LOADED:-0}" -gt 0 ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
check "engine" "$rc" "${LOADED:-?} loaded, ${NFAILED:-?} failed"
# OLD CODE START — NET-191 slice 2 ponytail review: nothing prints "interrupted", so this could never fail
# if grep -q "interrupted" "$WORK"/manual-*.log; then rc=1; else rc=0; fi
# check "no update cut off mid-write" "$rc" "logs in $WORK"
# OLD CODE END
# An update cut off mid-write leaves its marker, and the new container's startup says so when it recovers
if sudo docker logs --since "${STARTED/ /T}Z" "$LIVE" 2>&1 | grep -q "a previous update did not finish"; then rc=1; else rc=0; fi
check "no update cut off mid-write" "$rc" "new container's log $([ "$rc" -eq 0 ] && echo "has no recovery line" || echo "says it restored the last good rules"), manual logs in $WORK"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Rule update safety checks passed ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
