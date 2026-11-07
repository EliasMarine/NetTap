#!/usr/bin/env bash
# Check own Suricata rules end to end on the device (NET-191 slice 3). It changes the device on purpose:
# it saves a test rule through the daemon (Settings › Suricata rules does the same), replays its
# fixture, restarts suricata-live, then clears the rules again.
#
#   1. refuses unless Suricata runs cleanly and there are no own rules yet (it would replace them)
#   2. save the self-test rule (sid 1999999 on nettap-selftest.invalid): the engine loads one more rule
#   3. fixture replay: the self-test fires
#   4. restart suricata-live holding the rules lock: the rule is still listed and loaded
#   5. clear the rules: the engine loads one rule fewer, 0 failed
#   6. fixture replay: the self-test no longer fires
# A run that stops part-way clears the test rule on exit.
# Run as the normal user (NOT with sudo), after deploy-detection-slice3.sh:
#   bash /home/nettap/NetTap/scripts/remote/check-owner-rules.sh
# The full output is also saved to ~/nettap-check-owner-rules.log.
set -u
exec > >(tee "$HOME/nettap-check-owner-rules.log") 2>&1

REPO_DIR="${NETTAP_REPO_DIR:-/home/nettap/NetTap}"  # override for tests only
TEST_RULE='alert dns any any -> any any (msg:"NetTap owner rule self-test"; dns.query; content:"nettap-selftest.invalid"; nocase; sid:1999999; rev:1;)'
OWNER_FILE="/opt/suricata/rules/custom/owner.rules"
SAVED=0

# shellcheck source=scripts/remote/rules-checks.sh
. "$REPO_DIR/scripts/remote/rules-checks.sh"
# shellcheck source=scripts/remote/rules-lock.sh
. "$REPO_DIR/scripts/remote/rules-lock.sh"

save_rules() {  # save_rules <rules text>: "<HTTP status> <body>"; quotes are escaped, \n is passed as JSON's newline
    local body
    body=$(printf '{"content": "%s"}' "${1//\"/\\\"}")
    api POST /api/suricata/rules/custom "$body"
}
# shellcheck disable=SC2329  # run by the EXIT trap
cleanup() {
    rules_lock_release
    if [ "$SAVED" -eq 1 ]; then
        echo "   - clearing the test rule: HTTP $(save_rules "" | cut -d' ' -f1)"
    fi
}
trap cleanup EXIT
one_more() {  # one_more <a> <b>: a = b + 1 (both numbers; Suricata may not have answered)
    [[ "$1" =~ ^[0-9]+$ && "$2" =~ ^[0-9]+$ ]] && [ $(($1 - $2)) -eq 1 ]
}
owner_count() { json_get "$(api GET /api/suricata/rules/live | cut -d' ' -f2-)" '.owner_rules // "none"'; }
replay() {  # replay present|absent
    local report rc
    report=$(bash "$REPO_DIR/scripts/remote/verify-detection.sh" fixtures --owner-rule "$1" 2>&1)
    rc=$?
    # shellcheck disable=SC2001
    sed 's/^/   /' <<<"$report"
    if grep -q "PASS     owner-selftest\$" <<<"$report"; then rc=0; else rc=1; fi
    check "self-test $1" "$rc" "$(grep -m1 -E "(PASS|FAIL|SKIPPED) +owner-selftest" <<<"$report" | sed 's/^ *//')"
}

echo "=== Check: own Suricata rules (NET-191 slice 3) ==="
echo ""

echo "→ Step 1: Preflight..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
preflight_clean ""
CUSTOM=$(api GET /api/suricata/rules/custom)
COUNT=$(json_get "${CUSTOM#* }" '.rule_count')
SIZE=$(json_get "${CUSTOM#* }" '.content | length')  # comments count too: the save replaces the file
if [ "${CUSTOM%% *}" != 200 ] || [ "$(owner_count)" = none ]; then
    echo "   ✗ Own rules are not set up (HTTP ${CUSTOM%% *}, owner rules in suricata-live: $(owner_count)). Run deploy-detection-slice3.sh first."
    exit 3
fi
if [ "$COUNT" != 0 ] || [ "$SIZE" != 0 ]; then
    echo "   ✗ Your own rules aren't empty ($COUNT rules, $SIZE characters); this check would replace them. Copy them from Settings › Suricata rules, clear them, run this, then paste them back."
    exit 3
fi
echo "   ✓ the own rules are empty"
echo ""

echo "→ Step 2: Save the self-test rule through the daemon (Suricata's test, then a reload)..."
RESULT=$(save_rules "$TEST_RULE\n")
SAVED=1
read -r LOADED NFAILED <<<"$(engine_stats)"
if [ "${RESULT%% *}" = 200 ] && [ "$(owner_count)" = 1 ] && [ "${NFAILED:-x}" = 0 ] &&
    one_more "$LOADED" "$LOADED_BEFORE"; then rc=0; else rc=1; fi
check "save" "$rc" "HTTP ${RESULT%% *} $(json_get "${RESULT#* }" '.error // "saved"'); engine ${LOADED_BEFORE} → ${LOADED:-?} loaded, ${NFAILED:-?} failed"
echo ""

echo "→ Step 3: Replay: the self-test fires..."
replay present
echo ""

echo "→ Step 4: Restart suricata-live holding the rules lock (≤ 15 min)..."
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S')
if restart_live_locked && ACTIVATED=$(engine_started_since "$STARTED" 90); then
    check "restart" 0 "engine started at $ACTIVATED"
else
    check "restart" 1 "no 'Engine started' in $SURICATA_LOG since $STARTED UTC"
fi
if sudo docker exec "$LIVE" grep -q "$OWNER_FILE" /etc/suricata/suricata.yaml; then rc=0; else rc=1; fi
check "rule files" "$rc" "suricata.yaml lists $OWNER_FILE"
read -r LOADED NFAILED <<<"$(engine_stats)"
if [ "$(owner_count)" = 1 ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
check "after the restart" "$rc" "$(owner_count) own rule in the file, ${LOADED:-?} loaded, ${NFAILED:-?} failed"
echo ""

echo "→ Step 5: Clear the rules..."
RESULT=$(save_rules "")
read -r CLEARED NFAILED <<<"$(engine_stats)"
if [ "${RESULT%% *}" = 200 ]; then SAVED=0; fi
# One rule fewer proves the restarted engine had loaded the self-test rule
if [ "${RESULT%% *}" = 200 ] && [ "$(owner_count)" = 0 ] && [ "${NFAILED:-x}" = 0 ] &&
    one_more "$LOADED" "$CLEARED"; then rc=0; else rc=1; fi
check "clear" "$rc" "HTTP ${RESULT%% *} $(json_get "${RESULT#* }" '.error // "saved"'); engine ${LOADED:-?} → ${CLEARED:-?} loaded, ${NFAILED:-?} failed"
echo ""

echo "→ Step 6: Replay: the self-test no longer fires..."
replay absent
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Own rules checked: save, fire, restart, clear ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
exit "$FAILED"
