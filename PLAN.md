# Plan: NetTap full redesign to the NetTap design system

_Approved by Codex in round 4 (2026-11-03); review log: `.codex-review/2026-11-03-190850-ui-redesign-full/`. Replaces the 2026-11-03 staged plan (Codex round 4; still in git history at `c8267af:PLAN.md`). That plan's PR 1 is built and open as PR #165. Its PRs 2–4g were never built, and the owner rejected the staged approach on 2026-11-03: "you only changed the colors … I wanted a FULL REDESIGN."_

## 1. Goal

Rebuild the shell, the shared components and **every page** to the owner's design system in `nettap-design-system/`, which the owner supplied on 2026-11-03.

Done means a person opening any page sees the system's layout, components, type, icons, charts and copy, not just its colours.

## 2. Source of truth

- **`nettap-design-system/` is the spec and is committed to the repo root unchanged.** It holds:
  - `README.md`: voice, colour, type, layout, shape, severity, charts, icons, logo and motion rules
  - `tokens.json` and `tokens.css`
  - `components/*/README.md` and `preview.html` for 17 components, plus `components/bundle.css`
  - `assets/Icons`: 48 outline icons
  - `assets/Logos`: the mark
- **`web/DESIGN-SYSTEM.md` is rewritten as a short implementation guide.** It covers:
  - where the tokens and classes live in the app
  - which Svelte component implements each system component
  - the one documented extension, form controls (§5.1)
  - the lint gates
  - **Precedence:** where it and the system folder disagree, the folder wins.
- **The Design System section of `CLAUDE.md` is updated.**
  - Spacing becomes `--sp-*`, replacing `--space-*`.
  - Type sizes use the system's `--text-*` scale.
  - The reference implementation becomes Home (`web/src/routes/+page.svelte`), replacing Log Explorer.

## 3. Owner decisions

**New (2026-11-03):**
- **All at once.** The whole redesign is built on one branch. The owner deploys it once to the G11 and checks it, and it merges only after that check.
- **Home without device cards.** Home must look clean. The per-device card grid (`DeviceGrid`, its filter bar and the new-device banner) leaves Home. Owner: "They can be found under the devices page." See §5.6.

**Still in force from the earlier plan:**
- **Background:** pure black.
- **Themes:** Ember is the default; Graphite and Spectrum are available in a Settings picker.
- **Sidebar groups:** Overview, Investigate, Devices and System.
- **Replaced code:** replaced CSS and markup are deleted, with git as the record. Replaced logic follows OLD CODE START/END.
- **Fonts and charts:** fonts are bundled, and charts are hand-drawn SVG.
- **Density:** tuned for 1920 px, and it must also work at 1440 and 390.

## 4. Hard constraints

1. **Every number comes from data the app already fetches.**
   - **No daemon changes and no new endpoints.** A shell or page may call an existing `web/src/lib/api/*` client it did not call before. Each such call is listed in the PR body.
   - **Numbers agree across screens** (system README). Same code is not enough, because independent requests can return different totals. So one **alert snapshot store** (`web/src/lib/stores/alertSnapshot.ts`) owns the global count:
     - **Contents:** `getAlertCount` results keyed by an absolute window. The window is built once per refresh generation as `{from, to}` ISO strings and rounded to the minute.
     - **Callers:** the sidebar badge ("last 24 hours", stated in its `aria-label`), Home's Alerts KPI when Home's range is 24 h, and the Alerts page's severity summary at its default 24 h range. They all read the same snapshot object for the same window.
     - **Deduplication:** concurrent callers share one in-flight request.
     - **Ordering:** a generation counter drops out-of-order responses.
     - **Other windows:** a different range on Home or Alerts gets its own snapshot entry, labelled with that range.
     - **Filtered totals stay separate.** The Alerts table's filtered total and pagination keep their own request and their own label ("N matching"). They are never forced to equal the global count.
     - **Tests:** two callers get one request; a stale response is dropped; a refresh moves every caller to the new generation; a filter change leaves the global count alone.
   - **Missing data:**
     - If a system element needs data that doesn't exist, it is left out and listed in the PR body as a follow-up. It is never faked.
     - **KPI comparisons.** Where the KPI's endpoint takes `from/to`, the "vs previous 24 h" delta comes from the same endpoint over the previous window. Otherwise the card shows its window as a source note, which KpiCard's README allows.
     - **Device-type icons.** Mapped from the existing `category` field. Anything unknown gets the generic `devices` icon.
     - **Alert text.** The plain-language alert title, explanation and "What to do" come from fields the alert APIs already return: the enrichment description and recommendation. Where a field is absent, the row shows the category label over the raw signature, and the What-to-do box says "No specific advice for this alert yet." It never invents advice.
     - **Severity buckets.** One pure adapter, `severityBuckets()` in `web/src/lib/utils/severity.ts`, feeds every severity summary and gauge.
       - **Buckets:** taken only from severity fields the API returns. `getAlertCount` gives `high`, `medium` and `low`, and `info = max(0, total − high − medium − low)`. The buckets are mutually exclusive and sum to `total`.
       - **Critical:** shown only where an API returns a critical severity field. It is never derived from a category: today's `criticalCount` comes from the `malware-c2` category (`alerts/+page.svelte:157`) and overlaps High.
       - **Category counts stay categories.** "Malware / C2" remains a category figure on its own card.
       - **Zero total:** the gauge draws 36 neutral `surface-3` ticks and the centre reads 0.
       - **Failed request:** the card shows the error state, not a gauge.
       - **Tests:** the partition sums to total, info is clamped at 0, the zero case, and the failure case.
     - **Series aggregation.** One pure adapter, `topSeries(items, 6)` in `web/src/lib/utils/series.ts`. It applies only where colour must identify a series: donuts and stack bars.
       - **Bar lists are never aggregated.** Every item keeps its own row, link and filter action, as Home's traffic categories do today (`+page.svelte:946`). Labels identify the bars, which use one colour (`data-1`) unless the page passes six or fewer coloured items.
       - **Up to six items:** shown as-is, coloured `data-1..6` in order.
       - **More than six:** the top five keep their identity (key, label and callbacks) and take `data-1..5`.
       - **The remainder** gets the reserved key `__rest__`, the label "Everything else" and `data-6`. It can't be confused with a real `other` category.
       - **The legend** lists the remainder's constituent items in an expandable `.kv` list, each with its original link or filter action.
       - **Totals** are preserved, and ties break by label.
       - **Tests:**
         - more than six items, ties and zeros
         - a real `other` category alongside the synthetic remainder
         - the original keys reaching the callbacks, including from inside the expanded remainder
