#!/usr/bin/env bash
# Deploy NET-320 (roadmap F2, the device details store) and check it on the box (plan §5 G11):
#   - the live backup first, before anything is rebuilt: NET-344's classify_backup_export.py
#     classifies the running daemon's export (a 200 passes; the size 413 or a legacy_excluded_ips
#     422 is a finding for the owner; anything else stops the deploy with nothing changed);
#   - the running daemon and web app are the images just built (image IDs, not the tags);
#   - live and read-only: registry rows carry group, owner and watch_after_min, the device page
#     read carries notes, the classified export (a 200 must now carry device_details; the same
#     two findings are reported, anything else fails), no unreadable-file line;
#   - isolated: verify_device_details.py runs in a throwaway copy of the daemon image with no
#     network and no mounts (store, budgets, MAC rule, 0600, backup round trip, damaged file);
#   - the daemon's settled memory stays within 50 MB of before.
# Nothing live is written: no device details, no backup restore. Rebuilds and recreates only
# nettap-storage-daemon and nettap-web. Prints status codes and figures, never a token or notes.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-device-details.sh
# To try a branch before it merges: BRANCH=feature/... bash ...
set -u

REPO_DIR="${REPO_DIR:-/home/nettap/NetTap}"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
DAEMON_IMAGE="nettap/storage-daemon:latest"
WEB_IMAGE="nettap/web:latest"
CLASSIFIER="scripts/remote/classify_backup_export.py"  # NET-344, standard library only
FAILED=0
FINDINGS=0

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

# The export's raw bytes to stdout and its status to stderr, read with the token as daemon_py does
EXPORT_PY='
import sys, urllib.error, urllib.request
try:
    token = open("/run/nettap-auth/daemon-token").read().strip()
    req = urllib.request.Request("http://localhost:8880/api/backup/export",
                                 headers={"X-NetTap-Daemon-Token": token})
    with urllib.request.urlopen(req, timeout=120) as r:
        status, body = r.status, r.read()
except urllib.error.HTTPError as e:
    status, body = e.code, e.read()
except OSError as e:
    status, body = 0, str(e).encode()
sys.stdout.buffer.write(body)
print(status, file=sys.stderr)'

classify_export() {  # classify_export [--require-section NAME]: the classifier's one-line verdict on the live export
    local status verdict
    if [ ! -f "$CLASSIFIER" ]; then echo "FAIL $CLASSIFIER isn't in this checkout (NET-344 isn't on the box)"; return; fi
    # stderr (the status) to the pipe, stdout (the bytes) to the file, which the user writes
    # shellcheck disable=SC2024  # only docker needs sudo
    status=$(sudo docker exec nettap-storage-daemon python3 -c "$EXPORT_PY" 2>&1 >"$TMPD/export.json" | tail -n 1)
    # it runs in the daemon container as -c, so stdin carries the export (the host has no python)
    # shellcheck disable=SC2024  # the user reads the file; only docker needs sudo
    verdict=$(sudo docker exec -i nettap-storage-daemon python3 -c "$(cat "$CLASSIFIER")" "${status:-000}" "$@" < "$TMPD/export.json" 2>&1)
    # the export holds notes, names, photos and the home location: gone as soon as it's read
    rm -f "$TMPD/export.json"
    echo "$verdict"
}

export_verdict() {  # export_verdict LABEL VERDICT: OK passes, FINDING is reported (!), anything else fails
    case "$2" in
        OK\ *) check "$1" 0 "$2" ;;
        FINDING\ *)
            FINDINGS=1
            echo "   ! $1: $2"
            echo "     The owner has to act on this (the message says how); the deploy carries on."
            ;;
        *) check "$1" 1 "${2:-no verdict}" ;;
    esac
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

echo "=== Deploy: device details (NET-320, $BRANCH) ==="
echo ""

