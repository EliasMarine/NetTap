#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/fresh-install-cloud.sh
# ==========================================================================
# The script creates billable droplets in an account that also holds unrelated
# production droplets. These tests pin down that it only ever deletes what its
# own run created, never deletes a firewall while its droplet lives, reports
# leftovers, and never records a failed install as a success. doctl is a stub.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/fresh-install-cloud.sh"
RUN="20261110t010203z-u2404"

setup() {
    export FI_STATE_DIR="${BATS_TEST_TMPDIR}/state" FI_DELETE_WAIT_S=1 FI_POLL_S=0
    export STUB_DIR="${BATS_TEST_TMPDIR}/stub" DOCTL_LOG="${BATS_TEST_TMPDIR}/doctl.log"
    export STUB_ACCOUNT="acct-1"
    mkdir -p "${BATS_TEST_TMPDIR}/bin" "$STUB_DIR"
    : > "$DOCTL_LOG"
    cat > "${BATS_TEST_TMPDIR}/bin/doctl" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$DOCTL_LOG"
case "$*" in
    "account get"*)               echo "$STUB_ACCOUNT" ;;
    "compute ssh-key import"*)    echo 111 ;;
    "compute firewall create"*)   echo 222 ;;
    "compute droplet create"*)    [[ -n "${STUB_CREATE_FAIL:-}" ]] && exit 1; echo "333 203.0.113.5" ;;
    "compute droplet list --tag-name"*) [[ -n "${STUB_LIST_FAIL:-}" ]] && exit 1; echo "${STUB_TAGGED:-}" ;;
    "compute droplet list"*)      echo "${STUB_NAMED:-}" ;;
    "compute droplet delete"*)    [[ -n "${STUB_DELETE_FAIL:-}" ]] && exit 1; touch "$STUB_DIR/deleted-$4" ;;
    "compute droplet get"*)
        [[ -e "$STUB_DIR/deleted-$4" ]] && { echo "Error: GET droplets/$4: 404 not found"; exit 1; }
        echo "${STUB_GET_OUT:-$4}" ;;
    "compute firewall list"*|"compute ssh-key list"*) : ;;
    *) : ;;
esac
EOF
    cat > "${BATS_TEST_TMPDIR}/bin/curl" <<'EOF'
#!/usr/bin/env bash
echo 198.51.100.7
EOF
    chmod +x "${BATS_TEST_TMPDIR}/bin/"*
    export PATH="${BATS_TEST_TMPDIR}/bin:${PATH}"
}

# make_run <extra manifest lines…> — a run whose manifest names droplet 333, firewall 222, key 111
make_run() {
    mkdir -p "${FI_STATE_DIR}/${RUN}"
    {
        echo "ACCOUNT_UUID='acct-1'"; echo "RUN='${RUN}'"; echo "RUN_TAG='nettap-fi-${RUN}'"
        echo "KEY_ID='111'"; echo "FW_ID='222'"; echo "DROPLET_ID='333'"; echo "DROPLET_IP='203.0.113.5'"
        echo "SHA='$(printf 'a%.0s' {1..40})'"
        printf '%s\n' "$@"
    } > "${FI_STATE_DIR}/${RUN}/manifest.env"
}

@test "fresh-install: up refuses an image outside the allow-list" {
    run "$SCRIPT" up ubuntu-20-04-x64
    [ "$status" -ne 0 ]
    [[ "$output" == *"image must be one of"* ]]
    [ ! -s "$DOCTL_LOG" ]
}

