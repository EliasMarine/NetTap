#!/usr/bin/env bash
# ==========================================================================
# NetTap — installer look (NET-204)
# ==========================================================================
# Logo, step headers, cards, a start countdown and a spinner for install.sh.
# Sourced after scripts/common.sh by install.sh (and by deploy-malcolm.sh for
# the spinner). NETTAP_UI picks the layout:
#   fancy — colour, progress bar, spinner, cards (interactive terminal)
#   plain — today's timestamped lines (pipes, log files, NETTAP_COLOR=never)
# install.sh calls ui_enable once and exports NETTAP_UI to the scripts it runs.
#
# The card functions read install.sh's globals (WAN_INTERFACE, LAN_INTERFACE,
# MGMT_INTERFACE, NETTAP_HOSTNAME, DASHBOARD_PORT, SKIP_BRIDGE, DEFER_BRIDGE,
# NON_INTERACTIVE, INSTALL_START_TIME, INSTALL_ARGS).

UI_STEP=0
UI_STEP_TITLE=""
UI_TOTAL_STEPS="${UI_TOTAL_STEPS:-0}"
_UI_SPIN_PID=""
_UI_SPIN_LOG=""
# Path of the last spinner's output file, for the caller (deploy-malcolm.sh).
# shellcheck disable=SC2034
UI_SPIN_LOG=""

# ---------------------------------------------------------------------------
# Logo. {Y} yellow letters, {C} cyan shadow, {W}/{B} the bolt, {M}/{R} streaks.
# ---------------------------------------------------------------------------
_UI_BANNER_FULL=(
    '              {Y}███{C}╗    {Y}██{C}╗          {Y}██{C}╗   {Y}████████{C}╗{0}'
    '   {R}╸━        {Y}████{C}╗   {Y}██{C}║ {Y}██████{C}╗ {Y}██████{C}╗╚══{Y}██{C}╔══╝ {Y}██████{C}╗ {Y}███████{C}╗   {M}━━ ━{0}'
    ' {M}━━ ━       {Y}██{C}╔{Y}██{C}╗  {Y}██{C}║{Y}██{C}╔═══{Y}██{C}╗╚{Y}██{C}╔══╝   {Y}██{C}║    ╚════{Y}██{C}╗{Y}██{C}╔═══{Y}██{C}╗   {B}╲ ╱{0}'
    '{B}╺━━{W}━━━━━━━━{Y}██{C}║╚{Y}██{C}╗{W}━{Y}██{C}║{Y}████████{C}║{W}━{Y}██{C}║{W}━━━━━━{Y}██{C}║{W}━━━━{Y}███████{C}║{Y}██{C}║{W}━━━{Y}██{C}║{W}━━━━╾✦{B}━╸{0}'
    '          {Y}██{C}║ ╚{Y}██{C}╗{Y}██{C}║{Y}██{C}╔═════╝ {Y}██{C}║      {Y}██{C}║   {Y}██{C}╔═══{Y}██{C}║{Y}███████{C}╔╝     {B}╱ ╲{0}'
    '{M}━━━ ━    {Y}██{C}║  ╚{Y}████{C}║╚{Y}██████{C}╗  ╚{Y}████{C}╗   {Y}██{C}║   ╚{Y}███████{C}║{Y}██{C}╔════╝  {M}━ ━━━{0}'
    '        {C}╚═╝   ╚═══╝ ╚═════╝   ╚═══╝   ╚═╝    ╚══════╝{Y}██{C}║           {R}╸━{0}'
    '                                                    {C}╚═╝{0}'
)
_UI_BANNER_COMPACT=(
    '  {M}━━  {Y}█▄ █ █▀▀ ▀█▀ ▀█▀ ▄▀█ █▀█{0}'
    ' {M}━━━ {Y}█ ▀█ ██▄  █   █  █▀█ █▀▀{0}'
    '{B}╺━{W}━━━━━━━━━━━━━━━━━━━━━━━━━━━━╾✦{B}━╸{0}'
)

# ---------------------------------------------------------------------------
# Mode, colours and glyphs
# ---------------------------------------------------------------------------
# Decide the layout once, in the installer's own shell (not in $(...), where
# stdout is a pipe), and export it to child scripts.
ui_enable() {
    NETTAP_UI="plain"
    case "${NETTAP_COLOR:-auto}" in
        always) NETTAP_UI="fancy" ;;
        never)  ;;
        *)
            if [[ -t 1 && "${TERM:-dumb}" != "dumb" ]]; then
                NETTAP_UI="fancy"
            fi
            ;;
    esac
    export NETTAP_UI
    _ui_palette
}

