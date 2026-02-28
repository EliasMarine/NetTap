#!/usr/bin/env bash
# NetTap — Malcolm deployment script
# Pulls Malcolm container images, generates config, and starts the stack.
# This is the main entry point for deploying the capture/analysis pipeline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"
source "${SCRIPT_DIR}/malcolm-versions.conf"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.yml"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Deploys the NetTap + Malcolm container stack.

Options:
  --pull-only        Pull images without starting services
  --config-only      Generate config files without pulling or starting
  --start-only       Start services (assumes images already pulled)
  --no-start         Pull and configure but don't start services
  --skip-pull        Skip image pull (use cached images)
  --dry-run          Log actions without executing
  -v, --verbose      Enable debug output
  -h, --help         Show this help message
EOF
    exit 0
}

# Modes
DO_PULL="true"
DO_CONFIG="true"
DO_START="true"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pull-only)    DO_CONFIG="false"; DO_START="false"; shift ;;
        --config-only)  DO_PULL="false"; DO_START="false"; shift ;;
        --start-only)   DO_PULL="false"; DO_CONFIG="false"; shift ;;
        --no-start)     DO_START="false"; shift ;;
        --skip-pull)    DO_PULL="false"; shift ;;
        --dry-run)      NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
        -v|--verbose)   NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
        -h|--help)      usage ;;
        *)              echo "Unknown option: $1"; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Step 1: Pre-flight checks
# ---------------------------------------------------------------------------
preflight() {
    log "Running deployment pre-flight checks..."

    check_command docker

    # Verify Docker is running
    if ! docker info &>/dev/null; then
        error "Docker is not running. Start it with: systemctl start docker"
    fi

    # Verify docker compose plugin
    if ! docker compose version &>/dev/null; then
        error "Docker Compose plugin not found. Install with: apt-get install docker-compose-plugin"
    fi

    # Verify compose file exists
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        error "Docker compose file not found at ${COMPOSE_FILE}"
    fi

    # Check disk space (need ~15GB for images)
    local free_gb
    free_gb=$(df -BG "${PROJECT_ROOT}" | awk 'NR==2 {print int($4)}')
    if (( free_gb < 15 )); then
        warn "Only ${free_gb}GB free disk space. Malcolm images require ~10-15GB."
    fi

    log "Pre-flight checks passed"
}

