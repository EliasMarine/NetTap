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

@test "ILM JSON: contains exactly 3 policies" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
names = list(data.get('policies', {}).keys())
assert len(names) == 3, f'Expected 3 policies, got {len(names)}: {names}'
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

@test "ILM warm policy: targets suricata-* with warm stage at 7d, delete at 180d" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
policy = data['policies']['nettap-warm-policy']['policy']

templates = policy.get('ism_template', [])
patterns = [p for t in templates for p in t.get('index_patterns', [])]
assert 'suricata-*' in patterns, f'Expected suricata-* in {patterns}'

states = {s['name']: s for s in policy['states']}

# hot -> warm at 7d
hot_transitions = states['hot'].get('transitions', [])
warm_t = [t for t in hot_transitions if t['state_name'] == 'warm']
assert len(warm_t) == 1
assert warm_t[0]['conditions']['min_index_age'] == '7d'

# warm -> delete at 180d
warm_transitions = states['warm'].get('transitions', [])
delete_t = [t for t in warm_transitions if t['state_name'] == 'delete']
assert len(delete_t) == 1
assert delete_t[0]['conditions']['min_index_age'] == '180d'

# warm stage has force_merge
warm_actions = states['warm'].get('actions', [])
has_force_merge = any('force_merge' in a for a in warm_actions)
assert has_force_merge, 'warm stage should have force_merge action'
print('OK: suricata-* with 7d warm, 180d delete, force_merge')
"
    [ "$status" -eq 0 ]
}

@test "ILM cold policy: targets arkime-*/pcap-* with 30-day delete" {
    local ilm_file="${REPO_ROOT}/config/opensearch/ilm-policy.json"

    run python3 -c "
import json
with open('${ilm_file}') as f:
    data = json.load(f)
policy = data['policies']['nettap-cold-policy']['policy']

templates = policy.get('ism_template', [])
patterns = [p for t in templates for p in t.get('index_patterns', [])]
assert 'arkime-*' in patterns, f'Expected arkime-* in {patterns}'
assert 'pcap-*' in patterns, f'Expected pcap-* in {patterns}'

states = {s['name']: s for s in policy['states']}
hot_transitions = states['hot'].get('transitions', [])
delete_t = [t for t in hot_transitions if t['state_name'] == 'delete']
assert len(delete_t) == 1
assert delete_t[0]['conditions']['min_index_age'] == '30d'
print('OK: arkime-*/pcap-* with 30d retention')
"
    [ "$status" -eq 0 ]
}

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

# ==========================================================================
# OpenSearch security bootstrap
# ==========================================================================

@test "deploy: bootstrap_opensearch_security function is defined" {
    grep -q "^bootstrap_opensearch_security()" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
}

@test "deploy: bootstrap writes roles_mapping.yml with all_access mapping" {
    grep -q "all_access" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
    grep -q "admin" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
    grep -q "roles_mapping.yml" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
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

@test "deploy: bootstrap runs before apply_ilm_policy in start_services" {
    # bootstrap_opensearch_security must appear before apply_ilm_policy
    local bootstrap_line
    bootstrap_line=$(grep -n "bootstrap_opensearch_security" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | grep -v "^.*#" | grep -v "^.*bootstrap_opensearch_security()" | head -1 | cut -d: -f1)
    local ilm_line
    ilm_line=$(grep -n "apply_ilm_policy" "${REPO_ROOT}/scripts/install/deploy-malcolm.sh" | grep -v "^.*#" | grep -v "^.*apply_ilm_policy()" | head -1 | cut -d: -f1)
    [ -n "$bootstrap_line" ]
    [ -n "$ilm_line" ]
    [ "$bootstrap_line" -lt "$ilm_line" ]
}
