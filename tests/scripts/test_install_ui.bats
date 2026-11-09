#!/usr/bin/env bats
# ==========================================================================
# BATS tests for the installer look (NET-204):
# scripts/install/ui.sh, the NETTAP_UI branches in scripts/common.sh, and how
# install.sh, deploy-malcolm.sh and validate-hardware.sh use them.
# ==========================================================================
# Every snippet runs in a fresh `bash -euo pipefail`, because the installer
# runs under strict mode and a helper that returns non-zero kills it.

REPO_ROOT="$(cd "$(dirname "$BATS_TEST_FILENAME")/../.." && pwd)"
COMMON="${REPO_ROOT}/scripts/common.sh"
UI="${REPO_ROOT}/scripts/install/ui.sh"
INSTALL="${REPO_ROOT}/scripts/install/install.sh"
DEPLOY="${REPO_ROOT}/scripts/install/deploy-malcolm.sh"
HARDWARE="${REPO_ROOT}/scripts/install/validate-hardware.sh"
ESC=$'\033'
CURSOR_SHOW=$'\033[?25h'

setup() {
    TEST_TMPDIR="$(mktemp -d)"
    export TEST_TMPDIR
    # Plain unless a test says otherwise; colour off so output is easy to compare.
    export NETTAP_UI=plain NETTAP_COLOR=never TERM=xterm-256color
    unset COLUMNS
}

teardown() {
    rm -rf "${TEST_TMPDIR:-/nonexistent}"
}

# Run a snippet with common.sh + ui.sh loaded, under strict mode.
ui_run() {
    run bash -c "set -euo pipefail; source '$COMMON'; source '$UI'; $1"
}

# Same, but in the fancy layout with colours (what an interactive install sees).
fancy_run() {
    run env NETTAP_COLOR=always bash -c "set -euo pipefail; source '$COMMON'; source '$UI'; ui_enable; $1"
}

# Wait up to 5 s for a process whose command line matches $1.
wait_for_process() {
    local i
    for i in $(seq 1 50); do
        pgrep -f "$1" > /dev/null && return 0
        sleep 0.1
    done
    echo "process '$1' never started"
    return 1
}

# Longest line of $1 in characters (not bytes).
max_width() {
    local loc
    loc=$(locale -a 2>/dev/null | grep -iE '^(c|en_us)\.utf-?8$' | head -1)
    printf '%s\n' "$1" | LC_ALL="${loc:-C.UTF-8}" bash -c \
        'm=0; while IFS= read -r l; do (( ${#l} > m )) && m=${#l}; done; echo $m'
}

# ==========================================================================
# common.sh: status_line and the fancy log branch
# ==========================================================================

@test "status_line: plain output is today's [ OK ]/[WARN]/[FAIL]/[SKIP] line, and it returns 0" {
    ui_run "status_line OK 'Docker is running'; status_line WARN 'w'; status_line FAIL 'f'; status_line SKIP 's'; echo done"
    [ "$status" -eq 0 ]
    [ "${lines[0]}" = "[ OK ] Docker is running" ]
    [ "${lines[1]}" = "[WARN] w" ]
    [ "${lines[2]}" = "[FAIL] f" ]
    [ "${lines[3]}" = "[SKIP] s" ]
    [ "${lines[4]}" = "done" ]
}

@test "status_line: fancy glyphs, and console-safe ones on TERM=linux" {
    run env NETTAP_UI=fancy bash -c "set -euo pipefail; source '$COMMON'; status_line OK a; status_line WARN b; status_line FAIL c; status_line SKIP d"
    [ "${lines[0]}" = "        ✓ a" ]
    [ "${lines[1]}" = "        ! b" ]
    [ "${lines[2]}" = "        ✗ c" ]
    [ "${lines[3]}" = "        - d" ]
    run env NETTAP_UI=fancy TERM=linux bash -c "set -euo pipefail; source '$COMMON'; status_line OK a; status_line FAIL c"
    [ "${lines[0]}" = "        + a" ]
    [ "${lines[1]}" = "        x c" ]
}

