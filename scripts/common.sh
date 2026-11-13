#!/usr/bin/env bash
# NetTap — Shared shell utilities
# Sourced by all NetTap scripts for logging, validation, and system checks.

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
NETTAP_DRY_RUN="${NETTAP_DRY_RUN:-false}"
NETTAP_VERBOSE="${NETTAP_VERBOSE:-false}"
NETTAP_COLOR="${NETTAP_COLOR:-auto}"   # auto | always | never
NETTAP_LOCK_FILE="/var/run/nettap.lock"

# ---------------------------------------------------------------------------
# Color support
# ---------------------------------------------------------------------------
_setup_colors() {
    if [[ "$NETTAP_COLOR" == "never" ]]; then
        _CLR_RED="" _CLR_YLW="" _CLR_GRN="" _CLR_CYN="" _CLR_RST=""
    elif [[ "$NETTAP_COLOR" == "always" ]] || [[ -t 1 ]]; then
        _CLR_RED=$'\033[0;31m' _CLR_YLW=$'\033[0;33m'
        _CLR_GRN=$'\033[0;32m' _CLR_CYN=$'\033[0;36m'
        _CLR_RST=$'\033[0m'
    else
        _CLR_RED="" _CLR_YLW="" _CLR_GRN="" _CLR_CYN="" _CLR_RST=""
    fi
}
_setup_colors

# ---------------------------------------------------------------------------
# Installer layout (NET-204)
# ---------------------------------------------------------------------------
# install.sh sets NETTAP_UI=fancy on an interactive terminal (scripts/install/ui.sh)
# and exports it, so the scripts it runs indent their lines under its step
# headers. "plain" (the default) keeps the timestamped format below.
NETTAP_UI="${NETTAP_UI:-plain}"
_UI_PAD="        "
# The Linux text console font has no check mark or ballot X.
if [[ "${TERM:-}" == "linux" ]]; then
    _UI_G_OK="+" _UI_G_FAIL="x"
else
    _UI_G_OK="✓" _UI_G_FAIL="✗"
fi

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_ts() { date '+%Y-%m-%d %H:%M:%S'; }

log() {
    if [[ "$NETTAP_UI" == "fancy" ]]; then
        # Not "${*:+...}": bash 3.2 prints a stray \177 for an empty $* there.
        if [[ -n "$*" ]]; then echo "${_UI_PAD}$*"; else echo; fi
        return 0
    fi
    echo "${_CLR_GRN}[NetTap]${_CLR_RST} $(_ts) $*"
}

warn() {
    if [[ "$NETTAP_UI" == "fancy" ]]; then
        echo "${_UI_PAD}${_CLR_YLW}!${_CLR_RST} $*" >&2
        return 0
    fi
    echo "${_CLR_YLW}[NetTap] WARN:${_CLR_RST} $(_ts) $*" >&2
}

error() {
    if [[ "$NETTAP_UI" == "fancy" ]]; then
        echo "${_UI_PAD}${_CLR_RED}${_UI_G_FAIL}${_CLR_RST} $*" >&2
        exit 1
    fi
    echo "${_CLR_RED}[NetTap] ERROR:${_CLR_RST} $(_ts) $*" >&2
    exit 1
}

debug() {
    if [[ "$NETTAP_VERBOSE" == "true" ]]; then
        if [[ "$NETTAP_UI" == "fancy" ]]; then
            echo "${_UI_PAD}${_CLR_CYN}debug${_CLR_RST} $*" >&2
            return 0
        fi
        echo "${_CLR_CYN}[NetTap] DEBUG:${_CLR_RST} $(_ts) $*" >&2
    fi
}

