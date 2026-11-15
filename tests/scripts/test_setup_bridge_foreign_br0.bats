#!/usr/bin/env bats
# ==========================================================================
# NET-287: setup-bridge.sh never adopts or deletes a br0 NetTap didn't make
# ==========================================================================
# The script runs as a copy whose common.sh is a wrapper: the real common.sh, then
# helpers/bridge_stubs.bash (a logging ip with no real-ip fallback). run() and
# `set -euo pipefail` stay the script's own, so the non-dry-run cases are real runs.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

load 'helpers/setup'

NETPLAN_PORTS=$'network:\n  bridges:\n    br0:\n      interfaces:\n        - enp2s0\n        - enp3s0\n'

# _script NAME ARGS: run scripts/bridge/NAME with the stubbed common.sh
_script() {
    local name="$1" mock="${TEST_TMPDIR}/mock"
    shift
    mkdir -p "${mock}/bridge" "${TEST_TMPDIR}/sys/br0/brif"
    cat > "${mock}/common.sh" <<WRAPPER
source '${REPO_ROOT}/scripts/common.sh'
source '${BATS_TEST_DIRNAME}/helpers/bridge_stubs.bash'
WRAPPER
    sed "s|source \"\${SCRIPT_DIR}/../common.sh\"|source '${mock}/common.sh'|" \
        "${REPO_ROOT}/scripts/bridge/${name}" > "${mock}/bridge/${name}"
    run env TEST_TMPDIR="$TEST_TMPDIR" NETTAP_COLOR=never "${ENV_VARS[@]}" \
        bash "${mock}/bridge/${name}" "$@"
}

_bridge() { _script setup-bridge.sh --wan enp2s0 --lan enp3s0 "$@"; }

_make_br0() { touch "${TEST_TMPDIR}/br0-exists"; }
_ports() { local p; for p in "$@"; do mkdir -p "${TEST_TMPDIR}/sys/br0/brif/${p}"; done; }
_netplan() { printf '%s' "$NETPLAN_PORTS" > "${TEST_TMPDIR}/10-nettap-bridge.yaml"; }
_alias() { mkdir -p "${TEST_TMPDIR}/sys/br0"; echo nettap > "${TEST_TMPDIR}/sys/br0/ifalias"; }
_changes() { grep -E '^ip link (add|set|del)' "${TEST_TMPDIR}/ip.log" || true; }

ENV_VARS=()

# -- dry runs ---------------------------------------------------------------

@test "a br0 NetTap didn't make is refused, and nothing is retuned" {
    _make_br0; _ports vnet0
    _bridge --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"br0 already exists and NetTap didn't make it"* ]] || false
    [[ "$output" == *"sudo ip link set br0 alias nettap"* ]] || false
    [[ "$output" != *"type bridge stp_state"* ]] || false
}

@test "an empty br0 next to a matching netplan file is refused" {
    _make_br0; _netplan
    _bridge --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"didn't make it"* ]] || false
}

@test "a br0 carrying a host address is refused even when its port is in the file" {
    _make_br0; _netplan; _ports enp2s0
    ENV_VARS=(BR0_ADDR="3: br0    inet 192.168.1.5/24 scope global br0")
    _bridge --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"didn't make it"* ]] || false
}

@test "NetTap's own br0 (its alias) is reconfigured, marked first" {
    _make_br0; _alias
    _bridge --dry-run
    [ "$status" -eq 0 ]
    [[ "$output" == *"already exists, reconfiguring"* ]] || false
    [[ "$output" == *"[DRY-RUN] ip link set br0 alias nettap"* ]] || false
}

@test "a br0 netplan rebuilt from NetTap's file (ports listed, no address) is reconfigured" {
    _make_br0; _netplan; _ports enp2s0 enp3s0
    _bridge --dry-run
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] ip link set br0 alias nettap"* ]] || false
}

