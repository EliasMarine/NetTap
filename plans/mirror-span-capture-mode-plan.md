# NetTap Mirror/SPAN Capture Mode — Implementation Plan

**Date:** 2026-03-08
**Status:** In Progress
**Branch:** `phase-5/mirror-span-mode`
**Last Updated:** 2026-03-08

---

## 1. Overview

NetTap currently operates exclusively in **inline bridge mode** — sitting transparently between an ISP modem and router. This plan adds a second capture mode: **Mirror/SPAN mode**, where NetTap passively receives a copy of LAN traffic from a managed switch's port mirror.

### New Topology

```
ISP ──── UDM Pro ──── (10G uplink) ──── Unifi Pro XG 8 PoE ──── LAN Devices
                                              │
                                         (port mirror)
                                              │
                                         NetTap Device
```

The switch mirrors the uplink port (switch ↔ router) to a dedicated port connected to NetTap. NetTap receives a copy of all LAN-to-WAN traffic with real local device IPs visible (post-NAT).

### Key Differences from Bridge Mode

| Aspect | Bridge Mode | Mirror/SPAN Mode |
|--------|-------------|-------------------|
| Position | Inline between modem & router | Passive off switch mirror port |
| Risk | Can break internet if misconfigured | Zero risk — just a copy of traffic |
| NICs needed | 2 (WAN+LAN for bridge) + 1 mgmt | 1 (mirror feed) + 1 mgmt |
| Traffic seen | WAN-side (pre-NAT) | LAN-side (post-NAT, real device IPs) |
| Device visibility | Sees router's WAN IP for all devices | Sees each device's local IP + MAC |
| Capture interface | `br0` (bridge) | Single NIC in promisc, no IP |
| Bridge setup | Required | Not needed |

### Design Principles

- **Mode selection only affects the network layer** (how packets arrive). Everything from capture onward is the same pipeline (Zeek → Suricata → OpenSearch → Dashboard).
- **Bridge mode is fully preserved** — user selects mode during setup wizard.
- **Capture must be bulletproof** — zero tolerance for silent packet drops or misconfigured NICs.
- **Device identification is first-class** — mirror mode's main advantage is per-device visibility.

---

## 2. Capture Mode Abstraction

### 2.1 Configuration

Capture mode stored in `/etc/nettap/capture-mode.conf`:

```ini
[capture]
mode=mirror          # "bridge" or "mirror"
interface=enp2s0     # mirror NIC (mirror mode) or ignored (bridge mode)
management=enp3s0    # management NIC for web UI access

[bridge]
wan_interface=enp2s0
lan_interface=enp3s0
```

Written by setup wizard, read by daemon and docker-compose via `.env` file.

### 2.2 Daemon Abstraction

New `CaptureMode` enum and `CaptureManager` base class:

```
CaptureManager (abstract base)
├── setup() → configure NIC(s)
├── teardown() → deconfigure
├── get_health() → health status dict
├── get_capture_interface() → str (interface name for Zeek/Suricata)
├── get_stats() → drop counters, throughput, NIC speed
│
├── BridgeCaptureAdapter (new, wraps existing BridgeManager — do NOT modify BridgeManager)
│   └── Delegates to existing BridgeManager for br0 creation, NIC management, health checks
│
└── MirrorManager (new)
    └── Configures single NIC: no IP, promisc, offloads disabled, ring buffers maxed
```

Daemon reads mode from config at startup, instantiates the correct manager. All downstream code calls `get_capture_interface()` — never hardcodes `br0`.

### 2.3 Docker Compose

Single `docker-compose.yml` — no per-mode compose files. Capture interface injected via `PCAP_IFACE` environment variable in `.env`:

```env
# Written by setup wizard
PCAP_IFACE=enp2s0       # mirror mode: raw NIC; bridge mode: br0
CAPTURE_MODE=mirror      # "bridge" or "mirror"
```

All capture containers (`zeek-live`, `suricata-live`, `arkime-live`, `pcap-capture`) read `PCAP_IFACE`. They already use `network_mode: host` — works for both modes.

---

## 3. Mirror/SPAN Capture Hardening

### 3.1 NIC Configuration (no IP, max performance)

When MirrorManager runs `setup()`:

1. **Strip any IP** — `ip addr flush dev <iface>` + disable DHCP client for this interface
2. **Enable promiscuous mode** — `ip link set <iface> promisc on`
3. **Disable all offloads** — TSO, GSO, GRO, LRO, rx-vlan-offload (offloads corrupt/coalesce packets before capture tools see them):
   ```bash
   ethtool -K <iface> tso off gso off gro off lro off rx-vlan-offload off
   ```
4. **Increase ring buffer to max** — `ethtool -G <iface> rx 4096`
5. **Enable RSS** (Receive Side Scaling) across all CPU cores if supported
6. **Set IRQ affinity** to spread NIC interrupts across cores

### 3.2 Capture Stack Tuning

- **AF_PACKET with TPACKET_V3** ring buffers (kernel zero-copy path) for Zeek and Suricata
- **Suricata:** `cluster_flow` to distribute flows across worker threads, ring size 200k+ (already configured in `nettap.yaml`)
- **Zeek:** `af_packet` plugin with fanout for multi-core
- **Arkime:** direct `af_packet` capture with `tpacketv3`
- **pcap-capture** (netsniff-ng) as safety net — writes raw PCAPs even if Zeek/Suricata fall behind

### 3.3 Drop Detection & Alerting

- Monitor `/sys/class/net/<iface>/statistics/rx_dropped` and `rx_missed_errors` continuously (every 10s)
- Poll Zeek `capture_loss.log` and Suricata `stats.log` for kernel/tool-level drops
- Expose drop counters in dashboard health panel
- Alert if drop rate exceeds 0.1% sustained over 60s

### 3.4 Resilience

- **Systemd unit** ensures promisc mode re-enabled on boot and after link flaps
- **Watchdog:** Docker `restart: unless-stopped` + daemon health check auto-restarts crashed capture containers
- **Link flap recovery:** if mirror NIC link drops (cable unplugged), daemon detects and alerts but doesn't panic — resumes capture automatically when link returns

### 3.5 Speed Mismatch Handling (10G switch → 2.5G NIC)

- Unifi XG 8 auto-negotiates to 2.5G on the mirror port (Intel i226-V limit)
- If LAN aggregate traffic exceeds 2.5Gbps, the switch drops excess mirrored packets (hardware limitation, not fixable in software)
- Dashboard displays NIC negotiated speed and warns if mirror source bandwidth likely exceeds it

### 3.6 Container Startup Gating

Current: containers start immediately. New:

1. Daemon starts → reads capture mode config
2. Daemon configures mirror NIC (strip IP, promisc, offloads, ring buffers)
3. Daemon reports healthy via Docker healthcheck
4. Capture containers start (via `depends_on: condition: service_healthy`)
5. Prevents Zeek/Suricata from starting before NIC is ready

---

## 4. Device Identification & Enrichment

### 4.1 Tier 1: Universal Passive Identification (no vendor integration)

All of these work passively from mirrored traffic — no active probing, no network access needed:

| Source | What it provides | How |
|--------|-----------------|-----|
| ARP/NDP snooping | IP ↔ MAC mapping | Observe ARP requests/replies in mirrored traffic |
| DHCP snooping | Hostnames (option 12), vendor class (option 60), IP assignments | Watch DHCP Discover/Request/ACK |
| mDNS/Bonjour | Device friendly names | Parse `.local` announcements (Apple devices, Chromecasts, printers) |
| SSDP/UPnP | Device type, model, manufacturer | Parse discovery responses |
| DNS reverse mapping | Per-device browsing profiles | Correlate DNS queries with source IPs |
| MAC OUI lookup | Manufacturer (Apple, Intel, Raspberry Pi, etc.) | Offline database mapping MAC prefix → vendor |
| HTTP User-Agent | OS/browser/device type | Parse plaintext HTTP headers (useful for IoT) |
| TLS fingerprinting (JA3/JA4) | Client software/OS identification | Analyze TLS ClientHello patterns, even through encryption |

### 4.2 Tier 2: UniFi Integration (optional)

For users with UniFi hardware, query the UniFi Controller API (runs on UDM Pro):

- Device aliases (user-assigned names like "Dad's MacBook")
- Device type classifications
- Connection info (WiFi vs wired, AP name, VLAN)
- Historical connection data

Configuration:
- Setup wizard: user provides controller URL + credentials
- Polled every 5 minutes, cached locally
- **Graceful degradation** — if controller unreachable, falls back to Tier 1 only

### 4.3 Device Registry

- Central `device_registry` index in OpenSearch keyed by MAC address
- Merges all enrichment sources with priority: UniFi alias > DHCP hostname > mDNS name > OUI manufacturer
- Tracks: first-seen, last-seen, all known IPs, all known names, device category
- New `DeviceRegistry` service class in daemon — runs as background task in event loop

