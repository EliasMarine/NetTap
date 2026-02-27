#!/usr/bin/env bash
# ==========================================================================
# NetTap — Main installation script
# ==========================================================================
# Orchestrates the full deployment: pre-flight checks, system dependencies,
# network bridge, Malcolm stack, systemd services, mDNS, and verification.
#
# Usage:
#   sudo ./scripts/install/install.sh [OPTIONS]
#
# Options:
#   --skip-bridge        Skip bridge configuration (if already done)
#   --skip-pull          Skip Docker image pull (use cached images)
#   --skip-malcolm       Skip Malcolm deployment (bridge + deps only)
#   --persist-bridge     Write netplan/systemd for bridge persistence
#   --defer-bridge       Defer bridge activation until after cable rewiring
#   --immediate-bridge   (No-op, kept for backwards compatibility)
#   --non-interactive    Skip interactive prompts (auto-assign NICs)
#   --reconfigure-nics   Force NIC re-discovery even if .env has values
#   --dry-run            Log all actions without executing
#   -v, --verbose        Enable debug output
#   -h, --help           Show help
# ==========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults & flags
# ---------------------------------------------------------------------------
SKIP_BRIDGE="false"
SKIP_PULL="false"
SKIP_MALCOLM="false"
PERSIST_BRIDGE="true"
DEFER_BRIDGE="false"
NON_INTERACTIVE="false"
RECONFIGURE_NICS="false"
INSTALL_START_TIME=$(date +%s)

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: sudo $0 [OPTIONS]

Full NetTap installation: system deps, bridge, Malcolm, services.

Options:
  --skip-bridge        Skip bridge configuration
  --skip-pull          Skip Docker image pull (use cached)
  --skip-malcolm       Skip Malcolm deployment entirely
  --no-persist-bridge  Don't write persistent bridge config
  --defer-bridge       Defer bridge activation until after cable rewiring
  --immediate-bridge   (No-op, kept for backwards compatibility)
  --non-interactive    Auto-assign NICs without prompts
  --reconfigure-nics   Force NIC re-discovery even if .env has values
  --dry-run            Log without executing
  -v, --verbose        Debug output
  -h, --help           Show this help
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-bridge)       SKIP_BRIDGE="true"; shift ;;
        --skip-pull)         SKIP_PULL="true"; shift ;;
        --skip-malcolm)      SKIP_MALCOLM="true"; shift ;;
        --no-persist-bridge) PERSIST_BRIDGE="false"; shift ;;
        --defer-bridge)      DEFER_BRIDGE="true"; shift ;;
        --immediate-bridge)  shift ;;  # No-op, bridge activates by default now
        --non-interactive)   NON_INTERACTIVE="true"; shift ;;
        --reconfigure-nics)  RECONFIGURE_NICS="true"; shift ;;
        --dry-run)           NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
        -v|--verbose)        NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
        -h|--help)           usage ;;
        *)                   echo "Unknown option: $1"; usage ;;
    esac
done

# ===========================================================================
# NIC PREFLIGHT: Discover and assign NICs before main install
# ===========================================================================
step_nic_preflight() {
    # Check if .env already has NIC assignments
    local env_file="${PROJECT_ROOT}/.env"
    local needs_nics="false"

    if [[ ! -f "$env_file" ]]; then
        needs_nics="true"
    elif ! grep -q "^WAN_INTERFACE=" "$env_file" 2>/dev/null || \
         ! grep -q "^LAN_INTERFACE=" "$env_file" 2>/dev/null; then
        needs_nics="true"
    fi

    if [[ "$RECONFIGURE_NICS" == "true" ]]; then
        needs_nics="true"
    fi

    if [[ "$needs_nics" == "true" ]]; then
        local preflight_args=()
        preflight_args+=(--env-file "$env_file")

        if [[ "$NON_INTERACTIVE" == "true" ]]; then
            preflight_args+=(--non-interactive)
        fi

        if [[ "$RECONFIGURE_NICS" == "true" ]]; then
            preflight_args+=(--reconfigure-nics)
        fi

        if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
            preflight_args+=(--dry-run)
        fi

        if [[ "$NETTAP_VERBOSE" == "true" ]]; then
            preflight_args+=(-v)
        fi

        "${SCRIPT_DIR}/preflight.sh" "${preflight_args[@]}"
    else
        debug "NIC assignments found in .env, skipping NIC preflight"
    fi
}

