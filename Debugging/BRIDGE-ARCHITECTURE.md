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
         ┌───────┴────────┬─────────────────┐
         ↓                ↓                 ↓
    Zeek Live      Suricata Live      PCAP Capture
    (metadata)      (alerts)          (netsniff-ng, raw PCAP)
         ↓                ↓                 ↓
    zeek/live/      /var/log/          pcap-data/
                    suricata/               ↓
         ↓                ↓            PCAP Search (daemon, BPF over the files)
      Filebeat          Filebeat       TShark (packet decode / replay)
         ↓                ↓
         └────────┬───────┘
                  ↓
            Logstash (enrichment)
                  ↓
            OpenSearch (indexing)
```

Arkime Live (`arkime-live`) is **off by default** since 2026-11-02 (owner decision, `tracking-fixes/2026-11-01-dashboard-data-accuracy.md` #44). See "PCAP Capture and Arkime" below.

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
- Disables PCAP extraction (netsniff-ng in `pcap-capture` writes the PCAP)
- Sets log rotation

### Suricata Configuration

**Custom config:** `config/suricata/nettap.yaml`

- Uses Emerging Threats ruleset
- Runs in `workers` runmode (multi-threaded)
- Auto-updates rules

### PCAP Capture and Arkime

- **netsniff-ng in `pcap-capture` is the only PCAP writer** (CR-020/MS-002). It writes rotating files to the `pcap-data/` volume; the UI's capture toggle and file-size setting control it.
- **PCAP Search** (`daemon/services/pcap_search.py`) runs BPF filters over those files, and **TShark** (`nettap-tshark`) decodes and replays packets from the same files. Together they cover the session search and packet replay that Arkime's viewer would have given.
- **Arkime is off by default, not deleted** (owner decision 2026-11-02, #44). The `arkime-live` service stays in `docker/docker-compose.yml` with `profiles: ["arkime"]`, so a plain `docker compose up -d` doesn't start it. It never worked on NetTap: it had no `./curlrc:/var/local/curlrc:ro` mount, so Malcolm's `opensearch_status.sh` looped forever ("Giving opensearch-local time to start…", ~58 TLS `unknown_ca` errors a minute in OpenSearch), and with `ARKIME_PCAP_WRITE_METHOD: "null"` it wrote no PCAP anyway.
- To try it again: fix the curlrc mount first, then `docker compose -f docker/docker-compose.yml --profile arkime up -d arkime-live`. Naming `arkime-live` on any compose command line starts it, so scripts must not list it. `ARKIME_SECRET` must still be set in `docker/.env`, because compose interpolates every service, profiled or not.
- Old Arkime PCAP left in `pcap-data/arkime-live/` is still pruned by the storage daemon, which scans the volume recursively.

### Data Flow Isolation

**Critical:** Capture containers and storage daemon don't interact directly:

```
Zeek/Suricata/pcap-capture (network_mode: host)
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

> **Update 2026-11-01 (Chain 22):** the daemon now runs with `network_mode: host`, so it already is in the host network namespace and runs `ip`/`ethtool`/`iptables` directly. `nsenter -t 1 -n` was dropped: Ubuntu's docker-default AppArmor profile denies its ptrace read of PID 1 (`apparmor="DENIED" ... comm="nsenter"`), so every host command failed on the G11. `/proc/sys` is still read-only in the container, so `sysctl -w` from the daemon fails; host boot units apply sysctls.

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
4. **Bypass state** — checks if `/tmp/nettap-bypass-active` exists
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
| `/api/bridge/bypass/enable` | POST | Activate bypass (toggles promisc off via nsenter) |
| `/api/bridge/bypass/disable` | POST | Deactivate bypass (toggles promisc on via nsenter) |
| `/api/bridge/bypass/status` | GET | Current bypass state |
| `/api/setup/bridge` | POST | Create bridge with WAN/LAN interfaces (BridgeManager) |
| `/api/bridge/teardown` | POST | Remove bridge and release interfaces (BridgeManager) |
| `/api/bridge/readiness` | GET | 8-point readiness check with human-readable messages |

**Refresh Rate:** 30s background polling via `bridge_loop()` in `daemon/main.py` (configurable via `BRIDGE_CHECK_INTERVAL` env var, default 30s). Maintains 2880 history entries = 24 hours of monitoring.

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
  WAN ─→ [Zeek/Suricata/netsniff capturing] ─→ LAN  ← ~5-10ms latency

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
docker compose -f docker/docker-compose.yml stop zeek-live suricata-live pcap-capture

