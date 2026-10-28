# Homepage Stat Cards — Fix Data Accuracy & Add Interactivity

**Date:** 2026-03-12
**Status:** Approved

## Problems

1. **Stat cards not clickable** — All 5 homepage stat cards are plain `<div>` elements with no click handlers or navigation
2. **Connections/Alerts always show ~10k** — OpenSearch `hits.total.value` caps at 10,000 by default; queries lack `track_total_hits: true`
3. **Bandwidth possibly inflated** — Need `track_total_hits` to get accurate connection counts for sanity-checking; also audit query
4. **Devices count wrong** — Counts ALL unique RFC1918 source IPs from Zeek conn logs (includes stale/unleased IPs). Should count DHCP-leased devices only

## Solutions

### Fix 1: Add `track_total_hits: true` to daemon queries

**Files:** `daemon/api/traffic.py`, `daemon/api/alerts.py`

Add `"track_total_hits": true` to the OpenSearch query body in:
- `handle_traffic_summary()` — fixes connection count
- `handle_alerts_count()` — fixes alert count

### Fix 2: New DHCP device count endpoint

**File:** `daemon/api/devices.py` (new handler)

Create `handle_device_count()` at `GET /api/devices/count`:
- Query: `event.provider: "zeek"` + `event.dataset: "dhcp"` + time range filter
- Aggregation: `cardinality` on `zeek.dhcp.client_addr` (unique DHCP-leased IPs)
- Returns: `{ "count": N, "from": "...", "to": "..." }`
- Lightweight — no per-device enrichment, just a count

**File:** `web/src/lib/api/devices.ts` (new client function)

Add `getDeviceCount()` that calls `/api/devices/count`.

**File:** `web/src/routes/+page.svelte`

Replace `getDevices()` call with `getDeviceCount()` — avoids fetching the entire device list just for a count.

### Fix 3: Make stat cards clickable

**File:** `web/src/routes/+page.svelte`

Convert stat card `<div>` elements to `<a>` elements with `href`:

| Card | href |
|------|------|
| Total Bandwidth | `/logs` |
| Connections | `/logs` |
| Alerts | `/alerts` |
| System Health | `/infrastructure` |
| Devices | `/iot` |

Add hover styling via existing `.stat-card` pattern (cursor pointer, border highlight).

## Files Changed

| File | Change |
|------|--------|
| `daemon/api/traffic.py` | Add `track_total_hits: true` to summary query |
| `daemon/api/alerts.py` | Add `track_total_hits: true` to count query |
| `daemon/api/devices.py` | New `handle_device_count` endpoint + route registration |
| `web/src/lib/api/devices.ts` | New `getDeviceCount()` function |
| `web/src/routes/+page.svelte` | Clickable stat cards + use `getDeviceCount()` |
