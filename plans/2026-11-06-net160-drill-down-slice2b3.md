# Plan: Home's Devices card opens the Devices page over the same window (NET-160 slice 2b-3)
_Round 2 — revised after Codex round 2 (2 findings, both taken)_

## Goal

Home's Devices card counts devices over Home's window: 1h, 6h, 24h, 7d or 30d.
- That is LAN source IPs with at least 3 Zeek conn records in the window, minus excluded and skipped addresses: `GET /api/devices/count?from&to`, through `_lan_device_buckets`.
- The card links to `/iot`, which shows something else.
- The Devices page is fixed at the last 24 hours.

The owner decided (2026-11-06): **the Devices card opens the Devices page, with a new "seen in the last …" window matching the card.**

After this slice, choosing the card opens `/devices` over the card's exact `from`/`to`. There, **Total devices equals the card, and the All devices table lists exactly those devices**, one row per counted device, while there are at most 500.

## Approach

### A. Daemon: the device list counts the same devices as the count (`daemon/api/devices.py`)

1. **`handle_device_list` builds every sort from `_lan_device_buckets`,** as the `alerts` sort already does, instead of a `terms` aggregation (`size: limit`, `order` by a sub-aggregation). Then:
   - sort in Python by the requested field: `bytes` → `total_bytes.value`, `connections` → `doc_count`, `last_seen` / `first_seen` → `.value`, `alerts` → the alert counts;
   - break ties by bytes (largest first), then by IP, so the order is stable;
   - cut to `limit`.

   **Why:** today the list is a `terms` aggregation ordered by a sub-aggregation, with `size` = the limit.
   - Across shards, a terms list ordered by a sub-aggregation is approximate once a shard holds more keys than its `shard_size` (760 for size 500). A bucket can be left out, or its sum can be missing a shard's share.
   - Skipped addresses (`.255`, `.0`, `224.`) are removed after the cut, so the list can hold fewer rows than the count even below the limit.
   - A 7d or 30d window from Home makes both more likely.
   - `_lan_device_buckets` is the count's own helper: composite paging over every IP with the same filters, threshold and skip rules. One helper means the same membership.
2. **Alert counts for non-alert sorts** are fetched for the cut list only, as today. For the alerts sort, they cover every device, as today.
3. **`_lan_device_buckets` gains an optional `what` argument**, passed to `all_buckets(..., what=)`, so each page goes through `checked()`.
   - The list and the count pass it.
   - Both handlers catch `QueryFailed` and return 502 `{"error": "The device search was incomplete"}`, so a timed-out or partly failed search never reads as fewer devices.
   - The other callers (`devices_v2.py`, `risk.py`) don't pass it and behave as before.
