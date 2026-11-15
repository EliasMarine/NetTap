#!/usr/bin/env bash
# Deploy round 4 of the 2026-11-14 bug fixes and check them on the box:
#   NET-287 (daemon, web, scripts) NetTap never adopts, changes or deletes a br0 it didn't make
#   NET-290 (web)                  only the wizard's exact /api/setup calls are open before the
#                                  first admin (the box already has an admin, so CI's first-run
#                                  tests cover it; here the web only has to come back healthy)
#
# The NET-287 check is live, and safe on a mirror-mode box: if no br0 exists, it adds an EMPTY,
# DOWN bridge called br0 (no ports, no address) through the daemon container, which uses the host
# network. Then it makes read-only calls (readiness, the wizard's preview, and the installer's
# shell check), first as a bridge NetTap didn't make, then marked with NetTap's alias. It removes
# the bridge again on exit, even if a check fails. It never calls create, teardown or bypass. If a
# br0 already exists, the live check is skipped and that bridge is left alone.
#
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and counts, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-triage-fixes-4-2026-11-14.sh
# To try a branch before it merges: BRANCH=fix/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
FAILED=0
TEST_BRIDGE_CREATED="false"

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

# Host network commands through the daemon container (network_mode: host)
host_ip() { sudo docker exec nettap-storage-daemon ip "$@"; }

remove_test_bridge() {
    if [ "$TEST_BRIDGE_CREATED" = "true" ]; then
        host_ip link del br0 >/dev/null 2>&1 || true
        TEST_BRIDGE_CREATED="false"
    fi
}
trap remove_test_bridge EXIT

# Run a Python check inside the daemon container with the shared token as `call(method, path, body)`.
daemon_py() {  # daemon_py PYTHON_SNIPPET
    sudo docker exec -e SNIPPET="$1" nettap-storage-daemon python3 -c '
import json, os, urllib.error, urllib.request
token = open("/run/nettap-auth/daemon-token").read().strip()
def call(method, path, body=None):
    data = None if body is None else body.encode()
    req = urllib.request.Request("http://localhost:8880" + path, data=data, method=method,
                                 headers={"X-NetTap-Daemon-Token": token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
try:
    exec(os.environ["SNIPPET"])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])' 2>/dev/null || echo "FAIL could not run inside the daemon container"
}

result() {  # result LABEL OUTPUT  (OUTPUT starting with OK passes)
    local rc
    case "$2" in OK*) rc=0 ;; *) rc=1 ;; esac
    check "$1" "$rc" "$2"
}

# The installer's shell check, run as the normal user against the host (read-only)
shell_owned() {
    if bash -c 'source "$1/scripts/common.sh" >/dev/null 2>&1; nettap_bridge_owned br0' _ "$REPO_DIR"; then
        echo owned
    else
        echo foreign
    fi
}

READINESS='
status, body = call("GET", "/api/bridge/readiness")
data = json.loads(body) if status == 200 else {}
exists = next((c for c in data.get("checks", []) if c.get("name") == "bridge_exists"), {})
'
PREVIEW='
pstatus, pbody = call("POST", "/api/setup/bridge/preview",
                      json.dumps({"wan_interface": "nettapt0", "lan_interface": "nettapt1"}))
perror = json.loads(pbody).get("error", "") if pbody else ""
'

echo "=== Deploy: bug fixes, round 4, 2026-11-14 ($BRANCH) ==="
echo ""

echo "→ Step 1: Update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the daemon and web containers..."
# A failed build must stop here: recreating would bring back the OLD images unnoticed.
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the daemon and web containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 4: Wait for both to become healthy..."
WEB="unknown"; DAEMON="unknown"
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    [ "$WEB" = "healthy" ] && [ "$DAEMON" = "healthy" ] && break
    echo "   waiting... web=$WEB daemon=$DAEMON ($i/30)"
    sleep 5
done
if [ "$WEB" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-web health" "$rc" "$WEB"
if [ "$DAEMON" = "healthy" ]; then rc=0; else rc=1; fi
check "nettap-storage-daemon health" "$rc" "$DAEMON"
echo ""

echo "→ Step 5: NET-287, a br0 NetTap didn't make is refused (live, read-only)..."
if host_ip link show br0 >/dev/null 2>&1; then
    echo "   - A br0 already exists on this box, so the live check is skipped and it is left alone."
elif ! host_ip link add br0 type bridge; then
    check "add a temporary empty br0" 1 "ip link add failed"
else
    TEST_BRIDGE_CREATED="true"
    echo "   (temporary empty, down br0 added; it is removed at the end)"
    result "readiness says the bridge isn't NetTap's" "$(daemon_py "$READINESS
ok = status == 200 and data.get('ready') is False and exists.get('passed') is False \
    and \"didn't set up\" in data.get('message', '')
print('OK' if ok else 'FAIL', status, 'bridge_exists passed=' + str(exists.get('passed')))")"
    result "the wizard's preview refuses it (400)" "$(daemon_py "$PREVIEW
ok = pstatus == 400 and \"didn't set up\" in perror and 'alias nettap' in perror
print('OK' if ok else 'FAIL', pstatus, perror[:60])")"
    OWNED=$(shell_owned)
    if [ "$OWNED" = "foreign" ]; then rc=0; else rc=1; fi
    check "the installer's shell check calls it foreign" "$rc" "$OWNED"

    echo "   (marking the test bridge with NetTap's alias)"
    if host_ip link set br0 alias nettap; then
        result "readiness now treats it as NetTap's" "$(daemon_py "$READINESS
ok = status == 200 and exists.get('passed') is True and \"didn't set up\" not in data.get('message', '')
print('OK' if ok else 'FAIL', status, 'bridge_exists passed=' + str(exists.get('passed')))")"
        result "the preview no longer calls it foreign" "$(daemon_py "$PREVIEW
ok = pstatus == 400 and \"didn't set up\" not in perror
print('OK' if ok else 'FAIL', pstatus, perror[:60])")"
        OWNED=$(shell_owned)
        if [ "$OWNED" = "owned" ]; then rc=0; else rc=1; fi
        check "the installer's shell check calls it NetTap's" "$rc" "$OWNED"
    else
        check "mark the test bridge with the alias" 1 "ip link set alias failed"
    fi

    remove_test_bridge
    if host_ip link show br0 >/dev/null 2>&1; then rc=1; else rc=0; fi
    check "temporary br0 removed" "$rc"
fi
echo ""

echo "→ Step 6: NET-290, the web still answers (first-run paths are covered by CI)..."
CODE=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health" || true)
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/health answers" "$rc" "$CODE"
CODE=$(curl -sk -o /dev/null -X POST --max-time 20 -H 'Content-Type: application/json' -d '{}' -w '%{http_code}' "$BASE/api/setup/configure" || true)
if [ "$CODE" = "401" ]; then rc=0; else rc=1; fi
check "signed-out POST /api/setup/configure is 401" "$rc" "$CODE"
echo ""

echo "→ Step 7: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 5m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 8: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