# OLD CODE START — NET-344: fit measures the real file and trims the oldest acknowledgements, so
# the 768 KiB reserve for F2's share is gone; the export is classified instead (tracking doc,
# "Rebase requirements")
# echo "→ Step 1: Backup headroom, measured on the running daemon before anything changes..."
# cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# # compact, as Settings uploads a restore (web/src/lib/api/backup.ts importConfig: JSON.stringify)
# HEADROOM=$(daemon_py "
# s, b = call('GET', '/api/backup/export')
# if s != 200:
#     print('FAIL the export answered', s)
# else:
#     size = len(json.dumps(json.loads(b), separators=(',', ':'), ensure_ascii=False).encode())
#     room = $LIMIT_BYTES - $F2_SHARE_BYTES - size
#     print('OK' if room > 0 else 'FAIL', f'backup {size / 1e6:.2f} MB as uploaded, limit {$LIMIT_BYTES / 1e6:.2f} MB, headroom after F2 adds {$F2_SHARE_BYTES / 1e6:.2f} MB: {room / 1e6:.2f} MB')")
# result "the live backup has room for F2's share" "$HEADROOM"
# if [ "$FAILED" -ne 0 ]; then
#     echo ""
#     echo "=== Stopped: nothing was changed. A backup this size couldn't be restored once F2 fills up; shrink it first (NET-344) ==="
#     exit 1
# fi
# echo ""
# OLD CODE END
echo "→ Step 1: The live backup, classified on the running daemon before anything changes..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT
# no --require-section: the running build may not have F2 yet
export_verdict "the running daemon's backup export" "$(classify_export)"
if [ "$FAILED" -ne 0 ]; then
    echo ""
    echo "=== Stopped: nothing was changed. The running daemon's backup export failed (✗ above); fix that first ==="
    exit 1
fi
echo ""

echo "→ Step 2: Baseline (settled daemon memory)..."
DAEMON_RSS_BEFORE=$(settled_rss_mb)
echo "   daemon VmRSS ${DAEMON_RSS_BEFORE} MB (settled)"
echo ""

echo "→ Step 3: Update the code..."
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 4: Build the daemon and web containers..."
# a failed build must stop here: recreating would bring back the OLD images unnoticed
if ! "${COMPOSE[@]}" build nettap-storage-daemon nettap-web; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
BUILT=$(sudo docker image inspect "$DAEMON_IMAGE" --format '{{.Id}}' 2>/dev/null)
BUILT_WEB=$(sudo docker image inspect "$WEB_IMAGE" --format '{{.Id}}' 2>/dev/null)
echo "   ✓ Images built (daemon ${BUILT:7:12}, web ${BUILT_WEB:7:12})"
echo ""

echo "→ Step 5: Recreate the daemon and web containers (nothing else is touched)..."
if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-storage-daemon nettap-web; then
    echo "   ✗ Recreation failed — the checks below would test the old containers"
    exit 1
fi
echo ""

echo "→ Step 6: Wait for both to become healthy..."
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

echo "→ Step 7: The running containers are the images just built..."
RUNNING=$(sudo docker inspect nettap-storage-daemon --format '{{.Image}}' 2>/dev/null)
if [ -n "$BUILT" ] && [ "$RUNNING" = "$BUILT" ]; then rc=0; else rc=1; fi
check "daemon image ID" "$rc" "running ${RUNNING:7:12}, built ${BUILT:7:12}"
RUNNING_WEB=$(sudo docker inspect nettap-web --format '{{.Image}}' 2>/dev/null)
if [ -n "$BUILT_WEB" ] && [ "$RUNNING_WEB" = "$BUILT_WEB" ]; then rc=0; else rc=1; fi
check "web image ID" "$rc" "running ${RUNNING_WEB:7:12}, built ${BUILT_WEB:7:12}"
echo ""