2. **Behaviour is preserved.**
   - Every request, action, filter, sort, drawer, form, route and redirect stays.
   - **Dropped on purpose**, because the system has no such element. Each is listed in the PR body:
     - the sidebar collapse toggle
     - map zoom and pan
     - the Home device grid and its filter bar, which move to Devices (§3)
   - **Kept** even though the system's top bar lacks it: the daemon liveness status ("Can't reach NetTap"). It becomes a `sev-high` chip in the top bar, shown only while offline.
   - Tests that assert behaviour stay green unchanged.
   - Tests that asserted old markup, class names or old strings are updated, and each one is listed in the PR body.
3. **Copy follows the system's Voice rules:**
   - sentence case, UK spelling, the error and empty patterns, the `·` joiner, and card subtitles that state unit and window
   - no emoji and no exclamation marks
   - Daemon-supplied text (signatures, descriptions) is shown as received.
4. **No new runtime dependencies, and nothing loaded from a CDN.**
   - The Google Fonts `@import` at the top of `bundle.css` is dropped, since the fonts are already bundled by PR #165.
   - Leaflet is removed, because its only consumer, `GeoMap`, is replaced (§5.3).
5. **Accessibility follows the system:**
   - every interactive element gets the focus outline
   - `aria-sort` on sortable headers
   - `aria-pressed` on pills
   - `role="img"` and a headline `aria-label` on every chart
   - an `aria-label` on every icon button
   - severity always shown with colour, shape and word
   - motion stops under reduced motion, and the live feed starts paused there
   - text at 4.5:1 or better on every surface in every theme
6. **Checks.**
   - **Before opening the PR:**
     - `cd web && npx vitest run`
     - `npx svelte-check` (0 errors)
     - `npm run check:colors`
     - `npm run check:e2e`, which is a type check only
     - `npm run test:visual`
     - **`npx playwright test`**: the existing behavioural browser suite in `web/e2e/*.spec.ts` (login, dashboard, setup wizard), plus the new flows in §7. It is executed, not just type-checked.
       - **Config fix:** `playwright.config.ts` gets `testMatch: '*.spec.ts'` and `testIgnore: ['visual/**', '**/*.test.ts']`. `e2e/fixtures.test.ts` is a Vitest file and must not be collected. Collection is verified with `npx playwright test --list`.
       - **Isolation:** the suite is split into two projects, each with its own server instance and its own `mkdtemp` data directory, created when the config loads, following the visual harness:
         - **`auth`**: an account is created in setup, then the login, logout and dashboard specs run.
         - **`firstrun`**: the setup-wizard spec runs. Its directory reset touches only its own directory.
         - Neither can delete or create the other's users.
     - `cd daemon && python -m pytest` (failure set unchanged from the baseline)
   - **Before merging:** CI.

## 5. Architecture

### 5.1 Styles

| File | Content |
|---|---|
| `web/src/lib/styles/tokens.css` | The system's `tokens.css` verbatim. Its selectors are `:root, [data-theme="ember"]`, `[data-theme="graphite"]` and `[data-theme="spectrum"]`. The file also holds the `@font-face` rules. It is the only file allowed colour literals, and the colour gate exempts it by path (this replaces the `TOKENS START/END` marker). |
| `web/src/lib/styles/system.css` | `components/bundle.css` verbatim, minus the font `@import`. All system classes are global: `.app`, `.shell`, `.sidebar`, `.card`, `.grid`, `.c-*`, `.pills`, `.btn`, `.sev`, `table`, and so on. |
| `web/src/lib/styles/forms.css` | **The one extension.** The system has no inputs, selects, checkboxes, toggles, textareas or form layout, but Settings, Setup, Tools and the lookups need them. They are built only from tokens and system shapes: a 36 px `surface-1` field, a `line` border that brightens to `line-strong` on focus, `r-pill` single-line fields, `r-md` textareas, and labels in `type-label`. Tabs reuse Pills. It is documented in `DESIGN-SYSTEM.md` as an extension. |
| `web/src/lib/styles/global.css` | **Rewritten in step A**, not just trimmed. Every legacy component class goes: they collide with system class names (`.card`, `.btn`, `.grid`, `.pill`, `.pills`, `.mono`, `.sr-only`, `.badge-*`, `.data-table`, `.stat-card`, `.page-header`, …). The legacy base and reset rules go too: the root `font-size: 14px` at `global.css:282` (the system's rem scale assumes the browser's 16 px root), and the legacy `a`, heading, scrollbar and selection rules. What stays: the legacy token aliases (`--bg-tertiary`, `--cyan`, `--space-*`, …), only until the last page is migrated and deleted in step C, and app-wide rules the system lacks (scrollbar colour from tokens, `::selection`). |
| `web/src/lib/styles/a11y.css` | **Documented accessibility overrides.** The system wins on looks, but not where its CSS removes a required behaviour. Each override names the bundle line it corrects. The entries:<br>1. `bundle.css:148` sets `outline: 0` on the search input, so the system's focus rule moves to `.search:focus-within` (2 px `focus` outline).<br>2. `bundle.css:52` styles the selected pill only for `aria-pressed` or `aria-current`, so `.pill[role="tab"][aria-selected="true"]` gets the same `pill-active-bg` / `on-light` rule, and the Pills tabs mode shows its selected tab.<br>3. `DeviceList` select mode: `.dev[aria-pressed="true"]` gets the selected-row style (`surface-2` fill, `line-strong` ring, the AlertRow `aria-current` look).<br>Harness tests check the computed selected styles in all three themes. |