4. **The list's reply answers the page's three device figures from its one set of buckets** (Codex R1 #1, #3):
   - `total`: the number of devices before the cut;
   - `as_of`: the daemon's clock when it answered, **as whole epoch milliseconds** (Codex R2 #1): `as_of_ms = time.time_ns() // 1_000_000`;
   - `online_since`: `as_of_ms − 300_000`, an integer too;
   - both serialised from those integers as ISO with exactly three fractional digits (`…T12:00:00.123Z`), so JavaScript's `Date.parse` reads the same instant;
   - `online_total`: devices before the cut whose `last_seen` (OpenSearch `max`, epoch ms) is at least `online_since`, both compared as integers.

   The count endpoint's `active_since` keeps its own parsing; this page no longer calls it.

   The daemon's clock is the data's clock, so no browser clock is involved. These are additive fields; existing readers ignore them.
5. **The alert-count searches are checked too** (Codex R1 #2). Each chunk's reply goes through `checked(reply, "device alert counts", ("by_ip", "by_dst"))`. It must also hold an `ips.buckets` list under each, or `QueryFailed` is raised.
   - A timed-out, partly failed or aggregation-less alert search returns 502. It never returns a list with alert counts of 0, or with the wrong devices picked for the alerts sort.
   - Each chunk's `terms` runs inside a filter on exactly that chunk with `size = len(chunk)`, so every key is returned. The counts are exact once the reply is complete.
6. **OLD CODE blocks** keep the `terms` query and its post-processing, with the reason.

### B. Web: the Devices page reads a window from the URL (`web/src/routes/devices/+page.svelte`)

1. **URL window.**
   - `range` is one of `1h`, `6h`, `24h`, `7d` or `30d`, Home's five; anything else means `24h`.
   - Or an exact `from`/`to` through the existing `customRange()` (`lib/utils/drilldown.ts`), shown as "Custom". A link carries `range` too, as the category pages do.
   - A `view` of `all` or `type` sets the starting tab. Without one the page keeps today's default: By type in mirror mode, All devices otherwise.
2. **A "Seen in the last" range control in the page head** (`Pills`, Home's five ranges, plus "Custom" when the URL brought `from`/`to`).
   - Choosing a range runs `goto('?range=…')`, keeping `view` and dropping `from` and `to`.
3. **The loader works out the window once per load.**
   - Custom: the URL's `from`/`to`. A range: `rangeWindow(hours)`, ending now.
   - **One device request answers the list, Total devices and Online now** (Codex R1 #1, #3): `getDevices({...win, sort, order, limit: 500})`.
     - Total devices = the reply's `total`. Online now = its `online_total`.
     - The two `getDeviceCount` calls on this page go, kept as OLD CODE. The count endpoint stays for Home.
   - **The table's status column reads the same reading.**
     - Online when `last_seen >= online_since`.
     - Idle when `last_seen >= as_of − 1 h`.
     - Offline otherwise.

     It no longer compares against `Date.now()` at render time, which drifted from the count by the request time and used a strict `<` at the boundary.
   - **A Custom window whose `to` is before `online_since`** shows Online now as "—", with the sub "This window ended before the last 5 minutes". A 0 there would read as "nothing is online".
   - New in 24 h stays a separate registry request. Its figure comes from the registry's `first_seen`, and its label names its own window.
   - **The page holds one atomic `loaded` state**: `{devices, total, online_total, online_since, as_of, from, to, words}`.
     - A successful reply replaces all of it at once.
     - A failed refresh of the same window keeps it, with the existing "couldn't refresh" note.
     - A window change clears it.

     So a list and a total from different readings never show together.
4. **The words shown are those of the loaded figures, not the URL.**
   - Each loaded result stores the window it answers: `{from, to}` from the reply, plus the range or Custom.
   - The KPI notes, the By type subtitle and its note, and Top consumer read from that.
   - When the window changes, the page clears the figures and shows loading, the same rule as the PR #190 review fix. A slow reply for the old window can't show under the new window's words; the existing `LoadGuard` generation drops it.
5. **The list's partial note** ("counts for the N busiest devices") uses the same reply's `total`: `devices.length < total`.
6. **The 30-second auto refresh** re-runs the same load. A range rolls forward; a Custom window stays fixed.
7. **OLD CODE comments** keep the fixed-24-hour loader lines and the "Last 24 hours" notes.

### C. Web: Home's card links (`web/src/routes/+page.svelte`)

1. **Keep the count reply whole** (Codex R1 #4): `deviceCountReply: DeviceCountResponse | null`, with `deviceCount = $derived(deviceCountReply?.count ?? null)`, so the existing readers don't change.
   - The guarded `settle` success sets it. `changeRange()` clears it, as it clears `deviceCount` today.
   - The figure and its link window can't come from different ranges.
2. **The Devices card's `href`:**
   - with a reply: `/devices?view=all&${windowQuery(deviceCountReply, range)}`;
   - before the reply for the current range, or after it failed: `/devices?view=all&range=${range}`.

   The old `href="/iot"` stays as an OLD CODE comment.
   - **Why `view=all`:** in mirror mode By type shows every registry device (up to 200), including ones not seen in the window. So its card count is not the Home figure. The All devices table is.

### D. Types and proxy

- `lib/api/devices.ts`: `DeviceListResponse` gains `total`, `online_total`, `online_since` and `as_of`. All four are required, so svelte-check catches a reader that misses them.
- `getDevices` already forwards `from` and `to`.
- **`/api/devices` has its own route**, `web/src/routes/api/devices/+server.ts`, not the catch-all. Today it calls `daemonFetch` with the default 10 s timeout (`lib/server/daemon.ts`).
  - It now passes an explicit module constant, `DEVICE_LIST_TIMEOUT_MS = 10_000`, unless the G11 measures otherwise (Codex R2 #2).
  - Its vitest asserts that `daemonFetch` gets that timeout. It reads the expected number from `DEVICE_LIST_TIMEOUT_MS=` in `scripts/remote/deploy-drill-down.sh`, so the route and the device gate can't drift apart.

### E. Device check: `scripts/remote/deploy-drill-down.sh` Step 7d

For settled windows ending 10 minutes ago, lasting 1h, 24h, 7d and 30d, the script calls the daemon (inside the daemon container, with the token) and checks:
1. **The count equals the list.** `count` = the list's `total`, and when `total` ≤ 500, it also equals the number of rows.
2. **One row against OpenSearch.** The first device's `connection_count` equals an OpenSearch `_count`, run from the opensearch container, of `event.provider: zeek`, `event.dataset: conn`, `source.ip: <ip>` over the window.
   - The device filter excludes only by `source.ip`, so for a listed IP that is the same set. The check rebuilds that rule on purpose instead of calling daemon code.
3. **Online now.** `online_total` equals the rows with `last_seen >= online_since` when `total` ≤ 500. That is the same reading's own rule, checked from outside the code.
4. **The proxy's path, timed with a pass mark** (Codex R1 #5, R2 #2). The 30-day list is requested from inside `nettap-web`, the proxy's own path to the daemon, with its mounted daemon token, using `node -e` in the container.
   - **The gate is 80% of `DEVICE_LIST_TIMEOUT_MS`,** which Step 7d declares (`DEVICE_LIST_TIMEOUT_MS=10000`) with a comment naming the route. The request must return 200 with JSON inside it, or the line is ✗.
   - If the G11 needs longer, the constant changes in both places in one commit. The route's vitest fails if they differ.
   - **Not done: a full authenticated round trip through nginx.** It needs a browser session, and the only script-side ways are the admin password or minting a JWT from the secret on the box. The second would leave an auth-bypass tool in a deploy script. The nettap-web leg is the one with the timeout. nginx adds a pass-through.
5. **The web route.** `/devices?view=all&range=24h` returns 200 through nginx: the login redirect or the page, not a 5xx.

Then the summary line.

## Key decisions & tradeoffs

- **One helper for the list and the count**, instead of raising the terms `shard_size`. It is exact by construction and already in use for the alerts sort. The cost is that the daemon sorts in Python: about 100 devices on the G11, and the 50,000-bucket cap of `all_buckets` far above a household.
- **One reading per page** (Codex R1 #1, #3): the list reply carries `total`, `online_total`, `online_since` and `as_of`, instead of separate count requests. Two requests a few milliseconds apart can disagree when Zeek logs a connection late, stamped with its start time. Section D (the owner's A/B) covers clicks between pages. Within one page, one search answers every device figure.
- **`view=all` on the Home link**, not a change to By type. By type is the registry view, keyed by MAC, with traffic merged from the list. Windowing the registry is a different feature.
- **Online now follows the page window**, so it stays "the table's Online rows". A past Custom window says so instead of 0.
- **The Devices page's ranges are Home's five.** It doesn't take the category pages' seven, so every Home window has an identical Devices window and nothing more.

## Risks / open questions

- **Performance of a 30-day composite** with a painless sum script per bucket. The terms path already ran the same script over the same records, so the work is similar. Step 7d prints the time. If the G11 is slow, the fallback is a `shortcut:` comment and a longer proxy timeout, not a return to `terms`.
- **The sort tie-break changes order** for equal bytes (now IP-ascending). No caller relies on the previous order.
- **`devices_v2.py` and `risk.py` keep the unchecked path.** That is noted for a later sweep; this slice doesn't widen into them.
- **The registry note on By type** says "traffic in the last …". On a 30-day window, an address reassigned to another device counts on both cards, as the existing NET-158 note says. That is unchanged.

## Verification plan

- **Daemon pytest** (`daemon/tests/test_devices_api.py`, mocks in the existing style):
  - For every sort (bytes, connections, last_seen, first_seen, alerts), the list's IPs equal the count's IPs, over composite replies spanning 2 pages. The data includes a device with exactly 3 records, one with 2, a `.255` address and an excluded address.
  - Each sort's order and tie-break are right; `limit` cuts after sorting; `total` is the number of devices before the cut.
  - A page with `timed_out: true` or failed shards gives 502 for both the list and the count.
  - **The alert-count stage:** a timed-out reply, failed shards, a missing `by_ip`/`by_dst`, or a missing `ips` each give 502, for a bytes sort and for the alerts sort.
  - Non-alert sorts query alert counts for the cut list only.
  - **`online_total` and `online_since`:** a device whose `last_seen` equals the cutoff counts; one a millisecond older doesn't. `as_of` comes from a patched clock.
- **Web vitest:**
  - **Devices page:** `?range=7d` calls the list and the count with a 7-day `from`/`to`; `?from&to` passes them exactly and shows Custom; a bad `range` falls back to 24h; `?view=all` opens All devices; choosing a pill calls `goto` with `range` and `view` and drops `from`/`to`.
  - **Stale figures:** the notes show the loaded window's words; a window change clears the figures, and a late reply for the old window is dropped.
  - **One reading:** Total devices = `total` and Online now = `online_total`, both from the list reply, and `getDeviceCount` isn't called.
  - **Status from the reply:** with `last_seen` exactly `online_since`, a row is Online even if the reply took 3 seconds (fake timers).
  - **Online now:** "—" for a past Custom window. The partial note uses `total`.
  - **Atomic state:** a failed same-window refresh keeps the last list and total together; a failed window change shows the error with neither.
  - **Home** (`home-drilldown-links.test.ts`):
    - the Devices card's `href` is `/devices?view=all&from=<reply.from>&to=<reply.to>&range=<range>`, and `/devices?view=all&range=…` before the reply;
    - after 24h loads, choosing 7d makes the card link to `range=7d` with no `from`/`to` while 7d is loading, and still after 7d's count fails.
- **Device list route vitest:** `daemonFetch` is called with `DEVICE_LIST_TIMEOUT_MS`, which equals the deploy script's value. The four new reply fields pass through unchanged.
- **Daemon clock precision:** with a patched clock of `12:00:00.123456Z`, `as_of` is `12:00:00.123Z` and `online_since` is `11:55:00.123Z`. A device with `last_seen` exactly `11:55:00.123` counts; one at `.122` doesn't. A web test reads the same pair and marks the same rows Online.
- **svelte-check, `npm run check:colors`, and `npm run test:visual`.** The devices layout visual test's fixture gains `total`, and the head control must not break the layout at five widths.
- **Swap check:** each new test fails against the HEAD version of its source file.
- **On the G11:** Step 7d all ✓, plus a by-hand look at Home → Devices for 1h and 30d.

## Rollback / migration safety

- No stored data or schema changes. Revert the PR to roll back.
- The new reply field is additive.
- The device-side check runs only in the deploy script.

## Observability

- `_lan_device_buckets` already logs a warning when `all_buckets` stops at its cap.
- `QueryFailed` is logged with the handler name before the 502.
- Step 7d prints the counts, the IP checked and the timings.

## Out of scope

- Windowing the registry or By type.
- `devices_v2.py` and `risk.py`.
- Section D (live vs snapshot lists).
- The New in 24 h card.
- Device detail pages.
