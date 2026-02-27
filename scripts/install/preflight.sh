#!/usr/bin/env bash
# ==========================================================================
# NetTap — Pre-install NIC discovery and assignment
# ==========================================================================
# Interactive helper that discovers physical NICs, lets the user assign
# them to MGMT / WAN / LAN roles, and writes the result to .env.
# Designed to run *before* the main install so the user still has internet.
#
# Usage:
#   sudo scripts/install/preflight.sh [OPTIONS]
#
# Options:
#   --env-file PATH       Path to .env file (default: <project>/.env)
#   --non-interactive     Auto-assign NICs without prompts
#   --reconfigure-nics    Force re-run even if .env already has NIC values
#   --dry-run             Log actions without writing
#   -v, --verbose         Enable debug output
#   -h, --help            Show help
# ==========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=../common.sh
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults & flags
# ---------------------------------------------------------------------------
ENV_FILE="${PROJECT_ROOT}/.env"
NON_INTERACTIVE="false"
RECONFIGURE="false"
BLINK_DURATION=10

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: sudo $0 [OPTIONS]

Discovers physical NICs and assigns them to MGMT, WAN, and LAN roles.
Writes assignments to .env for use by install.sh and activate-bridge.sh.

Options:
  --env-file PATH       Path to .env file (default: <project>/.env)
  --non-interactive     Auto-assign NICs without prompts
  --reconfigure-nics    Force re-run even if .env already has NIC values
  --dry-run             Log actions without writing
  -v, --verbose         Enable debug output
  -h, --help            Show this help
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-file)           ENV_FILE="$2"; shift 2 ;;
        --non-interactive)    NON_INTERACTIVE="true"; shift ;;
        --reconfigure-nics)   RECONFIGURE="true"; shift ;;
        --dry-run)            NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
        -v|--verbose)         NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
        -h|--help)            usage ;;
        *)                    echo "Unknown option: $1"; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# NIC discovery
# ---------------------------------------------------------------------------

# Populate NIC_NAMES, NIC_DRIVERS, NIC_SPEEDS, NIC_MACS, NIC_CARRIERS arrays.
discover_nics() {
    NIC_NAMES=()
    NIC_DRIVERS=()
    NIC_SPEEDS=()
    NIC_MACS=()
    NIC_CARRIERS=()

    local nic
    while IFS= read -r nic; do
        [[ -z "$nic" ]] && continue
        NIC_NAMES+=("$nic")
        NIC_DRIVERS+=("$(get_nic_driver "$nic")")
        NIC_SPEEDS+=("$(get_nic_speed "$nic")")
        NIC_MACS+=("$(get_nic_mac "$nic")")
        if nic_has_carrier "$nic"; then
            NIC_CARRIERS+=("link up")
        else
            NIC_CARRIERS+=("no link")
        fi
    done < <(list_physical_nics | sort)

    debug "Discovered ${#NIC_NAMES[@]} physical NIC(s)"
}

# Find the NIC that currently has the default route (internet access).
# Sets INTERNET_NIC and INTERNET_NIC_INDEX (1-based).
detect_internet_nic() {
    INTERNET_NIC=""
    INTERNET_NIC_INDEX=""

    local iface
    iface=$(ip route show default 2>/dev/null \
        | head -1 \
        | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}') || true

    if [[ -z "$iface" ]]; then
        debug "No default route found"
        return 0
    fi

    INTERNET_NIC="$iface"
    debug "Internet NIC detected: ${INTERNET_NIC}"

    # Find index in NIC_NAMES
    local i
    for i in "${!NIC_NAMES[@]}"; do
        if [[ "${NIC_NAMES[$i]}" == "$INTERNET_NIC" ]]; then
            INTERNET_NIC_INDEX=$(( i + 1 ))
            break
        fi
    done
}

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

print_nic_table() {
    echo ""
    echo "  Detected ${#NIC_NAMES[@]} physical network interface(s):"
    echo ""
    printf "    %-5s %-15s %-12s %-12s %-20s %s\n" \
        "#" "Interface" "Driver" "Speed" "MAC" "Link"
    printf "    %-5s %-15s %-12s %-12s %-20s %s\n" \
        "---" "-----------" "---------" "----------" "------------------" "--------"

    local i
    for i in "${!NIC_NAMES[@]}"; do
        local num=$(( i + 1 ))
        local marker=""
        if [[ -n "$INTERNET_NIC_INDEX" && "$num" -eq "$INTERNET_NIC_INDEX" ]]; then
            marker="  <-- current internet"
        fi
        printf "    %-5s %-15s %-12s %-12s %-20s %s%s\n" \
            "$num" "${NIC_NAMES[$i]}" "${NIC_DRIVERS[$i]}" \
            "${NIC_SPEEDS[$i]}" "${NIC_MACS[$i]}" "${NIC_CARRIERS[$i]}" "$marker"
    done
    echo ""
}