_ui_palette() {
    local e=$'\033[' colors
    colors=$(tput colors 2>/dev/null) || colors=8
    [[ "$colors" =~ ^[0-9]+$ ]] || colors=8

    if [[ "$NETTAP_UI" != "fancy" ]]; then
        _UI_Y="" _UI_C="" _UI_W="" _UI_B="" _UI_M="" _UI_R="" _UI_DIM="" _UI_BOLD="" _UI_OFF=""
        _UI_OKC="" _UI_FAILC="" _UI_CURSOR_HIDE="" _UI_CURSOR_SHOW=""
        return 0
    fi
    if (( colors >= 256 )); then
        _UI_Y="${e}38;5;226m" _UI_C="${e}38;5;51m" _UI_W="${e}1;38;5;231m" _UI_B="${e}38;5;87m"
        _UI_M="${e}38;5;201m" _UI_R="${e}38;5;197m" _UI_DIM="${e}38;5;244m"
        _UI_OKC="${e}38;5;48m" _UI_FAILC="${e}38;5;196m"
    else
        # 8/16-colour terminals, including the Linux text console
        _UI_Y="${e}1;33m" _UI_C="${e}36m" _UI_W="${e}1;37m" _UI_B="${e}1;36m"
        _UI_M="${e}35m" _UI_R="${e}31m" _UI_DIM="${e}37m"
        _UI_OKC="${e}32m" _UI_FAILC="${e}31m"
    fi
    _UI_BOLD="${e}1m" _UI_OFF="${e}0m"
    _UI_CURSOR_HIDE="${e}?25l" _UI_CURSOR_SHOW="${e}?25h"
}

# The Linux text console font has box and block characters but not heavy
# lines, stars, small triangles or braille.
if [[ "${TERM:-}" == "linux" ]]; then
    _UI_FRAMES=('|' '/' '-' "\\")
    _UI_RULE="│" _UI_BAR_DONE="═" _UI_BAR_TODO="─" _UI_WIRE="═" _UI_ARROW=">"
else
    _UI_FRAMES=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    _UI_RULE="┃" _UI_BAR_DONE="━" _UI_BAR_TODO="─" _UI_WIRE="━" _UI_ARROW="▸"
fi

_ui_cols() {
    local c="${COLUMNS:-}"
    if [[ ! "$c" =~ ^[0-9]+$ ]]; then
        c=$(tput cols 2>/dev/null) || c=""
    fi
    [[ "$c" =~ ^[0-9]+$ ]] || c=80
    echo "$c"
}

# Seconds as "1m 05s".
_ui_duration() { printf '%dm %02ds' $(( $1 / 60 )) $(( $1 % 60 )); }

