#!/usr/bin/env bash
# Deploy DHCP gateway capture mode and report what the device is actually doing.
# Read-only after the deploy: it never enables DHCP gateway mode and never
# changes network config. Enable it from the Go Live page.
set -u

REPO_DIR="/home/nettap/NetTap"
BRANCH="phase-4/dhcp-gateway-mode"
COMPOSE="docker/docker-compose.yml"
DAEMON="nettap-storage-daemon"
CAPTURE_CONTAINERS=(nettap-zeek-live nettap-suricata-live nettap-arkime-live nettap-pcap-capture)

echo "=== Deploy DHCP gateway capture mode ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
git fetch origin || echo "   ✗ git fetch failed"
git checkout "$BRANCH" || echo "   ✗ git checkout $BRANCH failed"
git pull origin "$BRANCH" || echo "   ✗ git pull failed"
echo "   ✓ Code updated: $(git log --oneline -1)"
echo ""

echo "→ Step 2: Rebuild daemon and web containers..."
sudo docker compose -f "$COMPOSE" build nettap-storage-daemon nettap-web || echo "   ✗ build failed"
echo "   ✓ Images rebuilt"
echo ""

echo "→ Step 3: Recreate daemon, web and the four capture containers..."
# --no-deps: never touch OpenSearch (recreating it resets its security mapping).
sudo docker compose -f "$COMPOSE" up -d --no-deps --force-recreate \
    nettap-storage-daemon nettap-web zeek-live suricata-live arkime-live pcap-capture \
    || echo "   ✗ recreate failed"
echo "   ✓ Containers recreated"
echo ""

echo "→ Step 4: Wait for containers to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' "$DAEMON" 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        echo "   ✓ Both containers healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
echo ""

echo "→ Step 5: Read the daemon API token..."
TOKEN=$(sudo docker exec "$DAEMON" cat /run/nettap-auth/daemon-token 2>/dev/null || echo "")
if [ -n "$TOKEN" ]; then
    echo "   ✓ Token read"
else
    echo "   ✗ Could not read /run/nettap-auth/daemon-token (API checks below will fail)"
fi
echo ""

# GET a daemon endpoint from inside the daemon container.
api() {
    sudo docker exec "$DAEMON" curl -s --max-time 20 \
        -H "X-NetTap-Daemon-Token: $TOKEN" "http://localhost:8880$1" || echo ""
}

# Run a python3 snippet inside the daemon container on JSON from stdin.
in_daemon_py() {
    sudo docker exec -i "$DAEMON" python3 -c "$1" 2>/dev/null || echo "   ✗ could not parse response"
}

# Print $1 indented, or "✗ $2" when $1 is empty.
indent_or() {
    if [ -n "$1" ]; then
        # shellcheck disable=SC2001  # indents every line of multi-line output
        echo "$1" | sed 's/^/     /'
    else
        echo "     ✗ $2"
    fi
}

echo "→ Step 6: Current capture mode..."
MODE_JSON=$(api /api/capture/mode)
echo "   response: ${MODE_JSON:-<none>}"
MODE=$(echo "$MODE_JSON" | in_daemon_py '
import json, sys
try:
    print(json.load(sys.stdin).get("mode", ""))
except Exception:
    print("")
')
echo "   mode: ${MODE:-unknown}"
echo ""

ROUTING_ACTIVE="false"
LAN_IFACE=""
UPSTREAM_GW=""

echo "→ Step 7: DHCP gateway preflight and status..."
if [ "$MODE" = "dhcp_gateway" ]; then
    echo "   Preflight (sends one DHCP discover to look for other DHCP servers, ~3 s)..."
    api /api/capture/dhcp/preflight | in_daemon_py '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("   ✗ preflight: no JSON response")
    sys.exit(0)
if "error" in d:
    print("   ✗ preflight error: %s" % d["error"])
    sys.exit(0)
up = d.get("upstream") or {}
print("   interface=%s subnet=%s gateway_ip=%s" % (d.get("interface"), d.get("subnet"), d.get("gateway_ip")))
print("   upstream=%s via %s" % (up.get("address", "-"), up.get("gateway", "-")))
print("   firewall_backend=%s ip_forward=%s ipv6_router_advertisements=%s" % (
    d.get("firewall_backend"), d.get("ip_forward"), d.get("ipv6_router_advertisements")))
for s in d.get("other_dhcp_servers") or []:
    print("   other DHCP server: %s (offered %s)" % (s.get("server_ip"), s.get("offered_ip")))
for c in d.get("subnet_conflicts") or []:
    print("   subnet conflict: %s" % c)
for c in d.get("checks") or []:
    mark = "✓" if c.get("passed") else ("✗" if c.get("blocking") else "!")
    print("   %s %s: %s" % (mark, c.get("name"), c.get("message", "")))
print("   ready=%s" % d.get("ready"))
'
    echo ""
    echo "   Status..."
    STATUS_JSON=$(api /api/capture/dhcp/status)
    echo "$STATUS_JSON" | in_daemon_py '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("   ✗ status: no JSON response")
    sys.exit(0)
if "error" in d:
    print("   ✗ status error: %s" % d["error"])
    sys.exit(0)
up = d.get("upstream") or {}
print("   interface=%s subnet=%s gateway_ip=%s upstream=%s via %s" % (
    d.get("interface"), d.get("subnet"), d.get("gateway_ip"), up.get("address", "-"), up.get("gateway", "-")))
print("   routing_active=%s dhcp_enabled=%s dhcp_server_running=%s" % (
    d.get("routing_active"), d.get("dhcp_enabled"), d.get("dhcp_server_running")))
leases = d.get("leases") or []
print("   leases: %d" % len(leases))
for l in leases[:10]:
    print("     %-17s %-15s %s" % (l.get("mac"), l.get("ip"), l.get("hostname") or "-"))
for i in d.get("issues") or []:
    print("   ! issue: %s" % i)
'
    # One line for this script: "<routing_active> <interface> <upstream gateway>"
    read -r ROUTING_ACTIVE LAN_IFACE UPSTREAM_GW <<< "$(echo "$STATUS_JSON" | in_daemon_py '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
up = d.get("upstream") or {}
print("%s %s %s" % (str(d.get("routing_active") is True).lower(), d.get("interface") or "-", up.get("gateway") or "-"))
')"
    # Only use values that look like an interface name / IPv4 address on the host.
    case "$LAN_IFACE" in '' | *[!A-Za-z0-9._-]*) LAN_IFACE="" ;; esac
    case "$UPSTREAM_GW" in '' | *[!0-9.]*) UPSTREAM_GW="" ;; esac
