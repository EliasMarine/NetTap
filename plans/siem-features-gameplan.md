# NetTap SIEM-Inspired Features — Implementation Game Plan

**Created:** 2026-02-26
**Status:** Approved
**Scope:** 20 features (10 Must-Have + 10 Should-Have) fully integrated with tests

---

## Overview

Based on competitive research across 10 SIEM/network tools (Splunk, Elastic, Wazuh, Security Onion, Graylog, Grafana, PRTG, Firewalla, Pi-hole, ntopng), this plan adds 20 features organized into 5 implementation groups. Each feature includes daemon backend, SvelteKit frontend, and full test coverage.

### Three Pillars of Differentiation
1. **Device-Centric View** — Organize by "what are my devices doing?" not by log type
2. **Plain English Explanations** — Every alert gets a human-readable description
3. **Immediate Visual Value** — Big numbers, color coding, progressive disclosure

---

## Implementation Groups

### Group A: Data Foundation (Sprint 1)
*Must come first — provides the data layer all UI features depend on*

| # | Feature | Type | Daemon Files | Web Files | Tests |
|---|---------|------|-------------|-----------|-------|
| A1 | Device Inventory API | Must-Have | `daemon/api/devices.py`, `daemon/services/device_fingerprint.py` | `web/src/lib/api/devices.ts` | `test_devices_api.py`, `devices.test.ts` |
| A2 | Traffic Categorization API | Must-Have | `daemon/api/traffic.py` (extend), `daemon/services/traffic_classifier.py` | `web/src/lib/api/traffic.ts` (extend) | `test_traffic_classifier.py`, `traffic.test.ts` (extend) |
| A3 | Alert Description Enrichment | Must-Have | `daemon/services/alert_enrichment.py`, `daemon/data/suricata_descriptions.json` | — | `test_alert_enrichment.py` |
| A4 | GeoIP Lookup Service | Foundation | `daemon/services/geoip_service.py`, `daemon/api/geoip.py` | `web/src/lib/api/geoip.ts` | `test_geoip_service.py`, `geoip.test.ts` |

**Estimated new tests:** ~80 (daemon) + ~40 (web) = ~120 tests

#### A1: Device Inventory API

**What it does:** Automatically discovers and catalogs every device on the network by querying Zeek logs for unique source IPs, enriched with MAC addresses (from DHCP logs), hostnames (from DNS logs), manufacturer (OUI lookup from MAC), and OS fingerprint (from HTTP User-Agent and JA3/JA4 TLS fingerprints).

**Daemon implementation:**

```
daemon/api/devices.py
├── GET /api/devices                    — List all discovered devices
│   Query: terms agg on id.orig_h across zeek-conn-*, zeek-dhcp-*, zeek-dns-*
│   Returns: [{ip, mac, hostname, manufacturer, os_hint, first_seen, last_seen,
│              total_bytes, connection_count, protocols: [], alert_count, risk_score}]
│   Params: ?from=&to=&sort=bytes|alerts|last_seen&order=desc&limit=100
│
├── GET /api/devices/{ip}               — Single device detail
│   Query: filtered search across all zeek-* indices for this IP
│   Returns: {ip, mac, hostname, manufacturer, os_hint, first_seen, last_seen,
│             bandwidth_series: [], top_destinations: [], top_protocols: [],
│             recent_connections: [], recent_alerts: [], dns_queries: []}
│
└── GET /api/devices/{ip}/connections   — Paginated connections for device
    Query: zeek-conn-* where id.orig_h == ip OR id.resp_h == ip
    Returns: {page, size, total, connections: []}

daemon/services/device_fingerprint.py
├── get_mac_for_ip(ip)                  — Query zeek-dhcp-* for MAC
├── get_hostname_for_ip(ip)             — Query zeek-dns-* for PTR/A records
├── get_manufacturer_from_mac(mac)      — OUI prefix lookup (bundled IEEE database)
├── get_os_from_useragent(ip)           — Query zeek-http-* for User-Agent
└── get_os_from_ja3(ip)                 — Query zeek-ssl-* for JA3 fingerprint
```

