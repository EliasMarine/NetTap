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
