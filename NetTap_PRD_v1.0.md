# NetTap
## Inline Network Visibility Appliance
### Product Requirements Document — v1.0

**Classification:** Open Source / Public  
**Target Audience:** Home Users, Small Business, Cybersecurity Enthusiasts  
**Status:** Draft for Review

---

## 1. Executive Summary

NetTap is an open source, hardware-agnostic network visibility appliance that sits transparently inline between a user's ISP modem and their home or small business router. It passively captures, enriches, and visualizes all network traffic passing through it, providing Wireshark-level visibility in a polished, always-on dashboard without requiring the user to have deep networking knowledge to benefit from it.

The project targets an underserved gap in the consumer and small business market: enterprise-grade network telemetry at an accessible price point. By leveraging the existing Malcolm open source stack from CISA — which bundles Zeek, Suricata, Arkime, and OpenSearch Dashboards — NetTap focuses its differentiated value on seamless hardware integration, simplified deployment, and a consumer-friendly onboarding experience.

---

## 2. Problem Statement

Home users and small businesses have almost no visibility into what is actually happening on their network at the packet level. Consumer routers expose rudimentary traffic totals at best. Commercial products like Firewalla and eero Pro offer limited insights locked behind subscription paywalls. Open source solutions like Malcolm are powerful but require significant Linux expertise to deploy and operate.

The consequences of this blind spot are meaningful: undetected malware beaconing to C2 infrastructure, IoT devices exfiltrating data, bandwidth being consumed by unknown processes, and no forensic record to investigate incidents after the fact. NetTap solves this by making enterprise network telemetry deployable by anyone who can plug in two ethernet cables.

---

## 3. Goals and Non-Goals

### 3.1 Goals

- Provide full packet capture and metadata logging for all traffic between ISP and router
- Deliver a web-based dashboard with real-time and historical traffic analytics
- Enable deep packet inspection and session-level forensic review via Arkime
- Run IDS/IPS alerting via Suricata with community rulesets pre-loaded
- Be deployable on commodity N100 dual-NIC mini PCs for under $200 hardware cost
- Require no ongoing cloud dependency or subscription fee
- Provide a guided setup wizard for non-technical users
- Implement intelligent rolling storage with configurable retention policies

### 3.2 Non-Goals

- NetTap is not a replacement for a firewall or router — it is a passive observer
- TLS/HTTPS payload decryption is out of scope (metadata-only for encrypted traffic)
- Mobile application development is not in scope for v1.0
- Cloud sync or remote access features are deferred to a future version
- NetTap will not attempt to block traffic in v1.0 — read-only visibility only

---

## 4. Target Users

| Persona | Description | Primary Need |
|---|---|---|
| Home Power User | Tech-savvy individual with a homelab or cybersecurity interest. Comfortable with Linux basics. | Full traffic visibility, SIEM-style alerting, forensic capability |
| Small Business Owner | Runs a 10-50 person office with no dedicated IT staff. Wants simple security insights. | Anomaly alerts, bandwidth reporting, compliance-ready logs |
| Cybersecurity Student | Building practical skills. Has SANS or CompTIA background. Wants hands-on experience. | Learning tool for packet analysis, IDS tuning, incident response practice |
| MSP / IT Consultant | Manages multiple client sites. Wants deployable appliance with centralized visibility. | Multi-site deployment, exportable reports, Graylog/SIEM forwarding |

---

## 5. System Architecture

### 5.1 Physical Layer

The appliance requires a host device with two physical NICs. The recommended reference hardware is an N100-based mini PC with dual Intel i226-V 2.5GbE NICs, 16GB DDR5 RAM, and a 1TB NVMe SSD. The device connects physically between the ISP modem/ONT and the user's router. Both NICs are configured as a transparent Linux software bridge — the device is fully invisible to the network at Layer 2 and does not consume an IP address on the data path.

### 5.2 Software Stack

| Layer | Component | Purpose |
|---|---|---|
| Host OS | Ubuntu Server 22.04 LTS | Base operating system, bridge networking, Docker host |
| Containerization | Docker + Docker Compose | Orchestrates all Malcolm service containers |
| Traffic Capture | Zeek (via Malcolm) | Converts raw packets into structured network metadata logs |
| IDS/IPS | Suricata (via Malcolm) | Signature and anomaly-based intrusion detection with alerting |
| Packet Archive | Arkime (via Malcolm) | Full PCAP storage with session-level search and replay |
| Data Store | OpenSearch (via Malcolm) | Indexed storage of all Zeek logs and Suricata alerts |
| Dashboards | OpenSearch Dashboards | Primary web UI for traffic analytics, filtering, investigation |
| Visualization | Grafana (optional) | Custom dashboards for bandwidth trends and executive summaries |
| GeoIP & Enrichment | Malcolm built-in | Resolves destination IPs to geography, ASN, and threat intel |
| Log Forwarding | Logstash (via Malcolm) | Optional syslog/SIEM forwarding to Graylog or Splunk |