# Print the rewiring guide with an ASCII topology diagram.
print_rewiring_guide() {
    local wan="$1" lan="$2" mgmt="${3:-}"

    echo ""
    echo "  =========================================="
    echo "    NIC Roles Assigned — Wiring Reference"
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
}

# ---------------------------------------------------------------------------
# LED blink
# ---------------------------------------------------------------------------

blink_nic() {
    local iface="$1"
    local duration="${2:-$BLINK_DURATION}"

    if ! command -v ethtool &>/dev/null; then
        warn "ethtool not installed — cannot blink LEDs. Skipping."
        return 0
    fi

    log "Blinking ${iface} for ${duration} seconds... look for the flashing port."
    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] ethtool -p ${iface} ${duration}"
        return 0
    fi

    # ethtool -p blocks for the duration; run in background so the user
    # sees the prompt return after the blink finishes.
    ethtool -p "$iface" "$duration" 2>/dev/null || \
        warn "LED blink failed for ${iface} (device may not support it)"
}

# ---------------------------------------------------------------------------
# Interactive NIC assignment
# ---------------------------------------------------------------------------

# Read a NIC number from the user. Validates range 1..N.
# $1 = prompt, $2 = count, $3 = variable name to assign
_read_nic_choice() {
    local prompt="$1" count="$2" varname="$3"
    local choice
    while true; do
        read -rp "  ${prompt}: " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= count )); then
            eval "${varname}=${choice}"
            return 0
        fi
        echo "  Invalid choice. Enter a number between 1 and ${count}."
    done
}

