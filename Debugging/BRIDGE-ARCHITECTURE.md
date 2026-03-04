# NetTap Bridge Architecture Analysis

**Date:** 2026-03-03
**Status:** DEEP SYSTEMATIC INVESTIGATION COMPLETE
**Scope:** Full bridge data flow, isolation, health monitoring, bypass mode, and integration

---

## Executive Summary

NetTap is a **transparent Layer 2 inline tap** appliance built around a Linux software bridge (`br0`) that sits between an ISP modem (WAN) and home router (LAN). The bridge:

1. **Forwards all L2 frames** between WAN and LAN transparently — no IP stack involvement
2. **Remains isolated from Docker** — capture containers use `network_mode: host` while bridge resides on host kernel
3. **Survives daemon crashes** — hardened kernel settings prevent userspace failures from breaking L2 forwarding
4. **Supports dynamic bypass** — can disable capture temporarily without disrupting traffic flow

This document provides a **complete end-to-end analysis** of the bridge topology, data pipeline, health monitoring, and known gaps.

---

## 1. Physical Topology

### Hardware Configuration

```
ISP Modem
    ↓
    │
    eth0 (WAN interface)
    │
    └─────────────────────┐
                          │
                     br0 (bridge)
                          │
    ┌─────────────────────┘
    │
    eth1 (LAN interface)
    ↓
Home Router
```

**Assumptions & Constraints:**
- **Default NICs:** `eth0` (WAN), `eth1` (LAN) — overridable via `--wan` and `--lan` flags
- **Bridge name:** Always `br0` — hardcoded, not configurable
- **Management interface (optional):** 3rd NIC, Wi-Fi, or VLAN for dashboard access
- **MTU:** Inherited from member NICs; no explicit MTU override in setup script
- **IPv6:** Disabled on bridge (`net.ipv6.conf.br0.disable_ipv6=1`) to remain invisible

### NIC Discovery & Selection

**Script:** `/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/scripts/bridge/setup-bridge.sh`
**API:** `/daemon/api/nic_discovery.py`

**Discovery Flow:**

```python
# Daemon reads from sysfs (mounted from host via Docker volume)
HOST_SYS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")

# Each interface file has properties:
# - /sys/class/net/<iface>/address       → MAC address
# - /sys/class/net/<iface>/carrier       → Link status (0/1)
# - /sys/class/net/<iface>/operstate     → Operational state (up/down)
# - /sys/class/net/<iface>/speed         → Link speed in Mbps
# - /sys/class/net/<iface>/device/driver → Kernel driver name
# - /sys/class/net/<iface>/wireless      → Indicates wireless interface
# - /sys/class/net/<iface>/phy80211      → Indicates wireless interface

# Classification logic:
# - Exclude: docker*, br-*, veth*, virbr*, flannel*, cni*, cali* (container/virtual)
# - Type: "loopback" (name==lo), "wireless" (has wireless/phy80211), "virtual" (no device), "ethernet" (has device)

# IPv4 addresses: Resolves via:
# - Try: nsenter -t 1 -n -- ip -j -4 addr show (from within Docker container)
# - Fallback: ip -j -4 addr show (if not in container)
```

**Issues & Gaps:**

1. **NIC detection reliability** — relies on sysfs symlinks being correctly mounted
   - Full `/sys` must be mounted (not just `/sys/class/net`)
   - Dangling symlinks inside container can cause failures
   - Workaround: docker-compose mounts `/sys:/host/sys:ro`

2. **No persistent NIC assignment** — if NICs are hot-swapped, bridge may become invalid
   - Netplan config embeds interface names → static assignment
   - No fallback to MAC address matching

3. **Speed detection fails when link is down** — speed returns "-1", UI shows ""
   - Not a critical issue, but degrades user experience during initial setup

---

## 2. Bridge Setup Flow

### Step-by-Step Setup

