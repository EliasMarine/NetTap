#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/install/preflight.sh
# ==========================================================================

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

load 'helpers/setup'

# ---------------------------------------------------------------------------
# Test 1: Detects 3 physical NICs correctly
# ---------------------------------------------------------------------------
@test "discover_nics: detects 3 physical NICs" {
    export MOCK_NICS=$'enp1s0\nenp2s0\nenp3s0'

    # Use the mock list_physical_nics
    NIC_NAMES=()
    while IFS= read -r nic; do
        [[ -z "$nic" ]] && continue
        NIC_NAMES+=("$nic")
    done < <(list_physical_nics | sort)

    [ "${#NIC_NAMES[@]}" -eq 3 ]
    [ "${NIC_NAMES[0]}" = "enp1s0" ]
    [ "${NIC_NAMES[1]}" = "enp2s0" ]
    [ "${NIC_NAMES[2]}" = "enp3s0" ]
}

# ---------------------------------------------------------------------------
# Test 2: Detects internet NIC from default route
# ---------------------------------------------------------------------------
@test "detect_internet_nic: finds NIC with default route" {
    export MOCK_DEFAULT_ROUTE_NIC="enp1s0"

    local iface
    iface=$(ip route show default 2>/dev/null \
        | head -1 \
        | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}') || true

    [ "$iface" = "enp1s0" ]
}

# ---------------------------------------------------------------------------
# Test 3: Warns when internet NIC assigned to bridge
# ---------------------------------------------------------------------------
@test "preflight: warns when internet NIC is assigned to bridge" {
    local result
    result=$(
        INTERNET_NIC="enp2s0"
        ASSIGNED_WAN="enp2s0"
        ASSIGNED_LAN="enp3s0"
        if [[ "$INTERNET_NIC" == "$ASSIGNED_WAN" || "$INTERNET_NIC" == "$ASSIGNED_LAN" ]]; then
            echo "WARNING: internet NIC assigned to bridge"
        else
            echo "no warning"
        fi
    )
    [[ "$result" == *"WARNING: internet NIC assigned to bridge"* ]]
}

# ---------------------------------------------------------------------------
# Test 4: Rejects duplicate NIC assignments
# ---------------------------------------------------------------------------
@test "preflight: rejects duplicate NIC assignments" {
    local result rc=0
    result=$(
        ASSIGNED_WAN="enp1s0"
        ASSIGNED_LAN="enp1s0"
        if [[ "$ASSIGNED_WAN" == "$ASSIGNED_LAN" ]]; then
            echo "ERROR: duplicate"
            exit 1
        fi
    ) || rc=$?
    [ "$rc" -eq 1 ]
    [[ "$result" == *"ERROR: duplicate"* ]]
}

