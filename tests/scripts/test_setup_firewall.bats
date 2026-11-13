#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/install/setup-firewall.sh (NET-229 follow-up)
# ==========================================================================
# nettap-web reaches the daemon (host network, port 8880) over the compose network's bridge, so
# --enable must allow exactly that network's subnets before it denies 8880 to everyone else.
# The functions run in dry-run mode, so every ufw call is logged and nothing is applied; docker
# is a stub that answers `docker network inspect` from $MOCK_NET.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/install/setup-firewall.sh"

load 'helpers/setup'

_load_firewall() {
    mkdir -p "$TEST_TMPDIR/bin"
    cat > "$TEST_TMPDIR/bin/docker" <<'STUB'
#!/usr/bin/env bash
[[ "$1 $2 $3" == "network inspect docker_default" && -f "$MOCK_NET" ]] || exit 1
cat "$MOCK_NET"
STUB
    chmod +x "$TEST_TMPDIR/bin/docker"
    unset -f docker  # helpers/mocks defines a docker function that would shadow the stub
    export PATH="$TEST_TMPDIR/bin:$PATH" MOCK_NET="$TEST_TMPDIR/net"
    # shellcheck source=../../scripts/common.sh
    source "${REPO_ROOT}/scripts/common.sh"
    # The script parses arguments and dispatches at the top level, so only its functions are loaded
    eval "$(awk '/^(detect_mgmt_interface|docker_daemon_subnets|do_enable)\(\) \{/,/^\}/' "$SCRIPT")"
    require_root() { :; }
    do_status() { :; }
    # shellcheck disable=SC2034  # read by the loaded functions
    NETTAP_DRY_RUN=true MGMT_IFACE=eth9 SSH_PORT=22 HTTPS_PORT=443 MALCOLM_PORT=9443
    # shellcheck disable=SC2034
    DOCKER_NETWORK=docker_default
}

# The ufw lines in the order they ran
_ufw_calls() {
    grep -o '\[DRY-RUN\] ufw .*' "$TEST_TMPDIR/out" | sed 's/^\[DRY-RUN\] //'
}

_line_of() {
    _ufw_calls | grep -nF -- "$1" | head -1 | cut -d: -f1
}

@test "G11 shape: the compose network's subnet may reach 8880, before the deny" {
    _load_firewall
    printf '%s\n' 172.18.0.0/16 > "$MOCK_NET"
    do_enable > "$TEST_TMPDIR/out" 2>&1

    allow=$(_line_of 'ufw allow from 172.18.0.0/16 to any port 8880 proto tcp')
    deny=$(_line_of 'ufw deny in to any port 8880 proto tcp')
    [ -n "$allow" ]
    [ -n "$deny" ]
    [ "$allow" -lt "$deny" ]
    # nothing else opens 8880
    [ "$(_ufw_calls | grep -c 'allow.*port 8880')" -eq 1 ]
}

@test "a custom address pool and an IPv6 subnet are used as Docker reports them" {
    _load_firewall
    printf '%s\n%s\n' 10.99.0.0/24 2001:db8:99::/64 > "$MOCK_NET"
    do_enable > "$TEST_TMPDIR/out" 2>&1

    _ufw_calls | grep -qF 'ufw allow from 10.99.0.0/24 to any port 8880 proto tcp'
    _ufw_calls | grep -qF 'ufw allow from 2001:db8:99::/64 to any port 8880 proto tcp'
    [ "$(_ufw_calls | grep -c 'allow.*port 8880')" -eq 2 ]
}

@test "no compose network yet: nothing is opened, a warning says to re-run, 8880 stays denied" {
    _load_firewall
    do_enable > "$TEST_TMPDIR/out" 2>&1

    [ "$(_ufw_calls | grep -c 'allow.*port 8880')" -eq 0 ]
    _ufw_calls | grep -qF 'ufw deny in to any port 8880 proto tcp'
    grep -q "docker_default not found" "$TEST_TMPDIR/out"
    grep -q "run this script again" "$TEST_TMPDIR/out"
}

@test "NET-211 #6: nothing opens 9443, which nothing listens on" {
    _load_firewall
    printf '%s\n' 172.18.0.0/16 > "$MOCK_NET"
    do_enable > "$TEST_TMPDIR/out" 2>&1

    [ "$(_ufw_calls | grep -c 'port 9443')" -eq 0 ]
    _ufw_calls | grep -qF 'ufw allow in on eth9 to any port 443 proto tcp'
}