### 4.4 New Device Detection

- When a previously unseen MAC appears, surface a notification in the dashboard
- "New device detected: Apple iPhone — 192.168.1.47"
- Configurable: alert on new devices, or silent discovery only

---

## 5. Storage Resilience

### 5.1 Disk Monitoring

- Poll disk usage every 30s (existing)
- **Predictive exhaustion** — calculate fill rate over last 24h, alert when projected to hit 80% within 48h
- **Emergency cascade deletion:**
  - 90% disk: immediately prune oldest data regardless of retention policy
  - 95% disk: stop PCAP capture to prevent filling disk entirely
  - Resume when back below 85%
- **Per-tier accounting** — track disk consumption per tier (hot/warm/cold), show breakdown in dashboard

### 5.2 OpenSearch ILM Hardening

- **Verify ILM policy on every daemon startup** — recreate if deleted or corrupted
- **Monitor ILM execution** — detect failed rollover/deletion actions, alert and retry
- **Shard size limits** — 50GB max per shard to prevent bloat and degraded search performance

### 5.3 PCAP Storage (Cold Tier)

- Rotation by size (1GB per file) and time (5 min max), whichever first
- Date-based subdirectories: `/data/pcap/2026/03/08/`
- Oldest files pruned first (FIFO)
- **File integrity:** write xxh3 checksum alongside each PCAP, verify on read
- Mirror mode generates more unique flows — wizard should show estimated daily PCAP volume based on observed traffic rate

### 5.4 SSD Write Endurance

- Coalesce writes: Zeek logs flush every 30s (already configured)
- Monitor SMART wear leveling — alert at 80%, critical at 90%
- Dashboard shows SSD health + estimated remaining lifespan based on current write rate

### 5.5 Recovery

- If OpenSearch crashes: daemon waits for green/yellow cluster health before resuming writes
- If index corrupted: daemon can re-index from raw Zeek JSON logs on disk (logs are source of truth, OpenSearch is queryable cache)
- Config and retention settings persisted to disk file, not only in OpenSearch — survives full data loss

---

## 6. SMART Health Monitoring Hardening

### 6.1 Known Problem

The current SMART panel detects the drive model but shows `--` for Temperature, Wear, and Power-On Hours. Root causes:

1. `/dev` mounted read-only in Docker — NVMe admin commands require write access to `/dev/nvme0` (controller device). Read-only mount silently blocks SMART queries.
2. `SYS_RAWIO` capability missing — NVMe SMART queries use admin passthrough commands that need this capability. Without it, smartctl gets basic info (model/serial from sysfs) but can't read the health log.
3. No error surfacing — when metrics come back null, the UI shows `--` with no indication of why.

### 6.2 Root Cause Fixes

- **Verify `/dev` mount is read-write** in docker-compose (not `:ro`)
- **Verify `SYS_RAWIO` capability** — daemon checks `/proc/self/status` CapEff bitmask at startup, warns if missing
- **Startup self-test:** on daemon boot, run `smartctl -j -a <device>`, log full result at DEBUG, log WARNING with specific guidance if any key metric is null
- **Explicit error reporting:** if smartctl returns data but key fields are null, API response includes a `diagnostics` field explaining what's likely wrong

### 6.3 Parsing Resilience

- Samsung 970 EVO uses slightly different NVMe health log field names across firmware versions — add fallback key lookups
- Check both `temperature` inside `nvme_smart_health_information_log` AND top-level `temperature.current`
- Check `temperature_sensors[0]` as additional fallback
- Handle `percentage_used` as 0 vs null (0 is valid for new drives, null means read failure)

### 6.4 UI Improvements

- Instead of `--`, show "Unavailable" with an info icon explaining why and how to fix
- Add "Run SMART Test" button for on-demand check with raw diagnostics
- Expose self-test results via `GET /api/smart/diagnostics`

### 6.5 Metrics History

- Index SMART checks to OpenSearch (one doc per hourly check)
- Dashboard shows temperature and wear trending over time
- Enables "SSD lifespan remaining" estimation based on write rate trend

---

## 7. Setup Wizard Changes

### New Flow (6 steps)

| Step | Name | Description |
|------|------|-------------|
| 1 | **Welcome** | Requirements check — adapted per mode (mirror needs 1+ NIC, bridge needs 2+) |
| 2 | **Capture Mode** | NEW — User selects Mirror/SPAN or Inline Bridge |
| 3 | **Interface Config** | Adapts based on mode (see below) |
| 4 | **Storage** | Retention tiers, disk config (unchanged but hardened per Section 5) |
| 5 | **Device Enrichment** | NEW — Optional UniFi controller integration (mirror mode only) |
| 6 | **Account** | Create admin user (unchanged) |

### Step 2: Capture Mode Selection

Two options with descriptions:

- **Mirror/SPAN** (recommended) — "My managed switch sends a copy of network traffic to NetTap. Zero risk to your network. Best for per-device visibility."
- **Inline Bridge** — "NetTap sits between your modem and router. Sees all WAN traffic. Requires two dedicated NICs."

### Step 3: Interface Configuration (mode-dependent)

**Mirror mode:**
1. Select mirror capture NIC (single NIC, will have no IP assigned)
2. Select or confirm management interface (second NIC or WiFi) for web UI access
3. Validate: mirror NIC has link, management interface has IP

**Bridge mode:**
1. Select WAN and LAN NICs (existing flow)
2. Preview and create bridge (existing flow)

### Step 5: Device Enrichment (mirror mode only)

- Toggle: "Do you use UniFi network equipment?"
- If yes: controller URL, username, password, test connection button
- If no: skip (Tier 1 passive identification is automatic)
- Skipped entirely in bridge mode

---

## 8. Daemon & API Changes

### 8.1 New/Modified Services

| Service | Status | Description |
|---------|--------|-------------|
| `CaptureManager` | New (abstract) | Base class for capture mode operations |
| `BridgeCaptureAdapter` | New | Thin wrapper around existing BridgeManager, implements CaptureManager interface |
| `MirrorManager` | New | Mirror NIC setup, health checks, drop monitoring |
| `DeviceRegistry` | New | MAC-keyed device table, enrichment merging, OpenSearch indexing |
| `UnifiIntegration` | New | Optional UniFi Controller API polling |
| `SmartMonitor` | Hardened | Startup self-test, fallback parsing, diagnostics endpoint |
| `StorageManager` | Hardened | Predictive exhaustion, emergency cascade, ILM verification |

### 8.2 API Endpoints

**New capture-mode-agnostic endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/capture/mode` | Current capture mode |
| GET | `/api/capture/health` | Mode-agnostic health status |
| GET | `/api/capture/stats` | Drop counters, throughput, NIC speed |
| GET | `/api/capture/interface` | Active capture interface name |

**New device endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/devices` | List all discovered devices |
| GET | `/api/devices/:mac` | Single device detail |
| GET | `/api/devices/:mac/traffic` | Traffic summary for one device |

**New integration endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/integrations/unifi/configure` | Set controller credentials |
| GET | `/api/integrations/unifi/status` | Connection status |
| POST | `/api/integrations/unifi/test` | Test connectivity |

**New SMART diagnostics:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/smart/diagnostics` | Raw smartctl output + failure analysis |
| POST | `/api/smart/test` | Trigger on-demand SMART check |

**Existing bridge endpoints** (`/api/bridge/*`) remain functional in bridge mode.

---

## 9. Dashboard & Web UI Changes

### 9.1 Mirror Mode: Device-Centric Views

**Home page — Device grid/list:**
- All discovered devices with: friendly name, IP, MAC, manufacturer, traffic volume (in/out), active connections, last seen
- Auto-categorized by type (computers, phones, IoT, infrastructure) via OUI + fingerprinting
- User can override categories and names

**Device detail page:**
- Click any device → full traffic breakdown
- Top destinations, protocols, bandwidth over time
- DNS queries made by this device
- Active connections
- Suricata alerts/detections for this device

**New device alerts:**
- Notification when previously unseen MAC appears
- "New device detected: Apple iPhone — 192.168.1.47"

### 9.2 Bridge Mode

Existing views unchanged — traffic overview, protocol breakdown, alerts.

### 9.3 Shared Across Both Modes

- **Capture health panel:** NIC status, drop counters, throughput, negotiated speed
- **Storage panel:** disk usage per tier, retention status, SSD health with trending
- **SMART panel:** fixed to show actual metrics (not `--`), with diagnostics and trending
- **Alerts & detections:** Suricata alerts, anomaly detection
- **Settings:** capture mode (read-only after setup), storage config, integrations

### 9.4 Mode Indicator

Persistent badge in UI header: **"Mirror/SPAN"** or **"Inline Bridge"** — prevents confusion about what the user is looking at.

---

## 10. New Feature Pages & Tools

