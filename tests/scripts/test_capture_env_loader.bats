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

# Fake /sys/class/net holding every interface these tests name, so no test waits for one (NET-211 #9)
_sysfs() {
    local dir="${TEST_TMPDIR}/sys/class/net"
    mkdir -p "$dir"/{br0,enp1s0,enp4s0,eth2,abcdefghijklmno}
    echo "$dir"
}

# ---------------------------------------------------------------------------
# Helper: source the loader in a clean bash (like the entrypoint wrapper),
# then print the capture variables. Compose defaults are set first.
# ---------------------------------------------------------------------------
_run_loader() {
    run env -i PATH="$PATH" NETTAP_SYS_CLASS_NET="$(_sysfs)" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" \
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
    [[ "$output" == *"IFACE=br0"* ]] || false
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

    run env -i PATH="$PATH" NETTAP_SYS_CLASS_NET="$(_sysfs)" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" \
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
    [[ "$output" == *"IFACE=br0"* ]] || false
    [[ "$output" == *"CFILTER=unset"* ]]
}

@test "capture-env: invalid or too-long interface names are ignored" {
    printf 'PCAP_IFACE=eth0;reboot\n' > "${TEST_TMPDIR}/capture.env"
    _run_loader
    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=br0"* ]] || false

    printf 'PCAP_IFACE=abcdefghijklmnop\n' > "${TEST_TMPDIR}/capture.env"
    _run_loader
    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=br0"* ]] || false

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
    run env -i PATH="$PATH" NETTAP_SYS_CLASS_NET="$(_sysfs)" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" \
        bash -c ". '${LOADER}'; echo \"rc=\$?\"; set | grep -c '^_nettap_' || true"

    [ "$status" -eq 0 ]
    [ "${lines[0]}" = "rc=0" ]
    [ "${lines[1]}" = "0" ]
}

@test "capture-env: works under POSIX sh" {
    printf 'PCAP_IFACE=enp1s0\nPCAP_FILTER=net 10.77.0.0/24 or udp port 67 or udp port 68\n' \
        > "${TEST_TMPDIR}/capture.env"

    run env -i PATH="$PATH" NETTAP_SYS_CLASS_NET="$(_sysfs)" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" \
        sh -c ". '${LOADER}' && echo \"\$PCAP_IFACE|\$CAPTURE_FILTER\""

    [ "$status" -eq 0 ]
    [ "$output" = "enp1s0|net 10.77.0.0/24 or udp port 67 or udp port 68" ]
}

@test "capture-env: exports a valid PCAP_ROTATE_MEGABYTES (netsniff file size)" {
    printf 'PCAP_IFACE=enp4s0\nPCAP_ROTATE_MEGABYTES=750\n' > "${TEST_TMPDIR}/capture.env"
    run env -i PATH="$PATH" NETTAP_SYS_CLASS_NET="$(_sysfs)" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" PCAP_ROTATE_MEGABYTES=4096 \
        bash -c ". '${LOADER}' && echo \"ROTATE=\${PCAP_ROTATE_MEGABYTES}\""
    [ "$status" -eq 0 ]
    [[ "$output" == *"ROTATE=750"* ]]
}

@test "capture-env: junk or out-of-range PCAP_ROTATE_MEGABYTES keeps the compose value" {
    for bad in 5 20000 123456 '4096; rm -rf /' '$(id)' ''; do
        printf 'PCAP_ROTATE_MEGABYTES=%s\n' "$bad" > "${TEST_TMPDIR}/capture.env"
        run env -i PATH="$PATH" NETTAP_SYS_CLASS_NET="$(_sysfs)" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" PCAP_ROTATE_MEGABYTES=4096 \
            bash -c ". '${LOADER}' && echo \"ROTATE=\${PCAP_ROTATE_MEGABYTES}\""
        [ "$status" -eq 0 ]
        [[ "$output" == *"ROTATE=4096"* ]]
    done
}

# ---------------------------------------------------------------------------
# ET Pro code (NET-191 slice 2): /etc/nettap/suricata.env turns et/open into et/pro
# ---------------------------------------------------------------------------
_run_sources() {  # $1 = SURICATA_UPDATE_ENABLE_SOURCES before the loader
    run env -i PATH="$PATH" NETTAP_SYS_CLASS_NET="$(_sysfs)" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/none.env" \
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
    run env -i PATH="$PATH" NETTAP_SYS_CLASS_NET="$(_sysfs)" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/none.env" \
        NETTAP_SURICATA_ENV="${TEST_TMPDIR}/suricata.env" \
        sh -c ". '${LOADER}' && echo \"SOURCES=\${SURICATA_UPDATE_ENABLE_SOURCES-unset}\""
    [ "$status" -eq 0 ]
    [ "$output" = "SOURCES=unset" ]
}

# ---------------------------------------------------------------------------
# NET-211 #9: wait until the capture interface exists
# ---------------------------------------------------------------------------
# A `sleep` stub on PATH logs each call and makes $APPEAR appear on the second one. A tenth call
# stops the loader with TERM, so a broken wait fails the test instead of hanging it.
_sleep_stub() {
    local bin="${TEST_TMPDIR}/bin"
    mkdir -p "$bin"
    cat > "${bin}/sleep" <<'STUB'
#!/usr/bin/env bash
echo "sleep $*" >> "${TEST_TMPDIR}/sleep.log"
n=$(wc -l < "${TEST_TMPDIR}/sleep.log")
if [ "$n" -ge "${APPEAR_AT:-2}" ] && [ -n "$APPEAR" ]; then mkdir -p "$APPEAR"; fi
if [ "$n" -ge "${KILL_AT:-10}" ]; then kill -TERM "$PPID"; fi
STUB
    chmod +x "${bin}/sleep"
}

