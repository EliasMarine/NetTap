# Traffic Analysis

NetTap captures and analyzes all network traffic passing through the bridge using Zeek. This page explains the traffic analysis features and how to investigate network activity.

---

## Data Sources

### Zeek Metadata

Zeek generates structured JSON logs for every connection and protocol interaction:

| Log Type | What It Captures |
|---|---|
| **conn** | Every TCP/UDP connection: source, destination, ports, duration, bytes transferred |
| **dns** | DNS queries and responses (what domains your devices look up) |
| **http** | HTTP requests and responses (method, URL, status code, user agent) |
| **ssl/tls** | TLS handshakes (server name, certificate details, JA3 fingerprints) |
| **dhcp** | DHCP leases (which devices received IP addresses) |
| **smtp** | Email metadata (sender, recipient, subject) |
| **files** | File transfers detected in any protocol (hashes, MIME types, sizes) |

!!! info "No payload inspection"
    NetTap does not decrypt or inspect encrypted traffic content. For TLS connections, Zeek records the handshake metadata (server name, certificate, JA3) but not the encrypted payload.

---

## Device Inventory

The Devices page (`/devices`) provides a sortable, searchable table of all discovered network devices.

### Device Table Columns

| Column | Description |
|---|---|
| **IP Address** | The device's IP address on your network |
| **Hostname** | Reverse-DNS or DHCP hostname, if available |
| **Manufacturer** | OUI lookup from the device's MAC address |
| **Connections** | Total connection count |
| **Bandwidth** | Total bytes transferred |
| **Last Seen** | When the device was last active |

### Searching and Sorting

- **Search bar** --- filter by IP address, hostname, or manufacturer name
- **Column sorting** --- click any column header to sort ascending/descending
- **Auto-refresh** --- toggle 30-second refresh to see new devices appear

### Device Detail Page

Click any device row to navigate to `/devices/{ip}` for a deep-dive into that device's activity:

- Connection history over time
- Top destinations contacted
- Protocol breakdown
- Alert history for this device
- Risk score

---

## Connections Page

The Connections page (`/connections`) provides a log explorer for individual network connections. Each connection record includes:

- Source and destination IP + port
- Protocol
- Duration
- Bytes in/out
- Connection state (established, closed, reset, etc.)
- Timestamp

---

## Traffic Categories

NetTap classifies traffic into human-readable categories based on destination hostnames and IP reputation data:

| Category | Examples |
|---|---|
| **Streaming** | Netflix, YouTube, Twitch, Spotify |
| **Social Media** | Facebook, Instagram, TikTok, Twitter/X |
| **Gaming** | Steam, Xbox Live, PlayStation Network, Epic Games |
| **Productivity** | Google Workspace, Microsoft 365, Notion |
| **Cloud** | AWS, Azure, Google Cloud, Cloudflare |
| **Messaging** | WhatsApp, Slack, Discord, Telegram |
| **News** | CNN, BBC, Reddit, Hacker News |
| **Shopping** | Amazon, eBay, Shopify stores |
| **Email** | Gmail, Outlook, ProtonMail |

The dashboard home page shows a horizontal bar chart of bandwidth by category.

---

## Natural Language Search

NetTap includes a natural language search feature that lets you query your network data in plain English:

```
Show me all DNS queries to suspicious domains in the last 24 hours
```

```
Which device transferred the most data yesterday?
```

```
Connections from 192.168.1.42 to external IPs last week
```

The search parser converts your query into an OpenSearch query and returns matching results.

---

## Investigations

The Investigations page (`/investigations`) lets you bookmark and annotate suspicious activity for later review:

1. While viewing an alert, device, or connection --- click "Investigate"
2. Add notes and tags to the investigation
3. Review all open investigations from the Investigations page
4. Mark investigations as resolved when done

This is useful for tracking ongoing security concerns or documenting activity for later review.

---

## Risk Scores

Each device receives a risk score from 0 (safe) to 100 (high risk) based on:

- Number and severity of IDS alerts associated with the device
- Communication with known-bad IP addresses or domains
- Unusual traffic patterns or volume
- Protocol anomalies

Risk scores update periodically as new data arrives. View risk scores on the Device Inventory page or individual Device Detail pages.

---

## GeoIP Mapping

External IP addresses are enriched with geographic location data (country, city, ASN) using MaxMind GeoLite2 databases. This helps you understand:

- **Where your traffic goes** --- which countries and networks your devices communicate with
- **Unusual destinations** --- connections to unexpected geographic regions
- **ISP/hosting provider identification** --- via ASN lookups
