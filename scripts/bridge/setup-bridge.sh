#!/usr/bin/env bash
# NetTap — Linux bridge setup script
# Creates a transparent Layer 2 bridge between WAN and LAN NICs
# with performance tuning, validation, rollback, and optional persistence.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults (overridden by .env or arguments)
# ---------------------------------------------------------------------------
load_env
WAN_INTERFACE="${WAN_INTERFACE:-eth0}"
LAN_INTERFACE="${LAN_INTERFACE:-eth1}"
MGMT_INTERFACE="${MGMT_INTERFACE:-}"
BRIDGE_NAME="br0"

# Modes
MODE_PERSIST="false"
MODE_VALIDATE_ONLY="false"
MODE_TEARDOWN="false"
MODE_DETECT="false"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Creates a transparent network bridge between two interfaces for NetTap.

Options:
  --wan <iface>        WAN-side interface (default: \$WAN_INTERFACE or eth0)
  --lan <iface>        LAN-side interface (default: \$LAN_INTERFACE or eth1)
  --mgmt <iface>       Management interface for dashboard access (optional)
  --persist            Write netplan config and systemd units for boot persistence
  --no-persist         Skip persistence (runtime only, for testing)
  --validate-only      Check existing bridge config without making changes
  --teardown           Remove bridge and restore interfaces to original state
  --detect             Auto-detect NICs and suggest WAN/LAN assignment
  --dry-run            Log all commands without executing them
  -v, --verbose        Enable debug output
  -h, --help           Show this help message
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --wan)            WAN_INTERFACE="$2"; shift 2 ;;
        --lan)            LAN_INTERFACE="$2"; shift 2 ;;
        --mgmt)           MGMT_INTERFACE="$2"; shift 2 ;;
        --persist)        MODE_PERSIST="true"; shift ;;
        --no-persist)     MODE_PERSIST="false"; shift ;;
        --validate-only)  MODE_VALIDATE_ONLY="true"; shift ;;
        --teardown)       MODE_TEARDOWN="true"; shift ;;
        --detect)         MODE_DETECT="true"; shift ;;
        --dry-run)        NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
        -v|--verbose)     NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
        -h|--help)        usage ;;
        *)                echo "Unknown option: $1"; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Detect mode — just print NIC info and exit
# ---------------------------------------------------------------------------
if [[ "$MODE_DETECT" == "true" ]]; then
    # Source the hardware validation script for its detect_nics function
    source "${SCRIPT_DIR}/../install/validate-hardware.sh"
    detect_nics
    exit 0
fi

require_root

# ===========================================================================
# TEARDOWN MODE
# ===========================================================================
if [[ "$MODE_TEARDOWN" == "true" ]]; then
    log "Tearing down bridge ${BRIDGE_NAME}..."

    # Remove interfaces from bridge
    for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
        if ip link show "$iface" &>/dev/null; then
            run ip link set "$iface" promisc off 2>/dev/null || true
            run ip link set "$iface" nomaster 2>/dev/null || true
            run ip link set "$iface" down 2>/dev/null || true
            log "Removed ${iface} from bridge"
        fi
    done

    # Delete bridge
    if ip link show "$BRIDGE_NAME" &>/dev/null; then
        run ip link set "$BRIDGE_NAME" down 2>/dev/null || true
        run ip link del "$BRIDGE_NAME" 2>/dev/null || true
        log "Deleted bridge ${BRIDGE_NAME}"
    fi

    # Remove persistence files if they exist
    if [[ -f /etc/netplan/10-nettap-bridge.yaml ]]; then
        run rm -f /etc/netplan/10-nettap-bridge.yaml
        log "Removed netplan config"
    fi
    if [[ -f /etc/systemd/system/nettap-bridge-promisc.service ]]; then
        run systemctl disable nettap-bridge-promisc.service 2>/dev/null || true
        run rm -f /etc/systemd/system/nettap-bridge-promisc.service
        log "Removed promisc systemd unit"
    fi
    if [[ -f /etc/sysctl.d/99-nettap-bridge.conf ]]; then
        run rm -f /etc/sysctl.d/99-nettap-bridge.conf
        log "Removed sysctl config"
    fi
    if [[ -f /etc/NetworkManager/conf.d/99-nettap-unmanaged.conf ]]; then
        run rm -f /etc/NetworkManager/conf.d/99-nettap-unmanaged.conf
        run systemctl reload NetworkManager 2>/dev/null || true
        log "Removed NetworkManager unmanaged config"
    fi

    log "Teardown complete. Interfaces restored to default state."
    exit 0
