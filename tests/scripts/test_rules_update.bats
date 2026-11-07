#!/usr/bin/env bats
# ==========================================================================
# BATS tests for config/suricata/nettap-rules-update.sh (NET-191 slice 2)
# ==========================================================================
# "start" tests run anywhere. "update" tests need Linux (flock, setsid, jq, GNU coreutils) and skip
# elsewhere; run them in the image they run in on the device, with a copy of Homebrew's bats (Docker
# Desktop doesn't share /opt/homebrew), from the repo root:
#
#   cp -R /opt/homebrew/Cellar/bats-core/1.14.0 /tmp/bats
#   docker run --rm --platform linux/amd64 --user 1000:1000 --tmpfs /tinyfs:size=256k,mode=1777 -e TINYFS=/tinyfs \
#     -v "$PWD:/repo:ro" -v /tmp/bats:/bats:ro --entrypoint /bats/bin/bats \
#     ghcr.io/idaholab/malcolm/suricata:26.10.0 /repo/tests/scripts/test_rules_update.bats
#
# As Malcolm's user (1000): "update" refuses root. Malcolm's updater and suricatasc are stubs driven by
# files in $ENG (see _stubs).

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/config/suricata/nettap-rules-update.sh"

load 'helpers/setup'

_linux_only() {
    command -v flock >/dev/null && command -v setsid >/dev/null && command -v jq >/dev/null &&
        mv --version >/dev/null 2>&1 || skip "needs Linux (flock, setsid, jq, GNU mv); see the header"
}

_env() {
    export RULES_DIR="$TEST_TMPDIR/rules" STATE="${STATE:-$TEST_TMPDIR/state}" ENG="$TEST_TMPDIR/eng"
    mkdir -p "$RULES_DIR" "$STATE" "$ENG" "$TEST_TMPDIR/bin"
    export NETTAP_RULES_STATE="$STATE" SURICATA_MANAGED_RULES_DIR="$RULES_DIR"
    export NETTAP_MALCOLM_UPDATE="$TEST_TMPDIR/bin/malcolm-update" NETTAP_RULES_SOURCES_FILE="$TEST_TMPDIR/sources"
    export NETTAP_SURICATA_SOCKET="$TEST_TMPDIR/socket" SURICATA_UPDATE_RULES=true
    export SURICATA_UPDATE_SOURCES_DIR="$TEST_TMPDIR/sources.d"
    export NETTAP_RULES_LOCK_WAIT=10 NETTAP_RULES_RELOAD_WAIT=2 NETTAP_RULES_RETRY_S=0.2
    export PATH="$TEST_TMPDIR/bin:$PATH"
    echo "T0" > "$ENG/time"
}

