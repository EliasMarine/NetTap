#!/usr/bin/env bash
# NetTap — Hardware watchdog timer service setup (Phase 4C.3)
# Installs and configures the Linux hardware watchdog daemon so that if
# the NetTap appliance hangs (kernel panic, OOM, runaway process), the
# hardware watchdog timer triggers a reboot, restoring network traffic
# flow within ~90 seconds.
#
# The watchdog daemon "pets" /dev/watchdog every 10 seconds.  If the
# daemon fails to pet for 60 seconds, the hardware initiates a hard
# reboot.  This is a last-resort failsafe — the bridge itself is a
# kernel datapath and should survive userspace hangs, but the watchdog
# covers kernel-level failures.
#
# Usage:
#   sudo ./setup-watchdog.sh                # Install and configure
#   sudo ./setup-watchdog.sh --enable       # Enable and start the service
#   sudo ./setup-watchdog.sh --disable      # Stop and disable the service
#   sudo ./setup-watchdog.sh --status       # Show current watchdog status
#   sudo ./setup-watchdog.sh --dry-run      # Log what would be done
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
load_env

WATCHDOG_CONF="/etc/watchdog.conf"
WATCHDOG_TEMPLATE="${SCRIPT_DIR}/../../config/watchdog/watchdog.conf"
WATCHDOG_SERVICE="watchdog.service"

# Modes
MODE_ENABLE="false"
MODE_DISABLE="false"
MODE_STATUS="false"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Installs and configures the hardware watchdog timer for NetTap failsafe
reboots.  If the system hangs, the watchdog triggers a hardware reboot.

Options:
  --enable         Enable and start the watchdog service
  --disable        Stop and disable the watchdog service
  --status         Show current watchdog status and configuration
  --dry-run        Log all commands without executing them
  -v, --verbose    Enable debug output
  -h, --help       Show this help message

Without --enable/--disable/--status, the script installs the watchdog
package and writes the configuration, but does not start the service.
Use --enable to activate it.
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
        --dry-run)   NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
        -v|--verbose) NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
        -h|--help)   usage ;;
        *)           echo "Unknown option: $1"; usage ;;
    esac
done

# ===========================================================================
# STATUS MODE
# ===========================================================================
if [[ "$MODE_STATUS" == "true" ]]; then
    echo ""
    echo "=========================================="
    echo "  NetTap Watchdog Status"
    echo "=========================================="
    echo ""

    # Check if watchdog package is installed
    if command -v watchdog &>/dev/null; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} watchdog package installed"
    else
        echo "${_CLR_RED}[FAIL]${_CLR_RST} watchdog package not installed"
    fi

    # Check if /dev/watchdog exists
    if [[ -c /dev/watchdog ]]; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} /dev/watchdog device present (hardware watchdog available)"
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} /dev/watchdog not present (hardware watchdog may not be supported)"
    fi

    # Check configuration
    if [[ -f "$WATCHDOG_CONF" ]]; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Configuration exists: ${WATCHDOG_CONF}"
        # Show key settings
        local_timeout=$(grep -E "^watchdog-timeout" "$WATCHDOG_CONF" 2>/dev/null | awk '{print $NF}') || local_timeout="unknown"
        local_interval=$(grep -E "^interval" "$WATCHDOG_CONF" 2>/dev/null | awk '{print $NF}') || local_interval="unknown"
        echo "       Timeout: ${local_timeout}s  |  Pet interval: ${local_interval}s"
    else
        echo "${_CLR_RED}[FAIL]${_CLR_RST} Configuration missing: ${WATCHDOG_CONF}"
    fi

    # Check systemd service status
    echo ""
    if systemctl is-enabled "$WATCHDOG_SERVICE" &>/dev/null; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${WATCHDOG_SERVICE} enabled (starts on boot)"
    else
        echo "${_CLR_YLW}[INFO]${_CLR_RST} ${WATCHDOG_SERVICE} not enabled"
    fi

    if systemctl is-active "$WATCHDOG_SERVICE" &>/dev/null; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${WATCHDOG_SERVICE} is running"
        # Show uptime
        systemctl show "$WATCHDOG_SERVICE" --property=ActiveEnterTimestamp 2>/dev/null | \
            sed 's/ActiveEnterTimestamp=/       Running since: /' || true
    else
        echo "${_CLR_YLW}[INFO]${_CLR_RST} ${WATCHDOG_SERVICE} is not running"
    fi

    echo ""
    echo "------------------------------------------"
    exit 0
fi

# ===========================================================================
# ENABLE MODE
# ===========================================================================
if [[ "$MODE_ENABLE" == "true" ]]; then
    require_root
    log "Enabling watchdog service..."

    if ! command -v watchdog &>/dev/null; then
        error "Watchdog package not installed. Run '$0' first to install and configure."
    fi

    run systemctl daemon-reload
    run systemctl enable "$WATCHDOG_SERVICE"
    run systemctl start "$WATCHDOG_SERVICE"

    log "Watchdog service enabled and started"
    log "The hardware watchdog will reboot the system if it hangs for >60 seconds"
    exit 0
fi

# ===========================================================================
# DISABLE MODE
# ===========================================================================
if [[ "$MODE_DISABLE" == "true" ]]; then
    require_root
    log "Disabling watchdog service..."

    run systemctl stop "$WATCHDOG_SERVICE" 2>/dev/null || true
    run systemctl disable "$WATCHDOG_SERVICE" 2>/dev/null || true

    log "Watchdog service stopped and disabled"
    warn "Hardware watchdog is no longer active — system will NOT auto-reboot on hang"
    exit 0
fi

