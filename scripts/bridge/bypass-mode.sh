#!/usr/bin/env bash
# NetTap — Software bypass mode (Phase 4C.4)
# Toggles the NetTap appliance between "capture mode" (normal operation)
# and "bypass mode" (pure L2 forwarding with all capture disabled).
#
# In bypass mode:
#   - Zeek, Suricata, Arkime, and PCAP capture containers are stopped
#   - ebtables rules are flushed (clean L2 path)
#   - Promiscuous mode is disabled on bridge interfaces (no capture)
#   - A state file signals that bypass is active
#   - The bridge continues forwarding all traffic transparently
#
# Use cases:
#   - Maintenance windows (reduce resource usage during updates)
#   - Troubleshooting (isolate whether NetTap capture is causing issues)
#   - Emergency bypass (if capture is degrading network performance)
#
# Usage:
#   sudo ./bypass-mode.sh --enable       # Enter bypass mode
#   sudo ./bypass-mode.sh --disable      # Exit bypass mode (resume capture)
#   sudo ./bypass-mode.sh --status       # Show current mode
#   sudo ./bypass-mode.sh --install      # Install systemd service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
load_env

BRIDGE_NAME="${BRIDGE_NAME:-br0}"
WAN_INTERFACE="${WAN_INTERFACE:-eth0}"
LAN_INTERFACE="${LAN_INTERFACE:-eth1}"
BYPASS_STATE_FILE="/var/run/nettap-bypass-active"
COMPOSE_FILE="${SCRIPT_DIR}/../../docker/docker-compose.yml"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-nettap}"

# Capture services — these are stopped in bypass mode and started on resume.
# These must match the service names in docker-compose.yml.
CAPTURE_SERVICES=(
    "zeek-live"
    "suricata-live"
    "arkime-live"
    "pcap-capture"
)

# Modes
MODE_ENABLE="false"
MODE_DISABLE="false"
MODE_STATUS="false"
MODE_INSTALL="false"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Toggles NetTap between capture mode and bypass mode.
In bypass mode, the bridge continues forwarding but all capture is disabled.

Options:
  --enable         Enter bypass mode (stop capture, pure L2 forwarding)
  --disable        Exit bypass mode (resume capture)
  --status         Show current bypass state
  --install        Install systemd service for scheduled bypass
  --dry-run        Log all commands without executing them
  -v, --verbose    Enable debug output
  -h, --help       Show this help message
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --enable)    MODE_ENABLE="true"; shift ;;
        --disable)   MODE_DISABLE="true"; shift ;;
        --status)    MODE_STATUS="true"; shift ;;
        --install)   MODE_INSTALL="true"; shift ;;
        --dry-run)   NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
        -v|--verbose) NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
        -h|--help)   usage ;;
        *)           echo "Unknown option: $1"; usage ;;
    esac
done

# Ensure at least one mode is selected
if [[ "$MODE_ENABLE" == "false" && "$MODE_DISABLE" == "false" && \
      "$MODE_STATUS" == "false" && "$MODE_INSTALL" == "false" ]]; then
    echo "Error: No mode specified. Use --enable, --disable, --status, or --install."
    echo ""
    usage
fi

# ---------------------------------------------------------------------------
# Helper: Check if bypass mode is currently active
# ---------------------------------------------------------------------------
is_bypass_active() {
    [[ -f "$BYPASS_STATE_FILE" ]]
}

# ---------------------------------------------------------------------------
# Helper: Stop capture services via docker compose
# ---------------------------------------------------------------------------
stop_capture_services() {
    log "Stopping capture services..."

    if [[ ! -f "$COMPOSE_FILE" ]]; then
        warn "Docker compose file not found at ${COMPOSE_FILE}"
        warn "Attempting to stop containers by name..."
        for svc in "${CAPTURE_SERVICES[@]}"; do
            run docker stop "${COMPOSE_PROJECT}-${svc}-1" 2>/dev/null || \
                debug "Container ${COMPOSE_PROJECT}-${svc}-1 not running or not found"
        done
        return
    fi

    for svc in "${CAPTURE_SERVICES[@]}"; do
        run docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" stop "$svc" 2>/dev/null || \
            debug "Service ${svc} not running or not found"
        log "Stopped ${svc}"
    done
}

# ---------------------------------------------------------------------------
# Helper: Start capture services via docker compose
# ---------------------------------------------------------------------------
start_capture_services() {
    log "Starting capture services..."

    if [[ ! -f "$COMPOSE_FILE" ]]; then
        warn "Docker compose file not found at ${COMPOSE_FILE}"
        warn "Attempting to start containers by name..."
        for svc in "${CAPTURE_SERVICES[@]}"; do
            run docker start "${COMPOSE_PROJECT}-${svc}-1" 2>/dev/null || \
                debug "Container ${COMPOSE_PROJECT}-${svc}-1 not found"
        done
        return
    fi

    for svc in "${CAPTURE_SERVICES[@]}"; do
        run docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" start "$svc" 2>/dev/null || \
            warn "Failed to start ${svc} — it may need 'docker compose up -d' instead"
        log "Started ${svc}"
    done
}