### 5.3 Network Bridge Configuration

At the OS level, the host creates a Linux bridge (`br0`) binding both physical NICs (`eth0` = WAN/modem side, `eth1` = LAN/router side). Traffic flows natively through the bridge with zero routing — the appliance adds no measurable latency to the data path. A separate management interface (either a third NIC, Wi-Fi, or VLAN-tagged port) provides web dashboard access without interfering with monitored traffic.

---

## 6. Storage Architecture

### 6.1 Data Tiers

NetTap uses a three-tier storage strategy to balance forensic depth against available disk space. This approach ensures the drive never fills up while preserving the most valuable data for the longest possible window.

| Tier | Data Type | Retention | Compression | Est. Daily Size |
|---|---|---|---|---|
| Hot | Zeek metadata logs (conn, dns, http, tls, files) | 90 days rolling | zstd (~8:1) | 300–800 MB |
| Warm | Suricata IDS alerts, enriched event records | 180 days rolling | zstd (~6:1) | 10–50 MB |
| Cold / Selective | Raw PCAP (flagged sessions only, triggered by alerts) | 30 days rolling | zstd (~3:1) | Variable |

### 6.2 Rolling Storage Management

OpenSearch index lifecycle management (ILM) handles automatic rotation and deletion of hot-tier data. A custom Python daemon monitors total disk utilization and triggers early pruning if the drive exceeds 80% capacity, ensuring the appliance never goes offline due to storage exhaustion. The user can configure retention periods through the web UI. Raw PCAP storage is triggered only by Suricata alerts or user-defined rules, keeping PCAP volume small and meaningful.

### 6.3 SSD Endurance

Continuous write workloads are demanding on consumer SSDs. NetTap's reference design recommends drives with a minimum 600 TBW endurance rating. The software layer implements write coalescing, in-memory buffering of Zeek logs (flushed every 30 seconds), and Zeek's built-in log rotation to batch writes rather than writing individual packets. A SMART monitoring daemon alerts the user via the dashboard if drive health degrades.

---

## 7. Functional Requirements

### 7.1 Traffic Capture and Processing

- The system MUST capture all packets traversing the bridge interface in promiscuous mode
- Zeek MUST generate structured logs for: connections, DNS, HTTP, TLS, files, SSL certificates, DHCP, and SMTP
- Suricata MUST run continuously against mirrored traffic with Emerging Threats Open ruleset pre-loaded
- Log enrichment MUST include GeoIP resolution, ASN lookup, and hostname/domain resolution
- The system MUST support line rates up to 1Gbps sustained without packet loss on reference hardware

### 7.2 Dashboard and UI

- A web-based dashboard MUST be accessible on the local network at a friendly hostname (e.g., `nettap.local`)
- The home screen MUST display: real-time bandwidth (in/out), top talker IPs, top destinations, protocol distribution, and active alert count
- Users MUST be able to filter all views by time range, source IP, destination IP, protocol, and port
- The Arkime interface MUST allow session search and raw packet replay for any captured session within the retention window
- A dedicated Alerts view MUST surface Suricata detections with severity, rule name, source/destination, and timestamp
- GeoIP maps MUST visualize outbound connection destinations globally

### 7.3 Setup and Configuration

- A first-run setup wizard MUST guide users through network bridge verification, storage configuration, and admin password creation
- The system MUST auto-detect both NICs and validate bridge connectivity before completing setup
- Retention period, storage thresholds, and alert sensitivity MUST be configurable via the web UI without requiring CLI access
- The system MUST support optional Syslog forwarding to external SIEM (Graylog, Splunk, QRadar)

### 7.4 Alerting

- Suricata alerts MUST surface in the dashboard within 10 seconds of detection
- Users MUST be able to configure email or webhook notifications for high-severity alerts
- The system MUST support custom Suricata rule uploads via the web UI
- A threat intelligence feed integration (MISP or OTX) SHOULD be available for IOC matching

---

## 8. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Performance | Bridge must add <1ms latency to traffic path. Dashboard must load within 3 seconds on LAN. |
| Reliability | System must recover automatically from power loss without data corruption. RAID or journaling filesystem required. |
| Security | Dashboard must require authentication. Management interface must be isolated from capture bridge. No telemetry sent externally. |
| Privacy | No packet payloads are stored by default. Only metadata. Raw PCAP storage is opt-in. No cloud dependency. |
| Portability | Docker Compose deployment must run on any x86-64 Linux host. Hardware-agnostic beyond dual NIC requirement. |
| Observability | System health metrics (CPU, RAM, disk, NIC drops, OpenSearch health) must be visible in the dashboard. |

---

## 9. Reference Hardware Specification

