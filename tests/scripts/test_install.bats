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
    [[ "$output" == *"NEXT STEP"* ]] || false
    [[ "$output" == *"NIC roles skipped (--skip-bridge)"* ]] || false
    [ ! -e "${STUB_DIR}/calls" ]
    rm -rf "$STUB_DIR"
}

@test "NET-244: a non-interactive bridge install still auto-assigns (its abort keeps the internet port out)" {
    _stub_preflight
    _nic_preflight "SKIP_BRIDGE=false NON_INTERACTIVE=true"
    [ "$status" -ne 0 ]
    [[ "$output" != *"NEXT STEP"* ]] || false
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
    [[ "$output" == *"[ OK ] OpenSearch cluster health: green"* ]] || false
    [[ "$output" != *"not responding"* ]] || false
}

@test "NET-211 #5: a red cluster is a warning that names the status" {
    _verify_with_opensearch "echo '{\"status\":\"red\"}'"
    [[ "$output" == *"[WARN] OpenSearch cluster health: red"* ]] || false
}

@test "NET-211 #5: no answer from OpenSearch still says it isn't responding yet" {
    _verify_with_opensearch "return 1"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[WARN] OpenSearch not responding yet"* ]] || false
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
    [[ "$output" == *"UFW not active, nothing to change"* ]] || false
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

@test "NET-211 #6: the firewall step doesn't open 9443, which nothing publishes" {
    _firewall_with_ufw "Status: active"
    [ "$(grep -c '9443' "${FW_DIR}/calls")" -eq 0 ]
    rm -rf "$FW_DIR"
}

# ---------------------------------------------------------------------------
# NET-211 #8: --dry-run must write nothing
# ---------------------------------------------------------------------------
_strict() {
    run bash -c "set -euo pipefail; source '$INSTALL_SH'; NETTAP_UI=plain; $1"
}

@test "NET-211 #8: write_file writes stdin, and under --dry-run only names the file" {
    local dir; dir="$(mktemp -d)"
    _strict "write_file '$dir/a' <<< 'hello'"
    [ "$status" -eq 0 ]
    [ "$(cat "$dir/a")" = "hello" ]
    _strict "NETTAP_DRY_RUN=true; write_file '$dir/b' <<< 'hello'"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] write $dir/b"* ]] || false
    [ ! -e "$dir/b" ]
    rm -rf "$dir"
}

@test "NET-211 #8: the dry run writes no sysctl file and no nettap.service" {
    _strict "NETTAP_DRY_RUN=true; sysctl() { :; }; systemctl() { :; }; step_kernel_tuning; step_systemd"
    [ "$status" -eq 0 ]
    if [[ ! -e /etc/sysctl.d/99-nettap.conf ]]; then
        [[ "$output" == *"[DRY-RUN] write /etc/sysctl.d/99-nettap.conf"* ]] || false
    fi
    [[ "$output" == *"[DRY-RUN] write /etc/systemd/system/nettap.service"* ]] || false
}

@test "NET-211 #8: the dry run installs nothing and doesn't stop at the missing Compose plugin" {
    _strict "NETTAP_DRY_RUN=true
        apt-get() { echo REAL-APT-GET; }
        dpkg() { return 1; }
        docker() { return 1; }
        systemctl() { echo REAL-SYSTEMCTL; }
        configure_docker_daemon() { return 1; }
        step_dependencies"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] apt-get install -y -qq docker-compose-plugin"* ]] || false
    [[ "$output" != *"REAL-"* ]] || false
    [[ "$output" != *"Docker Compose plugin not available"* ]] || false
}

@test "NET-211 #8: the dry run doesn't run deploy-malcolm.sh, it names it" {
    local dir; dir="$(mktemp -d)"
    printf '#!/usr/bin/env bash\necho ran >> "%s/calls"\n' "$dir" > "$dir/deploy-malcolm.sh"
    chmod +x "$dir/deploy-malcolm.sh"
    _strict "NETTAP_DRY_RUN=true; SCRIPT_DIR='$dir'; step_malcolm"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] $dir/deploy-malcolm.sh --dry-run"* ]] || false
    [ ! -e "$dir/calls" ]
    rm -rf "$dir"
}

@test "NET-211 #8: configure_docker_daemon creates or extends daemon.json, and writes nothing in a dry run" {
    local dir; dir="$(mktemp -d)"
    # dry run, no file: names it, writes nothing, still asks for a restart
    _strict "NETTAP_DRY_RUN=true; configure_docker_daemon '$dir/daemon.json'"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] write $dir/daemon.json"* ]] || false
    [ ! -e "$dir/daemon.json" ]
    # real run, no file: NetTap's settings
    _strict "configure_docker_daemon '$dir/daemon.json'"
    [ "$status" -eq 0 ]
    [ "$(jq -c .dns "$dir/daemon.json")" = '["9.9.9.9","149.112.112.112"]' ]
    [ "$(jq -r '."storage-driver"' "$dir/daemon.json")" = "overlay2" ]
    # an owner's file without dns: dns added, the rest kept; a dry run leaves it as it was
    printf '{"data-root": "/srv/docker"}\n' > "$dir/daemon.json"
    _strict "NETTAP_DRY_RUN=true; configure_docker_daemon '$dir/daemon.json'"
    [ "$(cat "$dir/daemon.json")" = '{"data-root": "/srv/docker"}' ]
    _strict "configure_docker_daemon '$dir/daemon.json'"
    [ "$status" -eq 0 ]
    [ "$(jq -r '."data-root"' "$dir/daemon.json")" = "/srv/docker" ]
    [ "$(jq -c .dns "$dir/daemon.json")" = '["9.9.9.9","149.112.112.112"]' ]
    # dns already set: untouched, no restart (status 1)
    _strict "configure_docker_daemon '$dir/daemon.json'"
    [ "$status" -eq 1 ]
    # not JSON: stops with a message, the file is kept
    printf 'not json\n' > "$dir/daemon.json"
    _strict "configure_docker_daemon '$dir/daemon.json'"
    [ "$status" -ne 0 ]
    [[ "$output" == *"Couldn't read $dir/daemon.json as JSON"* ]] || false
    [ "$(cat "$dir/daemon.json")" = "not json" ]
    rm -rf "$dir"
}
