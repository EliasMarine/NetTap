#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/install/validate-hardware.sh check_disk (NET-177):
# decimal GB (10^9 bytes), as the daemon, System and Setup show sizes.
# ==========================================================================

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
HARDWARE="${REPO_ROOT}/scripts/install/validate-hardware.sh"

_check_disk_with_total_kb() {
    run bash -c "source '$HARDWARE'
        df() { printf 'Filesystem 1K-blocks Used Available Use%% Mounted on\n/dev/x %s 1 1 1%% /\n' $1; }
        check_disk"
}

@test "check_disk (NET-177): a 1 TB filesystem reads 1000 GB, not 931" {
    _check_disk_with_total_kb 976562500
    [ "$status" -eq 0 ]
    [[ "$output" == *"Disk: 1000 GB total"* ]] || false
}

@test "check_disk (NET-177): the minimum is 430 GB, the old 400 GiB in decimal" {
    _check_disk_with_total_kb 419921875  # 430.00 GB
    [ "$status" -eq 0 ]
    _check_disk_with_total_kb 419921874  # 429.99 GB
    [ "$status" -eq 1 ]
    [[ "$output" == *"Disk: 429 GB total (512 GB+ recommended)"* ]] || false
}

@test "run standalone (NET-253): a first-check warning still runs every check and prints the result" {
    stubs="$BATS_TEST_TMPDIR/bin"
    mkdir -p "$stubs"
    # uname reports x86-64 and nproc 2 cores, so check_cpu warns (4+ recommended)
    printf '#!/bin/sh\ncase "$1" in -m) echo x86_64 ;; *) echo 6.8.0-test ;; esac\n' > "$stubs/uname"
    printf '#!/bin/sh\necho 2\n' > "$stubs/nproc"
    chmod +x "$stubs/uname" "$stubs/nproc"
    PATH="$stubs:$PATH" run bash "$HARDWARE" --color never
    [ "$status" -ge 1 ]
    [[ "$output" == *"CPU cores: 2 (4+ recommended)"* ]] || false
    [[ "$output" == *"RAM:"* ]] || false
    [[ "$output" == *"Disk:"* ]] || false
    [[ "$output" == *"Kernel: 6.8.0-test"* ]] || false
    [[ "$output" == *"RESULT:"* ]] || false
}
