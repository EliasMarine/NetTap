# 2026-11-07 — The Live monitor globe (NET-207)

**Status:** built on `feature/live-globe`; PR, merge and G11 deploy pending. Plan approved by Codex in round 3 (`.codex-review/2026-11-07-2130-live-globe/`, git-ignored).

## Problem

The old Live map showed packets flying across the earth. The 2026-11 redesign replaced it with a flat dot map, with no home and no motion. The owner asked for the flying packets back, with a bigger space for the map (mockup: Design canvas LB3G1AwvB15dP1jmqFrLfD), and decided:

1. The home location is set in Settings, and a WAN GeoIP lookup can fill it.
2. The remote end of inbound connections is geolocated.
3. The existing flat map stays as the fallback, both automatically and as a choice for lower machine load.

## Root cause

- **No home to fly from.** The redesign removed the old made-up home, a centre of the US (PLAN.md §5.4).
- **Inbound rows had no place.** The live API read only `destination.geo`, and an inbound row's destination is a LAN address.

## Fix

### Daemon

- **`services/home_location.py`, `api/home_location.py`:**
  - `GET`, `PUT` and `DELETE /api/settings/home-location`: `{lat, lon, label}` validated, stored atomically in `/opt/nettap/data/home_location.json`.
  - `POST /api/settings/home-location/wan-lookup`: one HTTPS call to `ipinfo.io/json` (5 s, 16 KB cap). The reply is validated as untrusted, and the result is returned as a suggestion, never saved.
  - The G11's daemon has no GeoLite2 database, and the capture never sees the WAN address, so only an outside service can place it. The design system's rule "outside look-ups run on click" holds.
- **`services/live_connections.py`:**
  - One rule for a row's place: the destination's when it has a country, else the source's.
  - `_format_connection` applies it and adds `geo_ip`, the address the place belongs to.
  - `country_filter()` expresses the same rule in OpenSearch, so a filtered row's country always equals the filter.
- **`api/live.py`:**
  - The GeoIP fallback looks up the row's own `geo_ip`, so endpoints never mix.
  - `GET /api/live/connection/detail` takes `geo=`, which must be `src` or `dst` (default `dst`), so the drawer locates the same end as the row.

### Web

- **`components/ui/charts/Globe.svelte` + `charts/globe/`** (the mockup's engine, ported):
  - three.js 0.186 WebGPURenderer, which falls back to WebGL 2 by itself, with TSL materials and a 4,096-slot GPU packet ring.
  - The land mask is drawn from the same `countries-110m.geojson` DotMap uses. Rings that cross the date line are unwrapped first.
  - three loads only on `/live`, through a dynamic import.
  - On unmount it destroys the engine. If the renderer or the outlines fail, it calls `onfail` once.
- **`components/live/LiveGlobeCard.svelte`:**
  - Full-width card: the globe, or DotMap when this browser chose the flat map or the globe failed.
  - A Top destinations list doubles as the country filter.
  - Notices: no home set, home unreadable, no 3D available.
  - Expand opens a full-window modal: the rest of the page is inert, focus moves to Close, Tab wraps, and Esc closes and gives focus back.
- **`routes/live/+page.svelte`:**
  - Loads the home once.
  - Passes each poll's new rows to the globe, which launches packets for them.
  - Puts an inbound row's country beside its source.
  - Stacks the side cards beside the feed.
- **Settings:**
  - Network › Network location card (`LocationCard.svelte`).
  - Display › Live map (globe, or flat "lighter on this computer"), saved beside the default range.
  - `?tab=` opens a tab.

## Verification (local)

- **Daemon:** pytest 4,022 passed, 4 skipped, 0 failures (baseline 0 failures; +63 tests).
- **Web:**
  - Vitest 4,123 passed.
  - svelte-check: 0 errors (the one new warning was fixed).
  - `check:colors` clean, `check:e2e` clean.
  - Visual tests for `/live`:
    - The globe really starts (data-backend WebGPU or WebGL 2) and moves.
    - The chosen flat map shows its home ring, arcs and pause.
    - Forced fallback without WebGPU or WebGL 2.

## Lessons

- The countries file has rings that jump from -180° to 180°. A canvas raster fills them as thin bands across the whole map unless they are unwrapped onto 0..360 and drawn twice.
- One rule for "which end is the place", expressible both in Python and as an OpenSearch query, kept the filter, the rows, the fallback lookup and the drawer in agreement without passing LAN subnets around.

## Next steps

- Deploy with `scripts/remote/deploy-live-globe.sh` and check on the owner's Mac.
- Follow-ups not built: an inbound places list (it needs source-geo aggregations), and backing up the home location file.
