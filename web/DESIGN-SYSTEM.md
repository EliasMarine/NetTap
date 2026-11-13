# NetTap design system: how the web app uses it

> **Canonical reference for every page.** The design itself (voice, colour, type, layout, every component's look) is the owner's system in `nettap-design-system/`: start with its `README.md`, then `components/<Name>/README.md` and `preview.html` for each component you use. This file says how `web/` implements it, and which rules the build enforces. The full plan behind the 2026-11 redesign is in git history: `git show f71625ab:PLAN.md`.

## Three pillars

1. **Device-centric:** organise by "what are my devices doing?", not by log type.
2. **Plain English:** every alert, metric and detection gets a human-readable explanation, with the raw detail underneath in mono.
3. **Immediate value:** big numbers first, details on click. Overview, then category, then raw data.

---

## Style files

Imported once, in this order, by `src/routes/+layout.svelte`:

| File | What it holds |
|---|---|
| `src/lib/styles/tokens.css` | The system's `tokens.css`, verbatim: every colour, size, radius, motion and font token, per theme. **The only file allowed colour literals.** |
| `src/lib/styles/system.css` | The system's `components/bundle.css`, verbatim. All system classes are global: `.app`, `.shell`, `.sidebar`, `.page-head`, `.grid`, `.c-3`…`.c-12`, `.card`, `.pills`, `.btn`, `.chip`, `.tbl`, `.who`, … |
| `src/lib/styles/forms.css` | **The one extension.** The system has no form controls, so this adds them from tokens only: `.input`, `.select`, `.textarea`, `.switch`, `.check-row`, `.field`, `.label`, `.field-help`, `.field-error`, `.form-grid`, `.form-group`, `.form-actions`, plus the shared `.notice` banner (`.is-ok`, `.is-warn`, `.is-error`), `.chip.is-bad` (red: stopped or failed) and `.chip.is-caution` (amber: a check couldn't run, needs a look; the system's orange `.chip.is-warn` stays "bad change"). |
| `src/lib/styles/a11y.css` | Numbered corrections to `system.css`, each naming the `bundle.css` line it corrects (see "Accessibility corrections"). New corrections go here, never in `system.css`. |
| `src/lib/styles/global.css` | Only the app-wide base rules the system lacks: margins, `pre`/`code`, `::selection`, scrollbars. |

Never edit `tokens.css` or `system.css` by hand: they are copies of the owner's files.

## Tokens

Use only the system names (all defined in `tokens.css`):

- **Surfaces and lines:** `--bg`, `--surface-1`…`--surface-3`, `--line`, `--line-strong`, `--scrim`
- **Text:** `--text-1` (primary), `--text-2`, `--text-3` (muted), `--on-accent`, `--on-light`
- **Brand:** `--accent`, `--accent-strong`, `--focus`
- **Severity and status:** `--sev-critical`, `--sev-high`, `--sev-medium`, `--sev-low`, `--sev-info`, `--ok`
- **Data series:** `--data-1`…`--data-6`. More than six series go through `topSeries()` (`src/lib/utils/series.ts`), which folds the rest into "Other".
- **Spacing:** `--sp-1` (4 px), `--sp-2` (8), `--sp-3` (12), `--sp-4` (16), `--sp-5` (20), `--sp-6` (24), `--sp-8` (32)
- **Radius:** `--r-xs`, `--r-sm`, `--r-md`, `--r-lg`, `--r-xl`, `--r-pill`
- **Type sizes:** `--text-xs`, `--text-sm`, `--text-base`, `--text-md`, `--text-lg`, `--text-xl`; fonts `--font-body`, `--font-mono`
- **Motion:** `--dur-fast`, `--ease`

The old names (`--bg-tertiary`, `--text-primary`, `--cyan`, `--red`, `--space-md`, `--radius-md`, …) are gone. The colour gate fails on any `var(--x)` that nothing defines, so a legacy name or a typo can't slip back in.

## Themes

- Three themes: **Ember** (default), **Graphite** and **Spectrum**. The attribute is `<html data-theme="graphite|spectrum">`; Ember is no attribute.
- `src/app.html` has an inline script that reads `localStorage['nettap-theme']` and sets the attribute **before first paint**, so a saved theme never flashes Ember.
- `$lib/stores/theme` starts from that attribute. `setTheme(v)` is the only writer: attribute, then store, then storage. If storage is blocked, the theme still applies for the session.
- The picker is `ThemePicker.svelte` in **Settings → Display**. It renders Ember on the server and adopts the stored theme in `onMount`.

## Shell

`+layout.svelte` draws the system shell: skip link, `.app > .shell`, `Sidebar`, then `main#main` with `TopBar` and the page. Components live in `src/lib/components/shell/`.

- **Sidebar:** 20 links in 4 groups (`nav.ts`; Packet analysis joined Investigate in NET-188), the Alerts count from the shared alert snapshot, the capture chip and storage meter, and Sign out (a `POST /api/auth/logout` form).
- **TopBar:** search combobox (Ctrl-K), Refresh (runs the page's registered loader), the "Updated" time and the notification bell. **Pages have no Refresh button or "Updated" text of their own.**
- **Phone (≤ 760 px app width):** a top bar with a menu button opens the sidebar as a drawer: focus moves in, Tab is trapped, and Escape, the scrim or a link closes it.
- `/login` and `/setup` render bare (no shell).

## Page recipe

Top to bottom:

1. **`.page-head`:** `<div><h1 class="page-title">…</h1><p class="page-sub">…</p></div>` plus head actions, including time-range `Pills` wherever the page has a time range. **Exactly one `h1.page-title` per page**, inside `<main>`.
2. **KPI row:** at most four `KpiCard`s in `c-3`, or three in `c-4`.
3. **Hero chart and side card:** one hero card in `c-8` (or `c-7`) beside one in `c-4` (or `c-5`). At most two hero cards per screen.
4. **Detail cards and tables.**

Every card has a title and a sub that states the unit and the window ("GB per hour · last 24 hours"). Pages are always full width: never set `max-width` on a page container.

## Components (`src/lib/components/ui/`)

Build pages from these; read each file for its props.

- **Layout and state:** `Card`, `CardState` (loading, empty, error; "Try again" only when `onaction` is set), `KpiCard`, `StatStrip`, `Pipeline` (stage states: `ok` green check, `warn` amber triangle for a check that couldn't run, `failing` orange triangle, `unknown` grey clock; each icon names its state)
- **Controls:** `Pills` (toggle, tabs or nav mode), `SearchField`, `LiveChip`, `AutoRefreshButton` (Home's "Auto" / "Paused" toggle; every page with auto-refresh uses it)
- **Data:** `DataTable`, `BarList`, `Meter`, `Bytes`, `Who`, `ConnResult`, `SeverityPill`, `DeviceList`, `DeviceTile` (with `deviceIcon()` from `device-icon.ts`; pass a device's `picture` and `icon` so the owner's photo or chosen icon shows, NET-200), `AlertRow`, `AlertGroup`, `Icon` (the system's 48 icons; a test fails if they drift from `nettap-design-system/assets/Icons/`)
- **Charts (`ui/charts/`):** `AreaChart`, `Donut`, `SeverityGauge` (fed by `severityBuckets()` from `utils/severity.ts`), `Ring`, `Sparkline`, `StackBar`, `Radar`, `DotMap`. Chart maths lives in `ui/charts/geometry.ts`.
- **The Live globe (NET-207):**
  - `ui/charts/Globe.svelte` with its engine in `ui/charts/globe/` (three.js WebGPU, WebGL 2 where WebGPU is missing, TSL materials). three is dynamic-imported, so only `/live` downloads it.
  - `components/live/LiveGlobeCard.svelte` wraps it, and falls back to `DotMap` when the browser can draw neither, or when Settings › Display › Live map is "Flat map". The choice is `savedLiveMap()` in `utils/drilldown.ts`.
  - The globe reads its colours from the tokens at runtime, so it follows the theme. Its JS files are `@ts-nocheck`, because three ships no types.
- **Device cards** (Devices, By type): every card has the same three rows (top; the maker line, "Maker unknown" when the lookup found none, with any addresses note under it; stats), on a subgrid of the group's grid, so the stats line up across a row of cards; the List layout's rows use the same helpers, so both layouts show the same figures (NET-180).
- **Network flow** (`components/NetworkFlow.svelte`, maths in `ui/charts/flow.ts`): device → protocol → destination on one scale, coloured by protocol only (TCP `data-1`, UDP `data-2`, ICMP `data-5`), with an "Other destinations" node so every column adds up. Devices show their registry name (`utils/device-names.ts`), else their IP. Below 640 px of card width, or when the endpoint's two searches disagree beyond rounding, it shows `NetworkFlowTable` instead, with the reported figures unchanged.

Every chart has `role="img"` and an `aria-label` that states its headline, for example "Busiest hour 21:00, with 4.7 GB downloaded". The Network flow's labels are buttons, so it is a `role="group"` with the headline as its label instead. So is an `AreaChart` given `onpick` (see "Picking a moment on a chart" under Drill-down links).

## Data on a page

- **Only show numbers the page loads.** Never invent, default or estimate a figure. A failed request shows its error state, never `0`, `0 B` or "No data".
- **Keep the last figures on a failed refresh** and say so: `loadFailed(what, true)` gives "Couldn't refresh … ; showing the last figures loaded." (#96), always as `<p class="notice is-warn" role="status"><Icon name="warn" /><span>…</span></p>`.
- **One source per number.** A number on two screens comes from one place. The alert count is `alertSnapshots` (`stores/alertSnapshot.ts`): Home, Alerts and the sidebar read the same snapshot per window.
- **Refresh contract** (`stores/pageRefresh.ts`): a page that loads data calls `registerPageRefresh(loader)`. The loader awaits every request behind visible data and returns `'ok' | 'partial' | 'failed' | 'skipped'`; `outcome(results)` computes that from `Promise.allSettled`. Auto-refresh loops call the same loader.
- **Load guard:** `const g = guard.begin()`, copy the query (range, filters, page, sort) into locals before the first `await`, and check `guard.current(g)` before every state write after an `await`. A slow, older response then never overwrites a newer one.
- **Partial figures say so** (NET-160): a byte total some records didn't measure reads "at least …" with how many were measured, none measured reads "Not measured", and a list too long to count shows "—" with "too many to count" (`utils/drilldown.ts`).

## Drill-down links (NET-160)

- **Every IP is `IPAddress`** (`components/IPAddress.svelte`): a link to `$ipHref(ip)` (its device page when the daemon's LAN policy says so, `/address/<ip>` otherwise or before the policy loads, `stores/lan.ts`), with its right-click menu beside it. Inside another link or button, or in column 0 of a table with `onrowactivate`, use `linked={false}` (plain text) and make sure the row's drawer links the address.
- **Every domain links with `domainHref(name)`** (`/domain/<name>`), except in column 0 of a row-activated table: put the link in the row's drawer or detail.
- **Never nest a link or button in another.** Page tests call `expectNoNestedInteractive(container)` (`src/tests/nested-interactive.ts`).
<!-- OLD CODE: - **A count links to a list over the same window.** Pass the window on (`?range=` to Alerts and Log Explorer, `from`/`to` to Certificates), so the list a number opens holds that number. (slice 2a: exact windows) -->
- **A count links to a list over the same window, exactly.** Pass the count's own `from`/`to` (the bounds its response used, kept when the response lands, not recomputed at click time) plus `range` for the words: `windowQuery`, `alertsHrefForSignature`, `logsHrefForQuery`, `logsHrefForIp` in `utils/drilldown.ts`. Alerts, Log Explorer and Certificates open such a link as a "Custom" range; picking another range clears it, and paging or "load more" stays on the search's window.
<!-- OLD CODE: - **The link carries the count's own filters too.** A port's count links with the exact Log Explorer query behind it, so the list holds the number. Where the list can't take a count's filter yet (a smart alert's source → destination pair), the code says so and the link narrows as far as it can (`ip`). (slice 2b-1: the list takes the pair now) -->
- **The link carries the count's own filters too.** A port's count links with the exact Log Explorer query behind it, so the list holds the number.
- **Filter on what the count grouped by, not on what the page shows** (NET-160 slice 2b-1). A smart alert's ×N links with its response's `key` (`rule_name`, `source_ip`, `destination_ip`) through `smartAlertHref`, plus the device's `ip` on a device page; the shown signature can be another name. An alert row links by its `rule.name`. When a key part is missing or empty there is no link: the ×N or row stays plain, with the title `NO_EXACT_ALERT_LIST`. Never drop a filter to make a link.
- **A count that left something out says so in its response.** Home's Connections and Bandwidth come from `/api/traffic/summary`, which leaves out the sources excluded in Settings and returns them as `excluded_ips`; `connLogsHref` passes them as Log Explorer's `exclude_src`, shown as a chip.
- **Link the figure on screen.** After a failed refresh a card keeps its last figure, so its link keeps that response's window (`alertCount.from`/`to`, the summary's own `from`/`to`), never the window of the attempt that failed. Only a card with no number links by range alone.
<!-- OLD CODE: - **On Alerts the URL holds the list's filters** (`severity`, `signature`, `ip`, `range`, `from`, `to`). Controls change only their own parameter; a severity tile opens the counts' own window with no other filter, since the counts are unfiltered. (slice 2b-1: src and dst) -->
<!-- OLD CODE: - **On Alerts the URL holds the list's filters** (`severity`, `signature`, `ip`, `src`, `dst`, `range`, `from`, `to`). Controls change only their own parameter; a severity tile opens the counts' own window with no other filter, since the counts are unfiltered. (slice 2b-2: suricata_category, and Top signatures opens a fresh URL) -->
<!-- OLD CODE: - **On Alerts the URL holds the list's filters** (`severity`, `signature`, `ip`, `src`, `dst`, `suricata_category`, `range`, `from`, `to`). Controls change only their own parameter. A severity tile and a Top signatures row open their counts' own window with no other filter, since those counts are unfiltered. (NET-185: no_rule_name, and the category page reads its window) -->
- **On Alerts the URL holds the list's filters** (`severity`, `signature`, `no_rule_name`, `ip`, `src`, `dst`, `suricata_category`, `range`, `from`, `to`). Controls change only their own parameter. A severity tile and a Top signatures row open their counts' own window with no other filter, since those counts are unfiltered. A category bar opens `/alerts/<category>` with its counts' window; the category page reads `range`, `from` and `to` from the URL (a `from`/`to` link is "Custom"), and its range pills write `?range=`.
- **No value is not a value named "Unknown"** (NET-185). Alerts with no `rule.name` are their own row, labelled "No rule name" (an empty name reads the same), and link with `no_rule_name=true` (`alertsHrefForSignature(null, …)`); `no_rule_name=false` lists only alerts that have one. A rule really named "Unknown" links by its name, and an alert row links on its `rule.name`, never on the shown signature. Never fold a missing field into a placeholder name: neither link could then hold its figure.
- **A raw Suricata category links only where it is exact** (NET-160 slice 2b-2). `suricataCategoryHref(name)` opens `/alerts/suricata/<name>`, which filters on the stored `rule.category`. A shown category is a link only when the row's `rule_category` holds it (`linkedSuricataCategory`); otherwise it stays plain, as "Uncategorised" does. A "By category" heading links only when every alert under it carries its title, and its count of page rows stays plain. On the category page an Also tagged count is plain text: it counts the alerts carrying both categories, while that category's own page counts every alert carrying it.
- **On Log Explorer the URL is a one-time hand-off** (`filter`, `ip`, `query`, `type`, `exclude_src`, `range`, `from`, `to`). Each hand-off replaces those filters; after it, every control, chip and "Clear all" changes local state only and never writes the URL.
- **A top source or destination bar opens exactly its figure** (NET-184). It counted one side over its card's window, so its click searches `source.ip:"…"` or `destination.ip:"…"` over that window with the query, DNS, excluded sources and log type cleared; the chip says Source or Destination. Clicking it again clears it. Sorting and "load more" stay on that search's window.
<!-- OLD CODE: - **Every Home range exists on Alerts and Log Explorer** (1h, 6h, 24h, 7d, 30d), so a range link never falls back to 24 hours. (NET-192 PR 4: one set everywhere) -->
<!-- OLD CODE: - **One range set on every page with ranges: 1h, 6h, 24h, 7d, 30d** (Home's), … For now Connections stops at 7d: its stats take 14.5 s over 6 days of data on the G11, so 30d waits for the speed work. (NET-192 PR 3: Connections has 30d again) -->
- **One range set on every page with ranges: 1h, 6h, 24h, 7d, 30d** (Home's), so a range link never falls back to 24 hours. Live is the real-time page; there is no 15m or 4h, and an old `?range=15m` or `4h` link falls back like any unknown range.
- **Picking a moment on a chart** (NET-249). `AreaChart`'s `onpick(from, to)` reports inclusive point indices; the page builds the link and calls `goto`, so the chart stays free of the router.
  - A click or tap picks one point (a movement under 4 px is still a click), a drag picks a range (`touch-action: pan-y`: a vertical swipe scrolls the page), and the arrow keys, Home/End, Shift for a range, Enter and Escape do the same from the keyboard. The chart is then one focusable `role="group"` whose label is the headline plus how to use it, with a polite live line for the point or range.
  - A selection belongs to the series it was made on: a new `series` (a refresh, another range) cancels a drag and a keyboard range, so a pick always uses indices into the data on screen. Hold the reply whole (`{series, from, to, step}`, `BandwidthChart`) so the indices and the window come from one answer.
  - Buckets scale with the range, from one table: `DRILL_RANGES`' `bucket` (1h → 1 min, 6h and 24h → 5 min, 7d → 1 h, 30d → 3 h); a custom window takes `bucketFor`'s.
  - A slot is `[start, start + step)` and the daemon's windows are `gte from, lte to`, so `bucketWindow` ends a pick 1 ms before the next slot and clips the edge slots to the reply's own window. A trailing slot that starts at `to` gives `from == to`, a valid one-millisecond window: `customRange` takes `from <= to` on every page. `windowWords` and `customRange` show an end of …:59.999 as the next minute.
  - A bandwidth chart opens `/moment` (`momentHref`), carrying the picked points' `down`, `up` and `local`; the moment page says per figure where its own totals differ, and why. Its widen links drop those figures. Every chart that takes part shows the hint "Click a point or drag across the chart to see that moment." under it.
- **A protocol bar opens the records it counted** (NET-249): `serviceLogsHref` writes `/api/traffic/protocols`' whole predicate (conn records, its `excluded_ips`, ssl without QUIC, `unknown` as no service label).
- **Outside look-ups run on click.** Reverse DNS and WHOIS about an address or name wait for a button: an automatic one tells whoever runs that server that we looked. Settings › Network location's "Use my WAN location" (ipinfo.io) follows the same rule, and only fills the form.

## Tables

- Use `DataTable`. **Every column sorts, both directions.** A newly clicked column sorts descending first.
- Server-sorted tables pass `onsortchange` and keep sorting on the daemon.
- Numbers are right-aligned and tabular (`numeric: true`). Machine values (IPs, MACs, ports, hashes, signatures) use mono.
- A column can take a `title`, shown as hover text on its header (Log Explorer uses it for field descriptions).

## Voice

From the system README: sentence case everywhere (titles, buttons, labels), UK spelling, `…` not `...`, no exclamation marks, **no emoji**. Errors say what failed and how to fix it: "Couldn't load alerts: the request failed." Severity is always colour + shape + word (`SeverityPill`), never colour alone.

## Accessibility corrections (`a11y.css`)

1. The search field shows the focus ring on `.search:focus-within` (bundle.css removes the input's outline).
2. A selected tab in Pills tabs mode (`aria-selected`) gets the selected-pill look.
3. `DeviceList` select mode: a pressed row gets the selected-row look.
4. While the phone drawer is open the page doesn't scroll, and the drawer is one screen tall and scrolls inside itself.
5. On phones a long pill group scrolls inside its track instead of pushing the page sideways.
6. Severity count tiles share the row however many there are, and their counts shrink together to fit (the page sets `--sev-chars` on `.sev-counts`).
7. On phones the head actions are capped at the page head's width, so a long range-pill group (six with Custom on Alerts and Log Explorer) scrolls inside its track instead of scrolling the page sideways.
8. At 1100 px and below, the last half-width card of a run of one, three or five (like the side card of a c-8 hero row) takes the full row, instead of sitting alone on half a row.
9. In a `col` card the donut stacks above its legend and grows into the card's free height.

Every `<button>` sets an explicit text colour (the browser default is black). Focus rings use `--focus`.

## Colour gate

`npm run check:colors` (`web/scripts/check-colors.mjs`) checks every non-test file in `web/src` and fails on:

- **Colour literals:** `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()`/`rgba()`, `hsl()`/`hsla()`, and `white`/`black` used as colours. It reads all CSS (`.css` files and `<style>` blocks) and quoted strings in TypeScript, `<script>` and markup, so "PR #147" and `white-space` never trip it. `tokens.css` is skipped.
- **Tokens nothing defines:** a `var(--x)` with no `--x:` declaration, `style:--x` or `setProperty('--x')` anywhere in `web/src`. Names built in markup (`var(--sev-{level})`) are skipped.
- **Emoji** anywhere outside comments.

Comments are skipped, so commented-out `OLD CODE` never trips it. `// colour-gate: allow-next-line <reason>` exempts one line, only for output that can't read CSS variables (for example email HTML in `lib/server/notifications.ts`). `scripts/check-colors.allowlist` is empty and should stay that way.

**Colours in JavaScript:** for `style=` and SVG `fill`/`stroke`, use `var(--token)` strings (`fill="var(--data-2)"`). Code that can't take `var()` reads the real value with `resolveToken('--accent')` (`src/lib/utils/tokens.ts`) and reads it again when the theme changes.

## Testing the look

- `npm run test:visual` runs the visual harness (`e2e/visual/`, `playwright.visual.config.ts`) against a fixture daemon. It logs in for real, opens every route in empty and error mode (and the routes in `populated.visual.ts` with data), and in all three themes at 1920, 1440 and 390 px checks the accent token, the shell, one `h1.page-title`, horizontal scroll and console errors. Each route's heading marker is in `e2e/visual/routes.ts`.
- `npm run test:e2e` runs the behavioural specs (`e2e/*.spec.ts`).
- `npm run check:e2e` type-checks every spec and fixture against the API interfaces.
- `src/tests/token-contrast.test.ts` checks every text and severity token is AA (4.5:1) on every surface, in every theme.

## Rules

1. Use system classes first; scoped CSS only for layout glue the system lacks.
2. Only system tokens: no colour literals, no hard-coded spacing or font sizes, no legacy names. The colour gate fails the build otherwise.
3. Follow the page recipe: one `h1.page-title`, KPI row, hero, details. Full width.
4. Every data card shows `CardState` for loading, empty and error.
5. Every table sorts on every column.
6. Severity is colour + shape + word.
7. Sentence case, UK spelling, no emoji.
8. Every page works at 1920, 1440 and 390 px with no horizontal page scroll.
9. Every loader follows the refresh contract and the load guard.