_stubs() {
    # Malcolm's updater: optional output, new rules, sleep, its nonblocking reload landing after N
    # more reload-time reads, exit code
    cat > "$TEST_TMPDIR/bin/malcolm-update" <<'EOF'
#!/usr/bin/env bash
echo "malcolm $$ start" >> "$ENG/log"
echo "$$" > "$ENG/malcolm-pid"
[ -f "$ENG/malcolm-print" ] && cat "$ENG/malcolm-print"
IFS=',' read -ra specs <<< "${SURICATA_UPDATE_ENABLE_SOURCES:-}"
for spec in "${specs[@]}"; do  # enable-source: one file per source; a listed one fails to enable
    n="${spec%%|*}"
    grep -qxF "$n" "$ENG/skip-source" 2>/dev/null && continue
    mkdir -p "$SURICATA_UPDATE_SOURCES_DIR" && echo "source: $n" > "$SURICATA_UPDATE_SOURCES_DIR/${n//\//-}.yaml"
done
[ -f "$ENG/new-rules" ] && cp "$ENG/new-rules" "$RULES_DIR/suricata.rules"
[ -f "$ENG/malcolm-sleep" ] && sleep "$(cat "$ENG/malcolm-sleep")"
if [ -f "$ENG/malcolm-reload" ]; then
    read -r after t < "$ENG/malcolm-reload"
    echo "$(( $(cat "$ENG/rt-calls" 2>/dev/null || echo 0) + after )) $t" > "$ENG/time-after"
fi
echo "malcolm $$ end" >> "$ENG/log"
exit "$(cat "$ENG/malcolm-rc" 2>/dev/null || echo 0)"
EOF
    # suricatasc SOCKET -c CMD: down, busy (reload in progress N times), reload-noop, failed count
    cat > "$TEST_TMPDIR/bin/suricatasc" <<'EOF'
#!/usr/bin/env bash
cmd="$3"
echo "sc $cmd" >> "$ENG/log"
[ -f "$ENG/down" ] && { echo "Error: unable to connect to the socket"; exit 1; }
case "$cmd" in
    ruleset-reload-time)
        n=$(( $(cat "$ENG/rt-calls" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$ENG/rt-calls"
        if [ -f "$ENG/time-after" ]; then
            read -r at t < "$ENG/time-after"
            if [ "$n" -ge "$at" ]; then echo "$t" > "$ENG/time"; rm -f "$ENG/time-after"; fi
        fi
        printf '{"message": [{"id": 0, "last_reload": "%s"}], "return": "OK"}\n' "$(cat "$ENG/time")" ;;
    ruleset-stats)
        printf '{"message": [{"id": 0, "rules_loaded": 3, "rules_failed": %s}], "return": "OK"}\n' \
            "$(cat "$ENG/failed" 2>/dev/null || echo 0)" ;;
    reload-rules)
        busy=$(cat "$ENG/busy" 2>/dev/null || echo 0)
        if [ "$busy" -gt 0 ]; then
            echo $((busy - 1)) > "$ENG/busy"
            echo '{"message": "Reload already in progress", "return": "NOK"}'; exit 1
        fi
        [ -f "$ENG/reload-noop" ] || echo "reloaded-$RANDOM" > "$ENG/time"
        cp "$RULES_DIR/suricata.rules" "$ENG/engine-loaded"
        rm -f "$ENG/failed"  # the restored rules load cleanly
        echo '{"message": "done", "return": "OK"}' ;;
esac
EOF
    chmod +x "$TEST_TMPDIR/bin/malcolm-update" "$TEST_TMPDIR/bin/suricatasc"
}

_seed() {  # the running ruleset v1, already published as the last good generation
    echo "alert ip any any -> any any (msg:\"v1\"; sid:1;)" > "$RULES_DIR/suricata.rules"
    mkdir -p "$RULES_DIR/datasets" && echo "djE=" > "$RULES_DIR/datasets/abc"
    mkdir -p "$STATE/gen-0" && cp -R "$RULES_DIR/." "$STATE/gen-0/"
    ln -s gen-0 "$STATE/last-good"
    echo "alert ip any any -> any any (msg:\"v2\"; sid:2;)" > "$ENG/new-rules"
}

_update() { run bash "$SCRIPT" update; }
_status() { jq -r ".$1" "$STATE/update-status.json"; }
_rules() { cat "$RULES_DIR/suricata.rules"; }
_good() { cat "$STATE/$(readlink "$STATE/last-good")/suricata.rules"; }

# ---------------------------------------------------------------------------
# start (root, in the entrypoint wrapper)
# ---------------------------------------------------------------------------

_start_env() {
    TEST_TMPDIR=$(cd -P "$TEST_TMPDIR" && pwd)
    export NETTAP_RULES_STATE="$TEST_TMPDIR/state" SURICATA_UPDATE_SOURCES_DIR="$TEST_TMPDIR/sources.d"
    export NETTAP_RULES_SOURCES_FILE="$TEST_TMPDIR/update/nettap-enable-sources"
    export NETTAP_UPDATE_SCRIPT="$TEST_TMPDIR/suricata-update-rules.sh"
    export NETTAP_MALCOLM_UPDATE="$TEST_TMPDIR/malcolm-suricata-update-rules.sh"
    export NETTAP_RULES_SELF="$TEST_TMPDIR/nettap-rules-update.sh"
    export PUID PGID
    PUID=$(id -u)
    PGID=$(id -g)
    mkdir -p "$SURICATA_UPDATE_SOURCES_DIR"
    printf '#!/usr/bin/env bash\necho "malcolm original"\n' > "$NETTAP_UPDATE_SCRIPT"
}

