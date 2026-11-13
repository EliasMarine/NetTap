#!/usr/bin/env bash
# Check NET-217 (the OpenSearch bootstrap stops the run when it fails, and keeps the password
# out of every process's arguments) and NET-177 (installer sizes in decimal GB) on the device.
#
# Only install-time scripts changed, so nothing is rebuilt, recreated or restarted. The script
# runs deploy-malcolm.sh's real bootstrap functions against the running stack through
# guarded_docker, which lets through only the bootstrap's reads and the create-only Arkime
# marker: whatever state the stack is in, this check writes nothing.
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-malcolm-bootstrap.sh
# To test a branch first: git checkout <branch> && git pull, then BRANCH=<branch> bash …
# shellcheck disable=SC2033  # sudo runs the docker binary; docker() exists only in the bootstrap subshells
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
DEPLOY="scripts/install/deploy-malcolm.sh"
CURLRC="/var/local/curlrc/.opensearch.primary.curlrc"
FAILED=0
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

os_get() {  # os_get <path>: GET against OpenSearch from inside its container
    sudo docker exec nettap-opensearch curl -s --max-time 15 --config "$CURLRC" \
        --cacert /usr/share/opensearch/config/certs/ca.crt --insecure "https://localhost:9200$1"
}

os_code() {  # os_code <path>: the HTTP status of that GET
    sudo docker exec nettap-opensearch curl -s --max-time 15 --config "$CURLRC" \
        --cacert /usr/share/opensearch/config/certs/ca.crt --insecure \
        -o /dev/null -w '%{http_code}' "https://localhost:9200$1"
}

template_hash() { os_get "/_index_template/malcolm_template?filter_path=index_templates.index_template._meta.hash"; }
template_patterns() { os_get "/_index_template/malcolm_template?filter_path=index_templates.index_template.index_patterns"; }
marker_patterns() { os_get "/_template/arkime_sessions3_template?filter_path=*.index_patterns"; }

stack_state() {  # "id name started-at" of the two containers the bootstrap could touch
    sudo docker inspect --format '{{.Id}} {{.Name}} {{.State.StartedAt}}' nettap-opensearch nettap-dashboards-helper
}

# The bootstrap's docker in this check: never recreates a container, pushes security config or
# overwrites a template, even if the stack changed after the baseline (NET-217 device check).
# OLD CODE START — NET-217 review: a denylist misses writes it didn't list (-XPUT, compose restart)
# guarded_docker() {
#     if [[ "${1:-}" == compose && " $* " == *" up "* ]]; then
#         echo "   (refused: docker compose … up; this check recreates nothing)"
#         return 0
#     fi
#     if [[ "$*" == *securityadmin* || ( "$*" == *"-X PUT"* && "$*" != *"create=true"* ) ]]; then
#         echo "   (refused a write: this check changes nothing)"
#         return 1
#     fi
#     sudo docker "$@"
# }
# OLD CODE END
# True for the calls guarded_docker lets through: preflight's docker checks, the bootstrap's
# reads inside opensearch and dashboards-helper, and the create-only Arkime marker, which
# OpenSearch refuses when a template already exists.
_docker_allowed() {
    local a writes="" url=""
    case "$*" in "info" | "compose version") return 0 ;; esac
    [[ "${1:-} ${2:-} ${4:-} ${5:-}" == "compose -f exec -T" ]] || return 1
    case "${6:-} ${7:-}" in
        "dashboards-helper jq" | "dashboards-helper cat") return 0 ;;
        "dashboards-helper find")
            for a in "${@:8}"; do
                case "$a" in -delete | -exec* | -ok* | -fprint* | -fls) return 1 ;; esac
            done
            return 0 ;;
        "opensearch curl" | "dashboards-helper curl") ;;
        *) return 1 ;;
    esac
    for a in "${@:8}"; do
        case "$a" in
            https://*) url="$a" ;;
            -X* | --request* | -d* | --data* | -T* | --upload-file* | -F* | --form* | --json* | -[!-]*[XdTF]*)
                writes+="$a " ;;
        esac
    done
    [[ -z "$writes" ]] && return 0
    [[ "$writes" == "-X -d " && " ${*:8} " == *" -X PUT "* && " ${*:8} " == *" -d @- "* \
        && "$url" == "https://opensearch:9200/_template/arkime_sessions3_template?create=true" ]]
}

