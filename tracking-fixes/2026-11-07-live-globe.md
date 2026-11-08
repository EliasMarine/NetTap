# 2026-11-07 — The Live monitor globe (NET-207)

**Status:** merged to `main` as `f811e63f` (PR #220), and deployed on the G11 on 2026-11-08 (every deploy check passed). Plan approved by Codex in round 3 (`.codex-review/2026-11-07-2130-live-globe/`, git-ignored).

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

## Review fixes (PR #220)

- **/deep-review:** no findings.
- **/ponytail-review:** removed the engine's unused `stats()`/`refreshTheme()` and alert sums. `land.js` now uses `geometry.ts`'s `unwrapRing` instead of a second copy of the date-line rule.
- **Security** (nothing above LOW):
  - The WAN look-up follows no redirects.
  - Its failure log names only the error type. An undecodable reply's error carried the whole body, public IP included.
- **Python:**
  - An empty destination country counts as present, exactly as `country_filter`'s `exists` does.
  - The label drops control characters per part.
  - The file is fsynced before the rename.
  - The public-LAN-address limit is a `shortcut:` comment.
- **TypeScript:**
  - Esc is handled on the window. A drag on the globe left focus on `<body>`, so Esc did nothing. A new visual test drags, then presses Esc; it failed on the old handler.
  - A home or a poll that arrives while the shaders compile is applied once ready.
  - A lost GPU device or WebGL context falls back to the flat map.
  - A tap selects on touch screens.
  - The home has a loading state, and a failed read is retried with the next load.
  - Replies without a usable location are refused.
  - The coordinate fields drop `inputmode="decimal"`: iOS has no minus key on that keypad.
  - The Tab trap skips hidden controls.
  - A highlight can't stick after its list row is gone.
- **Left as they are:**
  - The home-location file handlers do their small file I/O on the event loop, as the excluded-IPs handlers next to them do.
  - No timeout on a renderer that stalls while starting. Settings › Display › Flat map is the way out.

## Deploy on the G11 (2026-11-08)

`scripts/remote/deploy-live-globe.sh` from `main`. Every check passed:
- Both containers healthy.
- `GET /api/settings/home-location` answers "not set yet".
- A latitude of 95 is refused (400).
- Dashboard rows carry `geo_ip`.
- A `geo=` that is neither end is refused (400).
- The built app has the globe and the location card.
- `/live` and `/settings` redirect to `/login`, and `/api/health` answers 200.

Of the newest 200 rows:
- **out:** 74 placed at the destination.
- **in:** all 50 placed at the source, which the old code could not place at all.
- **local:** 44 with no place, and 13 at the destination (6 of them IPv6).
- **unknown direction:** 19 at the destination.

Only `in` and `out` rows launch packets. The 13 local rows placed at the destination are the public-LAN-address case left to NET-208.

The G11 was on `feature/device-live-bandwidth` (NET-205, unmerged, CPU gate failed) and now runs `main`. That branch's empty `clsact` qdisc on `enp4s0` (0 filters) is still there. NET-205 redeploys its branch when its work resumes.

## Lessons

- The countries file has rings that jump from -180° to 180°. A canvas raster fills them as thin bands across the whole map unless they are unwrapped onto 0..360 and drawn twice.
- One rule for "which end is the place", expressible both in Python and as an OpenSearch query, kept the filter, the rows, the fallback lookup and the drawer in agreement without passing LAN subnets around.

## Next steps

- The owner sets the location (Settings › Network › Use my WAN location, then Save) and checks the globe on their Mac.
- Follow-ups not built:
  - Inbound places in `geo_arcs` (a source-geo aggregation). Today a country's count is destinations only, while its filter also matches inbound rows.
  - The home location file in `config_backup.py`.
  - Placing inbound rows whose LAN end has a public, geolocated address (IPv6, or a public WAN IP inline).
