#!/usr/bin/env bash
# shellcheck disable=SC2015  # "a && b || log": the log is meant to run when any step fails
# NetTap Suricata rule updates (NET-191 slice 2). Mounted at /usr/local/bin/nettap-rules-update.sh in
# suricata-live. Plan: .codex-review/2026-11-06-detection-accuracy/PLAN.md, slice 2 step 3a.
#
#   nettap-rules-update.sh start     root, from the compose entrypoint wrapper, before Malcolm's entrypoint:
#                                    takes the state volume, wipes the enabled sources, records the sources
#                                    this container runs with, installs the shim. Always exits 0.
#   nettap-rules-update.sh [update]  as Malcolm's user. The startup update, the nightly cron and "Update now"
#                                    all call /usr/local/bin/suricata-update-rules.sh, which is the shim.
#
# An update runs inside one flock on $STATE/rules.lock (the daemon and the deploy scripts take the same lock
# before they reload or restart Suricata): recover an interrupted attempt, run Malcolm's updater, wait until
# the engine has loaded the result with 0 failed rules, keep it as the last good generation, and write
# update-status.json. Every rollback restores the files and then has the engine reload and confirm them;
# the in-progress marker stays until that is confirmed. Nothing printed or recorded carries an ET Pro code.
set -u

STATE="${NETTAP_RULES_STATE:-/run/nettap-rules}"
RULES="${SURICATA_MANAGED_RULES_DIR:-/var/lib/suricata/rules}"
ORIGINAL="${NETTAP_UPDATE_SCRIPT:-/usr/local/bin/suricata-update-rules.sh}"
MALCOLM="${NETTAP_MALCOLM_UPDATE:-/usr/local/bin/malcolm-suricata-update-rules.sh}"
SELF="${NETTAP_RULES_SELF:-/usr/local/bin/nettap-rules-update.sh}"
SOURCES_DIR="${SURICATA_UPDATE_SOURCES_DIR:-/var/lib/suricata/update/sources}"
SOURCES_FILE="${NETTAP_RULES_SOURCES_FILE:-/var/lib/suricata/update/nettap-enable-sources}"
SOCKET="${NETTAP_SURICATA_SOCKET:-${SURICATA_RUN_DIR:-/var/run/suricata}/suricata-command.socket}"
LOCK_WAIT="${NETTAP_RULES_LOCK_WAIT:-900}"
RELOAD_WAIT="${NETTAP_RULES_RELOAD_WAIT:-300}"
RETRY_S="${NETTAP_RULES_RETRY_S:-5}"
UPDATE_MAX="${NETTAP_RULES_UPDATE_MAX:-900}"  # Malcolm's updater is stopped after this, so it can't hold the lock
SHIM_MARK="nettap-rules-update shim"
MARKER="$STATE/update-in-progress"
STATUS="$STATE/update-status.json"

