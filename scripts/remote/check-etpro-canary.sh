#!/usr/bin/env bash
# ET Pro credential checks on the device (NET-191 slice 2, plan step 5). Run after deploy-detection-slice2.sh.
#
# Two made-up ET Pro codes (canary A, then canary B) are written straight to /etc/nettap/suricata.env,
# skipping the Settings preflight, and suricata-live is restarted with each (holding the rules lock):
# the startup update must fail (Proofpoint refuses the code), the previous rules must stay loaded and the
# status record must say it failed. Then the code is cleared and suricata-live restarted on the free sources.
# After each stage both canaries are searched for where a code must never be: the docker logs of
# suricata-live and the daemon, /run/nettap-rules, suricata-live's /tmp, /etc/suricata and /var/log/suricata,
# and every daemon API answer read here. After the clear, also /etc/nettap and /var/lib/suricata/update
# (where the code lives while it is saved). All must be empty. The canaries are never printed.
#
# Suricata restarts three times (a few minutes without IDS each). Refuses to run if a real code is saved.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/check-etpro-canary.sh
set -u

REPO_DIR="/home/nettap/NetTap"
ENV_FILE="/etc/nettap/suricata.env"
WORK="$HOME/nettap-replay/etpro-canary-$(date -u +%Y%m%dT%H%M%SZ)"
# shellcheck source=scripts/remote/rules-checks.sh
. "$REPO_DIR/scripts/remote/rules-checks.sh"
# shellcheck source=scripts/remote/rules-lock.sh
. "$REPO_DIR/scripts/remote/rules-lock.sh"
trap rules_lock_release EXIT
mkdir -p "$WORK" || exit 1
RESPONSES="$WORK/api-responses.txt"
: > "$RESPONSES"

canary() { printf 'NetTapCanary%s%s' "$1" "$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)"; }
CANARY_A=$(canary A)
CANARY_B=$(canary B)

save_code() {  # save_code <code>: as root inside the daemon (it mounts /etc/nettap rw), 600, renamed into place
    # shellcheck disable=SC2016
    printf 'SURICATA_ETPRO_CODE=%s\n' "$1" | sudo docker exec -i "$DAEMON" sh -c \
        'umask 077 && cat > "$0.tmp" && mv -f "$0.tmp" "$0"' "$ENV_FILE"
}

restart_and_wait() {  # restart_and_wait <label>: restart holding the lock, wait for the engine
    local started
    started=$(date -u '+%Y-%m-%d %H:%M:%S')
    if ! restart_live_locked; then
        check "$1 restart" 1 "suricata-live was not restarted"
        return 1
    fi
    if ACTIVATED=$(engine_started_since "$started" 90); then
        check "$1 restart" 0 "engine started at $ACTIVATED"
    else
        check "$1 restart" 1 "no 'Engine started' since $started UTC"
        return 1
    fi
}

api_saved() {  # api_saved <path>: the body, also kept in $RESPONSES for the search at the end
    local out
    out=$(api GET "$1")
    printf '%s\n' "$out" >> "$RESPONSES"
    printf '%s' "${out#* }"
}

expect_rejected() {  # expect_rejected <label>
    local got state commercial
    got=$(enabled_sources)
    if [[ ",$got," == *",et/pro,"* ]] && [[ ",$got," != *",et/open,"* ]]; then rc=0; else rc=1; fi
    check "$1 sources" "$rc" "${got:-none} (want et/pro in place of et/open)"
    state=$(status_field state)
    if [ "$state" = failed ]; then rc=0; else rc=1; fi
    check "$1 update refused" "$rc" "status ${state:-none}: $(status_field reason)"
    read -r LOADED NFAILED <<<"$(engine_stats)"
    if [ "$(rules_sha)" = "$SHA_BEFORE" ] && [ "${LOADED:-0}" = "$LOADED_BEFORE" ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
    check "$1 previous rules kept" "$rc" "rules file $(rules_sha) (before $SHA_BEFORE), ${LOADED:-?} loaded (before $LOADED_BEFORE), ${NFAILED:-?} failed"
    commercial=$(api_saved /api/suricata/rules/commercial)
    if [ "$(json_get "$commercial" '"\(.configured) \(.active) \(.last_update_ok)"')" = "true false false" ]; then rc=0; else rc=1; fi
    check "$1 Settings status" "$rc" "$(json_get "$commercial" '"configured \(.configured), active \(.active), last update ok \(.last_update_ok)"')"
    api_saved /api/suricata/rules/live >/dev/null
}

echo "=== ET Pro credential checks (canary codes) ==="
echo ""

found() {  # found <label> <count or "?">
    case "${2:-?}" in
        0) check "$1" 0 "no canary" ;;
        "?") check "$1" 1 "the search itself failed" ;;
        *) check "$1" 1 "$2 match(es)" ;;
    esac
}
count_files() {  # count_files <container> <dir>...: files holding either canary, "?" when the search failed
    local out
    # -D skip: a FIFO or socket under /tmp must not block the search
    out=$(sudo docker exec "$1" grep -rlF -D skip -e "$CANARY_A" -e "$CANARY_B" "${@:2}" 2>/dev/null)
    case $? in
        0) printf '%s\n' "$out" | wc -l | tr -d ' ' ;;
        1) echo 0 ;;
        *) echo "?" ;;
    esac
}
count_logs() {  # count_logs <container>: log lines holding either canary, "?" when docker logs failed
    local out
    out=$(sudo docker logs "$1" 2>&1) || { echo "?"; return; }
    grep -cF -e "$CANARY_A" -e "$CANARY_B" <<<"$out"
}
search_canaries() {  # search_canaries <stage>: where a code must never be, at any stage
    found "$1: docker logs suricata-live" "$(count_logs "$LIVE")"
    found "$1: docker logs daemon" "$(count_logs "$DAEMON")"
    found "$1: suricata-live /run/nettap-rules, /tmp, /etc/suricata, /var/log/suricata" \
        "$(count_files "$LIVE" /run/nettap-rules /tmp /etc/suricata /var/log/suricata)"
    found "$1: daemon API answers ($(wc -l < "$RESPONSES") read)" "$(grep -cF -e "$CANARY_A" -e "$CANARY_B" "$RESPONSES")"
}

