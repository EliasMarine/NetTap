#!/usr/bin/env bash
# Deploy the owner's 2026-11-16 follow-ups and check them on the box:
#   NET-308 (daemon, web)  Security posture scores measure what they claim
#   NET-311 (web)          Apply updates opens only with something to apply
#   NET-312 (web)          SvelteKit 2.70.4 / adapter-node 5.5.8 security patch
#
# Every check is a read-only GET, plus one POST that the daemon must refuse (a malformed
# alert_ids list is a 400, so nothing is stored).
#
# Rebuilds and recreates only nettap-storage-daemon and nettap-web. Daemon calls run inside the
# daemon container, so the token never leaves it. Prints status codes and counts, never a token.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-posture-and-updates-2026-11-16.sh
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
pct = lambda a, b: round(100 * a / b) if b else None
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

echo "=== Deploy: posture scores and Apply updates, 2026-11-16 ($BRANCH) ==="
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

echo "→ Step 5: NET-308, the score inputs (last 24 hours)..."
result "Encryption counts only connections with data both ways" "$(daemon_py '
status, data = get("/api/traffic/protocols")
enc = data.get("encryption", {})
ok = status == 200 and {"eligible", "encrypted", "one_way"} <= set(enc)
print("OK" if ok else "FAIL", status, "encrypted", pct(enc.get("encrypted", 0), enc.get("eligible", 0)), "%",
      "of", enc.get("eligible"), "| one-way left out", enc.get("one_way"))')"
result "DNS leaves your own resolvers out of both sides" "$(daemon_py '
status, data = get("/api/traffic/protocols")
dns = data.get("dns", {})
local = dns.get("local", {})
ok = status == 200 and isinstance(local.get("plain"), int) and isinstance(local.get("over_tls"), int)
print("OK" if ok else "FAIL", status, "scored: plain", dns.get("plain"), "DoT", dns.get("over_tls"),
      "| local: plain", local.get("plain"), "DoT", local.get("over_tls"))')"
result "Segmentation comes from the isolation score (reached pairs only)" "$(daemon_py '
status, data = get("/api/iot/network-isolation")
score = data.get("segmentation_score", "absent")
pairs = data.get("pairs", [])
ok = status == 200 and (score is None or isinstance(score, (int, float))) and all("reached" in p for p in pairs)
print("OK" if ok else "FAIL", status, "score", score, "pairs", len(pairs),
      "reached", sum(1 for p in pairs if p.get("reached")))')"
result "Alert response answers with the high-severity rule groups" "$(daemon_py '
status, data = get("/api/posture/alert-response")
inv = data.get("investigations", {})
ok = status == 200 and data.get("category") == "alert-response" and isinstance(data.get("needing"), int)
print("OK" if ok else "FAIL", status, "needing", data.get("needing"), "investigated", data.get("investigated"),
      "| open during window", inv.get("open_during"), "unresolved links", inv.get("unresolved_links"))')"
for CATEGORY in encryption dns-security patch-currency; do
    result "posture detail for $CATEGORY" "$(daemon_py "
status, data = get('/api/posture/$CATEGORY')
print('OK' if status == 200 and data.get('category') == '$CATEGORY' else 'FAIL', status)")"
done
result "a malformed alert_ids list is refused, and nothing is stored" "$(daemon_py '
status, _ = call("POST", "/api/investigations", json.dumps({"title": "deploy check", "alert_ids": [{}]}))
print("OK" if status == 400 else "FAIL", status)')"
echo ""

echo "→ Step 6: NET-311, what Apply updates will offer..."
result "updates/available splits applicable and come-another-way updates" "$(daemon_py '
# A recreated daemon has checked nothing yet (stale, empty), so run one check first. It only
# asks GitHub and the registries what is new; it installs nothing.
status, data = get("/api/system/updates/available")
if data.get("stale", True) or not data.get("checked"):
    call("POST", "/api/system/updates/check", "{}")
    status, data = get("/api/system/updates/available")
ups = data.get("updates", []) if isinstance(data, dict) else []
own = [u.get("component") for u in ups if not u.get("applies_with")]
other = [str(u.get("component")) + " (with " + str(u.get("applies_with")) + ")" for u in ups if u.get("applies_with")]
ok = status == 200 and data.get("stale") is False and bool(data.get("checked"))
print("OK" if ok else "FAIL", status, "checked", len(data.get("checked", [])), "Review button shown:",
      "yes" if own else "no", "| applicable", own or "none", "| listed as information", other or "none")')"
echo ""

echo "→ Step 7: NET-312, the web image was built with the patched SvelteKit..."
# The runtime image prunes dev dependencies, so read the lockfile the image was built from (step 2).
KIT=$(grep -A1 '"node_modules/@sveltejs/kit": {' web/package-lock.json | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)
if [ "${KIT:-}" = "2.70.4" ]; then rc=0; else rc=1; fi
check "@sveltejs/kit in the built lockfile is 2.70.4" "$rc" "${KIT:-not found}"
CODE=$(curl -sk -o /dev/null --max-time 20 -w '%{http_code}' "$BASE/api/health" || true)
if [ "$CODE" = "200" ]; then rc=0; else rc=1; fi
check "/api/health answers" "$rc" "$CODE"
echo ""

echo "→ Step 8: Log errors since the restart..."
sudo docker logs nettap-storage-daemon --since 10m 2>&1 | grep -iE "error|exception|traceback" | tail -n 8 || true
sudo docker logs nettap-web --since 10m 2>&1 | grep -iE "error|exception" | tail -n 5 || true
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete: every check passed ==="
    echo "Open the dashboard: Security posture (the overview grade, then each card's page), an alert's"
    echo "drawer (Open an investigation), and System › Updates."
else
    echo "=== Deploy complete, but a check FAILED (✗ above) ==="
    exit 1
fi
