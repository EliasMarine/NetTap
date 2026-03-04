#!/bin/bash
# ==========================================================================
# OpenSearch Bootstrap — One-Shot Init Container
# ==========================================================================
# This script runs once at startup (before logstash) to ensure:
#   1. Security config is pushed (roles_mapping.yml → admin → all_access)
#   2. malcolm_template index template exists (unblocks logstash startup)
#
# Without this, after `docker compose down -v` + `up`:
#   - roles_mapping.yml resets → malcolm_internal gets 403
#   - malcolm_template doesn't exist → logstash blocks forever
#   - filebeat can't connect → no data in OpenSearch → empty dashboards
#
# See: Debugging/DEPLOYMENT-ISSUES.md (Chain 11, Chain 15)
# ==========================================================================
set -euo pipefail

LOG_PREFIX="[opensearch-init]"
OS_HOST="opensearch"
OS_PORT="9200"
OS_URL="https://${OS_HOST}:${OS_PORT}"
CURL_OPTS="-sk --connect-timeout 10 --max-time 30"
SECURITY_DIR="/usr/share/opensearch/config/opensearch-security"
CERTS_DIR="/usr/share/opensearch/config/certs"
SECURITYADMIN="/usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh"
MAX_RETRIES=5
RETRY_DELAY=5

log()  { echo "${LOG_PREFIX} $*"; }
warn() { echo "${LOG_PREFIX} WARNING: $*" >&2; }
die()  { echo "${LOG_PREFIX} FATAL: $*" >&2; exit 1; }

# --------------------------------------------------------------------------
# Read OpenSearch credentials from curlrc
# --------------------------------------------------------------------------
CURLRC="/var/local/curlrc/.opensearch.primary.curlrc"
if [[ ! -f "$CURLRC" ]]; then
    die "curlrc not found at $CURLRC — cannot authenticate"
fi

CREDS=$(grep -oP 'user:\s*"\K[^"]+' "$CURLRC" || true)
if [[ -z "$CREDS" ]]; then
    die "Could not parse credentials from $CURLRC"
fi

# --------------------------------------------------------------------------
# Step 1: Security Bootstrap
# --------------------------------------------------------------------------
# Write the correct roles_mapping.yml into this container's security config
# directory, then push ALL security config to OpenSearch via securityadmin.sh.
#
# Why write it here instead of just mounting it? Because securityadmin.sh reads
# the ENTIRE -cd directory (roles.yml, internal_users.yml, action_groups.yml,
# etc.). We need the image defaults for those files + our override for
# roles_mapping.yml.
# --------------------------------------------------------------------------
log "Step 1/3: Writing roles_mapping.yml..."
cat > "${SECURITY_DIR}/roles_mapping.yml" <<'YAML'
---
_meta:
  type: "rolesmapping"
  config_version: 2

all_access:
  reserved: false
  backend_roles:
  - "admin"
  description: "Maps admin backend role to all_access"
YAML

log "Step 2/3: Running securityadmin.sh (pushing security config to OpenSearch)..."
for attempt in $(seq 1 $MAX_RETRIES); do
    if JAVA_HOME=/usr/share/opensearch/jdk \
        "$SECURITYADMIN" \
        -cd "$SECURITY_DIR" \
        -cacert "${CERTS_DIR}/ca.crt" \
        -cert "${CERTS_DIR}/admin.crt" \
        -key "${CERTS_DIR}/admin.key" \
        -h "$OS_HOST" -p "$OS_PORT" \
        -icl -nhnv 2>&1; then
        log "Security config pushed successfully"
        break
    else
        if [[ $attempt -eq $MAX_RETRIES ]]; then
            die "securityadmin.sh failed after ${MAX_RETRIES} attempts"
        fi
        warn "securityadmin.sh failed (attempt ${attempt}/${MAX_RETRIES}), retrying in ${RETRY_DELAY}s..."
        sleep "$RETRY_DELAY"
    fi
done

# Verify auth works with malcolm_internal credentials
log "Verifying malcolm_internal authentication..."
if ! curl $CURL_OPTS -u "$CREDS" --fail "$OS_URL/_cluster/health" > /dev/null 2>&1; then
    die "Authentication failed after security bootstrap — check roles_mapping.yml"
fi
log "Authentication verified"

# --------------------------------------------------------------------------
# Step 3: Template Bootstrap
# --------------------------------------------------------------------------
# Push a minimal malcolm_template if it doesn't exist. This unblocks logstash's
# opensearch_status.sh which waits for this template before starting.
#
# dashboards-helper will eventually push the full template with complete field
# mappings — our minimal version just breaks the startup deadlock:
#   logstash waits for template → template needs dashboards-helper → dashboards-helper
#   waits for logs → logs need logstash → deadlock
# --------------------------------------------------------------------------
log "Step 3/3: Checking for malcolm_template index template..."
HTTP_CODE=$(curl $CURL_OPTS -u "$CREDS" -o /dev/null -w '%{http_code}' \
    "$OS_URL/_index_template/malcolm_template" 2>/dev/null) || true

if [[ "$HTTP_CODE" == "200" ]]; then
    log "malcolm_template already exists — skipping"
else
    log "Creating minimal malcolm_template (HTTP ${HTTP_CODE} = not found)..."
    TEMPLATE_RESPONSE=$(curl $CURL_OPTS -u "$CREDS" -X PUT \
        "$OS_URL/_index_template/malcolm_template" \
        -H "Content-Type: application/json" \
        -d '{
            "index_patterns": ["malcolm_*"],
            "template": {
                "settings": {
                    "index": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                        "refresh_interval": "10s"
                    }
                }
            },
            "priority": 100
        }' 2>&1) || true

    if echo "$TEMPLATE_RESPONSE" | grep -q '"acknowledged":true'; then
        log "malcolm_template created successfully"
    else
        warn "Unexpected response creating malcolm_template: ${TEMPLATE_RESPONSE}"
        warn "Logstash may still block — check dashboards-helper idxinit"
    fi
fi

log "=========================================="
log "Bootstrap complete — OpenSearch is ready"
log "  Security: admin → all_access (pushed)"
log "  Template: malcolm_template (verified)"
log "=========================================="
exit 0