# ---------------------------------------------------------------------------
# Step 2: Pull container images
# ---------------------------------------------------------------------------
pull_images() {
    log "Pulling Malcolm container images (${MALCOLM_IMAGE_REGISTRY}:${MALCOLM_IMAGE_TAG})..."
    log "This may take 5-15 minutes on broadband..."

    local images=(
        "$MALCOLM_IMG_OPENSEARCH"
        "$MALCOLM_IMG_DASHBOARDS"
        "$MALCOLM_IMG_DASHBOARDS_HELPER"
        "$MALCOLM_IMG_LOGSTASH"
        "$MALCOLM_IMG_FILEBEAT"
        "$MALCOLM_IMG_ZEEK"
        "$MALCOLM_IMG_SURICATA"
        "$MALCOLM_IMG_ARKIME"
        "$MALCOLM_IMG_PCAP_CAPTURE"
        "$MALCOLM_IMG_NGINX_PROXY"
        "$MALCOLM_IMG_REDIS"
        "$MALCOLM_IMG_API"
    )

    local total=${#images[@]}
    local count=0
    local failed=0

    for img in "${images[@]}"; do
        (( ++count ))
        local full_image="${MALCOLM_IMAGE_REGISTRY}/${img}:${MALCOLM_IMAGE_TAG}"
        log "[${count}/${total}] Pulling ${img}..."

        if run docker pull "$full_image"; then
            debug "  Pulled ${full_image}"
        else
            warn "  Failed to pull ${full_image}"
            (( ++failed ))
        fi
    done

    if (( failed > 0 )); then
        error "${failed} image(s) failed to pull. Check your internet connection and registry access."
    fi

    log "All ${total} Malcolm images pulled successfully"
}

# ---------------------------------------------------------------------------
# Step 3: Generate configuration
# ---------------------------------------------------------------------------
generate_config() {
    log "Generating Malcolm configuration..."
    source "${SCRIPT_DIR}/malcolm-config.sh"
    configure_malcolm
}

# ---------------------------------------------------------------------------
# Step 4: Start services
# ---------------------------------------------------------------------------
start_services() {
    log "Starting NetTap services..."

    # Build custom images first (with visible progress)
    # BuildKit hides output by default — use plain progress so users can
    # see what npm/pip/apt are doing during long builds.
    log "Building custom NetTap images (web, daemon, tshark, cyberchef)..."
    BUILDKIT_PROGRESS=plain run docker compose -f "$COMPOSE_FILE" build

    # ---------------------------------------------------------------------------
    # Phase 0: Bootstrap OpenSearch security before starting dependent services
    # ---------------------------------------------------------------------------
    # On fresh deployments, the .opendistro_security index doesn't exist.
    # The healthcheck (curl + auth) fails → Docker marks OpenSearch unhealthy →
    # dependent services (logstash, dashboards, etc.) refuse to start.
    #
    # Fix: start OpenSearch alone, wait for its HTTP API to respond (even 401),
    # run securityadmin.sh to create the security index, THEN start everything.
    # ---------------------------------------------------------------------------
    log "Starting OpenSearch first (security bootstrap required before other services)..."
    run docker compose -f "$COMPOSE_FILE" up -d opensearch

    # Wait for OpenSearch HTTP API to respond (even "Unauthorized" is fine —
    # it means the REST API is up and ready for securityadmin.sh)
    _wait_for_opensearch_http

    # Bootstrap security (idempotent — safe on existing deployments too)
    bootstrap_opensearch_security

    # Now start the full stack — OpenSearch should pass healthchecks
    log "Starting remaining services..."
    run docker compose -f "$COMPOSE_FILE" up -d

    log ""
    log "Containers launched. Monitoring startup progress..."
    log ""

    # ---------------------------------------------------------------------------
    # Verbose startup monitoring — show per-service status as they come up
    # ---------------------------------------------------------------------------
    monitor_startup

    # Apply ILM policy once OpenSearch is confirmed healthy and auth works
    apply_ilm_policy

    # Final status report
    log ""
    log "=========================================="
    log "  NetTap Deployment Status"
    log "=========================================="
    docker compose -f "$COMPOSE_FILE" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || \
        docker compose -f "$COMPOSE_FILE" ps
    log ""
    log "Malcolm Dashboards: https://localhost:${MALCOLM_HTTPS_PORT:-9443}"
    log "NetTap Dashboard:   https://${NETTAP_HOSTNAME:-nettap.local}:${DASHBOARD_PORT:-443}"
    log "=========================================="
}

# ---------------------------------------------------------------------------
# Monitor container startup — verbose per-service progress
# ---------------------------------------------------------------------------
# Shows real-time status of each service as it transitions through
# Created → Starting → Healthy/Running/Error states.
# ---------------------------------------------------------------------------
monitor_startup() {
    local max_wait=600  # 10 minutes max
    local poll_interval=10
    local elapsed=0

    # Services to monitor (in dependency order)
    local -a critical_services=(opensearch)
    local -a dependent_services=(dashboards-helper dashboards logstash)
    local -a pipeline_services=(filebeat zeek-live suricata-live pcap-capture arkime-live)
    local -a infra_services=(redis api nginx-proxy)
    local -a nettap_services=(nettap-storage-daemon nettap-web nettap-grafana nettap-nginx nettap-tshark nettap-cyberchef)

    # Phase 1: Wait for OpenSearch (everything depends on it)
    log "--- Phase 1: OpenSearch (all services depend on this) ---"
    _wait_for_service "opensearch" "$max_wait" "$poll_interval" || {
        warn "OpenSearch failed to become healthy. Dumping last 30 log lines:"
        docker logs --tail 30 nettap-opensearch 2>&1 | while IFS= read -r line; do
            warn "  $line"
        done
        warn ""
        warn "Common causes:"
        warn "  - curlrc permissions (should be 644, not 600)"
        warn "  - PUID=0 in .env (should be 1000)"
        warn "  - Insufficient memory (need 4g+ free for JVM heap)"
        warn "  - Port 9200 already in use"
        warn ""
        warn "Debug commands:"
        warn "  docker logs -f nettap-opensearch"
        warn "  docker inspect nettap-opensearch | jq '.[0].State'"
        return 1
    }

    # Phase 2: Log pipeline (needs OpenSearch healthy)
    log ""
    log "--- Phase 2: Log pipeline ---"
    for svc in "${dependent_services[@]}"; do
        _show_service_status "$svc"
    done

    # Phase 3: Capture services (host network)
    log ""
    log "--- Phase 3: Capture services ---"
    for svc in "${pipeline_services[@]}"; do
        _show_service_status "$svc"
    done

    # Phase 4: Infrastructure
    log ""
    log "--- Phase 4: Infrastructure ---"
    for svc in "${infra_services[@]}"; do
        _show_service_status "$svc"
    done

    # Phase 5: NetTap services
    log ""
    log "--- Phase 5: NetTap services ---"
    for svc in "${nettap_services[@]}"; do
        _show_service_status "$svc"
    done

    # Wait for logstash (has 600s start_period, slowest after OpenSearch)
    log ""
    log "--- Waiting for Logstash pipeline (this can take several minutes) ---"
    _wait_for_service "logstash" 660 15 || {
        warn "Logstash did not become healthy. Check: docker logs nettap-logstash"
    }

    # Final check: show any unhealthy/restarting containers
    log ""
    log "--- Final health check ---"
    local unhealthy
    unhealthy=$(docker compose -f "$COMPOSE_FILE" ps --format '{{.Name}}\t{{.Status}}' 2>/dev/null \
        | grep -iE '(unhealthy|restarting|exit)' || true)

    if [[ -n "$unhealthy" ]]; then
        warn "Some services are not healthy:"
        echo "$unhealthy" | while IFS= read -r line; do
            warn "  $line"
        done
    else
        log "All services are running"
    fi
}

# ---------------------------------------------------------------------------
# Wait for OpenSearch HTTP API to respond (any status, even 401/403)
# ---------------------------------------------------------------------------
# Used during bootstrap: we need securityadmin.sh to create the
# .opendistro_security index, but OpenSearch's REST API must be up first.
# The healthcheck (which requires auth) will fail until after bootstrap,
# so we check for ANY HTTP response instead.
# ---------------------------------------------------------------------------
_wait_for_opensearch_http() {
    local max_wait=120
    local interval=5
    local elapsed=0

    log "  Waiting for OpenSearch HTTP API..."
    while (( elapsed < max_wait )); do
        # Any HTTP response means the REST API is ready (even 401 "Unauthorized")
        local http_code
        http_code=$(docker compose -f "$COMPOSE_FILE" exec -T opensearch \
            curl -sk -o /dev/null -w '%{http_code}' https://localhost:9200/ 2>/dev/null) || true

        if [[ "$http_code" =~ ^[0-9]+$ ]] && (( http_code > 0 )); then
            log "  OpenSearch HTTP API responding (HTTP ${http_code}, ${elapsed}s)"
            return 0
        fi

        sleep "$interval"
        (( elapsed += interval ))
        log "  Waiting for OpenSearch HTTP... (${elapsed}s)"
    done

    warn "  OpenSearch HTTP API did not respond within ${max_wait}s"
    return 1
}

# ---------------------------------------------------------------------------
# Wait for a specific service to become healthy
# ---------------------------------------------------------------------------
_wait_for_service() {
    local service="$1"
    local max_wait="${2:-300}"
    local interval="${3:-10}"
    local elapsed=0

    while (( elapsed < max_wait )); do
        local status
        status=$(docker compose -f "$COMPOSE_FILE" ps --format '{{.Status}}' "$service" 2>/dev/null | head -1) || true

        case "$status" in
            *healthy*)
                log "  [OK] ${service} is healthy (${elapsed}s)"
                return 0
                ;;
            *starting*|*Starting*)
                log "  [..] ${service} starting... (${elapsed}s)"
                ;;
            *unhealthy*|*Unhealthy*)
                warn "  [!!] ${service} is unhealthy (${elapsed}s)"
                ;;
            *Exit*|*exited*|*Restarting*)
                warn "  [XX] ${service} has exited/crashed (${elapsed}s)"
                # Show last few log lines for immediate context
                docker logs --tail 5 "nettap-${service}" 2>&1 | while IFS= read -r line; do
                    warn "       $line"
                done
                ;;
            *Up*|*running*)
                # Running but no healthcheck defined
                log "  [OK] ${service} is running (${elapsed}s)"
                return 0
                ;;
            "")
                debug "  [??] ${service} status unknown (container may not exist yet)"
                ;;
            *)
                debug "  [??] ${service} status: ${status} (${elapsed}s)"
                ;;
        esac

        sleep "$interval"
        (( elapsed += interval ))
    done

    warn "  [TIMEOUT] ${service} did not become healthy within ${max_wait}s"
    return 1
}

