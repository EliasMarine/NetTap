#!/usr/bin/env bash
# ==========================================================================
# NET-287: stateful host stubs for setup-bridge.sh ownership tests
# ==========================================================================
# Sourced by the test wrapper after the real common.sh, so the script keeps its real run()
# and shell options. Every ip call is logged to $TEST_TMPDIR/ip.log; none reaches the real ip.
#   br0 exists:   $TEST_TMPDIR/br0-exists, or after BR0_APPEARS_AFTER `ip link show br0` calls
#   br0 owned:    $TEST_TMPDIR/sys/br0/ifalias, brif/, and $TEST_TMPDIR/10-nettap-bridge.yaml
#   BR0_ADDR:     what `ip -o addr show dev br0 scope global` prints
#   ALIAS_FAILS:  non-empty makes `ip link set br0 alias nettap` fail
#   BR0_ROUTE4/6: what `ip -j -4|-6 route show default dev br0` prints (default: nothing)
#   ROUTE_FAILS:  non-empty makes those route reads fail
#   DEL_FAILS:    non-empty makes `ip link del br0` fail

# shellcheck disable=SC2034  # read by nettap_bridge_owned in the real common.sh
NETTAP_SYS_NET="${TEST_TMPDIR}/sys"
# shellcheck disable=SC2034
NETTAP_BRIDGE_NETPLAN="${TEST_TMPDIR}/10-nettap-bridge.yaml"

require_root() { :; }
modprobe() { :; }
sysctl() { :; }
ethtool() { :; }
systemctl() { return 1; }

_br0_exists() {
    local n
    n=$(( $(cat "${TEST_TMPDIR}/br0-shows" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "${TEST_TMPDIR}/br0-shows"
    [[ -e "${TEST_TMPDIR}/br0-exists" ]] || (( n > ${BR0_APPEARS_AFTER:-999999} ))
}

_route() { [[ -z "${ROUTE_FAILS:-}" ]] || return 1; printf '%s' "$1"; }

ip() {
    echo "ip $*" >> "${TEST_TMPDIR}/ip.log"
    case "$*" in
        "link show br0") _br0_exists ;;
        "link add name br0 type bridge") touch "${TEST_TMPDIR}/br0-exists" ;;
        "link set br0 alias nettap") [[ -z "${ALIAS_FAILS:-}" ]] ;;
        "link del br0") [[ -z "${DEL_FAILS:-}" ]] && rm -f "${TEST_TMPDIR}/br0-exists" ;;
        "-o addr show dev br0 scope global") printf '%s' "${BR0_ADDR:-}" ;;
        "-j -4 route show default dev br0") _route "${BR0_ROUTE4:-}" ;;
        "-j -6 route show default dev br0") _route "${BR0_ROUTE6:-}" ;;
        *) return 0 ;;
    esac
}
