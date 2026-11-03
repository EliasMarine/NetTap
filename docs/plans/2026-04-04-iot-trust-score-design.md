# IoT Trust Score Page — Design Document

**Date:** 2026-04-04
**Branch:** `phase-4/iot-trust-score`
**Status:** Approved

## Context

The current `/iot` page lists IoT devices by manufacturer, shows behavioral baselines (known destinations/ports/countries), and has a flat anomaly feed. It provides no actionable insight — a home user visiting this page can't quickly answer "is my smart home safe?"

Other pages already cover: device inventory (`/devices`), connections (`/connections`), IDS alerts (`/alerts`), kill chains (`/threats`), live traffic (`/live`), bandwidth (`/bandwidth`), DNS (`/dns`).

The white space is: **per-device behavioral baselining, privacy/telemetry scoring, protocol compliance, encryption posture, lateral movement visibility, and manufacturer reputation** — things that only make sense when analyzed per-device-class over time.

## Audience

Home users who want plain-English, actionable answers. Not SOC analysts. Think: "credit score for your smart home."

## Design: IoT Trust Score

### 1. Hero Score Card

Full-width card at the top:
- **Smart Home Health Score**: Letter grade (A–F) + numeric 0–100
- **Three sub-scores** as colored badges: Privacy | Security | Behavior
- Plain-English subtitle: *"Your smart home is healthy. 1 device needs attention."*
- Score composite of all IoT devices' individual trust scores

**Scoring formula (per device, 0–100):**
- Privacy (30 pts): tracker domains contacted, telemetry volume, third-party data sharing
- Security (40 pts): encryption ratio, protocol compliance, alert count, firmware signals
- Behavior (30 pts): baseline adherence, new destinations, volume spikes, unusual timing

**Fleet score:** Weighted average of device scores, with lowest-scoring device pulling the average down more heavily (harmonic mean approach).

### 2. Stat Cards Row

4 stat cards below the hero:
| Card | Value | Color Logic |
|------|-------|-------------|
| IoT Devices | Total count | Always cyan |
| Anomalies | Behavioral deviations (24h) | Green if 0, amber if 1–3, red if 4+ |
| Privacy Concerns | Devices w/ privacy grade D or F | Green if 0, amber if 1–2, red if 3+ |
| Unencrypted | Devices sending plaintext externally | Green if 0, red if any |

### 3. Device Trust Grid

Grid of device cards sorted by risk (worst first):
- **Device name** (UniFi alias > manufacturer > hostname > MAC)
- **Trust grade** (A–F) with color badge:
  - A (90–100): green
  - B (75–89): cyan
  - C (60–74): amber
  - D (40–59): orange
  - F (0–39): red
- **Three mini indicators:** Privacy grade, Encryption %, Anomaly count
- **Last seen** timestamp
- **Click → opens device detail drawer**

### 4. Manufacturer Profiles Section

Card below device grid grouping devices by manufacturer:
- Each manufacturer shows: device count, average trust score, avg privacy grade
- Color-coded bar showing manufacturer "hygiene":
  - Encryption compliance (% of connections using TLS)
  - Tracker domain count across all devices from this manufacturer
  - Protocol violations count
- **Purpose:** Helps users make purchasing decisions. "Ring devices on your network have a B+ security hygiene. TP-Link devices have a D."
- Manufacturers sorted by worst hygiene first

### 5. Findings Feed

Chronological feed of noteworthy events:
- Severity badge (Critical/High/Medium/Low)
- Plain-English description: *"Your Roku TV contacted 3 new tracking domains today"*
- Device name (clickable)
- Timestamp + relative time ("3 hours ago")
- Category tag pill: Privacy | Security | Behavior

Finding types:
- **Privacy:** New tracker domains, telemetry volume spike, excessive phone-home
- **Security:** Unencrypted external connection, unexpected protocol, beaconing, self-signed cert on WAN connection
- **Behavior:** New destination not in baseline, new country, new port, unusual activity time, volume spike

### 6. Device Detail Drawer (on click)

5-tab drawer (480px, slides from right):

**Tab 1 — Overview**
- Trust score breakdown (3 sub-scores with progress bars)
- Device info: IP, MAC, manufacturer, hostname, first/last seen
- Quick stats: daily data volume, connection count, unique destinations
- Plain-English summary: "This device is behaving normally" or "This device has 2 findings"

**Tab 2 — Communication Map**
- HorizontalBarList showing every destination, bars sized by bytes
- Each row: hostname (or IP), country flag, bytes up/down
- "In baseline" (green dot) or "NEW" (amber badge) per destination
- Sort by: bytes, first seen, baseline status
- Destinations outside baseline highlighted

**Tab 3 — Privacy**
- Privacy grade (A–F) with explanation
- Tracker domains contacted (HorizontalBarList, sorted by bytes)
- Telemetry volume: bytes to trackers vs. functional domains (mini donut chart)
- Phone-home frequency: connections per hour when device is "idle"
- Encryption ratio: TLS vs plaintext (donut chart)

