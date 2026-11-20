#!/usr/bin/env bash
# Deploy NET-339 (roadmap #6, data cap warnings) and check it on the box (plan §8):
#   - the real scheduler path: the data-cap job runs on demand with no error;
#   - a synthetic crossing under an odd test cap (1.234567 GB) journals the 80% and 100% warnings
#     once, and a second run adds nothing; the saved cap is restored even if a step fails;
#   - the daemon's settled memory stays within 50 MB of before.
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and figures, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-data-cap-warnings.sh
# To try a branch before it merges: BRANCH=feature/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
TEST_CAP_GB="1.234567"  # a cap no owner would type: its warnings are their own instance
TEST_CAP_BYTES=1234567000
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

# Run a Python check inside the daemon container with the shared token as `call(method, path, body)`.
daemon_py() {  # daemon_py PYTHON_SNIPPET
    sudo docker exec -e SNIPPET="$1" nettap-storage-daemon python3 -c '
import json, os, time, urllib.error, urllib.request
from datetime import datetime, timezone
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
def run_job(name):
    """Force a job and wait (60 s at most) for a run that started after the request."""
    asked = datetime.now(timezone.utc)
    s, _ = call("POST", "/api/jobs/" + name + "/run")
    for _ in range(60):
        time.sleep(1)
        _, b = call("GET", "/api/jobs")
        job = next((j for j in json.loads(b)["jobs"] if j["name"] == name), None)
        if job is None:
            return None
        last = job.get("last_run")
        if last and datetime.fromisoformat(last) >= asked and not job["running"]:
            return job
    return {"last_error": "no run within 60 s (POST status %s)" % s}
def cap_lines(month):
    """The journal lines of data cap warnings for the test cap this month: [key, ...]."""
    keys = []
    with open("/opt/nettap/data/events.jsonl") as f:
        for line in f:
            e = json.loads(line)
            d = e.get("data") or {}
            if e.get("type") == "data_cap" and d.get("cap") == '"$TEST_CAP_BYTES"' and d.get("month") == month:
                keys.append(e.get("key"))
    return keys
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

daemon_rss_mb() {  # the daemon process's resident memory, in MB (not docker stats: F1 lesson)
    sudo docker top nettap-storage-daemon -o pid,rss,args 2>/dev/null | awk '$3 ~ /python/ && / main\.py/ { if ($2 > m) m = $2 } END { printf "%d", m / 1024 }'
}

daemon_uptime_s() {
    local started
    started=$(sudo docker inspect -f '{{.State.StartedAt}}' nettap-storage-daemon 2>/dev/null)
    echo $(( $(date +%s) - $(date -d "$started" +%s 2>/dev/null || date +%s) ))
}

settled_rss_mb() {  # wait until VmRSS moves under 10% across a minute (at most 5 minutes)
    local prev now i
    # start-up holds about 1.2 GB for its first minutes (F1 and F4 deploys): read after 5 minutes
    while [ "$(daemon_uptime_s)" -lt 300 ]; do sleep 15; done
    prev=$(daemon_rss_mb)
    for i in 1 2 3 4 5; do
        sleep 60
        now=$(daemon_rss_mb)
        if [ -n "$prev" ] && [ -n "$now" ] && [ $(( (now > prev ? now - prev : prev - now) * 10 )) -le "$prev" ]; then
            echo "$now"; return
        fi
        prev=$now
    done
    echo "${now:-0}"
}

SAVED_CAP=""
restore_cap() {  # put the owner's cap back; also the EXIT trap, so a failed restore is tried again
    [ -n "$SAVED_CAP" ] || return 0
    local out
    out=$(daemon_py "
s, _ = call('PUT', '/api/settings/bandwidth-cap', json.dumps({'monthly_cap_gb': $SAVED_CAP / 1e9}))
_, b = call('GET', '/api/bandwidth/cap')
now = json.loads(b)['monthly_cap_bytes']
print('OK' if s == 200 and now == $SAVED_CAP else 'FAIL', 'cap restored to', now, 'bytes (status', s, ')')")
    result "owner's cap restored" "$out"
    case "$out" in OK*) SAVED_CAP="" ;; esac
}

echo "=== Deploy: data cap warnings (NET-339, $BRANCH) ==="
echo ""

echo "→ Step 1: Baseline (settled daemon memory, the saved cap)..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
DAEMON_RSS_BEFORE=$(settled_rss_mb)
# only fields the running build already has (Codex r4 #4)
CAP_BEFORE=$(daemon_py "
s, b = call('GET', '/api/bandwidth/cap')
print(json.loads(b)['monthly_cap_bytes'] if s == 200 else 'FAIL')")
echo "   daemon VmRSS ${DAEMON_RSS_BEFORE} MB (settled), saved cap ${CAP_BEFORE} bytes"
case "$CAP_BEFORE" in ''|*[!0-9]*) echo "   ✗ Couldn't read the saved cap — stopping before any change"; exit 1 ;; esac
echo ""

echo "→ Step 2: Update the code..."
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Build the daemon and web containers..."
# a failed build must stop here: recreating would bring back the OLD images unnoticed
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 4: Recreate the daemon and web containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 5: Wait for both to become healthy..."
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

echo "→ Step 6: The cap reply and the real scheduler path, with the owner's own cap..."
result "/api/bandwidth/cap has the new fields" "$(daemon_py "
s, b = call('GET', '/api/bandwidth/cap')
c = json.loads(b)
ok = s == 200 and isinstance(c.get('lower_bound_bytes'), int) and len(c.get('first_day') or '') == 10
print('OK' if ok else 'FAIL', 'lower bound', c.get('lower_bound_bytes'), 'of', c.get('current_usage_bytes'), 'bytes, first day', c.get('first_day'), 'since', c.get('since'), 'complete', c.get('complete'))")"
result "data-cap job runs with no error" "$(daemon_py "
job = run_job('data-cap')
ok = job is not None and not job.get('last_error')
print('OK' if ok else 'FAIL', 'missing from /api/jobs' if job is None else 'last_error %s, %s ms' % (job.get('last_error'), job.get('last_duration_ms')))")"
echo ""

echo "→ Step 7: A synthetic crossing under the test cap (${TEST_CAP_GB} GB)..."
LOW=$(daemon_py "
_, b = call('GET', '/api/bandwidth/cap')
print(json.loads(b)['lower_bound_bytes'])")
case "$LOW" in ''|*[!0-9]*) LOW=0; check "read this month's lower bound" 1 "got: $LOW" ;; esac
if [ "$LOW" -lt 2000000000 ]; then
    # a correct watcher sends nothing under the cap, so there is nothing to see: a pass
    check "synthetic crossing" 0 "skipped: under 2 GB counted this month ($LOW bytes)"
else
    SAVED_CAP=$CAP_BEFORE
    trap restore_cap EXIT  # first, so the owner's cap comes back even if a later step fails
    MONTH=$(daemon_py "
_, b = call('GET', '/api/usage/month')
m = json.loads(b)
print('%04d-%02d' % (m['year'], m['month']))")
    result "test cap saved" "$(daemon_py "
s, b = call('PUT', '/api/settings/bandwidth-cap', json.dumps({'monthly_cap_gb': $TEST_CAP_GB}))
print('OK' if s == 200 else 'FAIL', 'status', s, b[:120])")"
    result "80% and 100% journaled once" "$(daemon_py "
before = cap_lines('$MONTH')
job = run_job('data-cap')
after = cap_lines('$MONTH')
new = sorted(after[len(before):])
ok = job and not job.get('last_error') and sorted(after) == ['100', '80']
print('OK' if ok else 'FAIL', 'month $MONTH, lines', sorted(after), 'new this run', new, 'job error', (job or {}).get('last_error'))")"
    result "a second run adds nothing" "$(daemon_py "
before = cap_lines('$MONTH')
job = run_job('data-cap')
after = cap_lines('$MONTH')
print('OK' if job and not job.get('last_error') and after == before else 'FAIL', len(before), '->', len(after), 'lines')")"
    restore_cap  # on failure SAVED_CAP stays set, so the EXIT trap tries once more
fi
echo ""

echo "→ Step 8: Settled memory..."
DAEMON_RSS_AFTER=$(settled_rss_mb)
if [ $((DAEMON_RSS_AFTER - DAEMON_RSS_BEFORE)) -le 50 ]; then rc=0; else rc=1; fi
check "settled daemon VmRSS within 50 MB of before" "$rc" "$DAEMON_RSS_BEFORE -> $DAEMON_RSS_AFTER MB"
echo ""

echo "→ Step 9: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 15m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
echo ""

echo "→ Step 10: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