@test "log/warn/error: fancy drops the prefix and timestamp; error still exits 1" {
    run env NETTAP_UI=fancy bash -c "set -euo pipefail; source '$COMMON'; log hello; log ''; warn careful 2>&1; error boom 2>&1; echo unreachable"
    [ "$status" -eq 1 ]
    [ "$output" = "        hello"$'\n\n'"        ! careful"$'\n'"        ✗ boom" ]
    [[ "$output" != *"[NetTap]"* ]] || false
    [[ "$output" != *"unreachable"* ]] || false
}

@test "log: plain mode keeps the [NetTap] timestamp format" {
    ui_run "log hello"
    [[ "$output" =~ ^\[NetTap\]\ [0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9:]{8}\ hello$ ]] || false
}

# ==========================================================================
# ui.sh: banner, steps, cards
# ==========================================================================

@test "banner: full logo at 100 columns is 8 rows, at most 78 columns, no escape codes in plain" {
    ui_run "COLUMNS=100 ui_banner v1.2.3"
    [ "$status" -eq 0 ]
    [[ "$output" != *"$ESC"* ]] || false
    local art
    art=$(printf '%s\n' "$output" | grep -E '[█═╚╗]')
    [ "$(printf '%s\n' "$art" | wc -l | tr -d ' ')" -eq 8 ]
    [ "$(max_width "$output")" -le 78 ]
    [[ "$output" == *"Installer v1.2.3"* ]] || false
}

@test "banner: compact logo under 80 columns is 3 rows, at most 50 columns" {
    ui_run "COLUMNS=60 ui_banner"
    [ "$status" -eq 0 ]
    [[ "$output" == *"█▄ █ █▀▀"* ]] || false
    [[ "$output" != *"███╗"* ]] || false
    local art
    art=$(printf '%s\n' "$output" | grep -E '[█▀▄╺]')
    [ "$(printf '%s\n' "$art" | wc -l | tr -d ' ')" -eq 3 ]
    [ "$(max_width "$art")" -le 50 ]
}

@test "TERM=linux: banner, step header and cards use only console-safe glyphs" {
    run env NETTAP_COLOR=always TERM=linux bash -c "set -euo pipefail; source '$COMMON'; source '$UI'; ui_enable
        UI_TOTAL_STEPS=9; COLUMNS=100 ui_banner; COLUMNS=100 ui_step 'Pre-flight checks'
        WAN_INTERFACE=enp2s0 LAN_INTERFACE=enp3s0; _ui_cabling"
    [ "$status" -eq 0 ]
    local g
    for g in ━ ✦ ╲ ╱ ╸ ╺ ╾ ✓ ✗ ┃ ▸ ⠋; do
        [[ "$output" != *"$g"* ]] || { echo "found $g"; return 1; }
    done
    [[ "$output" == *"███"* && "$output" == *"╚═╝"* ]] || false
}

@test "banner: works under strict mode with TERM and COLUMNS unset and tput missing or failing" {
    local bin="${TEST_TMPDIR}/bin"
    mkdir -p "$bin"
    ln -s "$(command -v date)" "$bin/date"
    ln -s "$(command -v hostname)" "$bin/hostname"
    run env -u TERM -u COLUMNS PATH="$bin" "$BASH" -c "set -euo pipefail; source '$COMMON'; source '$UI'; ui_enable; ui_banner; echo ok"
    [ "$status" -eq 0 ]
    [ "${lines[${#lines[@]}-1]}" = "ok" ]
    printf '#!/bin/sh\nexit 1\n' > "$bin/tput"
    chmod +x "$bin/tput"
    run env -u COLUMNS PATH="$bin" TERM=xterm NETTAP_COLOR=always "$BASH" -c "set -euo pipefail; source '$COMMON'; source '$UI'; ui_enable; ui_banner; echo ok"
    [ "$status" -eq 0 ]
    [[ "$output" == *"████████"* ]] || false   # 80 columns assumed, so the full logo
}

@test "ui_step: plain is a renumbered [Step N/9] log line" {
    ui_run "UI_TOTAL_STEPS=9; ui_step 'Pre-flight checks'; ui_step 'Installing system dependencies'"
    [ "$status" -eq 0 ]
    [[ "${lines[1]}" == *"[Step 2/9] Installing system dependencies..." ]] || false
    [[ "$output" != *"$ESC"* ]] || false
}

