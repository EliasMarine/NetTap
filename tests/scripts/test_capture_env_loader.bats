#!/usr/bin/env bats
# ==========================================================================
# BATS tests for config/capture/nettap-capture-env.sh
# ==========================================================================
# The loader is sourced by every capture container entrypoint before
# `exec tini`. It must parse /etc/nettap/capture.env without running it,
# export only PCAP_IFACE / PCAP_FILTER / CAPTURE_FILTER, and always return 0.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
LOADER="${REPO_ROOT}/config/capture/nettap-capture-env.sh"

load 'helpers/setup'

# ---------------------------------------------------------------------------
# Helper: source the loader in a clean bash (like the entrypoint wrapper),
# then print the capture variables. Compose defaults are set first.
# ---------------------------------------------------------------------------
_run_loader() {
    run env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" \
        PCAP_IFACE=br0 PCAP_FILTER="" \
        bash -c ". '${LOADER}' && echo \"IFACE=\${PCAP_IFACE-unset}\" \
            && echo \"FILTER=\${PCAP_FILTER-unset}\" \
            && echo \"CFILTER=\${CAPTURE_FILTER-unset}\" \
            && echo \"MODE=\${CAPTURE_MODE-unset}\" \
            && echo \"EVIL=\${EVIL-unset}\""
}

@test "capture-env: missing file leaves the compose env untouched" {
    _run_loader

    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=br0"* ]]
    [[ "$output" == *"FILTER="$'\n'* ]]
    [[ "$output" == *"CFILTER=unset"* ]]
}

@test "capture-env: exports PCAP_IFACE, PCAP_FILTER and CAPTURE_FILTER" {
    cat > "${TEST_TMPDIR}/capture.env" <<'EOF'
CAPTURE_MODE=dhcp_gateway
PCAP_IFACE=enp1s0
PCAP_FILTER=net 10.77.0.0/24 or udp port 67 or udp port 68
EOF
    _run_loader

    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=enp1s0"* ]]
    [[ "$output" == *"FILTER=net 10.77.0.0/24 or udp port 67 or udp port 68"* ]]
    [[ "$output" == *"CFILTER=net 10.77.0.0/24 or udp port 67 or udp port 68"* ]]
}

@test "capture-env: exported values reach exec'd children (tini)" {
    printf 'PCAP_IFACE=eth2\nPCAP_FILTER=net 10.77.0.0/24\n' > "${TEST_TMPDIR}/capture.env"

    run env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" \
        bash -c ". '${LOADER}' && exec env"

    [ "$status" -eq 0 ]
    [[ "$output" == *"PCAP_IFACE=eth2"* ]]
    [[ "$output" == *"CAPTURE_FILTER=net 10.77.0.0/24"* ]]
}

@test "capture-env: empty PCAP_FILTER clears the filter (mirror / bridge)" {
    printf 'CAPTURE_MODE=mirror\nPCAP_IFACE=eth2\nPCAP_FILTER=\n' > "${TEST_TMPDIR}/capture.env"
    _run_loader

    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=eth2"* ]]
    [[ "$output" == *"CFILTER="$'\n'* ]]
}

@test "capture-env: other keys are ignored (CAPTURE_MODE is not exported)" {
    printf 'CAPTURE_MODE=dhcp_gateway\nEVIL=1\nPCAP_IFACE=enp1s0\n' > "${TEST_TMPDIR}/capture.env"
    _run_loader

    [ "$status" -eq 0 ]
    [[ "$output" == *"MODE=unset"* ]]
    [[ "$output" == *"EVIL=unset"* ]]
}

@test "capture-env: \$(...) in the file is never executed" {
    local marker="${TEST_TMPDIR}/pwned"
    cat > "${TEST_TMPDIR}/capture.env" <<EOF
EVIL=\$(touch ${marker})
PCAP_FILTER=\$(touch ${marker})
PCAP_IFACE=\`touch ${marker}\`
touch ${marker}
EOF
    _run_loader

    [ "$status" -eq 0 ]
    [ ! -e "$marker" ]
    # Invalid values are rejected, so the compose defaults stay
    [[ "$output" == *"IFACE=br0"* ]]
    [[ "$output" == *"CFILTER=unset"* ]]
}

@test "capture-env: invalid or too-long interface names are ignored" {
    printf 'PCAP_IFACE=eth0;reboot\n' > "${TEST_TMPDIR}/capture.env"
    _run_loader
    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=br0"* ]]

    printf 'PCAP_IFACE=abcdefghijklmnop\n' > "${TEST_TMPDIR}/capture.env"
    _run_loader
    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=br0"* ]]

    printf 'PCAP_IFACE=abcdefghijklmno\n' > "${TEST_TMPDIR}/capture.env"
    _run_loader
    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=abcdefghijklmno"* ]]
}

@test "capture-env: last line without a trailing newline is read" {
    printf 'PCAP_IFACE=enp1s0' > "${TEST_TMPDIR}/capture.env"
    _run_loader

    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=enp1s0"* ]]
}

@test "capture-env: returns 0 when the path is not a file and leaks no helper vars" {
    mkdir -p "${TEST_TMPDIR}/capture.env"
    run env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" \
        bash -c ". '${LOADER}'; echo \"rc=\$?\"; set | grep -c '^_nettap_' || true"

    [ "$status" -eq 0 ]
    [ "${lines[0]}" = "rc=0" ]
    [ "${lines[1]}" = "0" ]
}

@test "capture-env: works under POSIX sh" {
    printf 'PCAP_IFACE=enp1s0\nPCAP_FILTER=net 10.77.0.0/24 or udp port 67 or udp port 68\n' \
        > "${TEST_TMPDIR}/capture.env"

    run env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" \
        sh -c ". '${LOADER}' && echo \"\$PCAP_IFACE|\$CAPTURE_FILTER\""

    [ "$status" -eq 0 ]
    [ "$output" = "enp1s0|net 10.77.0.0/24 or udp port 67 or udp port 68" ]
}
