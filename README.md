# NetTap

[![CI](https://github.com/EliasMarine/NetTap/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/EliasMarine/NetTap/actions/workflows/ci.yml)

**A network visibility appliance for home users and small businesses.**

NetTap watches the traffic on your network and shows it in a web dashboard: which devices talk to what, intrusion alerts, DNS, TLS certificates and full packet captures. It wraps CISA's [Malcolm](https://github.com/cisagov/Malcolm) stack (Zeek, Suricata, OpenSearch) with an installer, a setup wizard, its own dashboard and automatic storage management.

> **Status:** Pre-release. No version has been tagged yet. Phases 1–3 (core infrastructure, storage management, onboarding) are done. Phase 4 (dashboard polish) is in progress and is being tested on real hardware. See the [PRD](NetTap_PRD_v1.0.md) for the full product specification.

## What It Does

- **Traffic metadata** — Zeek logs every connection, DNS query, TLS handshake, HTTP request and file transfer
- **Intrusion detection** — Suricata with the Emerging Threats Open ruleset; alerts get a plain-English description
- **Device view** — devices are discovered and listed with their traffic, alerts, risk score and (for smart-home devices) a trust score
- **Packet capture** — netsniff-ng records full captures, capped at a share of the disk; search, preview and download them on the PCAP Search page and dig in with the built-in TShark and CyberChef tools
- **GeoIP** — traffic is enriched with country and ASN data
- **Storage management** — old data is deleted on a schedule, and earlier if the disk fills up, so the drive never runs out
- **Drive health** — SMART monitoring of the SSD (wear, temperature, errors)
- **Updates** — check for and apply updates to the Malcolm release NetTap has tested, with a backup and rollback
- **No cloud, no subscription** — captured traffic, logs and PCAP stay on the box. Some features contact the internet: update checks, rule updates and WHOIS lookups

## Capture Modes

You pick a capture mode in the setup wizard. The wizard recommends DHCP gateway mode, offers mirror mode, and keeps the inline bridge under "Advanced". Today the mode can only be chosen during setup.

**DHCP gateway (one NIC).** NetTap plugs into your router, hands out addresses on its own subnet and names itself as every device's gateway. It passes traffic on to the router (double NAT), so it sees each device's own address before the router's NAT. The only router change is turning off the router's DHCP server. NetTap refuses to start its DHCP server while another one answers on the network. Limits: devices with a static IP bypass NetTap; IPv6 from the router bypasses it; device-to-device traffic is not seen; port forwards on the router stop reaching devices. If NetTap is down, devices lose internet until you turn the router's DHCP back on; the Go Live page shows how. This mode is unit-tested but **not yet verified on real hardware**.

```
[ISP Modem] ── [Router, DHCP off] ── [NetTap, 1 NIC]
                     │                  hands out addresses,
                 your devices  ◀──────  routes to the router
                (gateway = NetTap)
```

**Mirror / SPAN (one capture NIC).** A managed switch sends a copy of traffic to a NetTap port. NetTap is not in the traffic path, so it cannot break your network. The capture NIC has no IP address; the dashboard is reached through a separate management interface.

```
[Router] ── [Managed switch] ── your devices
                  │ mirror (SPAN) port
                  ▼
         [NetTap capture NIC]
```

**Inline bridge (Advanced, two NICs).** NetTap sits between the ISP modem and the router as a transparent Layer 2 bridge. It sees all internet traffic, but only after the router's NAT, so every device appears as the router's public IP. The bridge is a kernel bridge, so it keeps forwarding if NetTap's containers stop. A separate management interface (a third NIC or Wi-Fi) serves the dashboard.

```
[ISP Modem] ──WAN NIC──▶ [ NetTap bridge (br0) ] ──LAN NIC──▶ [Router]
```

In every mode, the data flows the same way:

```
captured packets ──▶ Zeek (metadata) + Suricata (IDS) + netsniff-ng (PCAP files)
                              │
                          OpenSearch
                              │
              NetTap dashboard  https://nettap.local
```

Design targets, not yet verified on hardware: under 1 ms added latency in bridge mode, alerts on the dashboard within 10 seconds, dashboard loads in under 3 seconds on the LAN.

## Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | x86-64, 2 cores | Intel N100 or equivalent |
| RAM | 8 GB | 16 GB |
| Storage | 512 GB SSD | 1 TB NVMe SSD |
| NICs | 2 physical Ethernet ports | 2x Intel i226-V 2.5GbE + a management interface |

ARM is not supported. The installer currently needs at least two physical NICs, even if you then choose a one-NIC mode in the wizard. If your box has Wi-Fi, it can be the management interface so both wired ports are free for capture. See [Requirements](docs/getting-started/requirements.md) and the [Hardware Guide](docs/getting-started/hardware-guide.md).

## Quick Start

On Ubuntu Server 22.04 or 24.04 LTS, with internet access:

```bash
git clone https://github.com/EliasMarine/NetTap.git
cd NetTap
sudo scripts/install/install.sh
```

The installer:

1. Finds your NICs, blinks their port LEDs so you can tell them apart, and asks you to assign roles (MGMT, WAN, LAN)
2. Installs Docker and the system packages, and tunes the kernel
3. Activates the bridge (skip with `--skip-bridge`, or wait until cables are moved with `--defer-bridge`)
4. Pulls and starts the pinned Malcolm images and NetTap's own services
5. Sets up systemd services, mDNS and (if UFW is active) firewall rules, then prints a wiring diagram

Then open `https://nettap.local` from a device on your network. NetTap makes its own TLS certificate, so your browser shows a warning the first time. The setup wizard asks for the capture mode, network ports, storage retention, enrichment options and an admin account. Run `sudo scripts/install/install.sh --help` for all installer options.

## Dashboard Pages

| Page | What it shows |
|------|---------------|
| Home | Summary: alerts, bandwidth over time, protocols, top devices, traffic categories |
| Log Explorer | Search all Zeek and Suricata records |
| Devices | Every device seen on the network; click one for its traffic, DNS and connections |
| Alerts | Suricata alerts by category, with plain-English descriptions |
| Threats | Behaviour-based detection: beaconing, lateral movement, DNS anomalies |
| Connections | Network session explorer |
| Live Monitor | Real-time connections with a map, protocol chart and top talkers |
| Bandwidth | Daily usage, per-device breakdown and a time-of-day heatmap |
| DNS Analytics | Domain queries, NXDOMAIN errors and suspicious patterns |
| IoT & LAN | Trust score per smart-home device: privacy, security and behaviour |
| Changelog | Timeline of network events, such as devices joining or leaving |
| Certificates | TLS certificates seen on the network |
| PCAP Search | Search, preview and download packet captures |
| Tools | TShark, CyberChef, ping, DNS recon, SSL check, subnet calculator, MAC lookup, port reference, Base64 |
| Infrastructure | Health of the capture pipeline, from capture to OpenSearch |
| System | Services, storage, OpenSearch and drive health; the Updates page applies Malcolm updates |
| Settings | Notifications, retention, capture, API keys, network, integrations, Suricata rules, backup |

Setup (`/setup`) runs the first-run wizard, and Go Live (`/go-live`) checks readiness and cabling. Investigations (`/investigations`) and Security Posture (`/compliance`) are reachable by URL but are not in the menu.

## Tech Stack

| Layer | Component | Notes |
|-------|-----------|-------|
| Host OS | Ubuntu Server 22.04 or 24.04 LTS | x86-64 only |
| Orchestration | Docker + Docker Compose | |
| Core framework | [Malcolm](https://github.com/cisagov/Malcolm) 26.10.0 | Pinned in `scripts/install/malcolm-versions.conf` and `docker/docker-compose.yml` |
| Traffic analysis | [Zeek](https://zeek.org/) | From the Malcolm images |
| IDS | [Suricata](https://suricata.io/) | Emerging Threats Open ruleset |
| Packet archive | netsniff-ng (Malcolm `pcap-capture`) | Arkime is off by default (compose profile `arkime`) |
| Data store | [OpenSearch](https://opensearch.org/) | With Logstash and Filebeat for ingest |
| NetTap daemon | Python, aiohttp | API, storage retention, SMART, capture modes |
| Web UI | SvelteKit (Svelte 5) behind nginx | |
| Grafana | 10.4.2 | Off by default (`--profile grafana`); its dashboards do not match Malcolm's indices yet |

## Storage

| Data | Where | Default retention |
|------|-------|-------------------|
| Zeek metadata and Suricata alerts | OpenSearch, one index per day | 90 days (`RETENTION_HOT`) |
| Raw packet captures | PCAP files on disk | 30 days (`RETENTION_COLD`), and at most 25% of the disk (`PCAP_MAX_DISK_PCT`) |

Malcolm writes Zeek logs and Suricata alerts into the same daily index, so they share one retention period. When PCAP passes its share of the disk, the oldest files go first. You can change retention in the setup wizard and on the Settings page.

The storage daemon checks the disk every 5 minutes:

- **80%** (`DISK_THRESHOLD_PERCENT`): deletes indices that are past their retention
- **90%** (`EMERGENCY_THRESHOLD_PERCENT`): deletes the oldest PCAP, then the oldest indices if still needed
- **95%**: also stops packet capture, and restarts it once usage drops below 85%

## Project Structure

```
scripts/           Installer, bridge and bypass scripts, device deploy scripts
daemon/            Python daemon: API, storage retention, SMART, capture modes
web/               SvelteKit web UI: setup wizard and dashboard pages
config/            Overrides for Zeek, Suricata, OpenSearch, Logstash and capture
docker/            Docker Compose file, Dockerfiles and nginx config
docs/              User, admin and developer guides (MkDocs) and design docs
tests/             Shell-script tests (bats) and a sample PCAP
plans/             Build plan and feature plans
Debugging/         Bridge architecture, deployment issues, release verification
tracking-fixes/    One note per fix: cause, change and tests
```

## Development

```bash
cd daemon && python3 -m pytest -q    # daemon tests
cd web && npx vitest run             # web unit tests
cd web && npx svelte-check           # web type check
```

See the [Developer Guide](docs/developer-guide/dev-setup.md) for setup, and [Testing](docs/developer-guide/testing.md) for more. The full docs are in [`docs/`](docs/index.md): getting started, user guide, admin guide, developer guide and reference.

## Roadmap

- [x] Core infrastructure (bridge scripts, Malcolm deployment)
- [x] Storage management (retention, disk safeguards, SMART monitoring)
- [x] Onboarding (installer, NIC detection, setup wizard)
- [ ] Dashboard polish (pages built; hardware testing in progress)
- [ ] DHCP gateway mode verified on hardware, and switching capture mode after setup
- [ ] Community release, v1.0 (CI and docs exist; hardware sign-off and launch pending)

## Contributing

Bug reports and feature requests are welcome in the issue tracker. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request; section 4 of the [license](LICENSE) covers the rights you grant on contributions.

## License

NetTap is released under the [NetTap Personal Use License](LICENSE). You may install and use it for personal, non-commercial purposes and study the source. Commercial use, modification and redistribution need written permission; see the license for contact details. Third-party components (Malcolm, Zeek, Suricata, OpenSearch and others) keep their own licenses; see [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