@test "ui_step: fancy shows [N/T], a progress bar and the title" {
    fancy_run "UI_TOTAL_STEPS=9; COLUMNS=100; ui_step a; ui_step b; ui_step 'Applying kernel tuning'"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[3/9]"* ]] || false
    [[ "$output" == *"━━━━━━"* ]] || false
    [[ "$output" == *"Applying kernel tuning"* ]] || false
}

@test "before-we-start card: no .env yet, an unplugged port, and no MGMT port" {
    ui_run "nic_has_carrier() { return 1; }
        ui_before_we_start
        WAN_INTERFACE=enp2s0; ui_before_we_start"
    [ "$status" -eq 0 ]
    [[ "$output" == *"not set yet"* ]] || false
    [[ "$output" == *"enp2s0"*"no cable yet"* ]] || false
    [[ "$output" == *"through Wi-Fi"* ]] || false
    [[ "$output" == *"https://nettap.local"* ]] || false
}

@test "ui_countdown: EOF and timeout are normal under strict mode" {
    ui_run "ui_countdown 1 < /dev/null; echo after-eof"
    [ "$status" -eq 0 ]
    [[ "$output" == *"after-eof"* ]] || false
    ui_run "sleep 3 | { ui_countdown 1; echo after-timeout; }"
    [ "$status" -eq 0 ]
    [[ "$output" == *"after-timeout"* ]] || false
}

# ==========================================================================
# ui.sh: spinner
# ==========================================================================

@test "ui_spin: returns the command's status inside if" {
    fancy_run "if ui_spin x true; then echo zero; fi
        if ui_spin x sh -c 'exit 3'; then echo wrong; else echo \"rc=\$?\"; fi"
    [ "$status" -eq 0 ]
    [[ "$output" == *"zero"* ]] || false
    [[ "$output" == *"rc=3"* ]] || false
}

@test "ui_spin: a bare call under set -e carries on after success and stops after failure" {
    fancy_run "ui_spin x true; echo after"
    [ "$status" -eq 0 ]
    [[ "$output" == *"after"* ]] || false
    fancy_run "ui_spin x false; echo after"
    [ "$status" -eq 1 ]
    [[ "$output" != *"after"* ]] || false
    [[ "$output" == *"$CURSOR_SHOW"* ]] || false
}

@test "ui_spin: fancy captures the command's output in UI_SPIN_LOG; plain streams it" {
    fancy_run "ui_spin x sh -c 'echo hello-from-cmd'; echo; echo \"log=\$(cat \"\$UI_SPIN_LOG\")\"; rm -f \"\$UI_SPIN_LOG\""
    [ "$status" -eq 0 ]
    [[ "$output" == *"log=hello-from-cmd"* ]] || false
    [ "$(printf '%s\n' "$output" | grep -c 'hello-from-cmd')" -eq 1 ]
    ui_run "ui_spin x echo streamed; echo \"log=[\$UI_SPIN_LOG]\""
    [[ "$output" == *"streamed"* ]] || false
    [[ "$output" == *"log=[]"* ]] || false
}

@test "ui_spin: when mktemp fails it still runs the command, returns its status and hands back no path" {
    fancy_run "export TMPDIR='${TEST_TMPDIR}/missing'
        ui_spin x true; echo \"ok-log=[\$UI_SPIN_LOG]\"
        ui_spin x sh -c 'exit 4' || echo \"rc=\$? log=[\$UI_SPIN_LOG]\""
    [ "$status" -eq 0 ]
    [[ "$output" == *"ok-log=[]"* ]] || false
    [[ "$output" == *"rc=4 log=[]"* ]] || false
}

@test "pull_images (fancy): a pull still succeeds when no temp file can be made" {
    run env NETTAP_COLOR=always TMPDIR="${TEST_TMPDIR}/missing" bash -c "source '$DEPLOY'; ui_enable
        docker() { echo pulled; }
        pull_images; echo finished"
    [ "$status" -eq 0 ]
    [[ "$output" == *"finished"* ]] || false
    [[ "$output" == *"All "*" Malcolm images pulled successfully"* ]] || false
}

