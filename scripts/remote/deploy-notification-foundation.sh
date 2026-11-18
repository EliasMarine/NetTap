#!/usr/bin/env bash
# Deploy NET-319 (roadmap F1) and check it on the box:
#   - the event journal (events.jsonl) and the dispatcher's own event state (notification-events.json);
#   - "New device" notifications through the same channels and limits as alerts;
#   - the background job runner: GET /api/jobs, and a forced run of journal-compact through it;
#   - memory and swap against readings taken before the rebuild (the roadmap's 50 MB stop rule).
#
# A real new device is checked when one appears (one journal line, one "New device" in the log);
# this script prints the last journal lines for that. Nothing here sends a notification.
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and counts, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-notification-foundation.sh
# To try a branch before it merges: BRANCH=feature/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
DATA=/opt/nettap/data
FAILED=0

check() {  # check LABEL STATUS(0=ok) DETAIL
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+ ($3)}"; else echo "   ✗ $1${3:+ ($3)}"; FAILED=1; fi
}

# Run a Python check inside the daemon container with the shared token as `call(method, path, body)`.
daemon_py() {  # daemon_py PYTHON_SNIPPET
    sudo docker exec -e SNIPPET="$1" nettap-storage-daemon python3 -c '
import json, os, time, urllib.error, urllib.request
from datetime import datetime
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

container_mb() {  # container_mb NAME -> memory in MB, or empty
    sudo docker stats --no-stream --format '{{.MemUsage}}' "$1" 2>/dev/null | awk '{
        v=$1; u=v; gsub(/[0-9.]/, "", u); gsub(/[A-Za-z]/, "", v);
        if (u=="GiB") v*=1024; else if (u=="KiB") v/=1024; printf "%d", v }'
}

echo "=== Deploy: notification events, event journal and background checks (NET-319, $BRANCH) ==="
echo ""

echo "→ Step 1: Memory before the rebuild..."
MEM_BEFORE=$(free -m | awk '/^Mem:/ {print $3}')
SWAP_BEFORE=$(free -m | awk '/^Swap:/ {print $3}')
DAEMON_BEFORE=$(container_mb nettap-storage-daemon)
WEB_BEFORE=$(container_mb nettap-web)
echo "   used ${MEM_BEFORE} MB, swap ${SWAP_BEFORE} MB, daemon ${DAEMON_BEFORE:-?} MB, web ${WEB_BEFORE:-?} MB"
echo ""

echo "→ Step 2: Update the code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 3: Build the daemon and web containers..."
# A failed build must stop here: recreating would bring back the OLD images unnoticed.
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 4: Recreate the daemon and web containers (nothing else is touched)..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web
echo ""

echo "→ Step 5: Wait for both to become healthy, then 2 minutes to settle..."
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
sleep 120  # the dispatcher's first polls write its event state; memory settles
echo ""

echo "→ Step 6: Force a run of journal-compact through the scheduler, sampling memory..."
result "forced run finishes within 60 s with no error" "$(daemon_py "
def rss(pid):
    try:
        for line in open('/proc/%s/status' % pid):
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) // 1024
    except OSError:
        return None
pid = next((p for p in os.listdir('/proc') if p.isdigit() and b'main.py' in open('/proc/%s/cmdline' % p, 'rb').read()), None)
start = time.time()
status, body = call('POST', '/api/jobs/journal-compact/run')
samples, job = [], None
while time.time() - start < 60:
    samples.append(rss(pid))
    _, listing = call('GET', '/api/jobs')
    job = next(j for j in json.loads(listing)['jobs'] if j['name'] == 'journal-compact')
    ran = job['last_run'] and datetime.fromisoformat(job['last_run']).timestamp() >= start - 1
    if ran and not job['running']:
        break
    time.sleep(0.5)
