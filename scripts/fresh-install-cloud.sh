#!/usr/bin/env bash
# NetTap — fresh-install test on a throwaway DigitalOcean droplet (release gate H2/H7, cloud mirror scope).
#
# Runs on the dev machine. It creates, uses and deletes only the resources it records in
# .fresh-install/<run>/manifest.env, and checks the doctl account against that manifest first.
#
# Usage:
#   scripts/fresh-install-cloud.sh up <ubuntu-24-04-x64|ubuntu-22-04-x64>
#   scripts/fresh-install-cloud.sh install <run>        # documented interactive install, prompts answered
#   scripts/fresh-install-cloud.sh watch <run>          # read-only view of the live installer screen
#   scripts/fresh-install-cloud.sh tunnel <run>         # https://localhost/ -> the droplet (one at a time)
#   scripts/fresh-install-cloud.sh after-wizard <run>   # settings vs expected, reboot, settings again, auth
#   scripts/fresh-install-cloud.sh down <run>           # delete this run's droplet, firewall, key and tag
#   scripts/fresh-install-cloud.sh ssh <run> [command]  # a shell (or one command) on the droplet
#   scripts/fresh-install-cloud.sh status
#
# The wizard itself is run in a browser through the tunnel. Before after-wizard, write the choices to
# .fresh-install/<run>/expected-settings.txt (KEY=VALUE lines from `snapshot`) and the admin login to
# .fresh-install/<run>/admin.env (ADMIN_USER=…, ADMIN_PASS=…).
# pass/fail always return 0, so `test && pass … || fail …` is if/else here.
# shellcheck disable=SC2015,SC2001,SC2029  # SC2029: remote command strings are built locally on purpose
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${FI_STATE_DIR:-${REPO_ROOT}/.fresh-install}"
SIZE="s-4vcpu-16gb-amd"
HOURLY_USD="0.125"
REGION="${FI_REGION:-lon1}"
REPO_URL="https://github.com/EliasMarine/NetTap.git"
SSH_USER="tester"
ALLOWED_IMAGES=("ubuntu-24-04-x64" "ubuntu-22-04-x64")
CAPTURE_SERVICES=("zeek-live" "suricata-live" "pcap-capture")
INSTALL_DEADLINE_S=3600
DELETE_WAIT_S="${FI_DELETE_WAIT_S:-300}"
POLL_S="${FI_POLL_S:-5}"
SSH_POLL_S="${FI_SSH_POLL_S:-30}"  # waits that may open a new SSH connection each try
COMPOSE="sudo docker compose -f docker/docker-compose.yml"

FAILS=0

die() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "   PASS  $*"; }
fail() { echo "   FAIL  $*"; FAILS=$((FAILS + 1)); }
step() { echo ""; echo "→ $*"; }

# ---------------------------------------------------------------------------
# Manifest: one file per run, appended KEY='value' lines (a later line wins when sourced)
# ---------------------------------------------------------------------------

manifest_set() {
    printf "%s='%s'\n" "$1" "$2" >> "${RUN_DIR}/manifest.env"
}

valid_run_id() {
    [[ "$1" =~ ^[0-9]{8}t[0-9]{6}z-u(2204|2404)$ ]]
}

load_run() {
    local run="${1:-}"
    valid_run_id "$run" || die "not a run ID: '${run}' (see: $0 status)"
    RUN_DIR="${STATE_DIR}/${run}"
    [[ -f "${RUN_DIR}/manifest.env" ]] || die "no manifest for run ${run}"
    ACCOUNT_UUID="" RUN_TAG="" KEY_ID="" FW_ID="" DROPLET_ID="" DROPLET_IP="" SHA=""
    # shellcheck source=/dev/null
    source "${RUN_DIR}/manifest.env"
    # Every lookup and delete selects by this tag/name, so it must be this run's and never empty
    [[ "$RUN_TAG" == "nettap-fi-${run}" ]] || die "manifest RUN_TAG '${RUN_TAG}' is not nettap-fi-${run}"
}

current_account() {
    doctl account get --format UUID --no-header 2>/dev/null
}

check_account() {
    local now
    now="$(current_account)"
    [[ -n "$ACCOUNT_UUID" && "$now" == "$ACCOUNT_UUID" ]]
}