**Script:** `scripts/bridge/setup-bridge.sh --persist`
**Location:** `/Volumes/ExtraStrg_RAID1/Mega Sync/NetTap/scripts/bridge/setup-bridge.sh`

#### Phase 1: Pre-Flight Validation

```bash
# Check interfaces exist and are different
if [[ "$WAN_INTERFACE" == "$LAN_INTERFACE" ]]; then
    error "WAN and LAN interfaces must be different"
fi

# Check both NICs are available in /sys/class/net
for iface in eth0 eth1; do
    if ! ip link show "$iface" >/dev/null; then
        error "Interface $iface not found"
    fi
done

# Check neither NIC is already in a different bridge
if [[ -d "/sys/class/net/${iface}/master" ]]; then
    current_bridge=$(basename "$(readlink -f "$master_path")")
    if [[ "$current_bridge" != "br0" ]]; then
        error "Interface is already in bridge '$current_bridge'"
    fi
fi

# Warn if interfaces have IP addresses (they shouldn't on data path)
if ip addr show "$iface" | grep -q "inet "; then
    warn "Interface $iface has IP address — bridge interfaces should not have IPs"
fi

# Load kernel bridge module
modprobe bridge
```

**Potential Issues:**
- NetworkManager may be managing the NICs — script warns and suggests disabling it
- Some VPS/cloud providers don't allow bridge creation at all

#### Phase 2: Create Bridge

```bash
# Create the bridge interface
ip link add name br0 type bridge

# Disable STP (Spanning Tree Protocol) — we're a transparent tap, not a switch
ip link set br0 type bridge stp_state 0

# Performance tuning for inline tap:
ip link set br0 type bridge forward_delay 0        # No learning delay
ip link set br0 type bridge mcast_snooping 0       # Pass multicast transparently
ip link set br0 type bridge ageing_time 0          # Don't expire MAC table entries

# Add WAN and LAN interfaces to bridge
ip link set eth0 up
ip link set eth0 master br0
ip link set eth1 up
ip link set eth1 master br0

# Enable promiscuous mode (required for packet capture)
ip link set eth0 promisc on
ip link set eth1 promisc on
```

#### Phase 3: NIC Performance Tuning

```bash
# Disable hardware offloads that interfere with packet capture
ethtool -K eth0 tso off gso off gro off lro off
ethtool -G eth0 rx 4096                    # Increase RX ring buffer

# Same for LAN
ethtool -K eth1 tso off gso off gro off lro off
ethtool -G eth1 rx 4096
```

**Why These Matter:**
- **TSO/GSO/GRO/LRO:** Hardware combines/segments packets — Zeek/Suricata need to see individual frames
- **Ring buffers:** Captures are bursty — larger buffers reduce loss during spikes

#### Phase 4: Disable Netfilter on Bridged Frames

```bash
# Critical: prevent Docker's iptables rules from interfering with bridge
sysctl -w net.bridge.bridge-nf-call-iptables=0
sysctl -w net.bridge.bridge-nf-call-ip6tables=0
sysctl -w net.bridge.bridge-nf-call-arptables=0
```

**Why This Is Critical:**
- By default, bridged frames pass through the kernel's iptables firewall
- Docker adds rules to restrict container networking
- These rules can inadvertently DROP bridged traffic → no internet
- Setting to `0` = bridge operates at pure L2, bypassing all netfilter

#### Phase 5: Bring Bridge UP

```bash
ip link set br0 up
sysctl -w net.ipv6.conf.br0.disable_ipv6=1  # Stay invisible
```

#### Phase 6: Persistence (Netplan + Systemd)

**Netplan Config:** `/etc/netplan/10-nettap-bridge.yaml`

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: false
      dhcp6: false
      optional: true
    eth1:
      dhcp4: false
      dhcp6: false
      optional: true
  bridges:
    br0:
      interfaces:
        - eth0
        - eth1
      dhcp4: false
      dhcp6: false
      parameters:
        stp: false
        forward-delay: 0
