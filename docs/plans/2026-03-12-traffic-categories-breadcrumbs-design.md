# Design: ASN-Based Traffic Categories + Sitewide Breadcrumbs

**Date:** 2026-03-12
**Status:** Approved

## Problem

1. **Traffic categories show wrong data** — `get_category_stats()` aggregates bytes by `network.protocol` (service field), so all HTTPS traffic gets lumped into "Web Browsing". No per-organization visibility.
2. **No drill-down** — clicking a traffic category does nothing. Users want Unifi-style per-device breakdown per category.
3. **No breadcrumb navigation** — nested pages (device detail, tool subpages, settings subpages) have no context trail. Users lose orientation.

## Approach

### Traffic Categories: ASN-Based Classification

Conn records in OpenSearch have `destination.as.full` (e.g., "AS2906 Netflix Inc") WITH bytes (`source.bytes` + `destination.bytes`) on the same document. This allows single-query aggregation of bytes per organization, then mapping ASN org names to traffic categories.

**Why ASN over domain/SNI:** Conn records contain bytes but no domain. SSL records have SNI (`tls.client.server_name`) but no bytes. They're separate documents linked by `zeek.uid` but OpenSearch can't join them. ASN lives on the conn record alongside bytes — single query, accurate data.

### Sitewide Breadcrumbs

A `Breadcrumb.svelte` component in the main layout, between the topbar and content area, driven by route metadata configuration. Shows `Home / Section / Page` trails for all nested routes.

---

## Feature 1: ASN-Based Traffic Category Drill-Down

### ASN → Category Mapping

A Python dict mapping ASN org substrings to categories. ~150+ entries covering major services:

| Category | Example ASNs |
|----------|-------------|
| Streaming | Netflix, YouTube/Google, Spotify, Twitch/Amazon, Disney, Hulu, Plex, Apple (partial) |
| Gaming | Valve, Riot Games, Epic Games, Xbox/Microsoft, PlayStation/Sony, Nintendo, EA, Activision Blizzard |
| Social | Meta/Facebook, Twitter/X, Snap, TikTok/ByteDance, Reddit, Pinterest, LinkedIn |
| Communication | Zoom, Microsoft (Teams/Skype), Slack, Discord, Telegram, WhatsApp (Meta) |
| Cloud | AWS, Azure, Google Cloud, DigitalOcean, Oracle Cloud, IBM Cloud, Linode/Akamai |
| Shopping | Amazon, Shopify, eBay, Walmart, Etsy, PayPal, Stripe |
| News | CNN, NYT, Washington Post, BBC, Reuters, AP |
| Ads & Tracking | DoubleClick/Google Ads, Meta Ads, Amazon Ads, TradeDesk, Criteo |
| Work & Productivity | Google (Workspace), Microsoft (Office), Atlassian, Notion, Salesforce, Dropbox |
| IoT & Smart Home | Ring (Amazon), Nest (Google), Philips Hue, ecobee, TP-Link, Tuya |
| Updates | Apple (Software Update), Microsoft (Windows Update), Ubuntu/Canonical |
| Security | Cloudflare, Quad9, OpenDNS/Cisco, Let's Encrypt, CrowdStrike, Palo Alto |
| CDN & Infrastructure | Akamai, Fastly, Cloudflare (CDN), Limelight, StackPath |
| DNS | Google DNS, Cloudflare DNS, Quad9, OpenDNS |

**Fallback:** ASNs not matching any rule go to "Other". Port-based fallback for traffic without ASN info (DNS on 53, NTP on 123, etc.).

### Backend Changes

**File: `daemon/services/traffic_classifier.py`**

Rewrite `get_category_stats()`:
1. Query conn records with `destination.as.full` aggregation (terms agg, top 500 ASNs)
2. Each bucket has `key` (ASN org string) and sub-agg `total_bytes` (sum of `source.bytes` + `destination.bytes`)
3. Map each ASN bucket to a category using substring matching
4. Aggregate bytes per category
5. Return sorted categories with byte totals

**New method: `get_category_devices(category, time_range)`**
1. Collect all ASN org substrings for the given category
2. Query conn records filtered by those ASNs
3. Aggregate by `source.ip` (device) with sub-aggs: total_bytes, download_bytes, upload_bytes, connection_count
4. Return per-device breakdown sorted by total bytes

**New method: `get_category_services(category, time_range)`**
1. Same ASN filter as above
2. Aggregate by `destination.as.full` to get top services within category
3. Return service name + bytes

### New API Endpoint

**`GET /api/traffic/categories/{category}`**

Query params: `range` (default "24h")

Response:
```json
{
  "category": "streaming",
  "label": "Streaming",
  "total_bytes": 19789432012,
  "device_count": 7,
  "connection_count": 84207,
  "devices": [
    {
      "ip": "192.168.1.205",
      "hostname": "Nanit Camera",
      "total_bytes": 8589934592,
      "download_bytes": 8277655552,
      "upload_bytes": 312279040,
      "connections": 31284,
      "percent": 43.4
    }
  ],
  "services": [
    { "name": "Netflix Inc", "bytes": 7549747200 },
    { "name": "Google LLC", "bytes": 5452595200 }
  ]
}
```

### Frontend: New Page `/traffic/[category]`

**File: `web/src/routes/traffic/[category]/+page.svelte`**

