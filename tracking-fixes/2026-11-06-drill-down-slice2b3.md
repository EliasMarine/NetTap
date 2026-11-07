# 2026-11-06 — Home's Devices card opens the devices it counted (NET-160, slice 2b-3)

**Status:** built on `feature/drill-down-slice2b3`; PR pending. Plan: `plans/2026-11-06-net160-drill-down-slice2b3.md`. Codex approved it in round 3; the log is beside it.

## Problem

**Home's Devices card linked to the wrong page.** It counts devices over Home's window (1h, 6h, 24h, 7d or 30d), but it linked to `/iot`, which shows something else. The Devices page was fixed at the last 24 hours.

**The Devices page's figures came from three separate searches.** Total devices and Online now were their own `/api/devices/count` requests, and the list was a third.
- **The list could disagree with the count.** It was a `terms` aggregation ordered by a sub-aggregation, with `size` = the limit. Across shards that is approximate once a shard holds more IPs than its `shard_size`. Skipped addresses (`.255`, `.0`, `224.`) came off after the cut, so the list could hold fewer rows than the count even below the limit.
- **The searches were made at different moments.** A device's third connection could land in between.
- **The table's Online status used the browser's clock at render time,** with `<`, while the count used `>=` on a cutoff taken before the request.

**Incomplete searches read as smaller figures.**
- The device search was unchecked.
- A timed-out or partly failed alert-count search read as 0 alerts, and on the alerts sort it could pick the wrong devices.

## Fix: daemon (`daemon/api/devices.py`)

- **Every sort reads every device through `_lan_device_buckets`,** the count's own helper (composite paging, same filters, threshold and skip rules).
  - It then ranks in Python: by the sort, ties by bytes (largest first), then IP in numeric order, then cut to `limit`.
  - Alert counts are asked for the listed devices only, except on the alerts sort, which needs every device.
- **The reply adds four fields from that one reading:**
  - `total`: the devices before the cut;
  - `as_of`: the daemon's clock in whole epoch milliseconds;
  - `online_since`: `as_of` minus 5 minutes;
  - `online_total`: the devices whose `last_seen` is at or after `online_since`.

  Both times are written with exactly three fractional digits, so JavaScript reads the same instant.
- **`_lan_device_buckets` takes `what=`,** and the list and the count pass it.
  - Each alert-count reply goes through `checked()` plus an `ips.buckets` check.
  - An incomplete search returns 502 "The device search was incomplete".
- **OLD CODE blocks keep** the `terms` query, the sort map and the unchecked alert read.

## Fix: web

- **Devices page** (`web/src/routes/devices/+page.svelte`):
  - **The window comes from the URL:** `range` (Home's five) or an exact `from`/`to`, shown as Custom. A "Seen in the last" pill row sits in the head, and `view=all|type` sets the starting tab.
  - **One `getDevices` call** answers the table, Total devices (`total`) and Online now (`online_total`), held in one atomic reading.
    - A failed refresh of the same window keeps the reading.
    - A window change clears it, and a late reply for the old window is dropped.
  - **The status column reads `online_since` and `as_of`.**
  - **Online now shows "—"** for a Custom window that ended before the last 5 minutes.
  - **The notes and subtitles say the loaded window's words.**
- **Home** (`web/src/routes/+page.svelte`):
  - `deviceCountReply` keeps the figure and its window together, and `changeRange()` clears it.
  - The Devices card links to `/devices?view=all&from=…&to=…&range=…`, or `/devices?view=all&range=…` before the reply.
  - `view=all`, because By type lists every registry device, not the ones counted.
- **Route** (`web/src/routes/api/devices/+server.ts`): an explicit `DEVICE_LIST_TIMEOUT_MS = 10_000`. Its vitest reads the same value from `scripts/remote/deploy-drill-down.sh`.

## Device check: `scripts/remote/deploy-drill-down.sh` Step 7d

- **Settled windows of 1h, 24h, 7d and 30d** (each ends 10 minutes ago):
  - the count, the list's `total` and its rows are equal;
  - the first device's connections equal OpenSearch's own `_count` of its conn records.
- **Online now** equals the rows the same live reading marks Online.
- **The 30-day list via `nettap-web`'s own path to the daemon** must answer inside 80% of the route's timeout.
- **`/devices?view=all&range=24h` through nginx** must return the page or the login redirect.
- **Baseline before the change** (old `terms` list, via `nettap-web`): 2.5 s over 24h, 5.8 s over 30d, against an 8 s gate.

## Tests

- **Daemon:** 3,240 passed, 7 of them new, in `TestDeviceListOneReading`:
  - every sort lists the counted devices: an exactly-3-record device, an under-3 one and a broadcast address;
  - `total` across 2 composite pages before the cut;
  - the tie-break;
  - alert counts asked for the listed devices only;
  - the millisecond cutoff, with a microsecond clock and the boundary counted;
  - 502 for incomplete device and alert-count searches.

  The list tests moved to composite replies.
- **Web:** vitest 3,363 passed, svelte-check 0 errors, the colour gate clean, and `test:visual` 223 passed.
- **Swap check:** each new test fails on its file's HEAD version.

## Review gates

- **`/deep-review`:** no findings. The report is `security-reviews/feature-drill-down-slice2b3/security-review.md`.
- **`/ponytail-review`:** two findings, both fixed.
  - The list handler kept a `query` wrapper and a `bool_query` that only carried the per-device aggregations. They are now `device_aggs`, with the old lines kept as OLD CODE.
  - By type decided completeness with `devices.length < 500`, so a list of exactly 500 devices read as cut off. It now compares against the reading's `total`, with a test that fails on the old rule.

## Known limits

- **Home's card and the Devices page are separate readings.** A record landing between them can move the figure by one. Section D (the owner's A/B) covers every drill-down link.
- **By type stays the registry view.** It lists registry devices with this window's traffic, not only the devices counted.
- **`devices_v2.py` and `risk.py`** still call `_lan_device_buckets` without `what=`.

## Lessons

- **When a page shows a list and its total, one search should answer both.** Two requests a few milliseconds apart are two readings.
- **A cutoff shared between Python and JavaScript needs one precision.** Whole epoch milliseconds, serialised from the integer.