fi

# ===========================================================================
# PRE-FLIGHT VALIDATION (Tasks 1.3)
# ===========================================================================
preflight_checks() {
    log "Running pre-flight checks..."

    # WAN and LAN must be different
    if [[ "$WAN_INTERFACE" == "$LAN_INTERFACE" ]]; then
        error "WAN and LAN interfaces must be different (both set to '${WAN_INTERFACE}')"
    fi

    # Both interfaces must exist
    check_interface_exists "$WAN_INTERFACE"
    check_interface_exists "$LAN_INTERFACE"

    # Management interface must be different from WAN/LAN if specified
    if [[ -n "$MGMT_INTERFACE" ]]; then
        if [[ "$MGMT_INTERFACE" == "$WAN_INTERFACE" || "$MGMT_INTERFACE" == "$LAN_INTERFACE" ]]; then
            error "Management interface (${MGMT_INTERFACE}) must be different from WAN (${WAN_INTERFACE}) and LAN (${LAN_INTERFACE})"
        fi
        check_interface_exists "$MGMT_INTERFACE"
    fi

    # Check neither NIC is already in a different bridge
    for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
        local master_path="/sys/class/net/${iface}/master"
        if [[ -d "$master_path" ]]; then
            local current_bridge
            current_bridge=$(basename "$(readlink -f "$master_path")" 2>/dev/null) || current_bridge="unknown"
            if [[ "$current_bridge" != "$BRIDGE_NAME" ]]; then
                error "${iface} is already a member of bridge '${current_bridge}'. Remove it first or use --teardown."
            else
                debug "${iface} already in ${BRIDGE_NAME} — will reconfigure"
            fi
        fi
    done

    # Warn if interfaces have IP addresses (they shouldn't on the data path)
    for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
        if ip addr show "$iface" 2>/dev/null | grep -q "inet "; then
            warn "${iface} has an IP address assigned. Bridge interfaces should not have IPs on the data path."
        fi
    done

    # Verify kernel bridge module
    if ! modprobe bridge 2>/dev/null; then
        error "Kernel bridge module is not available. Ensure your kernel supports bridging."
    fi
    debug "Bridge kernel module loaded"

    # Detect NetworkManager and warn
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
        warn "NetworkManager is running. It may interfere with bridge configuration."
        warn "Consider disabling it: systemctl disable --now NetworkManager"
    fi

    # Check for required commands
    check_command ip
    check_command sysctl

    log "Pre-flight checks passed"
}

