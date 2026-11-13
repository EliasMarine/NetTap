#!/usr/bin/env bash
# ==========================================================================
# NetTap — Uninstall (NET-211 #11)
# ==========================================================================
# Stops NetTap and removes what it put outside this folder: its systemd units,
# its netplan, sysctl and NetworkManager files, and its change to
# /etc/docker/daemon.json (only while that file is exactly as NetTap left it).
#
# It never runs netplan apply, deletes br0 or flushes iptables, any of which
# can cut the SSH session: the network changes take effect at the next reboot.
#
# Usage:
#   sudo ./scripts/install/uninstall.sh [OPTIONS]
#
# Options:
#   --dry-run            Show what would go and change nothing (no root needed)
#   --yes                Don't ask before removing (--purge-data still asks)
#   --purge-data         Also erase all captured data: NetTap's Docker volumes and /etc/nettap
#   -v, --verbose        Enable debug output
#   -h, --help           Show help
# ==========================================================================
# Not -e: one failed step mustn't leave the rest undone. Failures are counted; any one means exit 1.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=../common.sh
source "${SCRIPT_DIR}/../common.sh"

# Test seam: tests point every system path at a temp dir.
ROOT="${UNINSTALL_ROOT:-}"
COMPOSE_FILE="${PROJECT_ROOT}/docker/docker-compose.yml"
SYSTEMD_DIR="${ROOT}/etc/systemd/system"
BRIDGE_NETPLAN="${ROOT}/etc/netplan/10-nettap-bridge.yaml"
DHCP_NETPLAN="${ROOT}/etc/netplan/90-nettap-dhcp-gateway.yaml"
DAEMON_JSON="${ROOT}/etc/docker/daemon.json"
SETTINGS_DIR="${ROOT}/etc/nettap"
DHCP_PREFLIGHT_URL="http://127.0.0.1:8880/api/capture/dhcp/preflight"

# Everything NetTap's installer, bridge scripts and daemon write. An explicit list: the one glob is
# NetTap's own mirror prefix.
UNITS=(nettap.service nettap-bridge.service nettap-bridge-promisc.service
    nettap-mirror.service nettap-dhcp-gateway.service nettap-bypass.service)
FILES=(
    /etc/netplan/10-nettap-bridge.yaml
    "/etc/netplan/10-nettap-mirror-*.yaml"
    /etc/netplan/90-nettap-dhcp-gateway.yaml
    /etc/sysctl.d/99-nettap.conf
    /etc/sysctl.d/99-nettap-bridge.conf
    /etc/sysctl.d/99-nettap-dhcp-gateway.conf
    /etc/sysctl.d/99-nettap-bridge-hardening.conf
    /etc/modules-load.d/nettap-br-netfilter.conf
    /etc/NetworkManager/conf.d/99-nettap-unmanaged.conf
    /etc/systemd/network/10-nettap-bridge.network
)

ASSUME_YES="false"
PURGE="false"
FAILURES=0
# Expanded as ${a[@]+"${a[@]}"}: bash before 4.4 calls an empty array unbound under set -u
PRESENT_UNITS=()
PRESENT_FILES=()
DAEMON_JSON_ACTION=""
BRIDGE_MODE="false"

usage() {
    cat <<EOF
Usage: sudo $0 [OPTIONS]

Stops NetTap and removes its system files. Reboot afterwards to finish.

Options:
  --dry-run            Show what would go and change nothing (no root needed)
  --yes                Don't ask before removing (--purge-data still asks)
  --purge-data         Also erase all captured data: NetTap's Docker volumes and /etc/nettap
  -v, --verbose        Enable debug output
  -h, --help           Show this help
EOF
    exit 0
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)    NETTAP_DRY_RUN="true"; export NETTAP_DRY_RUN; shift ;;
            --yes)        ASSUME_YES="true"; shift ;;
            --purge-data) PURGE="true"; shift ;;
            -v|--verbose) NETTAP_VERBOSE="true"; export NETTAP_VERBOSE; shift ;;
            -h|--help)    usage ;;
            *)            error "Unknown option: $1 (see --help)" ;;
        esac
    done
}

fail() { FAILURES=$((FAILURES + 1)); }

# Shown without the test prefix
show_path() { echo "${1#"$ROOT"}"; }

find_present() {
    local unit pattern f
    for unit in "${UNITS[@]}"; do
        if [[ -e "${SYSTEMD_DIR}/${unit}" ]] || compgen -G "${SYSTEMD_DIR}/*.wants/${unit}" >/dev/null; then
            PRESENT_UNITS+=("$unit")
        fi
    done
    for pattern in "${FILES[@]}"; do
        for f in "${ROOT}"${pattern}; do
            [[ -e "$f" || -L "$f" ]] && PRESENT_FILES+=("$f")
        done
    done
    DAEMON_JSON_ACTION="$(daemon_json_action)"
    if [[ -e "$BRIDGE_NETPLAN" || -e "${SYSTEMD_DIR}/nettap-bridge.service" ]]; then
        BRIDGE_MODE="true"
    fi
}