These are additional features that leverage mirror mode's per-device visibility and complete the network admin experience. Organized by priority.

### 10.1 Real-Time Connection Monitor (`/live`) — HIGH PRIORITY

**The "killer feature" for mirror mode.** A live-updating view of every active connection across the entire network — like running `netstat` for every device simultaneously.

**Page: `/live`**

**Layout:**
- Full-width auto-scrolling table of active connections
- Columns: Time | Device (name) | Direction (→/←) | Destination (IP + hostname + flag) | Protocol | Port | Bytes | Duration | Country
- Pause/Play button to freeze the feed
- Filter bar: by device, protocol, country, port range
- Connection rate counter: "247 connections/sec"
- Color coding: green (normal), yellow (unusual port), orange (flagged destination), red (alert match)

**Implementation:**

```
daemon/services/live_connections.py
├── LiveConnectionTracker
├── get_active_connections(filters?) → list of current connections
├── subscribe() → WebSocket stream of new connections
├── get_connection_rate() → connections/sec over last 60s
└── Integration: Reads from Zeek conn.log in near-real-time (tail -f equivalent on log dir)

daemon/api/live.py
├── GET /api/live/connections?device=&proto=&limit=100  — Snapshot of active connections
├── GET /api/live/rate                                   — Current connection rate
└── WS  /api/live/stream?device=&proto=                  — WebSocket real-time feed

web/src/routes/live/+page.svelte
├── WebSocket connection to daemon for live updates
├── Virtual scrolling table (DOM performance for 1000+ rows)
├── Pause/Play toggle
├── Filter bar with device dropdown, protocol selector, country filter
├── Connection rate display with sparkline
└── Click row → opens connection detail (dest device, related DNS, alert match)
```

**Key technical considerations:**
- WebSocket for real-time push (HTTP polling too slow for live feed)
- Virtual scrolling required — DOM can't handle 10k+ rows
- Buffer last 10,000 connections in memory, rotate oldest
- Rate limiting: aggregate if >500 connections/sec to prevent UI overload

**Tests:**
- Daemon: `test_live_connections.py` — tracker logic, filtering, rate calculation, WebSocket message format
- Web: `live.test.ts` — rendering, pause/play, filtering, WebSocket mock, virtual scroll

---

### 10.2 Bandwidth & ISP Data Cap Tracker (`/bandwidth`) — HIGH PRIORITY

**Answers "who's using all my internet?" and "am I going to exceed my ISP data cap?"**

**Page: `/bandwidth`**

**Layout:**
- **Hero card:** Monthly data usage vs configurable cap (e.g., "847 GB / 1,200 GB — 71%") with progress bar
- **Projected usage:** "At current rate, you'll use 1,150 GB this month" with warning if projected > cap
- **Per-device breakdown:** Stacked bar chart showing each device's contribution to total bandwidth
- **Daily usage chart:** Bar chart of daily totals for the current month
- **Top consumers table:** Device | Today | This Week | This Month | % of Total
- **Time-of-day heatmap:** When is bandwidth heaviest? (hour × day-of-week grid)

**Implementation:**

```
daemon/services/bandwidth_tracker.py
├── BandwidthTracker
├── get_monthly_usage(year, month)             — Total bytes in/out for month
├── get_daily_usage(from, to)                  — Daily totals array
├── get_per_device_usage(from, to)             — Per-device bytes in/out
├── get_projected_monthly(year, month)         — Linear projection based on rate
├── get_hourly_heatmap(from, to)              — 24×7 hour-of-day × day-of-week matrix
└── Integration: Aggregates from zeek-conn-* index (sum of orig_bytes + resp_bytes)

daemon/api/bandwidth.py
├── GET /api/bandwidth/monthly?year=&month=    — Monthly usage + projection
├── GET /api/bandwidth/daily?from=&to=         — Daily totals
├── GET /api/bandwidth/devices?from=&to=       — Per-device breakdown
├── GET /api/bandwidth/heatmap?from=&to=       — Hour×day matrix
└── GET /api/bandwidth/cap                     — Configured cap + current usage %

daemon/api/settings.py (extend)
└── PUT /api/settings/bandwidth-cap            — Set monthly cap (bytes)

web/src/routes/bandwidth/+page.svelte
├── Monthly usage hero card with progress bar + projection
├── Per-device stacked bar chart (D3 or pure SVG)
├── Daily usage bar chart
├── Top consumers table (sortable)
├── Heatmap component (SVG grid)
└── Settings modal for cap configuration
```

**Tests:**
- Daemon: `test_bandwidth_tracker.py` — monthly aggregation, projection math, per-device breakdown, heatmap generation
- Web: `bandwidth.test.ts` — rendering, cap progress bar, projection warning, device table sorting

---

### 10.3 DNS Analytics Page (`/dns`) — HIGH PRIORITY

**Deep visibility into every DNS query on the network.** The data already exists in Zeek DNS logs — this just needs a dedicated page.

**Page: `/dns`**

**Layout:**
- **Hero cards:** Total Queries (24h) | Unique Domains | NXDOMAIN Errors | Avg Resolution Time
- **Top queried domains table:** Domain | Query Count | Devices Querying | Category | First Seen
- **Per-device DNS breakdown:** Select a device → see all domains it queried
- **NXDOMAIN table:** Failed DNS lookups (potential malware indicators — DGA domains, C2 beacons)
- **Query type distribution:** Pie chart of A/AAAA/CNAME/MX/TXT/SRV
- **DNS timeline:** Queries per minute over time, filterable by device
- **Suspicious DNS panel:** Unusually long domain names (DGA), high query frequency to single domain (tunneling), TXT record abuse

**Implementation:**

```
daemon/services/dns_analytics.py
├── DNSAnalytics
├── get_top_domains(from, to, limit=50)        — Most queried domains
├── get_device_dns(device_ip, from, to)        — All DNS queries for one device
├── get_nxdomain_errors(from, to)              — Failed lookups (potential DGA)
├── get_query_type_distribution(from, to)      — A/AAAA/CNAME/MX/TXT/SRV counts
├── get_dns_timeline(from, to, interval="1m")  — Query volume over time
├── get_suspicious_dns(from, to)               — Long names, high frequency, TXT abuse
└── detect_dns_tunneling(from, to)             — Entropy analysis on query names

daemon/api/dns.py
├── GET /api/dns/top-domains?from=&to=&limit=  — Top queried domains
├── GET /api/dns/device/{ip}?from=&to=         — Per-device DNS queries
├── GET /api/dns/nxdomain?from=&to=            — NXDOMAIN errors
├── GET /api/dns/types?from=&to=               — Query type distribution
├── GET /api/dns/timeline?from=&to=            — Query volume over time
├── GET /api/dns/suspicious?from=&to=          — Suspicious patterns
└── GET /api/dns/stats?from=&to=               — Hero card stats

web/src/routes/dns/+page.svelte
├── Hero stat cards
├── Top domains table (sortable, clickable → shows querying devices)
├── Per-device DNS selector
├── NXDOMAIN error table with DGA probability score
├── Query type donut chart
├── DNS timeline chart
└── Suspicious DNS panel with explanations
```

**Tests:**
- Daemon: `test_dns_analytics.py` — domain aggregation, NXDOMAIN detection, DGA entropy scoring, tunneling detection
- Web: `dns.test.ts` — rendering, filtering, table interactions, chart data

---

### 10.4 IoT Behavior Monitor (`/iot`) — HIGH PRIORITY

**The security value proposition.** Smart home devices have predictable traffic patterns. This feature learns what's "normal" for each IoT device and alerts when behavior deviates.

**Page: `/iot`**

**Layout:**
- **IoT device grid:** All devices classified as IoT (cameras, thermostats, smart TVs, speakers, etc.) with status badges
- **Per-device behavioral baseline:** Normal destinations, normal ports, normal time-of-day activity, normal data volume
- **Anomaly feed:** "Ring Doorbell connected to 185.234.xx.xx (Russia) at 3:14 AM — never seen before"
- **Communication map:** Which external services does each IoT device talk to? (SVG diagram)
- **Data exfiltration warning:** Flag IoT devices uploading more data than expected

**Implementation:**

