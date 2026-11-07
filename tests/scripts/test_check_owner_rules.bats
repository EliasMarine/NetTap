#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/remote/check-owner-rules.sh (NET-191 slice 3)
# ==========================================================================
# The refusals and what the script sends to the daemon. The replay and the restart need the G11.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
SCRIPT="${REPO_ROOT}/scripts/remote/check-owner-rules.sh"

load 'helpers/setup'

# sudo records every call and answers as the device would: slice 2 is live, Suricata runs cleanly,
# the daemon API answers from MOCK_* (GET) and records each POST body. jq is the real one.
_stub() {
    mkdir -p "$TEST_TMPDIR/bin" "$TEST_TMPDIR/home"
    export CALLS="$TEST_TMPDIR/calls" BODIES="$TEST_TMPDIR/bodies" HOME="$TEST_TMPDIR/home"
    export NETTAP_REPO_DIR="$REPO_ROOT" MOCK_COUNT="${MOCK_COUNT:-0}" MOCK_OWNER="${MOCK_OWNER:-0}" MOCK_CONTENT="${MOCK_CONTENT:-}"
    : > "$CALLS"
    : > "$BODIES"
    cat > "$TEST_TMPDIR/bin/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo $*" >> "$CALLS"
[ "$1 $2" = "docker exec" ] || exit 1
shift 2
case "$1" in
    -i) shift 3; exec jq "$@" ;;  # json_get: docker exec -i <live> jq -r <filter>
    nettap-storage-daemon)  # api: python3 -c <script> <method> <path> [<body>]
        case "$5 $6" in
            "GET /api/suricata/rules/custom") echo "200 {\"content\": \"$MOCK_CONTENT\", \"rule_count\": $MOCK_COUNT}" ;;
            "GET /api/suricata/rules/live") echo "200 {\"owner_rules\": $MOCK_OWNER}" ;;
            "POST /api/suricata/rules/custom") printf '%s\n' "$7" >> "$BODIES"; echo '200 {"saved": true}' ;;
            *) echo "0 unexpected" ;;
        esac ;;
    nettap-suricata-live)
        case "$*" in
            *"nettap-rules-update shim"*) exit 0 ;;
            *sha256sum*) echo "0123456789abcdef0123  /var/lib/suricata/rules/suricata.rules" ;;
            *ruleset-stats*) echo "65378 0" ;;
            *) exit 1 ;;
        esac ;;
    *) exit 1 ;;
esac
EOF
    chmod +x "$TEST_TMPDIR/bin/sudo"
    export PATH="$TEST_TMPDIR/bin:$PATH"
}

@test "check-owner-rules: refuses when there are own rules (it would replace them)" {
    export MOCK_COUNT=2 MOCK_OWNER=2; _stub
    run bash "$SCRIPT"
    [ "$status" -eq 3 ]
    [[ "$output" == *"Your own rules aren't empty (2 rules, 0 characters); this check would replace them"* ]]
    [ ! -s "$BODIES" ]
}

@test "check-owner-rules: refuses when the own rules hold only comments (the save would drop them)" {
    export MOCK_CONTENT='# my notes\n# alert is coming'; _stub
    run bash "$SCRIPT"
    [ "$status" -eq 3 ]
    [[ "$output" == *"Your own rules aren't empty (0 rules, 28 characters)"* ]]
    [ ! -s "$BODIES" ]
}

@test "check-owner-rules: refuses before slice 3 is deployed (no owner rules file in suricata-live)" {
    export MOCK_OWNER=null; _stub
    run bash "$SCRIPT"
    [ "$status" -eq 3 ]
    [[ "$output" == *"Run deploy-detection-slice3.sh first"* ]]
    [ ! -s "$BODIES" ]
}

@test "check-owner-rules: saves the self-test rule as valid JSON, then clears it" {
    _stub
    run bash "$SCRIPT"
    # the replay and the restart can't run here, so the run ends with ✗ lines
    [ "$status" -eq 1 ]
    [ "$(wc -l < "$BODIES")" -eq 2 ]
    rule='alert dns any any -> any any (msg:"NetTap owner rule self-test"; dns.query; content:"nettap-selftest.invalid"; nocase; sid:1999999; rev:1;)'
    [ "$(sed -n 1p "$BODIES" | jq -r .content)" = "$rule" ]
    [ "$(sed -n 1p "$BODIES" | jq -j .content | tail -c 1 | od -An -c | tr -d ' ')" = '\n' ]
    [ "$(sed -n 2p "$BODIES" | jq -r .content)" = "" ]
}
