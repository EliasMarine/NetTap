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