@test "ui_spin: default, ignored and custom traps are put back after two calls" {
    fancy_run "trap '' TERM; trap 'echo custom' HUP
        before=\$(trap -p INT TERM HUP)
        ui_spin x true; ui_spin x true
        after=\$(trap -p INT TERM HUP)
        [[ \"\$before\" == \"\$after\" ]] && echo same"
    [ "$status" -eq 0 ]
    [[ "$output" == *"same"* ]] || false
}

@test "ui_spin: SIGTERM stops the child, shows the cursor and exits 143" {
    local script="${TEST_TMPDIR}/spin.sh" out="${TEST_TMPDIR}/out"
    printf '%s\n' "set -euo pipefail" "source '$COMMON'" "source '$UI'" "ui_enable" \
        "ui_spin 'Pulling' sleep 31.7" "echo NEXT" > "$script"
    NETTAP_COLOR=always bash "$script" > "$out" 2>&1 &
    local pid=$! rc=0
    wait_for_process 'sleep 31.7'
    kill -TERM "$pid"
    wait "$pid" || rc=$?
    [ "$rc" -eq 143 ]
    # A bare "! cmd" never fails a bats test (set -e ignores negation), so check the status.
    run pgrep -f 'sleep 31.7'
    [ "$status" -ne 0 ]
    grep -qF "$CURSOR_SHOW" "$out"
    ! grep -q NEXT "$out"
}

@test "Ctrl-C through installer -> child script -> spinner: exit 130, cancelled, nothing after" {
    command -v python3 > /dev/null || skip "python3 not available"
    local child="${TEST_TMPDIR}/child.sh" parent="${TEST_TMPDIR}/parent.sh"
    printf '%s\n' "set -euo pipefail" "source '$COMMON'" "source '$UI'" \
        "ui_spin 'Pulling images' sleep 32.3" > "$child"
    # The real install_entry (traps and all) with main swapped for a short stand-in.
    printf '%s\n' "source '$INSTALL'" \
        "main() { ui_step 'Deploying Malcolm stack'; bash '$child'; echo 'NEXT STEP'; }" \
        "install_entry" > "$parent"
    run env NETTAP_COLOR=always python3 -c '
import os, signal, subprocess, sys, time
p = subprocess.Popen(["bash", sys.argv[1]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     start_new_session=True,
                     preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
# Signal only once the spinner child is running, so the test exercises ui_spin.
for _ in range(50):
    # [.] so the pattern does not match this launcher, whose own command line holds the text
    if subprocess.run(["pgrep", "-f", "sleep 32[.]3"], stdout=subprocess.DEVNULL).returncode == 0:
        break
    time.sleep(0.1)
else:
    print("spinner child never started")
os.killpg(p.pid, signal.SIGINT)   # what a terminal does on Ctrl-C
out, _ = p.communicate(timeout=5)
sys.stdout.write(out.decode())
print("rc=%d" % p.returncode)
' "$parent"
    [[ "$output" == *"rc=130"* ]] || false
    [[ "$output" == *"Install cancelled at step 1/9: Deploying Malcolm stack"* ]] || false
    [[ "$output" != *"NEXT STEP"* ]] || false
    [[ "$output" == *"$CURSOR_SHOW"* ]] || false
    [[ "$output" != *"spinner child never started"* ]] || false
    run pgrep -f 'sleep 32.3'
    [ "$status" -ne 0 ]
}

# ==========================================================================
# install.sh
# ==========================================================================

@test "install.sh: sourcing parses nothing, sets no traps and runs nothing" {
    run bash -c "set -- --defer-bridge --dry-run; trap 'echo mine' HUP
        source '$INSTALL'
        echo \"args=\$*\"; echo \"defer=\$DEFER_BRIDGE\"; trap -p HUP; trap -p EXIT; echo \"step=\$UI_STEP\""
    [ "$status" -eq 0 ]
    [[ "$output" == *"args=--defer-bridge --dry-run"* ]] || false
    [[ "$output" == *"defer=false"* ]] || false
    [[ "$output" == *"echo mine"* ]] || false
    [[ "$output" != *"_install_on_exit"* ]] || false
    [[ "$output" == *"step=0"* ]] || false
}

@test "install.sh: nine steps, matching UI_TOTAL_STEPS" {
    [ "$(grep -cE '^\s*ui_step "' "$INSTALL")" -eq 9 ]
    grep -qE '^UI_TOTAL_STEPS=9$' "$INSTALL"
}

@test "install.sh: a failure at step 5 prints the card with its hint and the same command" {
    run bash -c "source '$INSTALL'
        main() { UI_STEP=4; ui_step 'Deploying Malcolm stack'; false; }
        install_entry --defer-bridge --skip-pull"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Install stopped at step 5/9: Deploying Malcolm stack"* ]] || false
    [[ "$output" == *"curl -sI https://ghcr.io"* ]] || false
    [[ "$output" == *"Run the same command again"* ]] || false
    [[ "$output" == *"sudo "*" --defer-bridge --skip-pull"* ]] || false
}

@test "install.sh: every failure hint names a real step title" {
    local title
    while IFS= read -r title; do
        grep -qF "ui_step \"${title}\"" "$INSTALL" || { echo "no step called: $title"; return 1; }
    done < <(sed -n '/^_ui_failure_hint()/,/^}/p' "$UI" | grep -oE '^ *"[^"]+"\)' | sed -E 's/^ *"(.*)"\)$/\1/')
}

@test "install.sh: the exit status survives a closed stdout (ssh dropped)" {
    run bash -c "source '$INSTALL'; main() { exit 130; }; install_entry >&-"
    [ "$status" -eq 130 ]
    run bash -c "source '$INSTALL'; main() { ui_step x; false; }; install_entry >&-"
    [ "$status" -eq 1 ]
}

@test "install.sh: a clean run prints no card; exit 130 prints the cancel line" {
    run bash -c "source '$INSTALL'; main() { ui_step 'Pre-flight checks'; }; install_entry"
    [ "$status" -eq 0 ]
    [[ "$output" != *"Install stopped"* ]] || false
    [[ "$output" != *"Install cancelled"* ]] || false
    run bash -c "source '$INSTALL'; main() { ui_step 'Pre-flight checks'; exit 130; }; install_entry"
    [ "$status" -eq 130 ]
    [[ "$output" == *"Install cancelled at step 1/9: Pre-flight checks"* ]] || false
}

# Stubs for step_verify: bridge up, docker up with two containers,
# OpenSearch not answering yet, services enabled, kernel tuned.
VERIFY_STUBS='
ip() { return 0; }
docker() { case "$1" in info) return 0 ;; compose) printf "a\nb\n" ;; esac; }
curl() { return 1; }
systemctl() { return 0; }
sysctl() { echo 262144; }'

@test "step_verify: plain checks keep today's lines; the summary card has the cabling" {
    printf 'WAN_INTERFACE=enp2s0\nLAN_INTERFACE=enp3s0\nMGMT_INTERFACE=enp1s0\n' > "${TEST_TMPDIR}/.env"
    run bash -c "source '$INSTALL'; $VERIFY_STUBS
        PROJECT_ROOT='$TEST_TMPDIR'; UI_STEP=8; step_verify"
    [ "$status" -eq 0 ]
    [[ "$output" == *"[ OK ] Bridge br0 exists"* ]] || false
    # macOS wc -l pads the count with spaces; Linux (where the installer runs) does not.
    [[ "$output" == *"[ OK ] "*"2 container(s) running"* ]] || false
    [[ "$output" == *"[WARN] OpenSearch not responding yet"* ]] || false
    [[ "$output" == *"NetTap is installed"* ]] || false
    [[ "$output" == *"https://nettap.local"* ]] || false
    [[ "$output" == *"ISP modem ──▸ enp2s0 (WAN)"* ]] || false
    [[ "$output" == *"enp3s0 (LAN) ──▸ your router's WAN port"* ]] || false
    [[ "$output" == *"Keep enp1s0 (MGMT) connected"* ]] || false
    [[ "$output" == *"6 passed, 1 warning, 0 failed"* ]] || false
}

# A13 (NET-229): nettap-web has a setup code (first run), so the card shows it and how to read it again
@test "step_verify: the summary card prints the setup wizard's code" {
    printf 'WAN_INTERFACE=enp2s0\nLAN_INTERFACE=enp3s0\n' > "${TEST_TMPDIR}/.env"
    run bash -c "source '$INSTALL'; $VERIFY_STUBS
        docker() { case \"\$1 \${3:-} \${4:-}\" in 'exec cat /var/lib/nettap-web/setup-code') echo ABCD-EFGH-JKMN ;; info*) return 0 ;; compose*) printf 'a\nb\n' ;; *) return 1 ;; esac; }
        PROJECT_ROOT='$TEST_TMPDIR'; step_verify"
    [ "$status" -eq 0 ]
    [[ "$output" == *"Setup code"*"ABCD-EFGH-JKMN"* ]] || false
    [[ "$output" == *"sudo docker exec nettap-web cat /var/lib/nettap-web/setup-code"* ]] || false
}

@test "step_verify: an install that already has an admin shows no setup code" {
    printf 'WAN_INTERFACE=enp2s0\nLAN_INTERFACE=enp3s0\n' > "${TEST_TMPDIR}/.env"
    run bash -c "source '$INSTALL'; $VERIFY_STUBS
        docker() { case \"\$1 \${3:-}\" in 'exec test') return 0 ;; 'exec cat') return 1 ;; info*) return 0 ;; compose*) printf 'a\nb\n' ;; esac; }
        PROJECT_ROOT='$TEST_TMPDIR'; step_verify"
    [ "$status" -eq 0 ]
    [[ "$output" != *"Setup code"* ]] || false
}

@test "step_verify: with --skip-bridge the card does not claim the bridge is on" {
    printf 'WAN_INTERFACE=enp2s0\nLAN_INTERFACE=enp3s0\n' > "${TEST_TMPDIR}/.env"
    run bash -c "source '$INSTALL'; $VERIFY_STUBS
        PROJECT_ROOT='$TEST_TMPDIR'; SKIP_BRIDGE=true; step_verify"
    [ "$status" -eq 0 ]
    [[ "$output" == *"NetTap is installed"* ]] || false
    [[ "$output" != *"The bridge is on"* ]] || false
}

@test "step_verify: deferred bridge ends with activate-bridge.sh" {
    printf 'WAN_INTERFACE=enp2s0\nLAN_INTERFACE=enp3s0\n' > "${TEST_TMPDIR}/.env"
    run bash -c "source '$INSTALL'; $VERIFY_STUBS
        PROJECT_ROOT='$TEST_TMPDIR'; DEFER_BRIDGE=true; step_verify"
    [ "$status" -eq 0 ]
    [[ "$output" == *"The bridge is not on yet"* ]] || false
    [[ "$output" == *"sudo scripts/install/activate-bridge.sh"* ]] || false
    [[ "$output" == *"Keep Wi-Fi connected"* ]] || false
}

# ==========================================================================
# deploy-malcolm.sh and validate-hardware.sh
# ==========================================================================

@test "pull_images (fancy): successful pulls leave no log; a failed pull keeps its log and prints the path" {
    run env NETTAP_COLOR=always TMPDIR="$TEST_TMPDIR" bash -c "source '$DEPLOY'; ui_enable
        docker() { if [[ \"\$2\" == *\"/api:\"* ]]; then echo 'denied: no access'; return 1; fi; echo pulled; }
        pull_images"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Failed to pull"*"/api:"* ]] || false
    [[ "$output" == *"denied: no access"* ]] || false
    [[ "$output" == *"Full output: ${TEST_TMPDIR}/nettap-spin."* ]] || false
    [ "$(find "$TEST_TMPDIR" -name 'nettap-spin.*' | wc -l | tr -d ' ')" -eq 1 ]
}

@test "validate_hardware: fancy drops the header box; plain keeps it and the [ OK ] lines" {
    run env NETTAP_UI=fancy bash -c "source '$HARDWARE'; validate_hardware || true"
    [[ "$output" != *"NetTap Hardware Validation"* ]] || false
    [[ "$output" == *"        ✓ Kernel:"* ]] || false
    [[ "$output" == *"RESULT:"* ]] || false
    run bash -c "source '$HARDWARE'; validate_hardware || true"
    [[ "$output" == *"NetTap Hardware Validation"* ]] || false
    [[ "$output" == *"[ OK ] Kernel:"* ]] || false
}
