#!/usr/bin/env bash
# Verify NetTap mirror (SPAN) capture on the device.
# Read-only apart from pulling the checked-out branch: it changes no network
# config, no capture mode and no containers. Run it after choosing Mirror in
# the setup wizard and turning on mirroring on the switch, and again after a
# reboot.
#
# Usage (as the normal user, not with sudo):
#   bash scripts/remote/verify-mirror-mode.sh            # NIC from capture.env
#   bash scripts/remote/verify-mirror-mode.sh enp2s0     # or name it
set -u

REPO_DIR="/home/nettap/NetTap"
DAEMON="nettap-storage-daemon"
# OLD CODE START — 2026-11-02: arkime-live is off by default (compose profile "arkime", #44)
# CAPTURE_CONTAINERS=(nettap-zeek-live nettap-suricata-live nettap-arkime-live nettap-pcap-capture)
# OLD CODE END
CAPTURE_CONTAINERS=(nettap-zeek-live nettap-suricata-live nettap-pcap-capture)
SAMPLE_SECONDS=10
# A non-mirror port sees broadcast/multicast and only the odd flooded unicast
# frame; a working uplink mirror sees a steady stream of other hosts' unicast.
MIN_UNICAST_FRAMES=50
FAILS=0

ok()   { echo "   ✓ $*"; }
warn() { echo "   ! $*"; }
fail() { echo "   ✗ $*"; FAILS=$((FAILS + 1)); }

echo "=== Verify mirror-mode capture ==="
echo ""

echo "→ Step 1: Pull latest code..."
cd "$REPO_DIR" || { echo "   ✗ $REPO_DIR not found"; exit 1; }
# Pull whatever branch the device runs, so the script outlives its own branch.
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ -n "$BRANCH" ] && [ "$BRANCH" != "HEAD" ]; then
    git pull origin "$BRANCH" || warn "git pull failed — checking the running stack anyway"
    ok "Code: $BRANCH @ $(git log --oneline -1)"
else
    warn "Detached HEAD — skipped git pull"
fi
echo ""

echo "→ Step 2: Wait for daemon and web containers to become healthy..."
for i in $(seq 1 30); do
    WEB_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' nettap-web 2>/dev/null || echo "unknown")
    DAEMON_STATUS=$(sudo docker inspect --format='{{.State.Health.Status}}' "$DAEMON" 2>/dev/null || echo "unknown")
    if [ "$WEB_STATUS" = "healthy" ] && [ "$DAEMON_STATUS" = "healthy" ]; then
        ok "Both containers healthy"
        break
    fi
    echo "   waiting... web=$WEB_STATUS daemon=$DAEMON_STATUS ($i/30)"
    sleep 5
done
if [ "$WEB_STATUS" != "healthy" ] || [ "$DAEMON_STATUS" != "healthy" ]; then
    fail "Containers not healthy after 2.5 min: web=$WEB_STATUS daemon=$DAEMON_STATUS"
fi
echo ""

echo "→ Step 3: Capture mode..."
TOKEN=$(sudo docker exec "$DAEMON" cat /run/nettap-auth/daemon-token 2>/dev/null || echo "")
[ -n "$TOKEN" ] || warn "Could not read the daemon API token — API check below will fail"
MODE_JSON=$(sudo docker exec "$DAEMON" curl -s --max-time 20 \
    -H "X-NetTap-Daemon-Token: $TOKEN" http://localhost:8880/api/capture/mode 2>/dev/null || echo "")
echo "   /api/capture/mode: ${MODE_JSON:-<no response>}"
case "$MODE_JSON" in
    *'"mode": "mirror"'* | *'"mode":"mirror"'*) ok "Daemon is in mirror mode" ;;
    *) fail "Daemon is not in mirror mode — choose Mirror in the setup wizard" ;;
esac
echo "   /etc/nettap/capture-mode.conf:"
sudo sed 's/^/     /' /etc/nettap/capture-mode.conf 2>/dev/null || fail "capture-mode.conf missing"
echo "   /etc/nettap/capture.env:"
sudo sed 's/^/     /' /etc/nettap/capture.env 2>/dev/null || fail "capture.env missing"
echo ""

