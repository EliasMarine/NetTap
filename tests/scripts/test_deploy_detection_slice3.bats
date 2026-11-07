#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/remote/deploy-detection-slice3.sh (NET-191 slice 3)
# ==========================================================================
# Its two gates: a failure stops before anything is built, or before suricata-live is touched.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/remote/deploy-detection-slice3.sh"

load 'helpers/setup'

# git is stubbed (the real repo is never switched). sudo records every call and answers as a device
# with slice 2 live; MOCK_CUSTOM_DIR is Malcolm's custom rules dir, MOCK_OWNER_FILE=0 means the
# daemon made owner.rules. Everything else docker is asked succeeds quietly.
_stub() {
    mkdir -p "$TEST_TMPDIR/bin" "$TEST_TMPDIR/home"
    export CALLS="$TEST_TMPDIR/calls" HOME="$TEST_TMPDIR/home" NETTAP_REPO_DIR="$REPO_ROOT"
    : > "$CALLS"
    printf '#!/usr/bin/env bash\necho "git $*" >> "$CALLS"\n[ "$1" = branch ] && echo feature/detection-slice3\nexit 0\n' > "$TEST_TMPDIR/bin/git"
    cat > "$TEST_TMPDIR/bin/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo $*" >> "$CALLS"
case "$*" in
    *"nettap-rules-update shim"*) exit 0 ;;
    *sha256sum*) echo "0123456789abcdef0123  suricata.rules" ;;
    *ruleset-stats*) echo "65378 0" ;;
    *"printenv SURICATA_CUSTOM_RULES_DIR") echo "$MOCK_CUSTOM_DIR" ;;
    *"--format={{.State.Health.Status}}"*) echo healthy ;;
    *"test -f /var/lib/nettap-suricata-custom/owner.rules") exit "$MOCK_OWNER_FILE" ;;
    "docker exec nettap-storage-daemon python3"*) echo "200 {}" ;;
    "docker exec -i"*) exit 0 ;;
    *) exit 0 ;;
esac
EOF
    chmod +x "$TEST_TMPDIR/bin/git" "$TEST_TMPDIR/bin/sudo"
    export PATH="$TEST_TMPDIR/bin:$PATH"
}

@test "deploy slice 3: Malcolm's custom rules dir elsewhere → nothing built or restarted" {
    export MOCK_CUSTOM_DIR=/opt/suricata/custom MOCK_OWNER_FILE=0
    _stub
    run bash "$SCRIPT"
    [ "$status" -eq 1 ]
    [[ "$output" == *"SURICATA_CUSTOM_RULES_DIR is '/opt/suricata/custom', not /opt/suricata/rules"* ]]
    ! grep -q "docker compose" "$CALLS"
}

@test "deploy slice 3: the daemon gate fails → suricata-live is not recreated" {
    export MOCK_CUSTOM_DIR=/opt/suricata/rules MOCK_OWNER_FILE=1
    _stub
    run bash "$SCRIPT"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Gate failed — suricata-live was not recreated"* ]]
    grep -q "docker compose -f docker/docker-compose.yml up -d --no-deps --force-recreate nettap-storage-daemon nettap-web" "$CALLS"
    ! grep -q "force-recreate suricata-live" "$CALLS"
}