# One check result on stdout. Always returns 0: callers keep the outcome in
# their own counters and return codes.
# Usage: status_line OK|WARN|FAIL|SKIP "message"
status_line() {
    local tag="$1" msg="$2" colour glyph label
    case "$tag" in
        OK)   colour="$_CLR_GRN" glyph="$_UI_G_OK"   label="[ OK ]" ;;
        WARN) colour="$_CLR_YLW" glyph="!"           label="[WARN]" ;;
        FAIL) colour="$_CLR_RED" glyph="$_UI_G_FAIL" label="[FAIL]" ;;
        SKIP) colour="$_CLR_YLW" glyph="-"           label="[SKIP]" ;;
        *)    colour=""          glyph="?"           label="[${tag}]" ;;
    esac
    if [[ "$NETTAP_UI" == "fancy" ]]; then
        printf '%s%s%s%s %s\n' "$_UI_PAD" "$colour" "$glyph" "$_CLR_RST" "$msg"
    else
        printf '%s%s%s %s\n' "$colour" "$label" "$_CLR_RST" "$msg"
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Dry-run helpers — wrap destructive commands so --dry-run logs them instead
# ---------------------------------------------------------------------------
# Usage: run ip link add name br0 type bridge
run() {
    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] $*"
        return 0
    fi
    debug "exec: $*"
    "$@"
}

# Write stdin to a file; --dry-run logs the path and writes nothing (NET-211 #8).
# Not `run tee "$f" >/dev/null`: that also sends the dry-run line to /dev/null.
# Usage: write_file /etc/foo.conf <<'EOF' … EOF   (or <<< "$text"; never a pipe)
write_file() {
    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] write $1"
        return 0
    fi
    cat > "$1"
}

# ---------------------------------------------------------------------------
# Cleanup / signal handling
# ---------------------------------------------------------------------------
_CLEANUP_ACTIONS=()

# Register a command to run on EXIT/ERR (LIFO order).
# Usage: push_cleanup "ip link del br0"
push_cleanup() {
    _CLEANUP_ACTIONS+=("$1")
}

_run_cleanup() {
    local exit_code=$?
    for ((i=${#_CLEANUP_ACTIONS[@]}-1; i>=0; i--)); do
        eval "${_CLEANUP_ACTIONS[$i]}" 2>/dev/null || true
    done
    return $exit_code
}

# Call once in your script to enable cleanup-on-error.
enable_cleanup_trap() {
    trap _run_cleanup ERR
}

# Clear the trap after successful completion so cleanup doesn't undo work.
disable_cleanup_trap() {
    trap - ERR
    _CLEANUP_ACTIONS=()
}

# ---------------------------------------------------------------------------
# Lock file — prevent concurrent script runs
# ---------------------------------------------------------------------------
acquire_lock() {
    local lock="${1:-$NETTAP_LOCK_FILE}"
    if [[ -f "$lock" ]]; then
        local pid
        pid=$(<"$lock")
        if kill -0 "$pid" 2>/dev/null; then
            error "Another NetTap process is running (PID ${pid}). Remove ${lock} if stale."
        else
            warn "Stale lock file found (PID ${pid} not running). Removing."
            rm -f "$lock"
        fi
    fi
    echo $$ > "$lock"
    # Remove lock on exit regardless of success/failure
    # Intentional: expand $lock now to capture current lock file path
    # shellcheck disable=SC2064
    trap "rm -f '$lock'" EXIT
}

release_lock() {
    local lock="${1:-$NETTAP_LOCK_FILE}"
    rm -f "$lock"
}

# ---------------------------------------------------------------------------
# Retry — run a command up to N times with a delay between attempts
# ---------------------------------------------------------------------------
# Usage: retry 5 2 curl -sf http://localhost:9200/_cluster/health
#        (5 attempts, 2 second delay)
retry() {
    local max_attempts="$1" delay="$2"
    shift 2
    local attempt=1
    while (( attempt <= max_attempts )); do
        if "$@"; then
            return 0
        fi
        if (( attempt == max_attempts )); then
            warn "Command failed after ${max_attempts} attempts: $*"
            return 1
        fi
        debug "Attempt ${attempt}/${max_attempts} failed, retrying in ${delay}s..."
        sleep "$delay"
        (( attempt++ ))
    done
}

# ---------------------------------------------------------------------------
# System checks
# ---------------------------------------------------------------------------
require_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root"
    fi
}

check_ubuntu() {
    if [[ ! -f /etc/os-release ]]; then
        error "Cannot detect OS — /etc/os-release not found"
    fi
    if ! grep -qi "ubuntu" /etc/os-release; then
        # shellcheck disable=SC1091,SC2153
        error "NetTap requires Ubuntu Server (detected: $(. /etc/os-release && echo "$NAME"))"
    fi
    local version
    # shellcheck disable=SC1091
    version=$(. /etc/os-release && echo "$VERSION_ID")
    debug "Ubuntu version: ${version}"
    case "$version" in
        22.04|24.04) : ;;  # supported
        *)
            warn "Ubuntu ${version} has not been tested. Supported: 22.04, 24.04."
            ;;
    esac
}