@test "start: wipes the enabled sources, records the container's sources (600), takes the state dir" {
    _start_env
    printf 'source: et/pro\nparams:\n  secret-code: OLDCODE\n' > "$SURICATA_UPDATE_SOURCES_DIR/et-pro.yaml"
    echo "source: et/open" > "$SURICATA_UPDATE_SOURCES_DIR/et-open.yaml"
    SURICATA_UPDATE_ENABLE_SOURCES="et/open,ipfire/dbl" run bash "$SCRIPT" start
    [ "$status" -eq 0 ]
    [ -z "$(ls "$SURICATA_UPDATE_SOURCES_DIR")" ]
    [ "$(cat "$NETTAP_RULES_SOURCES_FILE")" = "et/open,ipfire/dbl" ]
    [[ "$(ls -l "$NETTAP_RULES_SOURCES_FILE")" == -rw-------* ]]
    [ -f "$TEST_TMPDIR/state/rules.lock" ]
}

@test "start: installs the shim, keeps Malcolm's script, and a second start changes nothing" {
    _start_env
    run bash "$SCRIPT" start
    [ "$status" -eq 0 ]
    run bash "$SCRIPT" start
    [ "$status" -eq 0 ]
    grep -q "nettap-rules-update shim" "$NETTAP_UPDATE_SCRIPT"
    [ "$(bash "$NETTAP_MALCOLM_UPDATE")" = "malcolm original" ]
    # the shim runs the update mode
    printf '#!/usr/bin/env bash\necho "nettap $*"\n' > "$NETTAP_RULES_SELF"
    [ "$(bash "$NETTAP_UPDATE_SCRIPT")" = "nettap update" ]
}

@test "start: follows no link Malcolm's user left in its directories (root must not write or chown through it)" {
    _start_env
    mkdir -p "$TEST_TMPDIR/update" "$TEST_TMPDIR/state" "$TEST_TMPDIR/victim/sources"
    echo "keep me" > "$TEST_TMPDIR/victim/file"
    echo "keep me" > "$TEST_TMPDIR/victim/lock"
    echo "keep: me" > "$TEST_TMPDIR/victim/sources/keep.yaml"
    ln -s "$TEST_TMPDIR/victim/file" "$NETTAP_RULES_SOURCES_FILE.tmp"
    ln -s "$TEST_TMPDIR/victim/lock" "$TEST_TMPDIR/state/rules.lock"
    rm -rf "$SURICATA_UPDATE_SOURCES_DIR"
    ln -s "$TEST_TMPDIR/victim/sources" "$SURICATA_UPDATE_SOURCES_DIR"
    SURICATA_UPDATE_ENABLE_SOURCES="et/open" run bash "$SCRIPT" start
    [ "$status" -eq 0 ]
    [ "$(cat "$TEST_TMPDIR/victim/file")" = "keep me" ]
    [ "$(cat "$TEST_TMPDIR/victim/lock")" = "keep me" ]
    [ -f "$TEST_TMPDIR/victim/sources/keep.yaml" ]
    [ ! -L "$TEST_TMPDIR/state/rules.lock" ] && [ -f "$TEST_TMPDIR/state/rules.lock" ]
    [ ! -L "$NETTAP_RULES_SOURCES_FILE" ] && [ "$(cat "$NETTAP_RULES_SOURCES_FILE")" = "et/open" ]
    [ ! -e "$SURICATA_UPDATE_SOURCES_DIR" ]
}

@test "start: a parent dir replaced by a link → no wipe or write through it, the shim still installed" {
    _start_env
    export SURICATA_UPDATE_SOURCES_DIR="$TEST_TMPDIR/update/sources"
    mkdir -p "$TEST_TMPDIR/victim/sources"
    echo "keep: me" > "$TEST_TMPDIR/victim/sources/keep.yaml"
    echo "keep me" > "$TEST_TMPDIR/victim/nettap-enable-sources"
    ln -s "$TEST_TMPDIR/victim" "$TEST_TMPDIR/update"
    SURICATA_UPDATE_ENABLE_SOURCES="et/open" run bash "$SCRIPT" start
    [ "$status" -eq 0 ]
    [[ "$output" == *"ERROR: $TEST_TMPDIR/update is a link or missing"* ]]
    [ -f "$TEST_TMPDIR/victim/sources/keep.yaml" ]
    [ "$(cat "$TEST_TMPDIR/victim/nettap-enable-sources")" = "keep me" ]
    [ ! -e "$TEST_TMPDIR/victim/nettap-enable-sources.tmp" ]
    grep -q "nettap-rules-update shim" "$NETTAP_UPDATE_SCRIPT"
}