echo "→ Step 8: Live and read-only..."
# no set literals with commas in these snippets: bash 3.2 brace-expands them inside "$(f "...")"
result "registry rows carry group, owner and watch_after_min" "$(daemon_py "
s, b = call('GET', '/api/devices/registry?limit=50')
rows = json.loads(b).get('devices', []) if s == 200 else []
bad =[r for r in rows if not all(k in r for k in ('group', 'owner', 'watch_after_min'))]
print('OK' if s == 200 and rows and not bad else 'FAIL', 'status', s, 'rows', len(rows), 'without the keys', len(bad))")"
result "the device page read carries notes" "$(daemon_py "
s, b = call('GET', '/api/devices/registry?limit=1')
rows = json.loads(b).get('devices', []) if s == 200 else []
if not rows or not rows[0].get('mac'):
    print('FAIL no device to read, list status', s)
else:
    s, b = call('GET', '/api/devices/registry/' + rows[0]['mac'])
    d = json.loads(b).get('device', {}) if s == 200 else {}
    ok = s == 200 and all(k in d for k in ('notes', 'group', 'owner', 'watch_after_min'))
    print('OK' if ok else 'FAIL', 'status', s)")"
# OLD CODE START — NET-344: the export is classified now; a size 413 or legacy_excluded_ips 422
# is a finding, not a failure, and the classifier prints sizes, never the section's notes
# result "a backup export has a device_details section" "$(daemon_py "
# s, b = call('GET', '/api/backup/export')
# dd = json.loads(b).get('sections', {}).get('device_details') if s == 200 else None
# # a count only: the section holds the owner's own words
# print('OK' if isinstance(dd, dict) else 'FAIL', 'status', s, 'entries', len(dd) if isinstance(dd, dict) else type(dd).__name__)")"
# OLD CODE END
export_verdict "the backup export carries device_details" "$(classify_export --require-section device_details)"
# the container was just recreated, so its whole log is since the restart
UNREADABLE=$(sudo docker logs nettap-storage-daemon 2>&1 | grep -c "Device details file is unreadable" || true)
if [ "${UNREADABLE:-0}" -eq 0 ]; then rc=0; else rc=1; fi
check "no unreadable device details line in the daemon log" "$rc" "${UNREADABLE:-0} line(s)"
echo ""

echo "→ Step 9: Isolated exercise in a throwaway copy of the image (no network, no mounts)..."
if [ -z "$RUNNING" ] || [ "$RUNNING" != "$BUILT" ]; then
    check "isolated exercise" 1 "skipped: the running image isn't the one built"
else
    # the user reads the script and docker gets it on stdin, so sudo needn't touch the redirect
    # shellcheck disable=SC2024
    OUT=$(sudo docker run --rm -i --network none --entrypoint python3 "$BUILT" - < scripts/remote/verify_device_details.py 2>&1)
    echo "$OUT" | grep -E "^   " || true
    if echo "$OUT" | grep -qx "DEVICE-DETAILS-OK"; then rc=0; else rc=1; fi
    check "store, budgets, MAC rule, 0600, backup round trip, damaged file" "$rc" "$(echo "$OUT" | tail -n 1)"
fi
echo ""

echo "→ Step 10: Settled memory..."
DAEMON_RSS_AFTER=$(settled_rss_mb)
if [ $((DAEMON_RSS_AFTER - DAEMON_RSS_BEFORE)) -le 50 ]; then rc=0; else rc=1; fi
check "settled daemon VmRSS within 50 MB of before" "$rc" "$DAEMON_RSS_BEFORE -> $DAEMON_RSS_AFTER MB"
echo ""

echo "→ Step 11: Log errors since the restart..."
sudo docker logs nettap-storage-daemon 2>&1 | grep -iE "error|exception|traceback" | tail -n 5 || true
echo ""

echo "→ Step 12: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -ne 0 ]; then
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
elif [ "$FINDINGS" -ne 0 ]; then
    echo "=== Deploy complete; every check passed, with a finding for the owner (! above) ==="
else
    echo "=== Deploy complete: every check passed ==="
fi