log() { echo "nettap-rules: $*" >&2; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# --- start (root) ----------------------------------------------------------------------------------

install_shim() {
    if [ ! -f "$MALCOLM" ]; then
        if [ -f "$ORIGINAL" ] && ! grep -q "$SHIM_MARK" "$ORIGINAL"; then
            cp -p "$ORIGINAL" "$MALCOLM" || { log "ERROR: could not keep a copy of $ORIGINAL"; return; }
        else
            log "ERROR: Malcolm's $ORIGINAL is missing; rule updates run without NetTap's lock and status record"
            return
        fi
    fi
    printf '#!/bin/bash\n# %s (NET-191): every rule update goes through NetTap'"'"'s lock and status record\nexec /bin/bash %s update "$@"\n' \
        "$SHIM_MARK" "$SELF" > "$ORIGINAL.nettap-tmp" &&
        chmod 755 "$ORIGINAL.nettap-tmp" && mv -f "$ORIGINAL.nettap-tmp" "$ORIGINAL" ||
        log "ERROR: could not install the shim at $ORIGINAL"
}

start() {
    local owner="${PUID:-1000}:${PGID:-1000}"
    # Root here acts in directories Malcolm's user owns (PUSER_CHOWN), so nothing below follows a link that user
    # may have left: links are removed (no suricata-uid process runs during start), files are created O_EXCL
    # (set -C) and chowned with -h. chown -R does not follow links.
    # OLD CODE START — deep-review 2026-11-07: touch, ">" and chown follow a planted symlink as root
    # { mkdir -p "$STATE" && touch "$STATE/rules.lock" && chown -R "$owner" "$STATE"; } ||
    #     log "ERROR: could not prepare $STATE"
    # OLD CODE END
    { mkdir -p "$STATE" && { [ ! -L "$STATE/rules.lock" ] || rm -f "$STATE/rules.lock"; } &&
        { [ -e "$STATE/rules.lock" ] || (set -C && : > "$STATE/rules.lock"); } && chown -R "$owner" "$STATE"; } ||
        log "ERROR: could not prepare $STATE"
    # Each start enables exactly SURICATA_UPDATE_ENABLE_SOURCES: suricata-update only ever adds sources,
    # and its stored configs (a removed ET Pro code among them) would otherwise survive a restart.
    # OLD CODE START — deep-review 2026-11-07: followed a symlinked sources dir
    # rm -f "$SOURCES_DIR"/*.yaml
    # OLD CODE END
    # A parent replaced by a link (the user owns /var/lib/suricata) would point the wipe and the write below
    # anywhere, so both are skipped unless every parent is a real directory.
    local dir
    for dir in "$(dirname "$SOURCES_DIR")" "$(dirname "$SOURCES_FILE")"; do
        mkdir -p "$dir" 2>/dev/null
        if [ "$(cd -P "$dir" 2>/dev/null && pwd)" != "$dir" ]; then
            log "ERROR: $dir is a link or missing; not touching the rule sources (rule updates use the compose list)"
            install_shim
            return 0
        fi
    done
    if [ -L "$SOURCES_DIR" ]; then rm -f "$SOURCES_DIR"; else rm -f "$SOURCES_DIR"/*.yaml; fi
    # docker exec ("Update now") gets the compose environment, not the one the loader built at start
    # OLD CODE START — deep-review 2026-11-07: a fixed .tmp name written with ">" and chowned without -h
    # mkdir -p "$(dirname "$SOURCES_FILE")" &&
    #     (umask 077 && printf '%s\n' "${SURICATA_UPDATE_ENABLE_SOURCES:-}" > "$SOURCES_FILE.tmp") &&
    #     chown "$owner" "$SOURCES_FILE.tmp" && mv -f "$SOURCES_FILE.tmp" "$SOURCES_FILE" ||
    #     log "ERROR: could not record the enabled sources in $SOURCES_FILE"
    # OLD CODE END
    mkdir -p "$(dirname "$SOURCES_FILE")" && rm -f "$SOURCES_FILE.tmp" &&
        (umask 077 && set -C && printf '%s\n' "${SURICATA_UPDATE_ENABLE_SOURCES:-}" > "$SOURCES_FILE.tmp") &&
        chown -h "$owner" "$SOURCES_FILE.tmp" && mv -f "$SOURCES_FILE.tmp" "$SOURCES_FILE" ||
        log "ERROR: could not record the enabled sources in $SOURCES_FILE"
    install_shim
    return 0
}

# --- redaction -------------------------------------------------------------------------------------

REDACT=(-e 's#(emergingthreatspro\.com/)[^/[:space:]]+#\1<code>#g' -e 's#(secret-code=)[^[:space:]|,]+#\1<code>#g')
set_redaction() {  # also replace the code itself wherever it appears
    local code
    case "${SURICATA_UPDATE_ENABLE_SOURCES:-}" in
        *secret-code=*)
            code="${SURICATA_UPDATE_ENABLE_SOURCES#*secret-code=}"
            code="${code%%[,|]*}"
            [[ "$code" =~ ^[A-Za-z0-9]+$ ]] && REDACT+=(-e "s#$code#<code>#g")
            ;;
    esac
}
redact() { sed -E "${REDACT[@]}"; }

# --- engine ----------------------------------------------------------------------------------------

sc() { suricatasc "$SOCKET" -c "$1" 2>&1; }
# $1 = JSON answer, $2 = field of the (first) engine in .message
engine_field() { jq -er "(.message | if type == \"array\" then .[0] else . end).$2 // empty" <<<"$1" 2>/dev/null; }
# The engine's last reload (or start) time; fails when Suricata doesn't answer (not running yet)
engine_time() { local out; out=$(sc ruleset-reload-time) || return 1; engine_field "$out" last_reload; }

confirm_engine() {  # $1 = reload time before, $2 = seconds to wait [$3 = why, if it didn't move]: the time moved and 0 rules failed
    local deadline=$(($(date +%s) + $2)) t out failed
    while :; do
        t=$(engine_time) || t=""
        if [ -n "$t" ] && [ "$t" != "$1" ]; then
            out=$(sc ruleset-stats) || out=""
            failed=$(engine_field "$out" rules_failed) || failed=""
            if [ "$failed" = 0 ]; then
                CONFIRMED="$t"
                return 0
            fi
            REASON="Suricata loaded the rules with ${failed:-an unknown number of} failed rule(s)"
            return 1
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
            REASON="${3:-Suricata did not confirm the new rules within $2 s}"
            return 1
        fi
        sleep "$RETRY_S"
    done
}

reload_blocking() {  # reload what is on disk now, waiting out a reload in progress (Malcolm's nonblocking one)
    local deadline=$(($(date +%s) + RELOAD_WAIT)) before out
    while :; do
        before=$(engine_time) || before=""
        out=$(sc reload-rules) || true
        if jq -e '.return == "OK"' >/dev/null 2>&1 <<<"$out"; then
            confirm_engine "$before" 0 "Suricata's reload of the restored rules did not take effect"
            return $?  # a bare return in the TERM trap would return the status from before the trap (143)
        fi
        case "$out" in
            *"in progress"*) ;;
            *)
                REASON="Suricata refused the reload: $(printf '%s' "$out" | redact | tr '\n' ' ' | cut -c1-200)"
                return 1
                ;;
        esac
        if [ "$(date +%s)" -ge "$deadline" ]; then
            REASON="a rule reload was still in progress after $RELOAD_WAIT s"
            return 1
        fi
        sleep "$RETRY_S"
    done
}

# --- last good generations -------------------------------------------------------------------------

manifest() { (cd "$1" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum); }

publish() {  # copy the rules dir to a new verified generation, then repoint last-good at it atomically
    local name tmp prev
    name="gen-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    tmp="$STATE/gen.tmp-${name#gen-}"
    prev=$(readlink "$STATE/last-good" 2>/dev/null) || prev=""
    if ! { mkdir "$tmp" && cp -R --preserve=mode,timestamps "$RULES/." "$tmp/"; }; then
        rm -rf "$tmp"
        NOTE="the last good copy was not refreshed (copy failed)"
        return 1
    fi
    if [ "$(manifest "$tmp")" != "$(manifest "$RULES")" ]; then
        rm -rf "$tmp"
        NOTE="the last good copy was not refreshed (copy did not match)"
        return 1
    fi
    if ! { mv "$tmp" "$STATE/$name" && ln -sfn "$name" "$STATE/last-good.new" && mv -T "$STATE/last-good.new" "$STATE/last-good"; }; then
        rm -rf "$tmp" "$STATE/last-good.new"
        NOTE="the last good copy was not refreshed (publish failed)"
        return 1
    fi
    local gen
    for gen in "$STATE"/gen-*; do  # keep this generation and the one before
        case "${gen##*/}" in "$name" | "$prev") ;; *) rm -rf "$gen" ;; esac
    done
}

