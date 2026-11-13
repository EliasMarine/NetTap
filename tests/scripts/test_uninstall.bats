#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/install/uninstall.sh (NET-211 #11)
# ==========================================================================
# The script runs as a copy whose common.sh loads the real one and skips the root check.
# UNINSTALL_ROOT points every system path at a temp dir. docker, systemctl and curl are PATH stubs
# that log their calls to $TEST_TMPDIR/calls; curl also keeps its stdin.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

load 'helpers/setup'

TOKEN="SECRET-TOKEN-123"

_stub() {  # $1 = name, $2 = body after the call log
    printf '#!/usr/bin/env bash\necho "%s $*" >> "$TEST_TMPDIR/calls"\n%s\n' "$1" "$2" > "${TEST_TMPDIR}/bin/$1"
    chmod +x "${TEST_TMPDIR}/bin/$1"
}

_harness() {
    R="${TEST_TMPDIR}/root"
    MOCK="${TEST_TMPDIR}/mock"
    mkdir -p "$R/etc/systemd/system/multi-user.target.wants" "$R/etc/netplan" "$R/etc/sysctl.d" \
        "$R/etc/docker" "$R/etc/nettap" "$MOCK/scripts/install" "$MOCK/docker" "${TEST_TMPDIR}/bin"
    printf "source '%s/scripts/common.sh'\nrequire_root() { :; }\n" "$REPO_ROOT" > "$MOCK/scripts/common.sh"
    cp "$REPO_ROOT/scripts/install/uninstall.sh" "$MOCK/scripts/install/"
    touch "$MOCK/docker/docker-compose.yml"
    # DIE_AT: the systemctl call that kills uninstall.sh, as a power cut or Ctrl-C would
    _stub systemctl 'if [ -n "${DIE_AT:-}" ] && [ "$*" = "$DIE_AT" ]; then kill -KILL "$PPID"; fi'
    _stub docker "case \"\$1\" in exec) echo '${TOKEN}' ;; compose) exit \"\${DOCKER_COMPOSE_RC:-0}\" ;; esac"
    _stub curl 'cat > "$TEST_TMPDIR/curl-stdin"
[ "${CURL_RC:-0}" -eq 0 ] || exit "$CURL_RC"
if [ -n "${CURL_REPLY:-}" ]; then echo "$CURL_REPLY"; else echo "{\"other_dhcp_servers\": []}"; fi'
}

_unit() {  # $1 = unit name: unit file + the wants link systemctl enable makes
    echo "[Unit]" > "$R/etc/systemd/system/$1"
    ln -s "/etc/systemd/system/$1" "$R/etc/systemd/system/multi-user.target.wants/$1"
}

# What the G11 has (mirror mode): two units, the mirror netplan, the installer's sysctl file,
# and a daemon.json NetTap created
_mirror_box() {
    _unit nettap.service
    _unit nettap-mirror.service
    echo "network: {}" > "$R/etc/netplan/10-nettap-mirror-enp4s0.yaml"
    echo "vm.max_map_count = 262144" > "$R/etc/sysctl.d/99-nettap.conf"
    echo '{"dns": ["9.9.9.9"]}' > "$R/etc/docker/daemon.json"
    cp "$R/etc/docker/daemon.json" "$R/etc/docker/daemon.json.nettap-installed"
    echo "PCAP_IFACE=enp4s0" > "$R/etc/nettap/capture.env"
    # not NetTap's: must survive
    echo "network: {}" > "$R/etc/netplan/50-cloud-init.yaml"
    echo "x = 1" > "$R/etc/sysctl.d/10-other.conf"
    echo "[Unit]" > "$R/etc/systemd/system/other.service"
}

_uninstall() {  # args go to uninstall.sh; stdin is the test's
    run env PATH="${TEST_TMPDIR}/bin:$PATH" UNINSTALL_ROOT="$R" NETTAP_COLOR=never \
        bash "$MOCK/scripts/install/uninstall.sh" "$@"
}

_calls() { if [ -f "${TEST_TMPDIR}/calls" ]; then cat "${TEST_TMPDIR}/calls"; fi; }

# The installer's own daemon.json step, on the test file
_install_daemon_json() {
    bash -c "source '$REPO_ROOT/scripts/install/install.sh'; NETTAP_UI=plain; configure_docker_daemon '$R/etc/docker/daemon.json'" >/dev/null 2>&1 || true
}