```

**Known Issue (Systemd Bug LP#1874022):**
- netplan/networkd have a race condition where bridges without carrier end up administratively DOWN despite `ActivationPolicy=always-up`
- Even though netplan is written, running `netplan apply` during install can bring the bridge DOWN
- **Workaround:** Don't run `netplan apply` during installation; instead, use a systemd service to force it UP at boot

**Systemd Service:** `/etc/systemd/system/nettap-bridge.service`

```ini
[Unit]
Description=NetTap bridge UP and promiscuous mode
After=systemd-networkd.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/ip link set br0 up
ExecStart=/usr/sbin/ip link set eth0 promisc on
ExecStart=/usr/sbin/ip link set eth1 promisc on

[Install]
WantedBy=multi-user.target
```

This workaround forces the bridge UP and enables promisc at boot, working around the networkd race condition.

**Sysctl Persistence:** `/etc/sysctl.d/99-nettap-bridge.conf`

---

## 3. Capture Pipeline

### Overview

```
Bridge (br0) captures packets ←→ Promiscuous mode enabled on eth0/eth1
                 ↓
         ┌───────┴────────┬────────────┬──────────┐
         ↓                ↓            ↓          ↓
    Zeek Live      Suricata Live   Arkime Live  PCAP Capture
    (metadata)      (alerts)       (full PCAP)   (raw PCAP)
         ↓                ↓            ↓          ↓
    zeek/live/      /var/log/      pcap-data/   pcap-data/
                    suricata/
         ↓                ↓            ↓          ↓
      Filebeat          Filebeat     Arkime     (PCAP stored)
         ↓                ↓            ↓
         └────────┬───────┴────────────┘
                  ↓
            Logstash (enrichment)
                  ↓
            OpenSearch (indexing)
```

### Capture Containers Configuration

**All capture services use `network_mode: host`** — this is critical:

```yaml
zeek-live:
  image: ghcr.io/idaholab/malcolm/zeek:26.02.0
  network_mode: host              # Access to host's interfaces
  cap_add:
    - NET_ADMIN                    # Raw socket permissions
    - NET_RAW                      # Packet capture
    - SYS_NICE                     # Scheduling priority
  environment:
    PCAP_IFACE: "${PCAP_IFACE:-br0}"   # Capture interface
    ZEEK_LIVE_CAPTURE: "true"
    ZEEK_LOG_PATH: "/zeek/live"
  volumes:
    - zeek-live-logs:/zeek/live    # Logs shared with Filebeat
    - ../config/zeek/nettap.zeek:/opt/zeek/share/zeek/site/local.zeek:ro
```

**Key Points:**

1. **Interface:** All read from `br0` by default (can override with `PCAP_IFACE`)
2. **Capabilities:**
   - `NET_ADMIN`: Configure promiscuous mode, set packet filters
   - `NET_RAW`: Open raw sockets for packet capture
   - `SYS_NICE`: Set CPU affinity and scheduling priority
3. **No cap_drop: ALL** — Malcolm entrypoint uses `su` (setuid binary) which fails silently with `no-new-privileges`
4. **Log Volume:** zeek-live-logs and suricata-live-logs are shared with Filebeat for log shipping

### Zeek Configuration

**Custom config:** `config/zeek/nettap.zeek`

- Defines `local_nets` for internal traffic classification
- Disables PCAP extraction (we capture separately with Arkime)
- Sets log rotation

### Suricata Configuration

**Custom config:** `config/suricata/nettap.yaml`

- Uses Emerging Threats ruleset
- Runs in `workers` runmode (multi-threaded)
- Auto-updates rules

### Arkime Configuration

- Captures full PCAP sessions
- Stores in `pcap-data/` volume
- Indexes sessions into OpenSearch for searchability

### Data Flow Isolation

**Critical:** Capture containers and storage daemon don't interact directly:

```
Zeek/Suricata/Arkime (network_mode: host)
    ↓
    Write to shared Docker volumes
    ↓
