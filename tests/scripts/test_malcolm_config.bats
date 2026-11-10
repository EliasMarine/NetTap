#!/usr/bin/env bats
# ==========================================================================
# BATS tests for scripts/install/malcolm-config.sh
# ==========================================================================
# Tests certificate generation, curlrc credentials, nginx SSL, auth files,
# .env generation, and heap sizing logic.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"

load 'helpers/setup'

# Source the script under test (functions only, not the standalone block)
_source_malcolm_config() {
    # common.sh defines its own run() (the installer's dry-run wrapper), which replaces bats'
    # run; keep bats' copy as bats_run for the tests that need $status and $output
    eval "bats_run() $(declare -f run | tail -n +2)"
    # Source common.sh and the script under test
    source "${REPO_ROOT}/scripts/common.sh"
    source "${BATS_TEST_DIRNAME}/helpers/mocks.bash"
    source "${REPO_ROOT}/scripts/install/malcolm-config.sh"

    # CRITICAL: malcolm-config.sh sets PROJECT_ROOT from SCRIPT_DIR on source,
    # pointing to the REAL project root. We must override AFTER sourcing so
    # functions write to our test temp dir instead of the real project.
    export PROJECT_ROOT="${TEST_TMPDIR}"
    export CERTS_DIR="${TEST_TMPDIR}/docker/certs"
    export AUTH_DIR="${TEST_TMPDIR}/docker/auth"
    mkdir -p "${TEST_TMPDIR}/docker"  # the real repo always has it; generate_compose_env writes there

    # OLD CODE START — +e also switched off bats' own errexit, so a failed assertion before
    # a test's last line was ignored and the test passed anyway
    # # Reset strict mode — set -euo pipefail from the sourced scripts breaks
    # # BATS test isolation (unbound $status, premature exits on assertion failures)
    # set +euo pipefail
    # OLD CODE END
    # Drop the sourced scripts' -u and pipefail (unbound $status); keep -e, which is how bats fails a test
    set +uo pipefail
}

# ==========================================================================
# generate_certs
# ==========================================================================

@test "generate_certs: creates CA and server certificates" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"

    [ -f "${TEST_TMPDIR}/docker/certs/ca.crt" ]
    [ -f "${TEST_TMPDIR}/docker/certs/ca.key" ]
    [ -f "${TEST_TMPDIR}/docker/certs/server.crt" ]
    [ -f "${TEST_TMPDIR}/docker/certs/server.key" ]
}

@test "generate_certs: CA cert is a valid x509 certificate" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"

    bats_run openssl x509 -in "${TEST_TMPDIR}/docker/certs/ca.crt" -noout -text
    [ "$status" -eq 0 ]
    [[ "$output" == *"Issuer:"*"NetTap CA"* ]]
}

@test "generate_certs: server cert is signed by the CA" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"

    bats_run openssl verify \
        -CAfile "${TEST_TMPDIR}/docker/certs/ca.crt" \
        "${TEST_TMPDIR}/docker/certs/server.crt"
    [ "$status" -eq 0 ]
}

@test "generate_certs: server cert includes SAN entries for service hostnames" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"

    local san_output
    san_output=$(openssl x509 -in "${TEST_TMPDIR}/docker/certs/server.crt" -noout -text \
        | grep -A1 "Subject Alternative Name")

    [[ "$san_output" == *"opensearch"* ]]
    [[ "$san_output" == *"dashboards"* ]]
    [[ "$san_output" == *"logstash"* ]]
    [[ "$san_output" == *"localhost"* ]]
}

@test "generate_certs: key files have 600 permissions" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"

    local ca_perms server_perms
    ca_perms=$(stat -f '%Lp' "${TEST_TMPDIR}/docker/certs/ca.key" 2>/dev/null || \
               stat -c '%a' "${TEST_TMPDIR}/docker/certs/ca.key" 2>/dev/null)
    server_perms=$(stat -f '%Lp' "${TEST_TMPDIR}/docker/certs/server.key" 2>/dev/null || \
                   stat -c '%a' "${TEST_TMPDIR}/docker/certs/server.key" 2>/dev/null)

    [ "$ca_perms" = "600" ]
    [ "$server_perms" = "600" ]
}

