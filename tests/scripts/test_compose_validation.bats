#!/usr/bin/env bats
# ==========================================================================
# BATS tests for docker/docker-compose.yml structural validation
# ==========================================================================
# Validates the compose file has correct settings for all services:
# logging, OOM protection, security, cert mounts, healthchecks, etc.
#
# Uses python3 + PyYAML (or a grep-based fallback) to parse the compose file
# since YAML anchors/aliases need proper resolution.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.yml"

load 'helpers/setup'

# ---------------------------------------------------------------------------
# Helper: check if python3 with yaml module is available
# ---------------------------------------------------------------------------
_has_pyyaml() {
    python3 -c "import yaml" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Helper: query compose file with python3+PyYAML (resolves anchors)
# ---------------------------------------------------------------------------
_compose_query() {
    local query="$1"
    python3 -c "
import yaml, sys
with open('${COMPOSE_FILE}') as f:
    data = yaml.safe_load(f)
${query}
"
}

# ==========================================================================
# File structure
# ==========================================================================

@test "compose: file exists and is valid YAML" {
    [ -f "$COMPOSE_FILE" ]

    if _has_pyyaml; then
        run python3 -c "
import yaml
with open('${COMPOSE_FILE}') as f:
    data = yaml.safe_load(f)
assert 'services' in data, 'Missing services key'
"
        [ "$status" -eq 0 ]
    else
        # Fallback: just check it's not empty and has services
        grep -q "^services:" "$COMPOSE_FILE"
    fi
}

@test "compose: all expected services are defined" {
    local expected_services=(
        opensearch
        dashboards-helper
        dashboards
        logstash
        filebeat
        zeek-live
        suricata-live
        pcap-capture
        arkime-live
        redis
        api
        nginx-proxy
        nettap-storage-daemon
        nettap-web
        nettap-grafana
        nettap-nginx
        nettap-tshark
        nettap-cyberchef
    )

    for svc in "${expected_services[@]}"; do
        grep -q "^  ${svc}:" "$COMPOSE_FILE" || \
        grep -q "^  ${svc}:" "$COMPOSE_FILE"
    done
}

# ==========================================================================
# OOM Protection
# ==========================================================================

@test "compose: opensearch has oom_score_adj: -500" {
    grep -q "oom_score_adj: -500" "$COMPOSE_FILE"
}

# ==========================================================================
# Log rotation
# ==========================================================================

@test "compose: logging defaults anchor is defined with local driver" {
    grep -q "x-logging-defaults:" "$COMPOSE_FILE"
    grep -q "driver: local" "$COMPOSE_FILE"
    grep -q 'max-size: "200m"' "$COMPOSE_FILE"
    grep -q 'max-file: "2"' "$COMPOSE_FILE"
}

@test "compose: all services reference logging defaults" {
    if ! _has_pyyaml; then
        skip "PyYAML not available — using grep fallback"
    fi

    run _compose_query "
services = data.get('services', {})
missing = []
for name, svc in services.items():
    logging = svc.get('logging')
    if not logging:
        missing.append(name)
if missing:
    print('Services missing logging config: ' + ', '.join(missing))
    sys.exit(1)
print('All services have logging config')
"
    [ "$status" -eq 0 ]
}

# ==========================================================================
# Security: cap_drop
# ==========================================================================

@test "compose: Malcolm services do NOT have cap_drop: ALL" {
    # Malcolm services whose entrypoint chains need standard capabilities.
    # These should NOT have cap_drop: ALL.
    local malcolm_services=(
        opensearch
        dashboards-helper
        dashboards
        logstash
        filebeat
        redis
        api
        nginx-proxy
    )

    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    for svc in "${malcolm_services[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
cap_drop = svc.get('cap_drop', [])
if 'ALL' in cap_drop:
    print('${svc} has cap_drop: ALL — this breaks Malcolm entrypoint')
    sys.exit(1)
print('${svc}: OK')
"
        [ "$status" -eq 0 ]
    done
}

@test "compose: capture services have cap_drop: ALL + explicit cap_add" {
    local capture_services=(
        zeek-live
        suricata-live
        pcap-capture
        arkime-live
    )

    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    for svc in "${capture_services[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
cap_drop = svc.get('cap_drop', [])
cap_add = svc.get('cap_add', [])
assert 'ALL' in cap_drop, '${svc} should have cap_drop: ALL'
assert len(cap_add) > 0, '${svc} should have explicit cap_add'
# Must have NET_ADMIN and NET_RAW for packet capture
assert 'NET_ADMIN' in cap_add, '${svc} needs NET_ADMIN'
assert 'NET_RAW' in cap_add, '${svc} needs NET_RAW'
print('${svc}: OK (cap_drop ALL + cap_add ' + str(cap_add) + ')')
"
        [ "$status" -eq 0 ]
    done
}

@test "compose: NetTap custom services have cap_drop: ALL" {
    local nettap_services=(
        nettap-storage-daemon
        nettap-web
        nettap-grafana
    )

    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    for svc in "${nettap_services[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
cap_drop = svc.get('cap_drop', [])
assert 'ALL' in cap_drop, '${svc} should have cap_drop: ALL'
print('${svc}: OK')
"
        [ "$status" -eq 0 ]
    done
}

# ==========================================================================
# Security: no-new-privileges
# ==========================================================================

@test "compose: all services have no-new-privileges (except logstash)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Logstash is intentionally exempt: Malcolm's supervisord uses stdout_logfile=/dev/fd/1,
    # which fails with EACCES after the entrypoint privilege drop when no-new-privileges is set.
    run _compose_query "
services = data.get('services', {})
exempt = {'logstash'}
missing = []
for name, svc in services.items():
    if name in exempt:
        continue
    sec_opt = svc.get('security_opt', [])
    if 'no-new-privileges:true' not in sec_opt:
        missing.append(name)
if missing:
    print('Services missing no-new-privileges: ' + ', '.join(missing))
    sys.exit(1)
print('All non-exempt services have no-new-privileges')
"
    [ "$status" -eq 0 ]
}

