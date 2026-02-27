#!/usr/bin/env bash
# NetTap — Kernel bridge resilience hardening (Phase 4C.2)
# Hardens the Linux bridge so that Layer 2 forwarding continues even if
# userspace daemons (Zeek, Suricata, Docker) crash or hang.  The bridge
# itself is a kernel datapath — this script ensures nothing in iptables,
# ip6tables, or arptables can interfere with it, and that forwarding is
# unconditionally enabled at the kernel level.
#
# Usage:
#   sudo ./harden-bridge.sh            # Apply all hardening settings
#   sudo ./harden-bridge.sh --check    # Verify without changing anything
#   sudo ./harden-bridge.sh --dry-run  # Log what would be done
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
load_env

BRIDGE_NAME="${BRIDGE_NAME:-br0}"
SYSCTL_CONF="/etc/sysctl.d/99-nettap-bridge-hardening.conf"

# Modes
MODE_CHECK="false"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Hardens the kernel bridge configuration for NetTap resilience.
Ensures Layer 2 forwarding survives userspace daemon and container crashes.

Options:
  --check          Verify all hardening settings without making changes
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
        --check)     MODE_CHECK="true"; shift ;;
        --dry-run)   NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
        -v|--verbose) NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
        -h|--help)   usage ;;
        *)           echo "Unknown option: $1"; usage ;;
    esac
done

# ===========================================================================
# SYSCTL SETTINGS — These are the kernel parameters we harden
# ===========================================================================
# Each entry: "key=expected_value description"
# These ensure the bridge operates as a pure L2 forwarding engine.
declare -a SYSCTL_SETTINGS=(
    # Prevent iptables from filtering bridged frames — critical for inline tap.
    # Without this, Docker's iptables rules can drop bridged traffic.
    "net.bridge.bridge-nf-call-iptables=0"
    # Same for IPv6 firewall rules
    "net.bridge.bridge-nf-call-ip6tables=0"
    # Same for ARP filtering
    "net.bridge.bridge-nf-call-arptables=0"
    # Enable kernel IP forwarding — belt-and-suspenders for routing scenarios
    "net.ipv4.ip_forward=1"
)