check_droplet() {
    local out tags ip
    out="$(doctl compute droplet get "$DROPLET_ID" --format Tags,PublicIPv4 --no-header 2>/dev/null)" \
        || die "droplet ${DROPLET_ID} not found"
    tags="$(awk '{print $1}' <<< "$out")"
    ip="$(awk '{print $2}' <<< "$out")"
    [[ ",${tags}," == *",${RUN_TAG},"* ]] || die "droplet ${DROPLET_ID} does not carry ${RUN_TAG}"
    [[ "$ip" == "$DROPLET_IP" ]] || die "droplet ${DROPLET_ID} IP ${ip} != manifest ${DROPLET_IP}"
}

require_run() {
    load_run "$1"
    check_account || die "doctl account is not the one that created run $1"
    [[ -n "$DROPLET_ID" ]] || die "run $1 has no droplet"
    check_droplet
}

# One shared connection per droplet, so the polling loops don't open a new SSH connection every few
# seconds. The socket lives in /tmp because a Unix socket path must stay under 104 bytes.
ssh_opts() {  # sets SSH_OPTS (macOS ships bash 3.2: no mapfile)
    SSH_OPTS=(-i "${RUN_DIR}/id_ed25519" -o "UserKnownHostsFile=${RUN_DIR}/known_hosts"
        -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes
        -o ServerAliveInterval=15 -o ControlMaster=auto -o "ControlPath=/tmp/nettap-fi-%C"
        -o ControlPersist=15m)
    # FI_JUMP=<ssh host>: reach the droplet through another machine with the same public IP, when
    # something on this one (a filtering network extension) drops the direct connection.
    if [[ -n "${FI_JUMP:-}" ]]; then SSH_OPTS+=(-o "ProxyJump=${FI_JUMP}"); fi
}

rssh() {
    ssh_opts
    ssh "${SSH_OPTS[@]}" "${SSH_USER}@${DROPLET_IP}" "$@"
}

# wait_until <seconds> <description> <command…>   (wait_ssh_until: the same, polling every SSH_POLL_S)
wait_until() {
    local deadline=$(( SECONDS + $1 )) what="$2" every="${WAIT_EVERY:-$POLL_S}"
    shift 2
    until "$@" >/dev/null 2>&1; do
        (( SECONDS >= deadline )) && { echo "   timed out waiting for: ${what}"; return 1; }
        sleep "$every"
    done
}

wait_ssh_until() { WAIT_EVERY="$SSH_POLL_S" wait_until "$@"; }

# ---------------------------------------------------------------------------
# up
# ---------------------------------------------------------------------------

user_data() {
    cat <<EOF
#cloud-config
users:
  - name: ${SSH_USER}
    groups: [sudo]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
      - $(cat "${RUN_DIR}/id_ed25519.pub")
EOF
}

create_key() {
    ssh-keygen -q -t ed25519 -N "" -C "$RUN_TAG" -f "${RUN_DIR}/id_ed25519" || return 1
    KEY_ID="$(doctl compute ssh-key import "$RUN_TAG" --public-key-file "${RUN_DIR}/id_ed25519.pub" \
        --format ID --no-header)" || return 1
    manifest_set KEY_ID "$KEY_ID"
}

create_firewall() {
    local myip="$1" any="address:0.0.0.0/0,address:::/0"
    doctl compute tag create "$RUN_TAG" >/dev/null || return 1
    FW_ID="$(doctl compute firewall create --name "$RUN_TAG" --tag-names "$RUN_TAG" \
        --inbound-rules "protocol:tcp,ports:22,address:${myip}/32" \
        --outbound-rules "protocol:tcp,ports:all,${any} protocol:udp,ports:all,${any} protocol:icmp,${any}" \
        --format ID --no-header)" || return 1
    manifest_set FW_ID "$FW_ID"
}

create_droplet() {
    local image="$1" out
    user_data > "${RUN_DIR}/user-data.yaml"
    out="$(doctl compute droplet create "$RUN_TAG" --image "$image" --size "$SIZE" --region "$REGION" \
        --tag-names "$RUN_TAG" --ssh-keys "$KEY_ID" --user-data-file "${RUN_DIR}/user-data.yaml" \
        --wait --format ID,PublicIPv4 --no-header)" || return 1
    DROPLET_ID="$(awk '{print $1}' <<< "$out")"
    DROPLET_IP="$(awk '{print $2}' <<< "$out")"
    manifest_set DROPLET_ID "$DROPLET_ID"
    manifest_set DROPLET_IP "$DROPLET_IP"
}

