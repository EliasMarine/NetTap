#!/usr/bin/env bash
# Deploy drill-down exactness and the empty-box fixes (NET-185, NET-184, NET-182) and check each
# one on the device's real data.
#
# Rebuilds the web UI and the daemon. Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-drilldown-exact-empty-box.sh
# To test a branch first: git checkout <branch> && git pull, then BRANCH=<branch> bash …
#
# The figure checks use a 24-hour window that ended 2 hours ago, so records indexed after a
# figure was read (a connection is logged when it ends) can't move it between two reads.
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

in_daemon() {  # in_daemon < python: runs it in the daemon container; any "✗" line, or no output, fails
    local out
    out=$(sudo docker exec -i -w /opt/nettap/daemon nettap-storage-daemon python3 - 2>&1)
    echo "${out:-   ✗ no output}"
    case "$out" in *"✗ "*|"") FAILED=1 ;; esac
}

echo "=== Deploy: drill-down exactness and the empty box ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
if ! git fetch origin || ! git checkout "$BRANCH" || ! git pull origin "$BRANCH"; then
    echo "   ✗ Could not update to $BRANCH — nothing was rebuilt"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
echo ""

echo "→ Step 2: Build the web and daemon containers..."
if ! "${COMPOSE[@]}" build nettap-web nettap-storage-daemon; then
    echo "   ✗ Build failed — nothing was restarted"
    exit 1
fi
echo "   ✓ Images built"
echo ""

echo "→ Step 3: Recreate the web and the daemon..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate nettap-web nettap-storage-daemon
echo ""

echo "→ Step 4: Wait for them to become healthy..."
for i in $(seq 1 30); do
    WEB=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-storage-daemon 2>/dev/null || echo "unknown")
    if [ "$WEB" = "healthy" ] && [ "$DAEMON" = "healthy" ]; then break; fi
    echo "   waiting... web=$WEB daemon=$DAEMON ($i/30)"
    sleep 5
done
expect "nettap-web" "$WEB" healthy
expect "nettap-storage-daemon" "$DAEMON" healthy
echo ""

# One Python program per step, inside the daemon container. The token is read inside get(); it
# is never printed. Each program prints one "✓ …" or "✗ …" line per check.
COMMON='
import json, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

def get(path, **params):
    """(status, body) of a daemon GET; the body is {} when it is not JSON."""
    token = open("/run/nettap-auth/daemon-token").read().strip()
    url = "http://localhost:8880" + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"X-NetTap-Daemon-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except (urllib.error.URLError, ValueError) as e:
        return "unreachable", {"error": str(e)}

def say(ok, label, detail=""):
    print(("   ✓ " if ok else "   ✗ ") + label + (": " + str(detail) if detail != "" else ""))

end = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)
WIN = {"from": (end - timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
       "to": end.isoformat().replace("+00:00", "Z")}
'

echo "→ Step 5: NET-185 — a category bar's figure is what its page and lists hold..."
in_daemon <<PY
$COMMON
status, cats = get("/api/alerts/categories", **WIN)
rows = [c for c in cats.get("categories", []) if c.get("count")]
say(status == 200, "categories over a fixed window", f"{len(rows)} with alerts")
for c in rows:
    s1, detail = get("/api/alerts/categories/" + c["id"], **WIN)
    s2, listed = get("/api/alerts", category=c["id"], size=1, **WIN)
    got = (detail.get("stats", {}).get("total"), listed.get("total"))
    say(s1 == 200 and s2 == 200 and got == (c["count"], c["count"]),
        f"{c['id']}: bar {c['count']}, category page and list", got)
    # every Top signatures bar's link (up to 5 a category) lists exactly its figure
    for sig in detail.get("top_signatures", [])[:5]:
        if sig["signature"] == "":
            continue  # an empty name has no link
        narrow = {"no_rule_name": "true"} if sig["signature"] is None else {"signature": sig["signature"]}
        s3, one = get("/api/alerts", size=1, **narrow, **WIN)
        name = "no rule name" if sig["signature"] is None else sig["signature"][:60]
        say(s3 == 200 and one.get("total") == sig["count"],
            f"  {name}: bar {sig['count']}, list", one.get("total"))
s4, _ = get("/api/alerts", no_rule_name="maybe")
say(s4 == 400, "no_rule_name=maybe is refused", s4)
s5, none = get("/api/alerts", no_rule_name="true", size=1, **WIN)
say(s5 == 200 and isinstance(none.get("total"), int), "no_rule_name=true answers", none.get("total"))
PY
echo ""

echo "→ Step 6: NET-184 — a top source or destination bar's figure is its one-sided list..."
in_daemon <<PY
$COMMON
for path, key, side in (("/api/logs/top-talkers", "talkers", "source"),
                        ("/api/logs/top-destinations", "destinations", "destination")):
    status, bars = get(path, limit=3, **WIN)
    say(status == 200, path, status)
    for bar in bars.get(key, []):
        q = f'{side}.ip:"{bar["ip"]}"'
        s2, found = get("/api/logs/search", query=q, size=1, **WIN)
        total = found.get("total")
        if total != bar["count"]:  # a late record between the two reads: read the bar again
            _, again = get(path, limit=3, **WIN)
            bar = next((b for b in again.get(key, []) if b["ip"] == bar["ip"]), bar)
        say(s2 == 200 and total == bar["count"], f"{side} {bar['ip']}: bar {bar['count']}, list", total)
PY
echo ""

echo "→ Step 7: NET-182 — a search of no index answers zeros, through the daemon's own client..."
in_daemon <<'PY'
import os
from main import _parse_curlrc_credentials
from storage.manager import StorageManager

auth = _parse_curlrc_credentials(os.environ.get("OPENSEARCH_CREDS_CONFIG_FILE", ""))
client = StorageManager._create_client(os.environ["OPENSEARCH_URL"], http_auth=auth)
body = {
    "size": 0,
    "aggs": {
        "ips": {"terms": {"field": "source.ip"}},
        "tcp": {"filter": {"term": {"network.transport": "tcp"}}, "aggs": {"b": {"sum": {"field": "source.bytes"}}}},
    },
}
r = client.search(index="nettap-no-such-index-*", body=body)
aggs = r.get("aggregations") or {}
ok = (r["_shards"]["total"] == 0 and aggs.get("ips", {}).get("buckets") == []
      and aggs.get("tcp", {}).get("doc_count") == 0 and aggs["tcp"]["b"]["value"] == 0.0)
print(("   ✓ " if ok else "   ✗ ") + "no index: empty aggregations, not an incomplete reply" + ("" if ok else ": " + str(r)[:300]))
PY
echo ""

echo "→ Step 8: NET-182 — the device limit has its Changelog type, and the device reads still answer..."
in_daemon <<PY
$COMMON
status, types = get("/api/changelog/types")
say(status == 200 and "device_cap_reached" in types.get("event_types", []), "changelog types", types.get("event_types"))
for path in ("/api/devices", "/api/devices/count", "/api/risk/scores", "/api/traffic/protocols"):
    status, _ = get(path, **WIN)
    say(status == 200, path, status)
PY
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo "Open Alerts › Alert categories and a category's Top signatures, and Log Explorer's top sources, to see them."
