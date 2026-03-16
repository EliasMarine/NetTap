# Alerts v3: Category Hub + Drill-Down Design

**Date:** 2026-03-16
**Status:** Approved
**Mockups:** `mockups/alerts-v3/hub.html`, `mockups/alerts-v3/category-detail.html`

## Overview

Redesign the `/alerts` page into a **mission control hub** with an interactive category grid (13 categories) and dedicated `/alerts/[category]` drill-down pages. Adds 6 new alert categories, sub-categories for all 13, MITRE ATT&CK mapping, and exposes existing backend intelligence (smart alerts, suppress/FP, threat score) that currently has no UI.

## Design Pillars

- **Device-Centric:** Organize by "what categories are hitting my devices?"
- **Plain English:** Every category gets a description, every sub-category is human-readable
- **Immediate Value:** Big numbers on hub, details on click. Progressive disclosure: hub → category → raw logs

## Alert Category Taxonomy (13 Categories)

| # | ID | Label | Color | Suricata Patterns |
|---|-----|-------|-------|-------------------|
| 1 | `malware_c2` | Malware & C2 | red | MALWARE, TROJAN, C2, COMPROMISED, CINS, DSHIELD |
| 2 | `exfiltration` | Data Exfiltration | purple | DNS Tunnel, Covert Channel, Large Upload |
| 3 | `reconnaissance` | Reconnaissance | blue | SCAN, ENUM, Nmap, Masscan, RECON |
| 4 | `exploit` | Exploit Attempt | orange | SQL Injection, XSS, RCE, Buffer Overflow, CVE |
| 5 | `policy` | Policy Violation | amber | POLICY, P2P, GAMES, TOR, CHAT |
| 6 | `protocol_anomaly` | Protocol Anomaly | cyan | SURICATA TLS/HTTP/STREAM/FRAG/DNS |
| 7 | `credential_abuse` | Credential Abuse | pink | LOGIN, BRUTE, SSH Password, DEFAULT LOGIN |
| 8 | `geo_anomaly` | Geo-Anomaly | amber | *Derived from GeoIP* |
| 9 | `encrypted_threats` | Encrypted Threats | teal | SURICATA TLS Invalid, Self-Signed, Expired |
| 10 | `iot_anomaly` | IoT / Device Anomaly | purple | *Derived from baseline* |
| 11 | `dos` | Denial of Service | red | DOS, DDOS, FLOOD, SYN, Amplification |
| 12 | `sensitive_data` | Sensitive Data Exposure | pink | Cleartext credentials, PII patterns |
| 13 | `informational` | Informational | muted | ET INFO, GPL, generic low-priority |

### Sub-Categories

- **Malware & C2:** Trojan Activity, Known C2 Channel, Malware Download, Cryptomining, Botnet Comms
- **Reconnaissance:** Port Scan, Service Enum, OS Fingerprint, Network Sweep, Vuln Probe
- **Exploit Attempt:** Web App Attack, Client-Side Exploit, Privilege Escalation, Buffer Overflow, File Exploit
- **Data Exfiltration:** DNS Tunneling, Covert Channel, Large Upload, Cloud Exfil
- **Policy Violation:** P2P/Torrent, TOR/Proxy, Gaming, VPN Evasion, Inappropriate Content
- **Protocol Anomaly:** TLS Anomaly, HTTP Anomaly, DNS Anomaly, TCP State Violation, Fragmentation
- **Credential Abuse:** SSH Brute Force, RDP Brute Force, Default Login, Password Spray
- **Geo-Anomaly:** Unusual Country, First-Seen Country, Sanctioned Region, Known-Bad ASN
- **Encrypted Threats:** Self-Signed Cert, Expired Cert, Weak Cipher, JA3 Mismatch, Cert Impersonation
- **IoT/Device Anomaly:** Baseline Deviation, New Device, Unusual Port, Off-Hours Activity
- **DoS:** SYN Flood, UDP Flood, Amplification, Outbound DDoS Participation
- **Sensitive Data:** Cleartext Creds, PII in Transit, Unencrypted API Keys, HTTP POST with Passwords

## Page 1: `/alerts` Hub

### Layout (top to bottom)

1. **Header Bar** — Title, subtitle, threat score badge (0-100 gauge from smart/summary), time range pills, auto-refresh, refresh button
2. **Stats Strip** — 5 horizontal stat cards: Total, Critical, High, Medium, Low. Each clickable to filter.
3. **Alert Timeline** — Full-width stacked area chart. Toggle: "By Severity" / "By Category".
4. **Category Grid** — 4-column responsive grid of 13 category cards. Each card shows: icon, name, count, severity micro-bar, sparkline, sub-category pills, trend arrow. Click navigates to `/alerts/[category]`.
5. **Two-Column** — Top Signatures (ranked bar list with category badges) + Top Affected Devices (device name, IP, category dots, count, severity).
6. **Alert Log Table** — Sortable paginated table with: Timestamp, Severity, Category, Sub-Category, Signature, Source IP, Dest IP, Protocol, MITRE tactic, Actions (Suppress, False Positive).

### Key Interactions

