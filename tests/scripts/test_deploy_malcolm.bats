#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/install/deploy-malcolm.sh
# ==========================================================================
# Tests ILM policy parsing, preflight checks, and common.sh utilities.
#
# NOTE: We cannot source deploy-malcolm.sh directly because it sets
# PROJECT_ROOT from SCRIPT_DIR (overriding our test value) and enables
# set -euo pipefail globally. Instead, we test its logic indirectly.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

load 'helpers/setup'

# ==========================================================================
# ILM Policy JSON Parsing
# ==========================================================================
# These tests verify the ILM policy file structure and the python3 extraction
# logic used by apply_ilm_policy() — without needing Docker or OpenSearch.

@test "ILM JSON: file is valid JSON" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"
    [ -f "$ilm_file" ]

    run python3 -c "import json; json.load(open('${ilm_file}'))"
    [ "$status" -eq 0 ]
}

# OLD CODE START — one network policy replaced the three tiers (CR-017/CR-038).
# @test "ILM JSON: contains exactly 3 policies" {
#     local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"
#
#     run python3 -c "
# import json
# with open('${ilm_file}') as f:
#     data = json.load(f)
# names = list(data.get('policies', {}).keys())
# assert len(names) == 3, f'Expected 3 policies, got {len(names)}: {names}'
# print('OK: ' + ', '.join(names))
# "
#     [ "$status" -eq 0 ]
# }
# OLD CODE END

@test "ILM JSON: contains exactly 1 policy" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
names = list(data.get('policies', {}).keys())
assert names == ['nettap-hot-policy'], f'Expected [nettap-hot-policy], got {names}'
print('OK: ' + ', '.join(names))
"
    [ "$status" -eq 0 ]
}

@test "ILM JSON: policy names follow nettap-*-policy convention" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
for name in data['policies']:
    assert name.startswith('nettap-'), f'{name} does not start with nettap-'
    assert name.endswith('-policy'), f'{name} does not end with -policy'
print('OK: all policy names follow convention')
"
    [ "$status" -eq 0 ]
}

@test "ILM JSON: each policy has valid ISM structure" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
for name, wrapper in data['policies'].items():
    policy = wrapper.get('policy', {})
    assert 'states' in policy, f'{name}: missing states'
    assert 'default_state' in policy, f'{name}: missing default_state'
    assert policy['default_state'] == 'hot', f'{name}: default_state should be hot'
    assert 'ism_template' in policy, f'{name}: missing ism_template'
    # Each state must have a name and actions
    for state in policy['states']:
        assert 'name' in state, f'{name}: state missing name'
        assert 'actions' in state, f'{name}: state {state[\"name\"]} missing actions'
print('OK: all policies have valid ISM structure')
"
    [ "$status" -eq 0 ]
}

@test "ILM JSON: each policy extracts to valid standalone JSON" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
for name, wrapper in data['policies'].items():
    body = json.dumps(wrapper)
    # Verify round-trip parse
    parsed = json.loads(body)
    assert 'policy' in parsed, f'{name}: extracted JSON missing policy key'
print('OK: all policies extract cleanly')
"
    [ "$status" -eq 0 ]
}

@test "ILM hot policy: targets zeek-* with 90-day delete" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
policy = data['policies']['nettap-hot-policy']['policy']

# Check index patterns
templates = policy.get('ism_template', [])
patterns = [p for t in templates for p in t.get('index_patterns', [])]
assert 'zeek-*' in patterns, f'Expected zeek-* in {patterns}'

# Check 90-day retention
states = {s['name']: s for s in policy['states']}
hot_transitions = states['hot'].get('transitions', [])
delete_t = [t for t in hot_transitions if t['state_name'] == 'delete']
assert len(delete_t) == 1, 'Expected exactly one delete transition'
assert delete_t[0]['conditions']['min_index_age'] == '90d'
print('OK: zeek-* with 90d retention')
"
    [ "$status" -eq 0 ]
}