# Swap colour markers for codes (nothing in plain mode) and console-unsafe glyphs.
_ui_paint() {
    local s="$1"
    if [[ "${TERM:-}" == "linux" ]]; then
        s=${s//━/─}; s=${s//╸/─}; s=${s//╺/─}; s=${s//╾/─}
        s=${s//✦/*}; s=${s//╲/\\}; s=${s//╱//}
    fi
    s=${s//\{Y\}/$_UI_Y}; s=${s//\{C\}/$_UI_C}; s=${s//\{W\}/$_UI_W}; s=${s//\{B\}/$_UI_B}
    s=${s//\{M\}/$_UI_M}; s=${s//\{R\}/$_UI_R}; s=${s//\{0\}/$_UI_OFF}
    printf '%s\n' "$s"
}

# ---------------------------------------------------------------------------
# Logo, steps, cards
# ---------------------------------------------------------------------------
# Usage: ui_banner [version]
ui_banner() {
    local line host version="${1:-}"
    host=$(hostname -s 2>/dev/null) || host="nettap"
    printf '\n'
    if (( $(_ui_cols) >= 80 )); then
        for line in "${_UI_BANNER_FULL[@]}"; do _ui_paint "$line"; done
    else
        for line in "${_UI_BANNER_COMPACT[@]}"; do _ui_paint "$line"; done
    fi
    printf '\n  %sInstaller%s%s  %s·  %s  ·  %s%s\n' "$_UI_BOLD" "${version:+ $version}" "$_UI_OFF" \
        "$_UI_DIM" "$host" "$(date '+%Y-%m-%d %H:%M')" "$_UI_OFF"
    printf '  %sTransparent network visibility, inline between your modem and your router.%s\n' \
        "$_UI_DIM" "$_UI_OFF"
}

_ui_bar() {
    local done_part rest_part rest=$(( UI_TOTAL_STEPS - UI_STEP ))
    if (( $(_ui_cols) < 60 )); then return 0; fi
    if (( rest < 0 )); then rest=0; fi
    printf -v done_part '%*s' $(( UI_STEP * 2 )) ''
    printf -v rest_part '%*s' $(( rest * 2 )) ''
    printf '%s%s%s%s%s  ' "$_UI_C" "${done_part// /$_UI_BAR_DONE}" "$_UI_DIM" \
        "${rest_part// /$_UI_BAR_TODO}" "$_UI_OFF"
}

# Usage: ui_step "Installing system dependencies"
ui_step() {
    UI_STEP=$(( UI_STEP + 1 ))
    UI_STEP_TITLE="$1"
    if [[ "$NETTAP_UI" == "fancy" ]]; then
        printf '\n  %s[%d/%d]%s %s%s%s%s\n' "$_UI_DIM" "$UI_STEP" "$UI_TOTAL_STEPS" "$_UI_OFF" \
            "$(_ui_bar)" "$_UI_BOLD" "$1" "$_UI_OFF"
    else
        log "[Step ${UI_STEP}/${UI_TOTAL_STEPS}] $1..."
    fi
}

# A card is a left rule, so there is no width maths on Unicode text.
ui_card_line() { printf '  %s%s%s%s\n' "$_UI_C" "$_UI_RULE" "$_UI_OFF" "${1:+ $1}"; }
ui_card_kv()   { printf '  %s%s%s %s%-11s%s %s\n' "$_UI_C" "$_UI_RULE" "$_UI_OFF" "$_UI_DIM" "$1" "$_UI_OFF" "$2"; }

# Waits up to SECS for Enter. A timeout or EOF is the normal way through.
ui_countdown() {
    printf '  %sStarting in %d s. Enter starts now, Ctrl-C cancels.%s ' "$_UI_DIM" "$1" "$_UI_OFF"
    read -r -t "$1" || true
    printf '\n'
}

# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------
# Usage: ui_spin "label" cmd [args...]
# fancy: runs cmd in the background with its output in a temp file whose path
#        is left in UI_SPIN_LOG (the caller deletes or reports it), and shows a
#        spinner with the elapsed time. While it spins it owns Ctrl-C: a
#        non-interactive shell starts background jobs with SIGINT ignored, so
#        the child is killed and reaped here, never trusted to stop alone.
# plain: runs cmd in the foreground, output as before; UI_SPIN_LOG is empty.
# Returns cmd's exit status. Safe bare under set -e and inside if.
ui_spin() {
    local label="$1" rc=0 f=0 started=$SECONDS saved
    shift
    UI_SPIN_LOG=""
    if [[ "$NETTAP_UI" != "fancy" ]]; then
        "$@" || rc=$?
        return "$rc"
    fi

    _UI_SPIN_LOG=$(mktemp "${TMPDIR:-/tmp}/nettap-spin.XXXXXX") || _UI_SPIN_LOG="/dev/null"
    saved=$(trap -p INT TERM HUP)
    trap '_ui_spin_cancel 130' INT
    trap '_ui_spin_cancel 143' TERM
    trap '_ui_spin_cancel 129' HUP
    "$@" > "$_UI_SPIN_LOG" 2>&1 &
    _UI_SPIN_PID=$!

    printf '%s' "$_UI_CURSOR_HIDE"
    while kill -0 "$_UI_SPIN_PID" 2>/dev/null; do
        printf '\r\033[K%s%s%s%s %s  %s%s%s' "$_UI_PAD" "$_UI_C" "${_UI_FRAMES[f % ${#_UI_FRAMES[@]}]}" \
            "$_UI_OFF" "$label" "$_UI_DIM" "$(_ui_duration $(( SECONDS - started )))" "$_UI_OFF"
        f=$(( f + 1 ))
        sleep 0.1
    done
    wait "$_UI_SPIN_PID" || rc=$?
    _UI_SPIN_PID=""
    printf '\r\033[K%s' "$_UI_CURSOR_SHOW"

    # Put back exactly what was there: default, ignored or a custom handler.
    trap - INT TERM HUP
    eval "$saved"
    # shellcheck disable=SC2034  # read by the caller
    if [[ "$_UI_SPIN_LOG" != "/dev/null" ]]; then UI_SPIN_LOG="$_UI_SPIN_LOG"; fi
    _UI_SPIN_LOG=""
    return "$rc"
}

# Records the status first, so a failing kill/wait cannot change it or skip
# the cursor; an INT exits 130 even though the reaped child reports 143.
_ui_spin_cancel() {
    local status="$1"
    if [[ -n "$_UI_SPIN_PID" ]]; then
        kill -TERM "$_UI_SPIN_PID" 2>/dev/null || true
        wait "$_UI_SPIN_PID" 2>/dev/null || true
    fi
    if [[ -n "$_UI_SPIN_LOG" && "$_UI_SPIN_LOG" != "/dev/null" ]]; then
        rm -f "$_UI_SPIN_LOG" 2>/dev/null || true
    fi
    printf '\r\033[K%s' "$_UI_CURSOR_SHOW"
    exit "$status"
}

# ---------------------------------------------------------------------------
# Installer cards
# ---------------------------------------------------------------------------
_ui_dashboard_url() {
    local url="https://${NETTAP_HOSTNAME:-nettap.local}"
    if [[ "${DASHBOARD_PORT:-443}" != "443" ]]; then url+=":${DASHBOARD_PORT}"; fi
    echo "$url"
}

# "enp2s0  to your modem   2500Mb/s, cable in" — or "not set yet" before .env has it.
_ui_port_line() {
    local nic="$1" role="$2" state
    if [[ -z "$nic" ]]; then
        echo "${_UI_DIM}not set yet${_UI_OFF}"
        return 0
    fi
    if nic_has_carrier "$nic"; then
        state="$(get_nic_speed "$nic"), cable in"
    else
        state="no cable yet"
    fi
    printf '%-8s %s%-16s %s%s\n' "$nic" "$_UI_DIM" "$role" "$state" "$_UI_OFF"
}

ui_before_we_start() {
    local mgmt="${MGMT_INTERFACE:-}" bridge
    if [[ "${SKIP_BRIDGE:-false}" == "true" ]]; then
        bridge="skipped (--skip-bridge)"
    elif [[ "${DEFER_BRIDGE:-false}" == "true" ]]; then
        bridge="turned on after you move the cables (--defer-bridge)"
    else
        bridge="comes up in step 4; you move the cables at the end"
    fi

    printf '\n'
    ui_card_line "${_UI_BOLD}Before we start${_UI_OFF}"
    ui_card_line ""
    ui_card_kv "WAN port" "$(_ui_port_line "${WAN_INTERFACE:-}" "to your modem")"
    ui_card_kv "LAN port" "$(_ui_port_line "${LAN_INTERFACE:-}" "to your router")"
    if [[ -n "$mgmt" ]]; then
        ui_card_kv "Dashboard" "$(_ui_dashboard_url)  ${_UI_DIM}through ${mgmt}${_UI_OFF}"
    else
        ui_card_kv "Dashboard" "$(_ui_dashboard_url)  ${_UI_DIM}through Wi-Fi${_UI_OFF}"
    fi
    ui_card_kv "Bridge" "$bridge"
    ui_card_kv "Takes" "usually 10 to 20 minutes, mostly downloading"
    printf '\n'

    if [[ "$NETTAP_UI" == "fancy" && -t 0 && "${NON_INTERACTIVE:-false}" != "true" ]]; then
        ui_countdown 5
    fi
}

# The 1-2-3 cabling steps and the one-line diagram, shared by both summaries.
_ui_cabling() {
    local wan="${WAN_INTERFACE:-eth0}" lan="${LAN_INTERFACE:-eth1}" mgmt="${MGMT_INTERFACE:-}"
    local a="──${_UI_ARROW}"
    ui_card_line "  1. ISP modem ${a} ${_UI_Y}${wan}${_UI_OFF} (WAN)"
    ui_card_line "  2. ${_UI_Y}${lan}${_UI_OFF} (LAN) ${a} your router's WAN port"
    if [[ -n "$mgmt" ]]; then
        ui_card_line "  3. Keep ${_UI_Y}${mgmt}${_UI_OFF} (MGMT) connected for the dashboard"
    else
        ui_card_line "  3. Keep Wi-Fi connected for the dashboard"
    fi
    ui_card_line ""
    ui_card_line "  Modem ${a} ${_UI_Y}${wan}${_UI_OFF} ${_UI_W}${_UI_WIRE}${_UI_WIRE} NetTap ${_UI_WIRE}${_UI_WIRE}${_UI_OFF} ${_UI_Y}${lan}${_UI_OFF} ${a} Router"
}

_ui_counts() {
    local passed="$1" warned="$2" failed="${3:-}" s="s"
    if (( warned == 1 )); then s=""; fi
    printf '%d passed, %d warning%s%s' "$passed" "$warned" "$s" "${failed:+, $failed failed}"
}

# Usage: ui_summary_installed PASSED WARNED FAILED
ui_summary_installed() {
    local passed="$1" warned="$2" failed="$3"
    printf '\n'
    if (( failed > 0 )); then
        ui_card_line "${_UI_FAILC}${_UI_BOLD}NetTap is installed, but ${failed} check(s) failed${_UI_OFF}"
        ui_card_line "${_UI_DIM}Review the ${_UI_G_FAIL} lines above.${_UI_OFF}"
    else
        ui_card_line "${_UI_OKC}${_UI_BOLD}NetTap is installed${_UI_OFF}"
    fi
    ui_card_line ""
    ui_card_kv "Dashboard" "${_UI_BOLD}$(_ui_dashboard_url)${_UI_OFF}"
    ui_card_kv "Malcolm" "https://localhost:${MALCOLM_HTTPS_PORT:-9443}  ${_UI_DIM}on this box${_UI_OFF}"
    ui_card_kv "Checks" "$(_ui_counts "$passed" "$warned" "$failed")"
    ui_card_kv "Time taken" "$(_ui_duration $(( $(date +%s) - INSTALL_START_TIME )))"
    ui_card_line ""
    ui_card_line "${_UI_BOLD}Last step: move the cables${_UI_OFF}"
    _ui_cabling
    if [[ "${SKIP_BRIDGE:-false}" != "true" ]]; then
        ui_card_line "  ${_UI_DIM}The bridge is on, so traffic flows as soon as both cables are in.${_UI_OFF}"
    fi
    ui_card_line ""
    ui_card_kv "Manage" "systemctl {start|stop|restart} nettap"
    ui_card_kv "Logs" "journalctl -u nettap -f"
    ui_card_kv "Containers" "docker compose -f docker/docker-compose.yml ps"
    printf '\n'
}

# Usage: ui_summary_deferred PASSED WARNED
ui_summary_deferred() {
    printf '\n'
    ui_card_line "${_UI_OKC}${_UI_BOLD}NetTap is installed. The bridge is not on yet.${_UI_OFF}"
    ui_card_line ""
    ui_card_kv "Checks" "$(_ui_counts "$1" "$2")"
    ui_card_kv "Time taken" "$(_ui_duration $(( $(date +%s) - INSTALL_START_TIME )))"
    ui_card_line ""
    ui_card_line "${_UI_BOLD}Next: move the cables, then turn the bridge on${_UI_OFF}"
    _ui_cabling
    ui_card_line ""
    ui_card_line "  Then run:  ${_UI_BOLD}sudo scripts/install/activate-bridge.sh${_UI_OFF}"
    ui_card_kv "Dashboard" "$(_ui_dashboard_url)  ${_UI_DIM}once the bridge is on${_UI_OFF}"
    printf '\n'
}

_ui_failure_hint() {
    case "$UI_STEP_TITLE" in
        "Installing system dependencies")
            echo "Check this box can reach the Ubuntu package servers:  sudo apt-get update" ;;
        "Configuring network bridge")
            echo "Check both cables, and the port names in .env (WAN_INTERFACE, LAN_INTERFACE)." ;;
        "Deploying Malcolm stack")
            echo "Check this box can reach the image registry:  curl -sI https://ghcr.io" ;;
        *)
            echo "Read the last message above; it says what went wrong." ;;
    esac
}