- Category cards → navigate to `/alerts/[category]`
- Stat cards → filter table by severity
- Signature/IP rows → filter table
- Table rows → open detail drawer
- Suppress/FP buttons → call existing daemon APIs
- Threat score gauge → link to `/threats`

## Page 2: `/alerts/[category]` Drill-Down

### Layout (top to bottom)

1. **Header** — Back link, category icon + name, description, MITRE tactic badge, alert count, severity pills, time range.
2. **Stats Strip** — 4 cards: Total Alerts, Unique Sources, Unique Targets, Affected Devices.
3. **Sub-Category Breakdown** — Horizontal bar chart, one bar per sub-cat. Clickable to filter table.
4. **Category Timeline** — Area chart for this category only, stacked by sub-category.
5. **Two-Column** — Affected Devices (name, IP, count, severity, link) + Top Signatures (rank, name, bar, count, last seen).
6. **MITRE ATT&CK Mapping** — 3-column grid of technique cards (ID, name, description, alert count, external link).
7. **Alert Table** — Pre-filtered to category. Sub-category column, MITRE technique column, suppress/FP actions.

## Backend Changes

### Modified Endpoints

**`GET /api/alerts/categories`** — Enhance to return:
```json
{
  "categories": [
    {
      "id": "reconnaissance",
      "label": "Reconnaissance",
      "count": 3421,
      "severity_breakdown": {"critical": 12, "high": 89, "medium": 1847, "low": 1473},
      "trend": {"direction": "increasing", "percentage": 8},
      "sparkline": [120, 145, 132, 198, 167, 142, 155],
      "sub_categories": [
        {"id": "port_scan", "label": "Port Scanning", "count": 2103},
        {"id": "vuln_probe", "label": "Vulnerability Probing", "count": 842}
      ]
    }
  ]
}
```

### New Endpoints

**`GET /api/alerts/categories/[category]`** — Full detail for one category:
```json
{
  "category": { "id": "...", "label": "...", "description": "...", "mitre_tactic": "TA0043" },
  "stats": { "total": 3421, "unique_sources": 847, "unique_targets": 23, "affected_devices": 18 },
  "sub_categories": [...],
  "affected_devices": [...],
  "top_signatures": [...],
  "mitre_techniques": [
    { "id": "T1595.001", "name": "Active Scanning: IP Blocks", "count": 1204, "description": "..." }
  ]
}
```

**`GET /api/alerts/categories/[category]/timeline`** — Time-series for one category, bucketed by sub-category.

### Classifier Changes (`alert_intelligence.py`)

- Add 6 new category pattern matchers: `credential_abuse`, `geo_anomaly`, `encrypted_threats`, `iot_anomaly`, `dos`, `sensitive_data`
- Add sub-category classification within each parent category
- Add MITRE ATT&CK tactic/technique mapping dictionary
- Geo-anomaly: compare GeoIP country against device's historical country set
- IoT anomaly: compare behavior against 7-day baseline from existing engine

### No New Services Required

All detection uses existing data:
- Suricata alerts in OpenSearch (signature pattern matching)
- GeoIP enrichment (already in pipeline)
- Baseline engine (already in `alert_intelligence.py`)
- Zeek TLS/SSL logs (for encrypted threats)

## MITRE ATT&CK Mapping

| Category | Primary Tactic | Key Techniques |
|----------|---------------|----------------|
| Malware & C2 | TA0011: Command and Control | T1071, T1573, T1095 |
| Reconnaissance | TA0043: Reconnaissance | T1595, T1046, T1018 |
| Exploit Attempt | TA0002: Execution | T1190, T1203, T1068 |
| Data Exfiltration | TA0010: Exfiltration | T1048, T1041, T1567 |
| Credential Abuse | TA0006: Credential Access | T1110, T1078, T1133 |
| Lateral Movement | TA0008: Lateral Movement | T1021, T1210 |
| DoS | TA0040: Impact | T1498, T1499 |
| Policy Violation | — | — |
| Protocol Anomaly | TA0005: Defense Evasion | T1001, T1573 |
| Geo-Anomaly | — (behavioral) | — |
| IoT/Device Anomaly | — (behavioral) | — |
| Encrypted Threats | TA0005: Defense Evasion | T1573, T1071.001 |
| Sensitive Data | TA0009: Collection | T1557, T1040 |

## Research Sources

- [Suricata classification.config](https://github.com/OISF/suricata-verify/blob/master/etc/classification.config) — 30+ rule classtypes
- [MITRE ATT&CK Framework](https://attack.mitre.org/) — 14 tactics, 200+ techniques
- [Splunk ES Notable Events](https://dev.splunk.com/enterprise/docs/devtools/enterprisesecurity/notableeventsplunkes/) — Risk-based alerting
- [Zeek Notice Framework](https://docs.zeek.org/en/master/frameworks/notice.html) — Protocol-specific notices
- [Bitdefender 2025 IoT Report](https://www.bitdefender.com/en-us/blog/hotforsecurity/bitdefender-and-netgear-2025-iot-security-landscape-report-shows-alarming-rise-in-smart-home-threats) — 30 attacks/day per home
- [pfSense Security Monitoring](https://www.zenarmor.com/docs/network-security-tutorials/pfsense-security-monitoring) — Consumer appliance patterns