# OLD CODE START — suricata-* matched no index; Suricata alerts live in
# arkime_sessions3 with Zeek and follow the hot policy (CR-017/CR-038).
# @test "ILM warm policy: targets suricata-* with warm stage at 7d, delete at 180d" {
#     local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"
#
#     run python3 -c "
# import json
# with open('${ilm_file}') as f:
#     data = json.load(f)
# policy = data['policies']['nettap-warm-policy']['policy']
#
# templates = policy.get('ism_template', [])
# patterns = [p for t in templates for p in t.get('index_patterns', [])]
# assert 'suricata-*' in patterns, f'Expected suricata-* in {patterns}'
#
# states = {s['name']: s for s in policy['states']}
#
# # hot -> warm at 7d
# hot_transitions = states['hot'].get('transitions', [])
# warm_t = [t for t in hot_transitions if t['state_name'] == 'warm']
# assert len(warm_t) == 1
# assert warm_t[0]['conditions']['min_index_age'] == '7d'
#
# # warm -> delete at 180d
# warm_transitions = states['warm'].get('transitions', [])
# delete_t = [t for t in warm_transitions if t['state_name'] == 'delete']
# assert len(delete_t) == 1
# assert delete_t[0]['conditions']['min_index_age'] == '180d'
#
# # warm stage has force_merge
# warm_actions = states['warm'].get('actions', [])
# has_force_merge = any('force_merge' in a for a in warm_actions)
# assert has_force_merge, 'warm stage should have force_merge action'
# print('OK: suricata-* with 7d warm, 180d delete, force_merge')
# "
#     [ "$status" -eq 0 ]
# }
# OLD CODE END

@test "ILM hot policy: targets Malcolm's indices with no rollover (CR-017)" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
policy = data['policies']['nettap-hot-policy']['policy']

templates = policy.get('ism_template', [])
patterns = [p for t in templates for p in t.get('index_patterns', [])]
assert 'arkime_sessions3-*' in patterns, f'Expected arkime_sessions3-* in {patterns}'
assert 'malcolm_beats_*' in patterns, f'Expected malcolm_beats_* in {patterns}'

# Malcolm's dated indices have no rollover alias; a rollover would block delete
actions = [a for s in policy['states'] for a in s.get('actions', [])]
assert not any('rollover' in a for a in actions), 'rollover must not be used'
print('OK: Malcolm indices, no rollover')
"
    [ "$status" -eq 0 ]
}

# OLD CODE START — arkime-*/pcap-* matched no index (CR-017/CR-038).
# @test "ILM cold policy: targets arkime-*/pcap-* with 30-day delete" {
#     local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"
#
#     run python3 -c "
# import json
# with open('${ilm_file}') as f:
#     data = json.load(f)
# policy = data['policies']['nettap-cold-policy']['policy']
#
# templates = policy.get('ism_template', [])
# patterns = [p for t in templates for p in t.get('index_patterns', [])]
# assert 'arkime-*' in patterns, f'Expected arkime-* in {patterns}'
# assert 'pcap-*' in patterns, f'Expected pcap-* in {patterns}'
#
# states = {s['name']: s for s in policy['states']}
# hot_transitions = states['hot'].get('transitions', [])
# delete_t = [t for t in hot_transitions if t['state_name'] == 'delete']
# assert len(delete_t) == 1
# assert delete_t[0]['conditions']['min_index_age'] == '30d'
# print('OK: arkime-*/pcap-* with 30d retention')
# "
#     [ "$status" -eq 0 ]
# }
# OLD CODE END

@test "ILM policies: all actions have retry config for resilience" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
missing_retry = []
for pname, wrapper in data['policies'].items():
    for state in wrapper['policy']['states']:
        for action in state.get('actions', []):
            if 'retry' not in action:
                missing_retry.append(f'{pname}/{state[\"name\"]}')
if missing_retry:
    print('Actions missing retry: ' + ', '.join(missing_retry))
    sys.exit(1)
print('OK: all actions have retry config')
"
    [ "$status" -eq 0 ]
}

# ==========================================================================
# apply_ilm_policy: missing file handling
# ==========================================================================