echo "→ Step 1: Preflight..."
# OLD CODE START — review round 2: a stopped daemon container looked like "no code saved"
# if sudo docker exec "$DAEMON" test -e "$ENV_FILE"; then
# OLD CODE END
if ! sudo docker exec "$DAEMON" test ! -e "$ENV_FILE"; then
    echo "   ✗ An ET Pro code is saved ($ENV_FILE), or the daemon container isn't running. Remove the code in Settings first; this check would replace it."
    exit 3
fi
preflight_clean "work dir $WORK"
echo ""

echo "→ Step 2: Canary A..."
save_code "$CANARY_A"
if sudo docker exec "$DAEMON" test -s "$ENV_FILE"; then rc=0; else rc=1; fi
check "canary A saved" "$rc" "$ENV_FILE ($(sudo docker exec "$DAEMON" stat -c '%a %U' "$ENV_FILE" 2>/dev/null))"
restart_and_wait "canary A" && expect_rejected "canary A"
search_canaries "canary A"
echo ""

echo "→ Step 3: Rotate to canary B..."
save_code "$CANARY_B"
restart_and_wait "canary B" && expect_rejected "canary B"
search_canaries "canary B"
echo ""

echo "→ Step 4: Clear the code..."
sudo docker exec "$DAEMON" rm -f "$ENV_FILE"
# OLD CODE START — review round 2: passed when the daemon container was down (docker exec failed)
# if sudo docker exec "$DAEMON" test -e "$ENV_FILE"; then rc=1; else rc=0; fi
# OLD CODE END
sudo docker exec "$DAEMON" test ! -e "$ENV_FILE"
rc=$?
check "code cleared" "$rc" "$ENV_FILE removed (the daemon container must be running to check)"
if restart_and_wait "cleared"; then
    GOT=$(enabled_sources)
    if [ "$GOT" = "$FREE_SOURCES" ]; then rc=0; else rc=1; fi
    check "cleared sources" "$rc" "${GOT:-none} (want $FREE_SOURCES)"
    STATE=$(status_field state)
    if [[ "$STATE" =~ ^(active|prepared)$ ]]; then rc=0; else rc=1; fi
    check "cleared update" "$rc" "status ${STATE:-none} $(status_field reason)"
    read -r LOADED NFAILED <<<"$(engine_stats)"
    if [ "${LOADED:-0}" -gt 0 ] && [ "${NFAILED:-x}" = 0 ]; then rc=0; else rc=1; fi
    check "cleared engine" "$rc" "${LOADED:-?} loaded, ${NFAILED:-?} failed"
    COMMERCIAL=$(api_saved /api/suricata/rules/commercial)
    if [ "$(json_get "$COMMERCIAL" '.configured')" = false ]; then rc=0; else rc=1; fi
    check "cleared Settings status" "$rc" "configured $(json_get "$COMMERCIAL" '.configured')"
    api_saved /api/suricata/rules/live >/dev/null
fi
echo ""

echo "→ Step 5: Search for the canaries after the clear (counts only)..."
# OLD CODE START — review round 2: searched once, after the clear; a failed search counted as "no canary"
# found() {  # found <label> <count>
#     if [ "${2:-x}" = 0 ]; then check "$1" 0 "no canary"; else check "$1" 1 "${2:-?} match(es)"; fi
# }
# count_files() {  # count_files <container> <dir>: files under dir holding either canary
#     sudo docker exec "$1" grep -rlF -e "$CANARY_A" -e "$CANARY_B" "$2" 2>/dev/null | wc -l
# }
# found "/etc/nettap" "$(count_files "$DAEMON" /etc/nettap)"
# found "suricata-live /var/lib/suricata/update" "$(count_files "$LIVE" /var/lib/suricata/update)"
# found "suricata-live /run/nettap-rules" "$(count_files "$LIVE" /run/nettap-rules)"
# found "docker logs suricata-live" "$(sudo docker logs "$LIVE" 2>&1 | grep -cF -e "$CANARY_A" -e "$CANARY_B")"
# found "docker logs daemon" "$(sudo docker logs "$DAEMON" 2>&1 | grep -cF -e "$CANARY_A" -e "$CANARY_B")"
# found "daemon API answers ($(wc -l < "$RESPONSES") read)" "$(grep -cF -e "$CANARY_A" -e "$CANARY_B" "$RESPONSES")"
# OLD CODE END
search_canaries "cleared"
found "cleared: /etc/nettap" "$(count_files "$DAEMON" /etc/nettap)"
found "cleared: suricata-live /var/lib/suricata/update" "$(count_files "$LIVE" /var/lib/suricata/update)"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== ET Pro credential checks passed ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