**OUI Database:** Bundle a trimmed IEEE OUI file (~300KB) at `daemon/data/oui.txt`. Parse MAC prefix → manufacturer name. Update periodically via script.

**Web implementation:**

```
web/src/lib/api/devices.ts
├── getDevices(opts?)                   — Fetch device list
├── getDeviceDetail(ip)                 — Fetch single device
├── getDeviceConnections(ip, opts?)     — Paginated connections

web/src/routes/devices/+page.svelte     — Device inventory table page
web/src/routes/devices/[ip]/+page.svelte — Per-device detail page
web/src/routes/api/devices/+server.ts   — Proxy to daemon
web/src/routes/api/devices/[ip]/+server.ts
web/src/routes/api/devices/[ip]/connections/+server.ts
```

**Tests (daemon):**
- `test_devices_api.py`: 15+ tests — list devices, single device, connections, time range filtering, sorting, pagination, empty results, error handling
- `test_device_fingerprint.py`: 12+ tests — MAC lookup, hostname resolution, OUI parsing, User-Agent extraction, JA3 matching, cache behavior

**Tests (web):**
- `devices.test.ts`: 12+ tests — API client functions, error handling, parameter building

---

#### A2: Traffic Categorization

**What it does:** Maps raw protocol names (tcp, udp, tls) and Zeek service names (http, dns, ssl) into human-readable categories: Streaming, Gaming, Social Media, IoT Telemetry, Work/Productivity, Communication, File Transfer, DNS, Suspicious, Other.

**Implementation:**

```
daemon/services/traffic_classifier.py
├── CATEGORY_RULES: dict               — Domain pattern → category mapping
│   e.g., "*.netflix.com" → "Streaming", "*.zoom.us" → "Communication"
│   "*.facebook.com" → "Social Media", "*.github.com" → "Work"
├── classify_connection(conn)           — Returns category string
├── classify_domain(domain)             — Domain → category lookup
└── get_category_stats(from, to)        — Aggregated bytes/connections per category

daemon/api/traffic.py (extend)
└── GET /api/traffic/categories?from=&to=
    Query: terms agg on service + sub-agg on resp_host domains
    Returns: {categories: [{name, total_bytes, connection_count, top_domains: []}]}
```

**Category mapping strategy:**
1. First check Zeek `service` field (http, dns, ssh, smtp, ftp, etc.)
2. Then check destination domain from `zeek-dns-*` correlation
3. Then check destination port for well-known services
4. Fall back to protocol name (TCP/UDP)

**Tests:**
- `test_traffic_classifier.py`: 15+ tests — domain classification, port-based fallback, unknown domains, category stats aggregation, edge cases

---

#### A3: Alert Description Enrichment

**What it does:** Translates Suricata signature names into plain English descriptions. Maintains a curated mapping of common Suricata SIDs to human-readable explanations with severity context.

**Implementation:**

```
daemon/services/alert_enrichment.py
├── DESCRIPTION_DB: dict                — SID → {description, risk_context, recommendation}
│   Loaded from daemon/data/suricata_descriptions.json
├── enrich_alert(alert)                 — Add plain_description, risk_context, recommendation
├── generate_description(signature)     — Pattern-based fallback for unmapped SIDs
│   e.g., "ET MALWARE *" → "Potential malware activity detected: {signature detail}"
│   "ET SCAN *" → "Network scanning detected: {detail}"
│   "ET POLICY *" → "Policy violation: {detail}"
└── get_recommendation(category)        — Action suggestion per alert category

daemon/data/suricata_descriptions.json  — 200+ curated SID → description mappings
```

**Fallback strategy for unmapped SIDs:**
1. Parse the Suricata signature prefix (ET MALWARE, ET SCAN, ET POLICY, ET TROJAN, etc.)
2. Generate a category-appropriate plain English template
3. Include the original signature name for technical reference

**Extend `daemon/api/alerts.py`:**
- Alerts list and detail responses now include `plain_description`, `risk_context`, `recommendation` fields

