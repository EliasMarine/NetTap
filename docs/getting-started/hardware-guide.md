# Hardware Guide

This page covers compatible hardware, a reference build, and guidance for selecting components.

---

## Reference Build (~$200)

The target platform for NetTap is an Intel N100 mini PC. These are widely available, power-efficient, and provide excellent performance for network analysis workloads.

| Component | Specification | Approx. Cost |
|---|---|---|
| **Mini PC** | Intel N100 (4-core, 3.4GHz boost), dual Intel i226-V 2.5GbE NICs | $120--160 |
| **RAM** | 16 GB DDR4/DDR5 (often included) | Included or $25 |
| **Storage** | 1 TB NVMe M.2 SSD | $50--70 |
| **Total** | | **~$200** |

!!! tip "Why the Intel N100?"
    The N100 is a 6W TDP processor that runs fanless in many mini PC designs. It has 4 cores (enough for Zeek + Suricata + OpenSearch), hardware AES-NI for TLS processing, and many mini PC vendors ship boards with dual Intel i226-V 2.5GbE ports already installed.

---

## Selecting Hardware

### CPU

NetTap needs to run Zeek, Suricata, OpenSearch, and several supporting containers simultaneously. Key considerations:

- **Minimum:** 2 cores, x86-64 architecture
- **Recommended:** 4 cores (Intel N100, N95, Celeron J4125, or better)
- **Ideal:** Intel with AES-NI support (all modern Intel CPUs have this)

The CPU must be x86-64. ARM processors are not supported.

### Memory

OpenSearch is the largest memory consumer. The default JVM heap is 4 GB, and the full stack uses approximately 8--12 GB total.

- **8 GB:** Minimum. Works but may trigger OOM under heavy load.
- **16 GB:** Recommended. Comfortable headroom for all services.
- **32 GB:** Overkill for most home networks, but useful if you plan to increase OpenSearch heap size for larger datasets.

### Storage

NVMe SSDs are strongly recommended for both performance and endurance:

- **Read performance:** OpenSearch performs many random reads during queries.
- **Write endurance:** Zeek generates 300--800 MB of logs per day. NetTap includes write coalescing (30-second flush intervals) and SMART monitoring to protect drive life.
- **Capacity:** A 1 TB drive comfortably holds 90 days of Zeek metadata, 180 days of Suricata alerts, and 30 days of PCAP captures for a typical home network.

!!! info "SSD Write Endurance"
    A typical consumer 1 TB NVMe SSD is rated for 600 TBW (terabytes written). At 1 GB/day of log writes, NetTap would use about 365 GB/year --- meaning the drive would last many years. NetTap monitors SMART health and alerts you before drive failure.

### Network Interfaces

You need **at least two physical Ethernet NICs** for the data-path bridge. A third interface for management access is strongly recommended.

**Recommended NICs:**

| NIC | Speed | Notes |
|---|---|---|
| Intel i226-V | 2.5 GbE | Best choice. Common on N100 mini PCs. Excellent Linux support. |
| Intel i225-V | 2.5 GbE | Previous generation. Works well but has known errata on early revisions. |
| Intel I350 | 1 GbE | Server-grade. Reliable but limited to 1 Gbps. |
| Realtek RTL8125 | 2.5 GbE | Works but Intel is preferred for packet capture workloads. |
| Realtek RTL8111 | 1 GbE | Budget option. Functional but lower performance under sustained capture. |

**NICs to avoid:**

- USB Ethernet adapters (unreliable for sustained capture)
- Wi-Fi adapters (cannot be used for the bridge --- bridging requires wired Ethernet)
- Virtual NICs (veth, tun/tap)

### Management Interface Options

The management interface is how you access the NetTap dashboard. Options:

1. **Third Ethernet NIC** --- Most reliable. Assign a static IP or use DHCP.
2. **Wi-Fi adapter** --- Convenient for mini PCs with built-in Wi-Fi. Less reliable than wired.
3. **VLAN on the LAN NIC** --- Advanced. Requires VLAN-aware router configuration.

---

## Recommended Mini PCs

These models are known to work well with NetTap. All feature dual Intel i226-V 2.5GbE NICs:

| Model | CPU | RAM | Storage | NICs | Price Range |
|---|---|---|---|---|---|
| Beelink EQ12 Pro | Intel N100 | 16 GB | 500 GB SSD | 2x i226-V | $150--180 |
| Topton N100 Firewall | Intel N100 | 16 GB | 256 GB SSD | 4x i226-V | $140--170 |
| CWWK N100 | Intel N100 | 16 GB | 256 GB SSD | 2x i226-V | $120--150 |
| MinisForum UM560 | AMD R5 5625U | 16 GB | 512 GB SSD | 1x + USB | $250--300 |

!!! note "Community hardware reports"
    See the [Hardware Compatibility](../reference/hardware-compat.md) reference for community-tested hardware reports. If you get NetTap running on hardware not listed here, please open a GitHub issue or PR to add your configuration.

---

## Physical Setup

### Cabling

```
ISP Modem ──[Ethernet]──> [WAN Port] NetTap [LAN Port] ──[Ethernet]──> Router WAN Port
                                        │
                                  [Management Port]
                                        │
                                  [Your LAN / Switch]
```

1. Disconnect the Ethernet cable between your modem and router.
2. Connect the modem to the NetTap WAN port.
3. Connect the NetTap LAN port to your router's WAN port.
4. Connect the management port to a switch or directly to your computer.

### Power and Placement

- Place NetTap physically between your modem and router (near your network "edge").
- Use a UPS or battery backup if possible --- a power loss will interrupt the bridge and drop all network traffic until NetTap boots back up.
- Ensure adequate ventilation. Fanless mini PCs can throttle under sustained load if airflow is restricted.

---

## Performance Expectations

With the reference Intel N100 build:

| Metric | Expected Performance |
|---|---|
| Bridge latency | < 1 ms added |
| Sustained throughput | 500 Mbps with zero packet loss |
| Peak throughput | Up to 1 Gbps (may see minor packet loss at sustained line rate) |
| Dashboard load time | < 3 seconds on LAN |
| Alert detection latency | < 10 seconds from packet to dashboard |
| Power consumption | 10--15W idle, 20--25W under load |