# Step 2: Flush ebtables rules (clean L2 path)
ebtables -F && ebtables -X && ebtables -t nat -F && ebtables -t nat -X

# Step 3: Disable promiscuous mode (stop passive capture)
ip link set eth0 promisc off
ip link set eth1 promisc off

# Step 4: Write state file (signal to daemon and UI)
echo "bypass active" > /tmp/nettap-bypass-active
```

**Disable Bypass:**

```bash
# Step 1: Re-enable promiscuous mode
ip link set eth0 promisc on
ip link set eth1 promisc on

# Step 2: Start capture services
docker compose -f docker/docker-compose.yml start zeek-live suricata-live pcap-capture

# Step 3: Remove state file
rm -f /tmp/nettap-bypass-active
```

### State Persistence

**State file:** `/tmp/nettap-bypass-active`

- Created when bypass is enabled
- Removed when bypass is disabled
- Checked by daemon on every health check
- Consumed by UI to show bypass badge
- **Daemon bypass** also toggles promiscuous mode via `nsenter -t 1 -n -- ip link set <iface> promisc off/on`

**Limitations:**
- `/tmp/` is a tmpfs (lost on container restart — intentional: reboot should resume monitoring)
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
| **Bypass state file on read-only path** | `/var/run` write failed in container | Moved to `/tmp` (writable tmpfs) | **FIXED** (PR #83) |
| **Bypass didn't toggle promisc** | Capture continued despite bypass | Added nsenter promisc off/on in `trigger_bypass()`/`disable_bypass()` | **FIXED** (PR #83) |
| **No bridge health polling loop** | Health history was demand-driven only | Added `bridge_loop()` in `main.py` (30s interval) | **FIXED** (PR #83) |
| **No bridge creation from daemon** | Wizard step 3 only generated mock preview | Added `BridgeManager.create_bridge()` + `/api/setup/bridge` endpoint | **FIXED** (PR #83) |
| **No readiness check** | User had no guidance on cable migration | Added 8-point readiness check at `/api/bridge/readiness` | **FIXED** (PR #83) |
| **No Go Live page** | Wizard redirected to `/login` with no guidance | Added `/go-live` page with 3-phase workflow | **FIXED** (PR #83) |
| **Boot units never enabled** (review LD-001) | `nettap-bridge.service` / `nettap-mirror.service` wants/ links pointed at the container path `/host/etc/...`, which doesn't exist on the host, so the oneshot never ran at boot; re-creating the dangling link also raised FileExistsError | Links now use the relative target `../<unit>` via `replace_symlink()` (lexists-aware). Existing devices get the fixed link the next time the bridge or mirror persistence is written | **FIXED** (fix/code-review-batch-1), device check pending |
| **AppArmor blocked every daemon `nsenter`** (Chain 22) | On Ubuntu, mirror setup stopped at its first check: capture port left admin DOWN, no netplan file, no `nettap-mirror.service`. Bridge, bridge health and DHCP gateway host commands failed the same way | The daemon (`network_mode: host`) runs host commands directly; `_run_nsenter` no longer wraps them | **FIXED** (fix/daemon-drop-nsenter), verified on the G11 2026-11-01 |
| **Zeek cluster never connected on AMD CPUs with a broken RDRAND** (Chain 23) | Packets reached the capture port and Suricata logged them, but every Zeek process got the same Broker ID, so the zeekctl nodes refused to peer and Zeek wrote no logs (no conn/dns/http data on the dashboard) | zeek-live is built from `docker/Dockerfile.zeek-live`: a preloaded library sends `std::random_device`'s CPU sources to /dev/urandom | **FIXED** (fix/zeek-rdrand-urandom, NET-127), verified on the G11 2026-11-01 |
| **Zeek records rejected by OpenSearch; dashboard queries on guessed fields** (Chain 24) | malcolm_template's index pattern was a placeholder, so indices guessed field types: Zeek's text uids failed against `event.id` as a number, and the daemon's `.keyword` queries were built on the guessed mapping | Installer fills in the pattern; `fix-index-template.sh` for existing boxes; daemon and web query Malcolm's field names | **FIXED** (fix/index-template-pattern, NET-128), template and index fixed on the G11 |
| **In-use guard passed any NIC when `ip` failed** (Chain 22) | `_nic_in_use_problem` read failed `ip` calls as "no route, no address", so the wizard would have accepted the management port for mirror mode | Fails closed when `ip -j link show dev X` returns nothing | **FIXED** (fix/daemon-drop-nsenter) |
| **Mirror setup flushed the configured NIC at every daemon start** (review CR-076) | After a NIC rename the saved capture NIC could be the management port; setup() would strip its address | `main.py` skips mirror setup (logs `Mirror setup skipped`) when the NIC carries the default route or has an IPv4 address. The boot unit `nettap-mirror.service` no longer runs `ip addr flush` by name at every boot | **FIXED** (fix/daemon-drop-nsenter), device check pending |
| **Daemon can't turn IPv6 off on the capture NIC at runtime** | `/proc/sys` is read-only in the container; a mirrored router advert can give the capture NIC an IPv6 address until reboot | `nettap-mirror.service` sets `disable_ipv6=1` on the host at boot; `deploy-drop-nsenter.sh` starts it once | OPEN (workaround) |
| **Wizard Verify built the bridge** (review CR-004) | The bridge step's Verify called the daemon's bridge create, so it enslaved both NICs and persisted br0 mid-wizard; a daemon error fell back to a mock that showed as verified | Verify calls the read-only `POST /api/setup/bridge/preview`, which also refuses a port the machine still uses (an address, the default route, the live DHCP gateway NIC). Go Live still builds br0. Go Live's create (`POST /api/setup/bridge`) got the same in-use check and name validation on 2026-11-01 (Chain 22) | **FIXED** (fix/code-review-batch-1), device check pending |
| **arkime-live never started** (Chain 25, data accuracy #44) | No `./curlrc:/var/local/curlrc:ro` mount, so `opensearch_status.sh` looped forever (~58 TLS `unknown_ca` errors a minute in OpenSearch); no Arkime session was ever indexed. Nothing in NetTap used it | Not fixed on purpose: owner decision 2026-11-02 to turn it off. `profiles: ["arkime"]` keeps it out of the default stack; daemon capture restarts, bypass mode and the deploy scripts no longer name it. PCAP Search + TShark read the netsniff files | **OFF BY DEFAULT** (2026-11-02) |

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
   - Lost on container restart (intentional — reboot should resume monitoring)
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

6. **Bridge member NIC discovery order-dependent**
   - Uses sorted `brif/` directory listing — assumes first = WAN, second = LAN (alphabetical)
   - Falls back to `WAN_IFACE`/`LAN_IFACE` env vars
   - **Mitigation:** Env var fallback covers most cases; document in deployment guide

### Architectural Limitations

1. **Docker-isolated daemon can't directly interact with host network**
   - All sysfs reads must go through mounted volumes
   - All bridge commands use `nsenter -t 1 -n --` to enter host namespace *(until 2026-11-01; now run directly under `network_mode: host`, see Chain 22)*
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

5. **Persistence requires host volume mounts**
   - Bridge creation writes netplan/systemd/sysctl to mounted host dirs
   - If mounts are missing (`HOST_NETPLAN_DIR` etc.), bridge works in memory but won't survive reboot
   - Docker-compose configures these mounts; standalone daemon installs need manual setup

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
5. PCAP CAPTURE (netsniff-ng on br0, network_mode: host)
   Writes: pcap-data/*.pcap (read by PCAP Search and TShark, not indexed)
   (Arkime used to sit here; off by default since 2026-11-02, #44)
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
| `/etc/netplan/10-nettap-bridge.yaml` | Bridge config at boot | setup-bridge.sh --persist OR BridgeManager | systemd-networkd |
| `/etc/systemd/system/nettap-bridge.service` | Force bridge UP (workaround) | setup-bridge.sh --persist OR BridgeManager | systemd |
| `/etc/sysctl.d/99-nettap-bridge.conf` | Netfilter disabling | setup-bridge.sh --persist OR BridgeManager | sysctl --system |
| `/etc/sysctl.d/99-nettap-bridge-hardening.conf` | Resilience settings | harden-bridge.sh | sysctl --system |
| `/etc/modules-load.d/nettap-br-netfilter.conf` | Load br_netfilter at boot | harden-bridge.sh | systemd |
| `/etc/NetworkManager/conf.d/99-nettap-unmanaged.conf` | Tell NM to leave bridge alone | setup-bridge.sh --persist | NetworkManager |
| `/tmp/nettap-bypass-active` | Bypass state (ephemeral tmpfs) | daemon bridge_health.py | daemon, UI |

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
# Query health endpoint (daemon routes need the token since the PR #110 review fixes)
TOKEN=$(sudo docker exec nettap-storage-daemon cat /run/nettap-auth/daemon-token)
curl -s -H "X-NetTap-Daemon-Token: $TOKEN" http://localhost:8880/api/bridge/health | jq .

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
- `/scripts/bridge/setup-bridge.sh` — Main setup with persistence and validation (host script)
- `/scripts/bridge/harden-bridge.sh` — Kernel hardening for resilience
- `/scripts/bridge/bypass-mode.sh` — Bypass mode control (host script)

**Bridge Management (Daemon):**
- `/daemon/services/bridge_manager.py` — Bridge create/teardown/readiness via nsenter (from Docker)
- `/daemon/services/bridge_health.py` — Bridge health monitor + bypass toggle with promisc
- `/daemon/api/bridge.py` — Bridge API routes (9 endpoints)
- `/daemon/api/nic_discovery.py` — NIC discovery for setup wizard
- `/daemon/main.py` — `bridge_loop()` for 30s background health polling

**Docker Integration:**
- `/docker/docker-compose.yml` — All services, host volume mounts for bridge persistence
- `/config/zeek/nettap.zeek` — Zeek custom config
- `/config/suricata/nettap.yaml` — Suricata custom config

**Web UI:**
- `/web/src/routes/go-live/+page.svelte` — Three-phase Go Live workflow page
- `/web/src/lib/components/BridgeStatus.svelte` — Bridge status component
- `/web/src/lib/api/bridge.ts` — Bridge API client (health, readiness, create, teardown, bypass)
- `/web/src/routes/api/bridge/create/+server.ts` — Proxy route for bridge creation
- `/web/src/routes/api/bridge/readiness/+server.ts` — Proxy route for readiness check
- `/web/src/routes/api/bridge/teardown/+server.ts` — Proxy route for bridge teardown

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

## 15. Go Live Workflow

### Overview

The Go Live workflow bridges the gap between the setup wizard (which configures NIC selections and storage) and actual network monitoring. It handles bridge creation, physical cable migration guidance, and readiness verification.

**Flow:** Setup Wizard → Bridge Creation → Readiness Check → Physical Cable Migration → Live Monitoring

### Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Bridge creation method | `ip link` run directly (daemon has `network_mode: host`); was `nsenter -t 1 -n` until 2026-11-01 | nsenter is blocked by Ubuntu's AppArmor (Chain 22); host networking makes it unnecessary |
| Bridge persistence | Mount host `/etc/netplan`, `/etc/systemd/system`, `/etc/sysctl.d` as writable volumes | Daemon writes config files directly; host picks them up on next boot |
| Bypass mode | "Soft bypass" — toggle promiscuous mode via nsenter | No Docker socket needed; containers stay running but receive no packets |
| Bypass state file | `/tmp/nettap-bypass-active` | `/tmp` has writable tmpfs; `/var/run` was on read-only root fs |
| Go Live UX | Separate `/go-live` page (not a wizard step) | Reusable from dashboard; wizard handles config, Go Live handles physical deployment |

### Docker Security Model

The `nettap-storage-daemon` container has these capabilities for bridge management:

- **NET_ADMIN**: Required for `ip link add/set` bridge commands and ethtool NIC tuning
- **SYS_PTRACE**: Was for `nsenter -t 1 -n` (dropped 2026-11-01, Chain 22); kept until a device run shows nothing else needs it
- **pid: host**: Was for nsenter to target PID 1 (dropped 2026-11-01); kept for the same reason
- **network_mode: host**: Host network commands run directly in the shared namespace
- **No Docker socket**: Bridge management uses nsenter, not the Docker API — reduces attack surface

Host filesystem mounts for persistence:
- `/etc/netplan:/host/etc/netplan` — Netplan bridge YAML
- `/etc/systemd/system:/host/etc/systemd/system` — Systemd bridge service unit
- `/etc/sysctl.d:/host/etc/sysctl.d` — Sysctl netfilter disable config
- `/tmp` tmpfs — Bypass state file
- `/var/run` tmpfs — Future use

### New API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/setup/bridge` | POST | Create bridge with WAN/LAN interfaces |
| `/api/bridge/teardown` | POST | Remove bridge and release interfaces |
| `/api/bridge/readiness` | GET | 8-point readiness check with human-readable messages |