@test "generate_certs: cert files have 644 permissions" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"

    local ca_perms server_perms
    ca_perms=$(stat -f '%Lp' "${TEST_TMPDIR}/docker/certs/ca.crt" 2>/dev/null || \
               stat -c '%a' "${TEST_TMPDIR}/docker/certs/ca.crt" 2>/dev/null)
    server_perms=$(stat -f '%Lp' "${TEST_TMPDIR}/docker/certs/server.crt" 2>/dev/null || \
                   stat -c '%a' "${TEST_TMPDIR}/docker/certs/server.crt" 2>/dev/null)

    [ "$ca_perms" = "644" ]
    [ "$server_perms" = "644" ]
}

@test "generate_certs: skips if certificates already exist (idempotent)" {
    _source_malcolm_config

    # First run — creates certs
    generate_certs "${TEST_TMPDIR}/docker/certs"
    local first_hash
    first_hash=$(openssl x509 -in "${TEST_TMPDIR}/docker/certs/ca.crt" -noout -fingerprint)

    # Second run — should skip
    generate_certs "${TEST_TMPDIR}/docker/certs"
    local second_hash
    second_hash=$(openssl x509 -in "${TEST_TMPDIR}/docker/certs/ca.crt" -noout -fingerprint)

    # Cert should be identical (not regenerated)
    [ "$first_hash" = "$second_hash" ]
}

@test "generate_certs: cleans up temp files (CSR, extension, serial)" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"

    [ ! -f "${TEST_TMPDIR}/docker/certs/server.csr" ]
    [ ! -f "${TEST_TMPDIR}/docker/certs/server-ext.cnf" ]
    [ ! -f "${TEST_TMPDIR}/docker/certs/ca.srl" ]
}

# ==========================================================================
# generate_nginx_ssl
# ==========================================================================

@test "generate_nginx_ssl: creates nettap.crt and nettap.key" {
    _source_malcolm_config

    # Must generate CA first
    generate_certs "${TEST_TMPDIR}/docker/certs"
    generate_nginx_ssl

    [ -f "${TEST_TMPDIR}/docker/ssl/nettap.crt" ]
    [ -f "${TEST_TMPDIR}/docker/ssl/nettap.key" ]
}

@test "generate_nginx_ssl: cert is signed by the shared CA" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"
    generate_nginx_ssl

    bats_run openssl verify \
        -CAfile "${TEST_TMPDIR}/docker/certs/ca.crt" \
        "${TEST_TMPDIR}/docker/ssl/nettap.crt"
    [ "$status" -eq 0 ]
}

@test "generate_nginx_ssl: cert includes nettap.local SAN" {
    _source_malcolm_config
    export NETTAP_HOSTNAME="nettap.local"

    generate_certs "${TEST_TMPDIR}/docker/certs"
    generate_nginx_ssl

    local san_output
    san_output=$(openssl x509 -in "${TEST_TMPDIR}/docker/ssl/nettap.crt" -noout -text \
        | grep -A1 "Subject Alternative Name")

    [[ "$san_output" == *"nettap.local"* ]]
    [[ "$san_output" == *"localhost"* ]]
}

@test "generate_nginx_ssl: key has 600 permissions, cert has 644" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"
    generate_nginx_ssl

    local key_perms cert_perms
    key_perms=$(stat -f '%Lp' "${TEST_TMPDIR}/docker/ssl/nettap.key" 2>/dev/null || \
                stat -c '%a' "${TEST_TMPDIR}/docker/ssl/nettap.key" 2>/dev/null)
    cert_perms=$(stat -f '%Lp' "${TEST_TMPDIR}/docker/ssl/nettap.crt" 2>/dev/null || \
                 stat -c '%a' "${TEST_TMPDIR}/docker/ssl/nettap.crt" 2>/dev/null)

    [ "$key_perms" = "600" ]
    [ "$cert_perms" = "644" ]
}

@test "generate_nginx_ssl: skips if certs already exist (idempotent)" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"
    generate_nginx_ssl

    local first_hash
    first_hash=$(openssl x509 -in "${TEST_TMPDIR}/docker/ssl/nettap.crt" -noout -fingerprint)

    generate_nginx_ssl

    local second_hash
    second_hash=$(openssl x509 -in "${TEST_TMPDIR}/docker/ssl/nettap.crt" -noout -fingerprint)

    [ "$first_hash" = "$second_hash" ]
}