# ===========================================================================
# VALIDATE EXISTING BRIDGE (--validate-only)
# ===========================================================================
validate_bridge() {
    local issues=0

    echo ""
    echo "=========================================="
    echo "  NetTap Bridge Validation"
    echo "=========================================="
    echo ""

    # Check bridge exists
    if ! ip link show "$BRIDGE_NAME" &>/dev/null; then
        echo "${_CLR_RED}[FAIL]${_CLR_RST} Bridge ${BRIDGE_NAME} does not exist"
        return 2
    fi
    echo "${_CLR_GRN}[ OK ]${_CLR_RST} Bridge ${BRIDGE_NAME} exists"

    # Check bridge is up (or at least not administratively DOWN)
    # With no cables attached, bridge state is UNKNOWN — that's expected and fine.
    local link_state
    link_state=$(ip -br link show "$BRIDGE_NAME" 2>/dev/null | awk '{print $2}') || link_state="UNKNOWN"
    if [[ "$link_state" == "UP" ]]; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Bridge is UP"
    elif [[ "$link_state" == "UNKNOWN" ]]; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Bridge is UP (no carrier — waiting for cables)"
    elif [[ "$link_state" == "DOWN" ]]; then
        echo "${_CLR_RED}[FAIL]${_CLR_RST} Bridge is administratively DOWN"
        (( issues++ ))
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} Bridge state: ${link_state}"
        (( issues++ ))
    fi

    # Check STP is disabled
    local stp_state
    stp_state=$(cat "/sys/class/net/${BRIDGE_NAME}/bridge/stp_state" 2>/dev/null) || stp_state="unknown"
    if [[ "$stp_state" == "0" ]]; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} STP disabled"
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} STP state: ${stp_state} (should be 0 for inline tap)"
        (( issues++ ))
    fi

    # Check each interface is enslaved
    for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
        local master_path="/sys/class/net/${iface}/master"
        if [[ -d "$master_path" ]]; then
            local actual_bridge
            actual_bridge=$(basename "$(readlink -f "$master_path")" 2>/dev/null) || actual_bridge="none"
            if [[ "$actual_bridge" == "$BRIDGE_NAME" ]]; then
                echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${iface} attached to ${BRIDGE_NAME}"
            else
                echo "${_CLR_RED}[FAIL]${_CLR_RST} ${iface} attached to ${actual_bridge} instead of ${BRIDGE_NAME}"
                (( issues++ ))
            fi
        else
            echo "${_CLR_RED}[FAIL]${_CLR_RST} ${iface} not attached to any bridge"
            (( issues++ ))
        fi

        # Check promiscuous mode
        if ip link show "$iface" 2>/dev/null | grep -q "PROMISC"; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${iface} promiscuous mode on"
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} ${iface} promiscuous mode not confirmed"
            (( issues++ ))
        fi
    done

    # Check forward delay
    local fwd_delay
    fwd_delay=$(cat "/sys/class/net/${BRIDGE_NAME}/bridge/forward_delay" 2>/dev/null) || fwd_delay="unknown"
    if [[ "$fwd_delay" == "0" ]]; then
        echo "${_CLR_GRN}[ OK ]${_CLR_RST} Forward delay: 0 (optimal)"
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} Forward delay: ${fwd_delay} (should be 0 for inline tap)"
        (( issues++ ))
    fi

    echo ""
    echo "------------------------------------------"
    if (( issues > 0 )); then
        echo "${_CLR_YLW}RESULT: ${issues} issue(s) found${_CLR_RST}"
        return 1
    else
        echo "${_CLR_GRN}RESULT: Bridge is healthy${_CLR_RST}"
        return 0
    fi
}

if [[ "$MODE_VALIDATE_ONLY" == "true" ]]; then
    validate_bridge
    exit $?
fi

# ===========================================================================
# CREATE / CONFIGURE BRIDGE
# ===========================================================================
preflight_checks
enable_cleanup_trap

log "Creating bridge ${BRIDGE_NAME} with ${WAN_INTERFACE} (WAN) and ${LAN_INTERFACE} (LAN)"

# ---- Create bridge ----
if ! ip link show "$BRIDGE_NAME" &>/dev/null; then
    run ip link add name "$BRIDGE_NAME" type bridge
    push_cleanup "ip link del $BRIDGE_NAME 2>/dev/null"
    log "Bridge ${BRIDGE_NAME} created"
else
    log "Bridge ${BRIDGE_NAME} already exists, reconfiguring"
fi

# ---- Disable STP — we are a transparent inline tap, not a switch ----
run ip link set "$BRIDGE_NAME" type bridge stp_state 0

# ---- Performance tuning (Task 1.4) ----
# Set forwarding delay to 0 — no need to learn MACs for an inline tap
run ip link set "$BRIDGE_NAME" type bridge forward_delay 0