**Import order** (once, in `+layout.svelte`): `tokens.css` → `system.css` → `forms.css` → `a11y.css` → `global.css`. Step A checks the computed styles of representative elements against the system previews: body font-size 14 px from `--text-base` at a 16 px root, `h1.page-title` at 28 px Sora 500, `.card` padding 20 px, and table header 12 px.

**Theme attribute.** It is renamed from `data-variant` to `data-theme` to match the system. This touches:
- the bootstrap script in `app.html`
- `stores/theme.ts` and its tests
- `ThemePicker`: its swatches put `data-theme="…"` on the swatch element, which works because the system's selectors are not `:root`-only. `data-theme-preview` is dropped.

The storage key `nettap-theme`, the validation and the write order from PR #165 stay. Ember remains the fallback.

**Data colours.**
- The system defines `data-1..6`. PR #165's `data-7/8` are dropped.
- Charts with more than six series go through `topSeries()` (§4.1).
- **`CATEGORY_COLORS`** stays a static map, used only where a page shows a fixed, small category set. Its entries become `data-1..6`, and any category past six uses `text-3` together with its label.

### 5.2 Icons

- **`web/src/lib/components/ui/Icon.svelte`.** Its `name` prop takes one of the 48 asset names. It renders `<svg class="ic" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">` with the path data copied from `nettap-design-system/assets/Icons/<name>.svg`.
- **Drift test.** A unit test reads the asset folder and fails if the icon map and the folder differ in names or path data.
- **What it replaces:** the layout's inline `{#if item.icon === …}` chain, and every emoji or ad-hoc icon in routes and components.

### 5.3 Components (`web/src/lib/components/ui/`)

- **Markup:** each component emits the system's markup and classes, with no scoped styles beyond layout glue the system lacks.
- **Tests:** each gets a vitest + Testing Library test covering rendering, its ARIA attributes and its states. Plain buttons, links, chips and tags stay HTML with system classes (`.btn`, `.btn.primary`, `.icon-btn`, `.link`, `.chip`, `.tag`); there is no wrapper for those.

| System component | Svelte | Notes |
|---|---|---|
| Card | `Card.svelte` | Props: `title`, `sub`, `hero`, `col`. Snippets for the head-right area, the body and the foot. |
| CardStates | `CardState.svelte` | **Loading:** skeleton, `aria-busy` and `role="status"`. **Empty:** icon tile, heading, sentence, one action. **Error:** `role="alert"` and a "Try again" button wired to a retry callback. Minimum height 230 px. |
| KpiCard | `KpiCard.svelte` | Label, icon, value and unit, an optional delta chip (with a "bad when up" flag), a sub line, and a foot snippet (Sparkline or StackBar). |
| Pills | `Pills.svelte` | Options, value and `onchange`, inside `role="group"` with an `aria-label`; the selected option has `aria-pressed`. There are two other modes. **`mode="tabs"`** (in-page sections such as Settings) follows the WAI-ARIA tabs pattern: `role="tablist"`, `tab` and `tabpanel`, `aria-selected`, `aria-controls` and `aria-labelledby`, a roving tabindex and arrow, Home and End keys. **`mode="nav"`** links between routes with `aria-current="page"`. |
| SeverityPill | `SeverityPill.svelte` | Level → shape SVG + word. `.sev-count` tile variant. |
| Chip | `LiveChip.svelte` only | Live / Paused with the dot. Other chips are HTML. |
| SearchField | `SearchField.svelte` | Top-bar (40 px) and toolbar (36 px) sizes, with a visually hidden label and a stable id. |
| DataTable | `DataTable.svelte` | Columns (label, numeric flag, sort key, cell snippet), rows, initial sort and `aria-label`. Sorting reuses `utils/table-sort.svelte.ts`, which keeps the rule that every column sorts. Optional `.tbl-foot` pager with the light current page. Optional `onrowactivate` for drawers. A row that opens something has a real `<button>` in its first cell, carrying the row's accessible name, so Tab, Enter and Space work.
- **Forwarding:** a mouse click elsewhere on the row is forwarded to that button **only** when every one of these holds:
  - the event's `defaultPrevented` is false
  - the target is not inside the activation button itself, which already fires
  - the target is not inside a nested interactive element (`a`, `button`, `input`, `select`, `textarea`, `label`, `[role=button]`, `[role=link]`, `[tabindex]`)
  - the current text selection is empty
- So Suppress and False-positive buttons (`alerts/+page.svelte:1141`), links and context menus in cells keep working on their own.
- **Tests:**
  - each nested control fires only its own action
  - a row click activates exactly once
  - keyboard activation of the button activates exactly once
  - selecting text in a cell does not activate Wrapped in `.tbl-wrap`. Server-sorted tables (Connections, Alerts) pass a sort-change callback and keep their current server-side behaviour. |
