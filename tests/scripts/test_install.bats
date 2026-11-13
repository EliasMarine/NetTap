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

# ---------------------------------------------------------------------------
# NET-211 #5: the OpenSearch check sent no credentials, so the 401 read as "not responding"
# ---------------------------------------------------------------------------
# step_verify with stubs: bridge skipped, Docker up, one container, and a host curl that fails
# the way an unauthenticated request does. $1 = what `docker compose exec opensearch` prints.
_verify_with_opensearch() {
    run bash -c "set -euo pipefail; source '$INSTALL_SH'
        SKIP_BRIDGE=true NETTAP_UI=plain
        ip() { return 1; }
        curl() { return 22; }
        systemctl() { return 0; }
        sysctl() { echo 262144; }
        load_env() { :; }
        ui_summary_installed() { :; }
        docker() {
            case \"\$*\" in
                *'exec -T opensearch curl --config /var/local/curlrc/.opensearch.primary.curlrc'*) $1 ;;
                *'ps -q'*) echo container1 ;;
                *) return 0 ;;
            esac
        }
        step_verify"
}

@test "NET-211 #5: the installer's OpenSearch check signs in and reports the cluster status" {
    _verify_with_opensearch "echo '{\"status\":\"green\"}'"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[ OK ] OpenSearch cluster health: green"* ]]
    [[ "$output" != *"not responding"* ]]
}

@test "NET-211 #5: a red cluster is a warning that names the status" {
    _verify_with_opensearch "echo '{\"status\":\"red\"}'"
    [[ "$output" == *"[WARN] OpenSearch cluster health: red"* ]]
}

@test "NET-211 #5: no answer from OpenSearch still says it isn't responding yet" {
    _verify_with_opensearch "return 1"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[WARN] OpenSearch not responding yet"* ]]
}

# ---------------------------------------------------------------------------
# NET-211 #6, #7: step_firewall with a ufw stub that logs every call. $1 = its status line.
# ---------------------------------------------------------------------------
_firewall_with_ufw() {
    FW_DIR="$(mktemp -d)"
    mkdir -p "${FW_DIR}/bin"
    cat > "${FW_DIR}/bin/ufw" <<STUB
#!/usr/bin/env bash
if [[ "\$1" == "status" ]]; then echo "$1"; exit 0; fi
echo "ufw \$*" >> "${FW_DIR}/calls"
STUB
    chmod +x "${FW_DIR}/bin/ufw"
    run env PATH="${FW_DIR}/bin:$PATH" bash -c "set -euo pipefail; source '$INSTALL_SH'
        NETTAP_UI=plain; step_firewall"
}

@test "NET-211 #7: UFW inactive is left alone" {
    _firewall_with_ufw "Status: inactive"
    [ "$status" -eq 0 ]
    [[ "$output" == *"UFW not active, nothing to change"* ]]
    [ ! -e "${FW_DIR}/calls" ]
    rm -rf "$FW_DIR"
}

@test "NET-211 #7: UFW active gets the dashboard and mDNS rules" {
    _firewall_with_ufw "Status: active"
    [ "$status" -eq 0 ]
    grep -q "ufw allow 443/tcp" "${FW_DIR}/calls"
    grep -q "ufw allow 5353/udp" "${FW_DIR}/calls"
    rm -rf "$FW_DIR"
}
