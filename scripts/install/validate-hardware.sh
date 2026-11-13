#!/usr/bin/env bash
# NetTap — Hardware validation
# Verifies that the host meets minimum requirements for running NetTap.
# Can be sourced (provides validate_hardware function) or run standalone.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../common.sh
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
MIN_RAM_MB=7500          # ~8 GB (accounts for OS reporting slightly less)
RECOMMENDED_RAM_MB=15000 # ~16 GB
# OLD CODE START — NET-177: GiB, while every size NetTap shows is decimal GB
# MIN_DISK_GB=400          # ~512 GB drive (formatted capacity)
# OLD CODE END
MIN_DISK_GB=430          # ~512 GB drive (formatted capacity); decimal GB, the old 400 GiB
MIN_NIC_COUNT=2
MIN_CPU_CORES=2
RECOMMENDED_CPU_CORES=4

# Detail lines sit under the check text: after "[ OK ] " (7 columns), or after
# the installer's "        ✓ " (10) when NETTAP_UI=fancy (NET-204).
_hw_detail_pad() {
    if [[ "$NETTAP_UI" == "fancy" ]]; then echo "${_UI_PAD}  "; else echo "       "; fi
}

# ---------------------------------------------------------------------------
# Individual checks — each returns 0 on pass, 1 on warning, 2 on hard fail.
# They print their own log/warn/error messages but do NOT call error() so the
# caller can accumulate results.
# ---------------------------------------------------------------------------

check_cpu() {
    local arch cores
    arch=$(uname -m)
    if [[ "$arch" != "x86_64" ]]; then
        status_line FAIL "Architecture: ${arch} (x86-64 required)"
        return 2
    fi

    cores=$(nproc 2>/dev/null || echo 1)
    if (( cores < MIN_CPU_CORES )); then
        status_line FAIL "CPU cores: ${cores} (minimum ${MIN_CPU_CORES})"
        return 2
    elif (( cores < RECOMMENDED_CPU_CORES )); then
        status_line WARN "CPU cores: ${cores} (${RECOMMENDED_CPU_CORES}+ recommended)"
        return 1
    fi

    local model
    model=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs) || model="unknown"
    status_line OK "CPU: ${model} (${cores} cores, ${arch})"
    return 0
}

check_ram() {
    local ram_kb ram_mb
    ram_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null) || ram_kb=0
    ram_mb=$(( ram_kb / 1024 ))

    if (( ram_mb < MIN_RAM_MB )); then
        status_line FAIL "RAM: ${ram_mb} MB (minimum 8 GB required)"
        return 2
    elif (( ram_mb < RECOMMENDED_RAM_MB )); then
        status_line WARN "RAM: ${ram_mb} MB (16 GB recommended for best performance)"
        return 1
    fi

    status_line OK "RAM: ${ram_mb} MB"
    return 0
}

check_disk() {
    # Check the root filesystem — that's where Docker stores data by default
    local disk_kb disk_gb
    disk_kb=$(df -k / | awk 'NR==2 {print $2}') || disk_kb=0
    # OLD CODE START — NET-177: GiB labelled GB, so a 1 TB drive read 931 GB
    # disk_gb=$(( disk_kb / 1024 / 1024 ))
    # OLD CODE END
    disk_gb=$(( disk_kb * 1024 / 1000000000 ))  # decimal GB, as System and Setup show

    if (( disk_gb < MIN_DISK_GB )); then
        status_line WARN "Disk: ${disk_gb} GB total (512 GB+ recommended)"
        return 1
    fi

    # Check for NVMe
    local disk_type="SATA/other"
    if ls /dev/nvme* &>/dev/null; then
        disk_type="NVMe"
    fi

    # OLD CODE: status_line OK "Disk: ${disk_gb} GB (${disk_type})" (NET-177: "total", as the warning says;
    # System shows the smaller usable size, without root-reserved blocks)
    status_line OK "Disk: ${disk_gb} GB total (${disk_type})"
    return 0
}