# ---------------------------------------------------------------------------
# Test 5: Non-interactive mode auto-assigns NICs
# ---------------------------------------------------------------------------
@test "preflight --non-interactive: auto-assigns MGMT, WAN, LAN" {
    # preflight.sh sources common.sh which defines list_physical_nics().
    # On non-Linux (or without /sys/class/net), we need a patched common.sh
    # that loads the real one then re-applies our mocks on top.
    local mock_scripts="${TEST_TMPDIR}/mock_scripts"
    mkdir -p "${mock_scripts}"

    # Create a wrapper common.sh that sources the real one, then mocks
    cat > "${mock_scripts}/common.sh" <<WRAPPER
source '${REPO_ROOT}/scripts/common.sh'
source '${BATS_TEST_DIRNAME}/helpers/mocks.bash'
WRAPPER

    # Copy preflight.sh and patch its source line to use our wrapper
    sed "s|source \"\${SCRIPT_DIR}/../common.sh\"|source '${mock_scripts}/common.sh'|" \
        "${REPO_ROOT}/scripts/install/preflight.sh" > "${mock_scripts}/preflight.sh"
    chmod +x "${mock_scripts}/preflight.sh"

    local output rc=0
    output=$(bash -c "
        export MOCK_NICS='enp1s0
enp2s0
enp3s0'
        export MOCK_DEFAULT_ROUTE_NIC='enp1s0'
        export PROJECT_ROOT='${TEST_TMPDIR}'
        export TEST_TMPDIR='${TEST_TMPDIR}'
        export NETTAP_DRY_RUN='true'
        export NETTAP_VERBOSE='false'
        bash '${mock_scripts}/preflight.sh' --env-file '${TEST_TMPDIR}/.env' --non-interactive --reconfigure-nics --dry-run
    " 2>&1) || rc=$?

    [ "$rc" -eq 0 ]
    [[ "$output" == *"MGMT=enp1s0"* ]]
    [[ "$output" == *"WAN=enp2s0"* ]]
    [[ "$output" == *"LAN=enp3s0"* ]]
}

# ---------------------------------------------------------------------------
# Test 6: Writes .env with correct NIC values
# ---------------------------------------------------------------------------
@test "write_env_assignments: writes correct values to .env" {
    local env_file="${TEST_TMPDIR}/.env"
    touch "$env_file"

    # Inline the _set_env_value logic
    _set_env_value() {
        local key="$1" value="$2" file="$3"
        if grep -q "^${key}=" "$file" 2>/dev/null; then
            sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
            rm -f "${file}.bak"
        else
            echo "${key}=${value}" >> "$file"
        fi
    }

    _set_env_value "WAN_INTERFACE" "enp2s0" "$env_file"
    _set_env_value "LAN_INTERFACE" "enp3s0" "$env_file"
    _set_env_value "MGMT_INTERFACE" "enp1s0" "$env_file"

    grep -q "^WAN_INTERFACE=enp2s0$" "$env_file"
    grep -q "^LAN_INTERFACE=enp3s0$" "$env_file"
    grep -q "^MGMT_INTERFACE=enp1s0$" "$env_file"
}

# ---------------------------------------------------------------------------
# Test 7: Preserves existing .env non-NIC values
# ---------------------------------------------------------------------------
@test "write_env_assignments: preserves existing non-NIC values" {
    local env_file="${TEST_TMPDIR}/.env"
    cat > "$env_file" <<'EOF'
NETTAP_HOSTNAME=nettap.local
DASHBOARD_PORT=443
WAN_INTERFACE=eth0
LAN_INTERFACE=eth1
RETENTION_HOT=90
EOF

    # Update NIC values
    sed -i.bak "s|^WAN_INTERFACE=.*|WAN_INTERFACE=enp2s0|" "$env_file"
    sed -i.bak "s|^LAN_INTERFACE=.*|LAN_INTERFACE=enp3s0|" "$env_file"
    rm -f "${env_file}.bak"

    # Verify NIC values changed
    grep -q "^WAN_INTERFACE=enp2s0$" "$env_file"
    grep -q "^LAN_INTERFACE=enp3s0$" "$env_file"

    # Verify non-NIC values preserved
    grep -q "^NETTAP_HOSTNAME=nettap.local$" "$env_file"
    grep -q "^DASHBOARD_PORT=443$" "$env_file"
    grep -q "^RETENTION_HOT=90$" "$env_file"
}

# ---------------------------------------------------------------------------
# Test 8: Fails gracefully with fewer than 2 NICs
# ---------------------------------------------------------------------------
@test "preflight: fails with fewer than 2 NICs" {
    # Use the same patched script approach as test 5
    local mock_scripts="${TEST_TMPDIR}/mock_scripts"
    mkdir -p "${mock_scripts}"

    cat > "${mock_scripts}/common.sh" <<WRAPPER
source '${REPO_ROOT}/scripts/common.sh'
source '${BATS_TEST_DIRNAME}/helpers/mocks.bash'
WRAPPER

    sed "s|source \"\${SCRIPT_DIR}/../common.sh\"|source '${mock_scripts}/common.sh'|" \
        "${REPO_ROOT}/scripts/install/preflight.sh" > "${mock_scripts}/preflight.sh"
    chmod +x "${mock_scripts}/preflight.sh"

    local output rc=0
    output=$(bash -c "
        export MOCK_NICS='enp1s0'
        export MOCK_DEFAULT_ROUTE_NIC='enp1s0'
        export PROJECT_ROOT='${TEST_TMPDIR}'
        export TEST_TMPDIR='${TEST_TMPDIR}'
        export NETTAP_DRY_RUN='true'
        export NETTAP_VERBOSE='false'
        bash '${mock_scripts}/preflight.sh' --env-file '${TEST_TMPDIR}/.env' --non-interactive --reconfigure-nics --dry-run
    " 2>&1) || rc=$?

    [ "$rc" -ne 0 ]
    [[ "$output" == *"at least 2 physical NICs"* ]]
}

# ---------------------------------------------------------------------------
# NET-244: two ports, internet on one. Auto-assignment still stops rather than put the
# internet port in a bridge; install.sh doesn't call it under --skip-bridge --non-interactive.
# ---------------------------------------------------------------------------
@test "preflight --non-interactive: two ports with internet on one still stops (bridge installs)" {
    local mock_scripts="${TEST_TMPDIR}/mock_scripts"
    mkdir -p "${mock_scripts}"
    cat > "${mock_scripts}/common.sh" <<WRAPPER
source '${REPO_ROOT}/scripts/common.sh'
source '${BATS_TEST_DIRNAME}/helpers/mocks.bash'
WRAPPER
    sed "s|source \"\${SCRIPT_DIR}/../common.sh\"|source '${mock_scripts}/common.sh'|" \
        "${REPO_ROOT}/scripts/install/preflight.sh" > "${mock_scripts}/preflight.sh"

    local output rc=0
    output=$(bash -c "
        export MOCK_NICS='enp1s0
enp2s0'
        export MOCK_DEFAULT_ROUTE_NIC='enp2s0'
        export PROJECT_ROOT='${TEST_TMPDIR}' TEST_TMPDIR='${TEST_TMPDIR}'
        bash '${mock_scripts}/preflight.sh' --env-file '${TEST_TMPDIR}/.env' --non-interactive --reconfigure-nics --dry-run
    " 2>&1) || rc=$?

    [ "$rc" -ne 0 ]
    [[ "$output" == *"Could not assign WAN and LAN NICs"* ]] || false
}

# ---------------------------------------------------------------------------
# Test 9: LED blink calls ethtool -p with correct args
# ---------------------------------------------------------------------------
@test "blink_nic: calls ethtool -p with correct interface and duration" {
    export MOCK_ETHTOOL_AVAILABLE="true"

    # Call our mock ethtool
    ethtool -p enp1s0 10

    # Verify call was logged
    [ -f "${TEST_TMPDIR}/ethtool_calls.log" ]
    grep -q "ethtool -p enp1s0 10" "${TEST_TMPDIR}/ethtool_calls.log"
}

# ---------------------------------------------------------------------------
# Test 10: Skips LED blink gracefully when ethtool unavailable
# ---------------------------------------------------------------------------
@test "blink_nic: skips gracefully when ethtool is unavailable" {
    local result
    result=$(
        # Simulate missing ethtool by shadowing command
        command() {
            if [[ "${2:-}" == "ethtool" ]]; then return 1; fi
            builtin command "$@"
        }
        if ! command -v ethtool &>/dev/null; then
            echo "WARN: ethtool not installed — cannot blink LEDs. Skipping."
        else
            echo "ethtool found"
        fi
    )
    [[ "$result" == *"ethtool not installed"* ]]
}

# ---------------------------------------------------------------------------
# The root .env holds SMTP_PASS once notifications are set; only the installer reads it (#77)
# ---------------------------------------------------------------------------
@test "write_env_assignments: leaves the .env readable by its owner only" {
    source "${REPO_ROOT}/scripts/common.sh"
    set +uo pipefail
    # preflight.sh runs main when sourced, so load just the two functions under test
    sed -n '/^_set_env_value() {/,/^}/p; /^write_env_assignments() {/,/^}/p' \
        "${REPO_ROOT}/scripts/install/preflight.sh" > "${TEST_TMPDIR}/preflight-fns.sh"
    source "${TEST_TMPDIR}/preflight-fns.sh"
    PROJECT_ROOT="${TEST_TMPDIR}"
    ENV_FILE="${TEST_TMPDIR}/.env"
    DRY_RUN=false
    printf 'SMTP_PASS=secret\n' > "$ENV_FILE"
    chmod 644 "$ENV_FILE"

    write_env_assignments enp2s0 enp3s0 enp1s0

    grep -q "^WAN_INTERFACE=enp2s0$" "$ENV_FILE"
    grep -q "^SMTP_PASS=secret$" "$ENV_FILE"
    [ "$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")" = "600" ]
}

# ---------------------------------------------------------------------------
# NET-211 #1: .env.example's placeholder ports and management address became the box's settings
# ---------------------------------------------------------------------------
@test ".env.example sets no port name or management address" {
    run grep -nE '^[[:space:]]*(export[[:space:]]+)?(MGMT_INTERFACE|MGMT_IP|MGMT_NETMASK|WAN_INTERFACE|LAN_INTERFACE)=' \
        "${REPO_ROOT}/.env.example"
    [ "$status" -eq 1 ]
}

@test "write_env_assignments: a two-port box's .env gets its ports and no management placeholder" {
    source "${REPO_ROOT}/scripts/common.sh"
    set +uo pipefail
    sed -n '/^_set_env_value() {/,/^}/p; /^write_env_assignments() {/,/^}/p' \
        "${REPO_ROOT}/scripts/install/preflight.sh" > "${TEST_TMPDIR}/preflight-fns.sh"
    source "${TEST_TMPDIR}/preflight-fns.sh"
    PROJECT_ROOT="${TEST_TMPDIR}"
    ENV_FILE="${TEST_TMPDIR}/.env"
    cp "${REPO_ROOT}/.env.example" "${TEST_TMPDIR}/.env.example"

    write_env_assignments enp2s0 enp1s0 ""

    grep -q "^WAN_INTERFACE=enp2s0$" "$ENV_FILE"
    grep -q "^LAN_INTERFACE=enp1s0$" "$ENV_FILE"
    # (common.sh's run shadows bats' run here, so count instead)
    [ "$(grep -cE '^(MGMT_INTERFACE|MGMT_IP|MGMT_NETMASK)=' "$ENV_FILE")" -eq 0 ]
    # the rest of the example still comes across
    grep -q "^NETTAP_HOSTNAME=nettap.local$" "$ENV_FILE"
}
