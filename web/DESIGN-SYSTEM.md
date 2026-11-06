# NetTap design system: how the web app uses it

> **Canonical reference for every page.** The design itself (voice, colour, type, layout, every component's look) is the owner's system in `nettap-design-system/`: start with its `README.md`, then `components/<Name>/README.md` and `preview.html` for each component you use. This file says how `web/` implements it, and which rules the build enforces. The full plan behind the 2026-11 redesign is `PLAN.md` at the repo root.

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

- **Sidebar:** 19 links in 4 groups (`nav.ts`), the Alerts count from the shared alert snapshot, the capture chip and storage meter, and Sign out (a `POST /api/auth/logout` form).
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
- **Controls:** `Pills` (toggle, tabs or nav mode), `SearchField`, `LiveChip`
- **Data:** `DataTable`, `BarList`, `Meter`, `Bytes`, `Who`, `ConnResult`, `SeverityPill`, `DeviceList`, `DeviceTile` (with `deviceIcon()` from `device-icon.ts`), `AlertRow`, `AlertGroup`, `Icon` (the system's 48 icons; a test fails if they drift from `nettap-design-system/assets/Icons/`)
- **Charts (`ui/charts/`):** `AreaChart`, `Donut`, `SeverityGauge` (fed by `severityBuckets()` from `utils/severity.ts`), `Ring`, `Sparkline`, `StackBar`, `Radar`, `DotMap`. Chart maths lives in `ui/charts/geometry.ts`.
- **Network flow** (`components/NetworkFlow.svelte`, maths in `ui/charts/flow.ts`): device → protocol → destination on one scale, coloured by protocol only (TCP `data-1`, UDP `data-2`, ICMP `data-5`), with an "Other destinations" node so every column adds up. Devices show their registry name (`utils/device-names.ts`), else their IP. Below 640 px of card width, or when the endpoint's two searches disagree beyond rounding, it shows `NetworkFlowTable` instead, with the reported figures unchanged.

Every chart has `role="img"` and an `aria-label` that states its headline, for example "Busiest hour 21:00, with 4.7 GB downloaded". The Network flow's labels are buttons, so it is a `role="group"` with the headline as its label instead.

## Data on a page

- **Only show numbers the page loads.** Never invent, default or estimate a figure. A failed request shows its error state, never `0`, `0 B` or "No data".
- **Keep the last figures on a failed refresh** and say so: `loadFailed(what, true)` gives "Couldn't refresh … ; showing the last figures loaded." (#96).
- **One source per number.** A number on two screens comes from one place. The alert count is `alertSnapshots` (`stores/alertSnapshot.ts`): Home, Alerts and the sidebar read the same snapshot per window.
- **Refresh contract** (`stores/pageRefresh.ts`): a page that loads data calls `registerPageRefresh(loader)`. The loader awaits every request behind visible data and returns `'ok' | 'partial' | 'failed' | 'skipped'`; `outcome(results)` computes that from `Promise.allSettled`. Auto-refresh loops call the same loader.
- **Load guard:** `const g = guard.begin()`, copy the query (range, filters, page, sort) into locals before the first `await`, and check `guard.current(g)` before every state write after an `await`. A slow, older response then never overwrites a newer one.
- **Partial figures say so** (NET-160): a byte total some records didn't measure reads "at least …" with how many were measured, none measured reads "Not measured", and a list too long to count shows "—" with "too many to count" (`utils/drilldown.ts`).

## Drill-down links (NET-160)

- **Every IP is `IPAddress`** (`components/IPAddress.svelte`): a link to `$ipHref(ip)` (its device page when the daemon's LAN policy says so, `/address/<ip>` otherwise or before the policy loads, `stores/lan.ts`), with its right-click menu beside it. Inside another link or button, or in column 0 of a table with `onrowactivate`, use `linked={false}` (plain text) and make sure the row's drawer links the address.
- **Every domain links with `domainHref(name)`** (`/domain/<name>`), except in column 0 of a row-activated table: put the link in the row's drawer or detail.
- **Never nest a link or button in another.** Page tests call `expectNoNestedInteractive(container)` (`src/tests/nested-interactive.ts`).
- **A count links to a list over the same window.** Pass the window on (`?range=` to Alerts and Log Explorer, `from`/`to` to Certificates), so the list a number opens holds that number.
- **Outside look-ups run on click.** Reverse DNS and WHOIS about an address or name wait for a button: an automatic one tells whoever runs that server that we looked.

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
