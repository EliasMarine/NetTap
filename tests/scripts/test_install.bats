#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/install/install.sh
# ==========================================================================
# Structural checks on the generated nettap.service unit.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
INSTALL_SH="${REPO_ROOT}/scripts/install/install.sh"

@test "install: nettap.service stops containers without removing them (CR-025)" {
    # 'down' on every reboot recreated OpenSearch and the capture containers.
    local stop_lines
    stop_lines=$(grep -E '^ExecStop=' "$INSTALL_SH")
    [ -n "$stop_lines" ]
    echo "$stop_lines" | grep -q 'docker compose -f .* stop$'
    run bash -c "grep -E '^ExecStop=.* down' '$INSTALL_SH'"
    [ "$status" -ne 0 ]
}
