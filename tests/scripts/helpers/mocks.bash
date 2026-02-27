#!/usr/bin/env bash
# ==========================================================================
# BATS test helper — mocks for NetTap script tests
# ==========================================================================
# Provides mock functions that override system commands so tests run
# without root, physical NICs, or real hardware.

# ---------------------------------------------------------------------------
# Mock: list_physical_nics — returns configurable NIC list
# ---------------------------------------------------------------------------
# Set MOCK_NICS as a newline-separated list before sourcing, e.g.:
#   MOCK_NICS=$'enp1s0\nenp2s0\nenp3s0'
MOCK_NICS="${MOCK_NICS:-enp1s0
enp2s0
enp3s0}"

list_physical_nics() {
    echo "$MOCK_NICS"
}
export -f list_physical_nics

# ---------------------------------------------------------------------------
# Mock: get_nic_driver
# ---------------------------------------------------------------------------
get_nic_driver() {
    echo "igc"
}
export -f get_nic_driver

# ---------------------------------------------------------------------------
# Mock: get_nic_speed
# ---------------------------------------------------------------------------
get_nic_speed() {
    echo "2500Mb/s"
}
export -f get_nic_speed

# ---------------------------------------------------------------------------
# Mock: get_nic_mac
# ---------------------------------------------------------------------------
# Returns deterministic MAC based on interface name
get_nic_mac() {
    local iface="$1"
    case "$iface" in
        enp1s0) echo "aa:bb:cc:dd:ee:01" ;;
        enp2s0) echo "aa:bb:cc:dd:ee:02" ;;
        enp3s0) echo "aa:bb:cc:dd:ee:03" ;;
        *)      echo "00:00:00:00:00:00" ;;
    esac
}
export -f get_nic_mac

# ---------------------------------------------------------------------------
# Mock: nic_has_carrier
# ---------------------------------------------------------------------------
# By default, only enp1s0 has carrier (simulates internet NIC).
# Override MOCK_CARRIER_NICS to change.
MOCK_CARRIER_NICS="${MOCK_CARRIER_NICS:-enp1s0}"

nic_has_carrier() {
    local iface="$1"
    echo "$MOCK_CARRIER_NICS" | grep -qw "$iface"
}
export -f nic_has_carrier

# ---------------------------------------------------------------------------
# Mock: ip command
# ---------------------------------------------------------------------------
# Provides mock `ip route show default` output.
MOCK_DEFAULT_ROUTE_NIC="${MOCK_DEFAULT_ROUTE_NIC:-enp1s0}"

ip() {
    if [[ "${1:-}" == "route" && "${2:-}" == "show" && "${3:-}" == "default" ]]; then
        if [[ -n "$MOCK_DEFAULT_ROUTE_NIC" ]]; then
            echo "default via 192.168.1.1 dev ${MOCK_DEFAULT_ROUTE_NIC} proto dhcp metric 100"
        fi
        return 0
    fi
    if [[ "${1:-}" == "link" && "${2:-}" == "show" ]]; then
        # Simulate interface exists
        return 0
    fi
    # Fall through to real ip for other subcommands
    command ip "$@"
}
export -f ip

# ---------------------------------------------------------------------------
# Mock: ethtool
# ---------------------------------------------------------------------------
MOCK_ETHTOOL_AVAILABLE="${MOCK_ETHTOOL_AVAILABLE:-true}"
MOCK_ETHTOOL_CALLS=()

ethtool() {
    if [[ "$MOCK_ETHTOOL_AVAILABLE" != "true" ]]; then
        return 127
    fi
    # Record the call for assertions
    echo "ethtool $*" >> "${TEST_TMPDIR}/ethtool_calls.log"
    return 0
}
export -f ethtool

# ---------------------------------------------------------------------------
# Mock: require_root — skip root check in tests
# ---------------------------------------------------------------------------
require_root() {
    return 0
}
export -f require_root

# ---------------------------------------------------------------------------
# Mock: check_interface_exists — always succeeds
# ---------------------------------------------------------------------------
check_interface_exists() {
    return 0
}
export -f check_interface_exists

# ---------------------------------------------------------------------------
# Mock: docker
# ---------------------------------------------------------------------------
MOCK_DOCKER_COMPOSE_CONTAINERS="${MOCK_DOCKER_COMPOSE_CONTAINERS:-3}"

docker() {
    if [[ "${1:-}" == "compose" ]]; then
        if [[ "${*}" == *"ps -q"* ]]; then
            local i
            for (( i=1; i<=MOCK_DOCKER_COMPOSE_CONTAINERS; i++ )); do
                echo "container${i}"
            done
            return 0
        fi
        if [[ "${*}" == *"up -d"* ]]; then
            echo "docker compose up -d" >> "${TEST_TMPDIR}/docker_calls.log"
            return 0
        fi
    fi
    return 0
}
export -f docker

# ---------------------------------------------------------------------------
# Mock: curl — for OpenSearch health check
# ---------------------------------------------------------------------------
curl() {
    if [[ "${*}" == *"9200/_cluster/health"* ]]; then
        echo '{"status":"green"}'
        return 0
    fi
    command curl "$@"
}
export -f curl

# ---------------------------------------------------------------------------
# Mock: systemctl — no-op
# ---------------------------------------------------------------------------
systemctl() {
    return 0
}
export -f systemctl

# ---------------------------------------------------------------------------
# Mock: sysctl — no-op
# ---------------------------------------------------------------------------
sysctl() {
    if [[ "${1:-}" == "-n" ]]; then
        echo "262144"
        return 0
    fi
    return 0
}
export -f sysctl

# ---------------------------------------------------------------------------
# Mock: setup-bridge.sh — record calls
# ---------------------------------------------------------------------------
# Tests that need to verify setup-bridge.sh is called correctly should
# create a mock script at ${TEST_TMPDIR}/mock-setup-bridge.sh
