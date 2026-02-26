# Requirements

Before installing NetTap, make sure your hardware and software meet the following requirements.

---

## Hardware Requirements

### Minimum Specifications

| Component | Minimum | Recommended |
|---|---|---|
| **CPU** | x86-64, 2 cores | Intel N100 (4 cores) or equivalent |
| **RAM** | 8 GB | 16 GB |
| **Storage** | 512 GB SSD | 1 TB NVMe SSD |
| **Network** | 2 physical Ethernet NICs | 2x Intel i226-V 2.5GbE + 1 management NIC |
| **Architecture** | x86-64 only | --- |

!!! warning "ARM is not supported"
    NetTap requires x86-64 architecture. ARM-based systems (Raspberry Pi, Apple Silicon, etc.) are not supported because the Malcolm stack's container images are built for x86-64 only.

### Network Interfaces

NetTap requires **at least two physical Ethernet NICs** for the transparent bridge:

- **WAN NIC** --- connects to your ISP modem
- **LAN NIC** --- connects to your router

A **third interface** (Ethernet, Wi-Fi, or USB) is strongly recommended for management access to the dashboard. Without it, you would need to access the dashboard from the router side of the bridge.

!!! tip "Why two NICs?"
    NetTap creates a Layer 2 bridge between the WAN and LAN interfaces. All traffic passes through transparently while NetTap captures a copy for analysis. The bridge interfaces have no IP addresses --- they are invisible on the network.

### Storage Considerations

NetTap stores network metadata, IDS alerts, and packet captures. Storage needs depend on your network activity:

| Data Type | Daily Size | Default Retention | 90-Day Total |
|---|---|---|---|
| Zeek metadata (hot tier) | 300--800 MB | 90 days | 27--72 GB |
| Suricata alerts (warm tier) | 10--50 MB | 180 days | 1.8--9 GB |
| PCAP captures (cold tier) | Variable | 30 days | Variable |

An NVMe SSD is strongly recommended for write endurance and performance. NetTap includes SMART monitoring to track drive health.

---

## Software Requirements

### Operating System

| OS | Status |
|---|---|
| **Ubuntu Server 22.04 LTS** | Fully supported |
| **Ubuntu Server 24.04 LTS** | Supported |
| Other Ubuntu versions | May work, not tested |
| Debian, Fedora, Arch, etc. | Not supported |

!!! note "Why Ubuntu?"
    NetTap uses `netplan` for persistent bridge configuration, `systemd` for service management, and `apt` for package installation. These are all Ubuntu-native tools. Other distributions may work with modifications, but are not officially supported.

### Installed Automatically

The installation script installs all of these automatically. You do not need to install them manually:

- Docker and Docker Compose v2
- `bridge-utils`, `net-tools`, `ethtool`
- `smartmontools` (SSD health monitoring)
- Python 3.10+ and pip
- `avahi-daemon` (mDNS for `nettap.local` access)
- `curl`, `jq`, `openssl`

---

## Network Requirements

### Physical Setup

```
ISP Modem ──── [WAN NIC] ── NetTap ── [LAN NIC] ──── Router ──── Your devices
                                         │
                                   [Management NIC]
                                         │
                                    Dashboard access
```

### Ports Used

| Port | Service | Exposure |
|---|---|---|
| `443` | NetTap dashboard (HTTPS) | Management interface only |
| `80` | HTTP redirect to HTTPS | Management interface only |
| `9443` | Malcolm dashboards (HTTPS) | Management interface only |
| `8880` | Daemon API (HTTP) | Internal only (container-to-container) |
| `9200` | OpenSearch | Loopback only (`127.0.0.1`) |
| `5353/udp` | mDNS (Avahi) | LAN broadcast |

### Firewall

If UFW is active on the host, the installer automatically adds rules for the dashboard port, Malcolm port, and mDNS. See the [Firewall Configuration](../admin-guide/configuration.md) section for details.

---

## Pre-Installation Checklist

Before starting installation, confirm:

- [ ] Hardware meets minimum specs (2+ cores, 8+ GB RAM, 512+ GB storage)
- [ ] Two physical Ethernet NICs are installed and detected by the OS
- [ ] Ubuntu Server 22.04 or 24.04 is installed (minimal server install is fine)
- [ ] You have root or sudo access
- [ ] The system has internet access (to pull Docker images)
- [ ] The two data-path NICs are **not** assigned IP addresses (the installer handles this)