@test "start: Malcolm's script missing → says so, installs nothing, still exits 0" {
    _start_env
    rm -f "$NETTAP_UPDATE_SCRIPT"
    run bash "$SCRIPT" start
    [ "$status" -eq 0 ]
    [[ "$output" == *"ERROR: Malcolm's $NETTAP_UPDATE_SCRIPT is missing"* ]]
    [ ! -e "$NETTAP_UPDATE_SCRIPT" ]
    [ ! -e "$NETTAP_MALCOLM_UPDATE" ]
}

# ---------------------------------------------------------------------------
# update: results and status record
# ---------------------------------------------------------------------------

@test "update: success → waits for Malcolm's reload, status active, last good refreshed, previous kept" {
    _linux_only; _env; _stubs; _seed
    echo "1 T1" > "$ENG/malcolm-reload"
    _update
    [ "$status" -eq 0 ]
    [ "$(_status state)" = active ]
    [ "$(_status exit_code)" = 0 ]
    [ "$(_status last_activation)" = T1 ]
    [ "$(_status last_success)" = "$(_status attempt)" ]
    [ "$(jq -c .missing_sources "$STATE/update-status.json")" = "[]" ]
    [[ "$(_good)" == *v2* ]]
    [ -d "$STATE/gen-0" ]
    [ ! -e "$STATE/update-in-progress" ]
    [ "$(grep -c "sc reload-rules" "$ENG/log")" -eq 0 ]
}

@test "update: no engine yet (startup) → prepared, last good refreshed" {
    _linux_only; _env; _stubs; _seed
    touch "$ENG/down"
    _update
    [ "$status" -eq 0 ]
    [ "$(_status state)" = prepared ]
    [ "$(_status last_activation)" = null ]
    [[ "$(_good)" == *v2* ]]
    [ ! -e "$STATE/update-in-progress" ]
}

@test "update: Malcolm's update fails → its error is the reason, last good restored and reloaded" {
    _linux_only; _env; _stubs; _seed
    echo "7/11/2026 -- 00:00:05 - <Error> -- Failed to fetch https://example.invalid/r.tar.gz: HTTP Error 404" > "$ENG/malcolm-print"
    echo 1 > "$ENG/malcolm-rc"
    _update
    [ "$status" -eq 1 ]
    [ "$(_status state)" = failed ]
    [ "$(_status exit_code)" = 1 ]
    [ "$(_status reason)" = "Failed to fetch https://example.invalid/r.tar.gz: HTTP Error 404" ]
    [ "$(_status last_success)" = null ]
    [[ "$(_rules)" == *v1* ]]
    [[ "$(cat "$ENG/engine-loaded")" == *v1* ]]
    [[ "$(_good)" == *v1* ]]
    [ ! -e "$STATE/update-in-progress" ]
}

@test "update: as root → refused before anything runs (root would follow links Malcolm's user can plant)" {
    _env; _stubs; _seed
    printf '#!/usr/bin/env bash\n[ "$1" = -u ] && { echo 0; exit 0; }\nexec /usr/bin/id "$@"\n' > "$TEST_TMPDIR/bin/id"
    chmod +x "$TEST_TMPDIR/bin/id"
    _update
    [ "$status" -eq 1 ]
    [[ "$output" == *"refusing to update the rules as root"*"docker exec -u suricata"* ]]
    [ ! -e "$ENG/log" ]
    [ ! -e "$STATE/update-in-progress" ]
    [ ! -e "$STATE/update-status.json" ]
}

@test "update: a configured source that failed to enable → still active, recorded as missing" {
    _linux_only; _env; _stubs; _seed
    echo "et/open,ipfire/dbl|x=1,echap/stalkerware" > "$NETTAP_RULES_SOURCES_FILE"
    echo "ipfire/dbl" > "$ENG/skip-source"
    echo "1 T1" > "$ENG/malcolm-reload"
    _update
    [ "$status" -eq 0 ]
    [ "$(_status state)" = active ]
    [ "$(jq -c .missing_sources "$STATE/update-status.json")" = '["ipfire/dbl"]' ]
    [[ "$output" == *"these configured rule sources were not enabled: ipfire/dbl"* ]]
}

