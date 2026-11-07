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

@test "capture-env: exports a valid PCAP_ROTATE_MEGABYTES (netsniff file size)" {
    printf 'PCAP_IFACE=enp4s0\nPCAP_ROTATE_MEGABYTES=750\n' > "${TEST_TMPDIR}/capture.env"
    run env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" PCAP_ROTATE_MEGABYTES=4096 \
        bash -c ". '${LOADER}' && echo \"ROTATE=\${PCAP_ROTATE_MEGABYTES}\""
    [ "$status" -eq 0 ]
    [[ "$output" == *"ROTATE=750"* ]]
}

@test "capture-env: junk or out-of-range PCAP_ROTATE_MEGABYTES keeps the compose value" {
    for bad in 5 20000 123456 '4096; rm -rf /' '$(id)' ''; do
        printf 'PCAP_ROTATE_MEGABYTES=%s\n' "$bad" > "${TEST_TMPDIR}/capture.env"
        run env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" PCAP_ROTATE_MEGABYTES=4096 \
            bash -c ". '${LOADER}' && echo \"ROTATE=\${PCAP_ROTATE_MEGABYTES}\""
        [ "$status" -eq 0 ]
        [[ "$output" == *"ROTATE=4096"* ]]
    done
}

# ---------------------------------------------------------------------------
# ET Pro code (NET-191 slice 2): /etc/nettap/suricata.env turns et/open into et/pro
# ---------------------------------------------------------------------------
_run_sources() {  # $1 = SURICATA_UPDATE_ENABLE_SOURCES before the loader
    run env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/none.env" \
        NETTAP_SURICATA_ENV="${TEST_TMPDIR}/suricata.env" SURICATA_UPDATE_ENABLE_SOURCES="$1" \
        sh -c ". '${LOADER}' && echo \"SOURCES=\${SURICATA_UPDATE_ENABLE_SOURCES-unset}\""
}

@test "capture-env: a valid ET Pro code swaps et/open for et/pro, other sources kept in order" {
    printf 'SURICATA_ETPRO_CODE=Abc123Def456Ghi789\n' > "${TEST_TMPDIR}/suricata.env"
    _run_sources "et/open,abuse.ch/sslbl-blacklist,echap/stalkerware,ipfire/dbl"
    [ "$status" -eq 0 ]
    [ "$output" = "SOURCES=et/pro|secret-code=Abc123Def456Ghi789,abuse.ch/sslbl-blacklist,echap/stalkerware,ipfire/dbl" ]
}

@test "capture-env: no suricata.env leaves the sources unchanged" {
    _run_sources "et/open,ipfire/dbl"
    [ "$status" -eq 0 ]
    [ "$output" = "SOURCES=et/open,ipfire/dbl" ]
}

@test "capture-env: an invalid ET Pro code is ignored and never echoed" {
    for bad in 'short1234' 'Abc123Def456Ghi789;id' 'Abc123Def456Ghi789 x' '$(id)Abc123Def456Ghi' \
        "$(printf 'A%.0s' $(seq 1 65))" 'Abc123Def456Ghi789|evil=1'; do
        printf 'SURICATA_ETPRO_CODE=%s\n' "$bad" > "${TEST_TMPDIR}/suricata.env"
        _run_sources "et/open,ipfire/dbl"
        [ "$status" -eq 0 ]
        [[ "$output" == *"SOURCES=et/open,ipfire/dbl"* ]]
        [[ "$output" == *"ignoring an invalid SURICATA_ETPRO_CODE"* ]]
        [[ "$output" != *"$bad"* ]]
    done
}

@test "capture-env: containers without a source list (zeek, arkime, pcap) are not touched" {
    printf 'SURICATA_ETPRO_CODE=Abc123Def456Ghi789\n' > "${TEST_TMPDIR}/suricata.env"
    run env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/none.env" \
        NETTAP_SURICATA_ENV="${TEST_TMPDIR}/suricata.env" \
        sh -c ". '${LOADER}' && echo \"SOURCES=\${SURICATA_UPDATE_ENABLE_SOURCES-unset}\""
    [ "$status" -eq 0 ]
    [ "$output" = "SOURCES=unset" ]
}