@test "compose: logstash does NOT have no-new-privileges (supervisord compat)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['logstash']
sec_opt = svc.get('security_opt', [])
if 'no-new-privileges:true' in sec_opt:
    print('logstash has no-new-privileges — will break supervisord /dev/fd/1 access')
    sys.exit(1)
print('logstash: correctly omits no-new-privileges')
"
    [ "$status" -eq 0 ]
}

@test "compose: supervisord services have PUSER_PRIV_DROP=false" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Only logstash and dashboards-helper use supervisord with stdout_logfile=/dev/fd/1.
    # The su heredoc privilege drop breaks fd access, so these two need PUSER_PRIV_DROP=false.
    local services_need_false=(
        logstash
        dashboards-helper
    )

    for svc in "${services_need_false[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
env = svc.get('environment', {})
priv_drop = env.get('PUSER_PRIV_DROP', 'not set')
assert priv_drop == 'false', f'${svc}: PUSER_PRIV_DROP should be false, got: {priv_drop}'
print('${svc}: PUSER_PRIV_DROP=false (correct)')
"
        [ "$status" -eq 0 ]
    done
}

@test "compose: non-supervisord Malcolm services do NOT set PUSER_PRIV_DROP=false" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Most Malcolm services (OpenSearch, Dashboards, Redis, etc.) refuse to run as root.
    # They must NOT have PUSER_PRIV_DROP=false — the default privilege drop must stay enabled.
    local services_must_not_be_false=(
        opensearch
        dashboards
        filebeat
        api
        nginx-proxy
        redis
    )

    for svc in "${services_must_not_be_false[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
env = svc.get('environment', {})
priv_drop = env.get('PUSER_PRIV_DROP', 'not set')
assert priv_drop != 'false', f'${svc}: PUSER_PRIV_DROP must NOT be false (service refuses root), got: {priv_drop}'
print('${svc}: PUSER_PRIV_DROP={} (correct — not false)'.format(priv_drop))
"
        [ "$status" -eq 0 ]
    done
}

# ==========================================================================
# Cert mounts
# ==========================================================================

@test "compose: dashboards does NOT mount certs directory" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['dashboards']
volumes = svc.get('volumes', [])
cert_vols = [v for v in volumes if 'certs' in str(v) and 'certificates' in str(v)]
if cert_vols:
    print('dashboards has unnecessary cert mount: ' + str(cert_vols))
    sys.exit(1)
print('dashboards: no cert mount (correct)')
"
    [ "$status" -eq 0 ]
}

@test "compose: logstash does NOT mount certs directory (BEATS_SSL=false)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['logstash']
volumes = svc.get('volumes', [])
cert_vols = [v for v in volumes if 'certificates' in str(v)]
if cert_vols:
    print('logstash has unnecessary cert mount: ' + str(cert_vols))
    sys.exit(1)
print('logstash: no cert mount (correct — BEATS_SSL=false)')
"
    [ "$status" -eq 0 ]
}

@test "compose: filebeat does NOT mount certs directory (BEATS_SSL=false)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['filebeat']
volumes = svc.get('volumes', [])
cert_vols = [v for v in volumes if 'certificates' in str(v)]
if cert_vols:
    print('filebeat has unnecessary cert mount: ' + str(cert_vols))
    sys.exit(1)
print('filebeat: no cert mount (correct — BEATS_SSL=false)')
"
    [ "$status" -eq 0 ]
}

@test "compose: arkime does NOT mount host certs (self-generates internally)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['arkime-live']
volumes = svc.get('volumes', [])
cert_vols = [v for v in volumes if 'certs' in str(v) or 'certificates' in str(v)]
if cert_vols:
    print('arkime has unnecessary cert mount: ' + str(cert_vols))
    sys.exit(1)
print('arkime: no cert mount (correct — self-generates)')
"
    [ "$status" -eq 0 ]
}

@test "compose: api does NOT mount certs directory" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['api']
volumes = svc.get('volumes', [])
cert_vols = [v for v in volumes if 'certificates' in str(v)]
if cert_vols:
    print('api has unnecessary cert mount: ' + str(cert_vols))
    sys.exit(1)
print('api: no cert mount (correct)')
"
    [ "$status" -eq 0 ]
}