@test "update: Malcolm's updater past its time limit → stopped, status failed, last good restored" {
    _linux_only; _env; _stubs; _seed
    export NETTAP_RULES_UPDATE_MAX=1
    echo 30 > "$ENG/malcolm-sleep"
    touch "$ENG/down"
    SECONDS=0
    _update
    [ "$status" -eq 124 ]
    [ "$SECONDS" -lt 15 ]
    [ "$(_status state)" = failed ]
    [ "$(_status reason)" = "the rule update did not finish within 1 s and was stopped" ]
    [[ "$(_rules)" == *v1* ]]
    [ "$(grep -c "malcolm .* end" "$ENG/log")" -eq 0 ]
    [ ! -e "$STATE/update-in-progress" ]
}

@test "update: the updater's raw output never reaches the disk, even when the run is killed" {
    _linux_only; _env; _stubs; _seed
    export TMPDIR="$TEST_TMPDIR/tmp"
    mkdir -p "$TMPDIR"
    echo "et/pro|secret-code=CANARYz9y8x7w6v5u4t3,ipfire/dbl" > "$NETTAP_RULES_SOURCES_FILE"
    echo "fetching https://rules.emergingthreatspro.com/CANARYz9y8x7w6v5u4t3/x.tar.gz" > "$ENG/malcolm-print"
    echo 30 > "$ENG/malcolm-sleep"
    touch "$ENG/down"
    bash "$SCRIPT" update > "$TEST_TMPDIR/out" 2>&1 &
    pid=$!
    for _ in $(seq 1 50); do grep -q "malcolm .* start" "$ENG/log" 2>/dev/null && break; sleep 0.1; done
    sleep 0.5
    [ -n "$(ls "$TMPDIR")" ]  # the output file exists
    [ "$(grep -rlF CANARY "$TMPDIR" | wc -l)" -eq 0 ]
    kill -KILL "$pid"
    kill -KILL -- "-$(awk '{ print $5 }' "/proc/$(cat "$ENG/malcolm-pid")/stat")" 2>/dev/null || true  # its group
    sleep 0.5
    [ "$(grep -rlF CANARY "$TMPDIR" | wc -l)" -eq 0 ]
}

@test "update: Malcolm's startup time limit (TERM to the whole group) → the updater's output is still printed" {
    _linux_only; _env; _stubs; _seed
    echo "Fetching https://slow.example/rules.tar.gz" > "$ENG/malcolm-print"
    echo 30 > "$ENG/malcolm-sleep"
    touch "$ENG/down"
    # as docker_entrypoint.sh runs it: timeout without --foreground signals the wrapper's whole group
    run timeout 1 bash "$SCRIPT" update
    [ "$status" -eq 124 ]
    [[ "$output" == *"Fetching https://slow.example/rules.tar.gz"* ]]
    [ "$(_status state)" = interrupted ]
    [[ "$(_rules)" == *v1* ]]
}

@test "update: an ET Pro code never reaches the output or the status record" {
    _linux_only; _env; _stubs; _seed
    echo "et/pro|secret-code=CANARYa1b2c3d4e5f6g7,ipfire/dbl" > "$NETTAP_RULES_SOURCES_FILE"
    cat > "$ENG/malcolm-print" <<'EOF'
enabling et/pro secret-code=CANARYa1b2c3d4e5f6g7
7/11/2026 -- 00:00:05 - <Error> -- Failed to fetch https://rules.emergingthreatspro.com/CANARYa1b2c3d4e5f6g7/suricata-8.0.7/etpro.rules.tar.gz: HTTP Error 403: Forbidden
code CANARYa1b2c3d4e5f6g7 alone
EOF
    echo 1 > "$ENG/malcolm-rc"
    _update
    [ "$status" -eq 1 ]
    [[ "$output" != *CANARY* ]]
    [ "$(grep -c CANARY "$STATE/update-status.json")" -eq 0 ]
    [[ "$output" == *"emergingthreatspro.com/<code>/suricata-8.0.7"* ]]
    [[ "$output" == *"secret-code=<code>"* ]]
    [[ "$output" == *"code <code> alone"* ]]
    [[ "$(_status reason)" == *"emergingthreatspro.com/<code>/"* ]]
}

