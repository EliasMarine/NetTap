# Hardware Compatibility

Community-tested hardware configurations for NetTap. If you get NetTap running on hardware not listed here, please submit a pull request or open a GitHub issue to add your configuration.

---

## Tested Platforms

### Mini PCs (Recommended)

| Model | CPU | RAM | Storage | NICs | Status | Notes |
|---|---|---|---|---|---|---|
| Beelink EQ12 Pro | Intel N100 (4C/4T) | 16 GB DDR5 | 500 GB NVMe | 2x Intel i226-V 2.5GbE | Fully tested | Reference platform |
| Topton N100 Firewall | Intel N100 (4C/4T) | 16 GB DDR4 | 256 GB NVMe | 4x Intel i226-V 2.5GbE | Fully tested | Extra NICs available for management |
| CWWK N100 | Intel N100 (4C/4T) | 16 GB DDR5 | 512 GB NVMe | 2x Intel i226-V 2.5GbE | Fully tested | Compact form factor |

### Workstations / Servers

| Model | CPU | RAM | Storage | NICs | Status | Notes |
|---|---|---|---|---|---|---|
| Dell OptiPlex 3060 Micro | Intel i5-8500T (6C/6T) | 16 GB DDR4 | 512 GB SATA SSD | 1x Intel I219 + USB 2.5GbE | Community tested | USB NIC as 2nd data port |
| HP ProDesk 400 G5 | Intel i5-8500 (6C/6T) | 16 GB DDR4 | 1 TB NVMe | 1x Intel I219 + PCIe i350 | Community tested | Add PCIe NIC for 2nd port |

---

## Tested Network Interfaces

### Recommended (Intel)

| NIC | Driver | Speed | Tested | Notes |
|---|---|---|---|---|
| Intel i226-V | `igc` | 2.5 GbE | Yes | Best choice. Common on N100 mini PCs. |
| Intel i225-V (B3 stepping) | `igc` | 2.5 GbE | Yes | B3 stepping fixes earlier hardware bugs. |
| Intel I350-T2 | `igb` | 1 GbE | Yes | Server-grade dual-port PCIe card. |
| Intel I210 | `igb` | 1 GbE | Yes | Common on server motherboards. |
| Intel I219-V | `e1000e` | 1 GbE | Yes | Common on desktop motherboards. Single port. |
| Intel X710-DA2 | `i40e` | 10 GbE (SFP+) | Yes | Overkill for most home networks. |

### Works (Realtek)

| NIC | Driver | Speed | Tested | Notes |
|---|---|---|---|---|
| Realtek RTL8125B | `r8169` | 2.5 GbE | Yes | Works. Intel preferred for sustained capture. |
| Realtek RTL8111H | `r8169` | 1 GbE | Yes | Budget option. |

### Not Recommended

| NIC | Why |
|---|---|
| USB Ethernet adapters | Unreliable for sustained packet capture. Buffer overflows under load. |
| Wi-Fi adapters | Cannot be used in a Layer 2 bridge. Management-only. |
| Mellanox ConnectX | Requires OFED drivers not included in the installer. |

---

## NIC LED Identification Support

The setup wizard can blink NIC LEDs to help identify physical ports. Support varies by hardware:

| NIC Driver | LED Blink Support |
|---|---|
| `igc` (Intel i226-V, i225-V) | Yes |
| `igb` (Intel I350, I210) | Yes |
| `e1000e` (Intel I219) | Yes |
| `i40e` (Intel X710) | Yes |
| `r8169` (Realtek) | Limited (may not work on all models) |

LED identification uses `ethtool --identify`, which requires driver support.

---

## Storage

### Tested SSDs

| Model | Type | Capacity | Endurance | Notes |
|---|---|---|---|---|
| Samsung 980 Pro | NVMe | 1 TB | 600 TBW | Excellent. Fast and durable. |
| WD Black SN770 | NVMe | 1 TB | 600 TBW | Good performance/price ratio. |
| Crucial P3 | NVMe | 1 TB | 220 TBW | Budget. Adequate for home use. |
| Samsung 870 EVO | SATA | 1 TB | 600 TBW | Good SATA option if no M.2 slot. |

NVMe SSDs are strongly recommended for their superior random I/O performance (important for OpenSearch queries) and generally higher write endurance.

---

## Minimum Hardware Thresholds

These are enforced by the hardware validation script (`scripts/install/validate-hardware.sh`):

| Component | Hard Minimum (install fails) | Warning (install continues) |
|---|---|---|
| CPU architecture | x86-64 only | --- |
| CPU cores | 2 cores | < 4 cores |
| RAM | 8 GB (~7500 MB) | < 16 GB (~15000 MB) |
| Disk | --- | < 512 GB (~400 GB formatted) |
| NICs | 2 physical NICs | --- |

---

## Submit Your Hardware

Tested NetTap on hardware not listed here? Help the community by submitting your results:

1. Open a [GitHub Issue](https://github.com/EliasMarine/NetTap/issues) with the "Info" label
2. Include:
   - Hardware model and specs (CPU, RAM, storage, NICs)
   - NIC driver names (`ethtool -i eth0`)
   - Ubuntu version
   - Any issues encountered
   - Performance observations (throughput, latency, CPU usage)
3. Or submit a PR editing this page directly