| Component | Minimum | Recommended |
|---|---|---|
| CPU | Intel N100 (4-core, 6W TDP) | Intel N100 or N305 |
| RAM | 8GB DDR5 | 16GB DDR5 |
| Storage | 512GB NVMe SSD (600 TBW+) | 1TB NVMe SSD (1200 TBW+) |
| NICs | 2x Gigabit Ethernet (Intel preferred) | 2x Intel i226-V 2.5GbE |
| Management NIC | USB 2.5GbE adapter or Wi-Fi | Dedicated 3rd port or VLAN |
| Form Factor | Mini PC (e.g., Topton, Beelink) | Any x86-64 with dual NIC |
| Power | Any 12V barrel or USB-C PD | <20W under full load |
| Target BOM Cost | — | ~$150–$200 USD |

---

## 10. Open Source Components and Licensing

| Component | License | Version | Role |
|---|---|---|---|
| Malcolm (CISA) | Apache 2.0 | Latest stable | Core capture/analysis stack |
| Zeek | BSD | 6.x | Network metadata extraction |
| Suricata | GPLv2 | 7.x | IDS/IPS engine |
| Arkime | Apache 2.0 | 5.x | PCAP storage and session viewer |
| OpenSearch | Apache 2.0 | 2.x | Data store and dashboards |
| Grafana | AGPLv3 | 10.x | Optional enhanced dashboards |
| Ubuntu Server | Various (GPL-based) | 22.04 LTS | Host operating system |
| Docker | Apache 2.0 | 25.x | Container runtime |

---

## 11. Development Milestones

| Phase | Milestone | Deliverables |
|---|---|---|
| Phase 1 | Core Infrastructure | Linux bridge config scripts, Malcolm deployment automation, reference hardware validation |
| Phase 2 | Storage Management | ILM configuration, rolling retention daemon, SMART monitoring integration, compression tuning |
| Phase 3 | Onboarding UX | First-run setup wizard, NIC auto-detection, admin UI for configuration |
| Phase 4 | Dashboard Polish | Custom Grafana dashboards, GeoIP map view, bandwidth trending, alert notification system |
| Phase 5 | Community Release | GitHub repo, documentation site, install script, Discord community, initial blog post |

---

## 12. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenSearch RAM consumption causes OOM on 16GB systems | High | High | Pre-configure JVM heap caps; provide tuning guide for 16GB vs 32GB deployments |
| Packet loss at sustained 1Gbps due to kernel bridge overhead | Medium | Medium | Evaluate AF_XDP or DPDK for high-speed capture; validate on reference hardware pre-release |
| User confusion with Malcolm's complex multi-pane UI | High | Medium | Build a simplified landing dashboard as the default view; link to advanced Malcolm UI |
| SSD wear from constant writes reduces lifespan | Medium | Low | Implement write coalescing; recommend enterprise-grade NVMe; SMART alerting |
| Malcolm upstream breaking changes disrupt deployment | Low | High | Pin Malcolm to tested release tags; maintain fork of deployment scripts |

---

## 13. Success Metrics

- v1.0 can be deployed end-to-end on reference hardware in under 30 minutes by a user with basic Linux familiarity
- Zero packet loss at 500Mbps sustained throughput on reference hardware
- Dashboard loads within 3 seconds on LAN connection
- Storage consumption stays under 10GB/day on a typical home broadband connection
- 100+ GitHub stars within 90 days of public launch
- Positive community adoption metric: at least 3 independent deployment write-ups within 6 months

---

## 14. Future Considerations (Post v1.0)

- Multi-site deployment mode with centralized Graylog/OpenSearch cluster for MSP use cases
- Threat intelligence feed integration (MISP, OTX, Mandiant) for automated IOC matching
- ML-based anomaly detection for beaconing detection and behavioral baselining
- Optional HTTPS inspection via local CA with user-managed certificate trust
- Mobile-friendly dashboard view
- Pre-built appliance images for Raspberry Pi 5 and similar ARM SBCs
- Community ruleset marketplace for Suricata custom detection rules

---

## Appendix A: Glossary

| Term | Definition |
|---|---|
| Zeek | Open source network analysis framework that converts raw packets into structured, queryable logs |
| Suricata | Open source IDS/IPS engine that detects threats using signatures and protocol analysis |
| Arkime | Open source full packet capture and search tool, formerly known as Moloch |
| Malcolm | Open source network traffic analysis tool suite published by CISA, bundles Zeek/Suricata/Arkime/OpenSearch |
| PCAP | Packet Capture — the raw binary format storing captured network packets |
| Zeek Metadata | Structured logs extracted from packets including connection tuples, DNS queries, TLS certs, file hashes |
| Linux Bridge | Kernel-level Layer 2 forwarding mechanism that makes two NICs act as a transparent network switch |
| ILM | Index Lifecycle Management — OpenSearch policy for automatic rotation and deletion of old indices |
| TBW | Terabytes Written — SSD endurance rating measuring total data that can be written before wear |
| GeoIP | Database mapping IP addresses to geographic location, country, and organization (ASN) |
