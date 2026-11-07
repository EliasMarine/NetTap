# Same look on every page, charts that fill their cards, reliable and faster pages

Linear: NET-192. Plan: reviewed with Codex over 4 rounds (`.codex-review/2026-11-06-ui-consistency-speed/`, local).
Four PRs: 1 charts and visible breakage (web), 2 reliability (daemon + proxy), 3 speed, 4 consistency.

## Why

The owner (2026-11-06): the UI should look the same throughout, every chart should fill its card ("I think the DNS chart doesn't"), the app should work reliably, and slow pages should load faster where feasible.

Audits on the fixture build (1440 and 1024 px) and on the G11 (real data, cold):

- Seven "over time" cards had no `col`, so the AreaChart didn't grow: DNS left 223 px under its chart, Alerts 142 px.
- The IoT trust ring was squashed to 58 px; Live's protocol donut left 303 px empty; Compliance's overall card 177 px.
- The Home gauge printed "214,000" into its tick ring; the sidebar badge read "214000".
- Map labels overlapped; Threats split IP addresses mid-value; Infrastructure's "Not measured" wrapped at figure size.
- At 1024 px, 36 rows on 26 pages held one half-width card next to a hole.
- Speed (G11): Threats report ~70 s at 7 days (beaconing 65 s), reverse DNS 20 s, certificates 14.7 s, connections stats 14.4 s cold, risk scores 11.2 s cold.
- About 86 daemon routes ran synchronous OpenSearch work on the event loop; the client re-sent a timed-out request 3 times (up to 2 minutes per call).

## PR 1: charts fill their cards, and the visible breakage (web)

### What changed