```
daemon/services/iot_monitor.py
├── IoTMonitor
├── classify_as_iot(device)                    — OUI + traffic pattern → is IoT?
├── build_baseline(device_mac, days=14)        — Learn normal destinations, ports, volumes, schedules
├── check_anomalies(device_mac)                — Compare current behavior to baseline
├── get_iot_devices()                          — List all IoT-classified devices
├── get_device_baseline(mac)                   — Return learned baseline
├── get_anomalies(from, to)                    — All detected anomalies
└── Anomaly types:
    ├── NEW_DESTINATION — Device connecting to never-before-seen IP/domain
    ├── NEW_COUNTRY — Device connecting to a country it's never contacted
    ├── NEW_PORT — Device using a port it's never used before
    ├── UNUSUAL_TIME — Activity outside normal active hours
    ├── VOLUME_SPIKE — Data transfer >3x standard deviation from baseline
    └── PROTOCOL_CHANGE — Device switched from HTTPS to HTTP or used raw TCP

daemon/api/iot.py
├── GET /api/iot/devices                       — List IoT devices with status
├── GET /api/iot/devices/{mac}/baseline        — Learned behavioral baseline
├── GET /api/iot/devices/{mac}/anomalies       — Anomalies for specific device
├── GET /api/iot/anomalies?from=&to=           — All anomalies network-wide
├── POST /api/iot/devices/{mac}/acknowledge    — Mark anomaly as expected
└── POST /api/iot/devices/{mac}/reclassify     — Override IoT classification

web/src/routes/iot/+page.svelte
├── IoT device grid with health status badges
├── Anomaly feed (chronological, filterable by device/type)
├── Per-device baseline view (what's "normal" for this device)
├── Communication map (device → external services)
└── Acknowledge/dismiss actions for anomalies
```

**Baseline learning:**
- First 14 days: learning mode (no alerts, building baseline)
- After 14 days: anomaly detection active
- Baseline continuously updated with rolling 30-day window
- User can manually mark anomalies as "expected" to tune the baseline

**Tests:**
- Daemon: `test_iot_monitor.py` — IoT classification, baseline building, anomaly detection for each type, acknowledge flow
- Web: `iot.test.ts` — device grid, anomaly feed, baseline display, acknowledge interactions

---

### 10.5 Notification Hub (`/settings/notifications`) — HIGH PRIORITY

**Without multi-channel notifications, alerts only matter when you're looking at the dashboard.** This centralizes all notification routing.

**Page: `/settings/notifications`**

**Layout:**
- **Channels section:** Configure notification destinations
  - Email (SMTP server, from address, recipients)
  - Discord (webhook URL)
  - Slack (webhook URL)
  - Telegram (bot token + chat ID)
  - Pushover (user key + app token)
  - Generic webhook (URL + headers + body template)
- **Routing rules:** Which alerts go where
  - "Send critical Suricata alerts to Slack + Email"
  - "Send new device detections to Telegram"
  - "Send weekly bandwidth summary to Email"
  - "Send IoT anomalies to Discord"
- **Test button** per channel — sends a test notification
- **Notification log:** Recent notifications sent (success/failure, timestamp, channel, message)

**Implementation:**

```
daemon/services/notification_hub.py
├── NotificationHub
├── Channel classes:
│   ├── EmailChannel(smtp_host, smtp_port, from_addr, recipients, tls)
│   ├── DiscordChannel(webhook_url)
│   ├── SlackChannel(webhook_url)
│   ├── TelegramChannel(bot_token, chat_id)
│   ├── PushoverChannel(user_key, app_token)
│   └── WebhookChannel(url, method, headers, body_template)
├── send(channel_id, message, severity)        — Send to specific channel
├── dispatch(event_type, data)                 — Route to configured channels based on rules
├── test_channel(channel_id)                   — Send test notification
├── get_notification_log(limit=50)             — Recent sent notifications
└── Routing rules engine:
    ├── Rule: {event_type, severity_filter, channel_ids}
    ├── Event types: alert_critical, alert_high, new_device, iot_anomaly,
    │               bandwidth_cap_warning, smart_warning, capture_drops, weekly_summary
    └── Persistence: /opt/nettap/data/notification_config.json

daemon/api/notifications.py
├── GET /api/notifications/channels            — List configured channels
├── POST /api/notifications/channels           — Add channel
├── PUT /api/notifications/channels/{id}       — Update channel
├── DELETE /api/notifications/channels/{id}    — Remove channel
├── POST /api/notifications/channels/{id}/test — Send test notification
├── GET /api/notifications/rules               — List routing rules
├── POST /api/notifications/rules              — Add routing rule
├── PUT /api/notifications/rules/{id}          — Update rule
├── DELETE /api/notifications/rules/{id}       — Remove rule
└── GET /api/notifications/log?limit=50        — Recent notification history

web/src/routes/settings/notifications/+page.svelte
├── Channel configuration cards (add/edit/test/remove per channel type)
├── Routing rules table (event type → channels mapping)
├── Test button per channel with success/failure feedback
└── Notification log table with status indicators
```

**Tests:**
- Daemon: `test_notification_hub.py` — each channel type (mock HTTP), routing dispatch, test send, failure handling, log persistence
- Web: `notifications-settings.test.ts` — channel CRUD, rule CRUD, test button interaction

---

### 10.6 Network Changelog / Audit Log (`/changelog`) — MEDIUM PRIORITY

**"What changed on my network this week?"** A single chronological feed of all network events.

**Page: `/changelog`**

**Layout:**
- Chronological timeline feed (newest first)
- Event types with icons:
  - **Device appeared** (green +) — "MacBook Pro joined the network (192.168.1.42)"
  - **Device disappeared** (gray −) — "Ring Doorbell went offline (last seen 2h ago)"
  - **IP changed** (blue ↔) — "iPad changed IP from .50 to .51"
  - **New service detected** (purple) — "Raspberry Pi started serving on port 8080"
  - **Alert triggered** (red !) — "Suricata: ET MALWARE on PC-1"
  - **Alert acknowledged** (green ✓) — "Admin marked alert #247 as false positive"
  - **Config changed** (orange ⚙) — "Retention policy updated: hot tier 90d → 60d"
  - **IoT anomaly** (yellow ⚠) — "Smart TV contacted new destination in China"
  - **Capture event** (gray) — "Mirror NIC link flap detected and recovered"
- Filterable by event type, device, severity, date range
- Exportable as JSON/CSV

**Implementation:**

```
daemon/services/changelog.py
├── ChangelogService
├── record_event(type, description, device?, severity?, metadata?)
├── get_events(from, to, types?, device?, limit=100)
├── Event types enum: DEVICE_JOINED, DEVICE_LEFT, IP_CHANGED, SERVICE_DETECTED,
│                      ALERT_TRIGGERED, ALERT_ACKNOWLEDGED, CONFIG_CHANGED,
│                      IOT_ANOMALY, CAPTURE_EVENT, SYSTEM_EVENT
├── Persistence: OpenSearch index `nettap-changelog-*` (ILM managed, 90d retention)
└── Integration: Other services call changelog.record_event() when state changes

daemon/api/changelog.py
├── GET /api/changelog?from=&to=&types=&device=&limit=100
├── GET /api/changelog/stats?from=&to=         — Event counts by type
└── GET /api/changelog/export?format=json|csv   — Bulk export

web/src/routes/changelog/+page.svelte
├── Timeline feed with event type icons and color coding
├── Filter bar: event type checkboxes, device selector, date range
├── Infinite scroll or pagination
└── Export button (JSON/CSV)
```

**Tests:**
- Daemon: `test_changelog.py` — event recording, retrieval, filtering, stats aggregation
- Web: `changelog.test.ts` — timeline rendering, filtering, infinite scroll, export

---

### 10.7 Bandwidth Top Consumers (real-time) — MEDIUM PRIORITY

**Integrated into existing pages rather than a standalone page.** Adds real-time "who's using bandwidth right now" to the dashboard and bandwidth page.

**Components:**

```
web/src/lib/components/TopConsumers.svelte
├── Props: timeRange ("1m" | "5m" | "1h" | "24h"), limit (default 10)
├── Animated bar chart: Device name → current throughput (Mbps)
├── Auto-updates every 5s (short ranges) or 30s (longer ranges)
├── Click device → navigate to device detail
└── Shows direction split: download (blue) vs upload (orange)

daemon/api/bandwidth.py (extend)
└── GET /api/bandwidth/realtime?window=5m&limit=10 — Top consumers in sliding window
```

Placed on: Dashboard home (`/`), Bandwidth page (`/bandwidth`), Live page (`/live`) sidebar.

**Tests:**
- Daemon: `test_bandwidth_tracker.py` (extend) — real-time window aggregation
- Web: `TopConsumers.test.ts` — rendering, auto-update, click navigation

---

### 10.8 TLS Certificate Monitor (`/certificates`) — MEDIUM PRIORITY

**Track all TLS certificates observed in mirrored traffic.** Alert on security issues.

**Page: `/certificates`**

**Layout:**
- **Certificate inventory table:** Domain | Issuer | Valid From | Valid To | Days Until Expiry | Devices Using | Status
- **Status badges:** Valid (green), Expiring Soon <30d (yellow), Expired (red), Self-Signed (orange), Issuer Changed (red)
- **Alert conditions:**
  - Certificate expired
  - Certificate expiring within 30 days
  - Self-signed certificate detected (potential MITM)
  - Certificate issuer changed for same domain (definite MITM indicator)
  - Certificate with unusually short validity period (<7 days)