Filebeat/Logstash (default network)
    ↓
OpenSearch (default network, only internal)
```

This isolation ensures that if storage daemon or database crashes, capture continues uninterrupted.

---

## 4. Health Monitoring Architecture

### Daemon's Challenge: Docker Isolation

The storage daemon runs in **Docker without host networking**:

```
Docker Container (nettap-storage-daemon)
    │
    ├─ Can't see /sys/class/net directly (sees container interfaces)
    ├─ Can't call systemctl (no systemd socket)
    ├─ Can't run ip commands directly
    └─ Solution: nsenter -t 1 -n -- <command> (enter host network namespace)
```

### Sysfs Mounting

**docker-compose.yml volumes:**

```yaml
nettap-storage-daemon:
  volumes:
    - /sys:/host/sys:ro                    # Full sysfs (including symlinks)
    - /sys/class/leds:/host/sys/class/leds # Writable LED timer override
    - pid: "host"                          # Allows nsenter -t 1
```

**Why full `/sys` and not just `/sys/class/net`?**

```
/sys/class/net/eth0 → /sys/devices/pci.../net/eth0 (symlink)
```

If we mount only `/sys/class/net`, the symlink target is dangling inside the container. All file reads (MAC, carrier, speed, etc.) fail silently.

### Bridge Health Monitor

**File:** `daemon/services/bridge_health.py`

**What It Monitors:**

1. **Bridge state** — reads `/host/sys/class/net/br0/operstate` → "up" | "down" | "unknown" | "not_configured"
2. **NIC carrier** — reads `/host/sys/class/net/eth0/carrier` and `/host/sys/class/net/eth1/carrier` → 0 | 1
3. **Packet counters** — reads `/host/sys/class/net/br0/statistics/{rx_bytes, tx_bytes, rx_packets, tx_packets}`
4. **Bypass state** — checks if `/var/run/nettap-bypass-active` exists
5. **Watchdog status** — runs `systemctl is-active nettap-watchdog` (via nsenter or direct)

**Health Status Logic:**

```python
def _determine_health_status(bridge_state, wan_link, lan_link, bypass_active):
    if bridge_state == "not_configured":
        return "not_configured"

    if bypass_active:
        return "bypass"

    if bridge_state == "down" or (not wan_link and not lan_link):
        return "down"

    if bridge_state == "unknown" or not wan_link or not lan_link:
        return "degraded"

    return "normal"  # Bridge up, both NICs linked, no bypass
```

**API Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/bridge/health` | GET | Current health snapshot |
| `/api/bridge/history?limit=100` | GET | Historical data |
| `/api/bridge/stats` | GET | Aggregated statistics |
| `/api/bridge/bypass/enable` | POST | Activate bypass |
| `/api/bridge/bypass/disable` | POST | Deactivate bypass |
| `/api/bridge/bypass/status` | GET | Current bypass state |

**Refresh Rate:** 30s intervals (2880 history entries = 24 hours of monitoring)

### Internet Health Monitor

**File:** `daemon/services/internet_health.py`

**Separate from bridge monitoring** — tracks connectivity health:

```
- Latency: Ping 8.8.8.8, 1.1.1.1, 208.67.222.222 → median RTT
- DNS: Resolve google.com, cloudflare.com, example.com → median lookup time
- Packet Loss: Ping 10x, compute loss %

Status determination:
- down: latency=None AND dns=None, OR loss≥50%
- degraded: latency≥100ms OR dns≥500ms OR loss≥5%
- healthy: latency<100ms AND dns<500ms AND loss<5%
```

### Web UI Integration

**Component:** `web/src/lib/components/BridgeStatus.svelte`

**Fetches:**
- `/api/bridge/health` every 15 seconds
- `/api/bridge/bypass/status` concurrently

**Displays:**
- Network diagram (WAN → br0 → LAN) with link colors
- Latency, RX/TX rates, uptime
- Bypass toggle with confirmation dialog
- Health status badge and issue list