# ---------------------------------------------------------------------------
# Helper: Load br_netfilter module if needed
# ---------------------------------------------------------------------------
ensure_br_netfilter_loaded() {
    # The net.bridge.bridge-nf-call-* sysctls only exist when the
    # br_netfilter module is loaded.  We load it so we can set them to 0,
    # ensuring that if something else loads br_netfilter later, the values
    # are already pinned.
    if [[ ! -d /proc/sys/net/bridge ]]; then
        debug "Loading br_netfilter kernel module"
        run modprobe br_netfilter
        if [[ ! -d /proc/sys/net/bridge ]]; then
            warn "br_netfilter module could not be loaded — bridge-nf-call sysctls unavailable"
            warn "If bridging is handled purely in the kernel bridge module, this is acceptable"
            return 1
        fi
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Helper: Read a sysctl value
# ---------------------------------------------------------------------------
get_sysctl_value() {
    local key="$1"
    sysctl -n "$key" 2>/dev/null || echo "UNAVAILABLE"
}

# ---------------------------------------------------------------------------
# Helper: Parse key=value
# ---------------------------------------------------------------------------
parse_sysctl_entry() {
    local entry="$1"
    SYSCTL_KEY="${entry%%=*}"
    SYSCTL_VAL="${entry#*=}"
}

# ===========================================================================
# CHECK MODE — verify all settings without changing anything
# ===========================================================================
if [[ "$MODE_CHECK" == "true" ]]; then
    log "Verifying kernel bridge hardening settings..."
    echo ""
    echo "=========================================="
    echo "  NetTap Bridge Hardening Check"
    echo "=========================================="
    echo ""

    issues=0

    # Attempt to make sysctls visible (non-destructive, just loads the module)
    ensure_br_netfilter_loaded || true

    for entry in "${SYSCTL_SETTINGS[@]}"; do
        parse_sysctl_entry "$entry"
        current=$(get_sysctl_value "$SYSCTL_KEY")
        if [[ "$current" == "$SYSCTL_VAL" ]]; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${SYSCTL_KEY} = ${current}"
        elif [[ "$current" == "UNAVAILABLE" ]]; then
            echo "${_CLR_YLW}[SKIP]${_CLR_RST} ${SYSCTL_KEY} — sysctl not available (module not loaded?)"
            (( ++issues ))
        else
            echo "${_CLR_RED}[FAIL]${_CLR_RST} ${SYSCTL_KEY} = ${current} (expected: ${SYSCTL_VAL})"
            (( ++issues ))
        fi
    done

    # Check sysctl.d config file exists
    echo ""
    if [[ -f "$SYSCTL_CONF" ]]; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Persistent config exists: ${SYSCTL_CONF}"
    else
        echo "${_CLR_RED}[FAIL]${_CLR_RST} Persistent config missing: ${SYSCTL_CONF}"
        (( ++issues ))
    fi

    # Check br_netfilter is set to auto-load
    if [[ -f /etc/modules-load.d/nettap-br-netfilter.conf ]]; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} br_netfilter auto-load configured"
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} br_netfilter auto-load not configured (may not persist across reboot)"
        (( ++issues ))
    fi

    # Check bridge exists and is forwarding
    if ip link show "$BRIDGE_NAME" &>/dev/null; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Bridge ${BRIDGE_NAME} exists"
        # Verify STP is off
        stp_state=$(cat "/sys/class/net/${BRIDGE_NAME}/bridge/stp_state" 2>/dev/null) || stp_state="unknown"
        if [[ "$stp_state" == "0" ]]; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} STP disabled on ${BRIDGE_NAME}"
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} STP state: ${stp_state} (should be 0)"
            (( ++issues ))
        fi
    else
        echo "${_CLR_YLW}[INFO]${_CLR_RST} Bridge ${BRIDGE_NAME} not present (hardening still applies at boot)"
    fi

    echo ""
    echo "------------------------------------------"
    if (( issues > 0 )); then
        echo "${_CLR_YLW}RESULT: ${issues} issue(s) found${_CLR_RST}"
        exit 1
    else
        echo "${_CLR_GRN}RESULT: All hardening settings verified${_CLR_RST}"
        exit 0
    fi
fi

# ===========================================================================
# APPLY MODE — requires root
# ===========================================================================
require_root

log "Applying kernel bridge hardening settings..."

# ---------------------------------------------------------------------------
# Step 1: Ensure br_netfilter module is loaded and set to auto-load
# ---------------------------------------------------------------------------
log "Ensuring br_netfilter kernel module is loaded..."
ensure_br_netfilter_loaded || true

# Persist module loading across reboots
if [[ ! -f /etc/modules-load.d/nettap-br-netfilter.conf ]]; then
    run tee /etc/modules-load.d/nettap-br-netfilter.conf > /dev/null <<'MODULE_EOF'
# NetTap: Load br_netfilter so bridge-nf-call sysctls are available at boot.
# We load this module so we can DISABLE netfilter on the bridge (set to 0),
# preventing iptables/Docker rules from interfering with L2 forwarding.
br_netfilter
MODULE_EOF
    log "Configured br_netfilter to load at boot"
else
    debug "br_netfilter auto-load already configured"
fi

# ---------------------------------------------------------------------------
# Step 2: Apply sysctl settings at runtime
# ---------------------------------------------------------------------------
log "Applying sysctl settings at runtime..."

for entry in "${SYSCTL_SETTINGS[@]}"; do
    parse_sysctl_entry "$entry"
    current=$(get_sysctl_value "$SYSCTL_KEY")
    if [[ "$current" == "$SYSCTL_VAL" ]]; then
        debug "${SYSCTL_KEY} already set to ${SYSCTL_VAL}"
    elif [[ "$current" == "UNAVAILABLE" ]]; then
        warn "Cannot set ${SYSCTL_KEY} — sysctl not available"
    else
        run sysctl -q -w "${SYSCTL_KEY}=${SYSCTL_VAL}"
        log "Set ${SYSCTL_KEY} = ${SYSCTL_VAL} (was: ${current})"
    fi
done

# ---------------------------------------------------------------------------
# Step 3: Write persistent sysctl configuration
# ---------------------------------------------------------------------------
log "Writing persistent sysctl config to ${SYSCTL_CONF}..."

