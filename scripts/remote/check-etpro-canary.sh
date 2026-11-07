#!/usr/bin/env bash
# ET Pro credential checks on the device (NET-191 slice 2, plan step 5). Run after deploy-detection-slice2.sh.
#
# Two made-up ET Pro codes (canary A, then canary B) are written straight to /etc/nettap/suricata.env,
# skipping the Settings preflight, and suricata-live is restarted with each (holding the rules lock):
# the startup update must fail (Proofpoint refuses the code), the previous rules must stay loaded and the
# status record must say it failed. Then the code is cleared and suricata-live restarted on the free sources.
# Finally both canaries are searched for in /etc/nettap, the container's /var/lib/suricata/update and
# /run/nettap-rules, the docker logs of suricata-live and the daemon, and every daemon API answer read here:
# all must be empty. The canaries are never printed.
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

echo "→ Step 1: Preflight..."
if sudo docker exec "$DAEMON" test -e "$ENV_FILE"; then
    echo "   ✗ An ET Pro code is saved ($ENV_FILE). Remove it in Settings first; this check would replace it."
    exit 3
fi
preflight_clean "work dir $WORK"
echo ""

echo "→ Step 2: Canary A..."
save_code "$CANARY_A"
if sudo docker exec "$DAEMON" test -s "$ENV_FILE"; then rc=0; else rc=1; fi
check "canary A saved" "$rc" "$ENV_FILE ($(sudo docker exec "$DAEMON" stat -c '%a %U' "$ENV_FILE" 2>/dev/null))"
restart_and_wait "canary A" && expect_rejected "canary A"
echo ""

echo "→ Step 3: Rotate to canary B..."
save_code "$CANARY_B"
restart_and_wait "canary B" && expect_rejected "canary B"
echo ""

echo "→ Step 4: Clear the code..."
sudo docker exec "$DAEMON" rm -f "$ENV_FILE"
if sudo docker exec "$DAEMON" test -e "$ENV_FILE"; then rc=1; else rc=0; fi
check "code cleared" "$rc" "$ENV_FILE removed"
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

echo "→ Step 5: Search for the canaries (counts only)..."
found() {  # found <label> <count>
    if [ "${2:-x}" = 0 ]; then check "$1" 0 "no canary"; else check "$1" 1 "${2:-?} match(es)"; fi
}
count_files() {  # count_files <container> <dir>: files under dir holding either canary
    sudo docker exec "$1" grep -rlF -e "$CANARY_A" -e "$CANARY_B" "$2" 2>/dev/null | wc -l
}
found "/etc/nettap" "$(count_files "$DAEMON" /etc/nettap)"
found "suricata-live /var/lib/suricata/update" "$(count_files "$LIVE" /var/lib/suricata/update)"
found "suricata-live /run/nettap-rules" "$(count_files "$LIVE" /run/nettap-rules)"
found "docker logs suricata-live" "$(sudo docker logs "$LIVE" 2>&1 | grep -cF -e "$CANARY_A" -e "$CANARY_B")"
found "docker logs daemon" "$(sudo docker logs "$DAEMON" 2>&1 | grep -cF -e "$CANARY_A" -e "$CANARY_B")"
found "daemon API answers ($(wc -l < "$RESPONSES") read)" "$(grep -cF -e "$CANARY_A" -e "$CANARY_B" "$RESPONSES")"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== ET Pro credential checks passed ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
