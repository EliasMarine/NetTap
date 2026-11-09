#!/usr/bin/env bats
# ==========================================================================
# BATS tests for record_baseline() in scripts/remote/deploy-protocol-identification.sh (NET-219)
# ==========================================================================

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/remote/deploy-protocol-identification.sh"

load 'helpers/setup'

# Runs the real record_baseline() (the script deploys on load, so the function is cut out and
# eval'd) with git, sudo and docker stubbed on PATH: HEAD is $1 and its compose file is $2.
run_record_baseline() {
    local bin="${TEST_TMPDIR}/bin"
    mkdir -p "$bin"
    cat > "${bin}/git" <<'STUB'
#!/usr/bin/env bash
case "$1" in
    rev-parse) echo "$STUB_REV" ;;
    show) cat "$STUB_COMPOSE" ;;
    *) exit 1 ;;
esac
STUB
    printf '#!/usr/bin/env bash\nexec "$@"\n' > "${bin}/sudo"
    printf '#!/usr/bin/env bash\necho "sha256:image-of-${*: -1}"\n' > "${bin}/docker"
    chmod +x "${bin}/git" "${bin}/sudo" "${bin}/docker"
    local fn
    fn="$(sed -n '/^record_baseline()/,/^}/p' "$SCRIPT")"
    [ -n "$fn" ]
    run env PATH="${bin}:${PATH}" STUB_REV="$1" STUB_COMPOSE="$2" bash -c "
        BASELINE='${TEST_TMPDIR}/deploys/protocol-identification.baseline'
        ${fn}
        record_baseline
    "
}

setup_compose() {  # setup_compose NAME VALUE: a compose file with ZEEK_DISABLE_SPICY_QUIC=VALUE
    printf '      ZEEK_DISABLE_SPICY_QUIC: "%s"\n' "$2" > "${TEST_TMPDIR}/$1"
}

BEFORE_REV="1111111111111111111111111111111111111111"
FEATURE_REV="2222222222222222222222222222222222222222"

@test "record_baseline: the first run records the revision and the running images" {
    setup_compose before.yml true
    run_record_baseline "$BEFORE_REV" "${TEST_TMPDIR}/before.yml"
    [ "$status" -eq 0 ]
    local file="${TEST_TMPDIR}/deploys/protocol-identification.baseline"
    grep -qx "revision=${BEFORE_REV}" "$file"
    grep -qx "zeek_live_image=sha256:image-of-nettap-zeek-live" "$file"
    grep -qx "daemon_image=sha256:image-of-nettap-storage-daemon" "$file"
    grep -qx "web_image=sha256:image-of-nettap-web" "$file"
    grep -qE "^recorded=[0-9]{4}-[0-9]{2}-[0-9]{2}T" "$file"
    [ ! -e "${file}.tmp" ]
    [[ "$output" == *"recorded"* ]]
}

@test "record_baseline: a second run keeps the first revision" {
    setup_compose before.yml true
    run_record_baseline "$BEFORE_REV" "${TEST_TMPDIR}/before.yml"
    [ "$status" -eq 0 ]
    local file="${TEST_TMPDIR}/deploys/protocol-identification.baseline"
    local first
    first="$(cat "$file")"
    # the retry runs after the checkout moved to the feature branch
    setup_compose feature.yml false
    run_record_baseline "$FEATURE_REV" "${TEST_TMPDIR}/feature.yml"
    [ "$status" -eq 0 ]
    [ "$(cat "$file")" = "$first" ]
    [[ "$output" == *"kept"* ]]
    [[ "$output" == *"revision=${BEFORE_REV}"* ]]
}

@test "record_baseline: refuses a checkout that already has NET-219 as the rollback point" {
    setup_compose feature.yml false
    run_record_baseline "$FEATURE_REV" "${TEST_TMPDIR}/feature.yml"
    [ "$status" -ne 0 ]
    [ ! -e "${TEST_TMPDIR}/deploys/protocol-identification.baseline" ]
    [[ "$output" == *"already has NET-219"* ]]
}

@test "record_baseline: a checkout without NET-219 replaces an older point" {
    # run 1 recorded main@A and failed; another deploy then moved the device to main@B
    setup_compose before.yml true
    run_record_baseline "$BEFORE_REV" "${TEST_TMPDIR}/before.yml"
    [ "$status" -eq 0 ]
    local later_rev="3333333333333333333333333333333333333333"
    run_record_baseline "$later_rev" "${TEST_TMPDIR}/before.yml"
    [ "$status" -eq 0 ]
    grep -qx "revision=${later_rev}" "${TEST_TMPDIR}/deploys/protocol-identification.baseline"
}