**API Client:** `web/src/lib/api/bridge.ts` — wraps daemon endpoints for frontend

---

## 5. Bypass Mode

### What Is Bypass?

Bypass mode **disables all packet capture** while keeping the bridge forwarding:

```
Normal Mode:
  WAN ─→ [Zeek/Suricata/Arkime capturing] ─→ LAN  ← ~5-10ms latency

Bypass Mode:
  WAN ─────→ [Pure L2 forwarding, no capture] ─→ LAN  ← ~1ms latency
```

**Use Cases:**
1. Maintenance windows (update capture rules without stopping traffic)
2. Troubleshooting (isolate whether capture is degrading performance)
3. Emergency bypass (if capture is consuming all CPU)

### Implementation

**Script:** `scripts/bridge/bypass-mode.sh`

**Enable Bypass:**

```bash
# Step 1: Stop capture services
docker compose -f docker/docker-compose.yml stop zeek-live suricata-live arkime-live pcap-capture

# Step 2: Flush ebtables rules (clean L2 path)
ebtables -F && ebtables -X && ebtables -t nat -F && ebtables -t nat -X

# Step 3: Disable promiscuous mode (stop passive capture)
ip link set eth0 promisc off
ip link set eth1 promisc off

# Step 4: Write state file (signal to daemon and UI)
echo "bypass active" > /var/run/nettap-bypass-active
```

**Disable Bypass:**

```bash
# Step 1: Re-enable promiscuous mode
ip link set eth0 promisc on
ip link set eth1 promisc on

# Step 2: Start capture services
docker compose -f docker/docker-compose.yml start zeek-live suricata-live arkime-live pcap-capture

# Step 3: Remove state file
rm -f /var/run/nettap-bypass-active
```

### State Persistence

**State file:** `/var/run/nettap-bypass-active`

- Created when bypass is enabled
- Removed when bypass is disabled
- Checked by daemon on every health check
- Consumed by UI to show bypass badge

**Limitations:**
- `/var/run/` is ephemeral (lost on reboot)
- If host crashes in bypass mode, bypass is exited automatically
- No persistent bypass scheduling (can add systemd timer in future)

### Systemd Service for Scheduled Bypass

Optional service for maintenance windows:

```ini
[Unit]
Description=NetTap Software Bypass Mode

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/path/to/bypass-mode.sh --enable
ExecStop=/path/to/bypass-mode.sh --disable
TimeoutStartSec=120
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

Usage:
```bash
systemctl start nettap-bypass    # Enter bypass
systemctl stop nettap-bypass     # Exit bypass
```

---

## 6. Bridge Hardening for Resilience

### Philosophy

Bridge is a **kernel datapath** — if configured correctly, it continues forwarding even if all userspace daemons (Zeek, Suricata, Docker, daemon itself) crash.

**Script:** `scripts/bridge/harden-bridge.sh`

### Sysctl Settings

**File:** `/etc/sysctl.d/99-nettap-bridge-hardening.conf`

```bash
# Disable netfilter on bridged frames — critical
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-arptables = 0

# Enable IP forwarding (belt-and-suspenders)
net.ipv4.ip_forward = 1
```

**Module auto-load:** `/etc/modules-load.d/nettap-br-netfilter.conf`

```
br_netfilter
```

Ensures `net.bridge.bridge-nf-call-*` sysctls are available at boot.

### Bridge-Specific Settings

Once bridge exists:

```bash
ip link set br0 type bridge stp_state 0          # Disable STP
ip link set br0 type bridge forward_delay 0      # No learning delay
ip link set br0 type bridge mcast_snooping 0     # Pass multicast transparently
```

### Scenario: What Happens If Docker Crashes?

```
Before hardening:
  Docker crashes → iptables rules orphaned → bridge-nf-call-iptables still ON
  → Bridged frames hit iptables → rules may DROP traffic → no internet