### Readiness Checks

The readiness endpoint performs 8 sequential checks:

1. **bridge_exists** — Bridge interface exists in sysfs
2. **bridge_up** — Bridge operstate is "up"
3. **wan_carrier** — WAN NIC has link carrier (cable connected)
4. **lan_carrier** — LAN NIC has link carrier (cable connected)
5. **wan_promisc** — WAN NIC in promiscuous mode (IFF_PROMISC flag)
6. **lan_promisc** — LAN NIC in promiscuous mode
7. **stp_disabled** — STP is off (required for inline tap)
8. **netfilter_disabled** — bridge-nf-call-iptables is 0

### Bridge Health Loop

A new `bridge_loop()` runs alongside `storage_loop()` and `smart_loop()` in the daemon's async main. Default interval: 30 seconds (configurable via `BRIDGE_CHECK_INTERVAL` env var). This provides continuous bridge health history instead of demand-driven checks.

### Known Limitations

- Bridge member NIC discovery uses sorted `brif/` directory listing — assumes first = WAN, second = LAN (alphabetical order). Falls back to WAN_IFACE/LAN_IFACE env vars.
- Persistence files require host dirs to be mounted writable. If mounts are missing, bridge works but won't survive reboot.
- Bypass state is ephemeral (tmpfs) — lost on container restart. This is intentional: reboot should resume monitoring.
- No hot-swap NIC detection — if a NIC is physically replaced, bridge must be recreated.