**Tests:**
- `test_alert_enrichment.py`: 15+ tests — known SID lookup, pattern-based fallback for each ET category, unknown SIDs, recommendation generation

---

#### A4: GeoIP Lookup Service

**What it does:** Resolves IP addresses to country, city, ASN, and organization. Uses MaxMind GeoLite2 database (free, requires registration) with in-memory caching.

**Implementation:**

```
daemon/services/geoip_service.py
├── GeoIPService(db_path)              — Initialize with GeoLite2 database
├── lookup(ip)                         — Returns {country, country_code, city, latitude,
│                                         longitude, asn, organization, is_private}
├── lookup_batch(ips)                  — Batch lookup for multiple IPs
└── is_private(ip)                     — Check RFC1918/link-local/loopback

daemon/api/geoip.py
├── GET /api/geoip/{ip}                — Single IP lookup
└── GET /api/geoip/batch?ips=1,2,3     — Batch lookup (max 50)
```

**Database:** GeoLite2-City.mmdb (~65MB). Bundled or downloaded at install time.
**Fallback:** If no database, return `{country: "Unknown", is_private: true/false}` based on RFC1918 check.

**Tests:**
- `test_geoip_service.py`: 12+ tests — private IP detection, public IP lookup (mocked DB), batch lookup, missing database fallback, cache behavior

---

### Group B: Core UI Features (Sprint 2)
*Depends on Group A data layer*

| # | Feature | Type | Files | Tests |
|---|---------|------|-------|-------|
| B1 | Device Inventory Page | Must-Have | `web/src/routes/devices/+page.svelte` | Component tests |
| B2 | Per-Device Activity Page | Must-Have | `web/src/routes/devices/[ip]/+page.svelte` | Component tests |
| B3 | Alert-to-Detail Pivot | Must-Have | `web/src/lib/components/AlertDetailPanel.svelte` | Component tests |
| B4 | Right-Click Context Menus | Must-Have | `web/src/lib/components/ContextMenu.svelte` | Component tests |
| B5 | Enhanced Hero Dashboard | Must-Have | `web/src/routes/+page.svelte` (rewrite) | Existing tests updated |
| B6 | Dashboard Template Variables | Must-Have | `web/src/lib/components/DashboardFilters.svelte` | Component tests |

**Estimated new tests:** ~60 (web component + integration)

#### B1: Device Inventory Page (`/devices`)

**Layout:**
- Header: "Devices" + device count badge + time range selector
- Search bar: Filter by IP, hostname, or manufacturer
- Sortable table: IP | Hostname | Manufacturer | OS | Bandwidth | Connections | Alerts | Risk | Last Seen
- Each row is clickable → navigates to `/devices/{ip}`
- Risk score column: Color-coded badge (green 0-30, yellow 31-60, orange 61-80, red 81-100)
- Device type icons: Computer, Phone, IoT, Server, Router, Unknown

**Key interactions:**
- Click column header → sort
- Click row → navigate to device detail
- Right-click IP → context menu (pivot to connections, GeoIP, VirusTotal)
- Pagination with page size selector

**Tests:**
- Rendering with mock device data
- Sort behavior
- Search filtering
- Empty state
- Error state

---

#### B2: Per-Device Activity Page (`/devices/[ip]`)

**Layout:**
- Header: Device IP + hostname + manufacturer badge + risk score gauge
- Row 1: Bandwidth chart (TimeSeriesChart, last 24h) + protocol donut
- Row 2: Top destinations table (IP, country flag, bytes, connections) + DNS queries list
- Row 3: Recent connections table (time, dest, protocol, bytes, duration)
- Row 4: Alerts for this device (severity badge, signature, time)

**Key interactions:**
- Time range selector affects all panels
- Click destination → navigate to that device's page
- Click alert → open AlertDetailPanel
- "View all connections" link → `/connections?src={ip}`
- "View all alerts" link → `/alerts?ip={ip}`

---

#### B3: Alert-to-Detail Pivot

**What it does:** Clicking any alert anywhere in the UI opens a slide-out panel showing full alert context: the alert details, related Zeek connections for the same source IP and time window, DNS queries made by the attacker, and a link to view the PCAP in Arkime.