# none | legacy (no record of NetTap's write) | restore | remove | changed (edited since)
daemon_json_action() {
    local installed="${DAEMON_JSON}.nettap-installed"
    if [[ ! -e "$DAEMON_JSON" ]]; then
        echo none
    elif [[ ! -e "$installed" ]]; then
        echo legacy
    elif ! cmp -s "$DAEMON_JSON" "$installed"; then
        echo changed
    elif [[ -e "${DAEMON_JSON}.nettap-backup" ]]; then
        echo restore
    else
        echo remove
    fi
}

refuse() {
    echo >&2
    warn "$1"
    warn "Nothing was changed."
    exit 1
}

# The interface whose block in the bridge netplan has an addresses: line (setup-bridge.sh with MGMT_IP)
static_address_iface() {
    awk '/^    [A-Za-z0-9._-]+:[[:space:]]*$/ { name = $1; sub(/:$/, "", name) }
        /^[[:space:]]+addresses:/ { print (name == "" ? "a port" : name); exit }' "$1"
}

# Asks the running daemon whether another DHCP server answers on the LAN (NetTap's own excluded).
# 0 one does, 1 none does, 2 the daemon couldn't be asked.
# The token goes to curl on stdin (printf is a builtin), never in a process's arguments or the output.
other_dhcp_server_answers() {
    local token reply
    token="$(docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token 2>/dev/null)" || return 2
    [[ -n "$token" ]] || return 2
    reply="$(printf 'X-NetTap-Daemon-Token: %s\n' "$token" \
        | curl --max-time 30 -sf -H @- "$DHCP_PREFLIGHT_URL" 2>/dev/null)" || return 2
    jq -e '(.other_dhcp_servers | length) > 0' <<< "$reply" >/dev/null 2>&1
}

# Checked before any prompt or change, in a dry run too.
refuse_if_unsafe() {
    local iface rc
    # netplan files are root's (600): a dry run without sudo can't look inside
    if [[ -f "$BRIDGE_NETPLAN" && ! -r "$BRIDGE_NETPLAN" ]]; then
        refuse "Can't read $(show_path "$BRIDGE_NETPLAN") to check it. Run this with sudo."
    fi
    if [[ -f "$BRIDGE_NETPLAN" ]] && grep -qE '^[[:space:]]+addresses:' "$BRIDGE_NETPLAN"; then
        iface="$(static_address_iface "$BRIDGE_NETPLAN")"
        refuse "$(show_path "$BRIDGE_NETPLAN") also gives ${iface} its fixed address; removing it would drop that address at the next boot. Move the ${iface} part into its own file in /etc/netplan, then run this again."
    fi
    if [[ -e "${SYSTEMD_DIR}/nettap-dhcp-gateway.service" || -e "$DHCP_NETPLAN" ]]; then
        # Stopping NetTap stops its DHCP server (dnsmasq runs in the daemon container) at once
        other_dhcp_server_answers
        rc=$?
        if [[ "$rc" -eq 2 ]]; then
            refuse "NetTap is this network's DHCP server, and its daemon couldn't be asked whether your router's DHCP server answers. Run this with sudo while NetTap is running."
        elif [[ "$rc" -ne 0 ]]; then
            refuse "NetTap is this network's DHCP server. Turn your router's DHCP server back on, then run this again; it checks the router answers first."
        fi
        log "Another DHCP server answers on this network, so NetTap's can stop."
    fi
}

show_plan() {
    local unit f
    log "This removes NetTap from this machine:"
    log "  - stops and removes NetTap's containers (docker compose down)"
    for unit in ${PRESENT_UNITS[@]+"${PRESENT_UNITS[@]}"}; do log "  - systemd unit ${unit}"; done
    for f in ${PRESENT_FILES[@]+"${PRESENT_FILES[@]}"}; do log "  - $(show_path "$f")"; done
    case "$DAEMON_JSON_ACTION" in
        restore) log "  - /etc/docker/daemon.json: put back the version from before NetTap" ;;
        remove)  log "  - /etc/docker/daemon.json (NetTap created it)" ;;
    esac
    if [[ "$PURGE" == "true" ]]; then
        log "  - ALL captured data: NetTap's Docker volumes, and its settings in /etc/nettap"
    fi
}