check_nics() {
    local nics=()
    local nic
    while IFS= read -r nic; do
        [[ -n "$nic" ]] && nics+=("$nic")
    done < <(list_physical_nics)

    if (( ${#nics[@]} < MIN_NIC_COUNT )); then
        status_line FAIL "NICs: found ${#nics[@]} physical NIC(s) (minimum ${MIN_NIC_COUNT} required)"
        if (( ${#nics[@]} > 0 )); then
            echo "$(_hw_detail_pad)Detected: ${nics[*]}"
        fi
        return 2
    fi

    status_line OK "NICs: ${#nics[@]} physical interface(s) detected"

    # Detail each NIC
    for nic in "${nics[@]}"; do
        local driver speed mac carrier_str
        driver=$(get_nic_driver "$nic")
        speed=$(get_nic_speed "$nic")
        mac=$(get_nic_mac "$nic")
        if nic_has_carrier "$nic"; then
            carrier_str="link up"
        else
            carrier_str="no link"
        fi

        local driver_note=""
        case "$driver" in
            igc|igb|ixgbe|i40e|ice|e1000e)
                driver_note=" (Intel — optimal)" ;;
            r8169|r8168|r8125)
                driver_note=" (Realtek — Intel recommended)" ;;
        esac

        echo "$(_hw_detail_pad)${nic}: ${driver}${driver_note}, ${speed}, ${mac}, ${carrier_str}"
    done
    return 0
}

check_kernel() {
    local version
    version=$(uname -r)
    status_line OK "Kernel: ${version}"

    # Verify bridge module is available
    if ! modprobe -n bridge 2>/dev/null; then
        status_line WARN "Bridge kernel module not available"
        return 1
    fi
    return 0
}

check_virtualization() {
    if command -v systemd-detect-virt &>/dev/null; then
        local virt
        virt=$(systemd-detect-virt 2>/dev/null) || virt="none"
        if [[ "$virt" != "none" ]]; then
            status_line WARN "Virtualization detected: ${virt} (performance may differ from bare metal)"
            return 1
        fi
    fi
    status_line OK "Running on bare metal"
    return 0
}

# ---------------------------------------------------------------------------
# Auto-detect NICs and suggest WAN/LAN/MGMT assignment
# ---------------------------------------------------------------------------
detect_nics() {
    local nics=()
    local nic
    while IFS= read -r nic; do
        [[ -n "$nic" ]] && nics+=("$nic")
    done < <(list_physical_nics)

    if (( ${#nics[@]} < 2 )); then
        error "Need at least 2 physical NICs for bridge. Found: ${nics[*]:-none}"
    fi

    echo ""
    echo "Detected physical NICs (ordered by PCI bus):"
    echo "---------------------------------------------"
    local idx=0
    for nic in "${nics[@]}"; do
        local driver speed carrier_str
        driver=$(get_nic_driver "$nic")
        speed=$(get_nic_speed "$nic")
        if nic_has_carrier "$nic"; then carrier_str="link up"; else carrier_str="no link"; fi
        echo "  [${idx}] ${nic} — ${driver}, ${speed}, ${carrier_str}"
        (( ++idx ))
    done

    echo ""
    echo "Suggested assignment:"
    echo "  WAN (modem side):  ${nics[0]}"
    echo "  LAN (router side): ${nics[1]}"
    if (( ${#nics[@]} >= 3 )); then
        echo "  MGMT (dashboard):  ${nics[2]}"
    fi
}

# ---------------------------------------------------------------------------
# Main validation — runs all checks, returns 0 if all pass, 1 if warnings, 2 if hard fail
# ---------------------------------------------------------------------------
validate_hardware() {
    local errors=0 warnings=0 pad=""

    # Under the installer's "Pre-flight checks" header the box is redundant (NET-204).
    if [[ "$NETTAP_UI" == "fancy" ]]; then
        pad="$_UI_PAD"
    else
        echo ""
        echo "=========================================="
        echo "  NetTap Hardware Validation"
        echo "=========================================="
        echo ""
    fi

    # Run each check and capture its exit code without triggering set -e
    local rc
    check_cpu;            rc=$?; (( rc == 2 )) && (( ++errors ));  (( rc == 1 )) && (( ++warnings ))
    check_ram;            rc=$?; (( rc == 2 )) && (( ++errors ));  (( rc == 1 )) && (( ++warnings ))
    check_disk;           rc=$?; (( rc == 2 )) && (( ++errors ));  (( rc == 1 )) && (( ++warnings ))
    check_nics;           rc=$?; (( rc == 2 )) && (( ++errors ));  (( rc == 1 )) && (( ++warnings ))
    check_kernel;         rc=$?; (( rc == 2 )) && (( ++errors ));  (( rc == 1 )) && (( ++warnings ))
    check_virtualization; rc=$?; (( rc == 2 )) && (( ++errors ));  (( rc == 1 )) && (( ++warnings ))

    if [[ "$NETTAP_UI" != "fancy" ]]; then
        echo ""
        echo "------------------------------------------"
    fi
    if (( errors > 0 )); then
        echo "${pad}${_CLR_RED}RESULT: ${errors} error(s), ${warnings} warning(s) — hardware does not meet minimum requirements${_CLR_RST}"
        echo ""
        return 2
    elif (( warnings > 0 )); then
        echo "${pad}${_CLR_YLW}RESULT: ${warnings} warning(s) — hardware meets minimum requirements with caveats${_CLR_RST}"
        echo ""
        return 1
    else
        echo "${pad}${_CLR_GRN}RESULT: All checks passed — hardware meets recommended specifications${_CLR_RST}"
        echo ""
        return 0
    fi
}

# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --detect)     detect_nics; exit 0 ;;
            -v|--verbose) NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
            --color)      NETTAP_COLOR="$2"; export NETTAP_COLOR; _setup_colors; shift 2 ;;
            -h|--help)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Validates host hardware for NetTap deployment."
                echo ""
                echo "Options:"
                echo "  --detect     Auto-detect NICs and suggest WAN/LAN assignment"
                echo "  -v, --verbose  Enable debug output"
                echo "  --color <mode>  Color mode: auto, always, never"
                echo "  -h, --help   Show this help"
                exit 0
                ;;
            *) echo "Unknown option: $1"; exit 1 ;;
        esac
    done

    validate_hardware
fi