**Implementation:**

```
web/src/lib/components/AlertDetailPanel.svelte
├── Props: alert_id (string)
├── Fetches: getAlertDetail(id) + getDeviceDetail(src_ip)
├── Sections:
│   ├── Alert Summary: signature, severity, plain English description, recommendation
│   ├── Network Context: src/dest IP with GeoIP flags, port, protocol
│   ├── Related Traffic: Last 10 connections from src_ip in ±5 min window
│   ├── DNS Activity: Recent DNS queries from src_ip
│   └── Actions: Acknowledge, View in Arkime, View Device Profile, Copy IOCs
```

**Tests:**
- Panel rendering with mock alert
- Related traffic display
- Action buttons (acknowledge, navigate)
- Loading state
- Error state when alert not found

---

#### B4: Right-Click Context Menus

**What it does:** Every IP address, domain, and port value in the dashboard gets a right-click context menu with quick actions.

**Implementation:**

```
web/src/lib/components/ContextMenu.svelte
├── Props: type ("ip" | "domain" | "port"), value (string)
├── IP menu items:
│   ├── Filter traffic by this IP → /connections?src={ip}
│   ├── View device profile → /devices/{ip}
│   ├── GeoIP lookup (inline tooltip with country/ASN)
│   ├── Look up on VirusTotal → external link
│   ├── Look up on Shodan → external link
│   ├── Copy to clipboard
│   └── Exclude from view
├── Domain menu items:
│   ├── Filter DNS queries → /connections?q=dns AND {domain}
│   ├── Look up on VirusTotal → external link
│   ├── WHOIS lookup → external link
│   └── Copy to clipboard
└── Port menu items:
    ├── Filter by port → /connections?q=port=={port}
    ├── Service info tooltip (well-known port → service name)
    └── Copy to clipboard

web/src/lib/components/IPAddress.svelte
├── Wraps IP text with context menu trigger
├── Shows country flag emoji inline (from GeoIP cache)
└── Click → navigate to device, Right-click → context menu
```

**Usage pattern:** Replace raw IP text throughout the app with `<IPAddress ip="10.0.0.1" />` component.

---

#### B5: Enhanced Hero Dashboard

**What it does:** Redesign the home dashboard with bigger hero numbers (Pi-hole style), threshold-based color coding on all metrics, and progressive disclosure.

**Changes to `+page.svelte`:**
- Row 0 (NEW): 6 hero stat cards spanning full width — much larger numbers, subtle trend indicators (up/down arrow with % change vs yesterday)
  - Total Bandwidth (24h)
  - Active Devices
  - Connections Today
  - Alerts Today (color by highest severity)
  - Top Protocol
  - System Health (letter grade A-F)
- Row 1: Bandwidth chart + Protocol distribution (existing, refined)
- Row 2: Top Talkers + Recent Alerts (existing, refined with context menus)
- All numbers use threshold-based coloring consistently
- Device count links to `/devices`
- Alert count links to `/alerts`

---

#### B6: Dashboard Template Variables

**What it does:** A filter bar at the top of every dashboard page with device selector, time range picker, and protocol filter that dynamically filter all panels.

```
web/src/lib/components/DashboardFilters.svelte
├── Device dropdown: Populated from getDevices(), filterable, "All Devices" default
├── Time range picker: Last 1h/6h/24h/7d/30d/Custom
├── Protocol filter: All/TCP/UDP/HTTP/DNS/TLS/SSH
├── Apply button + URL param sync (?device=&from=&to=&proto=)
└── Emits: on:filter-change event consumed by parent pages
```

**Integration:** Every page that shows data (dashboard, connections, alerts) wraps content with `<DashboardFilters>` and passes filter values to API calls.

---

### Group C: Intelligence Layer (Sprint 3)
*Depends on Groups A & B*

