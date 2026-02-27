#!/usr/bin/env bash
# NetTap — Malcolm configuration generator
# Generates SSL certificates, auth files, and environment configs
# required by the Malcolm containers in NetTap's docker-compose.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CERTS_DIR="${PROJECT_ROOT}/docker/certs"
AUTH_DIR="${PROJECT_ROOT}/docker/auth"

# ---------------------------------------------------------------------------
# Generate self-signed SSL certificates for internal service communication
# ---------------------------------------------------------------------------
generate_certs() {
    local certs_dir="$1"

    if [[ -f "${certs_dir}/ca.crt" && -f "${certs_dir}/server.crt" ]]; then
        log "SSL certificates already exist in ${certs_dir}, skipping generation"
        return 0
    fi

    log "Generating self-signed SSL certificates..."
    mkdir -p "$certs_dir"

    # Generate CA key and certificate
    run openssl genrsa -out "${certs_dir}/ca.key" 2048
    run openssl req -x509 -new -nodes \
        -key "${certs_dir}/ca.key" \
        -sha256 -days 3650 \
        -out "${certs_dir}/ca.crt" \
        -subj "/C=US/ST=NetTap/L=Local/O=NetTap/OU=CA/CN=NetTap CA"

    # Generate server key and CSR
    run openssl genrsa -out "${certs_dir}/server.key" 2048
    run openssl req -new \
        -key "${certs_dir}/server.key" \
        -out "${certs_dir}/server.csr" \
        -subj "/C=US/ST=NetTap/L=Local/O=NetTap/OU=Server/CN=localhost"

    # Create SAN extension file for modern TLS
    cat > "${certs_dir}/server-ext.cnf" <<EXTEOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = opensearch
DNS.3 = dashboards
DNS.4 = logstash
DNS.5 = nginx-proxy
DNS.6 = arkime
DNS.7 = api
DNS.8 = nettap-opensearch
DNS.9 = nettap-dashboards
DNS.10 = nettap-logstash
DNS.11 = nettap-nginx-proxy
DNS.12 = nettap-arkime-live
DNS.13 = nettap-api
DNS.14 = ${NETTAP_HOSTNAME:-nettap.local}
IP.1 = 127.0.0.1
EXTEOF

    # Sign server cert with CA
    run openssl x509 -req \
        -in "${certs_dir}/server.csr" \
        -CA "${certs_dir}/ca.crt" \
        -CAkey "${certs_dir}/ca.key" \
        -CAcreateserial \
        -out "${certs_dir}/server.crt" \
        -days 3650 \
        -sha256 \
        -extfile "${certs_dir}/server-ext.cnf"

    # Clean up CSR and extension file
    rm -f "${certs_dir}/server.csr" "${certs_dir}/server-ext.cnf" "${certs_dir}/ca.srl"

    # Set permissions
    chmod 600 "${certs_dir}"/*.key
    chmod 644 "${certs_dir}"/*.crt

    log "SSL certificates generated in ${certs_dir}"
}

# ---------------------------------------------------------------------------
# Generate htpasswd for basic auth (used by nginx-proxy)
# ---------------------------------------------------------------------------
generate_auth() {
    local auth_dir="$1"
    local username="${NETTAP_ADMIN_USER:-admin}"
    local password="${NETTAP_ADMIN_PASSWORD:-}"

    mkdir -p "$auth_dir"

    if [[ -f "${auth_dir}/htpasswd" ]]; then
        log "Auth file already exists in ${auth_dir}, skipping generation"
        return 0
    fi

    # Generate a random password if none provided
    if [[ -z "$password" ]]; then
        password=$(openssl rand -base64 16 | tr -d '=/+' | head -c 16)
        log "Generated random admin password (saved to ${auth_dir}/.admin-password)"
        echo "$password" > "${auth_dir}/.admin-password"
        chmod 600 "${auth_dir}/.admin-password"
    fi

    log "Creating htpasswd for user '${username}'..."

    # Use openssl to generate bcrypt-compatible password hash
    # htpasswd format: username:{SSHA}hash or username:$2y$...
    if command -v htpasswd &>/dev/null; then
        run htpasswd -bcB "${auth_dir}/htpasswd" "$username" "$password"
    else
        # Fallback: use Python to generate Apache-compatible hash
        local hash
        hash=$(python3 -c "
import hashlib, base64, os
salt = os.urandom(16)
h = hashlib.sha1(b'${password}' + salt).digest()
print('{SSHA}' + base64.b64encode(h + salt).decode())
")
        echo "${username}:${hash}" > "${auth_dir}/htpasswd"
    fi

    chmod 644 "${auth_dir}/htpasswd"
    log "Auth file created for user '${username}'"
}

# ---------------------------------------------------------------------------
# Generate OpenSearch internal credentials (curlrc format)
# Malcolm's entrypoint reads this file to set up the admin user and hashes
# the password into internal_users.yml via setup-internal-users.sh.
# ---------------------------------------------------------------------------
generate_curlrc() {
    local curlrc_dir="${PROJECT_ROOT}/docker/curlrc"
    local curlrc_file="${curlrc_dir}/.opensearch.primary.curlrc"

    if [[ -f "$curlrc_file" ]]; then
        log "OpenSearch credentials already exist, skipping"
        return 0
    fi

    # Docker creates missing bind-mount sources as directories. If a previous
    # failed run left .opensearch.primary.curlrc as a directory, remove it.
    if [[ -d "$curlrc_file" ]]; then
        warn "Removing stale directory artifact at ${curlrc_file}"
        rm -rf "$curlrc_file"
    fi

    mkdir -p "$curlrc_dir"

    local os_password
    os_password=$(openssl rand -base64 48 | tr -d '=/+' | head -c 36)

    log "Generating OpenSearch internal credentials..."
    cat > "$curlrc_file" <<CURLRC
user: "malcolm_internal:${os_password}"
insecure
CURLRC

    chmod 600 "$curlrc_file"
    log "OpenSearch credentials generated in ${curlrc_dir}"
}

# ---------------------------------------------------------------------------
# Create support directories required by Malcolm containers
# ---------------------------------------------------------------------------
create_support_dirs() {
    # ca-trust: mounted into containers for custom CA certificate import
    mkdir -p "${PROJECT_ROOT}/docker/ca-trust"
}

# ---------------------------------------------------------------------------
# Detect available RAM and tune JVM heap sizes
# ---------------------------------------------------------------------------
calculate_heap_sizes() {
    local ram_mb
    if [[ -f /proc/meminfo ]]; then
        ram_mb=$(awk '/^MemTotal:/ {print int($2/1024)}' /proc/meminfo)
    else
        # Fallback for macOS/dev
        ram_mb=16384
    fi

    if (( ram_mb >= 30000 )); then
        # 32GB+ systems: generous heap
        OPENSEARCH_HEAP="8g"
        LOGSTASH_HEAP="4g"
    elif (( ram_mb >= 14000 )); then
        # 16GB systems (target hardware)
        OPENSEARCH_HEAP="4g"
        LOGSTASH_HEAP="2g"
    elif (( ram_mb >= 10000 )); then
        # 12GB systems
        OPENSEARCH_HEAP="3g"
        LOGSTASH_HEAP="1500m"
    else
        # 8GB systems (minimum)
        OPENSEARCH_HEAP="2g"
        LOGSTASH_HEAP="1g"
        warn "System has only ${ram_mb}MB RAM. Performance will be limited."
    fi

    log "RAM detected: ${ram_mb}MB → OpenSearch heap: ${OPENSEARCH_HEAP}, Logstash heap: ${LOGSTASH_HEAP}"
}

# ---------------------------------------------------------------------------
# Generate the .env file for docker-compose variable substitution
# ---------------------------------------------------------------------------
generate_compose_env() {
    local env_file="${PROJECT_ROOT}/docker/.env"

    # If existing .env has PUID=0, it was generated under sudo and needs
    # regeneration — OpenSearch refuses to run as root.
    if [[ -f "$env_file" ]] && grep -q '^PUID=0$' "$env_file"; then
        warn "Existing .env has PUID=0 (root) — regenerating with non-root UID"
        rm -f "$env_file"
    fi

    if [[ -f "$env_file" ]]; then
        log "Docker .env already exists at ${env_file}, skipping generation"
        return 0
    fi

    calculate_heap_sizes

    # Determine non-root UID/GID for container processes.
    # Install runs under sudo, so id -u returns 0. Use SUDO_UID (the real
    # user who invoked sudo) or fall back to 1000 (Malcolm's default).
    local puid="${SUDO_UID:-1000}"
    local pgid="${SUDO_GID:-1000}"
    if (( puid == 0 )); then
        puid=1000
        pgid=1000
    fi

    log "Generating docker-compose .env file..."
    cat > "$env_file" <<ENVEOF
# ==========================================================================
# NetTap Docker Compose Environment
# Generated by malcolm-config.sh — $(date '+%Y-%m-%d %H:%M:%S')
# ==========================================================================

# Malcolm image settings
MALCOLM_IMAGE_REGISTRY=ghcr.io/idaholab/malcolm
MALCOLM_IMAGE_TAG=26.02.0

# Process ownership (must be non-root — OpenSearch refuses to run as UID 0)
PUID=${puid}
PGID=${pgid}

# Network capture interface
PCAP_IFACE=${PCAP_IFACE:-br0}
ZEEK_LOCAL_NETS=${ZEEK_LOCAL_NETS:-192.168.0.0/16,10.0.0.0/8,172.16.0.0/12}

# JVM heap (auto-tuned for detected RAM)
OPENSEARCH_JAVA_OPTS=-Xms${OPENSEARCH_HEAP} -Xmx${OPENSEARCH_HEAP}
LS_JAVA_OPTS=-Xms${LOGSTASH_HEAP} -Xmx${LOGSTASH_HEAP}

# Ports
MALCOLM_HTTPS_PORT=${MALCOLM_HTTPS_PORT:-9443}
DASHBOARD_PORT=${DASHBOARD_PORT:-443}

# Auth
NGINX_AUTH_MODE=basic
ARKIME_SECRET=${ARKIME_SECRET:-$(openssl rand -hex 16 2>/dev/null || echo "NetTap_Arkime_Secret")}
REDIS_PASSWORD=${REDIS_PASSWORD:-$(openssl rand -hex 16 2>/dev/null || echo "NetTap_Redis_Secret")}

# Certificate and auth paths
MALCOLM_CERTS_DIR=./certs
MALCOLM_AUTH_DIR=./auth

# Storage retention
RETENTION_HOT=${RETENTION_HOT:-90}
RETENTION_WARM=${RETENTION_WARM:-180}
RETENTION_COLD=${RETENTION_COLD:-30}
DISK_THRESHOLD_PERCENT=${DISK_THRESHOLD_PERCENT:-80}

# PCAP rotation
PCAP_ROTATE_MB=${PCAP_ROTATE_MB:-4096}
PCAP_ROTATE_MIN=${PCAP_ROTATE_MIN:-10}

# Arkime
ARKIME_PACKET_THREADS=${ARKIME_PACKET_THREADS:-2}

# Logstash
LOGSTASH_WORKERS=${LOGSTASH_WORKERS:-2}

# NetTap web
NETTAP_HOSTNAME=${NETTAP_HOSTNAME:-nettap.local}
ENVEOF

    chmod 600 "$env_file"
    log "Docker .env written to ${env_file}"
}

# ---------------------------------------------------------------------------
# Main — run all config generation steps
# ---------------------------------------------------------------------------
configure_malcolm() {
    log "Configuring Malcolm for NetTap..."

    check_command openssl

    generate_certs "$CERTS_DIR"
    generate_auth "$AUTH_DIR"
    generate_curlrc
    create_support_dirs
    generate_compose_env

    log "Malcolm configuration complete"
    log "  Certificates: ${CERTS_DIR}"
    log "  Auth files:   ${AUTH_DIR}"
    log "  Credentials:  ${PROJECT_ROOT}/docker/curlrc/"
    log "  Compose env:  ${PROJECT_ROOT}/docker/.env"
}

# Standalone execution
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --certs-dir)  CERTS_DIR="$2"; shift 2 ;;
            --auth-dir)   AUTH_DIR="$2"; shift 2 ;;
            --dry-run)    NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
            -v|--verbose) NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
            -h|--help)
                echo "Usage: $0 [OPTIONS]"
                echo "Generates SSL certs, auth files, and .env for Malcolm containers."
                echo ""
                echo "Options:"
                echo "  --certs-dir <path>   Certificate output directory (default: docker/certs)"
                echo "  --auth-dir <path>    Auth output directory (default: docker/auth)"
                echo "  --dry-run            Log commands without executing"
                echo "  -v, --verbose        Debug output"
                exit 0
                ;;
            *) echo "Unknown option: $1"; exit 1 ;;
        esac
    done

    configure_malcolm
fi