run tee "$SYSCTL_CONF" > /dev/null <<'SYSCTL_EOF'
# ==========================================================================
# NetTap Bridge Hardening — sysctl configuration
# Written by scripts/bridge/harden-bridge.sh
# ==========================================================================
# These settings ensure the kernel bridge operates as a pure Layer 2
# forwarding engine, independent of userspace processes.  If Docker,
# Zeek, Suricata, or any other daemon crashes, the bridge continues
# forwarding all traffic transparently.
#
# DO NOT EDIT MANUALLY — re-run harden-bridge.sh to regenerate.
# ==========================================================================

# --- Disable netfilter on bridged frames ---
# By default, bridged packets are passed through iptables/ip6tables/arptables.
# This is disastrous for an inline tap because Docker's iptables rules or
# firewall policies can inadvertently drop bridged traffic.  Setting these
# to 0 means bridged frames bypass netfilter entirely.
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-arptables = 0

# --- Enable IP forwarding ---
# Belt-and-suspenders: ensure the kernel forwards IP packets.
# The bridge operates at L2 and doesn't strictly need this, but some
# edge cases (e.g., management interface routing) benefit from it.
net.ipv4.ip_forward = 1
SYSCTL_EOF

log "Persistent sysctl config written"

# ---------------------------------------------------------------------------
# Step 4: Verify bridge-specific resilience settings
# ---------------------------------------------------------------------------
if ip link show "$BRIDGE_NAME" &>/dev/null; then
    log "Verifying bridge ${BRIDGE_NAME} resilience settings..."

    # Ensure STP is disabled — prevents bridge from entering blocking state
    local_stp=$(cat "/sys/class/net/${BRIDGE_NAME}/bridge/stp_state" 2>/dev/null) || local_stp="unknown"
    if [[ "$local_stp" != "0" ]]; then
        run ip link set "$BRIDGE_NAME" type bridge stp_state 0
        log "Disabled STP on ${BRIDGE_NAME}"
    else
        debug "STP already disabled on ${BRIDGE_NAME}"
    fi

    # Set forward delay to 0 — no learning delay
    local_fwd=$(cat "/sys/class/net/${BRIDGE_NAME}/bridge/forward_delay" 2>/dev/null) || local_fwd="unknown"
    if [[ "$local_fwd" != "0" ]]; then
        run ip link set "$BRIDGE_NAME" type bridge forward_delay 0
        log "Set forward_delay to 0 on ${BRIDGE_NAME}"
    else
        debug "Forward delay already 0 on ${BRIDGE_NAME}"
    fi

    # Disable multicast snooping — pass all multicast transparently
    local_mcast=$(cat "/sys/class/net/${BRIDGE_NAME}/bridge/multicast_snooping" 2>/dev/null) || local_mcast="unknown"
    if [[ "$local_mcast" != "0" ]]; then
        run ip link set "$BRIDGE_NAME" type bridge mcast_snooping 0
        log "Disabled multicast snooping on ${BRIDGE_NAME}"
    else
        debug "Multicast snooping already disabled on ${BRIDGE_NAME}"
    fi
else
    debug "Bridge ${BRIDGE_NAME} not present — bridge-specific tuning skipped (will apply at next bridge creation)"
fi

# ---------------------------------------------------------------------------
# Step 5: Reload sysctl to confirm persistence
# ---------------------------------------------------------------------------
log "Reloading sysctl to confirm persistent settings..."
run sysctl --system > /dev/null 2>&1 || warn "sysctl --system returned non-zero (some settings may not apply until reboot)"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "Bridge hardening complete."
log "  - Netfilter bypassed on bridged frames (iptables/ip6tables/arptables)"
log "  - IP forwarding enabled at kernel level"
log "  - Persistent config: ${SYSCTL_CONF}"
log "  - Module auto-load: /etc/modules-load.d/nettap-br-netfilter.conf"
log ""
log "The bridge will continue forwarding traffic even if all userspace"
log "processes (Docker, Zeek, Suricata, etc.) crash or are stopped."
log ""
log "Run '$0 --check' to verify settings at any time."
