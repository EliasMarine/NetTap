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

# ---------------------------------------------------------------------------
# NET-244: install.sh sourced (main doesn't run then), preflight.sh swapped for a stub that
# records its call and stops the way a two-port box with internet on one port did.
# ---------------------------------------------------------------------------
_stub_preflight() {
    STUB_DIR="$(mktemp -d)"
    cat > "${STUB_DIR}/preflight.sh" <<'STUB'
#!/usr/bin/env bash
echo "preflight $*" >> "$(dirname "$0")/calls"
echo "Could not assign WAN and LAN NICs" >&2
exit 1
STUB
    chmod +x "${STUB_DIR}/preflight.sh"
}

_nic_preflight() {
    run bash -c "set -euo pipefail; source '$INSTALL_SH'
        SCRIPT_DIR='$STUB_DIR' PROJECT_ROOT='$STUB_DIR' $1
        step_nic_preflight; echo NEXT STEP"
}

@test "NET-244: --skip-bridge --non-interactive doesn't assign NIC roles, so two ports don't stop it" {
    _stub_preflight
    _nic_preflight "SKIP_BRIDGE=true NON_INTERACTIVE=true"
    [ "$status" -eq 0 ]
    [[ "$output" == *"NEXT STEP"* ]]
    [[ "$output" == *"NIC roles skipped (--skip-bridge)"* ]]
    [ ! -e "${STUB_DIR}/calls" ]
    rm -rf "$STUB_DIR"
}

@test "NET-244: a non-interactive bridge install still auto-assigns (its abort keeps the internet port out)" {
    _stub_preflight
    _nic_preflight "SKIP_BRIDGE=false NON_INTERACTIVE=true"
    [ "$status" -ne 0 ]
    [[ "$output" != *"NEXT STEP"* ]]
    grep -q -- "--non-interactive" "${STUB_DIR}/calls"
    rm -rf "$STUB_DIR"
}

@test "NET-244: the interactive --skip-bridge path still runs preflight (prompts unchanged)" {
    _stub_preflight
    _nic_preflight "SKIP_BRIDGE=true NON_INTERACTIVE=false"
    [ "$status" -ne 0 ]
    [ -e "${STUB_DIR}/calls" ]
    run grep -q -- "--non-interactive" "${STUB_DIR}/calls"
    [ "$status" -eq 1 ]
    rm -rf "$STUB_DIR"
}
