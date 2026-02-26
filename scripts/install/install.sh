#!/usr/bin/env bash
# NetTap — Main installation script
# Installs dependencies, configures the bridge, deploys Malcolm, and starts services
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/../common.sh"

require_root
load_env "${PROJECT_ROOT}/.env"

log "Starting NetTap installation..."

# ---- Step 1: System dependencies ----
log "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    docker.io \
    docker-compose-plugin \
    bridge-utils \
    smartmontools \
    python3 \
    python3-pip \
    avahi-daemon

# ---- Step 2: Network bridge ----
log "Configuring network bridge..."
"${SCRIPT_DIR}/../bridge/setup-bridge.sh"

# ---- Step 3: Malcolm deployment ----
log "Deploying Malcolm stack..."
# TODO: Clone/extract Malcolm, apply NetTap config overlays

# ---- Step 4: NetTap services ----
log "Starting NetTap services..."
docker compose -f "${PROJECT_ROOT}/docker/docker-compose.yml" up -d

log "Installation complete. Access the dashboard at https://${NETTAP_HOSTNAME:-nettap.local}"