_mirror_box_intact() {
    [ -e "$R/etc/systemd/system/nettap.service" ]
    [ -L "$R/etc/systemd/system/multi-user.target.wants/nettap-mirror.service" ]
    [ -e "$R/etc/netplan/10-nettap-mirror-enp4s0.yaml" ]
    [ -e "$R/etc/sysctl.d/99-nettap.conf" ]
    [ -e "$R/etc/docker/daemon.json" ]
    [ -e "$R/etc/nettap/capture.env" ]
}

setup() {
    TEST_TMPDIR="$(mktemp -d)"
    export TEST_TMPDIR
    _harness
}

@test "uninstall --dry-run lists what would go, asks nothing and changes nothing" {
    _mirror_box
    _uninstall --dry-run < /dev/null
    [ "$status" -eq 0 ]
    [[ "$output" == *"systemd unit nettap.service"* ]] || false
    [[ "$output" == *"systemd unit nettap-mirror.service"* ]] || false
    [[ "$output" == *" - /etc/netplan/10-nettap-mirror-enp4s0.yaml"* ]] || false
    [[ "$output" == *" - /etc/sysctl.d/99-nettap.conf"* ]] || false
    [[ "$output" == *"/etc/docker/daemon.json (NetTap created it)"* ]] || false
    [[ "$output" == *"Dry run: nothing was changed."* ]] || false
    [[ "$output" != *"50-cloud-init"* ]] || false
    _mirror_box_intact
    [ -z "$(_calls)" ]
}

@test "uninstall --yes removes NetTap's units, links and files, then stops the containers" {
    _mirror_box
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ ! -e "$R/etc/systemd/system/nettap.service" ]
    [ ! -e "$R/etc/systemd/system/nettap-mirror.service" ]
    [ ! -L "$R/etc/systemd/system/multi-user.target.wants/nettap.service" ]
    [ ! -L "$R/etc/systemd/system/multi-user.target.wants/nettap-mirror.service" ]
    [ ! -e "$R/etc/netplan/10-nettap-mirror-enp4s0.yaml" ]
    [ ! -e "$R/etc/sysctl.d/99-nettap.conf" ]
    # NetTap created daemon.json: it goes, with its record
    [ ! -e "$R/etc/docker/daemon.json" ]
    [ ! -e "$R/etc/docker/daemon.json.nettap-installed" ]
    # not NetTap's, and the settings without --purge-data
    [ -e "$R/etc/netplan/50-cloud-init.yaml" ]
    [ -e "$R/etc/sysctl.d/10-other.conf" ]
    [ -e "$R/etc/systemd/system/other.service" ]
    [ -e "$R/etc/nettap/capture.env" ]
    _calls | grep -qx "systemctl disable --now nettap.service"
    _calls | grep -qx "systemctl disable --now nettap-mirror.service"
    _calls | grep -qx "docker compose -f $MOCK/docker/docker-compose.yml --profile arkime --profile grafana down --remove-orphans"
    _calls | grep -qx "systemctl daemon-reload"
    # units first: stopping nettap-bypass.service would start the containers again
    [ "$(_calls | grep -n 'disable --now nettap-mirror' | cut -d: -f1)" -lt "$(_calls | grep -n 'compose' | cut -d: -f1)" ]
    [[ "$output" == *"Reboot to finish: sudo reboot"* ]] || false
    [[ "$output" == *"/etc/nettap and NetTap's Docker volumes"* ]] || false
    [[ "$output" != *"plug the modem straight into the router"* ]] || false
}

@test "uninstall: no, or no answer at all, changes nothing" {
    _mirror_box
    _uninstall <<< "n"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Nothing was changed."* ]] || false
    _uninstall < /dev/null
    [ "$status" -eq 1 ]
    _mirror_box_intact
    [ -z "$(_calls)" ]
    _uninstall <<< "y"
    [ "$status" -eq 0 ]
    [ ! -e "$R/etc/systemd/system/nettap.service" ]
}

@test "uninstall refuses while the bridge netplan also holds a fixed management address" {
    _unit nettap-bridge.service
    cat > "$R/etc/netplan/10-nettap-bridge.yaml" <<'EOF'
network:
  version: 2
  renderer: networkd
  ethernets:
    enp2s0:
      dhcp4: false
    enp3s0:
      dhcp4: false
    enp1s0:
      dhcp4: false
      addresses:
        - 192.0.2.10/24
  bridges:
    br0:
      interfaces:
        - enp2s0
        - enp3s0
EOF
    for args in --yes --dry-run; do
        _uninstall "$args" < /dev/null
        [ "$status" -eq 1 ]
        [[ "$output" == *"also gives enp1s0 its fixed address"* ]] || false
        [[ "$output" == *"Nothing was changed."* ]] || false
    done
    [ -e "$R/etc/netplan/10-nettap-bridge.yaml" ]
    [ -e "$R/etc/systemd/system/nettap-bridge.service" ]
    [ -z "$(_calls)" ]
}

