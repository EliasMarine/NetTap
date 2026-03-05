# NetTap Web UI v2 — Complete Redesign

**Date:** 2026-03-05
**Status:** Approved
**Branch:** TBD (phase-4/webui-v2)

## Decision

Scrap the entire existing web UI and rebuild from scratch as a guided power-user SIEM tool. Keep SvelteKit framework and existing infrastructure (Docker, nginx, auth). Replace all pages, components, and styles.

## Context

The v1 UI was a consumer-friendly dashboard that showed summarized data through custom daemon API endpoints. It lacked:
- Raw log browsing (no way to see Zeek conn.log, dns.log, etc.)
- OpenSearch cluster visibility (health, indices, shards, templates)
- Logstash pipeline monitoring (throughput, errors, queue)
- Kibana Discover-style data exploration (search, filter, column picker)

The UI felt broken because it only showed aggregated summaries with no way to drill into the underlying data.

## Design Pillars

1. **Guided power-user** — full SIEM capabilities with plain-English tooltips, sensible defaults, and progressive disclosure. No dumbing down, but no jargon without explanation.
2. **Datadog/Grafana aesthetic** — dark background, colorful charts that pop, dense but readable data tables, strong use of color to convey meaning. Vibrant accents on dark canvas.
3. **Production-grade reliability** — every API endpoint works, every page loads, every error state is handled. No broken pages.

## Pages (7)

### 1. Home / Dashboard
Pre-built visualizations — the "Grafana dashboard" experience.
- Bandwidth over time (area chart, selectable intervals)
- Geographic map of external connections (GeoIP)
- Protocol distribution (donut/treemap)
- Top talkers (bar chart + table)
- Alert trend timeline
- Device count + new device detection
- System health summary strip
- Auto-refresh (configurable interval)

### 2. Log Explorer
The centerpiece — Kibana Discover-style log browser.
- **Log type picker**: dropdown/tabs for Zeek conn, dns, http, tls, files, dhcp, smtp, Suricata alerts, or "all"
- **Search bar**: full-text search with field-aware autocomplete
- **Time range**: preset (15m, 1h, 4h, 24h, 7d, 30d) + custom date picker
- **Column picker**: checkboxes for available fields, drag to reorder
- **Results table**: sortable columns, expandable rows showing raw JSON
- **Field statistics sidebar**: top values for selected field (like Kibana field stats)
- **Pagination**: cursor-based, configurable page size
- **Export**: CSV / JSON download
- **Plain-English tooltips**: hover any Zeek field name to see what it means

### 3. Devices
Device-centric network inventory.
- Table: IP, hostname, MAC, manufacturer, OS hint, first seen, last seen, total bytes, connection count, risk score
- Click row to drill into device detail: all logs for that IP, protocol breakdown, alert history, bandwidth timeline
- "New device" badge for first-seen < 24h
- Search/filter by IP, hostname, manufacturer

### 4. Alerts
Suricata IDS alerts with context.
- Table: timestamp, severity badge, signature (with plain-English tooltip), source IP, dest IP, protocol, category
- Severity filter (high/medium/low/info)
- Click to expand: full alert detail, related Zeek logs for same flow, PCAP link if available
- Alert trend chart (alerts over time, stacked by severity)
- Top triggered rules summary

### 5. Connections
Live/recent connection browser with PCAP drill-down.
- Table: timestamp, source, dest, protocol, service, duration, bytes, state
- TShark integration: click a connection to analyze its PCAP
- Filter by protocol, service, IP
- Connection state indicators (established, closed, rejected, timeout)

### 6. Infrastructure
Three-tab view for backend visibility.

**Tab: OpenSearch**
- Cluster health (green/yellow/red) with node count, data size
- Index table: name, doc count, size, status, creation date
- Shard allocation overview
- Index template list

**Tab: Logstash**
- Pipeline status (running/stopped)
- Throughput: events in/out per second, graph over time
- Error count + recent errors
- Queue depth and type
- JVM heap usage

**Tab: System**
- Container status table (name, image, state, uptime, health)
- Bridge health (br0 status, NICs, promisc mode, netfilter state)
- Storage: disk usage, SSD SMART health, retention policy status
- Updates: current versions, available updates

### 7. Settings
- Notification preferences
- Retention policy configuration
- Display preferences (refresh interval, timezone, default time range)
- About (versions, license info)

## Navigation

Left sidebar (collapsible):
- Home (dashboard icon)
- Log Explorer (search icon)
- Devices (monitor icon)
- Alerts (bell icon)
- Connections (link icon)
- Infrastructure (server icon)
- Settings (gear icon)

Top bar: NetTap logo, current page title, system status indicator, notification bell, refresh controls.

## New Daemon API Endpoints

### Log Search API
```
GET /api/logs/search
  ?log_type=zeek.conn|zeek.dns|zeek.http|zeek.tls|zeek.files|zeek.dhcp|zeek.smtp|suricata|all
  &query=<full-text search string>
  &fields=<comma-separated field list for projection>
  &from=<ISO datetime>
  &to=<ISO datetime>
  &size=<page size, default 50, max 500>
  &sort=<field:asc|desc>
  &search_after=<cursor for pagination>

GET /api/logs/fields/{log_type}
  Returns: field name, type, description, example value
```

### OpenSearch Cluster API
```
GET /api/opensearch/cluster
  Returns: health, status, node count, data nodes, active shards, relocating, initializing, unassigned

GET /api/opensearch/indices
  Returns: [{name, health, status, doc_count, size, creation_date}]

GET /api/opensearch/shards
  Returns: [{index, shard, state, node, size, docs}]

GET /api/opensearch/templates
  Returns: [{name, index_patterns, order, settings_summary}]
```

### Logstash Monitoring API
```
GET /api/logstash/stats
  Returns: {pipeline: {events_in, events_out, events_filtered}, jvm: {heap_used, heap_max}, process: {cpu_percent}}

GET /api/logstash/pipelines
  Returns: [{id, events: {in, out, filtered, duration_ms}, plugins: {inputs: [], filters: [], outputs: []}}]
```

## What Gets Deleted

All existing page components and routes will be replaced. The following are preserved:
- `web/src/lib/server/auth.ts` — auth middleware
- `web/src/lib/server/daemon.ts` — daemon proxy helper
- `web/src/lib/server/middleware.ts` — server middleware
- `web/package.json`, `svelte.config.js`, `vite.config.ts` — build config
- `web/src/app.html` — HTML shell
- Docker, nginx config unchanged

## Mockup Strategy

Each page gets an HTML mockup in `mockups/<page-name>/` for approval before implementation. Mockups use the frontend-design skill for production-grade visual design.

## Implementation Order

1. Design system (colors, typography, components) + layout shell
2. Dashboard (Home) — proves the chart/visualization stack works
3. Log Explorer — the centerpiece, requires new daemon endpoints
4. Infrastructure — requires new OpenSearch/Logstash daemon endpoints
5. Devices, Alerts, Connections — rebuild with new design system
6. Settings
7. Integration testing + polish