# ===========================================================================
# STEP 0: Pre-flight checks
# ===========================================================================
step_preflight() {
    log ""
    log "=========================================="
    log "  NetTap Installation"
    log "  $(date '+%Y-%m-%d %H:%M:%S')"
    log "=========================================="
    log ""

    require_root
    load_env "${PROJECT_ROOT}/.env"

    log "[Step 0/8] Pre-flight checks..."

    # OS and architecture
    check_ubuntu
    check_arch

    # Hardware validation (source for the function, don't run standalone)
    source "${SCRIPT_DIR}/validate-hardware.sh"
    # Run validation but don't abort on warnings (rc=1)
    validate_hardware || {
        local rc=$?
        if (( rc == 2 )); then
            error "Hardware does not meet minimum requirements. See above for details."
        fi
        # rc=1 means warnings only — continue
        log "Continuing installation with hardware warnings..."
    }
}

# ===========================================================================
# STEP 1: System dependencies
# ===========================================================================
step_dependencies() {
    log "[Step 1/8] Installing system dependencies..."

    run apt-get update -qq

    # Docker — detect if docker-ce (official repo) is already installed.
    # docker-ce and docker.io conflict; install whichever isn't present.
    if dpkg -l docker-ce 2>/dev/null | grep -q "^ii"; then
        log "Docker CE (official) already installed, skipping docker.io"
    elif dpkg -l docker.io 2>/dev/null | grep -q "^ii"; then
        log "docker.io already installed"
    else
        # Neither installed — prefer docker.io (Ubuntu native)
        run apt-get install -y -qq docker.io
    fi

    # Non-Docker core packages
    run apt-get install -y -qq \
        bridge-utils \
        net-tools \
        ethtool \
        smartmontools \
        python3 \
        python3-pip \
        avahi-daemon \
        avahi-utils \
        curl \
        jq \
        openssl \
        ca-certificates \
        gnupg

    # Docker Compose plugin — package name varies by source:
    #   docker-compose-plugin  (Docker official repo / docker-ce)
    #   docker-compose-v2      (Ubuntu 24.04+ universe / docker.io)
    # Skip if already available (docker-ce bundles it).
    if docker compose version &>/dev/null; then
        debug "Docker Compose already available, skipping plugin install"
    elif apt-get install -y -qq docker-compose-plugin 2>/dev/null; then
        true  # installed from Docker official repo
    else
        log "docker-compose-plugin not found, trying docker-compose-v2..."
        run apt-get install -y -qq docker-compose-v2
    fi

    # Enable Docker
    run systemctl enable --now docker
    log "Docker enabled and running"

    # Verify docker compose is available
    if ! docker compose version &>/dev/null; then
        error "Docker Compose plugin not available. Install docker-compose-plugin or docker-compose-v2."
    fi
    debug "Docker Compose $(docker compose version --short 2>/dev/null) available"

    # Configure Docker daemon (log rotation, overlay2)
    if [[ ! -f /etc/docker/daemon.json ]]; then
        log "Configuring Docker daemon..."
        cat > /etc/docker/daemon.json <<'DAEMONJSON'
{
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "3"
    },
    "storage-driver": "overlay2"
}
DAEMONJSON
        run systemctl restart docker
        log "Docker daemon configured with log rotation"
    else
        debug "Docker daemon.json already exists, skipping"
    fi

    log "System dependencies installed"
}