_ui_rerun_command() {
    local cmd="sudo $0"
    if (( ${#INSTALL_ARGS[@]} > 0 )); then cmd+=$(printf ' %q' "${INSTALL_ARGS[@]}"); fi
    echo "$cmd"
}

_ui_where() {
    if (( UI_STEP == 0 )); then
        echo "before step 1"
    else
        echo "at step ${UI_STEP}/${UI_TOTAL_STEPS}: ${UI_STEP_TITLE}"
    fi
}

ui_failure_card() {
    printf '\n'
    ui_card_line "${_UI_FAILC}${_UI_BOLD}Install stopped $(_ui_where)${_UI_OFF}"
    ui_card_line ""
    ui_card_line "${_UI_BOLD}What to try${_UI_OFF}"
    ui_card_line "  1. $(_ui_failure_hint)"
    ui_card_line "  2. Run the same command again:"
    ui_card_line "     $(_ui_rerun_command)"
    if [[ "${NETTAP_VERBOSE:-false}" != "true" ]]; then
        ui_card_line ""
        ui_card_kv "Detail" "add -v for debug output"
    fi
    printf '\n'
}

ui_cancelled_line() {
    printf '\n  Install cancelled %s.\n  Run the same command again when you are ready:  %s\n\n' \
        "$(_ui_where)" "$(_ui_rerun_command)"
}

_ui_palette