else
    echo "   Mode is not dhcp_gateway — skipped (set it in the setup wizard, then enable it on Go Live)"
fi
echo ""

echo "→ Step 8: Capture settings each capture container runs with..."
echo "   /etc/nettap/capture.env on the host:"
indent_or "$(sudo cat /etc/nettap/capture.env 2>/dev/null)" "missing — capture containers use the compose env"
for c in "${CAPTURE_CONTAINERS[@]}"; do
    echo "   $c:"
    indent_or "$(sudo docker exec "$c" sh -c "tr '\0' '\n' < /proc/1/environ" 2>/dev/null \
        | grep -E '^(PCAP_IFACE|PCAP_FILTER|CAPTURE_FILTER)=')" \
        "could not read the environment (container not running?)"
done
echo ""

echo "→ Step 9: Routing checks..."
if [ "$ROUTING_ACTIVE" = "true" ]; then
    echo "   Firewall rules tagged nettap-dhcp-gateway:"
    indent_or "$(sudo iptables -S DOCKER-USER 2>/dev/null | grep nettap-dhcp-gateway)" "no DOCKER-USER rules found"
    indent_or "$(sudo iptables -t nat -S POSTROUTING 2>/dev/null | grep nettap-dhcp-gateway)" "no POSTROUTING rule found"
    indent_or "$(sudo iptables -S OUTPUT 2>/dev/null | grep nettap-dhcp-gateway)" "no OUTPUT redirect-drop rule found"
    echo ""
    if [ -n "$LAN_IFACE" ]; then
        echo "   Addresses on $LAN_IFACE:"
        indent_or "$(ip -4 addr show dev "$LAN_IFACE" 2>&1)" "could not read $LAN_IFACE"
    else
        echo "   ✗ LAN interface unknown"
    fi
    echo ""
    if [ -n "$UPSTREAM_GW" ]; then
        echo "   RTT to the router ($UPSTREAM_GW), capture running:"
        indent_or "$(ping -c 20 -q "$UPSTREAM_GW" 2>&1 | tail -2)" "ping failed"
    else
        echo "   ✗ Upstream gateway unknown — skipped router RTT"
    fi
    echo "   RTT to 1.1.1.1, capture running:"
    indent_or "$(ping -c 20 -q 1.1.1.1 2>&1 | tail -2)" "ping failed"
else
    echo "   Routing is not active — skipped (enable DHCP gateway mode on the Go Live page first)"
fi
echo ""

echo "→ Step 10: Throughput test (run it yourself from a client)..."
echo "   1. On a computer with a static address on the router's network, start: iperf3 -s"
echo "   2. On a device that got a 10.77.0.x address from NetTap, run both:"
echo "        iperf3 -c <that computer's IP> -t 30"
echo "        iperf3 -c <that computer's IP> -t 30 -R"
echo "   Expect close to your normal LAN speed; compare with the same test with NetTap off."
echo ""

echo "→ Step 11: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" \
    | grep -E "nettap-web|nettap-storage-daemon|nettap-zeek-live|nettap-suricata-live|nettap-arkime-live|nettap-pcap-capture"
echo ""

echo "=== Deploy Complete ==="
echo "Open the dashboard, go to Go Live, and check the DHCP gateway page."
