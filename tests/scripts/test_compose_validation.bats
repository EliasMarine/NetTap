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

@test "compose: capture services have cap_add for packet capture (no cap_drop: ALL)" {
    # Capture services are Malcolm images — must NOT have cap_drop: ALL because
    # their entrypoint needs standard capabilities (SETUID, SETGID, etc.)
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
assert 'ALL' not in cap_drop, '${svc} must NOT have cap_drop: ALL (Malcolm entrypoint needs su)'
assert len(cap_add) > 0, '${svc} should have explicit cap_add'
assert 'NET_ADMIN' in cap_add, '${svc} needs NET_ADMIN'
assert 'NET_RAW' in cap_add, '${svc} needs NET_RAW'
print('${svc}: OK (cap_add ' + str(cap_add) + ')')
"
        [ "$status" -eq 0 ]
    done
}

@test "compose: nginx containers have required capabilities (CHOWN, SETUID, SETGID)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    local nginx_services=(
        nettap-cyberchef
        nettap-nginx
    )

    for svc in "${nginx_services[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
cap_add = svc.get('cap_add', [])
assert 'CHOWN' in cap_add, '${svc} needs CHOWN for cache dir ownership'
assert 'SETUID' in cap_add, '${svc} needs SETUID for worker process'
assert 'SETGID' in cap_add, '${svc} needs SETGID for worker group'
print('${svc}: has required nginx capabilities')
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

@test "compose: NetTap custom services have no-new-privileges" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Only NetTap services (which we control) should have no-new-privileges.
    # Malcolm services use `su` (setuid binary) in their entrypoint which
    # silently fails with no-new-privileges, causing services to exit code 0.
    local nettap_services=(
        nettap-storage-daemon
        nettap-web
        nettap-grafana
        nettap-tshark
        nettap-cyberchef
        nettap-nginx
    )

    for svc in "${nettap_services[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
sec_opt = svc.get('security_opt', [])
assert 'no-new-privileges:true' in sec_opt, '${svc} should have no-new-privileges'
print('${svc}: has no-new-privileges (correct)')
"
        [ "$status" -eq 0 ]
    done
}

@test "compose: Malcolm services do NOT have no-new-privileges (entrypoint uses su)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Malcolm's docker-uid-gid-setup.sh uses `su` (setuid binary) for privilege
    # drop. no-new-privileges silently blocks the setuid bit, causing the service
    # process to never start (container exits 0 with no error output).
    local malcolm_services=(
        opensearch
        dashboards-helper
        dashboards
        logstash
        filebeat
        redis
        api
        nginx-proxy
        zeek-live
        suricata-live
        pcap-capture
        arkime-live
    )

    for svc in "${malcolm_services[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
sec_opt = svc.get('security_opt', [])
if 'no-new-privileges:true' in sec_opt:
    print('${svc} has no-new-privileges — will break Malcolm entrypoint su')
    sys.exit(1)
print('${svc}: correctly omits no-new-privileges')
"
        [ "$status" -eq 0 ]
    done
}

@test "compose: logstash has PUSER_PRIV_DROP=false with supervisord user= override" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Logstash needs PUSER_PRIV_DROP=false because after su, /proc/self/fd/1
    # becomes inaccessible (l-wx------ root root). Supervisord's stdout_logfile=
    # /dev/fd/1 fails with EACCES. With PUSER_PRIV_DROP=false, supervisord runs
    # as root (can open /dev/fd/1) and our custom supervisord.conf uses user=logstash
    # so the logstash process itself runs as non-root.
    run _compose_query "
svc = data['services']['logstash']
env = svc.get('environment', {})
priv_drop = env.get('PUSER_PRIV_DROP', 'not set')
assert priv_drop == 'false', f'logstash: PUSER_PRIV_DROP should be false, got: {priv_drop}'
# Verify custom supervisord.conf is mounted
volumes = [str(v) for v in svc.get('volumes', [])]
has_supervisord = any('supervisord.conf' in v for v in volumes)
assert has_supervisord, f'logstash: must mount custom supervisord.conf with user=logstash, volumes: {volumes}'
print('logstash: PUSER_PRIV_DROP=false + supervisord.conf override (correct)')
"
    [ "$status" -eq 0 ]
}

@test "compose: non-logstash Malcolm services do NOT set PUSER_PRIV_DROP=false" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Most Malcolm services refuse to run as root. They use the entrypoint's su
    # for privilege drop (works since no-new-privileges is removed).
    # Only logstash needs PUSER_PRIV_DROP=false (supervisord /dev/fd/1 issue).
    local malcolm_services=(
        opensearch
        dashboards-helper
        dashboards
        filebeat
        api
        nginx-proxy
        redis
    )

    for svc in "${malcolm_services[@]}"; do
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

@test "compose: opensearch sets every ROLE_* its role mapping uses (MS-001)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Malcolm's setup-internal-users.sh envsubsts roles_mapping.yml.orig and
    # deletes any entry with an empty role. These are every $ROLE_* it uses.
    run _compose_query "
env = data['services']['opensearch']['environment']
assert env.get('ROLE_ADMIN') == 'admin', 'ROLE_ADMIN must be admin (malcolm_internal backend role)'
for key in ('ROLE_CAPTURE_SERVICE', 'ROLE_READ_ACCESS', 'ROLE_READ_WRITE_ACCESS',
            'ROLE_DASHBOARDS_READ_ACCESS', 'ROLE_DASHBOARDS_READ_ALL_APPS_ACCESS',
            'ROLE_DASHBOARDS_READ_WRITE_ACCESS', 'ROLE_DASHBOARDS_READ_WRITE_ALL_APPS_ACCESS'):
    assert env.get(key), key + ' must be set'
