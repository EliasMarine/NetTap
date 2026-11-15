#!/usr/bin/env bash
# Deploy NET-291 and check it on the box: the daemon checks update component names before it
# uses them.
#   - Rollback gives one answer for any name it can't roll back, whether or not a path by that
#     name exists (it used to tell a caller which paths exist).
#   - Apply refuses a non-object body, more than 16 names, or a name NetTap can't update, before
#     anything is queued or recorded in the update history.
#   - The web proxies refuse a non-object body (covered by CI; the box only checks that a
#     signed-out call is still refused).
#
# Every apply call here is one the daemon must refuse, so no real update ever starts.
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and counts, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-update-names-net291.sh
# To try a branch before it merges: BRANCH=fix/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
BASE="https://localhost"
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

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

echo "=== Deploy: update component names are checked first (NET-291, $BRANCH) ==="
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

echo "→ Step 5: Rollback gives one answer whether or not the path exists..."
result "an existing path and a missing one get the same refusal" "$(daemon_py "
answers = {}
for name in ('../../../etc/passwd', '../../../nettap-no-such-path', '/etc/hostname', 'nettap-daemon'):
    status, body = call('POST', '/api/system/updates/rollback', json.dumps({'component': name}))
    answers[name] = (status, json.loads(body).get('message'))
same = len(set(answers.values())) == 1
status, message = next(iter(answers.values()))
ok = same and status == 404 and 'not supported' in (message or '')
print('OK' if ok else 'FAIL', status, repr(message), 'distinct answers=' + str(len(set(answers.values()))))")"
result "a non-object rollback body is a 400" "$(daemon_py "
status, _ = call('POST', '/api/system/updates/rollback', 'null')
print('OK' if status == 400 else 'FAIL', status)")"
echo ""

echo "→ Step 6: Apply refuses bad lists, and nothing reaches the history..."
result "17 names, an unknown name and a null body all get 400; history unchanged" "$(daemon_py "
_, before = call('GET', '/api/system/updates/history')
before = json.loads(before).get('count')
codes = [call('POST', '/api/system/updates/apply', body)[0] for body in (
    json.dumps({'components': ['zeek'] * 17}),
    json.dumps({'components': ['nettap-no-such-component']}),
    'null',
)]
_, after = call('GET', '/api/system/updates/history')
after = json.loads(after).get('count')
ok = codes == [400, 400, 400] and before == after
print('OK' if ok else 'FAIL', 'codes=' + ','.join(map(str, codes)), 'history', before, '->', after)")"
echo ""

echo "→ Step 7: The web proxies still need a session..."
for path in "/api/system/updates/apply" "/api/system/updates/rollback"; do
    CODE=$(curl -sk -o /dev/null -X POST --max-time 20 -H 'Content-Type: application/json' -d 'null' -w '%{http_code}' "$BASE$path" || true)
    if [ "$CODE" = "401" ]; then rc=0; else rc=1; fi
    check "signed-out POST $path is 401" "$rc" "$CODE"
done
echo ""

echo "→ Step 8: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 5m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
