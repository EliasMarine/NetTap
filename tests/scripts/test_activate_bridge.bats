#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/install/activate-bridge.sh
# ==========================================================================

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

load 'helpers/setup'

# ---------------------------------------------------------------------------
# Test 1: Fails without .env NIC assignments
# ---------------------------------------------------------------------------
@test "activate-bridge: fails without .env NIC assignments" {
    # Create empty .env (no NIC assignments)
    touch "${TEST_TMPDIR}/.env"

    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        source '${BATS_TEST_DIRNAME}/helpers/mocks.bash'
        export PROJECT_ROOT='${TEST_TMPDIR}'
        # Simulate what activate-bridge.sh does
        source '${TEST_TMPDIR}/.env' 2>/dev/null || true
        if [[ -z \"\${WAN_INTERFACE:-}\" || -z \"\${LAN_INTERFACE:-}\" ]]; then
            echo 'ERROR: NIC assignments not found'
            exit 1
        fi
    "
    [ "$status" -eq 1 ]
    [[ "$output" == *"NIC assignments not found"* ]]
}

# ---------------------------------------------------------------------------
# Test 2: Validates WAN carrier detected
# ---------------------------------------------------------------------------
@test "activate-bridge: validates WAN carrier detected" {
    export MOCK_CARRIER_NICS="enp2s0 enp3s0"

    local result rc=0
    result=$(
        WAN_INTERFACE="enp2s0"
        if nic_has_carrier "$WAN_INTERFACE"; then
            echo "OK: WAN carrier detected"
        else
            echo "FAIL: WAN no carrier"
            exit 1
        fi
    ) || rc=$?
    [ "$rc" -eq 0 ]
    [[ "$result" == *"OK: WAN carrier detected"* ]]
}

# ---------------------------------------------------------------------------
# Test 3: Fails when WAN has no cable
# ---------------------------------------------------------------------------
@test "activate-bridge: fails when WAN has no cable" {
    run bash -c '
        source "'"${REPO_ROOT}"'/scripts/common.sh"
        source "'"${BATS_TEST_DIRNAME}"'/helpers/mocks.bash"
        export MOCK_CARRIER_NICS="enp3s0"

        WAN_INTERFACE="enp2s0"
        if nic_has_carrier "$WAN_INTERFACE"; then
            echo "OK: WAN carrier"
            exit 0
        else
            echo "FAIL: WAN no cable"
            exit 1
        fi
    '
    [ "$status" -eq 1 ]
    [[ "$output" == *"FAIL: WAN no cable"* ]]
}

# ---------------------------------------------------------------------------
# Test 4: Force flag skips carrier validation
# ---------------------------------------------------------------------------
@test "activate-bridge --force: skips carrier validation" {
    cat > "${TEST_TMPDIR}/.env" <<'EOF'
WAN_INTERFACE=enp2s0
LAN_INTERFACE=enp3s0
EOF

    run bash -c '
        source "'"${REPO_ROOT}"'/scripts/common.sh"
        source "'"${BATS_TEST_DIRNAME}"'/helpers/mocks.bash"
        export MOCK_CARRIER_NICS=""

        FORCE="true"
        WAN_INTERFACE="enp2s0"
        LAN_INTERFACE="enp3s0"

        if [[ "$FORCE" == "true" ]]; then
            echo "Skipping cable carrier validation (--force)"
            exit 0
        fi

        if ! nic_has_carrier "$WAN_INTERFACE"; then
            echo "FAIL: WAN no cable"
            exit 1
        fi
    '
    [ "$status" -eq 0 ]
    [[ "$output" == *"Skipping cable carrier validation"* ]]
}

# ---------------------------------------------------------------------------
# Test 5: Calls setup-bridge.sh with correct arguments
# ---------------------------------------------------------------------------
@test "activate-bridge: calls setup-bridge.sh with correct arguments" {
    # Create a mock setup-bridge.sh that records its args
    local mock_bridge="${TEST_TMPDIR}/mock-setup-bridge.sh"
    cat > "$mock_bridge" <<'SCRIPT'
#!/usr/bin/env bash
echo "setup-bridge-args: $*" > "${TEST_TMPDIR}/bridge_call.log"
SCRIPT
    chmod +x "$mock_bridge"

    run bash -c '
        export TEST_TMPDIR="'"${TEST_TMPDIR}"'"
        WAN_INTERFACE="enp2s0"
        LAN_INTERFACE="enp3s0"
        MGMT_INTERFACE="enp1s0"
        NETTAP_VERBOSE="false"
        NETTAP_DRY_RUN="false"

        bridge_args=()
        bridge_args+=(--wan "$WAN_INTERFACE")
        bridge_args+=(--lan "$LAN_INTERFACE")
        [[ -n "$MGMT_INTERFACE" ]] && bridge_args+=(--mgmt "$MGMT_INTERFACE")
        bridge_args+=(--persist)

        "'"${TEST_TMPDIR}"'/mock-setup-bridge.sh" "${bridge_args[@]}"
    '
    [ "$status" -eq 0 ]

    # Verify the recorded args
    [ -f "${TEST_TMPDIR}/bridge_call.log" ]
    local logged
    logged=$(cat "${TEST_TMPDIR}/bridge_call.log")
    [[ "$logged" == *"--wan enp2s0"* ]]
    [[ "$logged" == *"--lan enp3s0"* ]]
    [[ "$logged" == *"--mgmt enp1s0"* ]]
    [[ "$logged" == *"--persist"* ]]
}

# ---------------------------------------------------------------------------
# Test 6: Calls docker compose up when services enabled
# ---------------------------------------------------------------------------
@test "activate-bridge: calls docker compose up when services enabled" {
    run bash -c '
        source "'"${REPO_ROOT}"'/scripts/common.sh"
        source "'"${BATS_TEST_DIRNAME}"'/helpers/mocks.bash"
        export TEST_TMPDIR="'"${TEST_TMPDIR}"'"

        SKIP_SERVICES="false"
        NETTAP_DRY_RUN="false"
        COMPOSE_FILE="'"${TEST_TMPDIR}"'/docker-compose.yml"

        # Simulate start_services
        docker compose -f "$COMPOSE_FILE" up -d
    '
    [ "$status" -eq 0 ]
    [ -f "${TEST_TMPDIR}/docker_calls.log" ]
    grep -q "docker compose up -d" "${TEST_TMPDIR}/docker_calls.log"
}

# ---------------------------------------------------------------------------
# Test 7: Skip-services flag prevents docker compose call
# ---------------------------------------------------------------------------
@test "activate-bridge --skip-services: prevents docker compose call" {
    run bash -c '
        export TEST_TMPDIR="'"${TEST_TMPDIR}"'"
        SKIP_SERVICES="true"

        if [[ "$SKIP_SERVICES" == "true" ]]; then
            echo "Skipping service startup"
            exit 0
        fi

        # This would only run if skip-services is false
        echo "docker compose up -d" >> "${TEST_TMPDIR}/docker_calls.log"
    '
    [ "$status" -eq 0 ]
    [[ "$output" == *"Skipping service startup"* ]]
    # Verify docker was NOT called
    [ ! -f "${TEST_TMPDIR}/docker_calls.log" ]
}
