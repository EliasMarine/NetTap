#!/usr/bin/env bash
# Deploy the owner's 2026-11-15 bug report fixes and check them on the box:
#   NET-305 (web)          charts mark missing data; the Home chart draws once at its final size
#   NET-306 (daemon, web)  software updates: history kept, pre-releases seen, one shared check
#   NET-303 (daemon, web)  a page per Suricata rule; the devices that looked up a domain
#   NET-302 (daemon, web)  Threats drill-downs: beaconing pair, failed lookups, finding mode
#   NET-304 (daemon, web)  Security posture category pages
#
# Every check is a read-only GET, except one "Check for updates" (POST /api/system/updates/check),
# which only asks GitHub and the registries what is new; it installs nothing.
#
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and counts, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-owner-bugs-2026-11-16.sh
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
# `get(path)` retries once on a 503 (the drill-down slots answer "busy" while another search runs).
daemon_py() {  # daemon_py PYTHON_SNIPPET
    sudo docker exec -e SNIPPET="$1" nettap-storage-daemon python3 -c '
import json, os, time, urllib.error, urllib.parse, urllib.request
token = open("/run/nettap-auth/daemon-token").read().strip()
def call(method, path, body=None):
    data = None if body is None else body.encode()
    req = urllib.request.Request("http://localhost:8880" + path, data=data, method=method,
                                 headers={"X-NetTap-Daemon-Token": token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
def get(path):
    status, body = call("GET", path)
    if status == 503:
        time.sleep(5)
        status, body = call("GET", path)
    return status, (json.loads(body) if body.startswith(("{", "[")) else {})
q = lambda s: urllib.parse.quote(s, safe="")
try:
    exec(os.environ["SNIPPET"])
except Exception as e:
    print("FAIL", type(e).__name__, str(e)[:200])' 2>/dev/null || echo "FAIL could not run inside the daemon container"
}

result() {  # result LABEL OUTPUT  (OUTPUT starting with OK passes, SKIP is shown but not a failure)
    case "$2" in
        OK*) check "$1" 0 "$2" ;;
        SKIP*) echo "   - $1 (${2#SKIP })" ;;
        *) check "$1" 1 "$2" ;;
    esac
}

echo "=== Deploy: owner bug fixes, 2026-11-16 ($BRANCH) ==="
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

echo "→ Step 5: NET-306, software updates..."
result "the daemon reports NetTap 0.4.0-alpha.2" "$(daemon_py '
status, data = get("/api/system/versions")
row = next((v for v in data.get("versions", []) if v.get("name") == "nettap-daemon"), {})
ver = row.get("current_version")
print("OK" if status == 200 and ver == "0.4.0-alpha.2" else "FAIL", status, ver)')"
result "a check finishes with no NetTap container in failed_checks, and stale is false" "$(daemon_py '
cstatus, _ = call("POST", "/api/system/updates/check", "{}")
status, data = get("/api/system/updates/available")
failed = data.get("failed_checks", [])
ours = [c for c in failed if str(c).startswith("nettap")]
ok = status == 200 and not ours and data.get("stale") is False
print("OK" if ok else "FAIL", "check", cstatus, "available", status, "stale", data.get("stale"),
      "failed_checks", failed, "checked", len(data.get("checked", [])))')"
result "history answers as a list of batches" "$(daemon_py '
status, data = get("/api/system/updates/history")
rows = data if isinstance(data, list) else data.get("history", [])
path = os.environ.get("UPDATE_HISTORY_FILE", "/opt/nettap/data/update-history.json")
on_disk = "on disk" if os.path.exists(path) else "no file yet (written after the first update batch)"
print("OK" if status == 200 and isinstance(rows, list) else "FAIL", status, len(rows), "batches,", on_disk)')"
echo ""

echo "→ Step 6: NET-303, the rule page and the devices that looked up a domain..."
result "the busiest rule opens its own page" "$(daemon_py '
status, data = get("/api/alerts/top-signatures")
sigs = data.get("signatures", [])
if not sigs:
    print("SKIP no alerts in the last 24 hours to open")
else:
    name = sigs[0]["signature"]
    rstatus, page = get("/api/alerts/rule/" + q(name))
    ok = rstatus == 200 and isinstance(page, dict) and bool(page)
    print("OK" if ok else "FAIL", rstatus, name[:50], "keys", sorted(page)[:6])')"
result "a domain answers in finding mode" "$(daemon_py '
status, data = get("/api/dns/top-domains")
doms = data.get("domains", [])
if not doms:
    print("SKIP no DNS lookups in the last 24 hours")
else:
    d = doms[0]["domain"]
    dstatus, page = get("/api/domains/" + q(d) + "?finding=" + q(d))
    print("OK" if dstatus == 200 and isinstance(page, dict) else "FAIL", dstatus, d[:50])')"
result "a finding that isn't the page's name is a 400" "$(daemon_py '
status, _ = call("GET", "/api/domains/example.com?finding=example.org")
print("OK" if status == 400 else "FAIL", status)')"
echo ""

echo "→ Step 7: NET-302, Threats drill-downs..."
result "the first beaconing pair opens" "$(daemon_py '
status, data = get("/api/threats/beaconing")
beacons = data.get("beacons", [])
if not beacons:
    print("SKIP no beaconing pair listed in the last 24 hours")
else:
    b = beacons[0]
    qs = urllib.parse.urlencode({"device": b["source_ip"], "server": b["destination_ip"],
                                 "port": b["destination_port"]})
    pstatus, page = get("/api/threats/beaconing/pair?" + qs)
    timing = page.get("timing", {}) if isinstance(page, dict) else {}
    ok = pstatus == 200 and timing.get("status") in {"periodic", "irregular", "too_few", "capped"}
    print("OK" if ok else "FAIL", pstatus, "timing", timing.get("status"))')"
result "a device's failed lookups answer, with the rule's verdict" "$(daemon_py '
status, data = get("/api/threats/beaconing")
beacons = data.get("beacons", [])
ip = beacons[0]["source_ip"] if beacons else "192.168.1.1"
fstatus, page = get("/api/threats/failed-lookups/" + q(ip))
ok = fstatus == 200 and isinstance(page.get("meets_rule"), bool)
print("OK" if ok else "FAIL", fstatus, ip, "lookups", page.get("lookups"), "meets_rule", page.get("meets_rule"))')"
result "a range instead of one address is a 400" "$(daemon_py '
status, _ = call("GET", "/api/threats/failed-lookups/" + q("192.168.1.0/24"))
print("OK" if status == 400 else "FAIL", status)')"
echo ""

echo "→ Step 8: NET-304, Security posture category details..."
for CATEGORY in encryption dns-security patch-currency; do
    result "posture detail for $CATEGORY" "$(daemon_py "
status, data = get('/api/posture/$CATEGORY')
print('OK' if status == 200 and data.get('category') == '$CATEGORY' else 'FAIL', status, 'keys', sorted(data)[:8])")"
done
result "an unknown category is a 404" "$(daemon_py '
status, _ = call("GET", "/api/posture/not-a-category")
print("OK" if status == 404 else "FAIL", status)')"
echo ""

echo "→ Step 9: The web answers..."
CODE=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health" || true)
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/health answers" "$rc" "$CODE"
echo ""

echo "→ Step 10: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 10m 2>&1 | grep -iE "error|exception|traceback" | tail -n 8 || true
sudo docker logs nettap-web --since 10m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
    echo "Open the dashboard: Threats (click a beaconing, failed-lookups and DGA row), Alerts (click a"
    echo "rule name), DNS (pick a domain), Security posture (click a card), System › Updates, and Home."
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