assign_nics_interactive() {
    local count=${#NIC_NAMES[@]}

    # --- Offer LED blink ---
    echo ""
    read -rp "  Blink a NIC's LEDs to identify its port? (y/n): " do_blink
    if [[ "$do_blink" =~ ^[Yy] ]]; then
        local blink_num
        _read_nic_choice "Enter NIC number (1-${count})" "$count" blink_num
        blink_nic "${NIC_NAMES[$(( blink_num - 1 ))]}" "$BLINK_DURATION"
    fi

    # --- Assign MGMT ---
    local mgmt_num wan_num lan_num

    if (( count >= 3 )); then
        echo ""
        _read_nic_choice "Select MANAGEMENT NIC (dashboard access) [1-${count}]" "$count" mgmt_num

        # --- Assign WAN ---
        while true; do
            _read_nic_choice "Select WAN NIC (ISP modem side) [1-${count}]" "$count" wan_num
            if [[ "$wan_num" == "$mgmt_num" ]]; then
                echo "  WAN cannot be the same as MGMT. Pick a different NIC."
                continue
            fi
            break
        done

        # --- Assign LAN ---
        while true; do
            _read_nic_choice "Select LAN NIC (router side) [1-${count}]" "$count" lan_num
            if [[ "$lan_num" == "$mgmt_num" || "$lan_num" == "$wan_num" ]]; then
                echo "  LAN cannot be the same as MGMT or WAN. Pick a different NIC."
                continue
            fi
            break
        done

        ASSIGNED_MGMT="${NIC_NAMES[$(( mgmt_num - 1 ))]}"
        ASSIGNED_WAN="${NIC_NAMES[$(( wan_num - 1 ))]}"
        ASSIGNED_LAN="${NIC_NAMES[$(( lan_num - 1 ))]}"
    elif (( count == 2 )); then
        warn "Only 2 NICs detected — no dedicated management NIC available."
        warn "You will need Wi-Fi or a VLAN for dashboard access."
        ASSIGNED_MGMT=""

        _read_nic_choice "Select WAN NIC (ISP modem side) [1-${count}]" "$count" wan_num
        lan_num=$(( wan_num == 1 ? 2 : 1 ))

        ASSIGNED_WAN="${NIC_NAMES[$(( wan_num - 1 ))]}"
        ASSIGNED_LAN="${NIC_NAMES[$(( lan_num - 1 ))]}"
        echo "  LAN automatically assigned to: ${ASSIGNED_LAN}"
    fi

    # Warn if the internet NIC is being used for the bridge
    if [[ -n "$INTERNET_NIC" ]]; then
        if [[ "$INTERNET_NIC" == "$ASSIGNED_WAN" || "$INTERNET_NIC" == "$ASSIGNED_LAN" ]]; then
            echo ""
            warn "Your current internet NIC (${INTERNET_NIC}) is assigned to the bridge."
            warn "Internet will be unavailable until cables are rewired and bridge is activated."
            echo ""
        fi
    fi
}

# ---------------------------------------------------------------------------
# Non-interactive NIC assignment
# ---------------------------------------------------------------------------

assign_nics_auto() {
    local count=${#NIC_NAMES[@]}

    # Management = internet NIC (the one we need to keep for now)
    if [[ -n "$INTERNET_NIC" ]]; then
        ASSIGNED_MGMT="$INTERNET_NIC"
    elif (( count >= 3 )); then
        # Fallback: first NIC as management
        ASSIGNED_MGMT="${NIC_NAMES[0]}"
    else
        ASSIGNED_MGMT=""
    fi

    # WAN + LAN = first two NICs that aren't MGMT
    ASSIGNED_WAN=""
    ASSIGNED_LAN=""
    local nic
    for nic in "${NIC_NAMES[@]}"; do
        [[ "$nic" == "$ASSIGNED_MGMT" ]] && continue
        if [[ -z "$ASSIGNED_WAN" ]]; then
            ASSIGNED_WAN="$nic"
        elif [[ -z "$ASSIGNED_LAN" ]]; then
            ASSIGNED_LAN="$nic"
            break
        fi
    done

    log "Auto-assigned NICs: MGMT=${ASSIGNED_MGMT:-none} WAN=${ASSIGNED_WAN} LAN=${ASSIGNED_LAN}"
}

# ---------------------------------------------------------------------------
# Write .env
# ---------------------------------------------------------------------------

# Update or append a key=value in the env file.
# Preserves existing non-NIC values.
_set_env_value() {
    local key="$1" value="$2" file="$3"

    if [[ ! -f "$file" ]]; then
        echo "${key}=${value}" >> "$file"
        return
    fi

    if grep -q "^${key}=" "$file" 2>/dev/null; then
        # Replace existing line
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
        rm -f "${file}.bak"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

write_env_assignments() {
    local wan="$1" lan="$2" mgmt="${3:-}"

    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] Would write to ${ENV_FILE}:"
        log "  WAN_INTERFACE=${wan}"
        log "  LAN_INTERFACE=${lan}"
        [[ -n "$mgmt" ]] && log "  MGMT_INTERFACE=${mgmt}"
        return 0
    fi

    # Ensure the .env file exists (copy from example if needed)
    if [[ ! -f "$ENV_FILE" ]]; then
        local example="${PROJECT_ROOT}/.env.example"
        if [[ -f "$example" ]]; then
            cp "$example" "$ENV_FILE"
            debug "Created .env from .env.example"
        else
            touch "$ENV_FILE"
            debug "Created empty .env"
        fi
    fi

    _set_env_value "WAN_INTERFACE" "$wan" "$ENV_FILE"
    _set_env_value "LAN_INTERFACE" "$lan" "$ENV_FILE"
    if [[ -n "$mgmt" ]]; then
        _set_env_value "MGMT_INTERFACE" "$mgmt" "$ENV_FILE"
    fi

    log "Written to ${ENV_FILE}: MGMT=${mgmt:-none}, WAN=${wan}, LAN=${lan}"
}

# ---------------------------------------------------------------------------
# Check if .env already has NIC assignments
# ---------------------------------------------------------------------------
env_has_nic_assignments() {
    [[ -f "$ENV_FILE" ]] || return 1
    grep -q "^WAN_INTERFACE=" "$ENV_FILE" 2>/dev/null && \
    grep -q "^LAN_INTERFACE=" "$ENV_FILE" 2>/dev/null
}

# ===========================================================================
# MAIN
# ===========================================================================
main() {
    echo ""
    echo "  =========================================="
    echo "    NetTap Pre-Install NIC Discovery"
    echo "  =========================================="

    # Skip if .env already has NIC values (unless --reconfigure-nics)
    if [[ "$RECONFIGURE" != "true" ]] && env_has_nic_assignments; then
        log "NIC assignments already present in ${ENV_FILE}."
        log "Use --reconfigure-nics to re-run NIC discovery."
        return 0
    fi

    # Discover NICs
    discover_nics

    if (( ${#NIC_NAMES[@]} < 2 )); then
        error "NetTap requires at least 2 physical NICs. Found: ${#NIC_NAMES[@]}. Please add more network adapters."
    fi

    detect_internet_nic
    print_nic_table

    # Assign NICs
    ASSIGNED_MGMT=""
    ASSIGNED_WAN=""
    ASSIGNED_LAN=""

    if [[ "$NON_INTERACTIVE" == "true" ]]; then
        assign_nics_auto
    else
        assign_nics_interactive
    fi

    # Validate we have at least WAN + LAN
    if [[ -z "$ASSIGNED_WAN" || -z "$ASSIGNED_LAN" ]]; then
        error "Could not assign WAN and LAN NICs. At least 2 physical NICs are required."
    fi

    # Reject duplicate assignments
    if [[ "$ASSIGNED_WAN" == "$ASSIGNED_LAN" ]]; then
        error "WAN and LAN cannot be the same NIC (${ASSIGNED_WAN})"
    fi
    if [[ -n "$ASSIGNED_MGMT" ]]; then
        if [[ "$ASSIGNED_MGMT" == "$ASSIGNED_WAN" || "$ASSIGNED_MGMT" == "$ASSIGNED_LAN" ]]; then
            error "MGMT NIC cannot overlap with WAN or LAN"
        fi
    fi

    # Write to .env
    write_env_assignments "$ASSIGNED_WAN" "$ASSIGNED_LAN" "$ASSIGNED_MGMT"

    # Print rewiring guide
    print_rewiring_guide "$ASSIGNED_WAN" "$ASSIGNED_LAN" "$ASSIGNED_MGMT"
}

main