NIC="${1:-$(sudo sed -n 's/^PCAP_IFACE=//p' /etc/nettap/capture.env 2>/dev/null | tail -1)}"
case "$NIC" in
    '' | *[!A-Za-z0-9._-]*)
        fail "No valid capture NIC (pass it as the first argument, e.g. enp2s0)"
        echo ""
        echo "=== Verify stopped: $FAILS problem(s) ==="
        exit 1
        ;;
esac
echo "   Capture NIC: $NIC"
echo ""

echo "→ Step 4: Capture NIC state ($NIC)..."
if ! ip link show "$NIC" >/dev/null 2>&1; then
    fail "$NIC does not exist on this host"
else
    ethtool -i "$NIC" 2>/dev/null | grep -E '^(driver|version|firmware-version):' | sed 's/^/     /'
    # An admin-DOWN port reports no speed even with a good cable (2026-11-01 G11 run)
    if ! ip -o link show "$NIC" | grep -qE '[<,]UP[,>]'; then
        fail "$NIC is switched off (admin DOWN) — NetTap's mirror setup didn't bring it up (sudo docker logs nettap-storage-daemon 2>&1 | grep -i mirror)"
    else
        SPEED=$(cat "/sys/class/net/$NIC/speed" 2>/dev/null || echo "?")
        echo "     link speed: ${SPEED} Mb/s"
        case "$SPEED" in
            2500) ;;
            "?"|-1|"") warn "Port is up but has no link — check the cable and that the switch port is enabled" ;;
            *) warn "Link is ${SPEED} Mb/s, not 2.5 Gb/s — check the cable and the switch port speed" ;;
        esac
    fi

    ADDRS=$(ip -o addr show dev "$NIC" 2>/dev/null)
    if [ -z "$ADDRS" ]; then ok "No IP addresses"; else fail "Has addresses (capture NIC must have none):"; echo "$ADDRS" | sed 's/^/     /'; fi

    if ip link show "$NIC" | grep -q PROMISC; then ok "Promiscuous mode on"; else fail "Promiscuous mode off"; fi

    OFFLOADS_ON=$(ethtool -k "$NIC" 2>/dev/null \
        | grep -E '^(tcp-segmentation-offload|generic-segmentation-offload|generic-receive-offload|large-receive-offload|rx-vlan-offload): on' \
        | grep -v '\[fixed\]')
    if [ -z "$OFFLOADS_ON" ]; then ok "TSO/GSO/GRO/LRO/rx-vlan offloads off"; else fail "Offloads still on:"; echo "$OFFLOADS_ON" | sed 's/^/     /'; fi

    RING=$(ethtool -g "$NIC" 2>/dev/null | awk '/^Current hardware settings/ {c=1} c && /^RX:/ {print $2; exit}')
    echo "     RX ring: ${RING:-unknown} (NetTap asks for 4096; Realtek r8169 may keep its default)"
fi
echo ""

echo "→ Step 5: Traffic on $NIC (${SAMPLE_SECONDS}s sample)..."
RX0=$(cat "/sys/class/net/$NIC/statistics/rx_packets" 2>/dev/null || echo 0)
B0=$(cat "/sys/class/net/$NIC/statistics/rx_bytes" 2>/dev/null || echo 0)
sleep "$SAMPLE_SECONDS"
RX1=$(cat "/sys/class/net/$NIC/statistics/rx_packets" 2>/dev/null || echo 0)
B1=$(cat "/sys/class/net/$NIC/statistics/rx_bytes" 2>/dev/null || echo 0)
PPS=$(( (RX1 - RX0) / SAMPLE_SECONDS ))
MBPS=$(( (B1 - B0) * 8 / SAMPLE_SECONDS / 1000000 ))
echo "     ${PPS} packets/s, ~${MBPS} Mb/s"
if (( RX1 > RX0 )); then ok "RX counter is climbing"; else fail "No packets received — is the cable on the switch's mirror destination port?"; fi

