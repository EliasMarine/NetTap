# Architecture

This page provides a deep-dive into the NetTap system architecture, covering the network layer, data pipeline, storage tiers, and service topology.

---

## High-Level Architecture

```
                        ┌───────────────────────────────────────────┐
                        │              NetTap Appliance               │
ISP Modem ──────────────┤                                             │
          eth0 (WAN)    │  ┌──────────────────────────────────────┐  │
                        │  │         br0 (Transparent Bridge)      │  │
          eth1 (LAN)    │  │   STP off | FwdDelay 0 | Promisc on  │  │
Router ─────────────────┤  └──────────────┬───────────────────────┘  │
                        │                 │ Promiscuous capture       │
                        │    ┌────────────┼────────────┐             │
                        │    │            │            │             │
                        │    ▼            ▼            ▼             │
                        │  Zeek       Suricata      Arkime           │
                        │  (metadata)  (IDS)       (PCAP)           │
                        │    │            │            │             │
                        │    ▼            ▼            ▼             │
                        │  Filebeat ─── Logstash ──► OpenSearch     │
                        │                               │            │
                        │              ┌────────────────┤            │
                        │              ▼                ▼            │
                        │         NetTap Web       Grafana           │
                        │         Dashboard        Dashboards        │
                        │              │                             │
          eth2 (MGMT)   │              │                             │
Dashboard Access ───────┤    nettap-nginx (TLS termination)         │
                        └───────────────────────────────────────────┘
```

---

## Network Layer

### Transparent Bridge

NetTap creates a Linux software bridge (`br0`) binding two physical NICs. This bridge operates at Layer 2, transparently forwarding all Ethernet frames between the WAN and LAN interfaces.

Key properties:

- **No IP address on bridge** --- the appliance is invisible on the data path
- **STP disabled** --- no learning delay; immediate forwarding
- **Forward delay = 0** --- packets are forwarded without any hold-time
- **Multicast snooping disabled** --- all multicast passes through transparently
- **MAC ageing disabled** --- no MAC table expiry (reduces jitter)
- **Promiscuous mode** --- both NICs capture all frames, not just those addressed to them
- **IPv6 disabled on br0** --- prevents the bridge from being discoverable

### Performance Tuning

The bridge setup script applies NIC-level tuning:

- **Hardware offloads disabled** (TSO, GSO, GRO, LRO) --- ensures Zeek and Suricata see actual wire-format packets
- **RX ring buffer increased** to 4096 entries --- prevents packet drops during traffic bursts
- **Bridge netfilter disabled** --- bypasses iptables processing for bridged traffic (significant performance improvement)

### Management Interface

A separate network interface (3rd NIC, Wi-Fi, or VLAN) provides dashboard access. This interface has an IP address and is not part of the bridge.

---

## Data Pipeline

The data flows through these stages:

### 1. Packet Capture

Three capture engines run simultaneously with `network_mode: host` to directly access the bridge interface:

| Engine | Container | Purpose |
|---|---|---|
| **Zeek** | `nettap-zeek-live` | Generates structured metadata logs for every connection |
| **Suricata** | `nettap-suricata-live` | IDS alerting using Emerging Threats ruleset |
| **netsniff-ng** | `nettap-pcap-capture` | Raw PCAP file capture |
| **Arkime** | `nettap-arkime-live` | Full packet capture with session indexing |

### 2. Log Collection

**Filebeat** (`nettap-filebeat`) monitors the Zeek and Suricata log directories via shared Docker volumes:

- `zeek-live-logs` --- Zeek JSON log files
- `suricata-live-logs` --- Suricata Eve JSON files

Filebeat ships log events to Logstash for enrichment.

### 3. Log Enrichment

**Logstash** (`nettap-logstash`) processes and enriches logs:

- GeoIP lookups (country, city, ASN)
- OUI lookups (MAC address to manufacturer)
- Severity scoring
- Field normalization

Enriched events are indexed into OpenSearch.

### 4. Storage and Indexing

**OpenSearch** (`nettap-opensearch`) stores all indexed data:

- `zeek-*` indices --- connection metadata
- `suricata-*` indices --- IDS alerts and protocol logs
- `arkime-*` / `pcap-*` indices --- packet capture session metadata

### 5. Visualization

Two visualization layers:

- **NetTap Dashboard** (`nettap-web`) --- SvelteKit-based custom dashboard querying OpenSearch via the daemon API
- **Grafana** (`nettap-grafana`) --- Enhanced dashboards for network overview, bandwidth trending, GeoIP maps, security alerts, and system health

---

## Service Topology