verify_firewall() {
    local out
    out="$(doctl compute firewall get "$FW_ID" --format Tags,InboundRules --no-header)" || return 1
    [[ "$out" == *"$RUN_TAG"* && "$out" == *"ports:22"* && "$out" != *"0.0.0.0/0"* ]]
}

cmd_up() {
    local image="${1:-}" myip run short
    [[ " ${ALLOWED_IMAGES[*]} " == *" ${image} "* ]] || die "image must be one of: ${ALLOWED_IMAGES[*]}"
    short="u$(sed -E 's/ubuntu-([0-9]+)-([0-9]+)-x64/\1\2/' <<< "$image")"
    run="$(date -u +%Y%m%dt%H%M%Sz)-${short}"
    RUN_DIR="${STATE_DIR}/${run}"
    RUN_TAG="nettap-fi-${run}"
    mkdir -p "$RUN_DIR" && chmod 700 "$RUN_DIR"
    ACCOUNT_UUID="$(current_account)"
    [[ -n "$ACCOUNT_UUID" ]] || die "doctl is not logged in"
    SHA="${FI_SHA:-$(git -C "$REPO_ROOT" rev-parse origin/main)}"
    [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "commit under test must be a full SHA, got '${SHA}'"
    myip="$(curl -fsS --max-time 10 https://api.ipify.org)"
    [[ "$myip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "could not read this machine's public IPv4"
    for kv in "ACCOUNT_UUID=$ACCOUNT_UUID" "RUN=$run" "RUN_TAG=$RUN_TAG" "IMAGE=$image" "SHA=$SHA" \
              "REGION=$REGION" "SIZE=$SIZE"; do
        manifest_set "${kv%%=*}" "${kv#*=}"
    done
    trap 'echo "Interrupted: rolling back"; destroy_run; exit 130' INT TERM
    step "Creating key, tag, firewall and droplet for ${run} (${SIZE}, ${REGION}, \$${HOURLY_USD}/h)"
    { create_key && create_firewall "$myip" && create_droplet "$image"; } \
        || { echo "A create failed: reconciling and rolling back"; destroy_run; exit 1; }
    trap - INT TERM
    step "Waiting for SSH and cloud-init"
    wait_ssh_until 600 "SSH on ${DROPLET_IP}" rssh true || die "no SSH; run: $0 down ${run}"
    rssh 'sudo timeout 600 cloud-init status --wait' >/dev/null || die "cloud-init did not finish; run: $0 down ${run}"
    verify_firewall || die "firewall ${FW_ID} is not as expected; run: $0 down ${run}"
    echo ""
    echo "Run ${run} is up: droplet ${DROPLET_ID} at ${DROPLET_IP}, testing ${SHA:0:8}."
    echo "Next: $0 install ${run}"
    echo "Remove: $0 down ${run}"
}

# ---------------------------------------------------------------------------
# down / rollback: only what this run's manifest names, or carries this run's unique tag/name
# ---------------------------------------------------------------------------

# run_droplets: this run's droplet IDs, by manifest, tag and name (a create interrupted before its
# ID was saved still has the name). Fails if a lookup fails, so "can't tell" never reads as "none".
run_droplets() {
    local by_tag by_name
    by_tag="$(doctl compute droplet list --tag-name "$RUN_TAG" --format ID --no-header)" || return 1
    by_name="$(named_id droplet)" || return 1
    { [[ -n "$DROPLET_ID" ]] && echo "$DROPLET_ID"; echo "$by_tag"; echo "$by_name"; } | sort -u | grep . || true
}

live_droplets() {  # this run's droplets that DO still has; fails if a lookup fails
    local ids id
    ids="$(run_droplets)" || return 1
    for id in $ids; do droplet_gone "$id" || echo "$id"; done
}

nothing_left() {
    local d f k
    d="$(live_droplets)" && f="$(named_id firewall)" && k="$(named_id ssh-key)" || return 1
    [[ -z "${d}${f}${k}" ]]
}

named_id() {  # named_id <droplet|firewall|ssh-key>: the ID of the one named exactly RUN_TAG
    local out
    out="$(doctl compute "$1" list --format ID,Name --no-header)" || return 1
    awk -v n="$RUN_TAG" '$2 == n {print $1}' <<< "$out"
}

droplet_gone() {
    local out
    out="$(doctl compute droplet get "$1" --format ID --no-header 2>&1)" && return 1
    [[ "$out" == *"404"* || "$out" == *"not found"* ]]
}

destroy_run() {
    local left=0 id
    if ! check_account; then
        echo "CLEANUP REQUIRED: doctl is not on account ${ACCOUNT_UUID:-unknown}; switch back and rerun down."
        return 2
    fi
    local ids fws keys
    ids="$(run_droplets)" || { echo "CLEANUP REQUIRED: couldn't list this run's droplets; nothing deleted. Rerun: $0 down ${RUN:-<run>}"; return 2; }
    for id in $ids; do
        doctl compute droplet delete "$id" --force >/dev/null 2>&1
        wait_until "$DELETE_WAIT_S" "droplet ${id} deleted" droplet_gone "$id" || { echo "   droplet ${id} still exists"; left=1; }
    done
    if (( left )); then
        echo "CLEANUP REQUIRED: a droplet is still there, so its firewall was kept. Rerun: $0 down ${RUN:-<run>}"
        return 2
    fi
    fws="$(named_id firewall)" && keys="$(named_id ssh-key)" \
        || { echo "CLEANUP REQUIRED: couldn't list firewalls/keys. Rerun: $0 down ${RUN:-<run>}"; return 2; }
    for id in ${FW_ID:-} $fws; do
        doctl compute firewall delete "$id" --force >/dev/null 2>&1
    done
    for id in ${KEY_ID:-} $keys; do
        doctl compute ssh-key delete "$id" --force >/dev/null 2>&1
    done
    doctl compute tag delete "$RUN_TAG" --force >/dev/null 2>&1
    # DO's list endpoints lag a few seconds behind a delete
    if ! wait_until 120 "deletes to show in DO's lists" nothing_left; then
        echo "CLEANUP REQUIRED: something named ${RUN_TAG} is still there ($0 status)."
        return 2
    fi
    manifest_set DESTROYED "$(date -u +%FT%TZ)"
    echo "DESTROYED: ${RUN_TAG} (droplet, firewall, key and tag)."
}

cmd_down() {
    load_run "${1:-}"
    destroy_run
}

cmd_status() {
    local m
    for m in "${STATE_DIR}"/*/manifest.env; do
        [[ -f "$m" ]] || { echo "No runs."; return 0; }
        RUN_DIR="$(dirname "$m")"
        load_run "$(basename "$RUN_DIR")"
        if [[ -n "${DESTROYED:-}" ]]; then
            echo "${RUN}: destroyed ${DESTROYED}"
        elif ! check_account; then
            echo "${RUN}: other doctl account, can't check"
        else
            echo "${RUN}: live droplets [$(live_droplets | tr '\n' ' ')] ip ${DROPLET_IP:-none} — $0 down ${RUN}"
        fi
        DESTROYED=""
    done
}

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

# The wrapper the installer runs under: its status lands in ~/install.status and is the exit code.
install_wrapper_body() {
    cat <<'EOF'
cd "$HOME/NetTap" || { echo 90 > "$HOME/install.status"; exit 90; }
sudo scripts/install/install.sh --skip-bridge
rc=$?
echo "$rc" > "$HOME/install.status"
exit "$rc"
EOF
}

# The guide's mirror setup has the capture port unplugged while Ubuntu installs, so it has no IP.
# On a droplet, eth1 comes up with a VPC address: take it off and stop cloud-init re-adding it.
# DO's resolver sits on the VPC, so DNS moves to DO's public resolvers on eth0 (the management port,
# where a real box gets DNS from the router).
prepare_box() {
    rssh 'bash -s' <<'EOF'
set -u
echo 'network: {config: disabled}' | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg >/dev/null
sudo python3 - <<'PY'
import glob, yaml
for path in glob.glob("/etc/netplan/*.yaml"):
    doc = yaml.safe_load(open(path)) or {}
    eths = doc.get("network", {}).get("ethernets", {})
    eths.pop("eth1", None)
    if "eth0" in eths:
        eths["eth0"]["nameservers"] = {"addresses": ["67.207.67.2", "67.207.67.3"], "search": []}
    open(path, "w").write(yaml.safe_dump(doc))
PY
sudo resolvectl dns eth0 67.207.67.2 67.207.67.3
sudo resolvectl dns eth1 ''
sudo ip addr flush dev eth1
getent hosts github.com >/dev/null || { echo "DNS does not work after moving it to eth0"; exit 1; }
command -v tmux >/dev/null || sudo apt-get install -y -qq tmux
EOF
}

clone_repo() {
    rssh "rm -rf NetTap && git clone -q '${REPO_URL}' NetTap && git -C NetTap checkout -q '${SHA}' && git -C NetTap rev-parse HEAD" \
        | grep -qx "$SHA"
}

start_installer() {
    install_wrapper_body | rssh 'cat > run-install.sh' || return 1
    rssh "rm -f install.status; tmux new-session -d -s install -x 160 -y 48 \
        \"script -e -q -c 'bash run-install.sh' install.log; exec sleep 86400\""
}

# Answer the documented prompts as a user would; anything else that waits for input fails the run.
answer_prompts() {
    local deadline=$(( SECONDS + INSTALL_DEADLINE_S )) pane last="" still=0 blinked=0 wan=0
    while (( SECONDS < deadline )); do
        rssh 'test -f install.status' && return 0
        pane="$(rssh 'tmux capture-pane -p -t install' 2>/dev/null | grep -v '^[[:space:]]*$' | tail -1)"
        if (( ! blinked )) && [[ "$pane" == *"Blink a NIC's LEDs"* ]]; then
            rssh "tmux send-keys -t install n Enter"; blinked=1; echo "   answered: no blink"
        elif (( ! wan )) && [[ "$pane" == *"Select WAN NIC"* ]]; then
            rssh "tmux send-keys -t install 1 Enter"; wan=1; echo "   answered: WAN = NIC 1"
        elif [[ "$pane" =~ (\?|\]|\)):[[:space:]]*$ && "$pane" == "$last" ]]; then
            still=$((still + 1))
            (( still >= 12 )) && { echo "   unexpected prompt: ${pane}"; return 1; }
        else
            still=0
        fi
        last="$pane"
        sleep 5
    done
    echo "   installer still running after ${INSTALL_DEADLINE_S}s"
    return 1
}

compose_rows() {  # "<service> <state> <health>" for every container compose knows about
    rssh "cd NetTap && ${COMPOSE} ps -a --format '{{.Service}} {{.State}} {{.Health}}'"
}

is_capture() { [[ " ${CAPTURE_SERVICES[*]} " == *" $1 "* ]]; }

# services_ready <need-capture 0|1> — every default-profile service exists and runs; the others healthy
services_ready() {
    local expected rows svc row
    expected="$(rssh "cd NetTap && ${COMPOSE} config --services")" || return 1
    rows="$(compose_rows)" || return 1
    for svc in $expected; do
        row="$(awk -v s="$svc" '$1 == s' <<< "$rows")"
        if is_capture "$svc"; then
            (( $1 )) || continue
            [[ "$row" == "$svc running"* ]] || { echo "$svc: ${row:-missing}"; return 1; }
        else
            [[ "$row" == "$svc running healthy" ]] || { echo "$svc: ${row:-missing}"; return 1; }
        fi
    done
}

post_install_checks() {
    local code_log code_cmd url
    if out="$(services_ready 0)"; then pass "every default service present, non-capture ones healthy"
    else fail "services: ${out}"; fi
    [[ "$(rssh "curl -s -o /dev/null -w '%{http_code}' http://localhost:8880/api/health")" == "200" ]] \
        && pass "daemon /api/health 200" || fail "daemon /api/health"
    url="$(rssh "curl -sk -L -o /dev/null -w '%{url_effective}' https://localhost/")"
    [[ "$url" == */setup* ]] && pass "unauthenticated https://localhost/ ends at /setup" || fail "/ ended at ${url}"
    code_log="$(sed -E 's/\x1b\[[0-9;]*[A-Za-z]//g' "${RUN_DIR}/install.log" \
        | grep -iA2 'setup code' | grep -oE '\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b' | head -1)"
    code_cmd="$(rssh 'sudo docker exec nettap-web cat /var/lib/nettap-web/setup-code' 2>/dev/null | tr -d '[:space:]')"
    (umask 077; printf '%s' "$code_cmd" > "${RUN_DIR}/setup-code")  # the wizard and the second-admin check use it
    if [[ -n "$code_cmd" && "$code_log" == "$code_cmd" ]]; then pass "installer printed the setup code; the documented command agrees"
    else fail "setup code: installer printed ${code_log:+one}${code_log:-none}, command gave ${code_cmd:+one}${code_cmd:-none}, and they differ"; fi
}

check_install_status() {
    [[ "$1" == "0" ]] && pass "install.sh --skip-bridge exited 0" || fail "install.sh exit status ${1:-missing}"
}

cmd_install() {
    local rc started=$SECONDS
    require_run "${1:-}"
    step "Preparing the box (capture port without an IP, as in the guide)"
    prepare_box || die "box preparation failed"
    step "Cloning ${SHA:0:8}"
    clone_repo || die "clone or checkout of ${SHA} failed"
    step "Starting the documented install in tmux (watch it: $0 watch ${1})"
    start_installer || die "could not start the installer"
    answer_prompts
    rc="$(rssh 'cat install.status 2>/dev/null')"
    rssh 'cat install.log' > "${RUN_DIR}/install.log"
    rssh 'sudo docker ps -a' > "${RUN_DIR}/docker-ps-a.txt" 2>&1
    step "Result"
    echo "   installer exit status: ${rc:-none}, $(( (SECONDS - started) / 60 )) min"
    check_install_status "$rc"
    post_install_checks
    finish
}

# ---------------------------------------------------------------------------
# watch / tunnel
# ---------------------------------------------------------------------------

cmd_watch() {
    require_run "${1:-}"
    ssh_opts
    exec ssh -t "${SSH_OPTS[@]}" "${SSH_USER}@${DROPLET_IP}" tmux attach -r -t install
}

cmd_tunnel() {
    require_run "${1:-}"
    # Port 443 keeps the browser's Origin equal to what nginx/SvelteKit rebuild (CSRF). macOS lets a
    # normal user bind 443 only on 0.0.0.0: FI_TUNNEL_BIND=0.0.0.0 then also opens it to the LAN.
    local bind="${FI_TUNNEL_BIND:-127.0.0.1}"
    echo "Open https://localhost/ (Ctrl-C to close the tunnel; listening on ${bind}:443)."
    ssh_opts
    # Its own connection: a shared one would ask the master process to bind the port
    exec ssh -N -o ExitOnForwardFailure=yes -o ControlMaster=no -o ControlPath=none "${SSH_OPTS[@]}" \
        -L "${bind}:443:localhost:443" "${SSH_USER}@${DROPLET_IP}"
}

# ---------------------------------------------------------------------------
# snapshot / after-wizard
# ---------------------------------------------------------------------------

# The wizard's effective settings as sorted KEY=VALUE lines (no secrets).
snapshot() {
    local d="docker exec nettap-storage-daemon cat /opt/nettap/data"
    {
        rssh "sudo ${d}/capture-mode.conf" | grep -E '^[A-Z_]+=' | sed 's/^/conf./'
        rssh "sudo ${d}/.env" | grep -E '^(CAPTURE_MODE|CAPTURE_INTERFACE|MANAGEMENT_INTERFACE|RETENTION_(HOT|WARM|COLD)|(DISK|EMERGENCY)_THRESHOLD_PERCENT)=' \
            | sed 's/^/env./'
        rssh "sudo ${d}/retention.json" \
            | jq -r '(.retention, .thresholds) | to_entries[] | "retention.\(.key)=\(.value)"'
        rssh 'ip -j addr show dev eth1' | jq -r '.[0] |
            "eth1.up=\(.flags | index("UP") != null)",
            "eth1.promisc=\(.flags | index("PROMISC") != null)",
            "eth1.ipv4=\([.addr_info[] | select(.family == "inet")] | length)",
            "eth1.global_ipv6=\([.addr_info[] | select(.family == "inet6" and .scope == "global")] | length)"'
    } | sort
}

# expect_in <snapshot-file> — every line of expected-settings.txt is in the snapshot
expect_in() {
    local missing
    missing="$(grep -vxF -f "$1" "${RUN_DIR}/expected-settings.txt")"
    [[ -z "$missing" ]] || { echo "${missing}" | sed 's/^/     not as chosen: /'; return 1; }
}

boot_id() { rssh 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null; }

new_boot() { local b; b="$(boot_id)" && [[ -n "$b" && "$b" != "$1" ]]; }

reboot_box() {
    local before
    before="$(boot_id)"
    [[ -n "$before" ]] || return 1
    rssh 'sudo systemctl reboot' >/dev/null 2>&1
    sleep 20
    wait_ssh_until 600 "a new boot ID" new_boot "$before"
}

auth_checks() {
    local loc code users
    # shellcheck source=/dev/null
    source "${RUN_DIR}/admin.env"
    loc="$(rssh "curl -sk -o /dev/null -w '%{redirect_url}' https://localhost/setup")"
    [[ "$loc" == */login* ]] && pass "cookie-free /setup sends you to /login" || fail "/setup redirect: ${loc:-none}"
    # The password goes over stdin, never on a command line.
    printf 'username=%s&password=%s' "$ADMIN_USER" "$ADMIN_PASS" | rssh "rm -f jar; curl -sk -c jar \
        -H 'Origin: https://localhost' --data-binary @- -o /dev/null https://localhost/login"
    rssh "grep -q nettap_token jar" && pass "login form sets the auth cookie" || fail "login set no auth cookie"
    code="$(rssh "curl -sk -b jar -o /dev/null -w '%{http_code}' https://localhost/alerts")"
    [[ "$code" == "200" ]] && pass "the cookie opens a protected page" || fail "protected page with cookie: ${code}"
    # A non-browser form POST gets SvelteKit's JSON answer, e.g. {"type":"redirect",…,"location":"/login"}
    loc="$(printf 'setupCode=%s&username=second&password=x&confirmPassword=x' "$(cat "${RUN_DIR}/setup-code" 2>/dev/null)" \
        | rssh "curl -sk -H 'Origin: https://localhost' --data-binary @- 'https://localhost/setup?/createAdmin'")"
    users="$(rssh "sudo docker exec nettap-web cat /var/lib/nettap-web/users.json" | grep -c '"username"')"
    if [[ "$loc" == *'"location":"/login"'* && "$users" == "1" ]]; then
        pass "the used setup code can't create a second admin (still 1 account)"
    else
        fail "second admin: reply '${loc:0:120}', accounts ${users}"
    fi
    rssh 'rm -f jar'
}

cmd_after_wizard() {
    require_run "${1:-}"
    [[ -s "${RUN_DIR}/expected-settings.txt" && -s "${RUN_DIR}/admin.env" ]] \
        || die "write expected-settings.txt and admin.env in ${RUN_DIR} first"
    step "Before the reboot"
    snapshot > "${RUN_DIR}/settings-before.txt"
    expect_in "${RUN_DIR}/settings-before.txt" && pass "settings are what the wizard chose" || fail "settings before reboot"
    if out="$(services_ready 1)"; then pass "capture services running before any reboot"; else fail "before reboot: ${out}"; fi
    step "Rebooting"
    reboot_box && pass "rebooted (new boot ID)" || { fail "no new boot ID"; finish; }
    wait_ssh_until 600 "services back" services_ready 1 && pass "every service back" \
        || fail "after reboot: $(services_ready 1)"
    step "After the reboot"
    snapshot > "${RUN_DIR}/settings-after.txt"
    expect_in "${RUN_DIR}/settings-after.txt" && pass "settings still what the wizard chose" || fail "settings after reboot"
    diff -u "${RUN_DIR}/settings-before.txt" "${RUN_DIR}/settings-after.txt" >/dev/null \
        && pass "nothing changed across the reboot" || fail "settings changed across the reboot (see settings-*.txt)"
    step "Login"
    auth_checks
    finish
}

finish() {
    echo ""
    if (( FAILS )); then echo "=== ${FAILS} check(s) failed ==="; else echo "=== All checks passed ==="; fi
    echo "Evidence: ${RUN_DIR}"
    echo "Remove when done (\$${HOURLY_USD}/h while it runs): $0 down ${RUN}"
    exit $(( FAILS > 0 ))
}

main() {
    local cmd="${1:-}"
    shift || true
    case "$cmd" in
        up)           cmd_up "$@" ;;
        install)      cmd_install "$@" ;;
        watch)        cmd_watch "$@" ;;
        tunnel)       cmd_tunnel "$@" ;;
        snapshot)     require_run "${1:-}"; snapshot ;;
        ssh)          require_run "${1:-}"; shift; rssh "$@" ;;
        after-wizard) cmd_after_wizard "$@" ;;
        down)         cmd_down "$@" ;;
        status)       cmd_status ;;
        *)            sed -n '2,20p' "$0"; exit 2 ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