print('opensearch roles: OK')
"
    [ "$status" -eq 0 ]
}

@test "compose: nettap-web reads the client IP from nginx's X-Real-IP and is not published (CR-034)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # Login throttling keys on getClientAddress(). Without ADDRESS_HEADER every
    # client is nginx's IP; with port 3000 published, clients could forge it.
    run _compose_query "
svc = data['services']['nettap-web']
assert svc['environment'].get('ADDRESS_HEADER') == 'x-real-ip', 'ADDRESS_HEADER must be x-real-ip'
assert not svc.get('ports'), 'nettap-web must not publish ports; only nginx may reach it'
print('nettap-web: OK')
"
    [ "$status" -eq 0 ]
    grep -Eq 'proxy_set_header[[:space:]]+X-Real-IP[[:space:]]+\$remote_addr;' "${REPO_ROOT}/docker/nginx.conf"
}

# ==========================================================================
# Capture settings from the daemon (DHCP gateway / mirror mode)
# ==========================================================================

@test "compose: capture entrypoints source the capture env loader first" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    # The loader must run before exec tini so the exported PCAP_IFACE /
    # PCAP_FILTER / CAPTURE_FILTER reach the Malcolm entrypoint.
    local capture_services=(zeek-live suricata-live pcap-capture arkime-live)

    for svc in "${capture_services[@]}"; do
        run _compose_query "
svc = data['services']['${svc}']
cmd = svc['entrypoint'][2]
assert cmd.startswith('. /usr/local/bin/nettap-capture-env.sh && mkdir -p '), '${svc}: ' + cmd[:80]
volumes = [str(v) for v in svc.get('volumes', [])]
assert '/etc/nettap:/etc/nettap:ro' in volumes, '${svc}: /etc/nettap must be mounted read-only'
assert '../config/capture/nettap-capture-env.sh:/usr/local/bin/nettap-capture-env.sh:ro' in volumes, '${svc}: loader not mounted'
print('${svc}: OK')
"
        [ "$status" -eq 0 ]
    done
    [ -f "${REPO_ROOT}/config/capture/nettap-capture-env.sh" ]
}

@test "compose: daemon can write /etc/nettap and bind the DHCP port" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['nettap-storage-daemon']
assert 'NET_BIND_SERVICE' in svc.get('cap_add', []), 'dnsmasq needs NET_BIND_SERVICE for UDP 67'
for cap in ('SETUID', 'SETGID', 'KILL'):
    assert cap in svc.get('cap_add', []), 'dnsmasq runs as nobody: daemon needs ' + cap
volumes = [str(v) for v in svc.get('volumes', [])]
assert '/etc/nettap:/etc/nettap' in volumes, 'daemon must mount /etc/nettap read-write'
print('nettap-storage-daemon: OK')
"
    [ "$status" -eq 0 ]
}

@test "compose: Arkime and Grafana secrets have no public fallback (CR-021, CR-022)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
arkime = data['services']['arkime-live']['environment']['ARKIME_PASSWORD_SECRET']
assert arkime.startswith('\${ARKIME_SECRET:?'), 'ARKIME_SECRET must be required: ' + arkime
grafana = [e for e in data['services']['nettap-grafana']['environment'] if e.startswith('GF_SECURITY_ADMIN_PASSWORD=')]
assert grafana and grafana[0].startswith('GF_SECURITY_ADMIN_PASSWORD=\${GRAFANA_ADMIN_PASSWORD:?'), grafana
print('secrets: OK')
"
    [ "$status" -eq 0 ]
    ! grep -v '^[[:space:]]*#' "$COMPOSE_FILE" | grep -q 'NetTap_Arkime_Secret'
}

@test "compose: Arkime viewer is pinned to loopback (CR-021)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
cmd = data['services']['arkime-live']['entrypoint'][2]
pin = \"sed -i 's/^viewHost=.*/viewHost=127.0.0.1/' /opt/arkime/etc/config*.ini\"
assert pin in cmd, cmd
assert cmd.index(pin) < cmd.index('exec /usr/bin/tini'), 'pin must run before Arkime starts'
print('viewHost: OK')
"
    [ "$status" -eq 0 ]
}

@test "compose: daemon can delete PCAP (CR-001)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
svc = data['services']['nettap-storage-daemon']
volumes = [str(v) for v in svc.get('volumes', [])]
assert 'pcap-data:/opt/nettap/pcap' in volumes, 'pcap-data must be mounted read-write: ' + str(volumes)
assert svc['environment']['PCAP_DIR'] == '/opt/nettap/pcap', 'PCAP_DIR must match the mount'
assert 'DAC_OVERRIDE' in svc.get('cap_add', []), 'root needs DAC_OVERRIDE to unlink in uid-1000 PCAP folders'
print('pcap mount: OK')
"
    [ "$status" -eq 0 ]
}

@test "compose: netsniff is the only PCAP writer (CR-020, MS-002)" {
    if ! _has_pyyaml; then
        skip "PyYAML not available"
    fi

    run _compose_query "
arkime = data['services']['arkime-live']['environment']
assert arkime.get('ARKIME_PCAP_WRITE_METHOD') == 'null', 'Arkime must not write PCAP: ' + repr(arkime.get('ARKIME_PCAP_WRITE_METHOD'))
assert data['services']['pcap-capture']['environment']['PCAP_ENABLE_NETSNIFF'] == 'true'
print('pcap writer: OK')
"
    [ "$status" -eq 0 ]
}