guarded_docker() {
    if [[ $# -eq 6 && "$1 $2 $4 $5 $6" == "compose -f up -d dashboards-helper" ]]; then
        echo "   (skipped docker compose up: this check recreates nothing)"
        return 0
    fi
    if ! _docker_allowed "$@"; then
        echo "   (refused docker ${*:1:7} …: this check changes nothing)"
        return 1
    fi
    sudo docker "$@"
}

bootstrap_run() {  # the bootstrap a normal install runs, against the live stack
    # shellcheck source=../install/deploy-malcolm.sh
    source "$DEPLOY"
    docker() { guarded_docker "$@"; }
    bootstrap_opensearch_security
    bootstrap_index_templates
}

forced_failure_run() {  # the template bootstrap without the curlrc: every call gets 401
    # shellcheck source=../install/deploy-malcolm.sh
    source "$DEPLOY"
    docker() { guarded_docker "$@"; }
    # shellcheck disable=SC2329  # called by bootstrap_index_templates
    _helper_curl() {
        docker compose -f "$COMPOSE_FILE" exec -T dashboards-helper \
            curl --insecure --silent --connect-timeout 10 --max-time 60 "$@"
    }
    bootstrap_index_templates
}

echo "=== Check: Malcolm bootstrap and decimal sizes, NET-217 + NET-177 ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was run"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Baseline (nothing runs unless the stack is already healthy)..."
AUTH=$(os_code "/_cluster/health")
PATTERNS=$(template_patterns)
MARKER=$(marker_patterns)
HASH=$(template_hash)
expect "OpenSearch login (malcolm_internal)" "$AUTH" 200
case "$PATTERNS" in *'"arkime_sessions3-*"'*) rc=0 ;; *) rc=1 ;; esac
check "malcolm_template targets arkime_sessions3-*" "$rc" "${PATTERNS:-missing}"
case "$MARKER" in *index_patterns*) rc=0 ;; *) rc=1 ;; esac
check "arkime_sessions3_template present" "$rc" "${MARKER:-missing}"
case "$HASH" in *'"hash"'*) rc=0 ;; *) rc=1 ;; esac
check "malcolm_template carries Malcolm's _meta.hash" "$rc" "${HASH:-none}"
if [ "$FAILED" -ne 0 ]; then
    echo "   ✗ Stopping: the bootstrap would try to repair this box. Fix it first:"
    echo "     bash scripts/remote/fix-opensearch.sh"
    exit 1
fi
stack_state > "$WORK/stack.before"
# Read through a pipe into a variable: never printed, never in an argument, never on disk
PW=$(sudo docker exec nettap-dashboards-helper cat "$CURLRC" 2>/dev/null | sed -n 's/^user: *"[^:]*:\(.*\)"$/\1/p')
if [ "${#PW}" -lt 8 ]; then
    echo "   ✗ Could not read the OpenSearch password to look for it in ps — stopping"
    exit 1
fi
echo "   ✓ opensearch and dashboards-helper start times recorded; password read for the ps check"
echo ""

echo "→ Step 3: Run the bootstrap while sampling every process's arguments..."
( bootstrap_run ) < /dev/null > "$WORK/run.log" 2>&1 &
PID=$!
SAMPLES=0
LEAKS=0
SEEN=0
while kill -0 "$PID" 2>/dev/null; do
    S=$(ps -ww -eo args 2>/dev/null)
    SAMPLES=$((SAMPLES + 1))
    case "$S" in *"$PW"*) LEAKS=$((LEAKS + 1)) ;; esac
    case "$S" in *"curl --config $CURLRC"*) SEEN=$((SEEN + 1)) ;; esac
    sleep 0.2
