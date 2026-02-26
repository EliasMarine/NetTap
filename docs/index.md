# NetTap

**Open-source network visibility for your home or small business.**

NetTap is a hardware-agnostic network appliance that sits transparently inline between your ISP modem and router. It captures and analyzes all network traffic, giving you enterprise-grade telemetry through a polished web dashboard --- without requiring deep networking knowledge.

---

## What NetTap Does

NetTap creates a transparent Layer 2 bridge between two network interfaces. All traffic passes through unmodified while NetTap silently inspects it using industry-standard tools:

- **Zeek** generates structured metadata logs for every connection (DNS, HTTP, TLS, DHCP, SMTP, and more)
- **Suricata** performs signature-based intrusion detection using the Emerging Threats ruleset
- **Arkime** captures full packets for alert-triggered forensic analysis
- **OpenSearch** indexes everything for fast search and visualization

The result: you see exactly what every device on your network is doing, which external servers they talk to, and whether any of that traffic is suspicious.

---

## Key Features

- **Device-Centric Dashboard** --- see what each device is doing at a glance, with bandwidth, connections, and risk scores
- **Plain English Alerts** --- Suricata IDS detections with human-readable explanations, not raw signatures
- **Zero Configuration Capture** --- transparent bridge adds less than 1ms latency and requires no changes to your network
- **Three-Tier Storage** --- intelligent retention policies keep 90 days of metadata, 180 days of alerts, and 30 days of packet captures
- **SSD Health Monitoring** --- SMART monitoring with automatic write coalescing to protect drive endurance
- **Built-in Update System** --- check for and apply updates from the dashboard
- **No Cloud Dependency** --- everything runs locally. No subscriptions, no telemetry, no data leaves your network
- **Setup Wizard** --- guided first-run experience walks you through NIC selection, bridge creation, and Malcolm deployment

---

## Quick Links

| I want to... | Go to... |
|---|---|
| Get NetTap running in 5 minutes | [Quick Start](getting-started/quick-start.md) |
| Check if my hardware is compatible | [Hardware Guide](getting-started/hardware-guide.md) |
| Understand the installation process | [Installation](getting-started/installation.md) |
| Learn the dashboard | [Dashboard Overview](user-guide/dashboard-overview.md) |
| Investigate an alert | [Alerts](user-guide/alerts.md) |
| Tune performance | [Performance Tuning](admin-guide/performance-tuning.md) |
| Forward logs to my SIEM | [SIEM Forwarding](user-guide/siem-forwarding.md) |
| Contribute to the project | [Contributing](developer-guide/contributing.md) |
| See all configuration options | [Environment Reference](reference/env-reference.md) |

---

## Architecture at a Glance

```
ISP Modem ─── [ eth0 (WAN) ]──╮
                               ├── br0 (transparent bridge) ── capture
Router ─────── [ eth1 (LAN) ]──╯         │
                                          ▼
                                   Zeek + Suricata + Arkime
                                          │
                                          ▼
                                     OpenSearch
                                          │
                                          ▼
                                   NetTap Dashboard (web UI)
                                   accessed via management NIC / Wi-Fi
```

NetTap is invisible on the data path. Your ISP modem and router communicate exactly as before --- NetTap just listens.

---

## Technology Stack

| Component | Role | Version |
|---|---|---|
| Ubuntu Server | Host OS | 22.04 / 24.04 LTS |
| Docker + Compose | Container orchestration | v2+ |
| Malcolm (CISA) | Network analysis platform | 26.02.0 |
| Zeek | Network metadata analysis | 6.x |
| Suricata | Intrusion detection (IDS) | 7.x |
| Arkime | Full packet capture | 5.x |
| OpenSearch | Search and analytics engine | 2.x |
| Grafana | Enhanced visualizations | 10.4.x |
| SvelteKit | Web dashboard framework | 2.x |
| Python (aiohttp) | Storage/health daemon | 3.10+ |

---

## Project Status

NetTap is in active development. The current release covers:

- Core infrastructure (bridge, Malcolm deployment, hardware validation)
- Storage management (ILM policies, retention daemon, SMART monitoring)
- Onboarding UX (setup wizard, NIC auto-detection)
- Dashboard (live traffic, alerts, devices, investigations, compliance)
- Community release (documentation, CI/CD, security hardening)

---

## License

NetTap is open-source software. All core components use permissive licenses (Apache 2.0, BSD, GPLv2). Grafana is AGPLv3.