- **Certificate detail:** Click → full cert info, chain, SAN list, historical changes

**Implementation:**

```
daemon/services/cert_monitor.py
├── CertificateMonitor
├── extract_certs_from_zeek()                  — Parse zeek-ssl/x509 logs for certificate data
├── get_certificate_inventory(from, to)        — All observed certs
├── check_expiring(days_threshold=30)          — Certs expiring soon
├── check_issuer_changes()                     — Detect issuer changes for same domain
├── detect_self_signed()                       — Flag self-signed certs
├── get_cert_history(domain)                   — Historical cert changes for domain
└── Integration: Runs on Zeek x509.log and ssl.log data in OpenSearch

daemon/api/certificates.py
├── GET /api/certificates?from=&to=&status=    — Certificate inventory
├── GET /api/certificates/expiring?days=30     — Expiring soon
├── GET /api/certificates/alerts               — Self-signed, issuer changes, expired
├── GET /api/certificates/{fingerprint}        — Single cert detail
└── GET /api/certificates/domain/{domain}      — Cert history for domain

web/src/routes/certificates/+page.svelte
├── Certificate inventory table (sortable by expiry, status)
├── Status filter tabs: All | Valid | Expiring | Expired | Alerts
├── Certificate detail modal
└── Alert indicators with explanations
```

**Tests:**
- Daemon: `test_cert_monitor.py` — cert extraction, expiry checks, issuer change detection, self-signed detection
- Web: `certificates.test.ts` — table rendering, status badges, filtering, detail modal

---

### 10.9 ARP/DHCP Anomaly Detection — MEDIUM PRIORITY

**Classic LAN attack indicators that are trivial to detect from mirrored traffic.** Integrated into the alerts system rather than a standalone page.

**Detections:**

| Anomaly | Description | Detection Method |
|---------|-------------|-----------------|
| ARP Spoofing | Multiple MACs claiming same IP | Monitor ARP replies: if IP maps to different MAC than baseline, alert |
| ARP Flooding | Excessive ARP requests from single source | Rate limit: >100 ARP requests/min from one MAC |
| Rogue DHCP Server | Unauthorized DHCP server on LAN | DHCP Offer from unexpected source IP (not the known DHCP server) |
| DHCP Exhaustion | Mass DHCP requests depleting address pool | >50 DHCP Discover from same MAC in 5 minutes |
| IP Conflict | Two devices using the same IP | Gratuitous ARP with conflicting MAC for existing IP |

**Implementation:**

```
daemon/services/lan_anomaly_detector.py
├── LANAnomalyDetector
├── check_arp_spoofing(from, to)               — Detect IP→MAC inconsistencies
├── check_arp_flooding(from, to)               — Detect excessive ARP from single source
├── check_rogue_dhcp(from, to)                 — Detect unauthorized DHCP servers
├── check_dhcp_exhaustion(from, to)            — Detect mass DHCP requests
├── check_ip_conflicts(from, to)               — Detect duplicate IP usage
├── run_all_checks()                           — Run all detections (called from daemon loop)
└── Integration: Results fed into alert system + changelog + notification hub

daemon/api/lan_security.py
├── GET /api/lan-security/anomalies?from=&to=  — Detected anomalies
├── GET /api/lan-security/arp-table            — Current ARP table (IP→MAC mapping)
└── GET /api/lan-security/dhcp-servers         — Known DHCP servers on LAN
```

Anomalies surface in: Alerts page, Changelog, Notification Hub (routable to channels).

**Tests:**
- Daemon: `test_lan_anomaly_detector.py` — each detection type with mock Zeek ARP/DHCP log data

---

### 10.10 MAC Randomization Correlation — MEDIUM PRIORITY

**Modern phones/laptops randomize MACs on WiFi.** Without handling this, the device list shows 5 "Apple iPhones" that are really the same phone.

**Implementation:**

```
daemon/services/mac_correlator.py
├── MACCorrelator
├── detect_randomized_macs()                   — Identify locally-administered MACs (bit 1 of first octet set)
├── correlate_devices(mac_list)                — Group randomized MACs by behavioral fingerprint
├── Correlation signals:
│   ├── JA3/JA4 TLS fingerprint match (same client software)
│   ├── DNS query pattern similarity (same browsing habits)
│   ├── Traffic timing correlation (same active hours)
│   ├── Destination overlap (same servers contacted)
│   └── DHCP hostname match (option 12 sometimes preserved across MAC changes)
├── merge_devices(primary_mac, secondary_macs) — Merge into single device identity
├── get_correlation_suggestions()              — Suggest potential merges for user approval
└── Integration: Fed into DeviceRegistry, user confirms merges via UI

daemon/api/devices.py (extend)
├── GET /api/devices/correlations              — Suggested MAC correlations
├── POST /api/devices/correlations/merge       — Confirm merge
└── POST /api/devices/correlations/dismiss     — Dismiss suggestion
```

**UI integration:** Banner on device page: "We detected 3 MACs that may be the same device. Review?" → shows evidence for each correlation.

**Tests:**
- Daemon: `test_mac_correlator.py` — randomized MAC detection, fingerprint matching, correlation scoring, merge logic

---

### 10.11 PCAP Search & Download (`/pcap`) — NICE-TO-HAVE

**Bridges the gap between the dashboard and deep packet analysis.** Search captured PCAPs, preview packets, download filtered captures for Wireshark.

**Page: `/pcap`**

**Layout:**
- **Search bar:** BPF filter syntax (e.g., `host 192.168.1.50 and port 443`)
- **Time range selector**
- **Results:** Matching PCAP files with packet count, size, time range
- **Preview:** First 100 packets shown in a table (similar to existing tshark viewer)
- **Download button:** Download filtered PCAP file for Wireshark analysis
- **Quick filters:** Pre-built buttons for common searches (DNS traffic, HTTP, a specific device, alerts)

**Implementation:**

```
daemon/services/pcap_search.py
├── PcapSearchService
├── search(bpf_filter, from, to)               — Find matching PCAP files
├── preview(pcap_file, bpf_filter, limit=100)  — Extract matching packets for preview
├── download(bpf_filter, from, to)             — Merge + filter PCAPs into single download
├── get_available_pcaps(from, to)              — List stored PCAP files with metadata
└── Integration: Reads from PCAP storage directory, uses tcpdump/tshark for filtering

daemon/api/pcap.py
├── GET /api/pcap/search?filter=&from=&to=     — Search PCAP files
├── GET /api/pcap/preview?file=&filter=&limit= — Preview packets
├── GET /api/pcap/download?filter=&from=&to=   — Download filtered PCAP
└── GET /api/pcap/files?from=&to=              — List available PCAP files

web/src/routes/pcap/+page.svelte
├── BPF filter input with syntax hints
├── Quick filter buttons
├── Results table (file, packets, size, time range)
├── Packet preview table (reuse existing tshark packet table component)
└── Download button with progress indicator
```

**Tests:**
- Daemon: `test_pcap_search.py` — BPF filter validation, file matching, preview extraction, download merging
- Web: `pcap.test.ts` — search interface, results display, preview rendering, download trigger

---

### 10.12 Backup/Restore Configuration (`/settings/backup`) — NICE-TO-HAVE

**Prevents "I rebuilt my NetTap and lost all my config."**

**Page: `/settings/backup`**

**Layout:**
- **Export button:** Download all NetTap settings as a single JSON file
- **Import button:** Upload a settings JSON to restore configuration
- **What's included:** Capture mode, retention policy, notification channels + rules, device aliases, investigation bookmarks, IoT baselines, bandwidth cap, UniFi integration config
- **What's NOT included:** Captured data, OpenSearch indices, PCAPs (too large, and deployment-specific)
- **Version stamp:** Export includes NetTap version for compatibility checking on import

**Implementation:**

```
daemon/services/config_backup.py
├── ConfigBackup
├── export_config()                            — Gather all settings into single dict
├── import_config(data)                        — Validate + apply settings from dict
├── validate_import(data)                      — Check version compatibility, schema validation
└── Sections exported:
    ├── capture_mode_config
    ├── storage_retention_config
    ├── notification_channels + rules
    ├── device_aliases + categories
    ├── investigation_bookmarks
    ├── iot_baselines
    ├── bandwidth_cap
    ├── unifi_integration_config
    ├── detection_packs_installed
    └── dashboard_preferences

daemon/api/backup.py
├── GET /api/backup/export                     — Download config JSON
├── POST /api/backup/import                    — Upload + validate config JSON
└── POST /api/backup/validate                  — Validate without applying

web/src/routes/settings/backup/+page.svelte
├── Export button with last export date
├── Import dropzone with validation preview
├── Diff view: "These settings will change: ..." before applying
└── Success/failure feedback
```