@test "update: the sources recorded at start replace the exec environment's" {
    _linux_only; _env; _stubs; _seed
    echo "et/open,ipfire/dbl" > "$NETTAP_RULES_SOURCES_FILE"
    printf '#!/usr/bin/env bash\necho "sources=$SURICATA_UPDATE_ENABLE_SOURCES"\n' > "$NETTAP_MALCOLM_UPDATE"
    touch "$ENG/down"
    SURICATA_UPDATE_ENABLE_SOURCES=et/open _update
    [ "$status" -eq 0 ]
    [[ "$output" == *"sources=et/open,ipfire/dbl"* ]]
}

# ---------------------------------------------------------------------------
# update: engine confirmation and rollback
# ---------------------------------------------------------------------------

@test "update: a delayed reload → waits for it and records the new reload time" {
    _linux_only; _env; _stubs; _seed
    export NETTAP_RULES_RELOAD_WAIT=10
    echo "4 T-late" > "$ENG/malcolm-reload"
    _update
    [ "$status" -eq 0 ]
    [ "$(_status state)" = active ]
    [ "$(_status last_activation)" = T-late ]
    [ "$(grep -c 'sc ruleset-reload-time' "$ENG/log")" -ge 5 ]
}

@test "update: Malcolm's reload never lands → status failed, last good restored and confirmed" {
    _linux_only; _env; _stubs; _seed
    export NETTAP_RULES_RELOAD_WAIT=1
    _update
    [ "$status" -eq 1 ]
    [ "$(_status state)" = failed ]
    [[ "$(_status reason)" == "Suricata did not confirm the new rules within 1 s; the last good rules were restored" ]]
    [[ "$(_rules)" == *v1* ]]
    [[ "$(cat "$ENG/engine-loaded")" == *v1* ]]
    [ ! -e "$STATE/update-in-progress" ]
}

@test "update: new rules load with failed rules → rolled back" {
    _linux_only; _env; _stubs; _seed
    echo "1 T1" > "$ENG/malcolm-reload"
    echo 3 > "$ENG/failed"
    export NETTAP_RULES_RELOAD_WAIT=1
    _update
    [ "$status" -eq 1 ]
    [ "$(_status reason)" = "Suricata loaded the rules with 3 failed rule(s); the last good rules were restored" ]
    [[ "$(_rules)" == *v1* ]]
}

@test "update: a reload still running after the deadline → rollback waits it out, then confirms the restored rules" {
    _linux_only; _env; _stubs; _seed
    export NETTAP_RULES_RELOAD_WAIT=2
    echo 3 > "$ENG/busy"
    _update
    [ "$status" -eq 1 ]
    [ "$(grep -c 'sc reload-rules' "$ENG/log")" -eq 4 ]
    [[ "$(cat "$ENG/engine-loaded")" == *v1* ]]
    [[ "$(_status reason)" == *"the last good rules were restored" ]]
    [ ! -e "$STATE/update-in-progress" ]
}

@test "update: the engine never confirms the restored rules → marker kept, status failed" {
    _linux_only; _env; _stubs; _seed
    export NETTAP_RULES_RELOAD_WAIT=1
    touch "$ENG/reload-noop"
    _update
    [ "$status" -eq 1 ]
    [ "$(_status state)" = failed ]
    [ "$(_status reason)" = "Suricata did not confirm the new rules within 1 s; Suricata's reload of the restored rules did not take effect; engine not confirmed (retried at the next update)" ]
    [ -e "$STATE/update-in-progress" ]
    [[ "$(_rules)" == *v1* ]]
}

@test "update: first run with no last good rules and a failed update → marker cleared, the next run updates" {
    _linux_only; _env; _stubs
    echo "alert ip any any -> any any (msg:\"v2\"; sid:2;)" > "$ENG/new-rules"
    echo 1 > "$ENG/malcolm-rc"
    _update
    [ "$status" -eq 1 ]
    [ "$(_status state)" = failed ]
    [ ! -e "$STATE/update-in-progress" ]
    [ "$(grep -c 'sc reload-rules' "$ENG/log")" -eq 0 ]
    rm -f "$ENG/malcolm-rc"
    echo "1 T1" > "$ENG/malcolm-reload"
    _update
    [ "$status" -eq 0 ]
    [ "$(_status state)" = active ]
    [ "$(grep -c "malcolm .* start" "$ENG/log")" -eq 2 ]
    [[ "$(_good)" == *v2* ]]
}

