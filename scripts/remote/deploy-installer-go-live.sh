#!/usr/bin/env bash
# Deploy the installer / Go Live fixes (NET-244, NET-211) and check what a running box can show.
#
# Rebuilds the web UI and the daemon (Go Live reads the saved bridge ports from /api/capture/mode),
# and recreates the running capture containers so they mount the new capture env loader (it waits
# for a missing capture interface). A single-file bind mount keeps the old file after git pull,
# so a plain restart isn't enough. Then it runs uninstall.sh --dry-run, which changes nothing.
#
# The installer changes (two-port --skip-bridge --non-interactive, dry run, firewall, OpenSearch
# check) only show on a fresh install; this script doesn't reinstall.
#
# Run as the normal user (NOT with sudo):
#   bash /home/nettap/NetTap/scripts/remote/deploy-installer-go-live.sh
# To test a branch first: BRANCH=<branch> bash …
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="${BRANCH:-main}"
COMPOSE=(sudo docker compose -f docker/docker-compose.yml)
LIVE="nettap-suricata-live"
FAILED=0

check() {  # check "label" <0 pass / 1 fail> "detail"
    if [ "$2" -eq 0 ]; then echo "   ✓ $1${3:+: $3}"; else echo "   ✗ $1${3:+: $3}"; FAILED=1; fi
}

expect() {  # expect "label" ACTUAL WANTED: passes when they are equal, shows ACTUAL
    if [ "$2" = "$3" ]; then check "$1" 0 "$2"; else check "$1" 1 "$2"; fi
}

api() {  # api PATH EXPRESSION: GET PATH from the daemon with its token, print EXPRESSION over the reply `d`
    # The expression is always a literal from this script. The token is read inside the
    # container, inside fetch(): it, the headers and the request are gone before the eval runs
    sudo docker exec nettap-storage-daemon python3 -c "
import json, sys, urllib.error, urllib.request
def fetch(path):
    headers = {'X-NetTap-Daemon-Token': open('/run/nettap-auth/daemon-token').read().strip()}
    req = urllib.request.Request('http://localhost:8880' + path, headers=headers)
    try:
        return json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        return {'_status': e.code}
    except (urllib.error.URLError, ValueError):
        return {'_status': 'unreachable'}  # truthy, so no check passes on it
d = fetch(sys.argv[1])
del fetch
print(eval(sys.argv[2]))" "$1" "$2" 2>&1 | tail -n 1
}

running() { [ "$(sudo docker inspect --format='{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }

program_state() {  # program_state CONTAINER PROGRAM
    sudo docker exec "$1" supervisorctl -c /etc/supervisord.conf status "$2" 2>/dev/null | awk '{ print $2 }'
}

echo "=== Deploy: installer and Go Live fixes ($BRANCH) ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
PULLED=1
for attempt in 1 2 3 4 5; do
    if git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"; then PULLED=0; break; fi
    echo "   pull failed (attempt $attempt/5), retrying in 5 s..."
    sleep 5
done
if [ "$PULLED" -ne 0 ]; then
    echo "   ✗ Could not update to $BRANCH — nothing was changed"
    exit 1
fi
echo "   ✓ Code: $(git branch --show-current) @ $(git log -1 --format='%h %s')"
# shellcheck source=scripts/remote/rules-lock.sh
. "$REPO_DIR/scripts/remote/rules-lock.sh"
trap rules_lock_release EXIT
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
WEB="unknown"
DAEMON="unknown"
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

echo "→ Step 5: Recreate the running capture containers (new capture env loader)..."
# Only those running now: PCAP capture may be off in Settings, and compose up would start it
RECREATE=()
for pair in zeek-live:nettap-zeek-live pcap-capture:nettap-pcap-capture; do
    if running "${pair#*:}"; then RECREATE+=("${pair%%:*}"); else echo "   - ${pair#*:} isn't running; left as it is"; fi
done
if [ "${#RECREATE[@]}" -gt 0 ]; then
    "${COMPOSE[@]}" up -d --no-deps --force-recreate "${RECREATE[@]}"
fi
SURICATA_RECREATED=1
if running "$LIVE"; then
    rules_lock_take "$LIVE"
    case $? in
        0) echo "   ✓ holding the rules lock" ;;
        *) echo "   - Couldn't take the rules lock; recreating anyway (an interrupted update's marker makes the next start restore the last good rules)" ;;
    esac
    "${COMPOSE[@]}" up -d --no-deps --force-recreate suricata-live
    rules_lock_release
    SURICATA_RECREATED=0