**Tab 4 — Protocol Audit**
- Table: protocol/port | status (Expected / Unexpected) | connection count | last seen
- Flags with plain-English explanations:
  - "Uses Telnet — this is an insecure remote access protocol"
  - "Bypasses your DNS — queries 8.8.8.8 directly instead of your router"
  - "Uses HTTP instead of HTTPS to send data externally"

**Tab 5 — Activity Timeline**
- TimeSeriesChart: connection count per hour, 7-day window
- Baseline overlay: shaded band showing "normal" activity hours and volume
- Anomaly markers: red dots on the timeline where deviations occurred
- Click a marker → shows the anomaly detail inline

### 7. Network Isolation Card (bottom of page)

Card answering: "If a device were compromised, what could it reach?"
- Table of IoT → non-IoT LAN communication pairs
- Risk-sorted:
  - Critical: IoT → workstation (via SMB/CIFS)
  - High: IoT → NAS
  - Medium: IoT → other IoT
  - Info: IoT → router/gateway
- Recommendation: "Consider creating a separate VLAN for your IoT devices — 3 IoT devices can currently reach your workstations"

## Backend: New API Endpoints

### `GET /api/iot/fleet-summary`
Returns overall health score, sub-scores, stat card data, devices-needing-attention list.
Internally aggregates from other IoT services. Cached 60 seconds.

### `GET /api/iot/privacy-report`
Per-device privacy grades (A–F) across 4 factors:
- Tracker domains contacted (matched against `daemon/data/tracker_domains.txt`)
- Telemetry volume (daily bytes uploaded)
- Third-party data sharing (distinct destination orgs)
- Encryption compliance (TLS vs plaintext ratio)

### `GET /api/iot/devices/{mac}/communication-map`
Full destination map for a single device:
- Each destination: IP, hostname (from DNS cross-query), country, port, bytes in/out, first/last seen
- `in_baseline: bool` flag per destination
- Sorted by bytes descending

### `GET /api/iot/devices/{mac}/activity-timeline`
Hourly buckets over configurable window (default 7d):
- Connection count, bytes sent/received, unique destinations, protocol breakdown
- `baseline_overlay`: learned normal hours and average volumes

### `GET /api/iot/protocol-audit`
Per-device protocol compliance check:
- Expected protocols per device category (from `daemon/data/protocol_profiles.json`)
- Actual protocols observed
- Findings: unexpected protocols, unencrypted WAN connections, hardcoded DNS

### `GET /api/iot/network-isolation`
Internal communication analysis:
- IoT devices that communicated with non-IoT LAN devices
- Risk classification per pairing
- Segmentation score (0–100)

### `GET /api/iot/manufacturer-profiles`
Aggregated manufacturer statistics:
- Device count per manufacturer
- Average trust score, privacy grade
- Encryption compliance %, tracker domain count, protocol violations

### Data Files Required

- `daemon/data/tracker_domains.txt` — ~200 known analytics/tracking domains (crashlytics.com, mixpanel.com, amplitude.com, doubleclick.net, etc.)
- `daemon/data/protocol_profiles.json` — Expected port/protocol sets per IoT device category (camera, thermostat, smart speaker, hub, TV, plug, etc.)

## Design System Compliance

- All colors via CSS variables (`var(--green)`, `var(--danger)`, etc.)
- All spacing via spacing vars (`var(--space-md)`)
- All text via text vars (`var(--text-sm)`)
- No max-width on page container
- All tables sortable
- Use existing components: HorizontalBarList, DetailDrawer, DrawerSection, KVRow, TimeSeriesChart, DonutChart, stat cards, pills, badges
- Monospace for IPs, MACs, ports
- Responsive: 2-col grid at 1024px, 1-col at 768px

## What This Page Does NOT Do (Avoid Overlap)

- General device inventory → `/devices`
- All connection logs → `/connections`
- IDS/Suricata alerts → `/alerts`
- Kill chain / threat intel → `/threats`
- Bandwidth monitoring → `/bandwidth`
- DNS query logs → `/dns`
- Live traffic → `/live`

The IoT page cross-references these (e.g., "3 alerts for this device — view on Alerts page") but does not duplicate them.

## Verification Plan

1. Backend: `cd daemon && python -m pytest` — all tests pass
2. Frontend: `cd web && npx vitest run` — all tests pass
3. Type check: `cd web && npx svelte-check` — no errors
4. Manual: Load `/iot` page with IoT devices on the network, verify:
   - Hero score renders with letter grade
   - Device cards sorted by risk
   - Click device → drawer opens with 5 tabs
   - Privacy tab shows tracker domains
   - Communication map shows baseline comparison
   - Network isolation card shows LAN pairs
   - Manufacturer profiles show aggregated data
