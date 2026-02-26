#!/usr/bin/env bash
# ==========================================================================
# NetTap — Self-Signed TLS Certificate Generator
# ==========================================================================
# Generates a self-signed TLS certificate for the nginx reverse proxy.
# Idempotent: skips generation if cert and key already exist.
#
# Output files:
#   docker/ssl/nettap.crt  — X.509 certificate (PEM)
#   docker/ssl/nettap.key  — RSA private key (PEM, mode 600)
#
# Usage:
#   scripts/generate-cert.sh            # normal run
#   scripts/generate-cert.sh --force    # regenerate even if cert exists
# ==========================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve project root (one level up from scripts/)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Source common.sh for logging helpers
# ---------------------------------------------------------------------------
# shellcheck source=common.sh
if [[ -f "${SCRIPT_DIR}/common.sh" ]]; then
    source "${SCRIPT_DIR}/common.sh"
else
    # Minimal fallback if common.sh is not available
    log()   { echo "[NetTap] $(date '+%Y-%m-%d %H:%M:%S') $*"; }
    warn()  { echo "[NetTap] WARN: $(date '+%Y-%m-%d %H:%M:%S') $*" >&2; }
    error() { echo "[NetTap] ERROR: $(date '+%Y-%m-%d %H:%M:%S') $*" >&2; exit 1; }
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SSL_DIR="${PROJECT_ROOT}/docker/ssl"
CERT_FILE="${SSL_DIR}/nettap.crt"
KEY_FILE="${SSL_DIR}/nettap.key"
CERT_DAYS=365
CERT_SUBJECT="/CN=nettap.local"
FORCE=false

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force|-f)
            FORCE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $(basename "$0") [--force]"
            echo "  --force, -f   Regenerate certificate even if it already exists"
            exit 0
            ;;
        *)
            warn "Unknown argument: $1"
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if ! command -v openssl &>/dev/null; then
    error "openssl is required but not found. Please install it first."
fi

# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------
if [[ -f "$CERT_FILE" && -f "$KEY_FILE" && "$FORCE" == "false" ]]; then
    log "TLS certificate already exists at ${CERT_FILE}"
    log "Key already exists at ${KEY_FILE}"
    log "Skipping generation. Use --force to regenerate."
    exit 0
fi

# ---------------------------------------------------------------------------
# Create output directory
# ---------------------------------------------------------------------------
mkdir -p "${SSL_DIR}"

# ---------------------------------------------------------------------------
# Generate self-signed certificate with SANs
# ---------------------------------------------------------------------------
log "Generating self-signed TLS certificate..."
log "  Subject: ${CERT_SUBJECT}"
log "  SANs:    DNS:nettap.local, DNS:localhost, IP:127.0.0.1"
log "  Valid:   ${CERT_DAYS} days"
log "  Output:  ${SSL_DIR}/"

openssl req -x509 -nodes -newkey rsa:2048 \
    -keyout "${KEY_FILE}" \
    -out "${CERT_FILE}" \
    -days "${CERT_DAYS}" \
    -subj "${CERT_SUBJECT}" \
    -addext "subjectAltName=DNS:nettap.local,DNS:localhost,IP:127.0.0.1" \
    -addext "keyUsage=digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    2>/dev/null

# ---------------------------------------------------------------------------
# Secure the private key
# ---------------------------------------------------------------------------
chmod 600 "${KEY_FILE}"

# ---------------------------------------------------------------------------
# Verify the generated certificate
# ---------------------------------------------------------------------------
log "Verifying certificate..."
if openssl x509 -in "${CERT_FILE}" -noout -text 2>/dev/null | grep -q "nettap.local"; then
    log "Certificate generated successfully."
    log "  Certificate: ${CERT_FILE}"
    log "  Private key: ${KEY_FILE} (mode 600)"

    # Show expiration date
    EXPIRY=$(openssl x509 -in "${CERT_FILE}" -noout -enddate 2>/dev/null | cut -d= -f2)
    log "  Expires:     ${EXPIRY}"
else
    error "Certificate verification failed. Check openssl output."
fi