@test "update: a marker with a dangling last good link → the live rules are kept, the update goes ahead" {
    _linux_only; _env; _stubs; _seed
    rm -rf "$STATE/gen-0"
    echo "earlier" > "$STATE/update-in-progress"
    echo "1 T1" > "$ENG/malcolm-reload"
    rm -f "$ENG/new-rules"
    _update
    [ "$status" -eq 0 ]
    [[ "$(_rules)" == *v1* ]]
    [ "$(grep -c "malcolm .* start" "$ENG/log")" -eq 1 ]
    [ "$(_status state)" = active ]
}

@test "update: a marker left by a killed run → last good restored and reloaded before anything else" {
    _linux_only; _env; _stubs; _seed
    echo "half-written" > "$RULES_DIR/suricata.rules"
    echo "earlier" > "$STATE/update-in-progress"
    echo "1 T1" > "$ENG/malcolm-reload"
    _update
    [ "$status" -eq 0 ]
    [[ "$(cat "$ENG/engine-loaded")" == *v1* ]]
    # the blocking reload of the restored rules came before Malcolm's updater ran
    [ "$(grep -n 'sc reload-rules' "$ENG/log" | head -1 | cut -d: -f1)" -lt "$(grep -n 'malcolm .* start' "$ENG/log" | cut -d: -f1)" ]
    [ "$(_status state)" = active ]
}

@test "update: TERM right after the new rules are written → last good restored, status interrupted" {
    _linux_only; _env; _stubs; _seed
    echo 30 > "$ENG/malcolm-sleep"
    touch "$ENG/down"
    bash "$SCRIPT" update > "$TEST_TMPDIR/out" 2>&1 &
    pid=$!
    for _ in $(seq 1 50); do grep -q "malcolm .* start" "$ENG/log" 2>/dev/null && [[ "$(_rules)" == *v2* ]] && break; sleep 0.1; done
    kill -TERM "$pid"
    wait "$pid" || true
    [ "$(_status state)" = interrupted ]
    [[ "$(_rules)" == *v1* ]]
    [ ! -e "$STATE/update-in-progress" ]
    [ "$(grep -c "malcolm .* end" "$ENG/log")" -eq 0 ]  # the updater was stopped with it
}

@test "update: TERM with the engine running → last good restored and reloaded, status interrupted" {
    _linux_only; _env; _stubs; _seed
    echo 30 > "$ENG/malcolm-sleep"
    bash "$SCRIPT" update > "$TEST_TMPDIR/out" 2>&1 &
    pid=$!
    for _ in $(seq 1 50); do grep -q "malcolm .* start" "$ENG/log" 2>/dev/null && [[ "$(_rules)" == *v2* ]] && break; sleep 0.1; done
    kill -TERM "$pid"
    wait "$pid" || true
    [ "$(_status state)" = interrupted ]
    [ "$(_status reason)" = "The update was stopped before it finished; the last good rules were restored" ]
    [[ "$(_rules)" == *v1* ]]
    [[ "$(cat "$ENG/engine-loaded")" == *v1* ]]
    [ ! -e "$STATE/update-in-progress" ]
    [ "$(grep -c "malcolm .* end" "$ENG/log")" -eq 0 ]
}

# ---------------------------------------------------------------------------
# update: the lock
# ---------------------------------------------------------------------------

@test "update: a second update waits for the first" {
    _linux_only; _env; _stubs; _seed
    touch "$ENG/down"
    echo 1 > "$ENG/malcolm-sleep"
    bash "$SCRIPT" update > "$TEST_TMPDIR/out1" 2>&1 &
    first=$!
    for _ in $(seq 1 50); do grep -q "malcolm .* start" "$ENG/log" 2>/dev/null && break; sleep 0.1; done
    bash "$SCRIPT" update > "$TEST_TMPDIR/out2" 2>&1
    wait "$first"
    run grep -o 'malcolm [0-9]* [a-z]*' "$ENG/log"
    [ "${#lines[@]}" -eq 4 ]
    [[ "${lines[0]}" == *start ]] && [[ "${lines[1]}" == *end ]]
    [[ "${lines[2]}" == *start ]] && [[ "${lines[3]}" == *end ]]
    [ "${lines[0]% start}" = "${lines[1]% end}" ]
}

