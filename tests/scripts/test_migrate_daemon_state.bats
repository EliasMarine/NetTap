#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/remote/migrate-daemon-state.sh (release audit F4)
# ==========================================================================
# Temp dirs stand in for the daemon's /tmp (src) and /opt/nettap/data (dst); the script runs
# under sh, as it does in the container.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/remote/migrate-daemon-state.sh"

load 'helpers/setup'

_dirs() {
    SRC="$TEST_TMPDIR/src" DST="$TEST_TMPDIR/dst"
    mkdir -p "$SRC" "$DST"
}

_aside() { find "$DST" -name "$1.pre-migration-*" | sort; }

@test "migrate-daemon-state: moves every present file and skips the missing ones" {
    _dirs
    echo '{"global": [{"signature_id": 1}]}' > "$SRC/nettap-suppress.json"
    echo '{"history": []}' > "$SRC/nettap-baselines.json"
    run sh "$SCRIPT" "$SRC" "$DST"
    [ "$status" -eq 0 ]
    cmp "$SRC/nettap-suppress.json" "$DST/nettap-suppress.json"
    cmp "$SRC/nettap-baselines.json" "$DST/nettap-baselines.json"
    [ ! -e "$DST/nettap-threat-intel.json" ]
    [[ "$output" == *"nettap-threat-intel.json: not in"* ]]
    [ -z "$(find "$DST" -name '.*.migrating')" ]
}

@test "migrate-daemon-state: a retry after a partial run installs the updated source and keeps the old copy" {
    _dirs
    echo '{"global": [{"signature_id": 1}]}' > "$SRC/nettap-suppress.json"
    echo '{"history": [' > "$SRC/nettap-baselines.json"  # cut short: the first run stops here
    run sh "$SCRIPT" "$SRC" "$DST"
    [ "$status" -eq 1 ]
    cmp "$SRC/nettap-suppress.json" "$DST/nettap-suppress.json"
    [ ! -e "$DST/nettap-baselines.json" ]

    # the old daemon keeps running and records a new suppression before the retry
    cp "$SRC/nettap-suppress.json" "$TEST_TMPDIR/first"
    echo '{"global": [{"signature_id": 1}, {"signature_id": 2}]}' > "$SRC/nettap-suppress.json"
    echo '{"history": []}' > "$SRC/nettap-baselines.json"
    run sh "$SCRIPT" "$SRC" "$DST"
    [ "$status" -eq 0 ]
    cmp "$SRC/nettap-suppress.json" "$DST/nettap-suppress.json"
    cmp "$SRC/nettap-baselines.json" "$DST/nettap-baselines.json"
    [ "$(_aside nettap-suppress.json | wc -l | tr -d ' ')" -eq 1 ]
    cmp "$TEST_TMPDIR/first" "$(_aside nettap-suppress.json)"
    [ -z "$(_aside nettap-baselines.json)" ]
    [ -z "$(find "$DST" -name '.*.migrating')" ]
}

@test "migrate-daemon-state: invalid JSON aborts and leaves the destination untouched" {
    _dirs
    echo '{"global": [{"signature_id": 7}]}' > "$DST/nettap-suppress.json"
    cp "$DST/nettap-suppress.json" "$TEST_TMPDIR/before"
    printf 'not json' > "$SRC/nettap-suppress.json"
    echo '{"history": []}' > "$SRC/nettap-baselines.json"
    run sh "$SCRIPT" "$SRC" "$DST"
    [ "$status" -eq 1 ]
    [[ "$output" == *"nettap-suppress.json: the copy is not valid JSON"* ]]
    cmp "$TEST_TMPDIR/before" "$DST/nettap-suppress.json"
    [ -z "$(_aside nettap-suppress.json)" ]
    [ ! -e "$DST/nettap-baselines.json" ]  # stopped at the first failure
    [ -z "$(find "$DST" -name '.*.migrating')" ]
}

@test "migrate-daemon-state: an identical destination is left as it is" {
    _dirs
    echo '{"history": []}' > "$SRC/nettap-baselines.json"
    cp "$SRC/nettap-baselines.json" "$DST/nettap-baselines.json"
    run sh "$SCRIPT" "$SRC" "$DST"
    [ "$status" -eq 0 ]
    [[ "$output" == *"nettap-baselines.json: already in"* ]]
    [ -z "$(_aside nettap-baselines.json)" ]
}

@test "migrate-daemon-state: a link in the source is refused and nothing moves" {
    _dirs
    echo '{"global": []}' > "$TEST_TMPDIR/elsewhere.json"
    ln -s "$TEST_TMPDIR/elsewhere.json" "$SRC/nettap-suppress.json"
    run sh "$SCRIPT" "$SRC" "$DST"
    [ "$status" -eq 1 ]
    [[ "$output" == *"nettap-suppress.json: not a regular file"* ]]
    [ ! -e "$DST/nettap-suppress.json" ]
}

@test "migrate-daemon-state: a missing destination directory fails before anything moves" {
    _dirs
    echo '{"history": []}' > "$SRC/nettap-baselines.json"
    run sh "$SCRIPT" "$SRC" "$TEST_TMPDIR/absent"
    [ "$status" -eq 1 ]
    [ -f "$SRC/nettap-baselines.json" ]
}
