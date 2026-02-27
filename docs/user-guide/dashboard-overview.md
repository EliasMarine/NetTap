# Dashboard Overview

The NetTap dashboard provides a real-time view of your network activity. This page explains each panel and how to use them.

---

## Layout

The dashboard is organized into rows of information, following a progressive disclosure pattern: big numbers first, details on drill-down.

### Header Bar

The top of the dashboard shows:

- **Network Overview** title and subtitle
- **Last updated** timestamp showing when data was last fetched
- **Auto-refresh toggle** --- enabled by default at 30-second intervals. Click to pause/resume.
- **Refresh button** --- manually trigger a data refresh

### Filter Bar

Below the header, the filter bar lets you narrow the dashboard to specific time ranges, devices, or protocols:

- **Time range** --- presets (1h, 6h, 24h, 7d, 30d) or custom date range
- **Device filter** --- filter by a specific IP address
- **Protocol filter** --- filter by protocol (TCP, UDP, DNS, HTTP, TLS, etc.)

---

## Row 1: Stat Cards

Five summary cards across the top provide at-a-glance metrics:

### Total Bandwidth (24h)

Shows the total bytes transferred across your network in the selected time period. Breaks down into inbound and outbound traffic below the main number.

A trend indicator (up/down arrow with percentage) compares to the previous equivalent time period. For example, if you're viewing 24 hours, the trend compares to the 24 hours before that.

### Connections (24h)

Total number of network connections observed. Shows the most common protocol below the count (e.g., "Top protocol: TLS").

### Alerts (24h)

Number of Suricata IDS detections in the selected period. The subtitle breaks down by severity: high, medium, and low. Click "View all" to go to the full [Alerts](alerts.md) page.

### System Health

Shows the overall health status of the NetTap system:

- **Healthy** (green) --- all systems operational
- **Degraded** (yellow) --- one or more subsystems have issues

Below the badge, it shows OpenSearch connectivity status.

### Devices

Count of unique devices (IP addresses) observed on your network. This tells you how many devices are actively generating traffic.

---

## Row 2: Charts

### Bandwidth Over Time

A time-series line chart showing bytes transferred per hour over the selected time range. Hover over any point to see the exact timestamp and value.

This chart is useful for identifying:

- **Usage patterns** --- when your network is busiest
- **Anomalies** --- unexpected spikes in traffic
- **Trends** --- whether bandwidth usage is increasing over time

### Protocol Distribution

A donut chart showing the breakdown of connections by protocol. The top 6 protocols are shown with distinct colors:

- Blue: primary protocol (usually TLS or DNS)
- Green, amber, red, purple, light blue: subsequent protocols
- Grey: "other" (aggregated remaining protocols)

---

## Row 2.5: Traffic Categories

A horizontal bar chart categorizing traffic by type:

- **Streaming** (Netflix, YouTube, Twitch)
- **Social Media** (Facebook, Instagram, TikTok)
- **Gaming** (Steam, Xbox Live, PlayStation Network)
- **Productivity** (Google Workspace, Microsoft 365)
- **Cloud** (AWS, Azure, Google Cloud)
- **Messaging** (WhatsApp, Slack, Discord)
- **News**, **Shopping**, **Email**, and more

Each bar shows the relative bandwidth consumed by that category. This section only appears when traffic category data is available.

---

## Row 3: Tables

### Top Talkers

A ranked table of the most active source IP addresses by bandwidth:

| Column | Description |
|---|---|
| **#** | Rank (1--10) |
| **Source IP** | The device's IP address (with hostname tooltip if available) |
| **Bandwidth** | Total bytes transferred |
| **Connections** | Number of connections from this device |

IP addresses are displayed as interactive elements --- hover for additional details, click to navigate to the device's detail page.

### Recent Alerts

The 10 most recent Suricata IDS detections:

| Column | Description |
|---|---|
| **Severity** | Color-coded badge: HIGH (red), MEDIUM (yellow), LOW (blue), INFO (grey) |
| **Signature** | The Suricata rule that triggered the alert |
| **Source** | Source IP address |
| **Dest** | Destination IP address |

Click any alert row to open the **Alert Detail Panel** --- a slide-out panel on the right showing full alert details including:

- Complete alert signature and description
- Source and destination IPs with port numbers
- Protocol details
- Timestamp
- The raw alert data

---

## Other Dashboard Pages

The navigation sidebar provides access to additional pages:

| Page | Path | Description |
|---|---|---|
| **Alerts** | `/alerts` | Full alert management with filtering, pagination, and detail view |
| **Devices** | `/devices` | Sortable, searchable device inventory |
| **Device Detail** | `/devices/{ip}` | Deep-dive into a specific device's activity |
| **Connections** | `/connections` | Connection log explorer |
| **Investigations** | `/investigations` | Bookmark and annotate suspicious activity |
| **Compliance** | `/compliance` | Security compliance posture overview |
| **Settings** | `/settings` | System configuration |
| **Notifications** | `/settings/notifications` | Email, webhook, and in-app alert configuration |
| **System** | `/system` | Hardware health, storage, service status |
| **Updates** | `/system/updates` | Software version inventory and update management |
| **Setup** | `/setup` | Re-run the setup wizard |
| **CyberChef** | `/system/cyberchef` | Data transformation and decoding tool |

---

## Tips

- **Loading skeletons** --- when data is loading, you will see animated placeholder shapes. This is normal during initial load or after changing filters.
- **Error banner** --- if the dashboard cannot reach the monitoring daemon, an orange warning banner appears at the top. Check that the `nettap-storage-daemon` container is running.
- **Empty states** --- "No traffic data available" or "No alerts detected. All clear." messages appear when there is no data for the selected time range. Give the system time to collect data after initial setup.