@test "apply_ilm_policy: function uses PROJECT_ROOT for ILM path" {
    # Verify the function references the correct path pattern
    grep -q 'config/opensearch/ilm-policy.json' \
        "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "apply_ilm_policy: uses docker compose exec (not host curl) for auth" {
    # The function must exec into the container to bypass nginx-proxy auth
    grep -q 'docker compose.*exec.*opensearch' \
        "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "apply_ilm_policy: uses curlrc for OpenSearch authentication" {
    grep -q 'curlrc/.opensearch.primary.curlrc' \
        "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "apply_ilm_policy: applies policies individually (not as single blob)" {
    # The function should iterate over policy names, not apply the whole file
    grep -q 'policy_name' "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
    grep -q '_plugins/_ism/policies/${policy_name}' \
        "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

# ==========================================================================
# common.sh: retry logic
# ==========================================================================

@test "retry: function is defined in common.sh" {
    grep -q "^retry()" "${REPO_ROOT}/scripts/common.sh"
}

@test "retry: succeeds on first attempt" {
    # Run in a subshell to avoid set -e issues from common.sh
    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        retry 3 0 true
    "
    [ "$status" -eq 0 ]
}

@test "retry: fails after max attempts" {
    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        retry 2 0 false
    "
    [ "$status" -eq 1 ]
}

@test "retry: succeeds on Nth attempt" {
    local counter_file
    counter_file=$(mktemp)
    echo "0" > "$counter_file"

    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        flaky() {
            local c=\$(cat '${counter_file}')
            c=\$((c + 1))
            echo \$c > '${counter_file}'
            [ \$c -ge 2 ]
        }
        retry 3 0 flaky
    "
    [ "$status" -eq 0 ]
    rm -f "$counter_file"
}

# ==========================================================================
# common.sh: logging
# ==========================================================================

@test "log: outputs timestamped messages" {
    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        log 'test message'
    "
    [ "$status" -eq 0 ]
    [[ "$output" == *"[NetTap]"* ]]
    [[ "$output" == *"test message"* ]]
}

@test "warn: outputs to stderr" {
    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        warn 'test warning' 2>&1
    "
    [[ "$output" == *"WARN"* ]]
    [[ "$output" == *"test warning"* ]]
}

@test "error: exits with code 1" {
    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        error 'test error'
    "
    [ "$status" -eq 1 ]
    [[ "$output" == *"ERROR"* ]]
}

# ==========================================================================
# common.sh: check_command
# ==========================================================================

@test "check_command: succeeds for existing command" {
    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        check_command bash
    "
    [ "$status" -eq 0 ]
}

@test "check_command: fails for missing command" {
    run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        check_command nonexistent_command_xyz_12345
    "
    [ "$status" -eq 1 ]
    [[ "$output" == *"not found"* ]]
}

# ==========================================================================
# Verbose monitoring functions exist
# ==========================================================================

@test "deploy: monitor_startup function is defined" {
    grep -q "^monitor_startup()" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "deploy: _wait_for_service function is defined" {
    grep -q "^_wait_for_service()" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "deploy: _show_service_status function is defined" {
    grep -q "^_show_service_status()" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "deploy: _wait_for_opensearch_http function is defined" {
    grep -q "^_wait_for_opensearch_http()" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "deploy: starts opensearch alone before full stack" {
    # start_services must run 'up -d opensearch' before the general 'up -d'
    local os_line
    os_line=$(grep -n "up -d opensearch" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | head -1 | cut -d: -f1)
    local full_line
    full_line=$(grep -n 'up -d$' "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | head -1 | cut -d: -f1)
    [ -n "$os_line" ]
    [ -n "$full_line" ]
    [ "$os_line" -lt "$full_line" ]
}

@test "deploy: bootstrap runs after opensearch HTTP wait, before full stack" {
    local http_wait_line
    http_wait_line=$(grep -n "_wait_for_opensearch_http" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | grep -v "^.*#" | grep -v "_wait_for_opensearch_http()" | head -1 | cut -d: -f1)
    local bootstrap_line
    bootstrap_line=$(grep -n "bootstrap_opensearch_security" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | grep -v "^.*#" | grep -v "bootstrap_opensearch_security()" | head -1 | cut -d: -f1)
    local full_up_line
    full_up_line=$(grep -n 'up -d$' "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | head -1 | cut -d: -f1)
    [ -n "$http_wait_line" ]
    [ -n "$bootstrap_line" ]
    [ -n "$full_up_line" ]
    # Order: wait_for_http → bootstrap → full up
    [ "$http_wait_line" -lt "$bootstrap_line" ]
    [ "$bootstrap_line" -lt "$full_up_line" ]
}

@test "deploy: malcolm_template is pushed with its index pattern filled in (Chain 24)" {
    local script="${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
    # The raw file's pattern is a placeholder that matches no index
    grep -q 's/MALCOLM_NETWORK_INDEX_PATTERN_REPLACER/${index_pattern}/g' "$script"
    ! grep -E '^[^#]*-d @/opt/templates/malcolm_template.json' "$script"

    # The same sed turns Malcolm's placeholder into a pattern that matches today's index
    local index_pattern="arkime_sessions3-*"
    run sh -c "echo '{\"index_patterns\":[\"MALCOLM_NETWORK_INDEX_PATTERN_REPLACER\"]}' | sed 's/MALCOLM_NETWORK_INDEX_PATTERN_REPLACER/${index_pattern}/g'"
    [ "$output" = '{"index_patterns":["arkime_sessions3-*"]}' ]
}

# ==========================================================================
# OpenSearch security bootstrap
# ==========================================================================

@test "deploy: bootstrap_opensearch_security function is defined" {
    grep -q "^bootstrap_opensearch_security()" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

# OLD CODE START — replaced 2026-10-30 (MS-001): the bootstrap no longer writes
# roles_mapping.yml; OpenSearch builds it from ROLE_* on every start.
# @test "deploy: bootstrap writes roles_mapping.yml with all_access mapping" {
#     grep -q "all_access" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
#     grep -q "admin" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
#     grep -q "roles_mapping.yml" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
# }
# OLD CODE END

@test "deploy: bootstrap never overwrites roles_mapping.yml (MS-001)" {
    # A minimal mapping written here would race Malcolm's push of the full one.
    run bash -c "grep -v '^[[:space:]]*#' '${REPO_ROOT}/scripts/install/deploy-malcolm.sh' | grep -q \"roles_mapping.yml','w'\""
    [ "$status" -ne 0 ]
}

@test "deploy: bootstrap waits for OpenSearch's own security push first" {
    local fn
    fn=$(sed -n '/^bootstrap_opensearch_security()/,/^}/p' "${REPO_ROOT}/scripts/install/deploy-malcolm.sh")
    local wait_line push_line
    wait_line=$(echo "$fn" | grep -n "_opensearch_auth_ok" | head -1 | cut -d: -f1)
    push_line=$(echo "$fn" | grep -n "securityadmin.sh" | grep -v '^[0-9]*:[[:space:]]*#' | head -1 | cut -d: -f1)
    [ -n "$wait_line" ]
    [ -n "$push_line" ]
    [ "$wait_line" -lt "$push_line" ]
}

@test "deploy: bootstrap runs securityadmin.sh with admin certs" {
    grep -q "securityadmin.sh" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
    grep -q "admin.crt" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
    grep -q "admin.key" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "deploy: bootstrap verifies auth after security push" {
    grep -q "Verifying malcolm_internal authentication" \
        "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

# OLD CODE START — deploy no longer applies the static ISM file (CR-017).
# @test "deploy: bootstrap runs before apply_ilm_policy in start_services" {
#     # bootstrap_opensearch_security must appear before apply_ilm_policy
#     local bootstrap_line
#     bootstrap_line=$(grep -n "bootstrap_opensearch_security" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | grep -v "^.*#" | grep -v "^.*bootstrap_opensearch_security()" | head -1 | cut -d: -f1)
#     local ilm_line
#     ilm_line=$(grep -n "apply_ilm_policy" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | grep -v "^.*#" | grep -v "^.*apply_ilm_policy()" | head -1 | cut -d: -f1)
#     [ -n "$bootstrap_line" ]
#     [ -n "$ilm_line" ]
#     [ "$bootstrap_line" -lt "$ilm_line" ]
# }
# OLD CODE END

@test "deploy: start_services leaves ISM policies to the daemon (CR-017)" {
    # The static file overwrote the user's retention; the daemon applies and
    # attaches the generated policy instead.
    run bash -c "grep -v '^[[:space:]]*#' '${REPO_ROOT}/scripts/install/deploy-malcolm.sh' | grep -v 'apply_ilm_policy()' | grep -q 'apply_ilm_policy'"
    [ "$status" -ne 0 ]
}

@test "deploy: bootstrap_index_templates function is defined" {
    grep -q "^bootstrap_index_templates()" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "deploy: index templates bootstrap runs before full stack start" {
    local template_line
    template_line=$(grep -n "bootstrap_index_templates" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | grep -v "^.*#" | grep -v "^.*bootstrap_index_templates()" | head -1 | cut -d: -f1)
    local full_up_line
    full_up_line=$(grep -n 'up -d$' "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | head -1 | cut -d: -f1)
    [ -n "$template_line" ]
    [ -n "$full_up_line" ]
    [ "$template_line" -lt "$full_up_line" ]
}

# OLD CODE START — NET-217: grepped the old GET-then-PUT with -u "$os_creds"; the marker is now a
# create-only PUT through the curlrc, and the tests below run it instead of grepping it
# @test "deploy: bootstrap writes the Arkime template marker only when it is missing (#73)" {
#     local script="${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
#     local fn
#     fn=$(sed -n '/^bootstrap_index_templates()/,/^}/p' "$script")
#     # dashboards-helper waits for this legacy template before creating the index pattern
#     echo "$fn" | grep -q 'X PUT "https://opensearch:9200/_template/arkime_sessions3_template"'
#     # it must match no index, so it can never shape arkime_sessions3-* mappings
#     echo "$fn" | grep -q '"index_patterns":\["nettap-arkime-template-marker"\]'
#     # and it is guarded by a GET, so Arkime's real template is never overwritten
#     echo "$fn" | grep -q 'if ! docker compose .* exec -T dashboards-helper \\'
#     echo "$fn" | grep -q 'curl -sfk -u "$os_creds" "https://opensearch:9200/_template/arkime_sessions3_template"'
# }
# OLD CODE END

# ==========================================================================
# NET-217: the bootstrap stops the run when it fails, and keeps the
# OpenSearch password out of every process's arguments
# ==========================================================================
# These source deploy-malcolm.sh (its standalone guard keeps deploy_malcolm
# from running) with helpers/bootstrap_stubs.bash playing docker.

DEPLOY="${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
STUBS="${REPO_ROOT}/tests/scripts/helpers/bootstrap_stubs.bash"

_templates() { run bash -c "source '$DEPLOY'; source '$STUBS'; bootstrap_index_templates"; }
_security() { run bash -c "source '$DEPLOY'; source '$STUBS'; bootstrap_opensearch_security"; }
_log_count() { grep -c -- "$1" "${TEST_TMPDIR}/curl.log" 2>/dev/null || true; }
_puts() { _log_count '-X PUT'; }
_passes() { _log_count '_index_template/malcolm_template?filter_path'; }

@test "templates (NET-217): a fresh box gets every template; each call logs in through the mounted curlrc" {
    _templates
    [ "$status" -eq 0 ]
    local calls
    calls=$(grep -c . "${TEST_TMPDIR}/curl.log")
    [ "$(_log_count '--config /var/local/curlrc/.opensearch.primary.curlrc')" -eq "$calls" ]
    [ "$(_log_count '--max-time')" -eq "$calls" ]
    ! grep -qE -- '(^| )-u ' "${TEST_TMPDIR}/curl.log"
    grep -q -- '-X PUT https://opensearch:9200/_component_template/ecs_base' "${TEST_TMPDIR}/curl.log"
    grep -q -- '-X PUT https://opensearch:9200/_component_template/ecs_event' "${TEST_TMPDIR}/curl.log"
    grep -q -- '-X PUT https://opensearch:9200/_component_template/custom_zeek' "${TEST_TMPDIR}/curl.log"
    # Chain 24: the placeholder is filled in before the template leaves the host
    grep -qF '"index_patterns":["arkime_sessions3-*"]' "${TEST_TMPDIR}/body.malcolm_template"
    grep -qF '"index_patterns":["nettap-arkime-template-marker"]' "${TEST_TMPDIR}/body.arkime_sessions3_template"
    [[ "$output" == *"marker created"* ]] || false
}

@test "templates (NET-217): a malcolm_template PUT that keeps failing stops the run after 3 passes" {
    export F_MT_PUT=500
    _templates
    [ "$status" -eq 1 ]
    [[ "$output" == *"Index template bootstrap failed after 3 attempts"* ]] || false
    [[ "$output" == *"malcolm_template or arkime_sessions3_template"* ]] || false
    [[ "$output" == *"run the same command again"* ]] || false
    [ "$(_passes)" -eq 3 ]
}

@test "templates (NET-217): one failed malcolm_template PUT is retried" {
    export F_MT_PUT="500 200"
    _templates
    [ "$status" -eq 0 ]
    [ "$(_passes)" -eq 2 ]
}

@test "templates (NET-217): a failed component template PUT fails the pass before malcolm_template" {
    export F_COMP_FAIL=ecs_event
    _templates
    [ "$status" -eq 1 ]
    [[ "$output" == *"PUT _component_template/ecs_event answered HTTP 500"* ]] || false
    [ "$(_log_count '-X PUT https://opensearch:9200/_index_template/malcolm_template')" -eq 0 ]
}

@test "templates (NET-217): no component template files listed fails the pass" {
    export F_NO_FILES=1
    _templates
    [ "$status" -eq 1 ]
    [[ "$output" == *"No component templates found"* ]] || false
}

@test "templates (NET-217): the Arkime marker is create-only, so an existing template is never replaced (#73)" {
    export F_MARKER_PUT=400  # what OpenSearch answers ?create=true when the template exists
    _templates
    [ "$status" -eq 0 ]
    [ "$(_log_count '-X PUT https://opensearch:9200/_template/arkime_sessions3_template?create=true')" -ge 1 ]
    [ "$(_log_count '-X PUT https://opensearch:9200/_template/arkime_sessions3_template')" -eq \
      "$(_log_count '-X PUT https://opensearch:9200/_template/arkime_sessions3_template?create=true')" ]
    [[ "$output" != *"marker created"* ]] || false
}

@test "templates (NET-217): the run stops when the marker template is still missing at the end" {
    export F_MARKER_PRESENT=0
    _templates
    [ "$status" -eq 1 ]
    [ "$(_passes)" -eq 3 ]
}

@test "templates (NET-217): a live box's malcolm_template is kept as Malcolm set it" {
    export F_MT_GET=200
    _templates
    [ "$status" -eq 0 ]
    [[ "$output" == *"left as Malcolm set it"* ]] || false
    [ "$(_log_count '_component_template/')" -eq 0 ]
    [ "$(_log_count '-X PUT https://opensearch:9200/_index_template/malcolm_template')" -eq 0 ]
}

@test "templates (NET-217): a malcolm_template with the placeholder pattern is pushed again (Chain 24)" {
    export F_MT_GET=200
    export F_MT_BODY='{"index_templates":[{"index_template":{"index_patterns":["MALCOLM_NETWORK_INDEX_PATTERN_REPLACER"]}}]}'
    _templates
    [ "$status" -eq 0 ]
    [ "$(_log_count '-X PUT https://opensearch:9200/_index_template/malcolm_template')" -eq 1 ]
}

@test "templates (NET-217): a failed or unreadable read of malcolm_template writes nothing" {
    local case
    for case in '500|' '401|' 'transport|' \
        '200|{"index_patterns":' \
        '200|{"index_templates":[{"index_template":{"index_patterns":"arkime_sessions3-*"}}]}' \
        '200|{"index_templates":[{"index_template":{"index_patterns":[]}}]}' \
        '200|{"index_templates":[]}'; do
        rm -f "${TEST_TMPDIR}/curl.log" "${TEST_TMPDIR}"/count.*
        export F_MT_GET="${case%%|*}" F_MT_BODY="${case#*|}"
        _templates
        [ "$status" -eq 1 ] || { echo "case ${case}: status ${status}"; return 1; }
        [ "$(_puts)" -eq 0 ] || { echo "case ${case}: $(_puts) PUTs"; return 1; }
        [ "$(_passes)" -eq 3 ] || { echo "case ${case}: $(_passes) passes"; return 1; }
    done
}

@test "security (NET-217): working auth needs no securityadmin.sh, and the probe is time-boxed" {
    _security
    [ "$status" -eq 0 ]
    [ ! -f "${TEST_TMPDIR}/securityadmin.log" ]
    grep -q -- '--max-time' "${TEST_TMPDIR}/auth.log"
}

@test "security (NET-217): auth still failing after securityadmin.sh stops the run" {
    export F_AUTH_OK_AFTER=never
    _security
    [ "$status" -eq 1 ]
    [ -f "${TEST_TMPDIR}/securityadmin.log" ]
    [[ "$output" == *"malcolm_internal still has no access after securityadmin.sh"* ]] || false
    [[ "$output" == *"run the same command again"* ]] || false
}

@test "security (NET-217): a failing securityadmin.sh stops the run, and it runs under a time limit" {
    export F_AUTH_OK_AFTER=never F_SECADMIN_RC=1
    _security
    [ "$status" -eq 1 ]
    [[ "$output" == *"securityadmin.sh could not push the security config"* ]] || false
    grep -q 'timeout -k 10 180 /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh' \
        "${TEST_TMPDIR}/securityadmin.log"
}

@test "security (NET-217): auth that works after securityadmin.sh lets the run go on" {
    export F_AUTH_OK_AFTER=12  # the 60 s wait probes 12 times
    _security
    [ "$status" -eq 0 ]
    [ -f "${TEST_TMPDIR}/securityadmin.log" ]
    [[ "$output" == *"Authentication verified"* ]] || false
}

@test "deploy (NET-217): no password on a command line, and the HTTP wait is time-boxed" {
    local code
    code=$(grep -v '^[[:space:]]*#' "$DEPLOY")
    ! grep -q -- '-u "\$' <<< "$code"
    ! grep -q 'docker/curlrc' <<< "$code"
    sed -n '/^_wait_for_opensearch_http()/,/^}/p' "$DEPLOY" | grep -v '^[[:space:]]*#' | grep -q -- '--max-time'
}

# ==========================================================================
# NET-177: preflight's free space is decimal GB, like System and Setup
# ==========================================================================

_preflight_with_avail_kb() {
    run bash -c "source '$DEPLOY'
        docker() { return 0; }
        df() { printf 'Filesystem 1K-blocks Used Available Use%% Mounted on\n/dev/x 1 1 %s 1%% /\n' $1; }
        preflight 2>&1"
}

@test "preflight (NET-177): warns below 15 GB free, in decimal GB" {
    _preflight_with_avail_kb 15136719  # 15.5 GB: the old ceil'd df -BG said 15G, no warning
    [ "$status" -eq 0 ]
    [[ "$output" != *"free disk space"* ]] || false
    _preflight_with_avail_kb 14648438  # 15.00 GB
    [[ "$output" != *"free disk space"* ]] || false
    _preflight_with_avail_kb 14648437  # 14.99 GB
    [ "$status" -eq 0 ]
    [[ "$output" == *"Only 14 GB free disk space"* ]] || false
}

# ==========================================================================
# NET-217 device check: scripts/remote/deploy-malcolm-bootstrap.sh runs the
# real bootstrap on a live box through guarded_docker, which must let no
# write through except the create-only Arkime marker
# ==========================================================================

_guarded() {  # _guarded ARGS...: run guarded_docker ARGS with a sudo that logs instead of running
    run bash -c "$(sed -n '/^guarded_docker()/,/^}/p' "${REPO_ROOT}/scripts/remote/deploy-malcolm-bootstrap.sh")
        sudo() { echo \"\$*\" >> '${TEST_TMPDIR}/sudo.log'; }
        guarded_docker \"\$@\"" _ "$@"
}

@test "deploy-malcolm-bootstrap.sh (NET-217): guarded_docker refuses every write but the create-only marker" {
    _guarded compose -f x.yml up -d dashboards-helper
    [ "$status" -eq 0 ]
    _guarded compose -f x.yml exec -T opensearch bash -c 'JAVA_HOME=x timeout -k 10 180 /x/securityadmin.sh -cd /y'
    [ "$status" -ne 0 ]
    _guarded compose -f x.yml exec -T dashboards-helper curl --silent -X PUT https://opensearch:9200/_component_template/ecs_x -d @f
    [ "$status" -ne 0 ]
    _guarded compose -f x.yml exec -T dashboards-helper curl --silent -X PUT https://opensearch:9200/_index_template/malcolm_template -d @-
    [ "$status" -ne 0 ]
    [ ! -f "${TEST_TMPDIR}/sudo.log" ]

    _guarded compose -f x.yml exec -T dashboards-helper curl --silent -X PUT "https://opensearch:9200/_template/arkime_sessions3_template?create=true" -d @-
    [ "$status" -eq 0 ]
    _guarded compose -f x.yml exec -T dashboards-helper curl --silent --fail -o /dev/null https://opensearch:9200/_index_template/malcolm_template
    [ "$status" -eq 0 ]
    _guarded ps -q
    [ "$status" -eq 0 ]
    [ "$(grep -c . "${TEST_TMPDIR}/sudo.log")" -eq 3 ]
    grep -q '^docker compose -f x.yml exec -T dashboards-helper curl --silent -X PUT https://opensearch:9200/_template/arkime_sessions3_template?create=true -d @-$' "${TEST_TMPDIR}/sudo.log"
}