| BarList | `BarList.svelte`, `Meter.svelte` | `.bars` scaled to the largest value; `.meter` with `role="meter"`; `.kv` legend list. |
| DeviceList | `DeviceList.svelte`, `DeviceTile.svelte` | Two row modes. **`mode="link"`** (default) links each row to the device page. **`mode="select"`** makes each row a `<button aria-pressed>` that calls `onselect(item)`. It is used by Live's top talkers, which filter the feed today through `setDeviceFilter` (`live/+page.svelte:310`) instead of navigating. Rows show a mini bar, or a sparkline variant for Live. The tile maps the device category to an icon. |
| StatStrip | `StatStrip.svelte`, `Pipeline.svelte` | `.stats`; `.pipe`, with a healthy or failing state per stage (a failing stage shows a `sev-high` warn icon in place of the `ok` check). |
| AlertRow | `AlertRow.svelte`, `AlertGroup.svelte` | A six-column button with `aria-current`, group head and plain sentence, and `.hide-sm` columns. |
| AlertDrawer | `AlertDrawer.svelte` | **Fixed order:** pill and close, title and wrapped signature, explanation, `.todo`, `.facts`, actions. Escape closes it. **Migration source:** the drawer that is rendered today, `DetailDrawer` + `drawer/content/AlertDrawerContent` (`alerts/+page.svelte:1183`) and that page's action handlers. `AlertDetailPanel` is already replaced there and is not the source. **Preservation checklist**, written into the PR body and covered by interaction tests (each tab or section, every copy button, every action and its error state, every destination link):<br>• Related Events<br>• Raw JSON<br>• copy buttons<br>• acknowledge / suppress / false-positive<br>• the device, connections, PCAP and lookup links<br>The system's fixed order covers the summary. The extra sections sit below the actions, as collapsible `.eyebrow` sections. |
| Charts | `AreaChart`, `Donut`, `SeverityGauge`, `Ring`, `Sparkline`, `StackBar`, `Radar`, `DotMap` (all in `ui/charts/`) | Rules in §5.4. |
| Sidebar, top bar | `Sidebar.svelte`, `TopBar.svelte` | §5.5. |