**Tests:**
- Daemon: `test_config_backup.py` — export completeness, import validation, version compatibility, partial import
- Web: `backup.test.ts` — export trigger, import upload, validation display, diff preview

---

## 10.13 Suricata IDS Rule Expansion (`/settings/suricata-rules`) — HIGH PRIORITY

**Massively increase detection coverage by enabling all available free Suricata rule feeds.** Currently NetTap only uses ET Open — leaving significant detection gaps for malware C2, malicious certificates, and threat hunting patterns.

### Current State

Only **ET Open** (Emerging Threats Open) is enabled via Malcolm's `suricata-update`. This provides ~30,000 rules covering malware, exploits, scans, and policy violations.

### Free Rule Sources to Add

| Source | Feed ID | What it covers | Rules |
|--------|---------|---------------|-------|
| **ET Open** | `et/open` | Malware, exploits, scans, policy violations | ~30,000 (already enabled) |
| **abuse.ch SSLBL** | `sslbl/ssl-fp-blacklist` | Malicious SSL certificates (C2 servers, botnets) | ~1,500 |
| **abuse.ch URLhaus** | `sslbl/ja3-fingerprints` | JA3 fingerprints of known malware | ~300 |
| **abuse.ch Feodo Tracker** | `etnetera/aggressive` | Banking trojans C2 IPs (Dridex, Emotet, TrickBot) | ~500 |
| **tgreen/hunting** | `tgreen/hunting` | Threat hunting (suspicious TLS, DNS tunneling, beaconing, unusual protocols) | ~200 |
| **OISF Traffic ID** | `oisf/trafficid` | Application protocol identification (useful for device fingerprinting) | ~300 |
| **Positive Technologies** | `ptresearch/attackdetection` | PT security research rules (CVE detections, web attacks) | ~500 |
| **Etnetera Aggressive** | `etnetera/aggressive` | Aggressive IP reputation and threat intel | ~1,000 |

**Total: ~34,000+ rules (up from ~30,000) with significantly better coverage for:**
- Botnet C2 communication (abuse.ch feeds)
- Malicious TLS certificates
- DNS tunneling and beaconing detection
- IoT-specific malware signatures
- Known threat actor infrastructure

### Commercial Sources (Optional, User-Configured)

| Source | What it covers | Cost |
|--------|---------------|------|
| **ET Pro** | ET Open + 40,000 additional rules, faster updates, curated threat intel | ~$900/yr |
| **Snort Subscriber** | Cisco Talos rules (complementary to ET) | ~$400/yr |

Users can enter their own license keys to enable commercial feeds.

### Implementation

**Page: `/settings/suricata-rules`**

**Layout:**
- **Active rules summary:** "34,217 active rules from 8 sources — last updated 2h ago"
- **Rule sources table:** Source | Status (enabled/disabled) | Rule Count | Last Update | Toggle
- **Free sources section:** All free feeds listed with enable/disable toggles
- **Commercial sources section:** ET Pro / Snort key input fields
- **Update controls:** "Update Rules Now" button, auto-update schedule (daily/weekly)
- **Rule stats:** Categories breakdown (malware, exploit, scan, policy, etc.) with counts
- **Custom rules section:** Upload custom `.rules` files for advanced users

```
daemon/services/suricata_rules.py
├── SuricataRuleManager
├── get_enabled_sources()                    — List all configured rule sources with status
├── enable_source(source_id)                 — Enable a rule feed
├── disable_source(source_id)               — Disable a rule feed
├── update_rules()                          — Run suricata-update to fetch latest rules
├── get_rule_stats()                        — Count rules by category (malware, exploit, etc.)
├── get_last_update()                       — When rules were last updated
├── set_update_schedule(interval)           — Configure auto-update (daily/weekly/manual)
├── add_custom_rules(content)               — Add user-provided .rules content
├── configure_commercial(source, key)       — Set license key for ET Pro / Snort
└── Integration: Executes suricata-update inside the suricata container via docker exec

daemon/api/suricata_rules.py
├── GET  /api/suricata/rules/sources        — List all rule sources with status
├── POST /api/suricata/rules/sources/{id}/enable   — Enable a source
├── POST /api/suricata/rules/sources/{id}/disable  — Disable a source
├── POST /api/suricata/rules/update         — Trigger rule update now
├── GET  /api/suricata/rules/stats          — Rule count by category
├── GET  /api/suricata/rules/schedule       — Current update schedule
├── PUT  /api/suricata/rules/schedule       — Set update schedule
├── POST /api/suricata/rules/custom         — Upload custom rules
└── POST /api/suricata/rules/commercial     — Configure commercial source key

config/suricata/update-sources.yaml
├── Sources configuration for suricata-update
├── All free sources enabled by default
└── Mounted into container at /etc/suricata/update-sources.yaml

web/src/routes/settings/suricata-rules/+page.svelte
├── Active rules summary hero card
├── Rule sources table with enable/disable toggles
├── Update controls (manual + schedule)
├── Rule category stats breakdown
├── Custom rules upload area
└── Commercial license key input
```

**Key technical considerations:**
- `suricata-update` runs inside the Suricata container — daemon uses `docker exec` to manage it
- Rule updates require a Suricata reload (`suricatasc -c reload-rules`) — not a full restart
- Sources config persisted to `config/suricata/update-sources.yaml` (survives container recreate)
- Rule count stats parsed from `suricata-update` output or from the rules file directly
- Commercial keys stored in capture-mode.conf or a separate secrets file (never in docker-compose.yml)

**Tests:**
- Daemon: `test_suricata_rules.py` — source listing, enable/disable, update trigger, stats parsing, custom rules, schedule management
- Web: `suricata-rules.test.ts` — source table rendering, toggle interactions, update button, stats display

---

## 11. Implementation Order & Progress Tracker

> **This section is the source of truth for implementation progress.**
> Update checkboxes as tasks are completed. Add completion dates in parentheses.

### Phase A: Capture Mode Abstraction (foundation) — Status: COMPLETE

- [x] A1. Create `CaptureMode` enum and `CaptureManager` base class (2026-03-08)
- [x] A2. Create `BridgeCaptureAdapter` that wraps existing `BridgeManager` (do NOT refactor BridgeManager itself) (2026-03-08)
- [x] A3. Implement `MirrorManager` with full NIC hardening (2026-03-08)
- [x] A4. Add capture mode config file reading/writing (2026-03-08)
- [x] A5. Update daemon startup to instantiate correct manager (2026-03-08)
- [x] A6. Update docker-compose to use `PCAP_IFACE` variable — already parameterized, updated docs (2026-03-08)
- [x] A7. Add container startup gating — depends_on service_healthy for all 4 capture containers (2026-03-08)
- [x] A8. Tests for both managers — 65 tests, all passing (2026-03-08)

### Phase B: SMART Health Fix (quick win, high impact) — Status: COMPLETE

- [x] B1. Fix `/dev` mount and `SYS_RAWIO` in docker-compose — already correct (2026-03-08)
- [x] B2. Add startup self-test with diagnostic logging — run_self_test() + get_diagnostics() (2026-03-08)
- [x] B3. Add fallback NVMe field parsing — 3 temperature fallbacks, Samsung firmware variants (2026-03-08)
- [x] B4. Add `GET /api/smart/diagnostics` + `POST /api/smart/test` endpoints (2026-03-08)
- [x] B5. Update UI: "Unavailable" with tooltip instead of `--`, diagnostics link (2026-03-08)
- [x] B6. Index SMART metrics to OpenSearch `nettap-smart-*` (2026-03-08)
- [x] B7. Tests — 14 new tests, 34 total passing (2026-03-08)

### Phase C: Storage Hardening — Status: COMPLETE

- [x] C1. Predictive disk exhaustion alerting — rolling 24h window, 48h projection (2026-03-08)
- [x] C2. Emergency cascade deletion — 90% prune, 95% stop capture, 85% resume (2026-03-08)
- [x] C3. ILM policy verification on daemon startup — auto-recreate if missing (2026-03-08)
- [x] C4. Per-tier disk accounting — hot/warm/cold bytes from OpenSearch + PCAP dir (2026-03-08)
- [x] C5. PCAP checksum writing/verification — xxh3 with sha256 fallback (2026-03-08)
- [x] C6. Re-index from logs recovery path — bulk JSON re-indexing (2026-03-08)
- [x] C7. Tests — 25 new tests, 47 total passing (2026-03-08)

### Phase D: Device Identification — Status: COMPLETE

- [x] D1. Implement `DeviceRegistry` service with OpenSearch backend (2026-03-08)
- [x] D2. Add passive enrichment: ARP/DHCP snooping (from Zeek logs) (2026-03-08)
- [x] D3. Add mDNS/SSDP/UPnP parsing (2026-03-08)
- [x] D4. Add MAC OUI offline database + lookup (2026-03-08)
- [x] D5. Add JA3/JA4 TLS fingerprinting integration (2026-03-08)
- [x] D6. Implement `UnifiIntegration` service (optional) (2026-03-08)
- [x] D7. Add device API endpoints — 4 capture + 7 device/UniFi endpoints (2026-03-08)
- [x] D8. Tests for enrichment merging and priority — 62 tests, all passing (2026-03-08)

