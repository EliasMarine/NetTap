# NetTap

**Open-source inline network visibility appliance for home users and small businesses.**

NetTap sits transparently between your ISP modem and router, passively capturing and analyzing all network traffic. It provides enterprise-grade telemetry — full packet metadata, intrusion detection, and forensic replay — through a polished web dashboard, without requiring deep networking expertise.

> **Status:** Early development. See the [PRD](NetTap_PRD_v1.0.md) for the full product specification.

## What It Does

- **Full traffic visibility** — Zeek extracts structured metadata for every connection, DNS query, TLS handshake, HTTP request, and file transfer
- **Intrusion detection** — Suricata runs continuously with the Emerging Threats Open ruleset, surfacing alerts in under 10 seconds
- **Forensic replay** — Arkime stores full packet captures (triggered by alerts) with session-level search and raw packet replay
- **GeoIP mapping** — See where your traffic is going, enriched with geography, ASN, and hostname data
- **Intelligent storage** — Three-tier rolling retention with automatic disk management so the drive never fills up
- **No cloud, no subscription** — Fully self-contained. No data leaves your network

## How It Works

```
[ISP Modem] ──eth0──▶ [ NetTap Bridge (br0) ] ──eth1──▶ [Your Router]
                              │
                         passive tap
                              │
                     ┌────────┴────────┐
                     │  Zeek + Suricata │
                     │    ▼        ▼    │
                     │   OpenSearch     │
                     │    ▼        ▼    │
                     │ Dashboards  Grafana
                     └─────────────────┘
                              │
                        mgmt interface
                              │
                     https://nettap.local
```

NetTap creates a transparent Layer 2 bridge between two NICs. Traffic flows through unmodified with <1ms added latency. A separate management interface serves the web dashboard.

## Recommended Hardware

| Component | Recommended | Cost |
|-----------|-------------|------|
| CPU | Intel N100 or N305 | |
| RAM | 16GB DDR5 | |
| Storage | 1TB NVMe SSD (1200+ TBW) | |
| NICs | 2x Intel i226-V 2.5GbE | |
| Form factor | Mini PC (Topton, Beelink, etc.) | |
| **Total BOM** | | **~$150-200** |

**Only have 2 NICs?** No problem. If your box has Wi-Fi (or you add a USB Wi-Fi adapter), NetTap uses Wi-Fi as the management interface for dashboard access while both wired NICs go to the bridge. No third Ethernet port required.

## Quick Start

NetTap uses a three-phase install so you keep internet access throughout:

```bash
# 1. INSTALL — clone, install deps, pull Docker images (internet required)
git clone https://github.com/EliasMarine/NetTap.git
cd NetTap
sudo scripts/install/install.sh

# The installer discovers your NICs, lets you assign roles (MGMT/WAN/LAN),
# installs everything, then prints a wiring diagram.

# 2. REWIRE — plug cables per the diagram:
#    ISP Modem → WAN NIC → [NetTap bridge] → LAN NIC → Router

# 3. ACTIVATE — start the bridge and services
sudo scripts/install/activate-bridge.sh
```

The installer auto-detects your NICs (with LED blink to identify ports), assigns them to roles, and defers bridge activation until after you rewire cables. Access the dashboard at `https://nettap.local`.

## Tech Stack

| Layer | Component | Purpose |
|-------|-----------|---------|
| Host OS | Ubuntu Server 22.04 LTS | Base system + bridge networking |
| Orchestration | Docker + Docker Compose | Container management |
| Traffic Analysis | [Zeek](https://zeek.org/) 6.x | Network metadata extraction |
| IDS | [Suricata](https://suricata.io/) 7.x | Signature-based intrusion detection |
| Packet Archive | [Arkime](https://arkime.com/) 5.x | Full PCAP storage + session replay |
| Data Store | [OpenSearch](https://opensearch.org/) 2.x | Indexed log storage + dashboards |
| Visualization | [Grafana](https://grafana.com/) 10.x | Custom bandwidth and alert dashboards |
| Core Framework | [Malcolm](https://github.com/cisagov/Malcolm) (CISA) | Bundles the above into a cohesive stack |

## Project Structure

```
scripts/           System setup and bridge configuration
daemon/            Python storage retention + SSD health monitoring
web/               Web UI — setup wizard and traffic dashboard
config/            Configuration overlays for Zeek, Suricata, OpenSearch, Grafana
docker/            Docker Compose and Dockerfiles for NetTap services
```

## Storage Architecture

NetTap uses three-tier rolling retention so you never run out of disk:

| Tier | Data | Retention | Est. Daily Size |
|------|------|-----------|-----------------|
| Hot | Zeek metadata (connections, DNS, TLS, HTTP) | 90 days | 300-800 MB |
| Warm | Suricata IDS alerts | 180 days | 10-50 MB |
| Cold | Raw PCAP (alert-triggered only) | 30 days | Variable |

A background daemon monitors disk utilization and triggers early pruning at 80% capacity. SSD health is tracked via SMART with dashboard alerts for drive wear.

## Roadmap

- [x] Project scaffold and architecture
- [ ] Core infrastructure (bridge scripts, Malcolm deployment)
- [ ] Storage management (ILM, retention daemon, SMART monitoring)
- [ ] Onboarding UX (setup wizard, NIC auto-detection)
- [ ] Dashboard polish (Grafana dashboards, GeoIP maps, notifications)
- [ ] Community release (docs, one-line install, community channels)

See the full [Product Requirements Document](NetTap_PRD_v1.0.md) for detailed specifications.

## Contributing

Contributions are welcome. This project is in early development — check the issues or open one to discuss what you'd like to work on.

## License

[MIT](LICENSE)