After hardening:
  Docker crashes → iptables rules orphaned → but bridge-nf-call-iptables = 0
  → Bridged frames bypass iptables entirely → traffic flows
```

### Validation

```bash
sudo scripts/bridge/harden-bridge.sh --check
```

Verifies:
- All sysctl settings are correct
- Persistent config files exist
- br_netfilter auto-load configured
- Bridge exists and STP is disabled

---

## 7. Known Issues & Gaps

### Critical Issues

| Issue | Impact | Workaround | Status |
|-------|--------|-----------|--------|
| **NIC detection fails if /sys not fully mounted** | Bridge won't be created | docker-compose mounts full `/sys` | MITIGATED |
| **Systemd race condition (LP#1874022)** | Bridge DOWN after reboot despite netplan | nettap-bridge.service forces UP | MITIGATED |
| **NetworkManager interferes with bridge** | Bridge config overwritten | Script tells user to disable NM | DOCUMENTED |

### Design Gaps

1. **No interface hot-swap detection**
   - If NICs are replaced, netplan still has old names
   - Bridge becomes invalid but setup wizard doesn't auto-detect
   - **Fix:** Add health check that compares bridge members with discovered interfaces

2. **NIC naming not persistent across MAC address changes**
   - Uses interface names (eth0/eth1) not MAC addresses
   - If NICs are swapped, bridge breaks
   - **Fix:** Store MAC address mapping and validate at boot

3. **Bypass state ephemeral**
   - Lost on reboot
   - Can't schedule bypass windows across reboots
   - **Fix:** Add optional persistent bypass schedule in future

4. **No explicit latency measurement**
   - Bridge health monitor "estimates" latency (returns 50µs by default)
   - Real measurement would require timestamped test packets through bridge
   - **Current behavior:** Acceptable for monitoring, not real performance data

5. **Watchdog service check unreliable**
   - Runs `systemctl is-active` inside container (limited privileges)
   - May report false negatives if systemctl unavailable
   - **Graceful degradation:** Returns false, issue added to health report

### Architectural Limitations

1. **Docker-isolated daemon can't directly interact with host network**
   - All sysfs reads must go through mounted volumes
   - All systemctl calls must use nsenter
   - **Trade-off:** Security (container isolation) vs. simplicity

2. **Capture containers isolated from storage daemon**
   - If daemon crashes, capture continues (good)
   - But daemon can't influence capture behavior directly (no shared memory)
   - **Trade-off:** Resilience vs. tight integration

3. **No persistent statistics across reboot**
   - History stored in daemon memory (daemon restarts on reboot)
   - Health history lost
   - **Future improvement:** Persist to OpenSearch

4. **Bridge state not reflected in OpenSearch**
   - Health data is independent of indexed logs
   - Can't correlate "bridge was down" with "no packets indexed"
   - **Future improvement:** Index health check results into OpenSearch

---

## 8. End-to-End Data Flow

### From ISP Modem to OpenSearch

```
1. PACKET ARRIVES ON WAN (eth0)
   ↓
2. KERNEL BRIDGE FORWARDS TO LAN (eth1)
   Promiscuous mode enabled → packets copied to capture sockets
   ↓
3. ZEEK (captures on br0, network_mode: host)
   Writes: zeek-live-logs/conn.log, dns.log, http.log, etc.
   ↓
4. SURICATA (captures on br0, network_mode: host)
   Writes: suricata-live-logs/eve.json (alerts)
   ↓
