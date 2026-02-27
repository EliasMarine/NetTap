#!/usr/bin/env bash
# ==========================================================================
# NetTap — UFW firewall setup
# ==========================================================================
# Configures host firewall rules for a hardened NetTap appliance.
# Restricts access to internal services (OpenSearch, daemon) and only
# allows HTTPS and SSH on the management interface.
#
# Usage:
#   sudo ./scripts/install/setup-firewall.sh --enable [OPTIONS]
#
# Modes:
#   --enable           Apply and enable firewall rules
#   --disable          Disable the firewall (removes all rules)
#   --status           Show current firewall status and rules
#
# Options:
#   --mgmt <iface>     Management interface (default: $MGMT_INTERFACE or auto-detect)
#   --ssh-port <port>  SSH port (default: 22)
#   --https-port <port> Dashboard HTTPS port (default: 443)
#   --dry-run          Log all commands without executing
#   -v, --verbose      Enable debug output
#   -h, --help         Show help
# ==========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
load_env
MODE=""
MGMT_IFACE="${MGMT_INTERFACE:-}"
SSH_PORT="${SSH_PORT:-22}"
HTTPS_PORT="${DASHBOARD_PORT:-443}"
MALCOLM_PORT="${MALCOLM_HTTPS_PORT:-9443}"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: sudo $0 MODE [OPTIONS]

Configures UFW firewall rules for the NetTap appliance.

Modes (exactly one required):
  --enable             Apply and enable firewall rules
  --disable            Disable the firewall
  --status             Show current firewall status

Options:
  --mgmt <iface>       Management interface (default: auto-detect or \$MGMT_INTERFACE)
  --ssh-port <port>    SSH port (default: 22)
  --https-port <port>  Dashboard HTTPS port (default: 443)
  --dry-run            Log without executing
  -v, --verbose        Debug output
  -h, --help           Show this help
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --enable)       MODE="enable"; shift ;;
        --disable)      MODE="disable"; shift ;;
        --status)       MODE="status"; shift ;;
        --mgmt)         MGMT_IFACE="$2"; shift 2 ;;
        --ssh-port)     SSH_PORT="$2"; shift 2 ;;
        --https-port)   HTTPS_PORT="$2"; shift 2 ;;
        --dry-run)      NETTAP_DRY_RUN="true"; shift ;;
        -v|--verbose)   NETTAP_VERBOSE="true"; shift ;;
        -h|--help)      usage ;;
        *)              echo "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "$MODE" ]]; then
    echo "Error: A mode (--enable, --disable, or --status) is required."
    echo ""
    usage
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Auto-detect the management interface if not specified.
# The management interface is the one with a default route that is NOT
# part of the bridge (br0).
detect_mgmt_interface() {
    if [[ -n "$MGMT_IFACE" ]]; then
        debug "Using specified management interface: ${MGMT_IFACE}"
        return 0
    fi

    # Try to find the interface with a default route that isn't br0
    local iface
    iface=$(ip route show default 2>/dev/null \
        | grep -v "br0" \
        | head -1 \
        | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}') || true

    if [[ -n "$iface" ]]; then
        MGMT_IFACE="$iface"
        log "Auto-detected management interface: ${MGMT_IFACE}"
        return 0
    fi

    # Fallback: first non-bridge, non-loopback interface with an IP
    iface=$(ip -o addr show 2>/dev/null \
        | grep -v "lo\|br0\|docker\|veth" \
        | awk '{print $2}' \
        | head -1) || true

    if [[ -n "$iface" ]]; then
        MGMT_IFACE="$iface"
        warn "Could not detect management interface via default route."
        warn "Falling back to: ${MGMT_IFACE}"
        return 0
    fi

    error "Cannot detect management interface. Specify with --mgmt <iface>"
}