# Both questions come before any change. EOF or anything but yes/delete: stop, nothing changed.
confirm() {
    local answer=""
    [[ "$NETTAP_DRY_RUN" == "true" ]] && return 0
    if [[ "$ASSUME_YES" != "true" ]]; then
        read -r -p "Remove NetTap? [y/N] " answer || answer=""
        [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]] || return 1
    fi
    if [[ "$PURGE" == "true" ]]; then
        answer=""
        read -r -p "This erases every capture, alert and setting, for good. Type delete to go on: " answer || answer=""
        [[ "$answer" == "delete" ]] || return 1
    fi
    return 0
}

# Units go first: stopping nettap-bypass.service runs bypass-mode.sh --disable, which starts the
# capture containers again, so compose down has to come after it.
remove_units() {
    local unit link
    for unit in ${PRESENT_UNITS[@]+"${PRESENT_UNITS[@]}"}; do
        if [[ -e "${SYSTEMD_DIR}/${unit}" ]]; then
            run systemctl disable --now "$unit" || { warn "Couldn't stop and disable ${unit}."; fail; }
            run rm -f "${SYSTEMD_DIR}/${unit}" || fail
        fi
        # The daemon makes its own wants links; a leftover one would point at nothing
        for link in "${SYSTEMD_DIR}"/*.wants/"${unit}"; do
            [[ -L "$link" ]] && { run rm -f "$link" || fail; }
        done
    done
}

stop_containers() {
    local args=(down)
    [[ "$PURGE" == "true" ]] && args+=(-v)
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        warn "No $(show_path "$COMPOSE_FILE"): NetTap's containers weren't stopped."
        fail
        return 0
    fi
    run docker compose -f "$COMPOSE_FILE" "${args[@]}" \
        || { warn "Couldn't stop NetTap's containers; the system files are removed anyway."; fail; }
}

remove_files() {
    local f
    for f in ${PRESENT_FILES[@]+"${PRESENT_FILES[@]}"}; do
        run rm -f "$f" || { warn "Couldn't remove $(show_path "$f")."; fail; }
    done
}

restore_docker_daemon() {
    local installed="${DAEMON_JSON}.nettap-installed" backup="${DAEMON_JSON}.nettap-backup"
    case "$DAEMON_JSON_ACTION" in
        restore)
            if run mv -f "$backup" "$DAEMON_JSON"; then
                run rm -f "$installed" || fail
            else
                warn "Couldn't put back /etc/docker/daemon.json from $(show_path "$backup")."
                fail
            fi
            ;;
        remove) run rm -f "$DAEMON_JSON" "$installed" || fail ;;
        changed)
            log "Left /etc/docker/daemon.json alone: it changed after NetTap wrote it."
            log "NetTap added \"dns\" (9.9.9.9, 149.112.112.112); take it out by hand if you don't want it."
            ;;
        legacy)
            log "Left /etc/docker/daemon.json alone: there's no record of what NetTap wrote to it."
            log "An older NetTap added \"dns\" (9.9.9.9, 149.112.112.112), and log-driver, log-opts and storage-driver if it created the file."
            ;;
    esac
}

closing_card() {
    log ""
    log "NetTap is removed. Reboot to finish: sudo reboot"
    if [[ "$BRIDGE_MODE" == "true" ]]; then
        log "Bridge mode: plug the modem straight into the router before you reboot. The bridge keeps forwarding until then."
    fi
    log "Left in place:"
    log "  - the packages the installer added (Docker, jq, ethtool and others)"
    log "  - the hostname and avahi settings, UFW rules and /etc/watchdog.conf"
    log "  - this folder (${PROJECT_ROOT}) with docker/.env and the certificates"
    log "  - Docker images (docker image prune -a removes the unused ones)"
    if [[ "$PURGE" != "true" ]]; then
        log "  - /etc/nettap and NetTap's Docker volumes (run again with --purge-data to erase them)"
    fi
}

main() {
    parse_args "$@"
    [[ "$NETTAP_DRY_RUN" == "true" ]] || require_root
    find_present
    refuse_if_unsafe
    show_plan
    if ! confirm; then
        warn "Nothing was changed."
        exit 1
    fi
    remove_units
    stop_containers
    remove_files
    restore_docker_daemon
    if [[ ${#PRESENT_UNITS[@]} -gt 0 ]]; then
        run systemctl daemon-reload || fail
    fi
    if [[ "$PURGE" == "true" && -d "$SETTINGS_DIR" ]]; then
        run rm -rf "$SETTINGS_DIR" || { warn "Couldn't remove /etc/nettap."; fail; }
    fi
    if [[ "$NETTAP_DRY_RUN" == "true" ]]; then
        log "Dry run: nothing was changed."
        exit 0
    fi
    closing_card
    if [[ "$FAILURES" -gt 0 ]]; then
        warn "${FAILURES} step(s) failed; see the warnings above."
        exit 1
    fi
}

main "$@"
