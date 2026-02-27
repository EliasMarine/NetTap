#!/usr/bin/env bash
# ==========================================================================
# NetTap — Secret generation script
# ==========================================================================
# Generates cryptographically random passwords and secrets for initial
# deployment. Writes them to /opt/nettap/.env (or stdout with --stdout).
#
# Usage:
#   sudo ./scripts/generate-secrets.sh [OPTIONS]
#
# Options:
#   --stdout        Print secrets to stdout instead of writing to .env
#   --env-file PATH Write to a custom .env path (default: /opt/nettap/.env)
#   --force         Regenerate all secrets even if they already exist
#   --dry-run       Show what would be done without writing
#   -v, --verbose   Enable debug output
#   -h, --help      Show help
# ==========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
ENV_FILE="/opt/nettap/.env"
MODE_STDOUT="false"
MODE_FORCE="false"
SECRET_LENGTH=32

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Generates cryptographically random secrets for NetTap deployment.

Options:
  --stdout          Print secrets to stdout instead of writing to .env
  --env-file PATH   Custom .env file path (default: /opt/nettap/.env)
  --force           Regenerate all secrets (overwrites existing values)
  --dry-run         Show what would be done without writing
  -v, --verbose     Debug output
  -h, --help        Show this help
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --stdout)       MODE_STDOUT="true"; shift ;;
        --env-file)     ENV_FILE="$2"; shift 2 ;;
        --force)        MODE_FORCE="true"; shift ;;
        --dry-run)      NETTAP_DRY_RUN="true"; shift ;;
        -v|--verbose)   NETTAP_VERBOSE="true"; shift ;;
        -h|--help)      usage ;;
        *)              echo "Unknown option: $1"; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Secret generation helper
# ---------------------------------------------------------------------------
# Generate a base64-encoded random string of at least $SECRET_LENGTH chars.
# Uses openssl for cryptographic randomness.
generate_secret() {
    openssl rand -base64 "$SECRET_LENGTH" | tr -d '\n'
}

# ---------------------------------------------------------------------------
# Read existing value from .env file (if it exists)
# Returns empty string if key is not found or file does not exist.
# ---------------------------------------------------------------------------
get_existing_value() {
    local key="$1"
    local file="$2"
    if [[ -f "$file" ]]; then
        # Match KEY=VALUE, strip quotes, return value
        grep -E "^${key}=" "$file" 2>/dev/null | head -1 | sed "s/^${key}=//" | sed 's/^["'"'"']//;s/["'"'"']$//' || true
    fi
}

# ---------------------------------------------------------------------------
# Set or skip a secret
# Returns the value (new or existing) via stdout capture.
# ---------------------------------------------------------------------------
resolve_secret() {
    local key="$1"
    local description="$2"
    local file="$3"
    local existing=""

    existing=$(get_existing_value "$key" "$file")

    if [[ -n "$existing" && "$MODE_FORCE" != "true" ]]; then
        debug "Keeping existing ${key} (use --force to regenerate)"
        echo "$existing"
        return 0
    fi

    local new_value
    new_value=$(generate_secret)
    if [[ -n "$existing" ]]; then
        log "Regenerating ${description} (${key})"
    else
        log "Generating ${description} (${key})"
    fi
    echo "$new_value"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log "NetTap secret generator"
    log ""

    # Validate openssl is available
    check_command openssl

    # If writing to file (not stdout), ensure directory exists
    if [[ "$MODE_STDOUT" != "true" ]]; then
        if [[ "$NETTAP_DRY_RUN" != "true" ]]; then
            local env_dir
            env_dir=$(dirname "$ENV_FILE")
            if [[ ! -d "$env_dir" ]]; then
                log "Creating directory ${env_dir}"
                mkdir -p "$env_dir"
            fi
        fi
    fi

    # --- Generate each secret ---
    local opensearch_pass grafana_pass jwt_secret api_key_salt

    opensearch_pass=$(resolve_secret \
        "OPENSEARCH_ADMIN_PASSWORD" \
        "OpenSearch admin password" \
        "$ENV_FILE")

    grafana_pass=$(resolve_secret \
        "GRAFANA_ADMIN_PASSWORD" \
        "Grafana admin password" \
        "$ENV_FILE")

    jwt_secret=$(resolve_secret \
        "JWT_SECRET" \
        "JWT signing secret" \
        "$ENV_FILE")

    api_key_salt=$(resolve_secret \
        "API_KEY_SALT" \
        "API key salt" \
        "$ENV_FILE")

    # --- Build the secrets block ---
    local secrets_block
    secrets_block=$(cat <<ENVEOF
# ==========================================================================
# NetTap Secrets — Auto-generated by generate-secrets.sh
# Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
# ==========================================================================
# WARNING: Do not commit this file to version control.
# Regenerate with: sudo scripts/generate-secrets.sh --force
# ==========================================================================

# OpenSearch admin password (used by all services connecting to OpenSearch)
OPENSEARCH_ADMIN_PASSWORD="${opensearch_pass}"

# Grafana admin password (web UI login)
GRAFANA_ADMIN_PASSWORD="${grafana_pass}"

# JWT secret for session tokens (web dashboard auth)
JWT_SECRET="${jwt_secret}"

# Salt for API key derivation (daemon <-> web communication)
API_KEY_SALT="${api_key_salt}"
ENVEOF
)

    # --- Output ---
    if [[ "$MODE_STDOUT" == "true" ]]; then
        echo "$secrets_block"
        return 0
    fi

    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] Would write secrets to ${ENV_FILE}"
        echo "$secrets_block"
        return 0
    fi

    # Write the secrets — preserve any non-secret lines already in the file
    if [[ -f "$ENV_FILE" ]]; then
        # Remove existing secret lines, then append new block
        local temp_file
        temp_file=$(mktemp)
        # Strip old auto-generated secrets block and the specific keys we manage
        grep -vE "^(OPENSEARCH_ADMIN_PASSWORD|GRAFANA_ADMIN_PASSWORD|JWT_SECRET|API_KEY_SALT)=" "$ENV_FILE" \
            | grep -v "^# .*Auto-generated by generate-secrets" \
            | grep -v "^# Generated:" \
            | grep -v "^# WARNING: Do not commit" \
            | grep -v "^# Regenerate with:" \
            | grep -v "^# =*$" \
            | grep -v "^# NetTap Secrets" \
            | grep -v "^# OpenSearch admin password" \
            | grep -v "^# Grafana admin password" \
            | grep -v "^# JWT secret for session" \
            | grep -v "^# Salt for API key" \
            > "$temp_file" 2>/dev/null || true

        # Append new secrets
        echo "" >> "$temp_file"
        echo "$secrets_block" >> "$temp_file"

        mv "$temp_file" "$ENV_FILE"
    else
        echo "$secrets_block" > "$ENV_FILE"
    fi

    # Secure permissions: owner read/write only
    chmod 600 "$ENV_FILE"
    log ""
    log "Secrets written to ${ENV_FILE} (mode 600)"
    log "Managed keys: OPENSEARCH_ADMIN_PASSWORD, GRAFANA_ADMIN_PASSWORD, JWT_SECRET, API_KEY_SALT"
}

main
