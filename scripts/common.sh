#!/usr/bin/env bash
# NetTap — Shared shell utilities

log() {
    echo "[NetTap] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

error() {
    echo "[NetTap] ERROR: $*" >&2
    exit 1
}

require_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root"
    fi
}

check_interface_exists() {
    local iface="$1"
    if ! ip link show "$iface" &>/dev/null; then
        error "Interface ${iface} not found. Available interfaces: $(ls /sys/class/net/ | tr '\n' ' ')"
    fi
}

check_command() {
    local cmd="$1"
    if ! command -v "$cmd" &>/dev/null; then
        error "Required command '${cmd}' not found. Please install it first."
    fi
}

# Load .env file if present
load_env() {
    local env_file="${1:-$(dirname "${BASH_SOURCE[0]}")/../.env}"
    if [[ -f "$env_file" ]]; then
        set -a
        source "$env_file"
        set +a
    fi
}
