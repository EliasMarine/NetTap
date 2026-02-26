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
        --dry-run)      NETTAP_DRY_RUN="true"; shift ;;
        -v|--verbose)   NETTAP_VERBOSE="true"; shift ;;
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
        (( count++ ))
        local full_image="${MALCOLM_IMAGE_REGISTRY}/${img}:${MALCOLM_IMAGE_TAG}"
        log "[${count}/${total}] Pulling ${img}..."

        if run docker pull "$full_image"; then
            debug "  Pulled ${full_image}"
        else
            warn "  Failed to pull ${full_image}"
            (( failed++ ))
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

    # Start the stack
    run docker compose -f "$COMPOSE_FILE" up -d

    log "Containers starting. Waiting for OpenSearch to be healthy..."

    # Wait for OpenSearch (it takes the longest to start)
    if ! retry 60 10 docker compose -f "$COMPOSE_FILE" exec -T opensearch \
        curl -skf "https://localhost:9200/_cluster/health" > /dev/null 2>&1; then

        # Fallback: check from host via nginx-proxy on localhost:9200
        if ! retry 30 10 curl -skf "https://localhost:9200/_cluster/health" > /dev/null 2>&1; then
            warn "OpenSearch did not become healthy within expected time."
            warn "It may still be initializing. Check with: docker logs nettap-opensearch"
        else
            log "OpenSearch is healthy (via nginx-proxy)"
        fi
    else
        log "OpenSearch is healthy"
    fi

    # Apply ILM policy
    apply_ilm_policy

    # Brief status report
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
# Apply OpenSearch ILM policy
# ---------------------------------------------------------------------------
apply_ilm_policy() {
    local ilm_file="${PROJECT_ROOT}/config/opensearch/ilm-policy.json"

    if [[ ! -f "$ilm_file" ]]; then
        warn "ILM policy file not found at ${ilm_file}, skipping"
        return 0
    fi

    log "Applying OpenSearch ILM policy..."

    # Try via the nginx-proxy localhost endpoint
    local opensearch_url="https://localhost:9200"

    if retry 3 5 curl -skf -XPUT \
        "${opensearch_url}/_plugins/_ism/policies/nettap-retention" \
        -H "Content-Type: application/json" \
        -d "@${ilm_file}" > /dev/null 2>&1; then
        log "ILM policy applied successfully"
    else
        warn "Could not apply ILM policy. OpenSearch may not be ready yet."
        warn "Apply manually later: curl -XPUT '${opensearch_url}/_plugins/_ism/policies/nettap-retention' -d @${ilm_file}"
    fi
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