else
    echo "   - $LIVE isn't running; left as it is"
fi
echo "   waiting 60 s for capture to start..."
sleep 60
echo ""

echo "→ Step 6: NET-211 #9 — capture starts on an interface that exists, and doesn't wait..."
# NETTAP_SYS_CLASS_NET pointed at nothing: read the interface without waiting for it
IFACE=$(sudo docker exec nettap-zeek-live sh -c 'NETTAP_SYS_CLASS_NET=/nonexistent . /usr/local/bin/nettap-capture-env.sh >/dev/null 2>&1; echo "$PCAP_IFACE"' 2>/dev/null)
echo "   capture interface: ${IFACE:-unknown}"
sudo docker exec nettap-zeek-live grep -q 'waiting for capture interface' /usr/local/bin/nettap-capture-env.sh
check "zeek-live mounts the new loader" $?
for c in nettap-zeek-live nettap-suricata-live nettap-pcap-capture; do
    running "$c" || continue
    if sudo docker logs --since 5m "$c" 2>&1 | grep -q 'nettap-capture-env: waiting for capture interface'; then
        check "$c" 1 "waiting for its capture interface (see docker logs $c)"
    else
        check "$c" 0 "not waiting"
    fi
done
expect "live-zeek" "$(program_state nettap-zeek-live live-zeek)" RUNNING
if [ "$SURICATA_RECREATED" -eq 0 ]; then
    # Its startup rule update runs first and can take a few minutes
    STATE=""
    for i in $(seq 1 30); do
        STATE=$(program_state "$LIVE" live-suricata)
        [ "$STATE" = "RUNNING" ] && break
        sleep 10
    done
    expect "live-suricata" "${STATE:-unknown}" RUNNING
fi
echo ""

echo "→ Step 7: NET-211 #3 — /api/capture/mode..."
echo "   $(api /api/capture/mode "d.get('_status') or 'mode=%s interface=%s wan=%s lan=%s' % (d.get('mode'), d.get('interface'), d.get('wan_interface', '-'), d.get('lan_interface', '-'))")"
R=$(api /api/capture/mode "d.get('_status') or ('ok' if d.get('mode') != 'bridge' and 'wan_interface' not in d else ('ok' if d.get('mode') == 'bridge' and d.get('wan_interface') and d.get('lan_interface') else 'bridge without saved ports: Go Live sends you to the wizard'))")
expect "bridge ports only in bridge mode" "$R" ok
echo ""

echo "→ Step 8: NET-211 #11 — uninstall.sh --dry-run (changes nothing)..."
OUT=$(bash scripts/install/uninstall.sh --dry-run 2>&1)
RC=$?
expect "exit status" "$RC" 0
echo "$OUT" | grep -E ' - |Left |Dry run' | sed 's/^/   /'
case "$OUT" in *"Dry run: nothing was changed."*) check "says it changed nothing" 0 ;; *) check "says it changed nothing" 1 ;; esac
for f in /etc/systemd/system/nettap.service /etc/sysctl.d/99-nettap.conf; do
    [ -e "$f" ] && check "$f still there" 0
done
MODE=$(api /api/capture/mode "d.get('mode')")
if [ "$MODE" = "mirror" ]; then
    case "$OUT" in *"systemd unit nettap-mirror.service"*) check "lists nettap-mirror.service" 0 ;; *) check "lists nettap-mirror.service" 1 ;; esac
    case "$OUT" in *"/etc/netplan/10-nettap-mirror-${IFACE}.yaml"*) check "lists the mirror netplan" 0 ;; *) check "lists the mirror netplan" 1 "10-nettap-mirror-${IFACE}.yaml" ;; esac
    [ -e "/etc/netplan/10-nettap-mirror-${IFACE}.yaml" ]
    check "the mirror netplan is still there" $?
fi
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "NAMES|nettap-web|nettap-storage-daemon|zeek-live|suricata-live|pcap-capture"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "=== Deploy complete ==="
else
    echo "=== Deploy finished with failures (see ✗ above) ==="
fi
echo "Open Go Live (https://nettap.local/go-live): in mirror mode it says there is no step to do."