# ===========================================================================
# STEP 2: Kernel tuning
# ===========================================================================
step_kernel_tuning() {
    log "[Step 2/8] Applying kernel tuning..."

    # Increase max map count for OpenSearch
    local sysctl_file="/etc/sysctl.d/99-nettap.conf"
    if [[ ! -f "$sysctl_file" ]]; then
        cat > "$sysctl_file" <<'SYSCTLEOF'
# NetTap kernel tuning

# Required by OpenSearch
vm.max_map_count = 262144

# Increase network buffer sizes for high-throughput capture
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.core.rmem_default = 16777216
net.core.netdev_max_backlog = 5000

# Increase conntrack table for busy networks
net.netfilter.nf_conntrack_max = 1048576
SYSCTLEOF
        run sysctl --system > /dev/null 2>&1
        log "Kernel parameters applied"
    else
        debug "Kernel tuning already configured"
    fi

    # Set vm.max_map_count immediately (OpenSearch requires this)
    run sysctl -q -w vm.max_map_count=262144 2>/dev/null || true
}

# ===========================================================================
# STEP 3: Network bridge
# ===========================================================================
step_bridge() {
    if [[ "$SKIP_BRIDGE" == "true" ]]; then
        log "[Step 3/8] Skipping bridge configuration (--skip-bridge)"
        return 0
    fi

    if [[ "$DEFER_BRIDGE" == "true" ]]; then
        log "[Step 3/8] Bridge activation DEFERRED (--defer-bridge)"
        log "  Run 'sudo scripts/install/activate-bridge.sh' after rewiring cables."
        return 0
    fi

    log "[Step 3/8] Configuring network bridge..."

    local bridge_args=()
    bridge_args+=(--wan "${WAN_INTERFACE:-eth0}")
    bridge_args+=(--lan "${LAN_INTERFACE:-eth1}")

    if [[ -n "${MGMT_INTERFACE:-}" ]]; then
        bridge_args+=(--mgmt "$MGMT_INTERFACE")
    fi

    if [[ "$PERSIST_BRIDGE" == "true" ]]; then
        bridge_args+=(--persist)
    fi

    if [[ "$NETTAP_VERBOSE" == "true" ]]; then
        bridge_args+=(-v)
    fi

    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        bridge_args+=(--dry-run)
    fi

    "${SCRIPT_DIR}/../bridge/setup-bridge.sh" "${bridge_args[@]}"
}

# ===========================================================================
# STEP 4: Malcolm deployment
# ===========================================================================
step_malcolm() {
    if [[ "$SKIP_MALCOLM" == "true" ]]; then
        log "[Step 4/8] Skipping Malcolm deployment (--skip-malcolm)"
        return 0
    fi

    log "[Step 4/8] Deploying Malcolm stack..."

    local deploy_args=()

    if [[ "$SKIP_PULL" == "true" ]]; then
        deploy_args+=(--skip-pull)
    fi

    if [[ "$DEFER_BRIDGE" == "true" ]]; then
        deploy_args+=(--no-start)
        log "  Services will not start until bridge is activated."
    fi

    if [[ "$NETTAP_VERBOSE" == "true" ]]; then
        deploy_args+=(-v)
    fi

    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        deploy_args+=(--dry-run)
    fi

    "${SCRIPT_DIR}/deploy-malcolm.sh" "${deploy_args[@]}"
}

# ===========================================================================
# STEP 5: Systemd services
# ===========================================================================
step_systemd() {
    log "[Step 5/8] Installing systemd services..."

    local service_file="/etc/systemd/system/nettap.service"
    local compose_file="${PROJECT_ROOT}/docker/docker-compose.yml"

    cat > "$service_file" <<SERVICEEOF
[Unit]
Description=NetTap Network Visibility Appliance
Documentation=https://github.com/EliasMarine/NetTap
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_ROOT}

# Pre-start: validate bridge is healthy
ExecStartPre=/bin/bash -c '${SCRIPT_DIR}/../bridge/setup-bridge.sh --validate-only || true'

# Start all containers
ExecStart=/usr/bin/docker compose -f ${compose_file} up -d

# Stop all containers gracefully
ExecStop=/usr/bin/docker compose -f ${compose_file} down

