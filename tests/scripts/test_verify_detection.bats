#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/remote/verify-detection.sh (NET-191 replay harness)
# ==========================================================================
# Only the refusals run here: they happen before any docker call. The replay itself
# needs the G11 (Linux, docker, the live Suricata) and is checked there.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/remote/verify-detection.sh"

load 'helpers/setup'

# sudo records every call and fails, so a test sees whether docker was reached;
# date answers +%H%M with MOCK_HHMM and defers to the real date otherwise.
_stub_commands() {
    mkdir -p "$TEST_TMPDIR/bin"
    export CALLS="$TEST_TMPDIR/calls"
    : > "$CALLS"
    cat > "$TEST_TMPDIR/bin/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo $*" >> "$CALLS"
exit 1
EOF
    cat > "$TEST_TMPDIR/bin/date" <<'EOF'
#!/usr/bin/env bash
if [ "${2:-}" = "+%H%M" ]; then echo "$MOCK_HHMM"; else exec /bin/date "$@"; fi
EOF
    chmod +x "$TEST_TMPDIR/bin/sudo" "$TEST_TMPDIR/bin/date"
    export PATH="$TEST_TMPDIR/bin:$PATH"
}

_meminfo() {  # $1 = MemAvailable in kB
    printf 'MemTotal:       12197808 kB\nMemAvailable:   %s kB\n' "$1" > "$TEST_TMPDIR/meminfo"
    export NETTAP_MEMINFO="$TEST_TMPDIR/meminfo"
}

@test "verify-detection: bad usage exits 2 without touching docker" {
    _stub_commands
    run bash "$SCRIPT"
    [ "$status" -eq 2 ]
    run bash "$SCRIPT" own
    [ "$status" -eq 2 ]
    run bash "$SCRIPT" fixtures --rules "$TEST_TMPDIR/does-not-exist"
    [ "$status" -eq 2 ]
    run bash "$SCRIPT" fixtures --bogus
    [ "$status" -eq 2 ]
    [ ! -s "$CALLS" ]
}

@test "verify-detection: refuses below 1.5 GiB available" {
    _stub_commands
    _meminfo 1048576
    export MOCK_HHMM=1200
    run bash "$SCRIPT" fixtures
    [ "$status" -eq 3 ]
    [[ "$output" == *"Only 1024 MiB available; need 1536 MiB"* ]]
    [ ! -s "$CALLS" ]
}

@test "verify-detection: refuses 23:50-00:30 UTC, around Malcolm's nightly rule update" {
    _stub_commands
    _meminfo 3145728
    for hhmm in 2350 2359 0000 0010 0029; do
        export MOCK_HHMM=$hhmm
        run bash "$SCRIPT" fixtures
        [ "$status" -eq 3 ]
        [[ "$output" == *"inside 23:50-00:30"* ]]
    done
    [ ! -s "$CALLS" ]
}

@test "verify-detection: 00:30 and 23:49 pass the time check (then need the live container)" {
    _stub_commands
    _meminfo 3145728
    for hhmm in 0030 2349 0809; do
        export MOCK_HHMM=$hhmm
        run bash "$SCRIPT" fixtures
        [ "$status" -eq 3 ]
        [[ "$output" != *"inside 23:50-00:30"* ]]
        [[ "$output" == *"nettap-suricata-live not found"* ]]
    done
}
