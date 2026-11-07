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
  - `/ponytail-review`: see the PR.

### Not changed

- devices/mac's bandwidth card stays empty, because the registry traffic reply has no series. This predates PR 4.
- Go-live keeps its own compact formatter.
- Alerts category has a timer but no button.
- KPI notes still mix "Last 24 hours" and "last 24 hours".