**Existing components replaced.** Markup and CSS are deleted; logic is moved, and replaced logic keeps OLD CODE markers:
- **Charts:** `TimeSeriesChart`, `DualSeriesChart`, `DonutChart`, `ProtocolDonut`, `TopTalkersChart`, `HorizontalBarList`, `TopConsumers`
- **Live:** `LiveStatsRibbon`, `LiveConnectionTable`
- **Map:** `GeoMap` (Leaflet), replaced by `DotMap`
- **Other:** `DashboardFilters`, `DeviceGrid`, `Breadcrumb` (replaced by the system's `.back` link)

Consumers move to the new components.

**Restyled in place to the chart rules** (the system has no spec for these): `DetailDrawer` and `drawer/*` (they become cards in the AlertDrawer style), `ConnectionDrawer`, `Collapsible`, `NotificationBell` (an `icon-btn` with `badge-dot`), `SankeyDiagram`, `NetworkMap`, `SessionTimeline`, `setup/*`, `golive/*`, `tshark/*`, `ContextMenu`, `IPAddress`, `NewDeviceBanner`, `BridgeStatus`, `CaptureHealthPanel`, `StorageTierPanel`.

### 5.4 Chart rules (from the system README and the Charts README)

- **Area.**
  - 2 px lines with round caps.
  - **Curve:** monotone cubic (Fritsch–Carlson), so it never overshoots below zero or above neighbouring peaks.
  - **Fill:** the series colour, from 32 % at the top to 0 at the baseline.
  - **Grid:** gridlines in `line`; every one above the baseline is dashed `2 5`.
  - **Axis:** labels in `type-axis` and `text-3`, on round steps of 1, 2, 2.5 or 5 × 10ⁿ.
  - **Headline point:** marked with a `band` column, dots ringed in `bg`, and a pill tooltip.
  - **Hover:** the tooltip follows the pointer, with a dashed `line-strong` guide.
  - **Width:** redraws to its container's width (`ResizeObserver`).
- **Donut.**
  - 12 px strokes with gaps between segments, and the total in `type-stat` at the centre.
  - The geometry rules and the regression matrix are carried over from the old plan (`c8267af:PLAN.md` §6, PR 3):
    - each gap is bounded by its own share
    - butt caps on short segments
    - zero values not drawn but keeping their original index
    - a single segment draws the full ring
- **Severity gauge:**
  - **Input:** the buckets from `severityBuckets()` (§4.1).
  - **Ticks:** 36 over 270°, allocated by share with largest-remainder rounding, so they sum to 36. Any non-zero bucket gets at least one tick.
  - **Zero total:** 36 neutral ticks.
- **Ring:** one accent arc over a `surface-3` track.
- **Sparkline:** an accent line, with an optional band window and ring dots at both ends.
- **StackBar:** rounded segments with a 6 px minimum and a legend.
- **Radar:** used only where a page already has scored factors.
- **DotMap** (contract):
  - **Land dots:** a dot grid of `map-dot`. The dots are computed once on mount from the already-bundled `static/geo/countries-110m.geojson` (point-in-polygon on a fixed lat/lon grid, equirectangular projection).
  - **Destinations:** a hotspot per destination country, from the data Live already has. Its size scales with that country's share.
  - **Home ring and arcs:**
    - **Shown only when a real home location is supplied.** The prop is `home: {lat, lng} | null`.
    - **Today nothing supplies one.** Live's `DEFAULT_HOME` (`live/+page.svelte:33`) is a hard-coded centre of the continental US, so it is deleted (OLD CODE) and Live passes `null`. The map then shows hotspots only, with no "Your network" marker and no arcs.
    - **Follow-up:** auto-detecting the home location is listed in the PR body, not built.
  - **Country selection is preserved:**
    - **Mouse:** clicking a hotspot calls the same `onclick(country)` toggle that `GeoMap.svelte:274` calls today.
    - **Keyboard:** each hotspot is a focusable SVG element (`role="button"`, `tabindex="0"`, an `aria-label` with the country and connection count, `aria-pressed` for the selected state) and activates on Enter and Space.
    - **Selected state:** an `accent-strong` ring.
    - **Tests** cover mouse, keyboard and toggling.
  - **Reduced motion:** the arcs, when there are any, are static. The `arc-scheduler` split from PR #165 is reused.
  - **Accessibility:** it is SVG, so `aria-label` works.
  - **Leaflet:** the package is removed.
- **Every chart:** `role="img"` and an `aria-label` that states the headline, for example "Busiest hour 21:00, with 4.7 GB downloaded".
- **Chart maths** lives in `ui/charts/geometry.ts`, as pure functions with unit tests.

### 5.5 Shell (`+layout.svelte`)

**Structure:** a skip link, then `.app` (the container-query root) holding `.shell` (`nav.sidebar` and `main.main#main`). There is no shell on `/login`, `/setup` or `/go-live`, as today.

**Sidebar (`Sidebar.svelte`):**
- **Brand:** the SVG mark (accent square, `on-accent` tap line and dot) and "NetTap" in Sora 600.
- **Mode chip:** "<Mode> mode · <interface>".
  - **Mode and interface** come from `getCaptureMode`, which the shell already calls.
  - **Health** comes from `getCaptureHealth` (`status`: `normal | degraded | down | not_configured`). This is an existing client the shell didn't call before, and it is listed in the PR body.

  | Health | Dot | Chip text |
  |---|---|---|
  | `normal` | `ok`, pulsing | "<Mode> mode · <iface>" |
  | `degraded` | `sev-medium`, static | "<Mode> mode · degraded" |
  | `down` | `sev-high`, static | "Capture stopped" |
  | `not_configured` | `text-3`, static | "Capture not set up" |
  | request failed or unknown value | `text-3`, static | "Capture status unknown" |

  - Each call fails independently: a failed mode call still allows the health to show, and the other way round.
  - Tests cover every row.
- **Nav groups** with system icons and the same 17 hrefs:
  - **Overview:** Home, Live Monitor, Bandwidth
  - **Investigate:** Alerts, Threats, Connections, Log Explorer, DNS Analytics, Certificates, PCAP Search
  - **Devices:** Devices, IoT & LAN, Changelog
  - **System:** Infrastructure, System, Tools, Settings
- **Current link:** `aria-current="page"`, including on nested routes.
- **Alert count:** a `.count` badge on Alerts, from the shared alert-count helper (§4.1).
- **Foot:**
  - **Storage meter:** from `getStorageStatus`. It shows "N% used", then "X GB free · R-day retention", where the retention shown is the one that endpoint reports.
  - **User:** the signed-in username.
    - **Source:** a new root `web/src/routes/+layout.server.ts` that returns only `{ username: locals.user?.username ?? null }`. It never dereferences a missing user and never redirects. Authorisation stays entirely in `hooks.server.ts`.
    - **Public and first-run routes** keep working: Login, public tools and lookups, Setup and Go Live.
    - **No username:** the user row is hidden, and the sign-out button still shows for an authenticated shell.
    - **Tests:** the load with an authenticated user, an anonymous user and a first-run state. It must never throw and must never return anything beyond the username.
    - This is the only server change.
  - **Sign out:** a ghost sign-out icon button inside the existing POST `/api/auth/logout` form.

**Top bar (`TopBar.svelte`):**
- **Search:** a `SearchField` wired to the existing `search.ts` client (`executeSearch`, `getSearchSuggestions`), reusing `SearchBar.svelte`'s logic, which has no consumer today.
  - **Shortcut:** ⌘K / Ctrl-K focuses it.
  - **ARIA:** the WAI-ARIA 1.2 combobox pattern: `role="combobox"`, `aria-expanded`, `aria-controls` pointing at a `role="listbox"`, and `aria-activedescendant`.
  - **Keys:** Down and Up move through results, Enter opens one, and Escape closes the list and then clears the field.
  - **States:** results, no results ("No matches for "x"") and error, each announced in a polite live region.
  - **Tests:** keyboard flow and states.
- **Page refresh contract** (`web/src/lib/stores/pageRefresh.ts`). Most pages fetch in `onMount` or effects, not in load functions, so `invalidateAll()` would not refresh them.
  - **Registration:** a page calls `registerPageRefresh(fetchFn)` from its setup. The returned handle is cleared automatically on destroy.
  - **Result contract.** "Resolved without throwing" is not success: Home uses `Promise.allSettled` and fires requests it doesn't await (`+page.svelte:186–282`), and Live's loader returns early while paused (`live/+page.svelte:137`). So `fetchFn` must return `'ok' | 'partial' | 'failed' | 'skipped'`, after awaiting **every** request that feeds the page's visible data.
    - Each migrated page's loader is changed to await its requests and compute that result from what actually succeeded. This is a logic change, made with OLD CODE markers.
    - **`ok`** advances `updatedAt`.
    - **`partial`** advances nothing and shows "Some data failed to refresh" beside the timestamp.
    - **`failed`** advances nothing and the page shows its error state.
    - **`skipped`** (paused, hidden tab) changes nothing.
  - **Request generations.** Today a slow 24 h request can land after a newer 1 h one and overwrite it (for example Connections, whose loads write state at `connections/+page.svelte:357` and `:396`, and whose range change starts a new load at `:427`). Every migrated loader therefore follows one contract, through a tiny helper `createLoadGuard()` in `pageRefresh.ts`:
    1. **Snapshot first.** At the start of each load, `const g = guard.begin()` increments the generation, and the loader copies the immutable query parameters it needs (range, filters, page and sort) into locals before the first `await`.
    2. **Check before writing.** Before **every** state write after an `await`, the loader checks `guard.current(g)`. A stale generation writes nothing and returns `'skipped'`. The check sits inside the loader, at each write, not only on the return value.
    3. **Any new load invalidates older ones.** A query change starts a new load, which is a new `begin()`.
    4. **Unregistering invalidates too.** `registerPageRefresh`'s cleanup (on destroy or navigation) calls `guard.invalidate()`, so a pending load can never update page state, `updatedAt` or the refresh status after the page has gone.
    5. **The wrapper honours the guard.** It updates `updatedAt` and status only while the guard and the registration are both still current.
  - **Tests,** with deferred promises against the real loaders of Home, Connections, Alerts and Live:
    - responses completing in reverse order: only the newest data is shown
    - a filter change during a refresh: the older result is dropped and the controls and data agree
    - navigation before completion: no writes and no `updatedAt` change after destroy
  - **Top-bar Refresh** calls the registered function. Filters, sort and pagination are untouched, because the page's own fetch function reads its current state.
  - **"Updated N s ago"** shows that page's `updatedAt`. It is never the shell's poll time.
  - **Pages without a registration** (forms, tools) hide both the button and the timestamp.
  - **Existing page-level auto-refresh** (Home's 30 s Auto toggle, Live's 3 s loop) goes through the same wrapper, so the timestamp is honest.
  - **Tests:**
    - **Store:** Refresh calls the page's function once and keeps the current filters. Each result value moves `updatedAt` only as specified. Navigating away unregisters the function.
    - **Integration, against the real page loaders** of Home, Live, Connections and Alerts with mocked API clients:
      - all requests succeed → `ok`
      - one request fails → `partial`
      - all fail → `failed`
      - a request still pending → the loader has not returned yet
      - Live paused → `skipped`
- **Notifications:** `NotificationBell`.
- **Daemon status:** the existing liveness check (`/api/system/ping` every 30 s) stays. While it is offline, a `sev-high` chip reads "Can't reach NetTap".

**Polling.**
- The existing 30 s ping loop also refreshes the capture health, the alert snapshot (§4.1) and storage. The mode is fetched once, as today.
- Each piece fails independently: a failed call hides that element's value and shows "—"; it never throws.
- Polling pauses while the tab is hidden.

**Below the 760 px container width:**
- `.m-top` shows the brand, the page title and a menu button (`aria-expanded`, `aria-controls`).
- The sidebar opens as a drawer over the scrim.
- **Focus:** opening moves focus to the first link, and Tab stays inside the drawer.
- **Closing:** Escape, the scrim, choosing a link, or growing past 760 px all close it. Focus returns to the button.

### 5.6 Page recipe and mapping

**Recipe (system Layout section), top to bottom:**
1. **`.page-head`:** the title (`type-page-title`), a one-line sub, and head actions, including time-range Pills wherever the page already has a time range.
2. **KPI row:** at most four `KpiCard`s in `c-3`, or three in `c-4`.
3. **Hero chart and side card:** one hero chart card in `c-8` (or `c-7`) beside a narrower card in `c-4` (or `c-5`).
4. **Detail cards and tables.**

**Per card:**
- Every card has a title and a sub that states the unit and the window.
- Every data card shows `CardState` for loading, empty and error.
- At most two hero cards per screen.

| Route(s) | Target layout |
|---|---|
| `/` Home | **Clean, with no device cards (§3).** KPIs: Bandwidth, Connections, Alerts and Devices. These are four of today's five stat cards, using the deltas Home already computes from `prevTimeParams`. Devices shows "N new today" as an `is-ok` chip.
  - **Source:** the existing `getNewDeviceCount(since)` client, with `since` set to local midnight. It is not the registry's `is_new` flag, which the daemon clears on later updates (`device_registry.py:203`), and not the capped registry list.
  - **Zero:** no chip.
  - **Failed request:** no chip and no number. The KPI value itself is unaffected.
  - **Tests:** the midnight boundary (a device first seen at 23:59 yesterday vs 00:01 today), zero, failure, and that later updates to a device don't change the count. System Health moves into the Pipeline strip. Bandwidth-over-time AreaChart hero `c-8` + Network protocols Donut `c-4`; Traffic categories BarList; Top devices DeviceList, five rows, the system's compact list, with "View all devices" linking to `/devices`; Alert summary with the severity gauge; capture Pipeline strip (replaces `CaptureHealthPanel` on Home). Removed from Home: `DeviceGrid`, `DashboardFilters` (its time range becomes head Pills. Its device and protocol filters are stored but never applied to any request, since only `from/to` are read at `+page.svelte:175`, so they are dropped rather than moved, and listed), `NewDeviceBanner`, and the mirror-mode "Device Overview" header. |
| `/devices` | Gains the device cards from Home: Pills "By type" / "All devices". **By type** is the redesigned `DeviceGrid`: system cards grouped by device type, with DeviceTile, name, IP in mono, traffic, and the same `deviceCards` data and `registry-traffic` merge Home used. **All devices** is the existing table as a DataTable. `NewDeviceBanner` moves here. By type loads the registry and traffic exactly as Home did, with the same calls, the same mirror-mode condition and the same failure messages. |
| `/alerts`, `/alerts/[category]` | Severity summary (`.sev-sum`: sev-count tiles + gauge); Pills "By category" / "All alerts"; grouped AlertRows, sorted by severity then count; sticky AlertDrawer `c-4` (below the list under 1100 px) |
| `/threats` | KPI row; threat cards and DataTable; SeverityPills |
| `/connections` | Hero StatStrip (Sessions, Data, Destinations, Devices); toolbar (SearchField, protocol Pills, filter buttons); DataTable with `.who`, `.tag`, `.bytes`, `.res`; ConnectionDrawer |
| `/live` | Page head with LiveChip and pause; StatStrip; DotMap hero + Top talkers (sparkline DeviceList in `select` mode); live feed DataTable (`tr.new` flash, paused under reduced motion). **All three existing filters are kept:**<br>• **Country:** DotMap hotspots.<br>• **Protocol:** protocol Pills in the feed toolbar, wired to the existing `setProtocolFilter` (`live/+page.svelte:296`). They replace the protocol donut's click-to-filter; the donut stays for display.<br>• **Device:** top-talker rows, wired to `setDeviceFilter`.<br>Active filters show as removable chips with "Clear filters". Tests cover each filter alone, all three combined, toggling one off, and clearing. |
| `/bandwidth`, `/traffic/[category]` | KPIs; AreaChart hero; category BarList; top devices; DataTable |
| `/dns` | KPIs; lookups AreaChart; top domains BarList; DataTable |
| `/certificates`, `/logs`, `/pcap`, `/changelog` | Toolbar + DataTable (Changelog: event list in cards); actions as `.btn` |
| `/iot` | KPIs; DataTable with `.who` and DeviceTile; IoT trust Ring and score-rows |
| `/devices/[ip]`, `/devices/mac/[mac]` | `.back` link; identity hero (72 px tile, chips, `.ident-meta`); trust Ring + score-rows; charts; tables |
| `/infrastructure`, `/system`, `/system/updates`, `/system/cyberchef` | Pipeline strip; cards with `.kv`, Meter and DataTable |
| `/settings` (+ `backup`, `notifications`, `suricata-rules`) | Pills as section tabs; form cards (`forms.css`); ThemePicker |
| `/tools` (+ 9 tools), `/lookup/*`, `/geoip/[ip]` | Tools index as a card grid (icon tile, title, one line); each tool is a form card plus a result card with `.facts` / DataTable |
| `/investigations`, `/compliance` | KPIs; cards; DataTable |
| `/login` | Centred card: brand, form, error state |
| `/setup`, `/go-live` | Wizard in cards; Pills step indicator; same steps, actions and redirects |

The exact KPIs and cards per page are chosen from what each page already loads. A row in the table that names data a page doesn't have is dropped for that page under §4.1, not built.

## 6. Work order

**Branch:** `feature/ui-redesign-full`, cut from the tip of `feature/ui-redesign-foundation` (`c8267af`, PR #165). This is the only branch.

**Step A — foundation, components and shell (lead):**
1. Commit `nettap-design-system/` as-is.
2. Add `tokens.css`, `system.css` and `forms.css`; rename the theme attribute; delete the legacy component classes; drop `data-7/8`.
3. Build `Icon` and every `ui/` component, with tests.
4. Restyle or replace **every shared component in `web/src/lib/components/**`** listed in §5.3. Move each helper off removed tokens (`category-colors.ts`, `api/logs.ts` `protocolColor`, `thresholds.ts`, and any others the gate finds). Add the adapters (`severity.ts`, `series.ts`) and the stores (`alertSnapshot.ts`, `pageRefresh.ts`).
5. Build the shell and `+layout.server.ts`, with tests.
6. Migrate the harness infrastructure (§7).
7. Run vitest and svelte-check, then `/ponytail-review` and `/deep-review` on the staged diff, then commit.

After step A, every shared contract is frozen before any page agent starts.

**Step B — pages, in parallel:**
- **Who:** agents in isolated worktrees branched from step A's commit. Each owns a disjoint set of route folders plus that folder's tests and visual fixtures:
  - B1: Home
  - B2: Alerts and Threats
  - B3: Connections, Live, Bandwidth and traffic
  - B4: DNS, Certificates, Logs, PCAP and Changelog
  - B5: Devices and IoT
  - B6: Infrastructure, System and Settings
  - B7: Tools, lookups and GeoIP
  - B8: Login, Setup, Go Live, Investigations and Compliance
- **File ownership:**

  | Files | Owner |
  |---|---|
  | `web/src/lib/**` (components, `ui/`, styles, utils, api, stores) | lead only |
  | `web/src/routes/+layout*` and `web/src/app.html` | lead only |
  | `web/e2e/visual/{harness,routes,known-issues,fixture-daemon}.ts`, the configs, `web/scripts/` | lead only |
  | `web/e2e/visual/fixtures/<route>.ts` and the specs for a batch's routes | that batch's agent |
  | `web/src/routes/<batch folders>/**`, including their tests | that batch's agent |
  | `nettap-design-system/` | nobody (the spec; read-only) |

- **Rules for agents:**
  - An agent that needs a shared change stops and reports it. The lead makes the change once on `feature/ui-redesign-full`.
  - Every open agent branch then rebases onto that commit before its work is accepted.
  - Agents don't run `git stash`.
  - Each agent runs vitest for its routes plus `svelte-check` before it reports back.
- **Merging:** the lead merges each worktree branch into `feature/ui-redesign-full` one at a time. After **each** merge, on the merged result, the lead:
  1. runs the **full** vitest and `svelte-check`
  2. runs the visual harness for that batch's routes
  3. reviews the diff against the recipe and the conformance checklist (§7)

  A batch is accepted only when all three are green. `/ponytail-review` and `/deep-review` run per accepted batch.

**Step C — cleanup and verification (lead):**
1. **Delete leftovers:** the legacy token aliases, the replaced components and the Leaflet dependency.
2. **Extend the colour gate.** It fails on:
   - legacy token names (`--bg-*`, `--cyan`, `--space-*`, `--radius-*`, …)
   - emoji code points in `web/src`
3. **Harness:** add populated, slow and stale fixtures for every route (every page changed).
4. **Full checks:** the full check list (§4.6).
5. **Docs:** update `DESIGN-SYSTEM.md`, `CLAUDE.md`, the tracking doc and Linear.
6. **G11 deploy.** Update `scripts/remote/deploy-ui-redesign.sh`:
   - **Branch:** `BRANCH="feature/ui-redesign-full"`.
   - **Token check:** look for the new theme contract (`[data-theme="graphite"]` in the served CSS, plus the `nettap-theme` bootstrap). This replaces the `data-theme-preview` check at line 79.
   - **Record the SHA first:** before updating, write the currently deployed SHA to `/home/nettap/.nettap-last-deploy`.
   - **Rollback path:** add `scripts/remote/rollback-ui-redesign.sh`. It reads that file (or takes a SHA argument), runs `git fetch origin` and `git checkout --detach <sha>` with no `git pull`, rebuilds `nettap-web`, recreates it, and runs the same health checks.
   - **Test the rollback before the real deploy.** `bash -n` both scripts, and check the rollback's SHA resolution and command sequence locally in a scratch clone.

   The owner deploys, then I check every page in Chrome on the G11 with real data in all three themes.

**Merge:**
- One PR from `feature/ui-redesign-full` into `main`. It contains PR #165's commits, so PR #165 is closed as superseded.
- **Pre-merge review:** a two-angle review (`security-engineer` + `typescript-reviewer`), because the shell touches the logout form and the layout's server load.
- **Merge method:** squash, after `gh pr checks` and the owner's G11 approval.
- **After merge:** the deploy script goes back to `BRANCH="main"`.

## 7. Verification

- **Unit (vitest):**
  - every `ui/` component (render, ARIA, states, callbacks)
  - the Icon drift test
  - chart geometry:
    - the monotone cubic never goes below 0 for non-negative data
    - axis steps are always 1, 2, 2.5 or 5 × 10ⁿ, and cover the max
    - the donut matrix (carried over)
    - gauge ticks sum to 36, and every non-zero severity gets ≥1
    - DotMap point-in-polygon on known points
    - empty, single-point, constant and gapped series draw no NaN
  - **shell:**
    - all 17 hrefs and the active state on nested routes
    - the mobile menu's ARIA, focus behaviour and every close path
    - the logout form posts to `/api/auth/logout`
    - each shell value degrades to "—" when its call fails
  - **adapters and stores:** `severityBuckets`, `topSeries`, `alertSnapshot` and `pageRefresh` (the cases in §4.1 and §5.5)
  - **the root layout load:** authenticated, anonymous and first-run
  - **interaction contracts:** DataTable row activation by keyboard, the search combobox, the Pills tabs mode, and DotMap hotspots
- **Behavioural browser suite (`npx playwright test`), executed:**
  - the existing `login.spec.ts`, `dashboard.spec.ts` and `setup-wizard.spec.ts`, with selectors updated only where markup changed
  - **new flows:**
    - **Logout:** a real login, then sign out from the sidebar. Check the session cookie is gone and a protected page (`/alerts`) then redirects to `/login`.
    - **First-run (current behaviour, unchanged):** on an empty user store, `/` redirects to `/setup` and `/setup` is reachable. Anonymous `/login` stays reachable, because it is a public path (`hooks.server.ts:21`) and is excluded from the first-run redirect (line 105).
    - **Navigation:** sidebar navigation to each group, and the phone menu opening, trapping focus and closing.
  - Weak existing assertions found along the way are tightened, not deleted.
- **Colour gate:**
  - exempts `tokens.css`
  - fails on literals, legacy token names and emoji
- **Harness migration (step A, before any page work):**
  - **Theme switching:** `harness.ts:102` sets `data-variant`; it moves to `data-theme`. Each theme run asserts a theme-only computed token (`--accent`) before it takes a screenshot, so mislabelled screenshots fail.
  - **Overflow:** the blanket 390 px overflow exemption in `known-issues.ts:8` is removed. Any remaining exemption names one route and one reason.
  - **Slow mode:** the fixture daemon holds `slow`-mode responses until the test releases them, instead of a fixed 2 s delay. The loading-state assertion and screenshot happen while they are held.
  - **Stale mode:** a success-then-failure sequence. The page loads populated, the next refresh fails, and the assertion checks the stale or error state over the old data.
- **Visual harness** (from PR #165, extended):
  - **Coverage:** every route × Ember, Graphite and Spectrum × 1920, 1440 and 390, in the populated, empty, error and slow modes.
  - **It asserts:**
    - a black body, no horizontal scroll and no console errors
    - the sidebar is visible at 1920 and 1440
    - `.m-top` is visible at 390
    - every page has an `h1.page-title`
  - **Reduced motion:** one pass with reduced motion (Live feed paused, no animations).
- **Design conformance:** I compare every route's 1920 and 390 screenshots against the system rules and previews, using a written checklist:
  - the recipe order
  - card heads with their subs
  - KPI count
  - hero count ≤ 2
  - mono for machine values
  - tabular, right-aligned numbers
  - the light selected pill
  - severity shown three ways
  - copy voice
- **G11 real data:** every page in all three themes, with Home, Alerts and sidebar alert counts equal.
- **Daemon:** pytest failure set unchanged (no daemon files touched).

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Scale: ~42k lines of route markup and 45 pages | Components and shell first, then a fixed recipe, parallel page agents with disjoint ownership, and a conformance checklist per page. |
| Deleting the legacy classes breaks un-migrated pages mid-branch | Expected and acceptable: nothing is deployed until step C, and every page is migrated before the harness and the G11 check. |
| Behaviour regressions while rewriting markup | Behaviour tests stay unchanged and green; the harness covers every route in four modes; the G11 check. Logic moves keep OLD CODE markers. |
| Copy changes break string assertions | Only styling and string assertions change, and each is listed in the PR body. Behaviour assertions never change. |
| Data the system shows doesn't exist (deltas, device types, alert advice) | §4.1: it is left out or shown as a source note, and listed. Never faked. |
| Numbers disagree across screens | One alert-count helper plus a test; the G11 count check. |
| Leaflet removal loses map interaction (zoom, pan) | The system's map is a static dot grid with arcs. Zoom and pan are dropped by design, and that is listed in the PR body. |
| Huge single PR is hard to review | `/deep-review` and `/ponytail-review` per step and per batch, a two-angle review before merge, and one revertible squash commit. |
| The forms extension drifts from the system | Built only from system tokens and shapes, and documented as the only extension. |

## 9. Rollback

- **Fastest:** `bash scripts/remote/rollback-ui-redesign.sh`. It checks out the SHA recorded in `/home/nettap/.nettap-last-deploy` (detached, no pull), then rebuilds and verifies (§6 step C.6).
- **On `main`:** revert the single squash commit. PR #165's work is inside it, so nothing is left half-applied.

The theme key ignores unknown values, so a stale `nettap-theme` falls back to Ember.

## 10. Out of scope

- daemon changes and new endpoints
- light mode
- features the system doesn't show
- the DNS, IoT and certificate totals audit (resumes after the redesign)