Matches the approved mockup:
- Breadcrumb: Home / Traffic Categories / {Category Name}
- Category header with icon, name, service list subtitle
- 4 stat cards: Total Bandwidth, Active Devices, Connections, Peak Rate
- Per-device breakdown table (sortable): Device name, IP, total data with bar, download, upload, connections
- Top Services sidebar with horizontal bars

### Frontend: Homepage Changes

**File: `web/src/routes/+page.svelte`**

Make category bars clickable → `href="/traffic/{category_key}"` navigation.

---

## Feature 2: Sitewide Breadcrumb Navigation

### Component: `Breadcrumb.svelte`

**File: `web/src/lib/components/Breadcrumb.svelte`**

A reactive component that reads `$page.url.pathname` and generates breadcrumb trail.

### Route Map Configuration

A static route map defining the breadcrumb hierarchy:

```typescript
const ROUTE_MAP: Record<string, { label: string; parent?: string }> = {
  '/': { label: 'Home' },
  '/logs': { label: 'Log Explorer' },
  '/devices': { label: 'Devices' },
  '/alerts': { label: 'Alerts' },
  '/connections': { label: 'Connections' },
  '/live': { label: 'Live Monitor' },
  '/bandwidth': { label: 'Bandwidth' },
  '/dns': { label: 'DNS Analytics' },
  '/iot': { label: 'IoT & LAN' },
  '/changelog': { label: 'Changelog' },
  '/certificates': { label: 'Certificates' },
  '/pcap': { label: 'PCAP Search' },
  '/tools': { label: 'Tools' },
  '/tools/dns-recon': { label: 'DNS Recon', parent: '/tools' },
  '/tools/ping': { label: 'Ping', parent: '/tools' },
  '/tools/traceroute': { label: 'Traceroute', parent: '/tools' },
  '/tools/ssl-cert': { label: 'SSL Cert', parent: '/tools' },
  '/tools/mac-lookup': { label: 'MAC Lookup', parent: '/tools' },
  '/tools/subnet-calc': { label: 'Subnet Calc', parent: '/tools' },
  '/tools/port-reference': { label: 'Port Reference', parent: '/tools' },
  '/tools/base64': { label: 'Base64', parent: '/tools' },
  '/tools/cyberchef': { label: 'CyberChef', parent: '/tools' },
  '/tools/tshark': { label: 'Tshark', parent: '/tools' },
  '/infrastructure': { label: 'Infrastructure' },
  '/settings': { label: 'Settings' },
  '/settings/notifications': { label: 'Notifications', parent: '/settings' },
  '/settings/backup': { label: 'Backup', parent: '/settings' },
  '/settings/suricata-rules': { label: 'Suricata Rules', parent: '/settings' },
  '/traffic': { label: 'Traffic Categories', parent: '/' },
};
```

### Dynamic Segments

For routes with dynamic params (`/devices/[ip]`, `/geoip/[ip]`, `/traffic/[category]`):
- Match by prefix (e.g., path starts with `/devices/` → parent is `/devices`)
- Display the param value as the last breadcrumb segment
- For IPs: show the IP address in monospace
- For categories: map slug to display name

### Layout Integration

**File: `web/src/routes/+layout.svelte`**

Insert `<Breadcrumb />` between topbar and content:
```html
<header class="topbar">...</header>
<Breadcrumb />
<main class="content">
  {@render children()}
</main>
```

### Styling

- Background: transparent (sits on `var(--bg-void)`)
- Padding: `var(--space-xs) var(--space-lg)` (compact, aligned with content padding)
- Font: `var(--text-sm)`, `var(--font-sans)`
- Inactive links: `var(--text-muted)`, hover → `var(--text-link)`
- Separator: `/` in `var(--text-dim)`
- Current page (last segment): `var(--text-secondary)`, no link
- Hidden on home page (`/`) — no breadcrumb needed
- Hidden on `/setup` and `/login` pages

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `daemon/services/traffic_classifier.py` | EDIT | Rewrite `get_category_stats()` to ASN-based, add `get_category_devices()`, `get_category_services()`, add ASN mapping table |
| `daemon/api/traffic.py` | EDIT | Add `/api/traffic/categories/{category}` endpoint |
| `web/src/lib/components/Breadcrumb.svelte` | CREATE | Sitewide breadcrumb component |
| `web/src/routes/+layout.svelte` | EDIT | Add `<Breadcrumb />` between topbar and content |
| `web/src/routes/traffic/[category]/+page.svelte` | CREATE | Category detail page (per-device breakdown) |
| `web/src/routes/traffic/[category]/+page.ts` | CREATE | Load function to fetch category data |
| `web/src/routes/+page.svelte` | EDIT | Make category bars clickable with href |
| `web/src/lib/api/traffic.ts` | EDIT | Add `getCategoryDetail()` API client function |

## Verification

1. Navigate to homepage → category bars are clickable
2. Click "Streaming" → navigates to `/traffic/streaming` with per-device data
3. Breadcrumbs show on all nested pages: `/devices/192.168.1.5` → "Home / Devices / 192.168.1.5"
4. Breadcrumbs show on tool pages: `/tools/dns-recon` → "Home / Tools / DNS Recon"
5. Breadcrumbs hidden on `/`, `/login`, `/setup`
6. Category page shows accurate byte data (not 25x inflated)
7. All tests pass: `npx vitest run` and `npx svelte-check`