# ---------------------------------------------------------------------------
# Helper: Flush ebtables rules for clean L2 path
# ---------------------------------------------------------------------------
flush_ebtables() {
    log "Flushing ebtables rules..."
    if command -v ebtables &>/dev/null; then
        run ebtables -F 2>/dev/null || debug "ebtables flush failed (may not have rules)"
        run ebtables -X 2>/dev/null || debug "ebtables chain delete failed"
        run ebtables -t nat -F 2>/dev/null || debug "ebtables nat flush failed"
        run ebtables -t nat -X 2>/dev/null || debug "ebtables nat chain delete failed"
        log "ebtables rules flushed"
    else
        debug "ebtables not installed — skipping (no L2 filtering rules to clear)"
    fi
}

# ---------------------------------------------------------------------------
# Helper: Disable promiscuous mode on bridge interfaces
# ---------------------------------------------------------------------------
disable_promisc() {
    log "Disabling promiscuous mode on bridge interfaces..."
    for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
        if ip link show "$iface" &>/dev/null; then
            run ip link set "$iface" promisc off
            debug "Promiscuous mode disabled on ${iface}"
        else
            debug "Interface ${iface} not found — skipping"
        fi
    done
    log "Promiscuous mode disabled — bridge interfaces are no longer capturing"
}

# ---------------------------------------------------------------------------
# Helper: Enable promiscuous mode on bridge interfaces
# ---------------------------------------------------------------------------
enable_promisc() {
    log "Enabling promiscuous mode on bridge interfaces..."
    for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
        if ip link show "$iface" &>/dev/null; then
            run ip link set "$iface" promisc on
            debug "Promiscuous mode enabled on ${iface}"
        else
            warn "Interface ${iface} not found — cannot enable promiscuous mode"
        fi
    done
    log "Promiscuous mode enabled — bridge interfaces are capturing"
}

# ===========================================================================
# STATUS MODE
# ===========================================================================
if [[ "$MODE_STATUS" == "true" ]]; then
    echo ""
    echo "=========================================="
    echo "  NetTap Bypass Mode Status"
    echo "=========================================="
    echo ""

    # Current mode
    if is_bypass_active; then
        echo "${_CLR_YLW}MODE: BYPASS (capture disabled)${_CLR_RST}"
        if [[ -f "$BYPASS_STATE_FILE" ]]; then
            echo "  Activated: $(stat -c '%y' "$BYPASS_STATE_FILE" 2>/dev/null || \
                                 stat -f '%Sm' "$BYPASS_STATE_FILE" 2>/dev/null || \
                                 echo 'unknown')"
        fi
    else
        echo "${_CLR_GRN}MODE: NORMAL (capture active)${_CLR_RST}"
    fi

    echo ""

    # Bridge status
    if ip link show "$BRIDGE_NAME" &>/dev/null; then
        local_state=$(ip -brief link show "$BRIDGE_NAME" 2>/dev/null | awk '{print $2}') || local_state="unknown"
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Bridge ${BRIDGE_NAME} is ${local_state}"
    else
        echo "${_CLR_RED}[FAIL]${_CLR_RST} Bridge ${BRIDGE_NAME} not found"
    fi

    # Promiscuous mode
    for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
        if ip link show "$iface" 2>/dev/null | grep -q "PROMISC"; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${iface} promiscuous mode: ON"
        elif ip link show "$iface" &>/dev/null; then
            echo "${_CLR_YLW}[INFO]${_CLR_RST} ${iface} promiscuous mode: OFF"
        else
            echo "${_CLR_RED}[FAIL]${_CLR_RST} ${iface} not found"
        fi
    done

    echo ""

    # Capture service status
    echo "Capture services:"
    for svc in "${CAPTURE_SERVICES[@]}"; do
        container_name="${COMPOSE_PROJECT}-${svc}-1"
        # Also try the container_name format from docker-compose.yml
        alt_container_name="nettap-${svc}"
        if docker inspect --format '{{.State.Status}}' "$container_name" &>/dev/null; then
            local_status=$(docker inspect --format '{{.State.Status}}' "$container_name" 2>/dev/null)
            if [[ "$local_status" == "running" ]]; then
                echo "  ${_CLR_GRN}[RUNNING]${_CLR_RST} ${svc}"
            else
                echo "  ${_CLR_YLW}[${local_status^^}]${_CLR_RST} ${svc}"
            fi
        elif docker inspect --format '{{.State.Status}}' "$alt_container_name" &>/dev/null; then
            local_status=$(docker inspect --format '{{.State.Status}}' "$alt_container_name" 2>/dev/null)
            if [[ "$local_status" == "running" ]]; then
                echo "  ${_CLR_GRN}[RUNNING]${_CLR_RST} ${svc}"
            else
                echo "  ${_CLR_YLW}[${local_status^^}]${_CLR_RST} ${svc}"
            fi
        else
            echo "  ${_CLR_RED}[NOT FOUND]${_CLR_RST} ${svc}"
        fi
    done

    # Systemd service status
    echo ""
    if systemctl is-enabled nettap-bypass.service &>/dev/null 2>&1; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} nettap-bypass.service installed and enabled"
    elif [[ -f /etc/systemd/system/nettap-bypass.service ]]; then
        echo "${_CLR_YLW}[INFO]${_CLR_RST} nettap-bypass.service installed but not enabled"
    else
        echo "${_CLR_YLW}[INFO]${_CLR_RST} nettap-bypass.service not installed (use --install)"
    fi

    echo ""
    echo "------------------------------------------"
    exit 0
