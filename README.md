<p align="center">
  <h1 align="center">NetTap</h1>
  <p align="center">
    <strong>Network visibility appliance for home and small business</strong>
  </p>
  <p align="center">
    <a href="https://github.com/EliasMarine/NetTap/releases/tag/v1.0.0"><img src="https://img.shields.io/badge/version-1.0.0-blue" alt="Version"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Personal%20Use-orange" alt="License"></a>
    <a href="https://github.com/EliasMarine/NetTap/actions/workflows/ci.yml"><img src="https://github.com/EliasMarine/NetTap/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  </p>
</p>

---

NetTap is an inline network appliance that sits transparently between your ISP modem and router. It passively captures and analyzes all traffic using enterprise-grade tools — Zeek, Suricata, Arkime, and OpenSearch — and presents everything through a clean web dashboard. No networking expertise required.

Zero cloud dependency. Zero subscription. Everything runs locally on a ~$200 mini PC.

## Features

**See everything on your network**
- Device inventory with automatic discovery — know every device, what it's doing, and who it's talking to
- Full traffic metadata: DNS queries, TLS handshakes, HTTP requests, file transfers, DHCP leases
- GeoIP mapping shows where your traffic goes, enriched with geography and ASN data
- Bandwidth trending and protocol breakdown per device

**Catch threats automatically**
- Suricata IDS with Emerging Threats ruleset — alerts surface in under 10 seconds
- Device risk scoring (0-100) based on behavior, external connections, and alert history
- New device detection alerts when unknown devices join your network
- Plain English alert descriptions — not raw Suricata signatures

**Investigate like a pro**
- Natural language search: type "show me DNS queries to suspicious domains" instead of writing queries
- Investigation bookmarks with notes for tracking incidents
- Sankey traffic flow diagrams and interactive network topology maps
- TShark deep packet inspection and CyberChef data decoding built in

**Set it and forget it**
- Three-tier storage with automatic retention (90 days metadata, 180 days alerts, 30 days PCAP)
- SSD health monitoring with SMART alerting and write protection
- Network failover and bypass — if NetTap goes down, traffic still flows
- Built-in software update system with one-click rollback

## How It Works

```
[ISP Modem] ──eth0──> [ NetTap Bridge (br0) ] ──eth1──> [Your Router]
                              |
                        passive tap
                              |
                    +--------------------+
                    |  Zeek  + Suricata  |
                    |    v         v     |
                    |     OpenSearch     |
                    |    v         v     |
                    |  Dashboard  Grafana|
                    +--------------------+
                              |
                       mgmt interface
                              |
                    https://nettap.local
```

NetTap creates a transparent Layer 2 bridge between two NICs. Traffic flows through unmodified with <1ms added latency. A separate management interface (3rd NIC, Wi-Fi, or VLAN) serves the web dashboard.

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores, x86_64 | Intel N100 / N305 |
| RAM | 8 GB | 16 GB DDR5 |
| Storage | 256 GB SSD | 1 TB NVMe (1200+ TBW) |
| Network | 2x Ethernet NICs | 2x Intel i226-V 2.5GbE |
| OS | Ubuntu Server 22.04 LTS | Ubuntu Server 22.04 LTS |

**Reference build (~$200):** Intel N100 mini PC (Topton/Beelink) with dual i226-V NICs, 16GB RAM, 1TB NVMe. See the [hardware guide](docs/getting-started/hardware-guide.md) for tested models.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/EliasMarine/NetTap.git
cd NetTap

# Copy and configure environment
cp .env.example .env
nano .env  # Set your NIC names and preferences

# Generate secrets
sudo scripts/generate-secrets.sh

# Run the installer (Ubuntu Server 22.04, as root)
sudo scripts/install/install.sh
```

The installer validates hardware, configures the network bridge, deploys the full Malcolm stack via Docker, and starts all services. A setup wizard walks you through first-run configuration at `https://nettap.local`.

## Tech Stack

| Layer | Component | Role |
|-------|-----------|------|
| Network | Linux bridge (br0) | Transparent Layer 2 forwarding |
| Traffic Analysis | [Zeek](https://zeek.org/) 6.x | Structured metadata extraction |
| IDS | [Suricata](https://suricata.io/) 7.x | Signature-based intrusion detection |
| Packet Archive | [Arkime](https://arkime.com/) 5.x | Full PCAP storage + session replay |
| Data Store | [OpenSearch](https://opensearch.org/) 2.x | Indexed log storage + search |
| Visualization | [Grafana](https://grafana.com/) 10.x | Bandwidth and alert dashboards |
| Web UI | [SvelteKit](https://kit.svelte.dev/) | Dashboard, wizard, device pages |
| Storage Daemon | Python 3.12 | Retention management, SMART monitoring, API |
| Core Framework | [Malcolm](https://github.com/cisagov/Malcolm) (CISA) | Bundles analysis tools into a cohesive stack |

## Project Structure

```
scripts/              System setup, bridge config, firewall, secrets
  bridge/             Linux bridge with netplan persistence
  install/            8-step install orchestrator
daemon/               Python daemon — storage, health, API (30+ endpoints)
  api/                REST API routes
  services/           Business logic (risk scoring, GeoIP, device fingerprinting, etc.)
  storage/            Rolling retention manager with OpenSearch ILM
  smart/              SSD SMART health monitoring
web/                  SvelteKit web application
  src/routes/         Pages: dashboard, devices, alerts, investigations, compliance, settings
  src/lib/components/ Reusable UI: charts, maps, filters, context menus, notifications
config/               Configuration for Zeek, Suricata, OpenSearch ILM, Grafana
docker/               Docker Compose + Dockerfiles (daemon, web, tshark, cyberchef)
docs/                 MkDocs Material documentation site (28 pages)
```

## Storage Architecture

Three-tier rolling retention ensures the drive never fills up:

| Tier | Data | Retention | Daily Size |
|------|------|-----------|------------|
| Hot | Zeek metadata (connections, DNS, TLS, HTTP) | 90 days | 300-800 MB |
| Warm | Suricata IDS alerts | 180 days | 10-50 MB |
| Cold | Raw PCAP (alert-triggered only) | 30 days | Variable |

A background daemon monitors disk utilization with an 80% threshold safeguard and triggers pruning automatically. SSD health is tracked via SMART with dashboard alerts for drive wear.

## Documentation

Full documentation is available at [eliasmarine.github.io/NetTap](https://eliasmarine.github.io/NetTap/) or in the [`docs/`](docs/) directory:

- **[Getting Started](docs/getting-started/quick-start.md)** — Hardware, installation, setup wizard
- **[User Guide](docs/user-guide/dashboard-overview.md)** — Dashboard, alerts, traffic analysis, storage
- **[Admin Guide](docs/admin-guide/configuration.md)** — Configuration, updates, backup, TLS, performance tuning
- **[Developer Guide](docs/developer-guide/architecture.md)** — Architecture, contributing, testing, API reference
- **[Reference](docs/reference/env-reference.md)** — Environment variables, CLI scripts, config files, hardware compatibility

## Contributing

Contributions are welcome for bug reports and feature requests. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, commit conventions, and PR process.

Note: By contributing, you agree to the terms in the [LICENSE](LICENSE) regarding contributions.

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

NetTap is released under the [NetTap Personal Use License](LICENSE).

**Free for personal use.** Commercial use, modification, and redistribution require a separate license. Contact nettap@cybthor.com for commercial licensing inquiries.

Third-party components (Zeek, Suricata, Arkime, OpenSearch, etc.) retain their original open-source licenses. See [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md) for details.