# ---------------------------------------------------------------------------
# Show current status of a service (non-blocking, single check)
# ---------------------------------------------------------------------------
_show_service_status() {
    local service="$1"
    local status
    status=$(docker compose -f "$COMPOSE_FILE" ps --format '{{.Status}}' "$service" 2>/dev/null | head -1) || true

    if [[ -z "$status" ]]; then
        debug "  [--] ${service}: not started yet"
    elif [[ "$status" == *healthy* ]]; then
        log "  [OK] ${service}: ${status}"
    elif [[ "$status" == *Exit* || "$status" == *exited* ]]; then
        warn "  [XX] ${service}: ${status}"
    else
        log "  [..] ${service}: ${status}"
    fi
}

# ---------------------------------------------------------------------------
# Bootstrap OpenSearch Security Plugin — roles mapping + securityadmin push
# ---------------------------------------------------------------------------
# Malcolm's OpenSearch image creates internal_users.yml (with malcolm_internal)
# via setup-internal-users.sh, but the roles_mapping.yml is left empty.
# Without a mapping from backend_role "admin" → OpenSearch role "all_access",
# malcolm_internal authenticates (200) but has no permissions (403).
#
# This function:
#   1. Writes the correct roles_mapping.yml inside the container
#   2. Runs securityadmin.sh to push all security config to the .opendistro_security index
#
# This must run AFTER OpenSearch is healthy but BEFORE any API calls that need auth.
# ---------------------------------------------------------------------------
bootstrap_opensearch_security() {
    log "Bootstrapping OpenSearch security configuration..."

    # Step 1: Write the correct roles_mapping.yml
    # The admin backend role must map to all_access for malcolm_internal to work.
    log "  Writing roles_mapping.yml with admin → all_access mapping..."
    if ! docker compose -f "$COMPOSE_FILE" exec -T opensearch \
        python3 -c "open('/usr/share/opensearch/config/opensearch-security/roles_mapping.yml','w').write('---\n_meta:\n  type: \"rolesmapping\"\n  config_version: 2\n\nall_access:\n  reserved: false\n  backend_roles:\n  - \"admin\"\n  description: \"Maps admin backend role to all_access\"\n')" 2>/dev/null; then
        warn "  Failed to write roles_mapping.yml"
        return 1
    fi

    # Step 2: Push all security config files to the OpenSearch security index.
    # securityadmin.sh uses the admin cert (generated by Malcolm's self_signed_key_gen.sh)
    # to authenticate via the REST API on port 9200.
    log "  Running securityadmin.sh to push security config..."
    if retry 3 5 docker compose -f "$COMPOSE_FILE" exec -T opensearch \
        bash -c 'JAVA_HOME=/usr/share/opensearch/jdk /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh -cd /usr/share/opensearch/config/opensearch-security/ -cacert /usr/share/opensearch/config/certs/ca.crt -cert /usr/share/opensearch/config/certs/admin.crt -key /usr/share/opensearch/config/certs/admin.key -icl -nhnv' 2>/dev/null; then
        log "  OpenSearch security configuration applied successfully"
    else
        warn "  securityadmin.sh failed — malcolm_internal may not have permissions"
        warn "  Manual fix: docker exec nettap-opensearch bash -c 'JAVA_HOME=/usr/share/opensearch/jdk /usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh -cd /usr/share/opensearch/config/opensearch-security/ -cacert /usr/share/opensearch/config/certs/ca.crt -cert /usr/share/opensearch/config/certs/admin.crt -key /usr/share/opensearch/config/certs/admin.key -icl -nhnv'"
        return 1
    fi

    # Step 3: Verify auth actually works
    log "  Verifying malcolm_internal authentication..."
    if docker compose -f "$COMPOSE_FILE" exec -T opensearch \
        curl --config /var/local/curlrc/.opensearch.primary.curlrc \
        --insecure --silent --fail \
        "https://localhost:9200/_cluster/health" >/dev/null 2>&1; then
        log "  Authentication verified — malcolm_internal has cluster access"
    else
        warn "  Authentication verification failed — check roles_mapping"
    fi
}