# Disable multicast snooping — pass all multicast through transparently
run ip link set "$BRIDGE_NAME" type bridge mcast_snooping 0

# Disable ageing — don't expire MAC table entries (reduces jitter)
run ip link set "$BRIDGE_NAME" type bridge ageing_time 0

# ---- Add interfaces to bridge ----
for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
    run ip link set "$iface" up
    run ip link set "$iface" master "$BRIDGE_NAME"
    push_cleanup "ip link set $iface nomaster 2>/dev/null"

    # Enable promiscuous mode for packet capture
    run ip link set "$iface" promisc on
    push_cleanup "ip link set $iface promisc off 2>/dev/null"

    log "Added ${iface} to ${BRIDGE_NAME} (promisc on)"
done

# ---- Performance tuning: NIC offloading and ring buffers (Task 1.4) ----
for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
    # Disable hardware offloads that interfere with packet capture accuracy
    if command -v ethtool &>/dev/null; then
        run ethtool -K "$iface" tso off gso off gro off lro off 2>/dev/null || \
            debug "Could not disable all offloads on ${iface} (some may not be supported)"

        # Increase RX ring buffer for better capture under burst
        run ethtool -G "$iface" rx 4096 2>/dev/null || \
            debug "Could not set ring buffer on ${iface}"
    else
        debug "ethtool not available — skipping NIC offload tuning"
    fi
done

# ---- Disable bridge netfilter — avoid iptables overhead on bridged traffic ----
run sysctl -q -w net.bridge.bridge-nf-call-iptables=0 2>/dev/null || \
    debug "Could not disable bridge-nf-call-iptables (module may not be loaded)"
run sysctl -q -w net.bridge.bridge-nf-call-ip6tables=0 2>/dev/null || true
run sysctl -q -w net.bridge.bridge-nf-call-arptables=0 2>/dev/null || true

# ---- Bring bridge up (no IP address — transparent L2) ----
run ip link set "$BRIDGE_NAME" up

# ---- Disable IPv6 on bridge to stay invisible ----
run sysctl -q -w "net.ipv6.conf.${BRIDGE_NAME}.disable_ipv6=1"

# Bridge is up — clear the rollback trap
disable_cleanup_trap

log "Bridge ${BRIDGE_NAME} is up and forwarding traffic"

# ===========================================================================
# PERSISTENCE (Task 1.5 — enabled with --persist)
# ===========================================================================
if [[ "$MODE_PERSIST" == "true" ]]; then
    log "Writing persistence configuration..."

    # ---- Netplan config ----
    local_netplan="/etc/netplan/10-nettap-bridge.yaml"
    cat > "$local_netplan" <<NETPLAN_EOF
# NetTap bridge configuration — managed by setup-bridge.sh
# Do not edit manually; re-run setup-bridge.sh --persist to regenerate.
network:
  version: 2
  renderer: networkd
  ethernets:
    ${WAN_INTERFACE}:
      dhcp4: false
      dhcp6: false
      optional: true
    ${LAN_INTERFACE}:
      dhcp4: false
      dhcp6: false
      optional: true
  bridges:
    ${BRIDGE_NAME}:
      interfaces:
        - ${WAN_INTERFACE}
        - ${LAN_INTERFACE}
      dhcp4: false
      dhcp6: false
      parameters:
        stp: false
        forward-delay: 0
NETPLAN_EOF
    chmod 600 "$local_netplan"
    log "Netplan config written to ${local_netplan}"

    # ---- Sysctl persistence ----
    cat > /etc/sysctl.d/99-nettap-bridge.conf <<SYSCTL_EOF
# NetTap bridge performance settings
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-arptables = 0
net.ipv6.conf.${BRIDGE_NAME}.disable_ipv6 = 1
SYSCTL_EOF
    log "Sysctl config written to /etc/sysctl.d/99-nettap-bridge.conf"

    # ---- Systemd unit for promiscuous mode (netplan can't set this) ----
    cat > /etc/systemd/system/nettap-bridge-promisc.service <<SYSD_EOF