@test "a legacy br0 whose route reads print [ ] is reconfigured" {
    _make_br0; _netplan; _ports enp2s0 enp3s0
    ENV_VARS=(BR0_ROUTE4='[ ]' BR0_ROUTE6='[ ]')
    _bridge --dry-run
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] ip link set br0 alias nettap"* ]] || false
}

@test "a legacy br0 carrying an IPv6 default route is refused" {
    _make_br0; _netplan; _ports enp2s0 enp3s0
    ENV_VARS=(BR0_ROUTE6='[{"dst":"default","gateway":"fe80::1","dev":"br0"}]')
    _bridge --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"didn't make it"* ]] || false
}

@test "a legacy br0 whose route read fails is refused" {
    _make_br0; _netplan; _ports enp2s0 enp3s0
    ENV_VARS=(ROUTE_FAILS=1)
    _bridge --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"didn't make it"* ]] || false
}

@test "a netplan port line with trailing whitespace still counts (as in the daemon)" {
    _make_br0; _ports enp2s0 enp3s0
    printf 'network:\n  bridges:\n    br0:\n      interfaces:\n        - enp2s0 \n        - enp3s0\t\n' \
        > "${TEST_TMPDIR}/10-nettap-bridge.yaml"
    _bridge --dry-run
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] ip link set br0 alias nettap"* ]] || false
}

@test "--teardown refuses a br0 NetTap didn't make" {
    _make_br0; _ports vnet0
    _bridge --teardown --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"won't touch it or its ports"* ]] || false
    [[ "$output" == *"sudo ip link set br0 alias nettap"* ]] || false
    [[ "$output" != *"ip link del br0"* ]] || false
}

@test "--teardown deletes NetTap's br0 and releases only its own ports" {
    _make_br0; _alias
    mkdir -p "${TEST_TMPDIR}/sys/enp2s0" "${TEST_TMPDIR}/sys/enp3s0"
    ln -s ../br0 "${TEST_TMPDIR}/sys/enp2s0/master"
    _bridge --teardown --dry-run
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] ip link set enp2s0 nomaster"* ]] || false
    [[ "$output" != *"enp3s0 nomaster"* ]] || false
    [[ "$output" == *"[DRY-RUN] ip link del br0"* ]] || false
}

# -- real runs (stubbed host) -----------------------------------------------

@test "a br0 that appears after preflight is refused where it would be adopted" {
    ENV_VARS=(BR0_APPEARS_AFTER=1)
    _bridge
    [ "$status" -ne 0 ]
    [[ "$output" == *"didn't make it"* ]] || false
    [ "$(grep -c '^ip link show br0$' "${TEST_TMPDIR}/ip.log")" -ge 3 ]
    [ -z "$(_changes)" ]
}

@test "if the alias fails, only the bridge this run made is deleted" {
    ENV_VARS=(ALIAS_FAILS=1)
    _bridge
    [ "$status" -ne 0 ]
    [[ "$output" == *"Could not mark br0 as NetTap's bridge"* ]] || false
    [ "$(_changes)" = $'ip link add name br0 type bridge\nip link set br0 alias nettap\nip link del br0' ]
}

@test "if the alias fails and the cleanup fails too, it says the bridge may remain" {
    ENV_VARS=(ALIAS_FAILS=1 DEL_FAILS=1)
    _bridge
    [ "$status" -ne 0 ]
    [[ "$output" == *"sudo ip link del br0"* ]] || false
    [[ "$output" != *"nothing else was changed"* ]] || false
}

# -- the other bridge scripts -----------------------------------------------

@test "harden-bridge.sh refuses a br0 NetTap didn't make" {
    _make_br0; _ports vnet0
    _script harden-bridge.sh --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"didn't make it"* ]] || false
    [[ "$output" != *"stp_state"* ]] || false
}

@test "bypass-mode.sh refuses a br0 NetTap didn't make" {
    _make_br0; _ports vnet0
    _script bypass-mode.sh --enable --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"didn't make it"* ]] || false
    [[ "$output" != *"promisc"* ]] || false
}