@test "fresh-install: an unknown subcommand prints usage and exits 2" {
    run "$SCRIPT" explode
    [ "$status" -eq 2 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "fresh-install: down refuses a malformed run ID or a run with no manifest" {
    run "$SCRIPT" down 'nettap-*'
    [ "$status" -ne 0 ]
    run "$SCRIPT" down "$RUN"
    [ "$status" -ne 0 ]
    [[ "$output" == *"no manifest"* ]]
    run grep -q delete "$DOCTL_LOG"; [ "$status" -ne 0 ]
}

@test "fresh-install: down deletes only this run's IDs, droplet first, then firewall, key and tag" {
    make_run
    run "$SCRIPT" down "$RUN"
    [ "$status" -eq 0 ]
    [[ "$output" == *"DESTROYED"* ]]
    deletes="$(grep delete "$DOCTL_LOG")"
    [ "$(sed -n 1p <<< "$deletes")" = "compute droplet delete 333 --force" ]
    [ "$(sed -n 2p <<< "$deletes")" = "compute firewall delete 222 --force" ]
    [ "$(sed -n 3p <<< "$deletes")" = "compute ssh-key delete 111 --force" ]
    [ "$(sed -n 4p <<< "$deletes")" = "compute tag delete nettap-fi-${RUN} --force" ]
    [ "$(wc -l <<< "$deletes")" -eq 4 ]
    grep -q '^DESTROYED=' "${FI_STATE_DIR}/${RUN}/manifest.env"
}

@test "fresh-install: a failed droplet delete keeps the firewall and says CLEANUP REQUIRED" {
    make_run
    STUB_DELETE_FAIL=1 run "$SCRIPT" down "$RUN"
    [ "$status" -eq 2 ]
    [[ "$output" == *"CLEANUP REQUIRED"* ]]
    run grep -q 'firewall delete' "$DOCTL_LOG"; [ "$status" -ne 0 ]
    run grep -q '^DESTROYED=' "${FI_STATE_DIR}/${RUN}/manifest.env"; [ "$status" -ne 0 ]
}

@test "fresh-install: another doctl account means CLEANUP REQUIRED and no deletes" {
    make_run
    STUB_ACCOUNT="someone-else" run "$SCRIPT" down "$RUN"
    [ "$status" -eq 2 ]
    [[ "$output" == *"CLEANUP REQUIRED"* ]]
    run grep -q delete "$DOCTL_LOG"; [ "$status" -ne 0 ]
}

@test "fresh-install: a droplet create that errors but exists is found by the run tag and deleted" {
    make_run
    sed -i.bak "/^DROPLET_ID=/d;/^DROPLET_IP=/d" "${FI_STATE_DIR}/${RUN}/manifest.env"
    STUB_TAGGED=444 run "$SCRIPT" down "$RUN"
    [ "$status" -eq 0 ]
    grep -q 'compute droplet list --tag-name nettap-fi-'"$RUN" "$DOCTL_LOG"
    grep -q 'compute droplet delete 444 --force' "$DOCTL_LOG"
}

@test "fresh-install: a droplet that lost its tag is still found by its run name and deleted" {
    make_run
    sed -i.bak "/^DROPLET_ID=/d;/^DROPLET_IP=/d" "${FI_STATE_DIR}/${RUN}/manifest.env"
    STUB_NAMED="555 nettap-fi-${RUN}
666 rown-app-1" run "$SCRIPT" down "$RUN"
    [ "$status" -eq 0 ]
    grep -q 'compute droplet delete 555 --force' "$DOCTL_LOG"
    run grep -q 'droplet delete 666' "$DOCTL_LOG"; [ "$status" -ne 0 ]  # a neighbour is never touched
}

@test "fresh-install: a failed droplet lookup is CLEANUP REQUIRED, not DESTROYED, and deletes nothing" {
    make_run
    STUB_LIST_FAIL=1 run "$SCRIPT" down "$RUN"
    [ "$status" -eq 2 ]
    [[ "$output" == *"CLEANUP REQUIRED"* ]]
    run grep -q delete "$DOCTL_LOG"; [ "$status" -ne 0 ]
}

@test "fresh-install: a manifest whose RUN_TAG isn't this run's is refused before any lookup" {
    make_run "RUN_TAG=''"
    run "$SCRIPT" down "$RUN"
    [ "$status" -ne 0 ]
    [[ "$output" == *"RUN_TAG"* ]]
    run grep -q 'compute' "$DOCTL_LOG"; [ "$status" -ne 0 ]
}

@test "fresh-install: up rolls back the key, firewall and tag when the droplet create fails" {
    FI_SHA="$(printf 'b%.0s' {1..40})" STUB_CREATE_FAIL=1 run "$SCRIPT" up ubuntu-24-04-x64
    [ "$status" -ne 0 ]
    grep -q 'compute firewall create --name nettap-fi-.* --tag-names nettap-fi-' "$DOCTL_LOG"
    grep -q 'address:198.51.100.7/32' "$DOCTL_LOG"
    grep -q 'compute firewall delete 222 --force' "$DOCTL_LOG"
    grep -q 'compute ssh-key delete 111 --force' "$DOCTL_LOG"
    grep -q 'compute tag delete nettap-fi-' "$DOCTL_LOG"
}

@test "fresh-install: install refuses a droplet that doesn't carry the run tag" {
    make_run
    STUB_GET_OUT="prod-tag 203.0.113.5" run "$SCRIPT" install "$RUN"
    [ "$status" -ne 0 ]
    [[ "$output" == *"does not carry"* ]]
}

@test "fresh-install: the installer wrapper records and returns the installer's own exit code" {
    home="${BATS_TEST_TMPDIR}/home"
    mkdir -p "${home}/NetTap/scripts/install"
    printf '#!/usr/bin/env bash\nexit 7\n' > "${home}/NetTap/scripts/install/install.sh"
    printf '#!/usr/bin/env bash\nexec "$@"\n' > "${BATS_TEST_TMPDIR}/bin/sudo"
    chmod +x "${home}/NetTap/scripts/install/install.sh" "${BATS_TEST_TMPDIR}/bin/sudo"
    source "$SCRIPT"; set +u
    install_wrapper_body > "${home}/run-install.sh"
    HOME="$home" run bash "${home}/run-install.sh"
    [ "$status" -eq 7 ]
    [ "$(cat "${home}/install.status")" = "7" ]
}

@test "fresh-install: a missing or non-zero installer status is a FAIL" {
    source "$SCRIPT"; set +u
    run check_install_status ""
    [[ "$output" == *"FAIL"*"missing"* ]]
    run check_install_status "7"
    [[ "$output" == *"FAIL"* ]]
    run check_install_status "0"
    [[ "$output" == *"PASS"* ]]
}
