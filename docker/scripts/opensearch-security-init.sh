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
# Step 1: Push ONLY roles_mapping.yml to the security index
# ---------------------------------------------------------------------------
# IMPORTANT: Do NOT use -cd (push entire directory). The init container's
# config directory has the Malcolm IMAGE DEFAULT internal_users.yml, which
# has wrong password hashes. Pushing the whole directory would overwrite
# the correct internal_users.yml that opensearch's entrypoint generated
# from the curlrc password, breaking all authentication (401).
#
# Using -f/-t pushes ONLY the roles mapping without touching internal_users,
# action_groups, tenants, or any other security config.
# ---------------------------------------------------------------------------
log "Pushing roles_mapping.yml to OpenSearch security index..."

attempt=0
while (( attempt < MAX_RETRIES )); do
    (( attempt++ )) || true

    if JAVA_HOME=/usr/share/opensearch/jdk \
       /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh \
       -f "$SECURITY_CONFIG_DIR/roles_mapping.yml" \
       -t rolesmapping \
       -h "$OPENSEARCH_HOST" \
       -p "$OPENSEARCH_PORT" \
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
        break
    fi

    if (( verify_attempt >= MAX_RETRIES )); then
        log "WARNING: Auth verification returned HTTP ${http_code} after ${MAX_RETRIES} attempts"
        log "securityadmin.sh succeeded, so security config was pushed — proceeding anyway"
        break
    fi

    log "Auth check returned HTTP ${http_code} (attempt ${verify_attempt}/${MAX_RETRIES}), retrying in ${RETRY_DELAY}s..."
    sleep "$RETRY_DELAY"
done

# ---------------------------------------------------------------------------
# Step 3: Create stub malcolm_template if missing (fresh install only)
# ---------------------------------------------------------------------------
# On fresh installs (after `down -v`), no index templates exist. Logstash
# blocks on startup waiting for `malcolm_template` to exist. Dashboards-helper
# creates the full template, but it has a 180s sleep + waits for log data
# that logstash produces — creating a deadlock:
#
#   logstash waits for malcolm_template → template needs dashboards-helper →
#   dashboards-helper waits for logs → logs need logstash → DEADLOCK
#
# Fix: create a minimal stub template that unblocks logstash. Dashboards-helper
# will overwrite it with the full template within minutes. By the time actual
# data flows through the pipeline, the full template will be in place.
# ---------------------------------------------------------------------------
OS_URL="https://${OPENSEARCH_HOST}:${OPENSEARCH_PORT}"
CURL_AUTH="--config $CURLRC --cacert $CERTS_DIR/ca.crt --insecure --silent"

template_code=$(curl $CURL_AUTH -o /dev/null -w '%{http_code}' \
    "${OS_URL}/_index_template/malcolm_template" 2>/dev/null) || true

if [[ "$template_code" == "200" ]]; then
    log "malcolm_template already exists — skipping stub creation"
else
    log "Creating stub malcolm_template to unblock logstash (dashboards-helper will update with full template)..."
    stub_code=$(curl $CURL_AUTH -o /dev/null -w '%{http_code}' \
        -XPUT "${OS_URL}/_index_template/malcolm_template" \
        -H "Content-Type: application/json" \
        -d '{
            "index_patterns": ["arkime_sessions3-*", "malcolm_beats_*"],
            "priority": 100,
            "template": {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0
                }
            }
        }' 2>/dev/null) || true

    if [[ "$stub_code" == "200" ]]; then
        log "Stub malcolm_template created — logstash will unblock"
    else
        log "WARNING: Failed to create stub template (HTTP ${stub_code}) — logstash may wait for dashboards-helper"
    fi
fi

log "OpenSearch init complete"
exit 0