5. ARKIME (captures full PCAP on br0, network_mode: host)
   Writes: pcap-data/*.pcap
   Indexes sessions into OpenSearch
   ↓
6. FILEBEAT (reads log volumes in default network)
   Watches: zeek-live-logs/, suricata-live-logs/
   Forwards to Logstash on port 5044
   ↓
7. LOGSTASH (enrichment, default network)
   Parses JSON/TSV
   Adds GeoIP, hostname resolution
   Outputs to OpenSearch
   ↓
8. OPENSEARCH (default network)
   Indexes all logs and session data
   ↓
9. WEB UI QUERIES OPENSEARCH
   Fetches conn logs, alerts, sessions
   Displays on dashboard
```

**Key Points:**
- Capture (steps 1-5) uses **host networking** → can access any host interface
- Log processing (steps 6-8) uses **default Docker network** → container-to-container communication
- Data isolation ensures failure in one component doesn't cascade

---

## 9. Configuration Files & Persistence

| File | Purpose | Who Writes | Who Reads |
|------|---------|-----------|-----------|
| `/etc/netplan/10-nettap-bridge.yaml` | Bridge config at boot | setup-bridge.sh --persist | systemd-networkd |
| `/etc/systemd/system/nettap-bridge.service` | Force bridge UP (workaround) | setup-bridge.sh --persist | systemd |
| `/etc/sysctl.d/99-nettap-bridge.conf` | Netfilter disabling | setup-bridge.sh --persist | sysctl --system |
| `/etc/sysctl.d/99-nettap-bridge-hardening.conf` | Resilience settings | harden-bridge.sh | sysctl --system |
| `/etc/modules-load.d/nettap-br-netfilter.conf` | Load br_netfilter at boot | harden-bridge.sh | systemd |
| `/etc/NetworkManager/conf.d/99-nettap-unmanaged.conf` | Tell NM to leave bridge alone | setup-bridge.sh --persist | NetworkManager |
| `/var/run/nettap-bypass-active` | Bypass state (ephemeral) | bypass-mode.sh | daemon, UI |

---

## 10. Troubleshooting Flowchart

```
Bridge Status Check
│
├─ Bridge doesn't exist (not_configured)
│  └─ Run: scripts/bridge/setup-bridge.sh --persist
│     └─ If fails: Check if bridge kernel module loaded (modprobe bridge)
│
├─ Bridge DOWN
│  └─ Run: ip link show br0
│     └─ If IFF_UP not set: sudo ip link set br0 up
│     └─ If both NICs down: Check cable connections
│
├─ Bridge UP but NO TRAFFIC
│  ├─ Check promiscuous mode: ip link show eth0 | grep PROMISC
│  │  └─ If not set: sudo ip link set eth0 promisc on
│  │
│  ├─ Check netfilter not blocking: cat /proc/sys/net/bridge/bridge-nf-call-iptables
│  │  └─ If = 1: sudo sysctl -w net.bridge.bridge-nf-call-iptables=0
│  │
│  └─ Check iptables not dropping: sudo iptables -vnL | grep DROP
│     └─ If Docker rules: systemctl stop docker (test), verify traffic
│
├─ One NIC NO CARRIER (link down)
│  └─ Physical link issue: Check cable, switch port, NIC driver
│     └─ Verify with: ethtool eth0 | grep "Link detected"
│
└─ High latency / packet loss
   └─ Check sysctl offload settings
      └─ ethtool -k eth0 | grep off
```

---

## 11. Testing the Bridge

### Validation Test

```bash
# Test bridge exists and is up
scripts/bridge/setup-bridge.sh --validate-only

# Should show:
# [OK] Bridge br0 exists
# [OK] Bridge is UP
# [OK] STP disabled
# [OK] eth0 attached to br0
# [OK] eth1 attached to br0
# [OK] eth0 promiscuous mode on
# [OK] eth1 promiscuous mode on
```

### Bypass Test

```bash
# Check status
sudo scripts/bridge/bypass-mode.sh --status

# Enable bypass
sudo scripts/bridge/bypass-mode.sh --enable
# Should show: BYPASS (capture disabled)
# Verify: docker ps | grep zeek-live  # Should be stopped

# Disable bypass
sudo scripts/bridge/bypass-mode.sh --disable
# Should show: NORMAL (capture active)
# Verify: docker ps | grep zeek-live  # Should be running

# Verify traffic still flowing during bypass
# (ping router while in bypass mode — should work)
```

### Health Check Test

```bash
# Query health endpoint
curl -s http://localhost:8880/api/bridge/health | jq .

# Expected response:
# {
#   "bridge_state": "up",
#   "wan_link": true,
#   "lan_link": true,
#   "health_status": "normal",
#   "issues": [],
#   ...
# }
```

### Hardening Verification

```bash
# Check all hardening settings
sudo scripts/bridge/harden-bridge.sh --check

# Should show:
# [OK] net.bridge.bridge-nf-call-iptables = 0
# [OK] net.bridge.bridge-nf-call-ip6tables = 0
# [OK] net.bridge.bridge-nf-call-arptables = 0
# [OK] net.ipv4.ip_forward = 1
# [OK] Persistent config exists
# [OK] br_netfilter auto-load configured
# [OK] Bridge br0 exists
# [OK] STP disabled on br0
```

---

## 12. Summary of Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Linux software bridge (br0)** | Simple, transparent, kernel-managed L2 forwarding |
| **Promiscuous mode for capture** | Only way to tap traffic without routing it |
| **network_mode: host for capture** | Capture containers need raw NIC access |
| **Default network for storage daemon** | Security isolation from host; sysfs mounts work around it |
| **Disable netfilter on bridge** | Prevent Docker's iptables rules from breaking traffic |
| **STP disabled, forward_delay=0** | Inline tap doesn't need MAC learning or BPDU |
| **Systemd workaround for networkd bug** | Only reliable way to ensure bridge UP at boot |
| **Bypass via promiscuous mode toggle** | Can disable capture without restarting containers |
| **Ephemeral bypass state** | Simple; persistent state would require system changes |

---

## 13. References & Related Code

**Bridge Setup:**
- `/scripts/bridge/setup-bridge.sh` — Main setup with persistence and validation
- `/scripts/bridge/harden-bridge.sh` — Kernel hardening for resilience
- `/scripts/bridge/bypass-mode.sh` — Bypass mode control

**Health Monitoring:**
- `/daemon/services/bridge_health.py` — Bridge health monitor class
- `/daemon/api/bridge.py` — Bridge API routes
- `/daemon/api/nic_discovery.py` — NIC discovery for setup wizard

**Docker Integration:**
- `/docker/docker-compose.yml` — All services, includes bridge references
- `/config/zeek/nettap.zeek` — Zeek custom config
- `/config/suricata/nettap.yaml` — Suricata custom config

**Web UI:**
- `/web/src/lib/components/BridgeStatus.svelte` — Bridge status component
- `/web/src/lib/api/bridge.ts` — Bridge API client

**Tracking:**
- `/Debugging/DEPLOYMENT-ISSUES.md` — Related deployment issues
- `/Debugging/RELIABILITY-TRACKER.md` — Subsystem health status
- `/plans/comprehensive-build-plan.md` — Phase milestones

---

## 14. Future Improvements

### Short Term

1. **Add NIC MAC address matching** — store MAC addresses in netplan, validate at boot
2. **Enhance bypass scheduling** — systemd timer for maintenance windows
3. **Index health data to OpenSearch** — correlate bridge events with traffic gaps
4. **Real latency measurement** — inject timestamped test packets through bridge

### Medium Term

1. **Backup bridge configuration** — handle single NIC failure by switching to different NIC pair
2. **LACP support** — bonded NICs for redundancy
3. **VLAN tagging** — separate management VLAN from data path
4. **Persistent bypass schedule** — allow recurring maintenance windows

### Long Term

1. **Hardware bridge acceleration** — offload to NIC if supported
2. **Anycast DNS** — replicate resolver across multiple NICs
3. **Traffic shaping** — fair-queuing to protect capture from starving router
4. **eBPF-based filtering** — replace ebtables with in-kernel eBPF programs

---

**Document Status:** COMPLETE & VERIFIED
**Next Review:** After Phase 2 completion (Storage Management)
**Maintainer:** NetTap Project Team
