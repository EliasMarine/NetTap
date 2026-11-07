#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/remote/verify-detection.sh (NET-191 replay harness)
# ==========================================================================
# Only the refusals and the rules lock run here: they happen before the snapshot is copied.
# The replay itself needs the G11 (Linux, docker, the live Suricata) and is checked there.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/remote/verify-detection.sh"

load 'helpers/setup'

# sudo records every call. It answers the inspects of the live container (image, env with our own
# UID, and the rules-state volume when MOCK_LOCK_VOLUME is set), the lock holder's start and logs,
# and fails everything else (so the snapshot copy fails and the script stops there).
# date answers +%H%M with MOCK_HHMM and defers to the real date otherwise.
_stub_commands() {
    mkdir -p "$TEST_TMPDIR/bin"
    export CALLS="$TEST_TMPDIR/calls" MOCK_UID MOCK_GID NETTAP_REPLAY_ROOT="$TEST_TMPDIR/replay"
    MOCK_UID=$(id -u)
    MOCK_GID=$(id -g)
    : > "$CALLS"
    cat > "$TEST_TMPDIR/bin/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo $*" >> "$CALLS"
case "$*" in
    "docker inspect -f {{.Config.Image}} nettap-suricata-live") echo "ghcr.io/idaholab/malcolm/suricata:26.10.0" ;;
    "docker inspect -f {{range .Config.Env}}{{println .}}{{end}} nettap-suricata-live")
        printf 'PUID=%s\nPGID=%s\n' "$MOCK_UID" "$MOCK_GID" ;;
    *"/run/nettap-rules"*"nettap-suricata-live") echo "${MOCK_LOCK_VOLUME:-}" ;;
    "docker run -d --rm --name nettap-rules-lock-"*) echo "holder-id" ;;
    "docker logs nettap-rules-lock-"*) echo "locked" ;;
    "docker rm -f nettap-rules-lock-"*) ;;
    *) exit 1 ;;
esac
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

_copied() { grep -c "docker cp" "$CALLS"; }

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

@test "verify-detection: no rules lock yet → refuses 23:50-00:30 UTC, around Malcolm's nightly rule update" {
    _stub_commands
    _meminfo 3145728
    for hhmm in 2350 2359 0000 0010 0029; do
        export MOCK_HHMM=$hhmm
        run bash "$SCRIPT" fixtures
        [ "$status" -eq 3 ]
        [[ "$output" == *"inside 23:50-00:30"* ]]
    done
    [ "$(_copied)" -eq 0 ]
}

@test "verify-detection: no rules lock yet → 00:30 and 23:49 pass the time check (then copy the snapshot)" {
    _stub_commands
    _meminfo 3145728
    for hhmm in 0030 2349 0809; do
        export MOCK_HHMM=$hhmm
        run bash "$SCRIPT" fixtures
        [ "$status" -eq 2 ]
        [[ "$output" != *"inside 23:50-00:30"* ]]
        [[ "$output" == *"no rules lock on this device yet"* ]]
        [[ "$output" == *"Could not copy /etc/suricata out of nettap-suricata-live"* ]]
    done
}

@test "verify-detection: with the rules lock → no time window; the snapshot is taken holding it" {
    _stub_commands
    _meminfo 3145728
    export MOCK_HHMM=2355 MOCK_LOCK_VOLUME=docker_nettap-rules-state
    run bash "$SCRIPT" fixtures
    [ "$status" -eq 2 ]
    [[ "$output" == *"holding the rules lock for the snapshot"* ]]
    # holder started on the volume, the copy tried while held, holder removed afterwards
    run grep -n "docker run -d --rm --name nettap-rules-lock-.*docker_nettap-rules-state:/run/nettap-rules --entrypoint flock .* -w 900 /run/nettap-rules/rules.lock" "$CALLS"
    [ "$status" -eq 0 ]
    taken=${output%%:*}
    copied=$(grep -n "docker cp" "$CALLS" | head -1 | cut -d: -f1)
    released=$(grep -n "docker rm -f nettap-rules-lock-" "$CALLS" | tail -1 | cut -d: -f1)
    [ "$taken" -lt "$copied" ] && [ "$copied" -lt "$released" ]
}
