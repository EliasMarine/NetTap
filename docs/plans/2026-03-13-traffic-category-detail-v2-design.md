# Traffic Category Detail Page v2 — Design Document

**Date:** 2026-03-13
**Branch:** `fix/traffic-category-duplicate-services` (extends existing fix)
**Mockup:** `mockups/traffic-category-detail-v2/index.html`

## Overview

Enhance the traffic category detail page (`/traffic/[category]`) from a basic table+sidebar layout to a full-featured analytics drill-down page with bandwidth charting, hostname resolution, search/filter, auto-refresh, service click-through filtering, and a traffic share column.

## Features

### 1. Bandwidth Over Time Chart
- Full-width `TimeSeriesChart` (existing component) showing category bandwidth over selected time range
- Dual series: Download (cyan) + Upload (purple) with gradient area fills
- **New daemon endpoint:** `GET /api/traffic/categories/{category}/bandwidth?from=&to=&interval=`
  - Filters by category's ASN set (reuses `_asn_filters_for_category()`)
  - Returns same shape as `/api/traffic/bandwidth` but scoped to category
  - Auto-selects interval: 1h→1m, 6h→5m, 24h→15m, 7d→1h, 30d→6h
- **New SvelteKit proxy:** `web/src/routes/api/traffic/categories/[category]/bandwidth/+server.ts`
- **New API client function:** `getCategoryBandwidth()` in `traffic.ts`

### 2. Device Hostname Resolution
- Modify `get_category_devices()` in `traffic_classifier.py` to resolve hostnames
- Uses existing `DeviceFingerprint.get_hostname_for_ip()` from `device_fingerprint.py`
- Queries `zeek.dns.answers` field to find most common domain resolving to each device IP
- Pass fingerprint service instance from `handle_category_detail()` in `traffic.py`
- Frontend already handles `hostname` field — just displays it when present

### 3. Traffic Share (%) Column
- API already returns `percent` field per device
- Add new column to table with mini progress bar + percentage value
- Sortable like all other columns

### 4. Download/Upload Split Bar
- Replace existing single-color inline bar with stacked DL/UL bar
- Cyan = download, Purple = upload, proportional widths
- Provides instant visual insight into traffic directionality per device

### 5. Search/Filter Input
- Client-side filter on the device table
- Filters by IP address or hostname (case-insensitive substring match)
- Debounced input (200ms) to avoid re-renders on every keystroke

### 6. Auto-Refresh Toggle
- Toggle button next to time range pills
- When active, re-fetches all data every 30 seconds
- Shows "Last updated Xs ago" in subtitle
- Persists state in component (not across page navigations)

### 7. Service Click-Through Filtering
- Clicking a service in Top Services sidebar filters device table
- Filter badge appears in table toolbar showing active service
- "Clear filter" link in sidebar footer
- **Implementation:** Client-side only — fetch all devices, filter by matching service ASNs
- **New daemon field:** Add `top_asns` array to each service in `get_category_services()` response so frontend can match devices

### 8. % of Network Stat Card
- 4th stat card showing what fraction of total network traffic this category represents
- Requires fetching total network bytes for the time range (reuse `getTrafficSummary()`)
- Calculated client-side: `category_bytes / total_network_bytes * 100`

### 9. Stat Card Trend Indicators
- Compare current period to previous period of same duration
- e.g., for 24h range: compare last 24h vs 24h before that
- Requires two API calls (current + previous) — done client-side
- Shows arrow + percentage change + color (green=up, red=down, neutral=stable)

## Files to Create/Modify

### Daemon (Python)
| File | Action | Description |
|------|--------|-------------|
| `daemon/services/traffic_classifier.py` | Modify | Add `get_category_bandwidth()`, add hostname resolution to `get_category_devices()`, add `connections` count to `get_category_services()` |
| `daemon/api/traffic.py` | Modify | Add `handle_category_bandwidth` endpoint, pass fingerprint to `get_category_devices()` |

### Web — API Layer
| File | Action | Description |
|------|--------|-------------|
| `web/src/routes/api/traffic/categories/[category]/bandwidth/+server.ts` | Create | SvelteKit proxy for category bandwidth |
| `web/src/lib/api/traffic.ts` | Modify | Add `getCategoryBandwidth()` function + types |

### Web — Page
| File | Action | Description |
|------|--------|-------------|
| `web/src/routes/traffic/[category]/+page.svelte` | Rewrite | Full page rewrite with all 9 features |

### Tests
| File | Action | Description |
|------|--------|-------------|
| `daemon/tests/test_category_bandwidth.py` | Create | Tests for new bandwidth endpoint |
| `web/src/routes/api/traffic/categories/[category]/bandwidth/+server.test.ts` | Create | Proxy endpoint test |
| `web/src/routes/traffic/[category]/category-detail.test.ts` | Create | Component interaction tests |

## Non-Goals
- Per-device sparklines (too many OpenSearch queries)
- Persistent auto-refresh state across navigations
- Server-side filtering by service (client-side is sufficient for <100 devices)

## Dependencies
- Existing `TimeSeriesChart.svelte` component
- Existing `DeviceFingerprint` service
- Existing `HorizontalBarList.svelte` component (for services sidebar — may replace with custom list for click-through behavior)