# ===========================================================================
# INSTALL + CONFIGURE MODE (default)
# ===========================================================================
require_root

log "Setting up hardware watchdog timer..."

# ---------------------------------------------------------------------------
# Step 1: Install watchdog package
# ---------------------------------------------------------------------------
if command -v watchdog &>/dev/null; then
    log "Watchdog package already installed"
else
    log "Installing watchdog package..."
    run apt-get update -qq
    run apt-get install -y -qq watchdog
    log "Watchdog package installed"
fi

# ---------------------------------------------------------------------------
# Step 2: Load watchdog kernel modules
# ---------------------------------------------------------------------------
log "Loading watchdog kernel modules..."

# Try to load the Intel TCO watchdog (common on Intel N100 and similar)
# The softdog module is a fallback for systems without hardware watchdog
for module in iTCO_wdt softdog; do
    if run modprobe "$module" 2>/dev/null; then
        debug "Loaded watchdog module: ${module}"
        break
    else
        debug "Module ${module} not available, trying next"
    fi
done

# Verify /dev/watchdog is now present
if [[ -c /dev/watchdog ]]; then
    log "Hardware watchdog device available: /dev/watchdog"
else
    warn "/dev/watchdog not found — hardware watchdog may not be supported on this platform"
    warn "The watchdog daemon will still monitor system health (load, memory, ping)"
fi

# ---------------------------------------------------------------------------
# Step 3: Write watchdog configuration
# ---------------------------------------------------------------------------
log "Writing watchdog configuration to ${WATCHDOG_CONF}..."

# Backup existing config if present
if [[ -f "$WATCHDOG_CONF" ]]; then
    run cp "$WATCHDOG_CONF" "${WATCHDOG_CONF}.nettap-backup.$(date +%Y%m%d%H%M%S)"
    debug "Backed up existing watchdog.conf"
fi

# Use the template if available, otherwise write directly
if [[ -f "$WATCHDOG_TEMPLATE" ]]; then
    run cp "$WATCHDOG_TEMPLATE" "$WATCHDOG_CONF"
    log "Configuration written from template: ${WATCHDOG_TEMPLATE}"
else
    warn "Template not found at ${WATCHDOG_TEMPLATE}, writing config directly"
    run tee "$WATCHDOG_CONF" > /dev/null <<'CONF_EOF'
# ==========================================================================
# NetTap Watchdog Configuration
# Written by scripts/install/setup-watchdog.sh
# ==========================================================================
# The watchdog daemon pets /dev/watchdog every 10 seconds.  If the system
# hangs and the daemon cannot pet for 60 seconds, the hardware triggers a
# hard reboot.  This restores network traffic flow within ~90 seconds.
# ==========================================================================

# --- Hardware Watchdog Device ---
watchdog-device = /dev/watchdog

# --- Timing ---
# Pet the watchdog every 10 seconds
interval = 10

# Hardware timeout: reboot if no pet for 60 seconds
# Note: actual hardware timeout depends on the chipset; some cap at 30s.
# The watchdog daemon will negotiate with the hardware for the closest
# supported value.
watchdog-timeout = 60

# --- System Health Checks ---
# Reboot if 1-minute load average exceeds 24 (effectively disabled on
# a 4-core system; this is a safety net for runaway fork bombs)
max-load-1 = 24

# Reboot if free memory drops below 1 page (~4KB).  This is an extreme
# safety net — OOM killer should handle most cases before this triggers.
min-memory = 1

# Verify the network stack is alive by pinging localhost.
# If the kernel network stack is dead, bridged traffic is also dead.
ping = 127.0.0.1

# --- Logging ---
# Log watchdog events to syslog
log-dir = /var/log/watchdog

# --- Reboot behavior ---
# Run this script before rebooting (optional — can notify or flush logs)
#repair-binary = /usr/local/bin/nettap-watchdog-repair.sh

# Realtime scheduling priority (higher = more reliable pet timing)
realtime = yes
priority = 1
CONF_EOF
    log "Configuration written directly to ${WATCHDOG_CONF}"
fi

# Ensure log directory exists
run mkdir -p /var/log/watchdog

# ---------------------------------------------------------------------------
# Step 4: Configure systemd unit overrides
# ---------------------------------------------------------------------------
log "Configuring systemd overrides for watchdog service..."

# Create a systemd override to ensure the watchdog service starts early
# and has proper permissions
run mkdir -p /etc/systemd/system/watchdog.service.d

run tee /etc/systemd/system/watchdog.service.d/nettap.conf > /dev/null <<'SYSD_EOF'
# NetTap watchdog service overrides
# Ensure the watchdog starts early and restarts on failure.
[Unit]
Description=NetTap Hardware Watchdog Timer
After=network.target

[Service]
# Restart the daemon itself if it crashes (distinct from hardware reboot)
Restart=on-failure
RestartSec=5

# Give the watchdog daemon access to the device
SupplementaryGroups=

[Install]
WantedBy=multi-user.target
SYSD_EOF

run systemctl daemon-reload
log "Systemd overrides installed"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "Watchdog setup complete."
log "  - Package: watchdog (installed)"
log "  - Config:  ${WATCHDOG_CONF}"
log "  - Device:  /dev/watchdog"
log "  - Timeout: 60s (hardware reboot if no pet for 60s)"
log "  - Interval: 10s (pet every 10 seconds)"
log "  - Health:  ping 127.0.0.1, load < 24, memory > 1 page"
log ""
log "The watchdog service is configured but NOT started."
log "To activate it, run:"
log "  sudo $0 --enable"
log ""
log "To check status at any time:"
log "  sudo $0 --status"