@test "uninstall refuses a bridge netplan it can't read (a dry run without sudo)" {
    printf 'network: {}\n' > "$R/etc/netplan/10-nettap-bridge.yaml"
    chmod 000 "$R/etc/netplan/10-nettap-bridge.yaml"
    if [ -r "$R/etc/netplan/10-nettap-bridge.yaml" ]; then skip "running as root"; fi
    _uninstall --dry-run < /dev/null
    [ "$status" -eq 1 ]
    [[ "$output" == *"Can't read /etc/netplan/10-nettap-bridge.yaml to check it. Run this with sudo."* ]] || false
}

@test "uninstall in bridge mode says to re-cable before the reboot" {
    _unit nettap-bridge.service
    printf 'network:\n  bridges:\n    br0:\n      interfaces: [enp2s0, enp3s0]\n' > "$R/etc/netplan/10-nettap-bridge.yaml"
    echo "x" > "$R/etc/sysctl.d/99-nettap-bridge.conf"
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ ! -e "$R/etc/netplan/10-nettap-bridge.yaml" ]
    [ ! -e "$R/etc/sysctl.d/99-nettap-bridge.conf" ]
    [[ "$output" == *"plug the modem straight into the router before you reboot"* ]] || false
}

@test "uninstall in DHCP gateway mode refuses unless another DHCP server answers" {
    _unit nettap-dhcp-gateway.service
    # the daemon finds no other server
    _uninstall --yes < /dev/null
    [ "$status" -eq 1 ]
    [[ "$output" == *"NetTap is this network's DHCP server"* ]] || false
    # the daemon can't be asked
    CURL_RC=7 _uninstall --dry-run < /dev/null
    [ "$status" -eq 1 ]
    [[ "$output" == *"its daemon couldn't be asked"* ]] || false
    [[ "$output" == *"Nothing was changed."* ]] || false
    [ -e "$R/etc/systemd/system/nettap-dhcp-gateway.service" ]
    [ "$(_calls | grep -c -e systemctl -e compose)" -eq 0 ]
    # the router's server answers: go ahead
    export CURL_REPLY='{"other_dhcp_servers": ["192.0.2.1"]}'
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [[ "$output" == *"Another DHCP server answers"* ]] || false
    [ ! -e "$R/etc/systemd/system/nettap-dhcp-gateway.service" ]
}

@test "uninstall sends the daemon token to curl on stdin only, never in arguments or output" {
    _unit nettap-dhcp-gateway.service
    CURL_REPLY='{"other_dhcp_servers": ["192.0.2.1"]}' _uninstall --dry-run < /dev/null
    [ "$status" -eq 0 ]
    [ "$(cat "${TEST_TMPDIR}/curl-stdin")" = "X-NetTap-Daemon-Token: ${TOKEN}" ]
    _calls | grep -q "^curl .* -H @- http://127.0.0.1:8880/api/capture/dhcp/preflight$"
    [ "$(_calls | grep -c "$TOKEN")" -eq 0 ]
    [[ "$output" != *"$TOKEN"* ]] || false
}

@test "uninstall puts back the owner's daemon.json NetTap added dns to" {
    printf '{"data-root": "/srv/docker"}\n' > "$R/etc/docker/daemon.json"
    _install_daemon_json
    [ -e "$R/etc/docker/daemon.json.nettap-backup" ]
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ "$(cat "$R/etc/docker/daemon.json")" = '{"data-root": "/srv/docker"}' ]
    [ ! -e "$R/etc/docker/daemon.json.nettap-installed" ]
    [ ! -e "$R/etc/docker/daemon.json.nettap-backup" ]
    # a second run doesn't call the owner's own file an older NetTap's
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [[ "$output" != *"daemon.json"* ]] || false
}

@test "uninstall restores the owner's latest daemon.json after a reinstall, not the first one" {
    printf '{"a": 1}\n' > "$R/etc/docker/daemon.json"
    _install_daemon_json
    printf '{"b": 2}\n' > "$R/etc/docker/daemon.json"   # the owner's new file, no dns
    _install_daemon_json
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ "$(cat "$R/etc/docker/daemon.json")" = '{"b": 2}' ]
}

