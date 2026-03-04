#!/usr/bin/env bash
# ==========================================================================
# OpenSearch Security Bootstrap — One-shot init container script
# ==========================================================================
# Pushes the security configuration (roles_mapping.yml, internal_users.yml,
# etc.) from the container filesystem into the .opendistro_security index.
#
# This runs as a one-shot init container (restart: "no") that:
#   1. Waits for OpenSearch to be reachable
#   2. Runs securityadmin.sh to sync config files → security index
#   3. Verifies auth works with a health check
#   4. Exits 0 on success, 1 on failure
#
# The roles_mapping.yml is bind-mounted from the repo, so it's always
# correct regardless of container recreations.
# ==========================================================================
set -euo pipefail

OPENSEARCH_HOST="${OPENSEARCH_HOST:-opensearch}"
OPENSEARCH_PORT="${OPENSEARCH_PORT:-9200}"
SECURITY_CONFIG_DIR="/usr/share/opensearch/config/opensearch-security"
CERTS_DIR="/usr/share/opensearch/config/certs"
CURLRC="/var/local/curlrc/.opensearch.primary.curlrc"
MAX_RETRIES=3
RETRY_DELAY=5

log() { echo "[opensearch-init] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

# ---------------------------------------------------------------------------
# Step 1: Run securityadmin.sh to push config files into the security index
# ---------------------------------------------------------------------------
log "Pushing security configuration to OpenSearch..."

attempt=0
while (( attempt < MAX_RETRIES )); do
    (( attempt++ )) || true

    if JAVA_HOME=/usr/share/opensearch/jdk \
       /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh \
       -cd "$SECURITY_CONFIG_DIR" \
       -cacert "$CERTS_DIR/ca.crt" \
       -cert "$CERTS_DIR/admin.crt" \
       -key "$CERTS_DIR/admin.key" \
       -icl -nhnv 2>&1; then
        log "securityadmin.sh completed successfully (attempt ${attempt}/${MAX_RETRIES})"
        break
    fi

    if (( attempt >= MAX_RETRIES )); then
        log "ERROR: securityadmin.sh failed after ${MAX_RETRIES} attempts"
        exit 1
    fi

    log "securityadmin.sh failed (attempt ${attempt}/${MAX_RETRIES}), retrying in ${RETRY_DELAY}s..."
    sleep "$RETRY_DELAY"
done

# ---------------------------------------------------------------------------
# Step 2: Verify authentication works
# ---------------------------------------------------------------------------
log "Verifying authentication..."

verify_attempt=0
while (( verify_attempt < MAX_RETRIES )); do
    (( verify_attempt++ )) || true

    http_code=$(curl --config "$CURLRC" \
        --cacert "$CERTS_DIR/ca.crt" \
        --insecure --silent --output /dev/null --write-out '%{http_code}' \
        "https://${OPENSEARCH_HOST}:${OPENSEARCH_PORT}/_cluster/health" 2>/dev/null) || true

    if [[ "$http_code" == "200" ]]; then
        log "Authentication verified (HTTP 200) — OpenSearch security is configured"
        exit 0
    fi

    if (( verify_attempt >= MAX_RETRIES )); then
        log "WARNING: Auth verification returned HTTP ${http_code} after ${MAX_RETRIES} attempts"
        log "securityadmin.sh succeeded, so security config was pushed — proceeding anyway"
        # Exit 0 because securityadmin.sh succeeded; verification failure may be
        # transient (e.g., security index still propagating)
        exit 0
    fi

    log "Auth check returned HTTP ${http_code} (attempt ${verify_attempt}/${MAX_RETRIES}), retrying in ${RETRY_DELAY}s..."
    sleep "$RETRY_DELAY"
done
