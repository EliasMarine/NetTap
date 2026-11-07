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

### Left for PR 4

- The Home Alerts KPI shows "214.0K" (`formatCompactNumber`) and its sub "9000 high, 47000 med" has no separators.
- Live's feed times and SessionTimeline's x labels use US formats ("11:35:42 PM", "11/06 22:00").