if command -v tcpdump >/dev/null 2>&1; then
    UNICAST=$(sudo timeout "$SAMPLE_SECONDS" tcpdump -i "$NIC" -l -nn -q -c 500 'not broadcast and not multicast' 2>/dev/null | wc -l)
    echo "     unicast frames in ${SAMPLE_SECONDS}s: ${UNICAST}"
    if (( UNICAST >= MIN_UNICAST_FRAMES )); then
        ok "Seeing other hosts' unicast traffic — the mirror is working"
    elif (( UNICAST > 0 )); then
        warn "Only ${UNICAST} unicast frames — mirroring may not be on (a normal port sees mostly broadcast/multicast)"
    else
        fail "No unicast traffic — turn on mirroring for this port in UniFi (source = the uplink port)"
    fi
else
    warn "tcpdump not installed — skipped the unicast check (sudo apt-get install -y tcpdump)"
fi

echo "   Drop / error counters (non-zero only):"
DROPS=$(ethtool -S "$NIC" 2>/dev/null | grep -iE 'miss|drop|err|fifo|over' | awk '$2 != 0')
ip -s link show "$NIC" 2>/dev/null | awk '/RX:/ {getline; print "     ip: rx_dropped=" $4 " rx_missed_or_overrun=" $5}'
if [ -z "$DROPS" ]; then ok "No NIC drop/error counters above zero"; else warn "Non-zero counters (watch whether they grow):"; echo "$DROPS" | sed 's/^/     /'; fi
echo ""

echo "→ Step 6: Boot persistence..."
NETPLAN_FILE="/etc/netplan/10-nettap-mirror-${NIC}.yaml"
if sudo test -f "$NETPLAN_FILE"; then ok "$NETPLAN_FILE exists"; else fail "$NETPLAN_FILE missing — the NIC may get DHCP after a reboot"; fi
# Netplan applies files in name order and later files win, so the installer's
# 50-cloud-init.yaml would override the 10-nettap-mirror file for this NIC.
OTHER_NETPLAN=$(sudo grep -l -w "$NIC" /etc/netplan/*.yaml 2>/dev/null | grep -v "/10-nettap-mirror-${NIC}.yaml$")
if [ -z "$OTHER_NETPLAN" ]; then
    ok "No other netplan file configures $NIC"
else
    fail "$NIC is also configured in (later files override NetTap's — remove $NIC from them):"
    echo "$OTHER_NETPLAN" | sed 's/^/     /'
fi
for unit in nettap-mirror.service nettap.service; do
    # is-enabled prints "not-found" itself and exits non-zero, so don't append a fallback
    STATE=$(systemctl is-enabled "$unit" 2>/dev/null | head -1)
    if [ "$STATE" = "enabled" ]; then ok "$unit enabled"; else fail "$unit is ${STATE:-missing}"; fi
done
echo ""

echo "→ Step 7: Management link..."
DEFAULT_ROUTE=$(ip route show default 2>/dev/null | head -1)
echo "     default route: ${DEFAULT_ROUTE:-<none>}"
case " $DEFAULT_ROUTE " in
    *" dev $NIC "*) fail "The default route uses the capture NIC — management must be on the other port" ;;
    "  ") fail "No default route — the management NIC has no network" ;;
    *) ok "Management traffic is on another NIC" ;;
esac
echo ""

echo "→ Step 8: Interface each capture container listens on..."
for c in "${CAPTURE_CONTAINERS[@]}"; do
    IFACE=$(sudo docker exec "$c" sh -c "tr '\0' '\n' < /proc/1/environ" 2>/dev/null | sed -n 's/^PCAP_IFACE=//p')
    if [ "$IFACE" = "$NIC" ]; then ok "$c → $IFACE"; else fail "$c → ${IFACE:-<not running?>} (expected $NIC)"; fi
done
echo ""

echo "→ Step 9: Container status..."
sudo docker ps --format "table {{.Names}}\t{{.Status}}" \
    | grep -E "nettap-web|nettap-storage-daemon|nettap-opensearch|nettap-zeek-live|nettap-suricata-live|nettap-arkime-live|nettap-pcap-capture"
echo ""

if (( FAILS == 0 )); then
    echo "=== Verify complete: all checks passed ==="
    echo "Open the dashboard; new connections should appear within a few minutes."
else
    echo "=== Verify complete: $FAILS problem(s) — see ✗ lines above ==="
fi
