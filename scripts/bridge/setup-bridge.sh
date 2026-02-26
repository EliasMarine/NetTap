#!/usr/bin/env bash
# NetTap — Linux bridge setup script
# Creates a transparent Layer 2 bridge between WAN and LAN NICs
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common.sh"

# Defaults (overridden by .env or arguments)
WAN_INTERFACE="${WAN_INTERFACE:-eth0}"
LAN_INTERFACE="${LAN_INTERFACE:-eth1}"
BRIDGE_NAME="br0"

usage() {
    echo "Usage: $0 [--wan <iface>] [--lan <iface>]"
    echo ""
    echo "Creates a transparent network bridge between two interfaces."
    echo ""
    echo "Options:"
    echo "  --wan <iface>    WAN-side interface (default: eth0)"
    echo "  --lan <iface>    LAN-side interface (default: eth1)"
    echo "  -h, --help       Show this help message"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --wan) WAN_INTERFACE="$2"; shift 2 ;;
        --lan) LAN_INTERFACE="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

require_root
check_interface_exists "$WAN_INTERFACE"
check_interface_exists "$LAN_INTERFACE"

log "Creating bridge ${BRIDGE_NAME} with ${WAN_INTERFACE} (WAN) and ${LAN_INTERFACE} (LAN)"

# Create bridge if it doesn't exist
if ! ip link show "$BRIDGE_NAME" &>/dev/null; then
    ip link add name "$BRIDGE_NAME" type bridge
    log "Bridge ${BRIDGE_NAME} created"
else
    log "Bridge ${BRIDGE_NAME} already exists, reconfiguring"
fi

# Disable STP — we are a transparent inline tap, not a switch
ip link set "$BRIDGE_NAME" type bridge stp_state 0

# Add interfaces to bridge
for iface in "$WAN_INTERFACE" "$LAN_INTERFACE"; do
    ip link set "$iface" up
    ip link set "$iface" master "$BRIDGE_NAME"
    # Enable promiscuous mode for packet capture
    ip link set "$iface" promisc on
    log "Added ${iface} to ${BRIDGE_NAME} (promisc on)"
done

# Bring bridge up (no IP address — transparent L2)
ip link set "$BRIDGE_NAME" up

# Disable IPv6 on bridge to stay invisible
sysctl -q -w "net.ipv6.conf.${BRIDGE_NAME}.disable_ipv6=1"

log "Bridge ${BRIDGE_NAME} is up and forwarding traffic"