_wait_loader() {  # $1 = compose PCAP_IFACE, $2 = interface dir the stub creates (or "")
    _sleep_stub
    mkdir -p "${TEST_TMPDIR}/wsys"
    run env -i PATH="${TEST_TMPDIR}/bin:$PATH" TEST_TMPDIR="$TEST_TMPDIR" APPEAR="$2" \
        APPEAR_AT="${APPEAR_AT:-2}" KILL_AT="${KILL_AT:-10}" \
        NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/capture.env" NETTAP_SYS_CLASS_NET="${TEST_TMPDIR}/wsys" \
        PCAP_IFACE="$1" bash -c ". '${LOADER}' && echo \"IFACE=\${PCAP_IFACE}\" && trap"
}

_sleeps() { if [ -f "${TEST_TMPDIR}/sleep.log" ]; then wc -l < "${TEST_TMPDIR}/sleep.log" | tr -d ' '; else echo 0; fi; }

@test "capture-env: an interface that exists starts capture at once" {
    mkdir -p "${TEST_TMPDIR}/wsys/br0"
    _wait_loader br0 ""
    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=br0"* ]] || false
    [[ "$output" != *"waiting"* ]] || false
    [ "$(_sleeps)" -eq 0 ]
}

@test "capture-env: a missing interface waits, says so once, then carries on" {
    _wait_loader br0 "${TEST_TMPDIR}/wsys/br0"
    [ "$status" -eq 0 ]
    [ "$(grep -c 'nettap-capture-env: waiting for capture interface br0 (set by the setup wizard, or Go Live for a bridge)' <<< "$output")" -eq 1 ]
    [[ "$output" == *"IFACE=br0"* ]] || false
    [ "$(_sleeps)" -eq 2 ]
    [ "$(grep -c 'sleep 5' "${TEST_TMPDIR}/sleep.log")" -eq 2 ]
    # the TERM trap is gone once capture starts (`trap` prints nothing)
    [[ "$output" != *"exit 143"* ]] || false
}

@test "capture-env: a port that doesn't appear is named again every 5 minutes" {
    APPEAR_AT=62 KILL_AT=70 _wait_loader eth9 "${TEST_TMPDIR}/wsys/eth9"
    [ "$status" -eq 0 ]
    [ "$(_sleeps)" -eq 62 ]
    # before the 1st sleep and the 61st (60 x 5 s = 5 minutes)
    [ "$(grep -c 'waiting for capture interface eth9' <<< "$output")" -eq 2 ]
}

@test "capture-env: waits for the wizard's interface from capture.env, not the compose br0" {
    mkdir -p "${TEST_TMPDIR}/wsys/enp4s0"
    printf 'CAPTURE_MODE=mirror\nPCAP_IFACE=enp4s0\n' > "${TEST_TMPDIR}/capture.env"
    _wait_loader br0 ""
    [ "$status" -eq 0 ]
    [[ "$output" == *"IFACE=enp4s0"* ]] || false
    [ "$(_sleeps)" -eq 0 ]
}

@test "capture-env: a comma list waits only for the missing interface" {
    mkdir -p "${TEST_TMPDIR}/wsys/enp1s0"
    _wait_loader "enp1s0,eth9" "${TEST_TMPDIR}/wsys/eth9"
    [ "$status" -eq 0 ]
    [[ "$output" == *"waiting for capture interface eth9"* ]] || false
    [[ "$output" != *"waiting for capture interface enp1s0"* ]] || false
    [[ "$output" == *"IFACE=enp1s0,eth9"* ]] || false
}

@test "capture-env: no sysfs means no wait" {
    _sleep_stub
    run env -i PATH="${TEST_TMPDIR}/bin:$PATH" TEST_TMPDIR="$TEST_TMPDIR" APPEAR="" \
        NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/none.env" NETTAP_SYS_CLASS_NET="${TEST_TMPDIR}/wsys" \
        PCAP_IFACE=br0 sh -c ". '${LOADER}' && echo \"IFACE=\${PCAP_IFACE}\""
    [ "$status" -eq 0 ]
    [ "$output" = "IFACE=br0" ]
    [ "$(_sleeps)" -eq 0 ]
}

@test "capture-env: docker stop ends the wait at once (TERM, exit 143)" {
    local sys="${TEST_TMPDIR}/empty-sys" out="${TEST_TMPDIR}/out" pid _ rc=0
    mkdir -p "$sys"
    env -i PATH="$PATH" NETTAP_CAPTURE_ENV="${TEST_TMPDIR}/none.env" NETTAP_SYS_CLASS_NET="$sys" PCAP_IFACE=br0 \
        sh -c ". '${LOADER}'; echo after" > "$out" 2>&1 3>&- &
    pid=$!
    for _ in $(seq 1 50); do
        grep -q 'waiting for capture interface br0' "$out" && break
        sleep 0.1
    done
    grep -q 'waiting for capture interface br0' "$out"
    kill -TERM "$pid"
    for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid"
        false
    fi
    wait "$pid" || rc=$?
    [ "$rc" -eq 143 ]
    [ "$(grep -c after "$out")" -eq 0 ]
}