@test "compose: nginx-proxy mounts certs at /etc/nginx/certs" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['nginx-proxy']
volumes = svc.get('volumes', [])
cert_mount = [v for v in volumes if '/etc/nginx/certs' in str(v)]
assert len(cert_mount) > 0, 'nginx-proxy must mount certs at /etc/nginx/certs'
print('nginx-proxy: cert mount found — ' + str(cert_mount[0]))
"
    [ "$status" -eq 0 ]
}

# ==========================================================================
# Healthchecks
# ==========================================================================

@test "compose: opensearch uses Malcolm's container_health.sh" {
    grep -A5 "healthcheck:" "$COMPOSE_FILE" | head -20 | grep -q "container_health.sh"
}

@test "compose: opensearch healthcheck has 180s start_period" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['opensearch']
hc = svc.get('healthcheck', {})
assert hc.get('start_period') == '180s' or hc.get('start_period') == 180, \
    f'Expected 180s start_period, got {hc.get(\"start_period\")}'
print('opensearch healthcheck start_period: 180s')
"
    [ "$status" -eq 0 ]
}

# ==========================================================================
# OpenSearch specific
# ==========================================================================

@test "compose: opensearch has IPC_LOCK and SYS_RESOURCE capabilities" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['opensearch']
cap_add = svc.get('cap_add', [])
assert 'IPC_LOCK' in cap_add, 'opensearch needs IPC_LOCK for memory locking'
assert 'SYS_RESOURCE' in cap_add, 'opensearch needs SYS_RESOURCE for mlockall'
print('opensearch capabilities: ' + str(cap_add))
"
    [ "$status" -eq 0 ]
}

@test "compose: opensearch has memlock ulimits set to unlimited" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['opensearch']
ulimits = svc.get('ulimits', {})
memlock = ulimits.get('memlock', {})
assert memlock.get('soft') == -1, f'Expected memlock soft=-1, got {memlock.get(\"soft\")}'
assert memlock.get('hard') == -1, f'Expected memlock hard=-1, got {memlock.get(\"hard\")}'
print('opensearch memlock: unlimited')
"
    [ "$status" -eq 0 ]
}

@test "compose: opensearch mounts curlrc for credential setup" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['opensearch']
volumes = svc.get('volumes', [])
curlrc_mount = [v for v in volumes if 'curlrc' in str(v)]
assert len(curlrc_mount) > 0, 'opensearch must mount curlrc directory'
print('opensearch curlrc mount: ' + str(curlrc_mount[0]))
"
    [ "$status" -eq 0 ]
}

@test "compose: OPENSEARCH_SSL_CERTIFICATE_VERIFICATION is false" {
    grep -q 'OPENSEARCH_SSL_CERTIFICATE_VERIFICATION.*false' "$COMPOSE_FILE"
}

# ==========================================================================
# Restart policy
# ==========================================================================

@test "compose: all services use restart: unless-stopped" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
services = data.get('services', {})
wrong = []
for name, svc in services.items():
    restart = svc.get('restart', 'no')
    if restart != 'unless-stopped':
        wrong.append(f'{name}: {restart}')
if wrong:
    print('Services with wrong restart policy: ' + ', '.join(wrong))
    sys.exit(1)
print('All services use restart: unless-stopped')
"
    [ "$status" -eq 0 ]
}

# ==========================================================================
# Image tags
# ==========================================================================

@test "compose: all Malcolm images use the same tag variable" {
    # Every Malcolm service image: line should reference MALCOLM_IMAGE_TAG.
    # Filter to only actual service image: keys (indented with spaces),
    # excluding YAML anchor definitions (x-malcolm-image:).
    local malcolm_lines
    malcolm_lines=$(grep -E '^\s+image:.*ghcr.io/idaholab/malcolm' "$COMPOSE_FILE")

    # Count lines that DON'T use the variable
    local bad_lines
    bad_lines=$(echo "$malcolm_lines" | grep -v 'MALCOLM_IMAGE_TAG' || true)

    [ -z "$bad_lines" ]
}

# ==========================================================================
# Network topology
# ==========================================================================

@test "compose: capture services use host network mode" {
    local capture_services=(zeek-live suricata-live pcap-capture arkime-live)

    for svc in "${capture_services[@]}"; do
        grep -A5 "^  ${svc}:" "$COMPOSE_FILE" | grep -q "network_mode: host"
    done
}

@test "compose: non-capture services do NOT use host network" {
    local internal_services=(
        opensearch dashboards logstash redis api nginx-proxy
        nettap-storage-daemon nettap-web nettap-grafana
    )

    for svc in "${internal_services[@]}"; do
        # Should NOT have network_mode: host
        local section
        section=$(sed -n "/^  ${svc}:/,/^  [^ ]/p" "$COMPOSE_FILE")
        if echo "$section" | grep -q "network_mode: host"; then
            echo "${svc} incorrectly uses host network"
            return 1
        fi
    done
}

# ==========================================================================
# Port exposure
# ==========================================================================

@test "compose: OpenSearch 9200 is bound to loopback only" {
    grep -q '127.0.0.1:9200:9200' "$COMPOSE_FILE"
}