restore() {  # rules dir := the published generation. 0 restored, 2 already equal, 3 nothing to restore, 1 failed
    local src
    # OLD CODE START — review round 2: no last good copy failed every rollback, so the marker stayed and every
    # later run stopped at "recovering" (a fresh volume whose first update failed never updated again)
    # if [ ! -L "$STATE/last-good" ]; then
    #     REASON="no last good ruleset to restore"
    #     return 1
    # fi
    # src="$STATE/$(readlink "$STATE/last-good")"
    # OLD CODE END
    src="$STATE/$(readlink "$STATE/last-good" 2>/dev/null)"
    # A missing, dangling or empty generation must never empty the live rules
    if [ ! -L "$STATE/last-good" ] || [ ! -s "$src/suricata.rules" ]; then
        log "no last good rules were kept; nothing to restore"
        return 3
    fi
    [ "$(manifest "$src")" = "$(manifest "$RULES")" ] && return 2
    if find "$RULES" -mindepth 1 -delete && cp -R --preserve=mode,timestamps "$src/." "$RULES/" &&
        [ "$(manifest "$src")" = "$(manifest "$RULES")" ]; then
        return 0
    fi
    REASON="restoring the last good rules failed"
    return 1
}

rollback() {  # $1 = always: reload even when the files already were the last good ones. Sets ROLLED.
    local rc
    restore
    rc=$?
    [ "$rc" -eq 1 ] && return 1
    ROLLED="the last good rules were restored"
    if [ "$rc" -eq 3 ]; then  # nothing known good to go back to: leave the engine and the files as they are
        ROLLED="no last good rules were kept to restore"
        return 0
    fi
    # No answer from the engine = it isn't running (startup): it loads the restored files when it starts
    engine_time >/dev/null || return 0
    if [ "$rc" -eq 0 ] || [ "$1" = always ]; then
        reload_blocking || { REASON="${REASON}; engine not confirmed"; return 1; }
    fi
    return 0
}