| # | Feature | Type | Daemon Files | Web Files | Tests |
|---|---------|------|-------------|-----------|-------|
| C1 | Device Risk Scoring | Should-Have | `daemon/services/risk_scoring.py` | Risk badge component | `test_risk_scoring.py` |
| C2 | New Device Alerts | Should-Have | `daemon/services/device_baseline.py` | Notification integration | `test_device_baseline.py` |
| C3 | Internet Health Monitor | Should-Have | `daemon/services/internet_health.py`, `daemon/api/health.py` (extend) | `/system/internet/+page.svelte` | `test_internet_health.py` |
| C4 | Investigation Bookmarks | Should-Have | `daemon/api/investigations.py` | `/investigations/+page.svelte` | `test_investigations.py` |

**Estimated new tests:** ~60 (daemon) + ~30 (web) = ~90 tests

#### C1: Device Risk Scoring

**Algorithm:** Per-device risk score 0-100 based on weighted signals:

```
Signal                          Weight    Max Points
────────────────────────────────────────────────────
High-severity alerts (24h)       30       30 (1 alert = 15, 2+ = 30)
Medium-severity alerts (24h)     15       15 (1-2 = 8, 3+ = 15)
Connections to flagged IPs       20       20 (per connection to known-bad)
Unusual destination countries    10       10 (connections to high-risk countries)
Anomalous data volume            10       10 (>2 std dev from device's baseline)
Rare protocol usage              10       10 (non-standard ports/protocols)
New/unknown device               5        5  (seen for first time in 24h)
────────────────────────────────────────────────────
Total possible                            100
```

**Risk tiers:**
- 0-20: Low (green badge)
- 21-50: Moderate (yellow badge)
- 51-75: Elevated (orange badge)
- 76-100: Critical (red badge, triggers notification)

**Implementation:**
```
daemon/services/risk_scoring.py
├── calculate_risk_score(ip, from, to) — Returns score + breakdown
├── calculate_all_risk_scores(from, to) — Batch for all devices
├── get_risk_signals(ip) — Returns individual signal values
└── RISK_WEIGHTS: configurable via .env
```

---

#### C2: New Device Alerts

**What it does:** Maintains a baseline of known devices (IP+MAC pairs). When a new device appears on the network, triggers a notification with device details.

```
daemon/services/device_baseline.py
├── DeviceBaseline(data_dir)           — Loads/saves known devices
├── check_for_new_devices()            — Query recent DHCP/ARP logs, compare to baseline
├── register_device(ip, mac)           — Add to known list
├── get_known_devices()                — Return baseline
└── is_known(ip, mac)                  — Boolean check

Integration: Called from daemon's periodic loop (every 60s)
On new device: POST to notification dispatcher with device info
```

---

#### C3: Internet Health Monitor

**What it does:** Periodically tests upstream internet connectivity and charts historical performance.

```
daemon/services/internet_health.py
├── InternetHealthMonitor(interval=60)
├── run_health_check()                 — Returns {latency_ms, dns_resolve_ms,
│                                         packet_loss_pct, download_speed_mbps}
├── ping_targets: ["8.8.8.8", "1.1.1.1", "208.67.222.222"]
├── dns_test_domains: ["google.com", "cloudflare.com"]
└── store_result(result)               — Append to OpenSearch nettap-health-* index

daemon/api/health.py (extend)
├── GET /api/health/internet            — Latest check result
├── GET /api/health/internet/history?from=&to= — Historical series
└── GET /api/health/internet/summary    — 24h avg/min/max/p99
```

**Web page:** `/system/internet/+page.svelte` — Latency chart, DNS chart, uptime percentage, packet loss trend.

---

#### C4: Investigation Bookmarks/Notes

**What it does:** Users can bookmark any alert or event and add investigation notes. A dedicated Investigations page shows all bookmarked items.

```
daemon/api/investigations.py
├── POST /api/investigations            — Create bookmark {alert_id, note, tags}
├── GET /api/investigations             — List all bookmarks
├── PUT /api/investigations/{id}        — Update note/tags
├── DELETE /api/investigations/{id}     — Remove bookmark
└── Storage: /opt/nettap/data/investigations.json

web/src/routes/investigations/+page.svelte
├── List of bookmarked alerts with notes
├── Tag filtering (e.g., "suspicious", "false-positive", "investigating")
├── Timeline view of investigation activity
└── Export bookmarks as JSON
```

