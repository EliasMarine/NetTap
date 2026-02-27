#!/usr/bin/env bash
# ==========================================================================
# NetTap — Post-rewire bridge activation
# ==========================================================================
# Run this after physically rewiring cables. Validates carrier status on
# WAN/LAN NICs, activates the bridge via setup-bridge.sh, and starts
# Docker services.
#
# Usage:
#   sudo scripts/install/activate-bridge.sh [OPTIONS]
#
# Options:
#   --force            Skip cable carrier validation
#   --skip-services    Activate bridge but don't start Docker services
#   --dry-run          Log actions without executing
#   -v, --verbose      Enable debug output
#   -h, --help         Show help
# ==========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=../common.sh
source "${SCRIPT_DIR}/../common.sh"

# ---------------------------------------------------------------------------
# Defaults & flags
# ---------------------------------------------------------------------------
FORCE="false"
SKIP_SERVICES="false"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.yml"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: sudo $0 [OPTIONS]

Activates the NetTap network bridge and starts services.
Run this after physically rewiring cables per the install instructions.

Prerequisites:
  - NIC assignments in .env (WAN_INTERFACE, LAN_INTERFACE)
  - Cables plugged into WAN and LAN ports

Options:
  --force            Skip cable carrier validation
  --skip-services    Activate bridge only, don't start Docker services
  --dry-run          Log actions without executing
  -v, --verbose      Enable debug output
  -h, --help         Show this help
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)           FORCE="true"; shift ;;
        --skip-services)   SKIP_SERVICES="true"; shift ;;
        --dry-run)         NETTAP_DRY_RUN="true"; shift ;;
        -v|--verbose)      NETTAP_VERBOSE="true"; shift ;;
        -h|--help)         usage ;;
        *)                 echo "Unknown option: $1"; usage ;;
    esac
done

require_root

# ---------------------------------------------------------------------------
# Load .env and validate NIC assignments exist
# ---------------------------------------------------------------------------
load_env "${PROJECT_ROOT}/.env"

if [[ -z "${WAN_INTERFACE:-}" || -z "${LAN_INTERFACE:-}" ]]; then
    error "NIC assignments not found in .env (WAN_INTERFACE, LAN_INTERFACE). Run preflight.sh first."
fi

log "NIC assignments loaded:"
log "  WAN:  ${WAN_INTERFACE}"
log "  LAN:  ${LAN_INTERFACE}"
[[ -n "${MGMT_INTERFACE:-}" ]] && log "  MGMT: ${MGMT_INTERFACE}"

# ---------------------------------------------------------------------------
# Validate cables are plugged in (carrier detection)
# ---------------------------------------------------------------------------
validate_cables() {
    local failed=0

    for role_iface in "WAN:${WAN_INTERFACE}" "LAN:${LAN_INTERFACE}"; do
        local role="${role_iface%%:*}"
        local iface="${role_iface##*:}"

        check_interface_exists "$iface"

        if nic_has_carrier "$iface"; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${role} (${iface}): cable detected"
        else
            echo "${_CLR_RED}[FAIL]${_CLR_RST} ${role} (${iface}): no cable detected"
            (( failed++ ))
        fi
    done

    # MGMT check is informational (not fatal)
    if [[ -n "${MGMT_INTERFACE:-}" ]]; then
        if nic_has_carrier "$MGMT_INTERFACE"; then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} MGMT (${MGMT_INTERFACE}): cable detected"
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} MGMT (${MGMT_INTERFACE}): no cable (dashboard may be unreachable)"
        fi
    fi

    if (( failed > 0 )); then
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Activate bridge
# ---------------------------------------------------------------------------
activate_bridge() {
    log "Activating bridge..."

    local bridge_args=()
    bridge_args+=(--wan "$WAN_INTERFACE")
    bridge_args+=(--lan "$LAN_INTERFACE")

    if [[ -n "${MGMT_INTERFACE:-}" ]]; then
        bridge_args+=(--mgmt "$MGMT_INTERFACE")
    fi

    bridge_args+=(--persist)

    if [[ "$NETTAP_VERBOSE" == "true" ]]; then
        bridge_args+=(-v)
    fi

    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        bridge_args+=(--dry-run)
    fi

    "${SCRIPT_DIR}/../bridge/setup-bridge.sh" "${bridge_args[@]}"
}

# ---------------------------------------------------------------------------
# Start services
# ---------------------------------------------------------------------------
start_services() {
    log "Starting NetTap services..."

    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        log "[DRY-RUN] docker compose -f ${COMPOSE_FILE} up -d"
        return 0
    fi

    docker compose -f "$COMPOSE_FILE" up -d

    log "Waiting for OpenSearch to become healthy..."
    if retry 30 10 curl -skf "https://localhost:9200/_cluster/health" > /dev/null 2>&1; then
        log "OpenSearch is healthy"
    else
        warn "OpenSearch did not become healthy within 5 minutes."
        warn "It may still be starting. Check with: curl -sk https://localhost:9200/_cluster/health"
    fi
}

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
verify() {
    echo ""
    echo "  =========================================="
    echo "    Post-Activation Verification"
    echo "  =========================================="
    echo ""

    local ok=0 fail=0

    # Bridge validation
    if "${SCRIPT_DIR}/../bridge/setup-bridge.sh" --validate-only 2>/dev/null; then
        (( ok++ ))
    else
        echo "${_CLR_YLW}[WARN]${_CLR_RST} Bridge validation reported issues (see above)"
        (( fail++ ))
    fi

    # Container count (only if services were started)
    if [[ "$SKIP_SERVICES" != "true" && "$NETTAP_DRY_RUN" != "true" ]]; then
        local running
        running=$(docker compose -f "$COMPOSE_FILE" ps -q 2>/dev/null | wc -l) || running=0
        if (( running > 0 )); then
            echo "${_CLR_GRN}[ OK ]${_CLR_RST} ${running} container(s) running"
            (( ok++ ))
        else
            echo "${_CLR_YLW}[WARN]${_CLR_RST} No containers detected yet"
            (( fail++ ))
        fi
    fi

    echo ""
    if (( fail == 0 )); then
        echo "${_CLR_GRN}  NetTap is now capturing traffic!${_CLR_RST}"
    else
        echo "${_CLR_YLW}  Activation complete with warnings. Review output above.${_CLR_RST}"
    fi
    echo "  Dashboard: https://${NETTAP_HOSTNAME:-nettap.local}:${DASHBOARD_PORT:-443}"
    echo ""
}

# ===========================================================================
# MAIN
# ===========================================================================
main() {
    # Cable validation
    if [[ "$FORCE" != "true" ]]; then
        if ! validate_cables; then
            echo ""
            error "Cable check failed. Plug in all cables and retry, or use --force to skip this check."
        fi
    else
        log "Skipping cable carrier validation (--force)"
    fi

    # Activate bridge
    activate_bridge
    log "Bridge activated."

    # Start services
    if [[ "$SKIP_SERVICES" != "true" ]]; then
        start_services
    else
        log "Skipping service startup (--skip-services)"
    fi

    # Verify
    verify
}

main