@test "update: lock held past the wait → no update, no status written" {
    _linux_only; _env; _stubs; _seed
    export NETTAP_RULES_LOCK_WAIT=1
    flock "$STATE/rules.lock" sleep 5 &
    holder=$!
    sleep 0.3
    _update
    kill "$holder" 2>/dev/null || true
    [ "$status" -eq 1 ]
    [[ "$output" == *"another rule operation held the lock for 1 s"* ]]
    [ "$(cat "$ENG/log" 2>/dev/null | grep -c malcolm)" -eq 0 ]
    [ ! -e "$STATE/update-status.json" ]
}

# ---------------------------------------------------------------------------
# update: last good generations
# ---------------------------------------------------------------------------

_stub_cp() {  # $1 = what to do when copying into a gen.tmp-* dir
    cat > "$TEST_TMPDIR/bin/cp" <<EOF
#!/usr/bin/env bash
case "\$*" in
    *gen.tmp-*) $1 ;;
    *) exec /bin/cp "\$@" ;;
esac
EOF
    chmod +x "$TEST_TMPDIR/bin/cp"
}

@test "update: killed while copying the last good rules → pointer unchanged; the next run cleans up" {
    _linux_only; _env; _stubs; _seed
    touch "$ENG/down"
    # copy one file, then the updater is SIGKILLed mid-copy
    _stub_cp 'mkdir -p "${@: -1}" && echo partial > "${@: -1}/suricata.rules"; kill -KILL $PPID; exit 1'
    _update
    [ "$status" -eq 137 ]
    [ "$(readlink "$STATE/last-good")" = gen-0 ]
    ls -d "$STATE"/gen.tmp-*
    [ -e "$STATE/update-in-progress" ]
    rm -f "$TEST_TMPDIR/bin/cp"
    _update
    [ "$status" -eq 0 ]
    [ -z "$(compgen -G "$STATE/gen.tmp-*")" ]
    [ "$(_status state)" = prepared ]
}

@test "update: disk full while copying the last good rules → pointer unchanged, nothing half-made left" {
    _linux_only
    [ -n "${TINYFS:-}" ] || skip "needs a small tmpfs: docker run --tmpfs /tinyfs:size=256k -e TINYFS=/tinyfs"
    STATE="$TINYFS/state-$BATS_TEST_NUMBER"
    _env; _stubs; _seed
    touch "$ENG/down"
    head -c 1048576 /dev/zero | tr '\0' 'x' > "$ENG/new-rules"
    _update
    [ "$status" -eq 0 ]
    [ "$(readlink "$STATE/last-good")" = gen-0 ]
    [ -z "$(compgen -G "$STATE/gen.tmp-*")" ]
    [ "$(_status reason)" = "the last good copy was not refreshed (copy failed)" ]
    rm -rf "$STATE"
}

@test "update: a copy that doesn't match the rules → not published" {
    _linux_only; _env; _stubs; _seed
    touch "$ENG/down"
    _stub_cp '/bin/cp "$@" && echo tampered >> "${@: -1}/suricata.rules"'
    _update
    [ "$status" -eq 0 ]
    [ "$(readlink "$STATE/last-good")" = gen-0 ]
    [ -z "$(compgen -G "$STATE/gen.tmp-*")" ]
    [ "$(_status reason)" = "the last good copy was not refreshed (copy did not match)" ]
}

@test "update: first run with no last good yet → the running rules are kept as one first" {
    _linux_only; _env; _stubs
    echo "alert ip any any -> any any (msg:\"v1\"; sid:1;)" > "$RULES_DIR/suricata.rules"
    echo "alert ip any any -> any any (msg:\"v2\"; sid:2;)" > "$ENG/new-rules"
    echo 1 > "$ENG/malcolm-rc"
    touch "$ENG/down"
    _update
    [ "$status" -eq 1 ]
    [[ "$(_rules)" == *v1* ]]
    [[ "$(_good)" == *v1* ]]
}