@test "uninstall removes a daemon.json NetTap created again after the owner deleted it" {
    printf '{"a": 1}\n' > "$R/etc/docker/daemon.json"
    _install_daemon_json
    rm "$R/etc/docker/daemon.json"
    _install_daemon_json
    [ ! -e "$R/etc/docker/daemon.json.nettap-backup" ]
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ ! -e "$R/etc/docker/daemon.json" ]
}

@test "uninstall leaves a daemon.json changed since, or with no record, and says so" {
    _install_daemon_json
    printf '{"dns": ["192.0.2.53"]}\n' > "$R/etc/docker/daemon.json"
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ "$(cat "$R/etc/docker/daemon.json")" = '{"dns": ["192.0.2.53"]}' ]
    [ -e "$R/etc/docker/daemon.json.nettap-installed" ]
    [[ "$output" == *"it changed after NetTap wrote it"* ]] || false
    # no record, NetTap's DNS servers in it: an older NetTap may have written it
    rm "$R/etc/docker/daemon.json.nettap-installed"
    printf '{"dns": ["9.9.9.9", "149.112.112.112"]}\n' > "$R/etc/docker/daemon.json"
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ "$(cat "$R/etc/docker/daemon.json")" = '{"dns": ["9.9.9.9", "149.112.112.112"]}' ]
    [[ "$output" == *"no record of what NetTap wrote"* ]] || false
}

@test "uninstall in DHCP gateway mode can run again after being cut short" {
    _unit nettap-dhcp-gateway.service
    _unit nettap.service
    echo "network: {}" > "$R/etc/netplan/90-nettap-dhcp-gateway.yaml"
    # the router answers; the run dies while stopping nettap.service, which stops the daemon
    CURL_REPLY='{"other_dhcp_servers": ["192.0.2.1"]}' DIE_AT="disable --now nettap.service" _uninstall --yes < /dev/null
    [ "$status" -ne 0 ]
    [ ! -e "$R/etc/netplan/90-nettap-dhcp-gateway.yaml" ]
    [ ! -e "$R/etc/systemd/system/nettap-dhcp-gateway.service" ]
    # the daemon can't be asked now, and nothing needs it: the next run finishes
    CURL_RC=7 _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ ! -e "$R/etc/systemd/system/nettap.service" ]
    [[ "$output" != *"DHCP server"* ]] || false
}

@test "uninstall --purge-data asks for 'delete' every time, even with --yes" {
    _mirror_box
    _uninstall --yes --purge-data <<< "yes"
    [ "$status" -eq 1 ]
    _mirror_box_intact
    [ -z "$(_calls)" ]
    # a dry run asks nothing and erases nothing
    _uninstall --dry-run --purge-data < /dev/null
    [ "$status" -eq 0 ]
    [[ "$output" == *"ALL captured data"* ]] || false
    [ -e "$R/etc/nettap/capture.env" ]
    _uninstall --purge-data <<< $'y\ndelete'
    [ "$status" -eq 0 ]
    [ ! -e "$R/etc/nettap" ]
    _calls | grep -qx "docker compose -f $MOCK/docker/docker-compose.yml --profile arkime --profile grafana down --remove-orphans -v"
    [[ "$output" != *"run again with --purge-data"* ]] || false
}

@test "uninstall removes the files when docker compose down fails, then exits 1" {
    _mirror_box
    DOCKER_COMPOSE_RC=1 _uninstall --yes < /dev/null
    [ "$status" -eq 1 ]
    [[ "$output" == *"Couldn't stop NetTap's containers"* ]] || false
    [[ "$output" == *"1 step(s) failed"* ]] || false
    [ ! -e "$R/etc/netplan/10-nettap-mirror-enp4s0.yaml" ]
    [ ! -e "$R/etc/systemd/system/nettap.service" ]
}

@test "uninstall drops a leftover wants link without asking systemctl about a unit that's gone" {
    ln -s /etc/systemd/system/nettap-bridge-promisc.service \
        "$R/etc/systemd/system/multi-user.target.wants/nettap-bridge-promisc.service"
    _uninstall --yes < /dev/null
    [ "$status" -eq 0 ]
    [ ! -L "$R/etc/systemd/system/multi-user.target.wants/nettap-bridge-promisc.service" ]
    [ "$(_calls | grep -c 'disable --now')" -eq 0 ]
}

@test "uninstall rejects an unknown option before doing anything" {
    _mirror_box
    _uninstall --force < /dev/null
    [ "$status" -eq 1 ]
    [[ "$output" == *"Unknown option: --force"* ]] || false
    _mirror_box_intact
}