# --- status ----------------------------------------------------------------------------------------

write_status() {  # state exit_code reason
    local success activation
    success=$(jq -r '.last_success // empty' "$STATUS" 2>/dev/null) || success=""
    activation=$(jq -r '.last_activation // empty' "$STATUS" 2>/dev/null) || activation=""
    case "$1" in active | prepared) success="$T0" ;; esac
    [ -n "${CONFIRMED:-}" ] && [ "$1" = active ] && activation="$CONFIRMED"
    jq -n --arg attempt "$T0" --argjson code "$2" --arg state "$1" --arg reason "$3" \
        --arg success "$success" --arg activation "$activation" --arg missing "${MISSING:-}" \
        '{attempt: $attempt, exit_code: $code, state: $state, reason: $reason,
          last_success: (if $success == "" then null else $success end),
          last_activation: (if $activation == "" then null else $activation end),
          missing_sources: ($missing | split("\n") | map(select(. != "")))}' \
        > "$STATUS.tmp" && mv -f "$STATUS.tmp" "$STATUS" || log "could not write $STATUS"
}

missing_sources() {  # configured sources with no source file: Malcolm only warns when one fails to enable
    local have name
    have=$(cat "$SOURCES_DIR"/*.yaml 2>/dev/null | sed -n 's/^source: *//p')
    tr ',' '\n' <<<"${SURICATA_UPDATE_ENABLE_SOURCES:-}" | while IFS= read -r name; do
        name="${name%%|*}"
        name="${name//[[:space:]]/}"
        [ -n "$name" ] && ! grep -qxF "$name" <<<"$have" && printf '%s\n' "$name"
    done
}

# The line that says why: suricata-update's last error, else the last line, without its timestamp
failure_reason() {
    local line
    line=$(grep -E '<(Error|Critical)>|ERROR|[Ee]rror' <<<"$1" | tail -1)
    [ -n "$line" ] || line=$(grep -v '^[[:space:]]*$' <<<"$1" | tail -1)
    # OLD CODE START — review round 2: feed text kept its control characters (printed raw over SSH, logged)
    # sed -E 's/^[0-9/]+ -- [0-9:]+ - <[A-Za-z]+> -- //' <<<"$line" | cut -c1-300
    # OLD CODE END
    sed -E 's/^[0-9/]+ -- [0-9:]+ - <[A-Za-z]+> -- //' <<<"$line" | tr -d '\000-\010\013-\037\177' | cut -c1-300
}

# --- update ----------------------------------------------------------------------------------------

output_done() {  # close the redactor's input and wait until it has written everything
    [ -n "${REDACTOR:-}" ] || return 0
    exec 8>&-
    wait "$REDACTOR" 2>/dev/null
    REDACTOR=""
}

on_signal() {
    trap '' TERM INT
    if [ -n "${CHILD:-}" ]; then
        kill -TERM -- "-$CHILD" 2>/dev/null
        (exec 8>&-; sleep 5 && kill -KILL -- "-$CHILD" 2>/dev/null) &  # without the redactor's pipe
        local killer=$!
        wait "$CHILD" 2>/dev/null
        kill "$killer" 2>/dev/null
    fi
    # OLD CODE START — review round 2: $OUT now holds redacted text only
    # [ -n "${OUT:-}" ] && [ -f "$OUT" ] && { redact < "$OUT"; rm -f "$OUT"; }
    # OLD CODE END
    if [ -n "${OUT:-}" ] && [ -f "$OUT" ]; then
        output_done
        cat "$OUT"
        rm -f "$OUT"
    fi
    if rollback always; then
        rm -f "$MARKER"
        write_status interrupted 143 "The update was stopped before it finished; $ROLLED"
    else
        write_status interrupted 143 "The update was stopped before it finished; ${REASON} (retried at the next update)"
    fi
    exit 143
}

update() {
    # Root would write the marker, the status and the rules through links Malcolm's user can plant
    if [ "$(id -u)" -eq 0 ]; then
        log "refusing to update the rules as root; run it as Malcolm's user: docker exec -u suricata <container> $ORIGINAL"
        exit 1
    fi
    [ "${SURICATA_UPDATE_RULES:-false}" = true ] || exec "$MALCOLM"  # Malcolm's: does nothing, exits 0
    if [ -r "$SOURCES_FILE" ]; then
        SURICATA_UPDATE_ENABLE_SOURCES=$(cat "$SOURCES_FILE")
        export SURICATA_UPDATE_ENABLE_SOURCES
    fi
    set_redaction
    # Read-only: the daemon (root) may have created the lock file; flock works on any open file
    if ! { [ -d "$STATE" ] && { [ -e "$STATE/rules.lock" ] || : > "$STATE/rules.lock"; } && exec 9< "$STATE/rules.lock"; }; then
        log "no $STATE; running Malcolm's updater without NetTap's lock and status record"
        "$MALCOLM" 2>&1 | redact
        exit "${PIPESTATUS[0]}"
    fi
    if ! flock -w "$LOCK_WAIT" 9; then
        log "another rule operation held the lock for $LOCK_WAIT s; not updating"
        exit 1
    fi
    T0=$(now)
    REASON=""
    NOTE=""
    CONFIRMED=""
    MISSING=""
    ROLLED=""
    rm -rf "$STATE"/gen.tmp-*

    if [ -e "$MARKER" ]; then
        log "a previous update did not finish; restoring the last good rules first"
        if ! rollback always; then
            write_status failed 1 "Recovering an unfinished update: $REASON"
            exit 1
        fi
        rm -f "$MARKER"
    fi
    if [ ! -L "$STATE/last-good" ] && [ -f "$RULES/suricata.rules" ]; then
        publish || log "could not keep the running rules as the last good ones: $NOTE"
    fi

    BEFORE=$(engine_time) || BEFORE=""
    echo "$T0" > "$MARKER"
    trap on_signal TERM INT
    OUT=$(mktemp)
    # Redacted before it reaches the disk: a run killed with SIGKILL leaves no code in $OUT
    exec 8> >(redact > "$OUT")
    REDACTOR=$!
    # Own session, so a stop takes Malcolm's updater and suricata-update down with it. A time limit, so a
    # stalled download can't hold the rules lock (capture restarts, the ET Pro code, deploys wait on it).
    # Malcolm's script exits non-zero if its grep -v sees no line; its "enable-conf does not exist"
    # warnings always give it one on 26.10.0.
    # OLD CODE START — review round 2: no time limit, and the raw output went to $OUT
    # setsid "$MALCOLM" > "$OUT" 2>&1 &
    # OLD CODE END
    setsid timeout -k 30 "$UPDATE_MAX" "$MALCOLM" >&8 2>&1 &
    CHILD=$!
    wait "$CHILD"
    RC=$?
    CHILD=""
    # OLD CODE START — review round 2: redacted only after the raw output was on disk
    # LOGTEXT=$(redact < "$OUT")
    # OLD CODE END
    output_done
    LOGTEXT=$(cat "$OUT")
    rm -f "$OUT"
    OUT=""
    [ -n "$LOGTEXT" ] && printf '%s\n' "$LOGTEXT"

    if [ "$RC" -ne 0 ]; then
        local why
        why=$(failure_reason "$LOGTEXT")
        [ "$RC" -eq 124 ] && why="the rule update did not finish within $UPDATE_MAX s and was stopped"
        [ -n "$why" ] || why="the rule update exited $RC"
        if rollback no; then
            rm -f "$MARKER"
            write_status failed "$RC" "$why"
        else
            write_status failed "$RC" "$why; $REASON (retried at the next update)"
        fi
        exit "$RC"
    fi
    MISSING=$(missing_sources)
    [ -z "$MISSING" ] || log "these configured rule sources were not enabled: $(paste -sd, - <<<"$MISSING")"
    if [ -z "$BEFORE" ]; then
        # Startup: Suricata starts after this and loads what suricata-update tested (-T) and installed
        publish || true
        rm -f "$MARKER"
        write_status prepared 0 "$NOTE"
        exit 0
    fi
    if confirm_engine "$BEFORE" "$RELOAD_WAIT"; then
        publish || true
        rm -f "$MARKER"
        write_status active 0 "$NOTE"
        exit 0
    fi
    local why="$REASON"
    if rollback always; then
        rm -f "$MARKER"
        write_status failed 1 "$why; $ROLLED"
    else
        write_status failed 1 "$why; $REASON (retried at the next update)"
    fi
    exit 1
}

case "${1:-update}" in
    start) start ;;
    update) update ;;
    *) log "usage: $0 [start|update]"; exit 2 ;;
esac