check_arch() {
    local arch
    arch=$(uname -m)
    if [[ "$arch" != "x86_64" ]]; then
        error "NetTap requires x86-64 architecture (detected: ${arch})"
    fi
    debug "Architecture: ${arch}"
}

check_interface_exists() {
    local iface="$1"
    if ! ip link show "$iface" &>/dev/null; then
        error "Interface ${iface} not found. Available interfaces: $(find /sys/class/net/ -maxdepth 1 -printf '%f ' 2>/dev/null)"
    fi
}

check_command() {
    local cmd="$1"
    if ! command -v "$cmd" &>/dev/null; then
        error "Required command '${cmd}' not found. Please install it first."
    fi
}

# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------
# Load .env file if present
load_env() {
    local env_file="${1:-$(dirname "${BASH_SOURCE[0]}")/../.env}"
    if [[ -f "$env_file" ]]; then
        debug "Loading env from ${env_file}"
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
    else
        debug "No .env file at ${env_file}, using defaults"
    fi
}

# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

# List physical NICs (excludes loopback, docker, bridge, veth, etc.)
# Outputs one interface name per line.
list_physical_nics() {
    local iface name
    for iface in /sys/class/net/*; do
        name=$(basename "$iface")
        # Skip virtual interfaces
        [[ "$name" =~ ^(lo|docker|br|veth|virbr|vnet|tun|tap|wg) ]] && continue
        # Only include devices with a PCI/USB backing device
        [[ -L "${iface}/device" ]] || continue
        echo "$name"
    done
}

# Get the driver name for a NIC (e.g., "igc", "r8169")
get_nic_driver() {
    local iface="$1"
    local driver_path="/sys/class/net/${iface}/device/driver"
    if [[ -L "$driver_path" ]]; then
        basename "$(readlink -f "$driver_path")"
    else
        echo "unknown"
    fi
}

# Check if a NIC has a cable connected (carrier up)
nic_has_carrier() {
    local iface="$1"
    [[ "$(cat "/sys/class/net/${iface}/carrier" 2>/dev/null)" == "1" ]]
}

# Get NIC speed in Mb/s, or "unknown" if not available
get_nic_speed() {
    local iface="$1"
    local speed
    speed=$(cat "/sys/class/net/${iface}/speed" 2>/dev/null) || true
    if [[ -n "$speed" && "$speed" != "-1" ]]; then
        echo "${speed}Mb/s"
    else
        echo "unknown"
    fi
}

# Get NIC MAC address
get_nic_mac() {
    local iface="$1"
    cat "/sys/class/net/${iface}/address" 2>/dev/null || echo "unknown"
}

# ---------------------------------------------------------------------------
# First-run setup code (A13, NET-229)
# ---------------------------------------------------------------------------
# shellcheck disable=SC2034  # used by install/ui.sh and install/activate-bridge.sh
NETTAP_SETUP_CODE_CMD="sudo docker exec nettap-web cat /var/lib/nettap-web/setup-code"

# Print the one-time code the setup wizard asks for. nettap-web writes it when it starts with no
# admin account; once an admin exists there is none and this prints nothing. Waits up to 60 s for
# the container to start. Needs root (docker).
nettap_setup_code() {
    local i
    for (( i = 0; i < 30; i++ )); do
        if docker exec nettap-web cat /var/lib/nettap-web/setup-code 2>/dev/null; then return 0; fi
        if docker exec nettap-web test -e /var/lib/nettap-web/users.json 2>/dev/null; then return 0; fi
        sleep 2
    done
}