fi

# ===========================================================================
# INSTALL MODE — install systemd service for bypass control
# ===========================================================================
if [[ "$MODE_INSTALL" == "true" ]]; then
    require_root

    log "Installing nettap-bypass systemd service..."

    # Resolve the absolute path to this script for the systemd unit
    BYPASS_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

    run tee /etc/systemd/system/nettap-bypass.service > /dev/null <<SYSD_EOF
# ==========================================================================
# NetTap Bypass Mode Service
# Written by scripts/bridge/bypass-mode.sh --install
# ==========================================================================
# This service enables bypass mode when started and disables it when stopped.
# It can be used for scheduled maintenance windows:
#
#   systemctl start nettap-bypass    # Enter bypass mode
#   systemctl stop nettap-bypass     # Resume capture
#
# For scheduled bypass (e.g., 2am-4am daily), create a systemd timer:
#   systemctl enable --now nettap-bypass-window.timer
# ==========================================================================

[Unit]
Description=NetTap Software Bypass Mode
Documentation=https://github.com/EliasMarine/NetTap
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes

# Enter bypass mode on start
ExecStart=${BYPASS_SCRIPT} --enable

# Resume capture on stop
ExecStop=${BYPASS_SCRIPT} --disable

# Timeout for container start/stop operations
TimeoutStartSec=120
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
SYSD_EOF

    run systemctl daemon-reload
    log "nettap-bypass.service installed"
    log ""
    log "Usage:"
    log "  systemctl start nettap-bypass    # Enter bypass mode"
    log "  systemctl stop nettap-bypass     # Resume capture"
    log "  systemctl status nettap-bypass   # Check current state"
    log ""
    log "For scheduled maintenance windows, create a timer unit."
    exit 0
fi

# ===========================================================================
# ENABLE BYPASS MODE
# ===========================================================================
if [[ "$MODE_ENABLE" == "true" ]]; then
    require_root

    if is_bypass_active; then
        warn "Bypass mode is already active (state file: ${BYPASS_STATE_FILE})"
        log "Use --disable to return to normal capture mode"
        exit 0
    fi

    log "============================================"
    log "  ENTERING BYPASS MODE"
    log "============================================"
    log ""
    log "Bridge will continue forwarding traffic."
    log "All capture and analysis will be stopped."
    log ""

    enable_cleanup_trap

    # Step 1: Stop capture services
    stop_capture_services
    push_cleanup "start_capture_services"

    # Step 2: Flush ebtables for clean L2 path
    flush_ebtables

    # Step 3: Disable promiscuous mode (no capture)
    disable_promisc
    push_cleanup "enable_promisc"

    # Step 4: Write state file
    run tee "$BYPASS_STATE_FILE" > /dev/null <<STATE_EOF
# NetTap bypass mode active
# Activated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
# Activated by: $(whoami)@$(hostname)
# To disable: bypass-mode.sh --disable
STATE_EOF
    log "State file written: ${BYPASS_STATE_FILE}"

    # All steps succeeded — clear cleanup trap
    disable_cleanup_trap

    log ""
    log "============================================"
    log "  BYPASS MODE ACTIVE"
    log "============================================"
    log ""
    log "Network traffic is flowing through the bridge (pure L2)."
    log "No packets are being captured or analyzed."
    log ""
    log "To resume capture: $0 --disable"
    log "To check status:   $0 --status"
    exit 0
fi

# ===========================================================================
# DISABLE BYPASS MODE (resume capture)
# ===========================================================================
if [[ "$MODE_DISABLE" == "true" ]]; then
    require_root

    if ! is_bypass_active; then
        warn "Bypass mode is not active (no state file at ${BYPASS_STATE_FILE})"
        log "Capture should already be running. Use --status to verify."
        exit 0
    fi

    log "============================================"
    log "  EXITING BYPASS MODE"
    log "============================================"
    log ""
    log "Resuming packet capture and analysis..."
    log ""

    # Step 1: Re-enable promiscuous mode for capture
    enable_promisc

    # Step 2: Start capture services
    start_capture_services

    # Step 3: Remove state file
    run rm -f "$BYPASS_STATE_FILE"
    log "State file removed"

    log ""
    log "============================================"
    log "  CAPTURE MODE RESTORED"
    log "============================================"
    log ""
    log "Zeek, Suricata, Arkime, and PCAP capture are running."
    log "Promiscuous mode is enabled on bridge interfaces."
    log ""
    log "To verify: $0 --status"
    exit 0
fi