# ---------------------------------------------------------------------------
# Apply OpenSearch ISM (Index State Management) policies
# ---------------------------------------------------------------------------
# The ILM JSON contains 3 separate policies under .policies.*:
#   - nettap-hot-policy   (Zeek metadata, 90-day retention)
#   - nettap-warm-policy  (Suricata alerts, 180-day retention)
#   - nettap-cold-policy  (Arkime/PCAP, 30-day retention)
#
# Each must be applied individually via the ISM API. We exec into the
# opensearch container to bypass nginx-proxy auth and use the curlrc
# credentials that Malcolm's entrypoint already configured.
# ---------------------------------------------------------------------------
apply_ilm_policy() {
    local ilm_file="${PROJECT_ROOT}/config/opensearch/ilm-policy.json"

    if [[ ! -f "$ilm_file" ]]; then
        warn "ILM policy file not found at ${ilm_file}, skipping"
        return 0
    fi

    # Verify python3 is available (needed to extract individual policies from JSON)
    if ! command -v python3 &>/dev/null; then
        warn "python3 not found — cannot parse ILM policies. Skipping ISM setup."
        return 0
    fi

    log "Applying OpenSearch ISM policies..."

    # Extract policy names from the JSON
    local policy_names
    policy_names=$(python3 -c "
import json, sys
with open('${ilm_file}') as f:
    data = json.load(f)
for name in data.get('policies', {}):
    print(name)
")

    if [[ -z "$policy_names" ]]; then
        warn "No policies found in ${ilm_file}"
        return 0
    fi

    local applied=0 failed=0

    while IFS= read -r policy_name; do
        # Extract this policy's JSON body (the value under .policies.<name>)
        local policy_body
        policy_body=$(python3 -c "
import json, sys
with open('${ilm_file}') as f:
    data = json.load(f)
policy = data['policies']['${policy_name}']
print(json.dumps(policy))
")

        log "  Applying ISM policy: ${policy_name}..."

        # Exec into opensearch container — this bypasses nginx-proxy auth entirely
        # and uses the internal https://localhost:9200 endpoint with curlrc auth.
        if retry 3 5 docker compose -f "$COMPOSE_FILE" exec -T opensearch \
            curl --config /var/local/curlrc/.opensearch.primary.curlrc \
            --insecure --silent --output /dev/null --fail \
            -XPUT "https://localhost:9200/_plugins/_ism/policies/${policy_name}" \
            -H "Content-Type: application/json" \
            -d "${policy_body}" 2>/dev/null; then
            log "  ${policy_name} applied successfully"
            (( applied++ ))
        else
            # Policy may already exist — try update (requires seq_no + primary_term)
            local existing
            existing=$(docker compose -f "$COMPOSE_FILE" exec -T opensearch \
                curl --config /var/local/curlrc/.opensearch.primary.curlrc \
                --insecure --silent \
                "https://localhost:9200/_plugins/_ism/policies/${policy_name}" 2>/dev/null) || true

            local seq_no primary_term
            seq_no=$(echo "$existing" | python3 -c "import json,sys; print(json.load(sys.stdin).get('_seq_no',''))" 2>/dev/null) || true
            primary_term=$(echo "$existing" | python3 -c "import json,sys; print(json.load(sys.stdin).get('_primary_term',''))" 2>/dev/null) || true

            if [[ -n "$seq_no" && -n "$primary_term" ]]; then
                if docker compose -f "$COMPOSE_FILE" exec -T opensearch \
                    curl --config /var/local/curlrc/.opensearch.primary.curlrc \
                    --insecure --silent --output /dev/null --fail \
                    -XPUT "https://localhost:9200/_plugins/_ism/policies/${policy_name}?if_seq_no=${seq_no}&if_primary_term=${primary_term}" \
                    -H "Content-Type: application/json" \
                    -d "${policy_body}" 2>/dev/null; then
                    log "  ${policy_name} updated successfully"
                    (( applied++ ))
                else
                    warn "  Failed to update ${policy_name}"
                    (( failed++ ))
                fi
            else
                warn "  Failed to apply ${policy_name}"
                (( failed++ ))
            fi
        fi
    done <<< "$policy_names"

    if (( failed > 0 )); then
        warn "${failed} ISM policy(ies) failed. Check OpenSearch logs."
    fi
    log "ISM policies applied: ${applied}, failed: ${failed}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
deploy_malcolm() {
    log ""
    log "=========================================="
    log "  NetTap Malcolm Deployment"
    log "  Images: ${MALCOLM_IMAGE_REGISTRY}:${MALCOLM_IMAGE_TAG}"
    log "=========================================="
    log ""

    preflight

    if [[ "$DO_CONFIG" == "true" ]]; then
        generate_config
    fi

    if [[ "$DO_PULL" == "true" ]]; then
        pull_images
    fi

    if [[ "$DO_START" == "true" ]]; then
        start_services
    fi

    log "Malcolm deployment complete"
}

# Standalone execution
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    deploy_malcolm
fi