---

### Group D: Visualizations & Reports (Sprint 4)
*Can run parallel with Group C*

| # | Feature | Type | Files | Tests |
|---|---------|------|-------|-------|
| D1 | Sankey Traffic Flow Diagram | Should-Have | `web/src/lib/components/charts/SankeyDiagram.svelte` | Component tests |
| D2 | Visual Network Map | Should-Have | `web/src/lib/components/charts/NetworkMap.svelte` | Component tests |
| D3 | Threshold-Based Color Coding | Must-Have | Audit all components | Update existing tests |
| D4 | Progressive Disclosure | Must-Have | Refactor all pages | Update existing tests |
| D5 | Compliance Posture Summary | Should-Have | `web/src/routes/compliance/+page.svelte` | New tests |

**Estimated new tests:** ~40 (web)

#### D1: Sankey Traffic Flow Diagram

**What it does:** Pure SVG Sankey diagram showing traffic flows between internal devices (left) and external destinations (right), with band widths proportional to bytes transferred.

```
web/src/lib/components/charts/SankeyDiagram.svelte
├── Props: flows: [{source, target, value}], width, height
├── Layout: Left column (local IPs) → bands → Right column (dest IPs/domains)
├── Color: By category (Streaming=purple, Social=blue, Work=green, etc.)
├── Interaction: Hover shows tooltip with bytes/connections
└── Data source: GET /api/traffic/top-talkers + top-destinations cross-referenced
```

---

#### D2: Visual Network Map

**What it does:** SVG topology diagram showing Modem → NetTap → Router → Devices with live status indicators and bandwidth on each connection.

```
web/src/lib/components/charts/NetworkMap.svelte
├── Props: devices: Device[], gateway: string
├── Layout: Force-directed or hierarchical
│   ├── Center: NetTap appliance (always visible)
│   ├── Left: WAN (modem/ISP)
│   ├── Right: LAN devices (clustered by group)
│   └── Lines: Thickness = bandwidth, Color = status
├── Device icons: SVG icons by device type
├── Interaction: Click device → navigate to /devices/{ip}
└── Auto-layout: Devices arranged by traffic volume
```

---

#### D3: Threshold-Based Color Coding (Systematic Audit)

**What it does:** Audit every numeric value in the UI and apply consistent threshold-based coloring.

**Rules:**
```
Bandwidth:     <1 GB/day = green, 1-5 GB = blue, 5-20 GB = yellow, >20 GB = orange
Alerts:        0 = green, 1-5 = yellow, 6-20 = orange, >20 = red
Risk Score:    0-20 = green, 21-50 = yellow, 51-75 = orange, 76-100 = red
Disk Usage:    <60% = green, 60-79% = yellow, 80-89% = orange, >90% = red
Temperature:   <50°C = green, 50-65°C = yellow, 65-75°C = orange, >75°C = red
Latency:       <20ms = green, 20-50ms = yellow, 50-100ms = orange, >100ms = red
Connections:   Contextual (compared to device's rolling average)
```

**Implementation:** Create `web/src/lib/utils/thresholds.ts` with helper functions that return CSS class names based on values.

---

### Group E: Advanced Features (Sprint 5)
*Depends on Groups A-D*

| # | Feature | Type | Files | Tests |
|---|---------|------|-------|-------|
| E1 | Natural Language Search | Should-Have | `daemon/services/nl_search.py`, search component | Tests |
| E2 | Community Detection Packs | Should-Have | `daemon/services/detection_packs.py`, settings UI | Tests |
| E3 | Scheduled Reports | Should-Have | `daemon/services/report_generator.py`, settings UI | Tests |

**Estimated new tests:** ~40 (daemon) + ~20 (web) = ~60 tests

#### E1: Natural Language Search

**What it does:** Search bar accepting plain English queries like "DNS queries to Russia this week" or "which device used the most bandwidth yesterday." Translates to OpenSearch queries.