# Restart policy handled by Docker (restart: unless-stopped)
TimeoutStartSec=600
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
SERVICEEOF

    run systemctl daemon-reload
    run systemctl enable nettap.service
    log "Systemd service installed and enabled (nettap.service)"
    log "  Start:   systemctl start nettap"
    log "  Stop:    systemctl stop nettap"
    log "  Status:  systemctl status nettap"
    log "  Logs:    journalctl -u nettap"
}

# ===========================================================================
# STEP 6: mDNS / Avahi
# ===========================================================================
step_mdns() {
    log "[Step 6/8] Configuring mDNS (${NETTAP_HOSTNAME:-nettap.local})..."

    local hostname="${NETTAP_HOSTNAME:-nettap.local}"
    # Strip .local suffix for hostnamectl
    hostname="${hostname%.local}"

    # Set the system hostname
    run hostnamectl set-hostname "$hostname" 2>/dev/null || \
        debug "Could not set hostname (may be in container/VM)"

    # Configure Avahi for mDNS broadcast
    local avahi_conf="/etc/avahi/avahi-daemon.conf"
    if [[ -f "$avahi_conf" ]]; then
        # Ensure avahi uses the correct hostname
        if grep -q "^host-name=" "$avahi_conf"; then
            run sed -i "s/^host-name=.*/host-name=${hostname}/" "$avahi_conf"
        else
            run sed -i "/^\[server\]/a host-name=${hostname}" "$avahi_conf"
        fi

        # Publish the hostname
        if grep -q "^publish-addresses=" "$avahi_conf"; then
            run sed -i "s/^publish-addresses=.*/publish-addresses=yes/" "$avahi_conf"
        fi

        run systemctl enable --now avahi-daemon
        run systemctl restart avahi-daemon 2>/dev/null || true
        log "Avahi mDNS configured — dashboard accessible at ${hostname}.local"
    else
        warn "Avahi config not found. Install avahi-daemon for mDNS support."
    fi
}

# ===========================================================================
# STEP 7: Firewall (if UFW is active)
# ===========================================================================
step_firewall() {
    log "[Step 7/8] Configuring firewall rules..."

    if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
        log "UFW is active, adding NetTap rules..."

        # Allow dashboard access (HTTPS)
        run ufw allow "${DASHBOARD_PORT:-443}/tcp" comment "NetTap dashboard"

        # Allow Malcolm dashboards (if different port)
        local malcolm_port="${MALCOLM_HTTPS_PORT:-9443}"
        if [[ "$malcolm_port" != "${DASHBOARD_PORT:-443}" ]]; then
            run ufw allow "${malcolm_port}/tcp" comment "Malcolm dashboards"
        fi

        # Allow mDNS
        run ufw allow 5353/udp comment "mDNS (avahi)"

        log "Firewall rules added"
    else
        debug "UFW not active, skipping firewall configuration"
    fi
}