@test "generate_nginx_ssl: fails if CA does not exist" {
    _source_malcolm_config

    # Don't generate CA — should fail with error (exit 1)
    # Run in subshell since error() calls exit 1
    bats_run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        source '${REPO_ROOT}/scripts/install/malcolm-config.sh'
        export PROJECT_ROOT='${TEST_TMPDIR}'
        generate_nginx_ssl
    "
    [ "$status" -ne 0 ]
}

@test "generate_nginx_ssl: cleans up temp files" {
    _source_malcolm_config

    generate_certs "${TEST_TMPDIR}/docker/certs"
    generate_nginx_ssl

    [ ! -f "${TEST_TMPDIR}/docker/ssl/nettap.csr" ]
    [ ! -f "${TEST_TMPDIR}/docker/ssl/nettap-ext.cnf" ]
}

# ==========================================================================
# generate_curlrc
# ==========================================================================

@test "generate_curlrc: creates curlrc file with correct format" {
    _source_malcolm_config

    generate_curlrc

    local curlrc_file="${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc"
    [ -f "$curlrc_file" ]

    # Must contain user: line with malcolm_internal
    grep -q '^user: "malcolm_internal:' "$curlrc_file"
    # Must contain insecure flag
    grep -q '^insecure$' "$curlrc_file"
}

# OLD CODE START — the file used to be world-readable (644); now PUID-owned 600
# @test "generate_curlrc: file has 644 permissions (not 600 — container user must read)" {
#     ... asserted perms = 644
# }
# OLD CODE END