# ---------------------------------------------------------------------------
# Status mode
# ---------------------------------------------------------------------------
do_status() {
    log "Firewall status:"
    echo ""
    if command -v ufw &>/dev/null; then
        ufw status verbose
    else
        warn "UFW is not installed. Install with: apt-get install ufw"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Disable mode
# ---------------------------------------------------------------------------
do_disable() {
    require_root
    log "Disabling UFW firewall..."

    if ! command -v ufw &>/dev/null; then
        warn "UFW is not installed. Nothing to disable."
        return 0
    fi

    run ufw --force disable
    log "Firewall disabled. All ports are now accessible."
    warn "This is not recommended for production deployments."
}

# ---------------------------------------------------------------------------
# Enable mode — main firewall configuration
# ---------------------------------------------------------------------------
do_enable() {
    require_root

    # Ensure UFW is installed
    if ! command -v ufw &>/dev/null; then
        log "Installing UFW..."
        run apt-get update -qq
        run apt-get install -y -qq ufw
    fi

    detect_mgmt_interface

    log "Configuring NetTap firewall rules..."
    log "  Management interface:  ${MGMT_IFACE}"
    log "  SSH port:              ${SSH_PORT}"
    log "  HTTPS port:            ${HTTPS_PORT}"
    log "  Malcolm port:          ${MALCOLM_PORT}"
    log ""

    # -- Reset to clean state (non-interactive) --
    run ufw --force reset
    debug "UFW reset to defaults"

    # -- Default policies --
    run ufw default deny incoming
    run ufw default allow outgoing
    run ufw default deny routed
    log "Default policies: deny incoming, allow outgoing, deny routed"

    # -- Allow SSH on management interface only --
    run ufw allow in on "$MGMT_IFACE" to any port "$SSH_PORT" proto tcp comment "NetTap SSH (mgmt only)"
    log "Allowed SSH (port ${SSH_PORT}) on ${MGMT_IFACE}"

    # -- Allow HTTPS dashboard on management interface only --
    run ufw allow in on "$MGMT_IFACE" to any port "$HTTPS_PORT" proto tcp comment "NetTap dashboard HTTPS (mgmt only)"
    log "Allowed HTTPS (port ${HTTPS_PORT}) on ${MGMT_IFACE}"

    # -- Allow Malcolm dashboards on management interface (if different port) --
    if [[ "$MALCOLM_PORT" != "$HTTPS_PORT" ]]; then
        run ufw allow in on "$MGMT_IFACE" to any port "$MALCOLM_PORT" proto tcp comment "Malcolm dashboards HTTPS (mgmt only)"
        log "Allowed Malcolm dashboards (port ${MALCOLM_PORT}) on ${MGMT_IFACE}"
    fi

    # -- Allow HTTP for HTTPS redirect on management interface --
    run ufw allow in on "$MGMT_IFACE" to any port 80 proto tcp comment "NetTap HTTP->HTTPS redirect (mgmt only)"
    debug "Allowed HTTP redirect (port 80) on ${MGMT_IFACE}"

    # -- Allow mDNS on management interface for nettap.local discovery --
    run ufw allow in on "$MGMT_IFACE" to any port 5353 proto udp comment "mDNS/Avahi (mgmt only)"
    debug "Allowed mDNS (port 5353) on ${MGMT_IFACE}"

    # -- Block OpenSearch port from ALL external access --
    # Port 9200 is already bound to 127.0.0.1 in docker-compose, but
    # defense-in-depth: also block it at the firewall level.
    run ufw deny in to any port 9200 proto tcp comment "Block OpenSearch (internal only)"
    log "Blocked external access to OpenSearch (port 9200)"

    # -- Block daemon port from ALL external access --
    # The daemon should only be reachable from within the Docker network.
    run ufw deny in to any port 8880 proto tcp comment "Block NetTap daemon (internal only)"
    log "Blocked external access to daemon (port 8880)"

    # -- Block Redis port --
    run ufw deny in to any port 6379 proto tcp comment "Block Redis (internal only)"
    debug "Blocked external access to Redis (port 6379)"

    # -- Block Logstash Beats input --
    run ufw deny in to any port 5044 proto tcp comment "Block Logstash Beats (internal only)"
    debug "Blocked external access to Logstash (port 5044)"

    # -- Block Arkime viewer --
    run ufw deny in to any port 8005 proto tcp comment "Block Arkime viewer (internal only)"
    debug "Blocked external access to Arkime viewer (port 8005)"

    # -- Allow DNS outbound (already covered by default allow outgoing, but
    #    explicitly noted for documentation / audit purposes) --
    debug "DNS (53) outbound is allowed by default outgoing policy"

    # -- Enable UFW --
    run ufw --force enable
    log ""
    log "Firewall enabled and configured."
    log ""

    # Show summary
    do_status
    echo ""
    log "Firewall setup complete."
    log ""
    log "Allowed inbound (${MGMT_IFACE} only):"
    log "  - SSH:              port ${SSH_PORT}/tcp"
    log "  - HTTPS dashboard:  port ${HTTPS_PORT}/tcp"
    if [[ "$MALCOLM_PORT" != "$HTTPS_PORT" ]]; then
        log "  - Malcolm:          port ${MALCOLM_PORT}/tcp"
    fi
    log "  - HTTP redirect:    port 80/tcp"
    log "  - mDNS:             port 5353/udp"
    log ""
    log "Blocked from external access:"
    log "  - OpenSearch:       port 9200/tcp"
    log "  - Daemon API:       port 8880/tcp"
    log "  - Redis:            port 6379/tcp"
    log "  - Logstash:         port 5044/tcp"
    log "  - Arkime viewer:    port 8005/tcp"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "$MODE" in
    enable)  do_enable ;;
    disable) do_disable ;;
    status)  do_status ;;
    *)       error "Unknown mode: ${MODE}" ;;
esac