# ===========================================================================
# STEP 8: Post-install verification
# ===========================================================================
step_verify() {
    log "[Step 8/8] Running post-install verification..."
    echo ""

    # --- Deferred bridge mode: skip bridge/container checks, print rewiring guide ---
    if [[ "$DEFER_BRIDGE" == "true" ]]; then
        local checks_passed=0
        local checks_warned=0

        # Docker check
        if docker info &>/dev/null; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} Docker is running"
            (( ++checks_passed ))
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} Docker is not running"
            (( ++checks_warned ))
        fi

        # Systemd check
        if systemctl is-enabled nettap.service &>/dev/null; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} nettap.service enabled"
            (( ++checks_passed ))
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} nettap.service not enabled"
            (( ++checks_warned ))
        fi

        # mDNS check
        if systemctl is-active avahi-daemon &>/dev/null; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} Avahi mDNS active (${NETTAP_HOSTNAME:-nettap.local})"
            (( ++checks_passed ))
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} Avahi mDNS not running"
            (( ++checks_warned ))
        fi

        # Kernel tuning check
        local map_count
        map_count=$(sysctl -n vm.max_map_count 2>/dev/null) || map_count=0
        if (( map_count >= 262144 )); then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} vm.max_map_count = ${map_count}"
            (( ++checks_passed ))
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} vm.max_map_count = ${map_count} (should be >= 262144)"
            (( ++checks_warned ))
        fi

        local elapsed=$(( $(date +%s) - INSTALL_START_TIME ))
        local minutes=$(( elapsed / 60 ))
        local seconds=$(( elapsed % 60 ))

        echo ""
        echo "=========================================="
        echo "  Installation Summary (bridge deferred)"
        echo "=========================================="
        echo "  Passed:   ${checks_passed}"
        echo "  Warnings: ${checks_warned}"
        echo "  Time:     ${minutes}m ${seconds}s"
        echo ""

        # Print rewiring instructions using .env values
        load_env "${PROJECT_ROOT}/.env"
        local wan="${WAN_INTERFACE:-eth0}"
        local lan="${LAN_INTERFACE:-eth1}"
        local mgmt="${MGMT_INTERFACE:-}"

        echo "  =========================================="
        echo "    NEXT STEPS — Physical Rewiring"
        echo "  =========================================="
        echo ""
        echo "  1. Plug ISP modem  --> ${wan} (WAN)"
        echo "  2. Plug ${lan} (LAN) --> Router WAN port"
        if [[ -n "$mgmt" ]]; then
            echo "  3. Keep ${mgmt} (MGMT) connected for dashboard"
        else
            echo "  3. Keep Wi-Fi connected — it's your dashboard access"
        fi
        echo ""
        echo "     [ISP Modem] --> [${wan}] ==BRIDGE== [${lan}] --> [Router]"
        echo "                              NetTap"
        if [[ -n "$mgmt" ]]; then
            echo "     [${mgmt} MGMT] --> dashboard at https://${NETTAP_HOSTNAME:-nettap.local}"
        else
            echo "     [Wi-Fi MGMT] --> dashboard at https://${NETTAP_HOSTNAME:-nettap.local}"
        fi
        echo ""
        echo "  Then run:  sudo scripts/install/activate-bridge.sh"
        echo ""
        echo "=========================================="
        echo ""
        return 0
    fi

    # --- Normal (immediate) mode verification ---
    local checks_passed=0
    local checks_failed=0
    local checks_warned=0

    # Bridge check
    if ip link show br0 &>/dev/null; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Bridge br0 exists"
        (( ++checks_passed ))
    else
        if [[ "$SKIP_BRIDGE" == "true" ]]; then
            echo "${_CLR_YLW}[SKIP]${_CLR_RST} Bridge check skipped"
        else
            echo "${_CLR_RED}[FAIL]${_CLR_RST} Bridge br0 not found"
            (( ++checks_failed ))
        fi
    fi

    # Docker check
    if docker info &>/dev/null; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Docker is running"
        (( ++checks_passed ))
    else
        echo "${_CLR_RED}[FAIL]${_CLR_RST} Docker is not running"
        (( ++checks_failed ))
    fi

    # Container check
    if [[ "$SKIP_MALCOLM" != "true" ]]; then
        local running
        running=$(docker compose -f "${PROJECT_ROOT}/docker/docker-compose.yml" ps -q 2>/dev/null | wc -l) || running=0
        if (( running > 0 )); then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${running} container(s) running"
            (( ++checks_passed ))
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} No containers detected (may still be starting)"
            (( ++checks_warned ))
        fi

        # OpenSearch check
        if curl -skf "https://localhost:9200/_cluster/health" > /dev/null 2>&1; then
            local health
            health=$(curl -sk "https://localhost:9200/_cluster/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null) || health="unknown"
            if [[ "$health" == "green" || "$health" == "yellow" ]]; then
                echo "${_CLR_GRN}[ OK ]${_CLR_RST} OpenSearch cluster health: ${health}"
                (( ++checks_passed ))
            else
                echo "${_CLR_YLW}[WARN]${_CLR_RST} OpenSearch cluster health: ${health}"
                (( ++checks_warned ))
            fi
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} OpenSearch not responding yet (may need a few minutes)"
            (( ++checks_warned ))
        fi
    fi

    # Systemd check
    if systemctl is-enabled nettap.service &>/dev/null; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} nettap.service enabled"
        (( ++checks_passed ))
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} nettap.service not enabled"
        (( ++checks_warned ))
    fi

    # mDNS check
    if systemctl is-active avahi-daemon &>/dev/null; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Avahi mDNS active (${NETTAP_HOSTNAME:-nettap.local})"
        (( ++checks_passed ))
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} Avahi mDNS not running"
        (( ++checks_warned ))
    fi

    # Kernel tuning check
    local map_count
    map_count=$(sysctl -n vm.max_map_count 2>/dev/null) || map_count=0
    if (( map_count >= 262144 )); then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} vm.max_map_count = ${map_count}"
        (( ++checks_passed ))
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} vm.max_map_count = ${map_count} (should be >= 262144)"
        (( ++checks_warned ))
    fi

    # Summary
    local elapsed=$(( $(date +%s) - INSTALL_START_TIME ))
    local minutes=$(( elapsed / 60 ))
    local seconds=$(( elapsed % 60 ))

    echo ""
    echo "=========================================="
    echo "  Installation Summary"
    echo "=========================================="
    echo "  Passed:   ${checks_passed}"
    echo "  Warnings: ${checks_warned}"
    echo "  Failed:   ${checks_failed}"
    echo "  Time:     ${minutes}m ${seconds}s"
    echo ""

    if (( checks_failed > 0 )); then
        echo "${_CLR_RED}  Some checks failed. Review the output above.${_CLR_RST}"
    else
        echo "${_CLR_GRN}  NetTap installation complete!${_CLR_RST}"
    fi

    echo ""
    echo "  Malcolm Dashboards:  https://localhost:${MALCOLM_HTTPS_PORT:-9443}"
    echo "  NetTap Dashboard:    https://${NETTAP_HOSTNAME:-nettap.local}:${DASHBOARD_PORT:-443}"
    echo ""
    echo "  Manage services:     systemctl {start|stop|restart} nettap"
    echo "  View logs:           journalctl -u nettap -f"
    echo "  Container status:    docker compose -f docker/docker-compose.yml ps"
    echo "=========================================="
    echo ""

    # Print rewiring instructions (bridge is active, just needs cables)
    load_env "${PROJECT_ROOT}/.env"
    local wan="${WAN_INTERFACE:-eth0}"
    local lan="${LAN_INTERFACE:-eth1}"
    local mgmt="${MGMT_INTERFACE:-}"

    echo "  =========================================="
    echo "    INSTALL COMPLETE — Now Rewire Cables"
    echo "  =========================================="
    echo ""
    echo "  The bridge is active and services are running."
    echo "  Plug in your cables — traffic will flow immediately."
    echo ""
    echo "  1. Plug ISP modem  --> ${wan} (WAN)"
    echo "  2. Plug ${lan} (LAN) --> Router WAN port"
    if [[ -n "$mgmt" ]]; then
        echo "  3. Keep ${mgmt} (MGMT) connected for dashboard access"
    else
        echo "  3. Keep Wi-Fi connected for dashboard access"
    fi
    echo ""
    echo "     [ISP Modem] --> [${wan}] ==BRIDGE== [${lan}] --> [Router]"
    echo "                              NetTap"
    if [[ -n "$mgmt" ]]; then
        echo "     [${mgmt} MGMT] --> dashboard at https://${NETTAP_HOSTNAME:-nettap.local}"
    else
        echo "     [Wi-Fi MGMT] --> dashboard at https://${NETTAP_HOSTNAME:-nettap.local}"
    fi
    echo ""
    echo "  Dashboard: https://${NETTAP_HOSTNAME:-nettap.local}:${DASHBOARD_PORT:-443}"
    echo ""
    echo "=========================================="
    echo ""
}

# ===========================================================================
# MAIN
# ===========================================================================
main() {
    step_nic_preflight
    step_preflight
    step_dependencies
    step_kernel_tuning
    step_bridge
    step_malcolm
    step_systemd
    step_mdns
    step_firewall
    step_verify
}

main