- **`col` on the seven AreaChart cards** (DNS, Alerts, PCAP, Address, Domain, Alerts category, Suricata rule), so the chart grows to the card's height.
- **Ring** keeps its 128 px in a flex row (`svg { flex: none }`).
- **Live's protocol donut** fills its card: a11y.css correction 9 stacks the donut above its legend in a `col` card and lets its box take the free height; the svg covers the box and its viewBox keeps the ring round.
- **Compliance overall** uses the system `.trust-top` plus a score row per category (no custom centred layout). **Alerts** `.threat-top` is the system `.trust-top`.
- **`fitCount`** (`lib/utils/drilldown.ts`): exact below 100,000, "214K" above. Used by the gauge centre and the sidebar badge; both keep the exact figure in their accessible label. en-US compact notation, because en-GB writes "1.3m".
- **Map labels** (`mapLabels` in `geometry.ts`): busiest first, a label whose estimated box overlaps one already placed is left off; the dot and tooltip stay.
- **Threats** investigation facts break a value only when it can't fit on its own line (`overflow-wrap: break-word`).
- **Connections "Session volume"** is a `Card` with `CardState` for loading, empty and failed; y labels have thousands separators; the last time label is anchored inside the chart.
- **Infrastructure**: the Latency KPI shows "—" with the reason in its sub; the KPI row comes before the Capture pipeline card (page recipe).
- **a11y.css correction 8**: at 1100 px and below, the last half-width card of a run of one, three or five takes the full row. 1024 px holes: 37 → 1 (Compliance's run of seven category cards), no new holes.
- **`e2e/visual/chart-fill.visual.ts`**: on every populated route at 1440 and 1024, a card holding an AreaChart or a Donut leaves ≤ 24 px under its content and nothing overflows; a col card's donut svg covers its box; no Ring under 128 px.

### Dead ends

- **First version of correction 8 (`.c-8 + .c-4, .c-4:has(+ .c-8)`)** opened new holes on Home, device detail and Log Explorer: a c-4 after a c-8 is often the first of a run that already paired up. Measured per variant across all routes before settling on the odd-run rule.
- **The device page's `.stack`** spans 12 at 1100 px through the system's own rule (bundle.css:424), invisible to class-based selectors; it is counted as full-width in correction 8.

### Tests

- Vitest: 3,469 passed (new: `fitCount`, `mapLabels`, SessionTimeline separators and last-label anchor, the Infrastructure latency dash).
- svelte-check: 0 errors (2 warnings, both pre-existing in untouched files). `check:colors` clean. `check:e2e` clean.
- `test:visual`: 271 passed, 49 skipped. chart-fill: 48 passed.
- Swap check: with DNS `col`, Live `col` and Ring `flex: none` reverted, chart-fill fails with the audit's numbers (DNS 223 px, Live 303 px, IoT ring 58 px, Compliance ring 78 px).
- Gates: `/ponytail-review` (one finding, the correction 8 holes, fixed), `/deep-review` (no findings, `security-reviews/feature-ui-consistency-speed/`).
- G11: deployed with `deploy-ui-charts.sh` from the branch (web healthy, corrections 8 and 9 in the build, sign-in 200). Merged as #199 (`fdafbba`); the device is back on `main`.

### Left for PR 4

- The Home Alerts KPI shows "214.0K" (`formatCompactNumber`) and its sub "9000 high, 47000 med" has no separators.
- Live's feed times and SessionTimeline's x labels use US formats ("11:35:42 PM", "11/06 22:00").

## PR 2: the daemon keeps answering while pages load (daemon + proxy)

### What changed

- **OpenSearch client** (`storage/manager.py`): `retry_on_timeout: False` (a timed-out search was sent 3 more times, up to 2 minutes per call) and `pool_maxsize: 16`.
- **Route work runs off the request loop** (`api/offload.py`):
  - 67 sync route handlers are `@in_thread`.
  - 34 blocking calls inside async handlers go through `run_blocking`. Those are logs, connections stats, the threat report and beaconing, the OpenSearch cluster page, the device count, the packets summary, PCAP search and download, the live dashboard, risk scores, and the storage, SMART and ILM routes.
  - Both use a dedicated 8-thread route pool. asyncio's default pool stays free for drill-downs, bridge-health sysfs reads, the Internet DNS check, DHCP probes, notification sends, update copies and aiohttp's resolver.
  - The ILM retry (a background task) and IoTMonitor's own one-thread executor are unchanged. The threat report's investigation fan-out runs on the report thread's own loop, so it is left alone to avoid nesting route-pool jobs.
- **Public lookups are capped** (security review, Medium):
  - Reverse DNS, WHOIS and MAC lookup are reachable without a login (NET-193 removes that). They run on 2 threads of their own with at most 2 waiting; a fifth answers 503 "Lookups are busy. Try again in a moment." at once.
  - Before this, they shared the default pool and could hold up everything on it.
- **Shared state is safe from threads:**
  - The threat-intel cache, the device baseline and the alert files use `write_file_atomic` (temp file + `os.replace`).
  - The threat-intel transaction (load → merge → save) holds `CACHE_LOCK` for milliseconds. The OpenSearch scan (`scan_suricata`) runs before it, with no lock, so an address drill-down never waits behind a 30 s page of the scan.
  - The acknowledge and suppress handlers run on the loop with no `await` inside, so they need no lock. The locks added for them were removed after review.
- **SMTP** sends in a thread with `timeout=10`. `smart_loop`, PCAP file walks and update copies are threaded too.
- **Rollback** (`update_executor._swap_in`): the GeoIP and Suricata-rules rollbacks copy the backup to a temp file beside the target and `os.replace` it in. Rewriting the live `.mmdb` in place while threads have it memory-mapped can SIGBUS the daemon (security review, Low).
- **Web proxy:** cold reads get time to answer. Connections and stats, risk/scores and devices get 30 s; WHOIS gets 25 s.
- **Not done:** there is no daemon-side gate on concurrent searches. OpenSearch's search pool (queue 1,000) is the limit.
- **Accepted shortcut:** when the proxy gives up, the daemon's thread finishes its work anyway.

### Measured on the G11 before PR 2 (main's daemon, 2026-11-07)

- With five Home pages loading at once (75 calls), `/api/health` answered only 4 times in about 6 s, and its slowest answer took 2.79 s. The request loop was blocked by OpenSearch calls.

### Measured on the G11 after PR 2 (`deploy-daemon-reliability.sh`, 2026-11-07)

- **Same check as before** (the health watcher shares a process with the 75 load threads): health's slowest answer was 1.20 s cold (9 answers) and 1.00 s warm (18 answers), against 2.79 s (4 answers) on main. No page call failed; OpenSearch rejected 0 searches.
- **Health watcher in its own process:** in the first version, the watcher's timings included waiting for its own process's GIL behind the 75 client threads. Measured from a separate process, the slowest answer was 0.65 s and 0.10 s and the median 0.01 s, during five Home loads. `verify_event_loop.py` now runs the watcher this way.
- **Figures:** split invariance passed (88 same, 2 moving). Page figures matched OpenSearch for DNS, traffic, connections, certificates, security posture and IoT. No daemon errors since the restart.
- **Two stale checks, not PR 2:**
  - `verify-figures.sh` "alert total" compares raw alerts with `/api/alerts/count`. Since #197 (NET-191 slice 1) that endpoint counts by ET severity and sets the .44 activity apart: 17 counted against 2,645 raw.
  - `verify_device_figures.py` expects a device's top destinations in connection order. NET-158 sorts them by bytes, which gave 67 "not sorted" and "left out" lines.
  - Both checks are filed as a follow-up.

### Tests

- Daemon:
  - 3,532 passed, 3 skipped. `ruff check` and `ruff format --check` are clean.
  - New: `test_health_while_blocked.py`. Health answers while every offloaded route is blocked. It also covers the route pool vs the default pool, the lookup cap and 503, and a guard that fails if a default-pool call appears in `daemon/api` outside `drilldown_runner` and the ILM retry.
  - New: `test_shared_state_threads.py`.
  - Updated: the threat-intel transaction tests now prove the drill-down's load doesn't wait for a scan.
  - Rollback test: a reader that has the database memory-mapped keeps the old bytes.
  - Each new test fails on the old code.
- Device check: `scripts/remote/verify_event_loop.py`, run by `deploy-daemon-reliability.sh`. Five Home pages load at once, twice (cold, then warm). It requires `/api/health` under 1 s, no failed page calls and no OpenSearch search rejections. Then it runs `verify-split-invariance`, `verify-device-figures` and `verify-figures`.

### Reviews

- **Security (security-engineer):** no Critical or High.
  - Fixed: the Medium (public lookups could starve the shared pool) and the Low (in-place rollback copy).
  - Noted: `CACHE_LOCK` was held across the scan; fixed.
- **Python/over-engineering:** verdict Ship.
  - Should-fix items, all done: a dedicated route pool; the lock split; deleting the two loop-only locks.
- **Pre-existing, not changed here:** the tshark `/tmp/nettap_merged.pcap` race, and prune running at the same time as the storage cycle.

## PR 3: speed (daemon + web), branch `feature/net192-speed`

First run: parts 1a (measurement), 2 (beaconing in the background) and 3 (reverse DNS and WHOIS). Part 1b (fix the dominant query in each slow handler) waits for the G11 timings.

### What changed

- **Measurement (1a):**
  - `NETTAP_QUERY_TIMING=1` (compose default 0) gives every daemon client a transport (`storage/query_timing.py`, wired in `StorageManager._client_kwargs`) that logs one INFO line per OpenSearch request:
    `query-timing caller=<module>.<function>:<line> POST _search index=arkime_sessions3-* took_ms=<OpenSearch took> wall_ms=<wall> outcome=ok|error`
  - The caller is the first frame outside opensearch-py and `daemon/storage`. Document ids are never logged. An exact-terms re-send logs its own line.
  - `scripts/remote/deploy-speed-timing.sh` restarts the daemon with timing on and the background scan off, runs `verify_page_speed.py pages` (cold, fresh `to`, one call at a time), prints the 60 slowest requests and the total per query site, then restarts the daemon normally and runs `verify_page_speed.py snapshot`.
- **Beaconing in the background (2)** (`services/beacon_snapshots.py`):
  - A task started in `on_startup` and cancelled in `on_cleanup` rescans 24h and 7d every 15 min and 30d hourly, one scan at a time, each one `run_blocking` call. It logs `beacon-snapshot window=… duration_s=… beacons=… outcome=…` per run.
  - Only a complete scan is published. A bucket-cap scan keeps the previous rows as `stale` (`last_error: "scan hit the bucket cap"`), or `failed` with none.
  - `/api/threats/report` and `/api/threats/beaconing` take `?snapshot=24h|7d|30d` and return `beaconing_snapshot` (`state`, `computed_at`, `last_success_at`, `last_error`, scanned `from`/`to`). An explicit from/to is always live; any other `snapshot` value is a 400.
  - `NETTAP_BEACON_BACKGROUND=0` turns the task off; `snapshot=` is then live, as before.
  - Web: `threatRequest(range)` maps 24h/7d/30d to `snapshot`, 1h/6h to live bounds. The KPI shows "—" while pending or failed; the brief says "no beaconing" only after a finished check; the card shows loading, error, stale (rows plus a warn notice) and "checked <time>"; a live partial scan shows "Partial scan". While pending the page re-asks every 20 s for at most 10 min.
- **Reverse DNS and WHOIS (3)** (`api/lookup.py`, `services/ttl_cache.py`): on PR 2's lookup pool and 503 cap, one lookup per IP at a time, 6 s in all (`timed_out: true` and no name past that; the reverse name stands if the forward check fails), and a 2,048-entry LRU + TTL cache (name 1 h, no name or timeout 5 min, WHOIS 24 h). `RES_OPTIONS="timeout:1 attempts:2"` in the daemon's environment. The address and DNS lookup pages say "No reverse DNS name (lookup timed out)".

### Tests

- Daemon: 3,581 passed, 3 skipped (main: 3,532). New: `test_query_timing.py`, `test_beacon_snapshots.py`, `test_ttl_cache.py`, `test_lookup_cache.py`. `conftest.py` turns the background scan off for apps built in tests.
- Web: 3,735 passed. New: `threats-beaconing.test.ts`, `lookup/dns/[ip]/dns-result.test.ts`, `threatRequest` tests, an address-page timeout test.
- Swap checks: the partial-scan, report-skips-live-check, single-flight and 6 s bound tests fail with the old logic; every new web test fails on main's pages.

### Measured on the G11

- Pending: `BRANCH=feature/net192-speed bash scripts/remote/deploy-speed-timing.sh`.
- Update: the timing run passed (`aa42bc29` runs the timed restart through `scripts/remote/speed-timing.compose.yml`, because the G11's sudo rule has no SETENV). The background snapshot took the Threats 7d report from 72 s to 3.3 s; warm reverse DNS answers in 0.00 s.

### 1b: the measured fixes

**connections/stats, 13.65 s at 7d.** Two requests from `traffic.py:1078` in a row, 7.5 s then 6.2 s: `top_destinations` has more than 10k terms per shard (`doc_count_error_upper_bound` -1), so the exact-terms client re-sends at shard size 100k. Read-only variants at shard 100k, request cache off, two runs each (ms):

| Variant | Run 1 | Run 2 |
|---|---|---|
| Painless sum, asn/geo kept (as it was) | 6,093 | 7,265 |
| field sum, asn/geo kept | 7,281 | 6,525 |
| Painless sum, no asn/geo | 2,146 | 1,943 |
| field sum, no asn/geo | 1,190 | 1,425 |

All four gave the identical top 10 sources and destinations, so the `asn` and `geo` terms under every destination bucket dominate.

- Fix: `top_destinations` keeps only `total_bytes`. One follow-up search looks up `asn` and `geo` for the 10 winners: the same window and conn filters, `destination.ip` in the winners, and terms `destination.ip` (size = the number of winners) with the same size-1 sub-aggs. It is skipped when there are no winners, and a failure is a 502. The response shape is unchanged.
- `top_sources` and `top_destinations` sum `network.bytes` (equal to source + destination bytes on every conn doc). A test checks that every query summing it filters `event.dataset: conn`.
- Connections offers 30d again: the `shortcut:` from PR 4 is gone, and 30d asks for day buckets.

**devices list, 7.9 s at 30d.** In `_lan_device_buckets` the composite alone took 3.6 s, and the cost was the LAN filter. `build_lan_filter` was a Painless script that split `source.ip` as text on every doc.
- Script vs CIDR `terms` on `source.ip`: 3,839 / 4,311 ms against 998 / 929 ms.
- Identical over 30 days: 3,845,029 docs, 59 IPs, the same per-IP doc counts and byte sums.
- Detected subnets `(192,168,1) (10,10,0) (192,168,40)` become `192.168.1.0/24 10.10.0.0/24 192.168.40.0/24`.
- Fix: `build_lan_filter` returns `{"terms": {"source.ip": [cidrs]}}` (/8, /16, /24; none gives the RFC1918 three). `lan_subnets_of` parses the CIDRs back (the RFC1918 list reads as `[]`).
- No reader depended on the script shape. `main.py`'s in-place update still swaps the filter's one key at once, and `changed_lan_filter`'s equality still works.
- Not changed: the devices list's own Painless→field swap barely mattered (5.0 vs 4.7 s), so `device_aggs` stays as it is.

**1b tests.**
- Daemon: 3,602 passed, 3 skipped. New: `TestConnectionStatsQueries` (no per-destination asn/geo; one follow-up for the winners; none without winners; a failed follow-up is a 502; `network.bytes` only in conn-filtered queries), and `test_lan_filter.py` (each subnet form, the round trip, the fallback, re-detection, and that the CIDRs match the same addresses as the old script's rule). The stats tests fail on main's `traffic.py`.
- Web: 3,764 passed, including the Connections range set with 30d and a 30d request test. Visual: 276 passed, 49 skipped.
- On the G11 next: `deploy-speed-timing.sh` again, then `verify-figures.sh`, `verify-device-figures.sh` and `verify-split-invariance.sh`.

**1b on the G11 (`fc59a144`).** connections/stats at 7d 13.65 s → 2.43 s; the devices list at 30d 7.92 s → 3.30 s; risk at 24h 2.45 s → 0.79 s. `verify-figures`, `verify-device-figures` and `verify-split-invariance` all pass.

### Reviews

Five reviews of `fc59a144` plus `733af24e` (`deploy-speed.sh`):

- **/deep-review:** no findings (`security-reviews/feature-net192-speed/security-review.md`).
- **security-engineer:** 3 Low. L1 and L3 are fixed below. L2 wasn't in the fix list for this round.
- **Python reviewer, TypeScript reviewer, /ponytail-review:** no Critical or High.

Fixed in this round, each with a test that fails without the fix (or a new test where the item is test-only):

- **The report's beaconing rows and state** (`api/threats.py`). Both are now read before the multi-second report. Before, the rows were read before it and the state after, so a scan that published in between gave empty rows labelled "ready": a false "No beaconing".
- **A failed scan is retried sooner** (`services/beacon_snapshots.py`).
  - After `QUERY_FAILED` the next try is 60 s later, doubling on each further failure, never past the window's interval.
  - `CAP_HIT` keeps the normal interval, because the cap would stop the scan again.
  - Reason: after a reboot the daemon often starts before OpenSearch or its auth bootstrap, so all three first scans failed, and the page said "failed" for 15 to 60 minutes.
  - Also tested: publishing one window leaves the others empty and pending, and over a run 30d scans fewer times than 24h.
- **WHOIS** (`api/lookup.py`).
  - Output is cut at 64 KiB before decoding.
  - A non-zero exit, empty output or no parsed fields gives `error: "WHOIS lookup failed"`, kept 5 min instead of 24 h.
- **Reverse DNS.** `socket.herror` TRY_AGAIN (errno 2), which glibc raises when `RES_OPTIONS`' tries run out, is `timed_out`. Other `herror` values stay "no record".
- **Lookup validation (security L1).** The routes use `parse_single_ip`, which refuses IPv6 scope ids. `ipaddress` keeps any scope id, newlines included, so `::1%25%0Ax` could forge a daemon log line. It is now a 400.
- **Dead code.** The cache stats only ever logged at DEBUG, and the daemon logs at INFO. Removed: `_log_cache_stats`, `STATS_EVERY_S`, `TTLCache.hits`/`misses` and their test.
- **LAN_SUBNETS (security L3)** (`services/excluded_ips.py`).
  - Each entry is parsed with `ipaddress.IPv4Network(strict=False)` and must be a /8, /16 or /24. Anything else is skipped with one warning per entry.
  - Before, `192.168.300.0/24` went into the filter and OpenSearch then rejected every LAN-filtered query, and a non-number raised at import.
  - `cidr()` is now public, and `api/network.py` uses it instead of its own copy (kept as OLD CODE).
- **Tests only.**
  - Single-flight: when the first reverse lookup or WHOIS raises, every concurrent waiter gets a 500, `_in_flight` is empty, and the next call succeeds.
  - The blackhole tests no longer use wall-clock limits. Health answers while the lookups are still blocked, and the lookups end well before the fake resolver's 10 s hang.
- **`RES_OPTIONS`** is now `"timeout:2 attempts:2"`. It applies to the whole process (whois, the threat-intel feeds, the update check, UniFi), and 2 × 2 s stays under the 6 s lookup bound.
- **Threats polling** (web).
  - While the check is pending the page polls `/api/threats/beaconing?snapshot=`, not the whole report, and merges `beaconing` and `beaconing_snapshot`.
  - When the state leaves pending, it reloads the page once, so "Updated" moves.
  - The 20 s interval, the 10-minute cap and the stale-response guard are unchanged.
  - New tests: no requests after unmount; a poll in flight across a range change doesn't overwrite; a rejected poll retries and recovers.
- **Threats copy.**
  - After the 10-minute cap, the KPI sub says "Still running. Refresh to check again." and the card's note and loading text say "Beaconing check still running. Refresh to check again." Before, they still promised "a few minutes".
  - When the state is stale, the KPI sub reads "Last checked {time}", so the count isn't read as live.
- **`threatRequest`.** 1h and 6h take their bounds from the page's `computeTimeParams(range)`, so the report and the threat intel count one window. `LIVE_SPAN_MS` and the `now` parameter are gone, and an `isSnapshotWindow` type guard replaces the `as` cast.
- **Copy.** "Reverse DNS lookup timed out" on the address and DNS lookup pages, since a timeout doesn't mean there's no name. Also fixed the DNS page's `{#if}` indent.
- **Web proxy.** The Connections sankey and timeline get 30 s, like connections stats. With 30d back, the sankey (2.3 s at 6 days on the G11) could pass the 10 s default at a real 30 days.

**Plan deviations.**

- **The LAN filter is CIDR terms.** The plan's 1b fixes were the Painless→field byte sum or reshaping the dominant aggregation. On the devices list the dominant cost was the LAN filter's Painless script, so it became CIDR `terms` on `source.ip`, with identical results.
- **Retry after a failed query.** The plan had a fixed 15/15/60 min schedule. A failed query now retries after 60 s, doubling up to the interval.
- **No 8-waiter cap on lookups.** The plan said a new lookup answers `timed_out` at once when 8 are waiting. PR 2's `lookup_slot` (`Semaphore(4)`: 2 running, 2 waiting) already answers 503 at once when full, so a second cap would never be reached.
- **The page polls the beaconing route, not the whole report**, and reloads once when the check finishes.
- **`RES_OPTIONS` is `timeout:2`**, not the plan's `timeout:1`, because it applies to the whole process.
- **The timeout copy** is "Reverse DNS lookup timed out", not "No reverse DNS name (lookup timed out)".

**Review-round tests.**
- Daemon: 3,621 passed, 3 skipped.
- Ruff check and format: clean.
- Web: 3,768 passed.
- svelte-check: 0 errors.
- check:colors and check:e2e: clean.
- Visual: 276 passed, 49 skipped.
- Swap checks:
  - The report race and LAN_SUBNETS tests fail on the old code.
  - The WHOIS failure and 64 KiB, TRY_AGAIN and scope-id tests fail on the old code.
  - The retry test fails with the plain interval, and the cap test fails if every failure retried early.
  - Every new poll test, and the stale KPI test, fail on the old page.

## PR 4: one look on every page (web)

### What changed

- **One time and number format.** `lib/utils/time.ts` `formatTime(ts, 'short' | 'long' | 'clock' | 'date')` is en-GB and 24-hour. It replaced about 25 local formatter copies and about 90 locale-less `toLocale*String()` calls (Live's feed, SessionTimeline's "11/06 22:00"). The ten compact-number copies now use `formatCompactNumber`. `time.test.ts` fails on a `toLocale*String()` call with no locale anywhere in `web/src`.
- **One range set: 1h 6h 24h 7d 30d.**
  - DNS, Connections, Alerts, Alerts category, Suricata category, Log Explorer and PCAP drop 15m and 4h.
  - Pages gain the ranges they lacked: 6h, 30d, or 1h and 6h.
  - devices/mac gets the pills (`getDeviceTraffic` takes the window).
  - Settings' default range offers the same five.
  - An old `?range=15m` or `4h` link falls back to the page default.
- **Connections stops at 7d for now.** Its stats took 14.5 s over the G11's 6 days of data (`shortcut:` comment in `connections/+page.svelte`). PR 3 adds 30d back once that query is fast.
- **Auto-refresh:** `ui/AutoRefreshButton.svelte` ("Auto" with "Refreshes every N s", or "Paused") replaces every page's variant. Pages that start with refresh off read "Paused".
- **Stale notes:** every "showing older figures" note is `.notice.is-warn` with the warn icon.
- **Voice:**
  - The IoT drawer and the tabs use sentence case. Live's "24h history" now reads "Last 24 hours".
  - Connections writes its window in lower case mid-sentence.
  - `formatCompactNumber` drops ".0" (Home's Alerts KPI shows "214K"), and Home's breakdown has thousands separators.
- **Structure:**
  - The Threats KPI sub reads "Higher is riskier · <window>", and the scoring paragraph sits in a disclosure.
  - IoT's hero is the c-8 Findings card.
  - Settings has `registerPageRefresh`, which re-reads only Retention health and About. An unsaved form edit survives a Refresh.

### Measured on the G11 (2026-11-07, PR 2's daemon)

- **Every long-range request answered in time.**
  - Connections stats at 6 days of data took 14.5 s (its limit is 24 s).
  - The sankey took 2.3 s and DNS suspicious 1.2 s. Everything else took 1.1 s or less.
  - IoT's 30-day activity timeline (721 one-hour buckets) took 0.1 s.
- `scripts/remote/verify_long_range_timings.py` runs these at deploy (`deploy-ui-consistency.sh`).

### Tests

- Vitest: 3,714 passed. svelte-check: 0 errors (the 2 old warnings). `check:colors` and `check:e2e` are clean.
- `test:visual`: 276 passed, 49 skipped.
- New tests cover:
  - the formatter and the locale scan;
  - the Auto/Paused button;
  - the devices/mac pills;
  - the DNS range set and its 30d buckets;
  - the Connections four-range set and the `?range=30d` fallback;
  - the compact Alerts KPI and the Threats disclosure;
  - the Settings refresh keeping an unsaved edit (it fails with the earlier version).
- Gates:
  - `/deep-review`: no findings (`security-reviews/feature-ui-consistency-pr4/`).
  - `/ponytail-review`: verdict "fix 1 and 2 first". All fixed in this PR:
    - three pages' stale notes now use the amber style, with a scan test;
    - one compact formatter, so 999,950 reads "1M", not "1000K";
    - range defaults are picked by value;
    - `formatWhen`/`formatDay` are aliases of `formatTime`;
    - six `fmt` copies removed;
    - one `AUTO_REFRESH_MS` per page;
    - an empty URL test removed;
    - the locale scan also catches `new Intl.*Format()` with no locale.
  - Filed:
    - NET-196: one range list instead of 14.
    - NET-195: Settings > Display saves choices no page reads. This predates PR 4 and needs the owner's call.

### Not changed

- devices/mac's bandwidth card stays empty, because the registry traffic reply has no series. This predates PR 4.
- Go-live keeps its own compact formatter.
- Alerts category has a timer but no button.
- KPI notes still mix "Last 24 hours" and "last 24 hours".
