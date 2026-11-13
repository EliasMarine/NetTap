#!/usr/bin/env bats
# ==========================================================================
# NET-211 #8: setup-bridge.sh --persist --dry-run writes nothing and loads no module
# ==========================================================================
# The script runs at the top level, so it runs as a copy whose common.sh is a wrapper that loads
# the real one and then the mocks (same pattern as test_preflight.bats). modprobe is a PATH stub
# that records its calls.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

load 'helpers/setup'

_dry_run_bridge() {
    local mock="${TEST_TMPDIR}/mock" bin="${TEST_TMPDIR}/bin"
    mkdir -p "${mock}/bridge" "$bin"
    cat > "${mock}/common.sh" <<WRAPPER
source '${REPO_ROOT}/scripts/common.sh'
source '${BATS_TEST_DIRNAME}/helpers/mocks.bash'
WRAPPER
    sed "s|source \"\${SCRIPT_DIR}/../common.sh\"|source '${mock}/common.sh'|" \
        "${REPO_ROOT}/scripts/bridge/setup-bridge.sh" > "${mock}/bridge/setup-bridge.sh"
    printf '#!/usr/bin/env bash\necho "modprobe $*" >> "%s/modprobe.log"\n' "$TEST_TMPDIR" > "${bin}/modprobe"
    chmod +x "${bin}/modprobe"
    run env PATH="${bin}:$PATH" TEST_TMPDIR="$TEST_TMPDIR" NETTAP_COLOR=never "$@" \
        bash "${mock}/bridge/setup-bridge.sh" --wan enp2s0 --lan enp3s0 --persist --dry-run
}

@test "setup-bridge --persist --dry-run names every boot file and writes none" {
    _dry_run_bridge
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] write /etc/netplan/10-nettap-bridge.yaml"* ]] || false
    [[ "$output" == *"[DRY-RUN] write /etc/sysctl.d/99-nettap-bridge.conf"* ]] || false
    [[ "$output" == *"[DRY-RUN] write /etc/systemd/system/nettap-bridge.service"* ]] || false
    [[ "$output" == *"[DRY-RUN] chmod 600 /etc/netplan/10-nettap-bridge.yaml"* ]] || false
}

@test "setup-bridge --dry-run loads no kernel module" {
    _dry_run_bridge
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] modprobe bridge"* ]] || false
    [ ! -e "${TEST_TMPDIR}/modprobe.log" ]
}

@test "setup-bridge --dry-run with a fixed management address writes no netplan either" {
    _dry_run_bridge MGMT_INTERFACE=enp1s0 MGMT_IP=192.0.2.10
    [ "$status" -eq 0 ]
    [[ "$output" == *"[DRY-RUN] write /etc/netplan/10-nettap-bridge.yaml"* ]] || false
    [[ "$(grep -c 'write /etc/netplan/10-nettap-bridge.yaml' <<< "$output")" -eq 2 ]] || false
}