---

## 16. DHCP Gateway Mode (added 2026-10-30)

> Design and contract: `docs/plans/2026-10-30-dhcp-gateway-mode-design.md`. Branch `phase-4/dhcp-gateway-mode`. Not yet verified on hardware.

### Why it exists

The inline bridge sits between modem and router, so it only sees traffic **after** the router's NAT: every device looks like the router's public IP. DHCP gateway mode moves NetTap in front of the NAT. NetTap hands out addresses on its own subnet, names itself the gateway, and routes and masquerades to the router, so every flow carries the device's real IP and MAC. In the onboarding wizard it is now the recommended mode, Mirror/SPAN is the other primary mode, and the inline bridge moved under "Advanced".

### Topology (one-armed)

```
ISP modem ── router (192.168.1.1, DHCP OFF) ── LAN / Wi-Fi ──┬── NetTap LAN NIC: 192.168.1.50/24 (static) + 10.77.0.1/24
                                                             └── devices: 10.77.0.x, gw 10.77.0.1, dns 192.168.1.1
```

One NIC carries both legs: device ↔ NetTap (pre-NAT, captured) and NetTap ↔ router (post-NAT, filtered out of capture).

### Moving parts

| Piece | Where | Notes |
|-------|-------|-------|
| DHCP server | dnsmasq child of the daemon (`--port=0`, DHCP only, 1 h lease, unprivileged user) | Router IP handed out as DNS, so DNS still crosses NetTap and is attributed to the device. Never started without first probing for another DHCP server. |
| Forwarding + NAT | iptables `DOCKER-USER` accept (pinned `-i lan -o lan`), `nat POSTROUTING` masquerade, `OUTPUT` ICMP-redirect drop, all tagged `nettap-dhcp-gateway` | `DOCKER-USER` because Docker's FORWARD policy is DROP. Backend (nft/legacy) detected by which one has `DOCKER-USER`. |
| Self-heal | `DhcpGatewayManager.reconcile()` every capture-health tick (30 s) | Re-adds gateway address, upstream address, default route, rules; restarts a dead dnsmasq only after a clean probe. |
| Boot persistence | `/etc/netplan/90-nettap-dhcp-gateway.yaml`, `/etc/sysctl.d/99-nettap-dhcp-gateway.conf`, `/etc/nettap/dhcp-gateway-firewall.sh`, `nettap-dhcp-gateway.service` (After=docker.service; wants-symlink targets the **host** path) | Routing returns at boot without waiting for OpenSearch/daemon. |
| Capture | `PCAP_IFACE=<lan>`, `PCAP_FILTER="net <subnet> or udp port 67 or udp port 68"` | Device leg only, so each flow is recorded once. Zeek honours it via Malcolm's own `local.zeek` (`CAPTURE_FILTER`). |