done
wait "$PID"
RC=$?
unset PW S
sed 's/^/     /' "$WORK/run.log"
expect "bootstrap exit status" "$RC" 0
grep -q "Authentication verified" "$WORK/run.log"
check "auth verified by bootstrap_opensearch_security" "$?" "no securityadmin.sh needed"
grep -q "left as Malcolm set it" "$WORK/run.log"
check "malcolm_template kept as Malcolm tuned it" "$?"
expect "ps samples showing the password" "$LEAKS" 0
if [ "$SEEN" -gt 0 ]; then rc=0; else rc=1; fi
check "the sampler saw the bootstrap's curl calls" "$rc" "$SEEN of $SAMPLES samples"
expect "OpenSearch login after the run" "$(os_code "/_cluster/health")" 200
expect "malcolm_template unchanged" "$(template_hash)" "$HASH"
expect "arkime_sessions3_template unchanged" "$(marker_patterns)" "$MARKER"
echo ""

echo "→ Step 4: Forced failure (no credentials, so OpenSearch refuses everything)..."
# stdin from /dev/null: docker compose exec would otherwise read the terminal
( forced_failure_run ) < /dev/null > "$WORK/forced.log" 2>&1
RC=$?
sed 's/^/     /' "$WORK/forced.log"
if [ "$RC" -ne 0 ]; then rc=0; else rc=1; fi
check "the run stops with a nonzero exit" "$rc" "exit $RC"
grep -q "Reading malcolm_template answered HTTP 401" "$WORK/forced.log"
check "each pass stopped at the refused read" "$?"
grep -q "Index template bootstrap failed after 3 attempts" "$WORK/forced.log"
check "it says what failed and how to retry" "$?"
expect "malcolm_template still unchanged" "$(template_hash)" "$HASH"
expect "arkime_sessions3_template still unchanged" "$(marker_patterns)" "$MARKER"
echo ""

echo "→ Step 5: Decimal GB (NET-177)..."
# check_disk alone: run standalone, validate-hardware.sh stops at the first warning (RAM on the G11)
HW=$(bash -c 'source scripts/install/validate-hardware.sh; check_disk || true' 2>&1 | grep -o 'Disk: [0-9]* GB total' || true)
TOTAL_GB=$(df -B1 / | awk 'NR==2 {print int($2 / 1e9)}')
expect "validate-hardware total, in GB of 10^9 bytes" "$HW" "Disk: ${TOTAL_GB} GB total"
# shellcheck source=../install/deploy-malcolm.sh
( source "$DEPLOY"; docker() { guarded_docker "$@"; }; preflight ) < /dev/null > "$WORK/preflight.log" 2>&1
RC=$?
if [ "$RC" -eq 0 ] && ! grep -q "free disk space" "$WORK/preflight.log"; then rc=0; else rc=1; fi
check "deploy-malcolm.sh preflight passes" "$rc" "$(tail -n 1 "$WORK/preflight.log")"
echo ""

echo "→ Step 6: Wait for OpenSearch and dashboards-helper to report healthy..."
for i in $(seq 1 30); do
    OS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-opensearch 2>/dev/null || echo "unknown")
    DH=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-dashboards-helper 2>/dev/null || echo "unknown")
    if [ "$OS" = "healthy" ] && [ "$DH" = "healthy" ]; then break; fi
    echo "   waiting... opensearch=$OS dashboards-helper=$DH ($i/30)"
    sleep 5
done
expect "nettap-opensearch" "$OS" healthy
expect "nettap-dashboards-helper" "$DH" healthy
stack_state > "$WORK/stack.after"
if cmp -s "$WORK/stack.before" "$WORK/stack.after"; then rc=0; else rc=1; fi
check "opensearch and dashboards-helper not recreated or restarted" "$rc" "IDs and start times as before"
echo ""

echo "→ Step 7: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Check complete: all ✓ ==="
else
    echo "=== Finished with ✗ lines above — paste this output back ==="
fi