### Phase E: Setup Wizard — Status: COMPLETE

- [x] E1. Add capture mode selection step (Step 2) — Mirror/SPAN with recommended badge, Inline Bridge (2026-03-08)
- [x] E2. Refactor interface config step to be mode-dependent — 1 NIC mirror, 2 NIC bridge (2026-03-08)
- [x] E3. Add device enrichment step (UniFi integration, mirror mode only) — toggle, creds, test button (2026-03-08)
- [x] E4. Adjust requirements check for mode (1 NIC vs 2) — dynamic before/after mode selection (2026-03-08)
- [x] E5. Write config file and `.env` on wizard completion — POST /api/setup/configure endpoint (2026-03-08)
- [x] E6. Tests for wizard flow — 37 tests, all passing (2026-03-08)

### Phase F: Dashboard (core) — Status: COMPLETE

- [x] F1. Add device-centric home page (mirror mode) — DeviceGrid component, mode-aware +page.svelte (2026-03-08)
- [x] F2. Add device detail page — /devices/mac/[mac] with traffic, DNS, alerts (2026-03-08)
- [x] F3. Add new device detection notifications — NewDeviceBanner with dismiss/acknowledge (2026-03-08)
- [x] F4. Add capture health panel — CaptureHealthPanel, mode-agnostic (2026-03-08)
- [x] F5. Add mode indicator badge in header — MIRROR/BRIDGE badge in +layout.svelte (2026-03-08)
- [x] F6. Fix SMART panel UI — Already done in Phase B (2026-03-08)
- [x] F7. Add SSD trending charts — Already done in Phase B (2026-03-08)
- [x] F8. Add storage per-tier breakdown panel — StorageTierPanel component (2026-03-08)
- [x] F9. Tests — 87 new tests across 6 files, all passing (2026-03-08)

### Phase G: Real-Time & Bandwidth (high-impact new features) — Status: COMPLETE

- [x] G1. Implement `LiveConnectionTracker` service — in-memory 10k cache, filtering, rate calc (2026-03-08)
- [x] G2. Build `/live` page — auto-refresh 3s, pause/play, filters, color-coded rows (2026-03-08)
- [x] G3. Implement `BandwidthTracker` service — monthly/daily/per-device, projection, heatmap (2026-03-08)
- [x] G4. Build `/bandwidth` page — hero card, progress bar, daily chart, per-device table, heatmap (2026-03-08)
- [x] G5. Build `TopConsumers` component — ranked bar visualization (2026-03-08)
- [x] G6. Tests — 57 new tests (36 daemon + 21 web), all passing (2026-03-08)

### Phase H: DNS & Security Analytics (high-impact new features) — Status: COMPLETE

- [x] H1. Implement `DNSAnalytics` service — 8 methods, Shannon entropy DGA detection, tunneling (2026-03-08)
- [x] H2. Build `/dns` page — hero stats, top domains, per-device, query types, timeline, suspicious panel (2026-03-08)
- [x] H3. Implement `IoTMonitor` service — 35+ vendor OUIs, baseline learning, 6 anomaly types (2026-03-08)
- [x] H4. Build `/iot` page — device grid, baseline viewer, anomaly feed (2026-03-08)
- [x] H5. Implement `LANAnomalyDetector` — ARP spoofing, rogue DHCP, IP conflicts (2026-03-08)
- [x] H6. Integrate LAN anomalies — 3 API endpoints, combined into IoT & LAN page (2026-03-08)
- [x] H7. Tests — 81 new tests (51 daemon + 30 web), all passing (2026-03-08)

### Phase I: Notification & Observability (medium-priority new features) — Status: COMPLETE

- [x] I1. Implement `NotificationHub` — 6 channel types (Email/Discord/Slack/Telegram/Pushover/Webhook) (2026-03-08)
- [x] I2. Implement routing rules engine — event type → channels mapping with severity filter (2026-03-08)
- [x] I3. Build `/settings/notifications` page — channel CRUD, routing rules, test buttons, delivery log (2026-03-08)
- [x] I4. Implement `ChangelogService` — OpenSearch nettap-changelog-* indices (2026-03-08)
- [x] I5. Build `/changelog` page — timeline feed, type filters, CSV/JSON export (2026-03-08)
- [x] I6. Implement `CertificateMonitor` — expiry, self-signed, issuer change (MITM) detection (2026-03-08)
- [x] I7. Build `/certificates` page — inventory table, status filters, detail modal, MITM warnings (2026-03-08)
- [x] I8. Tests — 97 new tests (57 daemon + 40 web), all passing (2026-03-08)

### Phase J: Intelligence & Utilities (nice-to-have new features) — Status: COMPLETE

- [x] J1. Implement `MACCorrelator` — randomized MAC detection, behavioral fingerprinting, similarity, merge/undo (2026-03-08)
- [x] J2. Integrate MAC correlation — 6 API endpoints, JSON persistence (2026-03-08)
- [x] J3. Implement `PcapSearchService` — BPF filter, tshark preview, filtered download (2026-03-08)
- [x] J4. Build `/pcap` page — filter input, quick filters, results, preview, download (2026-03-08)
- [x] J5. Implement `ConfigBackup` — export/import 7 config sections, schema versioning (2026-03-08)
- [x] J6. Build `/settings/backup` page — export button, drag-and-drop import, validation (2026-03-08)
- [x] J7. Tests — 102 new tests (54 daemon + 48 web), all passing (2026-03-08)

### Phase K: Suricata IDS Rule Expansion (detection coverage) — Status: COMPLETE

- [x] K1. Create `config/suricata/update-sources.yaml` — 7 free community feeds enabled (2026-03-08)
- [x] K2. Update `docker-compose.yml` — sources config volume mount added to suricata-live (2026-03-08)
- [x] K3. Implement `SuricataRuleManager` — 11 methods, async docker exec for update/reload (2026-03-08)
- [x] K4. Implement API endpoints — 11 endpoints with slash-containing source ID support (2026-03-08)
- [x] K5. Build `/settings/suricata-rules` page — sources table, toggles, update controls, custom rules, commercial (2026-03-08)
- [x] K6. Update suricata_descriptions.json — 6 new category descriptions added (2026-03-08)
- [x] K7. Tests — 60 new tests (32 daemon + 28 web), all passing (2026-03-08)

---

## 12. Files Affected (High-Level)

### New Files — Core (Phases A-F)

| File | Description |
|------|-------------|
| `daemon/services/capture_manager.py` | Abstract base + CaptureMode enum |
| `daemon/services/mirror_manager.py` | Mirror NIC setup, health, drops |
| `daemon/services/device_registry.py` | Device table, enrichment merging |
| `daemon/services/unifi_integration.py` | Optional UniFi Controller API client |
| `daemon/api/capture.py` | Mode-agnostic capture endpoints |
| `daemon/api/integrations.py` | UniFi integration endpoints |
| `scripts/mirror/setup-mirror.sh` | Mirror NIC configuration script |
| `web/src/lib/api/capture.ts` | Capture mode API client |
| `config/nettap/capture-mode.conf` | Default capture mode config |

### New Files — Feature Pages (Phases G-J)