### Capture-mode plumbing (all modes)

Before 2026-10-30 the wizard's capture choice never reached the daemon or the capture containers (review CR-007). Now:

- `/etc/nettap` on the host is mounted read-write into the daemon and read-only into zeek-live, suricata-live and pcap-capture (and arkime-live, when its `arkime` profile is turned on).
- `/api/setup/configure` writes `/etc/nettap/capture-mode.conf` (INI, the file `load_capture_config` reads) and `/etc/nettap/capture.env` (`CAPTURE_MODE`, `PCAP_IFACE`, `PCAP_FILTER`), then restarts the capture containers only if `capture.env` changed. Since 2026-11-02 that is three (zeek-live, suricata-live, pcap-capture); arkime-live is off by default (#44) and the daemon never restarts it.
- Each capture entrypoint first sources `config/capture/nettap-capture-env.sh`, which **parses** (never sources) `capture.env`, validates the values and exports `PCAP_IFACE`, `PCAP_FILTER`, `CAPTURE_FILTER`. No file means the compose values stay in effect, so existing installs are unchanged.

### API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/capture/dhcp/preflight` | GET | Interface, upstream, subnet conflicts, other DHCP servers (live DHCPDISCOVER probe), IPv6 RA, ip_forward, firewall backend, checks, ready |
| `/api/capture/dhcp/enable` | POST `{"confirm": true}` | Re-runs preflight; 409 with checks if blocked; applies + persists; starts dnsmasq |
| `/api/capture/dhcp/disable` | POST | Stops the DHCP server; routing stays so devices keep working while they move back to the router |
| `/api/capture/dhcp/status` | GET | Routing/DHCP state, leases, issues |

The web proxies enable/disable through dedicated routes with a 60 s timeout.

### Recovery (NetTap down, router DHCP off)

Give a laptop a fixed address in the router's network, open the router's admin page, turn its DHCP back on, then reconnect devices. Full wording lives in the go-live page and design §7.

### Known issues / risks (DHCP gateway)

| Issue | Impact | Status |
|-------|--------|--------|
| NetTap's old router lease expires after router DHCP is turned off | networkd drops the address and default route once; reconcile re-adds them within 30 s; NetTap's own DNS may fail until a reboot applies the netplan file | MITIGATED (self-heal + netplan) |
| Reboot on installs using `nettap.service` runs `compose down` | OpenSearch recreated, auth mapping lost (review CR-025, root cause MS-001) | OPEN — run the OpenSearch bootstrap after reboot |
| iptables run from the daemon image, not the host binary | On **legacy**-backend hosts the daemon and dockerd don't share the xtables lock; rare insert race. nft hosts (Ubuntu 22.04 default) unaffected | DOCUMENTED |
| IPv6 via router RAs bypasses NetTap | v6 traffic invisible | WARNED in preflight / go-live |
| Static-IP devices and device-to-device LAN traffic | Not captured | DOCUMENTED |
| Double NAT | Router port forwards/UPnP don't reach devices | DOCUMENTED; NetTap-side port forwarding is a follow-up |
| Switching capture mode after first run | The wizard can't save once an admin exists, so there is no in-app mode switch yet | FOLLOW-UP |
| Bridge/mirror wants-symlinks point at the container path (LD-001) | Their boot units never run | OPEN (bridge/mirror only; DHCP unit uses the host path) |

---

## 17. Live bandwidth per device (added 2026-11-07, NET-205)

The **Live bandwidth** card on both device pages shows a device's download and upload rate every 2 s, with a 5-minute chart. Code: `daemon/services/live_bandwidth.py` (the meter), `daemon/services/live_bandwidth_tc.py` (filter lines, dump parser, tool runner), `daemon/api/live_bandwidth.py` (`GET /api/live-bandwidth?mac=` or `?ip=`), `web/src/lib/components/LiveBandwidthCard.svelte`.

### Opt-in (added 2026-11-08)

- **Off by default.** The owner turns it on in **Settings › Capture › Live bandwidth**. Saved in `/opt/nettap/data/live_bandwidth.json` on the daemon's data volume (`daemon/services/live_bandwidth_setting.py`); a missing or unreadable file means off, so existing boxes come up off after the update.
- **API.** `GET /api/settings/live-bandwidth` → `{enabled, supported, reason, mode, cleanup: {state, failed}}`. `PUT` with `{"enabled": true|false}` (a JSON bool, else 400) saves first, then applies; a failed save is a 500 and nothing changes. Turning on in bridge or gateway mode is allowed and saved, so it takes effect if the box moves to mirror mode.
- **While off,** `GET /api/live-bandwidth` answers `{"supported": false, "off": true, "reason": …}` without touching tc, and the device card shows "Live bandwidth is off" with a link to the setting. It asks again only when the page comes back into view or gets focus.
- **Turning off** flips the flag at once; the filters are removed by a background task. If removal fails on an interface that still exists, the interface stays "dirty": the task retries every 10 s (30 times), then every 60 s, and new watches get 503 "Removing earlier counters; trying again in a moment." until it is clean. `GET` shows the state (`running`, `retrying` with the reason per interface), and the Settings card follows it. An interface that has gone away counts as clean (its filters went with it).
- **Races.** An admission that waited across an off (or off and on) re-checks after the lock, after preparing and after installing; if the switch moved it removes what it added and answers `off` (or 503 if it is on again).
- **Cost (G11, `verify_live_bandwidth.py bench`, 2026-11-09).** Every packet on the capture port passes the six shared stages while any watch is on, so the cost follows the port's traffic, not the watched device's. Median extra CPU per frame, as a share of one core at 1 Gbit/s: one watch 6.7–7.9 % with full-size frames, 29–39 % with IMIX, about 140–220 % with minimum-size frames (more than the port can carry); eight watches about twice that. The Settings card states it. The bench's own `/api/health` check reached 1.50 s worst while it flooded a veth pair at line rate; in the lifecycle gate (real use) it stayed at 0.42 s.
- **Capture loss (G11, `verify_live_bandwidth.py capture-safety`, 2026-11-09): FAIL, accepted because the setting is opt-in.** Two valid runs under a ~330 Mbit/s two-stream download, three pairs of 60 s arms each. With eight watches the r8169 NIC's `rx_missed_errors` grew 38, 76, 56 and 91 in four of six arms (0 in the other two); with the meter off it grew 0 in all six. Under 0.01 % of frames, missed in the NIC before AF_PACKET, so Zeek, Suricata and Arkime never see them. Likely cause: the extra per-packet softirq work on the RTL8125B's single RX queue with its 256-entry ring (the maximum). The script's verdict was INCONCLUSIVE (each run had one 0/0 pair), but the pattern is reproducible. The Settings card states it. Untested on the Intel i226-V (multiple queues).
- **Accuracy (G11, `live_bandwidth_reference.py`, 2026-11-09): PASS both ways.** Download 500 MB (OVH, 10 MiB/s): 22 windows, worst 0.12 %; the meter's total 0.27 % off curl's bytes plus the measured 3.6 % header share; byte-exact against the reference's own span total. Upload 300 MB (Cloudflare, 5 MiB/s): 25 windows, worst 0.63 %; the total 0.07 % off; byte-exact span.
- **Rollback.** (1) Turn it off in Settings › Capture (or `PUT /api/settings/live-bandwidth {"enabled": false}`); the daemon removes its filters. (2) `bash scripts/remote/live-bandwidth-cleanup.sh --check` must report none. (3) Revert the change and deploy. (4) If filters are left after the revert (e.g. a crash before the clean-up), remove them with the script from history: `git show <sha>:scripts/remote/live-bandwidth-cleanup.sh | bash -s` (it needs no daemon code). An empty `clsact` qdisc may stay; it costs nothing measurable.

### How it counts

- **Kernel byte counters, not a reader.** The daemon puts tc flower filters on the capture interface's **ingress** hook (a `clsact` qdisc). The kernel counts each matching frame; the daemon reads the counters once per tick (`tc -s -j filter show`) and divides the byte change by the time between reads. Nothing is copied to user space and nothing is written to disk.
- **The count is the Ethernet payload** (`skb->len` at ingress): the IP packet, plus padding for packets under 46 bytes. The 802.1Q tag isn't counted (the kernel moves it to metadata before tc runs).
- **The MAC page counts by MAC** (`dst_mac` = download, `src_mac` = upload, `protocol all`): everything the device sends, and unicast addressed to it. Broadcast and multicast it receives aren't counted. **The IP page counts by IPv4 address** (`dst_ip`/`src_ip`, plus the `802.1Q` forms for tagged frames).
- **Six shared stages.** Every watch's filters sit in six fixed prefs, 49152–49157 (MAC down/up, IP down/up, 802.1Q IP down/up), so a frame costs at most six hash lookups however many devices are watched. Each watch takes one handle (slot + 1) in its prefs.
- **`action continue`, never `pass`.** A terminal action ends classification, and every later filter would count nothing (found in the first G11 spike).
- **Ownership by cookie.** Every NetTap filter's action carries a cookie: `4e4554544150424d` ("NETTAPBM"), the slot, and a generation. NetTap deletes only filters with that cookie, only by exact `pref` + `protocol` + `handle`, and never deletes `clsact`. If any other filter or a plain `ingress` qdisc is on the interface, the card says "Another traffic rule on <iface> runs first, so NetTap can't count reliably." and nothing is installed.

### Lifecycle

- **Each poll is the keepalive.** The first poll for a device starts its watch; every viewer shares it; it stops 15 s after the last poll. At most 8 watches (the 9th gets 503 "Too many live views are open").
- **One lock** covers installs, removals and sampling; a keepalive for a running watch never waits on it. Every tc call has its own deadline and admission has a 6 s one, so a request answers before the web proxy's 10 s limit.
- **Startup and shutdown clean-up.** After the capture manager is installed (`main.py`), and on daemon shutdown (`on_cleanup`), the meter deletes every NetTap-cookie filter on every interface. After a crash, its filters stay until the next daemon start removes them.
- **Invalid samples are shown, never hidden.** A tick is invalid (with its reason) when the counters were read late (interval outside 1.5–4 s), the two reads took more than 2% of the interval, a counter went backwards, a filter is missing or carries another generation, a foreign rule appeared, or capture settings are changing (`capture_config_lock` held). The headline goes blank when the latest reading is more than 5 s old.

### Modes

| Mode | Supported | Why |
|------|-----------|-----|
| Mirror | Yes | The mirror port sees every device's own MAC and LAN address |
| Bridge | No | NetTap sits in front of the router and sees only its public address |
| DHCP gateway | No | NetTap's own NAT readdresses replies before tc ingress sees them |

### Known issues / risks (live bandwidth)

| Issue | Impact | Status |
|-------|--------|--------|
| Leftover NetTap filters after a daemon crash | They keep counting (cheaply) until the next daemon start, which removes them. By hand: `sudo tc -s -j filter show dev <iface> ingress`, then for each filter whose action cookie starts `4e4554544150424d`: `sudo tc filter del dev <iface> ingress pref <pref> protocol <proto> handle <handle> flower` | MITIGATED (startup + shutdown reconcile) |
| **Capture safety isn't verified by engine telemetry** | Suricata's stats are disabled and Zeek writes no stats or capture-loss log, so there's no live engine drop counter to compare with the meter off and on. The meter's per-packet CPU cost is measured instead (`verify_live_bandwidth.py bench`) | OPEN — follow-up: enable Suricata `stats`, compare `capture.kernel_drops` off vs on |
| GRO on the capture NIC | Merged super-frames carry fewer Ethernet headers, so rates read about 3% low; the API reports `offloads.gro` and the daemon logs a warning | DOCUMENTED |
| Intel i226-V (target hardware) | Not verified (no bench). `skip_hw` keeps the filters in software, so the path is driver-independent | DOCUMENTED |
| A `clsact` qdisc stays on the capture interface | Harmless when empty; NetTap never deletes it | BY DESIGN |

### Verification

`scripts/remote/deploy-device-live-bandwidth.sh` runs the release gate in the daemon container: exact counts on a throwaway veth pair (`verify_live_bandwidth.py kernel`), the per-packet CPU cost (`bench`) and the API lifecycle (`lifecycle`). The accuracy gate (±5% per 2 s window against `scripts/remote/live_bandwidth_reference.py`, an AF_PACKET reader with kernel timestamps) runs during a known download and upload. Results: `tracking-fixes/2026-11-07-device-live-bandwidth.md`.

---

**Document Status:** COMPLETE & VERIFIED
**Next Review:** After Phase 2 completion (Storage Management)
**Maintainer:** NetTap Project Team