[Unit]
Description=NetTap bridge promiscuous mode
After=network-online.target sys-subsystem-net-devices-${BRIDGE_NAME}.device
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/ip link set ${WAN_INTERFACE} promisc on
ExecStart=/usr/sbin/ip link set ${LAN_INTERFACE} promisc on

[Install]
WantedBy=multi-user.target
SYSD_EOF
    run systemctl daemon-reload
    run systemctl enable nettap-bridge-promisc.service
    log "Systemd promisc unit installed and enabled"

    # ---- Management interface ----
    # The management interface (especially Wi-Fi) stays under NetworkManager.
    # We do NOT add it to the networkd netplan config — NM is already managing
    # it and networkd cannot handle Wi-Fi. Only wired mgmt interfaces with a
    # static IP get added to netplan (under ethernets:, not bridges:).
    if [[ -n "$MGMT_INTERFACE" ]]; then
        mgmt_ip="${MGMT_IP:-}"
        # Only add wired mgmt interfaces with explicit static IPs to netplan
        if [[ -n "$mgmt_ip" ]] && [[ ! "$MGMT_INTERFACE" =~ ^wl ]]; then
            mgmt_netmask="${MGMT_NETMASK:-255.255.255.0}"
            # Re-write netplan to include mgmt under ethernets (not bridges)
            cat > "$local_netplan" <<NETPLAN_MGMT_EOF
# NetTap bridge configuration — managed by setup-bridge.sh
# Do not edit manually; re-run setup-bridge.sh --persist to regenerate.
network:
  version: 2
  renderer: networkd
  ethernets:
    ${WAN_INTERFACE}:
      dhcp4: false
      dhcp6: false
      optional: true
    ${LAN_INTERFACE}:
      dhcp4: false
      dhcp6: false
      optional: true
    ${MGMT_INTERFACE}:
      dhcp4: false
      addresses:
        - ${mgmt_ip}/$(mask_to_cidr "$mgmt_netmask" 2>/dev/null || echo "24")
  bridges:
    ${BRIDGE_NAME}:
      interfaces:
        - ${WAN_INTERFACE}
        - ${LAN_INTERFACE}
      dhcp4: false
      dhcp6: false
      parameters:
        stp: false
        forward-delay: 0
NETPLAN_MGMT_EOF
            chmod 600 "$local_netplan"
            log "Management interface ${MGMT_INTERFACE} (static IP) added to netplan"
        else
            debug "Management interface ${MGMT_INTERFACE} left under NetworkManager (Wi-Fi or DHCP)"
        fi
    fi

    # ---- Tell NetworkManager to leave bridge interfaces alone ----
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
        nm_conf="/etc/NetworkManager/conf.d/99-nettap-unmanaged.conf"
        cat > "$nm_conf" <<NM_EOF
# NetTap: prevent NetworkManager from managing bridge interfaces
[keyfile]
unmanaged-devices=interface-name:${BRIDGE_NAME};interface-name:${WAN_INTERFACE};interface-name:${LAN_INTERFACE}
NM_EOF
        run systemctl reload NetworkManager 2>/dev/null || \
            run systemctl restart NetworkManager 2>/dev/null || true
        log "NetworkManager configured to ignore bridge interfaces"
        # Give NM a moment to release the interfaces
        sleep 1
    fi

    # Apply netplan (non-destructive — only applies our file)
    run netplan apply 2>/dev/null || warn "netplan apply returned non-zero (bridge may already be active)"

    # netplan apply hands the bridge to systemd-networkd, which may reset
    # its state. Re-bring the bridge up to ensure it's ready for traffic.
    ip link set "$BRIDGE_NAME" up 2>/dev/null || true
    log "Persistence configuration complete — bridge will survive reboot"
fi

# ===========================================================================
# FINAL VALIDATION
# ===========================================================================
log ""
validate_bridge || true