```
daemon/services/nl_search.py
├── NLSearchParser()
├── parse(query_text) → OpenSearchQuery
├── Pattern matching for common queries:
│   ├── "show {protocol} traffic" → filter by service
│   ├── "from {ip}" → filter by id.orig_h
│   ├── "to {domain}" → filter by resp_host
│   ├── "{time_ref}" → parse time range (today, yesterday, this week, last 24h)
│   ├── "top {N} {entity}" → top-N aggregation
│   └── "which device" → terms agg on id.orig_h
└── Fallback: Pass as raw query_string to OpenSearch
```

---

#### E2: Community Detection Packs

**What it does:** Subscribe to community-maintained configuration bundles (Suricata rules, alert descriptions, traffic categories) via URL.

```
daemon/services/detection_packs.py
├── PackManager(data_dir)
├── install_pack(url)                  — Download and validate JSON pack
├── list_installed_packs()             — List installed packs
├── remove_pack(pack_id)               — Uninstall pack
├── update_all_packs()                 — Re-download all installed packs
└── Pack format:
    {
      "name": "Smart Home Monitoring",
      "version": "1.0.0",
      "author": "community",
      "suricata_rules": [...],
      "traffic_categories": {...},
      "alert_descriptions": {...}
    }
```

---

#### E3: Scheduled PDF/Email Reports

**What it does:** Generate weekly/monthly summary reports with bandwidth trends, top talkers, alert summary, new devices, risk score changes.

```
daemon/services/report_generator.py
├── ReportGenerator(opensearch_client)
├── generate_report(period="weekly")   — Returns HTML report
├── schedule_reports()                 — Cron-like scheduling
├── send_report(report, recipients)    — Email via SMTP
└── Report sections:
    ├── Executive Summary (5 hero numbers)
    ├── Bandwidth Trends (chart as inline SVG)
    ├── Top Talkers (table)
    ├── Alert Summary (count by severity)
    ├── New Devices (list with MAC/manufacturer)
    └── Risk Score Changes (devices that increased)
```

---

## Sprint Schedule

| Sprint | Duration | Groups | Features | New Tests |
|--------|----------|--------|----------|-----------|
| Sprint 1 | 1 PR | Group A: Data Foundation | A1-A4 | ~120 |
| Sprint 2 | 1 PR | Group B: Core UI | B1-B6 | ~60 |
| Sprint 3 | 1 PR | Group C: Intelligence | C1-C4 | ~90 |
| Sprint 4 | 1 PR | Group D: Visualizations | D1-D5 | ~40 |
| Sprint 5 | 1 PR | Group E: Advanced | E1-E3 | ~60 |
| **Total** | **5 PRs** | **A-E** | **20 features** | **~370 new tests** |

Combined with existing ~359 tests = **~729 total tests at completion**.

---

## Test Strategy

Every feature MUST have:

1. **Daemon unit tests** (pytest): Mock OpenSearch responses, test query building, test response formatting, test error handling
2. **Web API client tests** (Vitest): Mock fetch, test parameter building, test response parsing, test error states
3. **Web component tests** (Vitest + Testing Library): Render with mock data, test interactions, test empty/loading/error states

**Test naming convention:**
- Daemon: `daemon/tests/test_{module_name}.py`
- Web API: `web/src/lib/api/{module}.test.ts`
- Web components: `web/src/lib/components/{Component}.test.ts`
- Web pages: `web/src/routes/{path}/+page.test.ts` (if complex logic)

**Pass criteria:** ALL tests must pass before any PR is created. This includes existing tests (140 daemon + 80 Vitest) plus all new tests.

---

## Dependency Graph