| File | Description |
|------|-------------|
| `daemon/services/live_connections.py` | Real-time connection tracking + WebSocket |
| `daemon/services/bandwidth_tracker.py` | Monthly/daily/per-device bandwidth + heatmap |
| `daemon/services/dns_analytics.py` | DNS query analytics, DGA detection, tunneling |
| `daemon/services/iot_monitor.py` | IoT classification, baseline learning, anomaly detection |
| `daemon/services/notification_hub.py` | Multi-channel notifications (Email/Discord/Slack/Telegram/Pushover/Webhook) |
| `daemon/services/changelog.py` | Network event audit log |
| `daemon/services/cert_monitor.py` | TLS certificate tracking + anomaly detection |
| `daemon/services/lan_anomaly_detector.py` | ARP spoofing, rogue DHCP, IP conflict detection |
| `daemon/services/mac_correlator.py` | MAC randomization detection + behavioral correlation |
| `daemon/services/pcap_search.py` | PCAP search, preview, filtered download |
| `daemon/services/config_backup.py` | Settings export/import |
| `daemon/api/live.py` | Real-time connections + WebSocket endpoint |
| `daemon/api/bandwidth.py` | Bandwidth stats endpoints |
| `daemon/api/dns.py` | DNS analytics endpoints |
| `daemon/api/iot.py` | IoT monitor endpoints |
| `daemon/api/notifications.py` | Notification channel + rule CRUD |
| `daemon/api/changelog.py` | Changelog event endpoints |
| `daemon/api/certificates.py` | Certificate inventory endpoints |
| `daemon/api/lan_security.py` | LAN anomaly detection endpoints |
| `daemon/api/pcap.py` | PCAP search/preview/download endpoints |
| `daemon/api/backup.py` | Config backup/restore endpoints |
| `web/src/routes/live/+page.svelte` | Real-time connection monitor |
| `web/src/routes/bandwidth/+page.svelte` | Bandwidth & data cap tracker |
| `web/src/routes/dns/+page.svelte` | DNS analytics page |
| `web/src/routes/iot/+page.svelte` | IoT behavior monitor |
| `web/src/routes/changelog/+page.svelte` | Network audit log |
| `web/src/routes/certificates/+page.svelte` | TLS certificate monitor |
| `web/src/routes/pcap/+page.svelte` | PCAP search & download |
| `web/src/routes/settings/notifications/+page.svelte` | Notification hub settings |
| `web/src/routes/settings/backup/+page.svelte` | Backup/restore settings |
| `web/src/lib/components/TopConsumers.svelte` | Real-time bandwidth top consumers |
| `web/src/lib/api/live.ts` | Live connections API client |
| `web/src/lib/api/bandwidth.ts` | Bandwidth API client |
| `web/src/lib/api/dns-analytics.ts` | DNS analytics API client |
| `web/src/lib/api/iot.ts` | IoT monitor API client |
| `web/src/lib/api/notifications.ts` | Notification hub API client |
| `web/src/lib/api/changelog.ts` | Changelog API client |
| `web/src/lib/api/certificates.ts` | Certificate monitor API client |
| `web/src/lib/api/pcap.ts` | PCAP search API client |
| `web/src/lib/api/backup.ts` | Config backup API client |

### New Files — Suricata Rule Expansion (Phase K)

| File | Description |
|------|-------------|
| `daemon/services/suricata_rules.py` | Rule source management, update trigger, stats parsing |
| `daemon/api/suricata_rules.py` | Rule management REST endpoints |
| `config/suricata/update-sources.yaml` | suricata-update sources config (all free feeds enabled) |
| `web/src/routes/settings/suricata-rules/+page.svelte` | Rule source management UI |
| `web/src/lib/api/suricata-rules.ts` | Suricata rules API client |

### Modified Files

| File | Changes |
|------|---------|
| `daemon/main.py` | Mode-aware startup, instantiate correct manager, register new service loops |
| `daemon/services/bridge_manager.py` | NO CHANGES — preserved as-is, wrapped by BridgeCaptureAdapter |
| `daemon/services/bridge_health.py` | Generalize for mode-agnostic health |
| `daemon/smart/monitor.py` | Startup self-test, fallback parsing, diagnostics |
| `daemon/api/server.py` | Register all new endpoints + WebSocket routes |
| `docker/docker-compose.yml` | PCAP_IFACE variable, healthcheck gating, /dev mount fix, suricata-update sources mount |
| `web/src/routes/setup/+page.svelte` | New wizard steps (mode select, enrichment) |
| `web/src/routes/system/+page.svelte` | SMART panel fix, trending |
| `web/src/routes/+page.svelte` | Mode-aware home page, TopConsumers integration |
| `web/src/lib/api/system.ts` | SMART diagnostics endpoint |
| `web/src/lib/api/devices.ts` | MAC correlation endpoints |
| `config/suricata/nettap.yaml` | Use PCAP_IFACE instead of hardcoded br0 |

### Test Files (one per service + component)

**Daemon tests (~15 new files):**
`test_capture_manager.py`, `test_mirror_manager.py`, `test_device_registry.py`, `test_unifi_integration.py`, `test_live_connections.py`, `test_bandwidth_tracker.py`, `test_dns_analytics.py`, `test_iot_monitor.py`, `test_notification_hub.py`, `test_changelog.py`, `test_cert_monitor.py`, `test_lan_anomaly_detector.py`, `test_mac_correlator.py`, `test_pcap_search.py`, `test_config_backup.py`, `test_suricata_rules.py`

**Web tests (~15 new files):**
`live.test.ts`, `bandwidth.test.ts`, `dns.test.ts`, `iot.test.ts`, `notifications-settings.test.ts`, `changelog.test.ts`, `certificates.test.ts`, `pcap.test.ts`, `backup.test.ts`, `TopConsumers.test.ts`, `capture.test.ts`, `live-api.test.ts`, `bandwidth-api.test.ts`, `dns-analytics-api.test.ts`, `iot-api.test.ts`, `suricata-rules.test.ts`

**Estimated totals: ~40 new files (daemon) + ~45 new files (web) = ~85 new files, ~25,000-30,000 new lines**

---

## 13. Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| 10G mirror → 2.5G NIC packet drops | Lost visibility during traffic bursts | Dashboard warns when NIC speed < mirror source; pcap-capture as safety net |
| Mirror NIC accidentally gets IP (DHCP) | Injects traffic onto mirrored VLAN | Strip IP on setup + NetworkManager/systemd-networkd config to never DHCP this interface |
| UniFi API changes across firmware | Integration breaks silently | Version detection, graceful fallback to Tier 1, periodic connectivity test |
| OpenSearch OOM on 16GB system | Data pipeline stalls | JVM heap cap (existing), emergency cascade deletion, daemon waits for cluster health |
| smartctl silent failures in Docker | SMART shows `--` forever | Startup self-test, diagnostics endpoint, explicit UI messaging |
| Bridge mode regression | Existing users broken | Full test suite for bridge mode preserved, mode-aware tests |
| WebSocket connection drops | Live page goes stale | Auto-reconnect with exponential backoff, visual "disconnected" indicator |
| IoT baseline false positives | Alert fatigue | 14-day learning period, user acknowledge/dismiss, rolling baseline update |
| Notification channel failures | Alerts not delivered | Retry with backoff, notification log shows failures, fallback to dashboard |
| PCAP download size | Browser crash on large downloads | Stream download, max file size limit (1GB), time range validation |
| MAC correlation false merges | Devices incorrectly combined | User confirmation required before merge, undo capability |
| DNS tunneling false positives | Legitimate CDNs flagged | Whitelist common CDN patterns (Akamai, Cloudflare), entropy threshold tuning |
| Suricata memory spike from extra rules | OOM on 16GB system | Monitor RSS after rule reload, document memory impact per source, allow disabling individual feeds |
| Rule update breaks detection | False negatives during update | Atomic rule reload via `suricatasc`, no restart needed, rollback to previous rules on error |

---

## 14. Success Criteria

### Core (Phases A-F)
- [ ] User can select Mirror/SPAN or Bridge mode during setup wizard
- [ ] Mirror mode captures packets with zero configuration beyond NIC selection
- [ ] Drop rate < 0.1% at sustained 2.5Gbps mirrored traffic
- [ ] All LAN devices discovered and identified by name within 5 minutes of first traffic
- [ ] UniFi integration pulls device aliases when configured
- [ ] SMART panel shows real Temperature, Wear, Power-On Hours (no more `--`)
- [ ] Storage cascade deletion prevents disk from ever reaching 100%
- [ ] Bridge mode works exactly as before (no regression)
- [ ] Dashboard loads < 3s, device list updates in real-time

### Feature Pages (Phases G-J)
- [ ] Live connection monitor streams connections in real-time via WebSocket
- [ ] Bandwidth page shows monthly usage vs cap with accurate projection
- [ ] DNS analytics page surfaces NXDOMAIN errors and suspicious patterns (DGA, tunneling)
- [ ] IoT monitor detects behavioral anomalies after 14-day learning period
- [ ] Notification hub delivers alerts to at least 3 channel types (Email, Discord, Slack)
- [ ] Changelog captures all network state changes in chronological feed
- [ ] Certificate monitor flags expired, self-signed, and issuer-changed certs
- [ ] ARP spoofing and rogue DHCP detection generates alerts
- [ ] MAC randomization correlation suggests device merges with evidence
- [ ] PCAP search returns filtered results and allows download
- [ ] Config backup/restore roundtrips correctly

### Suricata Rule Expansion (Phase K)
- [ ] All 8 free rule sources enabled and downloading on container start
- [ ] Rule count increases from ~30,000 (ET Open only) to ~34,000+ (all free sources)
- [ ] UI shows all sources with enable/disable toggles and last update timestamp
- [ ] "Update Rules Now" triggers `suricata-update` + `reload-rules` without container restart
- [ ] Commercial key input (ET Pro, Snort) works for users who have subscriptions
- [ ] Custom .rules file upload persists across container restarts

### Quality
- [ ] All new code has test coverage (daemon pytest + web vitest)
- [ ] All existing tests continue to pass (no regressions)
- [ ] All pages load < 3s on LAN
- [ ] WebSocket reconnects automatically after disconnection