_mode() { stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1" 2>/dev/null; }

@test "generate_curlrc: owned by the compose PUID, readable by nobody else" {
    _source_malcolm_config
    chown() { echo "$*" > "${TEST_TMPDIR}/chown.args"; }
    mkdir -p "${TEST_TMPDIR}/docker"
    printf 'PUID=1234\nPGID=5678\n' > "${TEST_TMPDIR}/docker/.env"

    generate_curlrc

    local file="${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc"
    [ "$(_mode "$file")" = "600" ]
    [ "$(cat "${TEST_TMPDIR}/chown.args")" = "1234:5678 ${file}" ]
}

# Run generate_curlrc the way install.sh does: the real scripts, set -euo pipefail, chown recorded
_strict_generate_curlrc() {
    bats_run bash -c "
        source '${REPO_ROOT}/scripts/common.sh'
        source '${REPO_ROOT}/scripts/install/malcolm-config.sh'
        set -euo pipefail
        PROJECT_ROOT='${TEST_TMPDIR}'
        chown() { echo \"\$*\" > '${TEST_TMPDIR}/chown.args'; }
        generate_curlrc"
}

@test "generate_curlrc: works on a fresh install, before docker/.env exists, under the installer's strict mode" {
    # NET-246: every fresh install stopped at step 5 here. _source_malcolm_config drops pipefail,
    # which hid the bug, so this runs the function with the installer's own set -euo pipefail.
    _source_malcolm_config
    rm -f "${TEST_TMPDIR}/docker/.env"
    export SUDO_UID=1234 SUDO_GID=5678  # not the 1000 default, so the fallback really reads them

    _strict_generate_curlrc

    [ "$status" -eq 0 ]
    local file="${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc"
    [ "$(_mode "$file")" = "600" ]
    [ "$(cat "${TEST_TMPDIR}/chown.args")" = "1234:5678 ${file}" ]  # same fallback as generate_compose_env
}

@test "generate_curlrc: a stale PUID=0 in docker/.env gives the file to the sudo user, as the rewritten .env will" {
    _source_malcolm_config
    printf 'PUID=0\nPGID=0\n' > "${TEST_TMPDIR}/docker/.env"
    export SUDO_UID=1234 SUDO_GID=5678

    _strict_generate_curlrc

    [ "$status" -eq 0 ]
    [ "$(cut -d' ' -f1 "${TEST_TMPDIR}/chown.args")" = "1234:5678" ]
}

@test "generate_curlrc: a root install with no docker/.env gives the file to 1000, like the compose PUID" {
    _source_malcolm_config
    rm -f "${TEST_TMPDIR}/docker/.env"
    export SUDO_UID=0 SUDO_GID=0

    _strict_generate_curlrc

    [ "$status" -eq 0 ]
    [ "$(cut -d' ' -f1 "${TEST_TMPDIR}/chown.args")" = "1000:1000" ]
}

@test "generate_curlrc: locks a world-readable file from an earlier install" {
    _source_malcolm_config
    chown() { return 0; }
    local file="${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc"
    mkdir -p "$(dirname "$file")"
    printf 'user: "malcolm_internal:x"\n' > "$file"
    chmod 644 "$file"

    generate_curlrc

    [ "$(_mode "$file")" = "600" ]
    grep -q 'malcolm_internal:x' "$file"  # credentials kept
}

@test "generate_curlrc: stays 644 if the owner can't be changed (OpenSearch must still read it)" {
    _source_malcolm_config
    chown() { return 1; }

    generate_curlrc

    [ "$(_mode "${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc")" = "644" ]
}

@test "generate_curlrc: generates a non-empty password" {
    _source_malcolm_config

    generate_curlrc

    local curlrc_file="${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc"
    local password
    password=$(grep '^user:' "$curlrc_file" | sed 's/.*malcolm_internal:\(.*\)"/\1/')

    [ -n "$password" ]
    # Password should be at least 20 chars (we generate 36)
    [ "${#password}" -ge 20 ]
}

@test "generate_curlrc: skips if file already exists (idempotent)" {
    _source_malcolm_config

    generate_curlrc

    local curlrc_file="${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc"
    local first_password
    first_password=$(grep '^user:' "$curlrc_file")

    generate_curlrc

    local second_password
    second_password=$(grep '^user:' "$curlrc_file")

    # Password should be identical (not regenerated)
    [ "$first_password" = "$second_password" ]
}

@test "generate_curlrc: removes stale directory artifact from failed Docker run" {
    _source_malcolm_config

    # Simulate Docker creating the path as a directory
    mkdir -p "${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc"

    generate_curlrc

    # Should now be a file, not a directory
    [ -f "${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc" ]
    [ ! -d "${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc" ]
}

# ==========================================================================
# generate_auth
# ==========================================================================

@test "generate_auth: creates htpasswd file" {
    _source_malcolm_config

    generate_auth "${TEST_TMPDIR}/docker/auth"

    [ -f "${TEST_TMPDIR}/docker/auth/htpasswd" ]
}

@test "generate_auth: htpasswd contains the admin user" {
    _source_malcolm_config
    export NETTAP_ADMIN_USER="admin"

    generate_auth "${TEST_TMPDIR}/docker/auth"

    grep -q "^admin:" "${TEST_TMPDIR}/docker/auth/htpasswd"
}

@test "generate_auth: generates random password file when none provided" {
    _source_malcolm_config
    unset NETTAP_ADMIN_PASSWORD

    generate_auth "${TEST_TMPDIR}/docker/auth"

    [ -f "${TEST_TMPDIR}/docker/auth/.admin-password" ]

    local password
    password=$(cat "${TEST_TMPDIR}/docker/auth/.admin-password")
    [ -n "$password" ]
    [ "${#password}" -ge 10 ]
}

@test "generate_auth: password file has 600 permissions" {
    _source_malcolm_config
    unset NETTAP_ADMIN_PASSWORD

    generate_auth "${TEST_TMPDIR}/docker/auth"

    local perms
    perms=$(stat -f '%Lp' "${TEST_TMPDIR}/docker/auth/.admin-password" 2>/dev/null || \
            stat -c '%a' "${TEST_TMPDIR}/docker/auth/.admin-password" 2>/dev/null)

    [ "$perms" = "600" ]
}

@test "generate_auth: skips if htpasswd already exists (idempotent)" {
    _source_malcolm_config

    generate_auth "${TEST_TMPDIR}/docker/auth"
    local first_hash
    first_hash=$(md5sum "${TEST_TMPDIR}/docker/auth/htpasswd" 2>/dev/null || \
                 md5 -q "${TEST_TMPDIR}/docker/auth/htpasswd" 2>/dev/null)

    generate_auth "${TEST_TMPDIR}/docker/auth"
    local second_hash
    second_hash=$(md5sum "${TEST_TMPDIR}/docker/auth/htpasswd" 2>/dev/null || \
                  md5 -q "${TEST_TMPDIR}/docker/auth/htpasswd" 2>/dev/null)

    [ "$first_hash" = "$second_hash" ]
}

# ==========================================================================
# generate_compose_env
# ==========================================================================

@test "generate_compose_env: creates .env with non-root PUID" {
    _source_malcolm_config
    # Simulate running under sudo as user 1000
    export SUDO_UID=1000
    export SUDO_GID=1000

    generate_compose_env

    local env_file="${TEST_TMPDIR}/docker/.env"
    [ -f "$env_file" ]
    grep -q "^PUID=1000$" "$env_file"
    grep -q "^PGID=1000$" "$env_file"
}

@test "generate_compose_env: falls back to 1000 when SUDO_UID is 0" {
    _source_malcolm_config
    export SUDO_UID=0
    export SUDO_GID=0

    generate_compose_env

    local env_file="${TEST_TMPDIR}/docker/.env"
    grep -q "^PUID=1000$" "$env_file"
    grep -q "^PGID=1000$" "$env_file"
}

@test "generate_compose_env: falls back to 1000 when SUDO_UID is unset" {
    _source_malcolm_config
    unset SUDO_UID
    unset SUDO_GID

    generate_compose_env

    local env_file="${TEST_TMPDIR}/docker/.env"
    grep -q "^PUID=1000$" "$env_file"
    grep -q "^PGID=1000$" "$env_file"
}

@test "generate_compose_env: regenerates when existing PUID=0 detected" {
    _source_malcolm_config
    export SUDO_UID=1000
    export SUDO_GID=1000

    # Create a bad .env with PUID=0
    mkdir -p "${TEST_TMPDIR}/docker"
    cat > "${TEST_TMPDIR}/docker/.env" <<'EOF'
PUID=0
PGID=0
EOF

    generate_compose_env

    # Should have been regenerated with correct values
    grep -q "^PUID=1000$" "${TEST_TMPDIR}/docker/.env"
    # PUID=0 should no longer exist
    ! grep -q "^PUID=0$" "${TEST_TMPDIR}/docker/.env"
}

# _source_malcolm_config turns set -e off, and then a failing assertion does
# not fail the test at all. These tests turn it back on after the call.
@test "generate_compose_env: new .env gets random Arkime and Grafana secrets (CR-021, CR-022)" {
    _source_malcolm_config
    unset ARKIME_SECRET GRAFANA_ADMIN_PASSWORD
    mkdir -p "${TEST_TMPDIR}/docker"

    generate_compose_env
    set -e

    local env_file="${TEST_TMPDIR}/docker/.env"
    grep -Eq "^ARKIME_SECRET=[0-9a-f]{32}$" "$env_file"
    grep -Eq "^GRAFANA_ADMIN_PASSWORD=[0-9a-f]{32}$" "$env_file"
    # (common.sh's own run() shadows bats' run here)
    [ "$(grep -c "NetTap_Arkime_Secret" "$env_file")" -eq 0 ]
}

@test "generate_compose_env: adds missing secrets to an existing .env, keeps the rest (CR-021)" {
    _source_malcolm_config
    mkdir -p "${TEST_TMPDIR}/docker"
    printf 'PUID=1000\nREDIS_PASSWORD=keepme\nARKIME_SECRET=\n' > "${TEST_TMPDIR}/docker/.env"

    generate_compose_env
    set -e

    local env_file="${TEST_TMPDIR}/docker/.env"
    grep -q "^PUID=1000$" "$env_file"
    grep -q "^REDIS_PASSWORD=keepme$" "$env_file"
    [ "$(grep -c '^ARKIME_SECRET=' "$env_file")" -eq 1 ]
    grep -Eq "^ARKIME_SECRET=[0-9a-f]{32}$" "$env_file"
    grep -Eq "^GRAFANA_ADMIN_PASSWORD=[0-9a-f]{32}$" "$env_file"
}

@test "generate_compose_env: never changes a secret that is already set" {
    _source_malcolm_config
    mkdir -p "${TEST_TMPDIR}/docker"
    printf 'PUID=1000\nARKIME_SECRET=abc\nGRAFANA_ADMIN_PASSWORD=def\n' > "${TEST_TMPDIR}/docker/.env"

    generate_compose_env
    set -e

    grep -q "^ARKIME_SECRET=abc$" "${TEST_TMPDIR}/docker/.env"
    grep -q "^GRAFANA_ADMIN_PASSWORD=def$" "${TEST_TMPDIR}/docker/.env"
}

# NET-224: compose reads only docker/.env, so the root .env's notification names must land there
_unset_notification_env() {
    unset SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_SENDER_EMAIL \
        ALERT_EMAIL WEBHOOK_URL ALERT_SEVERITY_THRESHOLD
}

@test "generate_compose_env: a new .env gets the notification names, taken as written" {
    _source_malcolm_config
    _unset_notification_env
    export SMTP_HOST=smtp.example.net
    export SMTP_PASSWORD='pa$$word #1'
    export ALERT_EMAIL='a@example.net, b@example.net'

    generate_compose_env
    set -e

    local env_file="${TEST_TMPDIR}/docker/.env"
    grep -qx "SMTP_HOST='smtp.example.net'" "$env_file"
    grep -qx "SMTP_PASSWORD='pa\$\$word #1'" "$env_file"
    [ "$(grep -c '^WEBHOOK_URL=' "$env_file")" -eq 0 ]
    [ "$(stat -c %a "$env_file" 2>/dev/null || stat -f %Lp "$env_file")" = "600" ]
    # bash reads it back unchanged (compose's dotenv takes single quotes literally too)
    [ "$(set -a; source "$env_file"; printf '%s' "$SMTP_PASSWORD")" = 'pa$$word #1' ]
    [ "$(set -a; source "$env_file"; printf '%s' "$ALERT_EMAIL")" = 'a@example.net, b@example.net' ]
}

@test "generate_compose_env: an existing .env gets the values replaced once, others kept" {
    _source_malcolm_config
    _unset_notification_env
    printf "PUID=1000\nARKIME_SECRET=abc\nGRAFANA_ADMIN_PASSWORD=def\nSMTP_HOST='old.example.net'\nWEBHOOK_URL='https://hooks.example.net/x'\n" > "${TEST_TMPDIR}/docker/.env"
    export SMTP_HOST=smtp.example.net

    generate_compose_env
    generate_compose_env
    set -e

    local env_file="${TEST_TMPDIR}/docker/.env"
    [ "$(grep -c '^SMTP_HOST=' "$env_file")" -eq 1 ]
    grep -qx "SMTP_HOST='smtp.example.net'" "$env_file"
    grep -qx "WEBHOOK_URL='https://hooks.example.net/x'" "$env_file"
    grep -q "^ARKIME_SECRET=abc$" "$env_file"
}

@test "generate_compose_env: a value with a quote is skipped with a warning, the rest still copied" {
    _source_malcolm_config
    _unset_notification_env
    export SMTP_PASSWORD="it's secret"
    export SMTP_HOST=smtp.example.net

    output=$(generate_compose_env 2>&1)
    set -e

    local env_file="${TEST_TMPDIR}/docker/.env"
    [ "$(grep -c '^SMTP_PASSWORD=' "$env_file")" -eq 0 ]
    grep -qx "SMTP_HOST='smtp.example.net'" "$env_file"
    [[ "$output" == *"SMTP_PASSWORD has a quote or line break"* ]]
    [[ "$output" != *"it's secret"* ]]
}

@test "generate_compose_env: includes heap sizes" {
    _source_malcolm_config
    export SUDO_UID=1000

    generate_compose_env

    local env_file="${TEST_TMPDIR}/docker/.env"
    grep -q "^OPENSEARCH_JAVA_OPTS=" "$env_file"
    grep -q "^LS_JAVA_OPTS=" "$env_file"
}

@test "generate_compose_env: includes Malcolm image tag" {
    _source_malcolm_config
    export SUDO_UID=1000

    generate_compose_env

    local env_file="${TEST_TMPDIR}/docker/.env"
    grep -q "^MALCOLM_IMAGE_TAG=26.10.0$" "$env_file"
}

# ==========================================================================
# calculate_heap_sizes
# ==========================================================================

@test "calculate_heap_sizes: 16GB system gets 4g OpenSearch, 2g Logstash" {
    _source_malcolm_config

    # Override /proc/meminfo for 16GB
    local meminfo="${TEST_TMPDIR}/proc_meminfo"
    echo "MemTotal:       16384000 kB" > "$meminfo"

    # Monkey-patch calculate_heap_sizes to read our mock
    calculate_heap_sizes() {
        local ram_mb
        ram_mb=$(awk '/^MemTotal:/ {print int($2/1024)}' "$meminfo")
        if (( ram_mb >= 14000 )); then
            OPENSEARCH_HEAP="4g"
            LOGSTASH_HEAP="2g"
        fi
    }

    calculate_heap_sizes

    [ "$OPENSEARCH_HEAP" = "4g" ]
    [ "$LOGSTASH_HEAP" = "2g" ]
}

@test "calculate_heap_sizes: 32GB system gets 8g OpenSearch, 4g Logstash" {
    _source_malcolm_config

    local meminfo="${TEST_TMPDIR}/proc_meminfo"
    echo "MemTotal:       32768000 kB" > "$meminfo"

    calculate_heap_sizes() {
        local ram_mb
        ram_mb=$(awk '/^MemTotal:/ {print int($2/1024)}' "$meminfo")
        if (( ram_mb >= 30000 )); then
            OPENSEARCH_HEAP="8g"
            LOGSTASH_HEAP="4g"
        fi
    }

    calculate_heap_sizes

    [ "$OPENSEARCH_HEAP" = "8g" ]
    [ "$LOGSTASH_HEAP" = "4g" ]
}

@test "calculate_heap_sizes: 8GB system gets 2g OpenSearch, 1g Logstash" {
    _source_malcolm_config

    local meminfo="${TEST_TMPDIR}/proc_meminfo"
    echo "MemTotal:       8192000 kB" > "$meminfo"

    calculate_heap_sizes() {
        local ram_mb
        ram_mb=$(awk '/^MemTotal:/ {print int($2/1024)}' "$meminfo")
        if (( ram_mb < 10000 )); then
            OPENSEARCH_HEAP="2g"
            LOGSTASH_HEAP="1g"
        fi
    }

    calculate_heap_sizes

    [ "$OPENSEARCH_HEAP" = "2g" ]
    [ "$LOGSTASH_HEAP" = "1g" ]
}

# ==========================================================================
# create_support_dirs
# ==========================================================================

@test "create_support_dirs: creates ca-trust directory" {
    _source_malcolm_config

    create_support_dirs

    [ -d "${TEST_TMPDIR}/docker/ca-trust" ]
}

# ==========================================================================
# configure_malcolm (integration)
# ==========================================================================

@test "configure_malcolm: runs full config pipeline without errors" {
    _source_malcolm_config
    export SUDO_UID=1000
    export SUDO_GID=1000

    bats_run configure_malcolm
    [ "$status" -eq 0 ]

    # Verify all outputs exist
    [ -f "${TEST_TMPDIR}/docker/certs/ca.crt" ]
    [ -f "${TEST_TMPDIR}/docker/certs/server.crt" ]
    [ -f "${TEST_TMPDIR}/docker/ssl/nettap.crt" ]
    [ -f "${TEST_TMPDIR}/docker/ssl/nettap.key" ]
    [ -f "${TEST_TMPDIR}/docker/auth/htpasswd" ]
    [ -f "${TEST_TMPDIR}/docker/curlrc/.opensearch.primary.curlrc" ]
    [ -d "${TEST_TMPDIR}/docker/ca-trust" ]
    [ -f "${TEST_TMPDIR}/docker/.env" ]
}

@test "configure_malcolm: is fully idempotent (second run succeeds)" {
    _source_malcolm_config
    export SUDO_UID=1000

    configure_malcolm
    bats_run configure_malcolm
    [ "$status" -eq 0 ]
}