```
Group A: Data Foundation
  ├── A1: Device Inventory API
  ├── A2: Traffic Categorization
  ├── A3: Alert Enrichment
  └── A4: GeoIP Service
        │
        ├── Group B: Core UI ──────────────────────┐
        │   ├── B1: Device Inventory Page (← A1)   │
        │   ├── B2: Per-Device Page (← A1, A4)     │  Group D: Visualizations
        │   ├── B3: Alert Detail Panel (← A3, A4)  │  ├── D1: Sankey Diagram
        │   ├── B4: Context Menus (← A4)           │  ├── D2: Network Map
        │   ├── B5: Hero Dashboard (← A1, A2)      │  ├── D3: Color Coding
        │   └── B6: Template Variables              │  ├── D4: Progressive Disclosure
        │                                           │  └── D5: Compliance Summary
        ├── Group C: Intelligence ──────────────────┘
        │   ├── C1: Risk Scoring (← A1, A3, A4)
        │   ├── C2: New Device Alerts (← A1)
        │   ├── C3: Internet Health Monitor
        │   └── C4: Investigation Bookmarks (← B3)
        │
        └── Group E: Advanced
            ├── E1: NL Search
            ├── E2: Detection Packs (← A3)
            └── E3: Scheduled Reports (← C1)
```

---

## Files Summary

### New Files (estimated)

**Daemon (Python):**
- `daemon/api/devices.py` — Device inventory endpoints
- `daemon/api/geoip.py` — GeoIP lookup endpoints
- `daemon/api/investigations.py` — Bookmark/notes endpoints
- `daemon/services/device_fingerprint.py` — MAC, hostname, OUI, OS detection
- `daemon/services/traffic_classifier.py` — Protocol → category mapping
- `daemon/services/alert_enrichment.py` — Suricata SID → plain English
- `daemon/services/geoip_service.py` — MaxMind GeoLite2 wrapper
- `daemon/services/risk_scoring.py` — Per-device risk calculation
- `daemon/services/device_baseline.py` — Known device tracking
- `daemon/services/internet_health.py` — Upstream connectivity probing
- `daemon/services/nl_search.py` — Natural language → OpenSearch query
- `daemon/services/detection_packs.py` — Community pack management
- `daemon/services/report_generator.py` — PDF/email report builder
- `daemon/data/oui.txt` — IEEE OUI database (~300KB)
- `daemon/data/suricata_descriptions.json` — Curated alert descriptions
- `daemon/tests/test_devices_api.py`
- `daemon/tests/test_device_fingerprint.py`
- `daemon/tests/test_traffic_classifier.py`
- `daemon/tests/test_alert_enrichment.py`
- `daemon/tests/test_geoip_service.py`
- `daemon/tests/test_risk_scoring.py`
- `daemon/tests/test_device_baseline.py`
- `daemon/tests/test_internet_health.py`
- `daemon/tests/test_nl_search.py`
- `daemon/tests/test_detection_packs.py`
- `daemon/tests/test_report_generator.py`
- `daemon/tests/test_investigations.py`

**Web (SvelteKit/TypeScript):**
- `web/src/lib/api/devices.ts` + `devices.test.ts`
- `web/src/lib/api/geoip.ts` + `geoip.test.ts`
- `web/src/lib/api/investigations.ts` + `investigations.test.ts`
- `web/src/lib/api/health.ts` + `health.test.ts`
- `web/src/lib/utils/thresholds.ts` + `thresholds.test.ts`
- `web/src/lib/components/AlertDetailPanel.svelte` + `.test.ts`
- `web/src/lib/components/ContextMenu.svelte` + `.test.ts`
- `web/src/lib/components/IPAddress.svelte` + `.test.ts`
- `web/src/lib/components/DashboardFilters.svelte` + `.test.ts`
- `web/src/lib/components/charts/SankeyDiagram.svelte` + `.test.ts`
- `web/src/lib/components/charts/NetworkMap.svelte` + `.test.ts`
- `web/src/routes/devices/+page.svelte`
- `web/src/routes/devices/[ip]/+page.svelte`
- `web/src/routes/investigations/+page.svelte`
- `web/src/routes/compliance/+page.svelte`
- `web/src/routes/system/internet/+page.svelte`
- `web/src/routes/settings/notifications/+page.svelte` (extend)
- 10+ new API proxy routes under `web/src/routes/api/`

**Estimated total: ~60 new files, ~15,000-20,000 new lines of code**