### Container Map

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose Stack                       │
│                                                              │
│  DATA STORE                                                  │
│  ├── opensearch          (OpenSearch 2.x, port 9200)        │
│                                                              │
│  DASHBOARDS                                                  │
│  ├── dashboards          (OpenSearch Dashboards)             │
│  ├── dashboards-helper   (Dashboard initialization)          │
│                                                              │
│  LOG PIPELINE                                                │
│  ├── logstash            (Log enrichment, port 5044)        │
│  ├── filebeat            (Log shipping)                      │
│                                                              │
│  LIVE CAPTURE (host network)                                 │
│  ├── zeek-live           (Zeek metadata analysis)           │
│  ├── suricata-live       (Suricata IDS)                     │
│  ├── pcap-capture        (netsniff-ng raw capture)          │
│  ├── arkime-live         (Arkime session indexer)           │
│                                                              │
│  INFRASTRUCTURE                                              │
│  ├── redis               (Caching and queues)               │
│  ├── api                 (Malcolm REST API)                  │
│  ├── nginx-proxy         (Malcolm reverse proxy, port 9443) │
│                                                              │
│  NETTAP SERVICES                                             │
│  ├── nettap-storage-daemon  (Storage/SMART daemon, API)     │
│  ├── nettap-web             (SvelteKit dashboard)           │
│  ├── nettap-grafana         (Grafana dashboards)            │
│  ├── nettap-nginx           (TLS reverse proxy, port 443)   │
│  ├── nettap-tshark          (Packet decoder)                │
│  └── nettap-cyberchef       (Data transformation tool)      │
└─────────────────────────────────────────────────────────────┘
```

### Dependency Chain

```
opensearch (must be healthy first)
  ├── dashboards-helper
  ├── dashboards
  ├── logstash
  │     └── filebeat
  ├── api
  │     └── nginx-proxy
  ├── nettap-storage-daemon
  └── nettap-web
```

Capture containers (Zeek, Suricata, Arkime, pcap-capture) have no service dependencies --- they start immediately and write to shared volumes.

---

## Storage Architecture

### Three-Tier Model

| Tier | Index Pattern | Data Type | Retention | Daily Size |
|---|---|---|---|---|
| Hot | `zeek-*` | Zeek metadata | 90 days | 300--800 MB |
| Warm | `suricata-*` | Suricata alerts | 180 days | 10--50 MB |
| Cold | `arkime-*`, `pcap-*` | Raw PCAP | 30 days | Variable |

### Lifecycle

Each tier has an OpenSearch ISM (Index State Management) policy defined in `config/opensearch/ilm-policy.json`:

- **Hot policy:** Rollover at 10 GB or 1 day, delete after 90 days
- **Warm policy:** Rollover at 5 GB or 1 day, force-merge and read-only after 7 days, delete after 180 days
- **Cold policy:** Rollover at 20 GB or 1 day, delete after 30 days

### Disk Safety

The storage daemon (`nettap-storage-daemon`) runs a maintenance cycle every 5 minutes:

1. Check disk utilization against threshold (80% warning, 90% emergency)
2. If above threshold, identify and delete oldest expired indices
3. Report status via the `/api/storage/status` endpoint

---

## Security Model

### Container Hardening

All containers follow these security practices:

- `no-new-privileges: true` --- prevents privilege escalation
- `cap_drop: ALL` --- drops all Linux capabilities by default
- Capabilities added back only where required (e.g., `NET_RAW` for capture)
- `read_only: true` with explicit `tmpfs` mounts where write access is needed
- Internal services are not exposed to the host network

### Network Isolation

- OpenSearch port 9200 is bound to `127.0.0.1` only --- never exposed externally
- The daemon API (port 8880) is only `expose`d to other containers, not `ports` mapped to the host
- Dashboard access is via the nginx reverse proxy with TLS termination

### Bridge Security

The bridge itself is hardened:

- No IP addresses on the bridge interface (invisible on the network)
- IPv6 disabled on the bridge
- Bridge netfilter disabled (no iptables interference)

---

## Project Directory Structure

```
/opt/nettap/
  scripts/             Shell scripts for system setup
    bridge/            Linux bridge configuration
    install/           Installation automation
    common.sh          Shared shell utilities
  daemon/              Python storage & health daemon
    storage/           Rolling retention manager
    smart/             SSD SMART health monitoring
    api/               REST API endpoints
    services/          Business logic services
    main.py            Daemon entry point
  web/                 SvelteKit web dashboard
    src/routes/        Page routes
    src/lib/           Shared components and utilities
  config/              Configuration files
    malcolm/           Malcolm stack overrides
    opensearch/        ILM policies
    suricata/          Suricata config overrides
    zeek/              Zeek script overrides
    grafana/           Grafana dashboard JSON + provisioning
    watchdog/          Hardware watchdog configuration
  docker/              Docker Compose and Dockerfiles
    docker-compose.yml All services
    Dockerfile.daemon  Python daemon container
    Dockerfile.web     Web UI container
  docs/                MkDocs documentation (this site)
```