peak = max([s for s in samples if s is not None] or [0])
ok = status == 202 and job and not job['running'] and job['last_error'] is None and time.time() - start < 60
print('OK' if ok else 'FAIL', 'status', status, 'took', job and job['last_duration_ms'], 'ms',
      'rss before/after', job and job['rss_mb_before'], job and job['rss_mb_after'],
      'sampled peak', peak, 'MB', 'VmHWM', job and job['peak_rss_mb'], 'error', job and job['last_error'])")"
echo ""

echo "→ Step 7: Memory and swap compared with step 1..."
MEM_AFTER=$(free -m | awk '/^Mem:/ {print $3}')
SWAP_AFTER=$(free -m | awk '/^Swap:/ {print $3}')
DAEMON_AFTER=$(container_mb nettap-storage-daemon)
WEB_AFTER=$(container_mb nettap-web)
echo "   used ${MEM_BEFORE} -> ${MEM_AFTER} MB, swap ${SWAP_BEFORE} -> ${SWAP_AFTER} MB"
for pair in "daemon:${DAEMON_BEFORE:-0}:${DAEMON_AFTER:-0}" "web:${WEB_BEFORE:-0}:${WEB_AFTER:-0}"; do
    IFS=: read -r name before after <<< "$pair"
    if [ $((after - before)) -le 50 ]; then rc=0; else rc=1; fi
    check "$name container grew by no more than 50 MB" "$rc" "$before -> $after MB"
done
LIMIT=$((SWAP_BEFORE + SWAP_BEFORE / 20))
if [ "$SWAP_AFTER" -le "$LIMIT" ]; then rc=0; else rc=1; fi
check "swap within the baseline + 5%" "$rc" "$SWAP_BEFORE -> $SWAP_AFTER MB, limit $LIMIT"
echo ""

echo "→ Step 8: The journal and the dispatcher's state files..."
result "event journal readable, mode 600 (or no event yet)" "$(daemon_py "
path = '$DATA/events.jsonl'
if not os.path.exists(path):
    print('OK no event yet')
else:
    mode = oct(os.stat(path).st_mode & 0o777)
    lines = open(path).read().splitlines()
    bad = sum(1 for l in lines if l.strip() and not isinstance(json.loads(l).get('seq'), int))
    print('OK' if mode == '0o600' and not bad else 'FAIL', len(lines), 'events, mode', mode, 'unreadable', bad)")"
result "event state has journal_seq; the alert state keeps its cursor" "$(daemon_py "
events = json.load(open('$DATA/notification-events.json'))
alerts = json.load(open('$DATA/notification-dispatch.json'))
mode = oct(os.stat('$DATA/notification-events.json').st_mode & 0o777)
ok = isinstance(events.get('journal_seq'), int) and 'cursor' in alerts and mode == '0o600'
print('OK' if ok else 'FAIL', 'journal_seq', events.get('journal_seq'), 'queued channels', len(events.get('channels', {})), 'alert cursor', bool(alerts.get('cursor')), 'mode', mode)")"
result "GET /api/jobs lists journal-compact" "$(daemon_py "
status, body = call('GET', '/api/jobs')
names = [j['name'] for j in json.loads(body)['jobs']] if status == 200 else []
print('OK' if 'journal-compact' in names else 'FAIL', status, names)")"
result "Settings shows new devices (on by default where a Settings channel exists)" "$(daemon_py "
status, body = call('GET', '/api/notifications/config')
cfg = json.loads(body)
has_channel = cfg['email']['enabled'] or cfg['webhook']['enabled']
print('OK' if status == 200 and isinstance(cfg.get('new_device'), bool) else 'FAIL', 'new_device', cfg.get('new_device'), 'settings channel', has_channel)")"
echo ""

echo "→ Step 9: The last journal lines (a real new device shows here)..."
daemon_py "
path = '$DATA/events.jsonl'
lines = open(path).read().splitlines()[-3:] if os.path.exists(path) else []
for l in lines:
    e = json.loads(l)
    print('   ', e['seq'], e['type'], e['key'], e['recorded_at'][:19])
print('    (' + str(len(lines)) + ' shown)')"
echo ""

echo "→ Step 10: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 5m 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
sudo docker logs nettap-web --since 5m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
