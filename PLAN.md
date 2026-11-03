# Plan: NetTap UI redesign (pure black, Ember default)

_Approved by Codex in round 4 (2026-11-03) and signed off by the owner. Review log: `.codex-review/2026-11-03-144402-ui-redesign/`._

## 1. Goal

Replace the web UI's look with the owner-approved design from `mockups/redesign-2026-11/index.html`:

- **Background:** pure black (#000) on every page.
- **Surfaces:** near-black cards with hairline borders, large corner radius and big thin numbers.
- **Charts:** smooth area charts with pill tooltips, rounded donuts and segmented gauges.
- **Navigation:** a grouped sidebar.

### Owner decisions (2026-11-03, final)

- **Variants:** Ember is the default. Graphite and Spectrum ship too, switchable in Settings.
- **Navigation:** left sidebar grouped into Overview, Investigate, Devices and System. On phones it becomes a menu button.
- **Replaced code:** replaced CSS and markup are deleted, with git history as the record. Replaced logic (TS or JS) still follows the OLD CODE START/END policy.
- **Density:** balanced, tuned for a 1920 px monitor. It must still work at 1440 and 390.

## 2. Hard constraints

1. **No behaviour or data changes.** Same API calls, same numbers, same loading, empty and error messages, same sorting, filtering, drawers and actions. This is a visual and layout change only. The data-accuracy work (#144–#148) must not regress.
2. **No new metrics, fetches or shell actions.** If a design idea needs data or behaviour the app lacks, it is dropped or logged as a follow-up, never faked.
3. **No new runtime dependencies.** Charts stay hand-written SVG; Leaflet stays for maps.
4. **Fonts are bundled, never loaded from a CDN.** Today `+layout.svelte` loads DM Sans and JetBrains Mono from fonts.googleapis.com. That goes away.
5. **The rules in `web/DESIGN-SYSTEM.md` keep applying** (the file gets rewritten): tokens only, pages full width, every table column sortable, no hard-coded text colours.
6. **Every PR must pass these locally before opening, and CI before merge:** `cd web && npx vitest run`, `npx svelte-check` (0 errors), the colour gate (§5), the visual harness for the PR's routes (§5), and `cd daemon && python -m pytest` (unchanged).
7. **Gates per PR:**
   - `/ponytail-review`
   - `/deep-review` (each PR is ≥ 200 lines)
   - `gh pr checks` before merge
   - a squash merge
   - Linear issue and tracking doc updated

## 3. Branches

**Each phase gets a fresh branch from an updated `main`**, created only after the previous phase's PR has merged:

| Phase | Branch |
|---|---|
| PR 1 | `feature/ui-redesign-foundation` (the current `feature/ui-redesign` is renamed) |
| PR 2 | `feature/ui-redesign-shell` |
| PR 3 | `feature/ui-redesign-components` |
| PR 4a–4g | `feature/ui-redesign-<batch>` |

Each branch name is recorded in the tracking doc, and the G11 deploy script points at the open PR's branch. No branch is reused after its squash merge.

## 4. Strategy: alias first, then rebuild

The app has 42k lines of route markup across ~45 pages and 48 components. They use the existing token names heavily (`--bg-tertiary` 241×, `--text-muted` 405×, `--accent` 246×, `--cyan` 115× and so on).

- **PR 1 keeps every existing token name and remaps it onto the new palette.** It also moves every use whose meaning a remap would get wrong (severity, info, canvas colours) onto a semantic token. Every page turns black/Ember at once.
- **PRs 2–4 then change structure:** the shell, shared components, then page layouts in batches.

`main` stays deployable after every PR.

## 5. Verification (applies to every PR)

### 5.1 Colour gate (`web/scripts/check-colors.mjs`, added in PR 1, run in the CI "Lint Web" job)

**It scans** `web/src/**/*.{svelte,ts,css}`. It skips:
- tests
- the token blocks in `global.css`
- `// OLD CODE START`–`END` and `/* OLD CODE … */` blocks
- comments

**It fails on** `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb(`/`rgba(`, `hsl(`/`hsla(`, and the named colours `white` and `black` used as colour values.

- **Script palettes** (for example `SERVICE_COLORS` in `routes/+page.svelte:384`) must use `var(--data-*)` strings, or `resolveToken()` for canvas.
- **Allowlist:** a checked-in allowlist holds only the files scheduled for a later PR (`charts/NetworkMap.svelte` and `charts/SankeyDiagram.svelte`, both PR 3). It must be empty after PR 3.

### 5.2 Visual harness (`web/e2e/visual/`, added in PR 1)

It runs the production build against a fixture daemon, using its own config (`web/playwright.visual.config.ts`).

**Fixtures:**
- Typed TS modules in `web/e2e/visual/fixtures/*.ts`. Each response is declared `satisfies` the matching interface from `web/src/lib/api/*.ts`.
- Synthetic data only, never data captured from the G11, because the repo is public.

**Type check:**
- `web/e2e/tsconfig.json` has `"extends": "../tsconfig.json"` and `"include": ["visual/**/*.ts", "../playwright.visual.config.ts"]`. Includes resolve relative to that file. The scope is the new harness only, so existing E2E specs aren't pulled into a new check.
- Relative imports carry the `.ts` extension, which Node's type stripping needs. The inherited `rewriteRelativeImportExtensions` lets `tsc` accept them.
- A new `npm run check:e2e` (`svelte-kit sync && tsc -p e2e/tsconfig.json --noEmit`) runs locally and in the CI "Lint Web" job. PR 1 first confirms it reports zero inputs as an error, not a pass, and that a deliberately wrong fixture fails it.
- Fixture drift fails that command. It does not rely on `svelte-check` finding the files.

**Start-up order.** Playwright starts `webServer` entries before `globalSetup` (`node_modules/playwright/lib/runner/tasks.js:104–108`, Playwright 1.58.2), so nothing the servers need may come from `globalSetup`:
- The temp dirs are created when the config module loads (`mkdtempSync` in `playwright.visual.config.ts`) and passed to each server through `env`. `globalTeardown` removes them.
- The fixture daemon is the first `webServer` entry, so the web instances never start against a missing daemon.

**Fixture daemon:**
- A Node `http` server in `web/e2e/visual/fixture-daemon.ts`, run as `node --experimental-strip-types e2e/visual/fixture-daemon.ts` on port 3199 (Node 22, as used locally and in CI). Its `webServer.url` is `/__fixture/health`. It serves the typed fixtures by daemon path.
- Type stripping only erases types, so the daemon and fixtures use erasable syntax only and `import type` for the API interfaces. `check:e2e` type-checks the same files.
- Its mode is set through a control endpoint (`POST /__fixture/mode`) before each test. The modes:
  - `populated`
  - `empty`
  - `error` (503)
  - `slow` (delayed, so loading states can be captured)
  - `stale`, where a page has a stale-data state
- Because the mode is shared daemon state, the visual config runs serially (`workers: 1`, `fullyParallel: false`). The existing `playwright.config.ts` is unchanged.

**Two isolated web-server instances.** Both are entries in the visual config's `webServer` array, and both point at the fixture daemon through `DAEMON_URL`, with `DAEMON_TOKEN_FILE` set to a temp file. `auth.ts` reads `DATA_DIR` once at module load, so each state needs its own process:

| Instance | Port | Data dirs | Used for |
|---|---|---|---|
| `app` | 3101 | its own `DATA_DIR` and `NETTAP_DATA_DIR` (notifications live in `NETTAP_DATA_DIR`) | Every page except the first-run ones. |
| `firstrun` | 3102 | its own `DATA_DIR` and `NETTAP_DATA_DIR`, never written to by the harness | `/setup` and `/go-live` |

**Getting a real session on `app`.** First run means an empty user store (`isFirstRun()` in `hooks.server.ts:53`), so `app` starts in first run too. A Playwright `auth-setup` project runs first; every other `app` project depends on it through `dependencies`. It:
1. submits the real `createAdmin` action on `/setup` (`setup/+page.server.ts:25`) with a synthetic username and password, and checks it succeeded. The action also signs that context in.
2. throws that context away and opens a fresh one with no cookies
3. in the fresh context, checks that `/setup` redirects to `/login` (setup complete, not signed in)
4. logs in through the `/login` form, checks it lands on `/`, and saves `storageState`

The harness adapts to the app. App behaviour is not changed for it.

No users file is hand-written, so the harness can't drift from the real auth format.

**Each spec:**
- Navigates to the route.
- Fails unless `page.url()` is that route and the page's `h1` (or a route-specific marker) is visible. A redirect to Login or Setup is never accepted as coverage.
- At 1920, 1440 and 390, in all three variants:
  - asserts `getComputedStyle(body).backgroundColor === 'rgb(0, 0, 0)'`
  - asserts no horizontal scroll and no console errors
  - saves a screenshot
- Also runs once with `reducedMotion: 'reduce'`.

**Coverage grows by PR:**
- **PR 1** (global tokens touch every page): every top-level route and every detail route with a fixture id, in `empty` and `error` mode. Also `/login` (logged out), and `/setup` and `/go-live` (first-run data dir).
- **PR 1, populated fixtures:** Home, Settings and Live Monitor. Live is included because PR 1 changes `GeoMap`'s drawing logic; the spec asserts that arcs are drawn, both normally and under reduced motion.
- **Each later PR** adds populated, slow and (where it applies) stale fixtures for the routes it restructures.
- **PR 3** covers every consumer of each restyled shared component.

### 5.3 Real data on the G11

- `scripts/remote/deploy-ui-redesign.sh` follows the CLAUDE.md template, rebuilds only `nettap-web`, and has `BRANCH` set to the PR's branch.
- The owner runs it. I check the PR's pages in Chrome at the device URL in all three variants before merge.
- After merge the script goes back to `BRANCH="main"`.

### 5.4 Contrast and motion

- **Contrast:** text tokens are AA or better on every surface, checked per variant. `--text-3` is ≥ 4.5:1 on `--surface-2`.
- **Motion:** CSS animations are disabled under reduced motion. JS animation (`GeoMap`) keeps drawing and animating separate: under reduced motion the static frame is still drawn, and only the moving parts stop (see PR 1).

## 6. Phases

### PR 1: Foundation (tokens, severity audit, fonts, theme picker, colour gate, harness)

**New token layer in `web/src/lib/styles/global.css`, matching the mockup:**
- surfaces: `--bg`, `--surface-1..3`, `--line`, `--line-strong`
- text: `--text-1..3`
- accents: `--accent`, `--accent-strong`, `--on-accent`
- data: `--data-1..8` (8 per variant, so 8-series charts don't repeat colours)
- severity: `--sev-critical|high|medium|low|info` (the same in every variant)
- status: `--ok`
- other: `--font-display`, `--r-*`, `--scrim`
- blocks: `:root` holds Ember; `:root[data-variant="graphite"]` and `:root[data-variant="spectrum"]` override it.

**Complete legacy mapping.** Every token currently in `global.css` gets a definition; none keeps its old literal:

| Legacy | New |
|---|---|
| `--bg-void`, `--bg-primary` | `--bg` |
| `--bg-secondary`, `--bg-input` | `--surface-1` |
| `--bg-tertiary` | `--surface-2` |
| `--bg-elevated` | `--surface-3` |
| `--bg-overlay` | `--scrim` |
| `--border-dim`, `--border-muted`, `--border-default` | `--line` |
| `--border-bright` | `--line-strong` |
| `--border-accent` | `--accent` |
| `--text-primary` / `--text-secondary` | `--text-1` / `--text-2` |
| `--text-muted`, `--text-dim` | `--text-3` (raises dim text to AA) |
| `--text-link` | `--accent-strong` |
| `--accent`, `--cyan`, `--info` | `--accent` (brand and "informational" use) |
| `--accent-hover` | `--accent-strong` |
| `--accent-muted`, `--cyan-dim`, `--info-muted` | `color-mix(in srgb, var(--accent) 12%, transparent)` |
| `--accent-glow` | the same at 25% |
| `--shadow-glow` | built from `--accent` |
| `--red`, `--danger` | `--sev-critical` |
| `--orange` | `--sev-high` |
| `--amber`, `--warning` | `--sev-medium` |
| `--blue` | `--sev-low` |
| `--green`, `--success` | `--ok` |
| `--purple`, `--pink`, `--teal` | `--data-4`, `--data-6`, `--data-3` (decorative category colours) |
| each `*-dim` / `*-muted` | `color-mix` of its mapped colour at 12% |
| `--chart-1..8` | `--data-1..8` |
| `--radius-sm/md/lg/xl` | 8 / 12 / 20 / 26 px |
| `--font-sans` | the Manrope stack |

`--space-*` and the `--text-*` sizes are unchanged.

**Semantic audit.** This runs before the aliases go in and is listed file by file in the PR body:
- **Severity:** every severity consumer is found by grepping for severity class maps (`badge-*`, `sev-*`, `critical|high|medium|low|info` → colour) across `routes/` and `components/`. Each one moves to the matching `--sev-*` token. Examples:
  - Home's LOW badge (`+page.svelte:351–360`, now `badge-accent`) becomes `--sev-low`.
  - Device detail (`devices/[ip]/+page.svelte:1045–1048`) splits critical and high onto `--sev-critical` and `--sev-high`.
  - Info severity uses `--sev-info`.
- **Brand cyan:** any remaining use of `--cyan` that means a state rather than the brand is moved to the right semantic token.
- **Inline `rgba(...)` glows and backgrounds** (for example `devices/+page.svelte:493–510`) become `color-mix` with tokens.
- **Script palettes** (`SERVICE_COLORS` and others the gate finds) become `var(--data-*)` strings.

**Canvas colours (`GeoMap`).** Canvas cannot use `var()`.
- Add `web/src/lib/utils/tokens.ts` with `resolveToken(name)`, a `getComputedStyle` read on `documentElement`.
- `GeoMap` resolves its marker, arc and label colours after mount, and again when the variant changes (it subscribes to the theme store, which notifies only after the root attribute has changed; see the theme protocol).
- Split `GeoMap`'s current `animationLoop` (`GeoMap.svelte:241–313`), which draws the static arcs and the moving pulses together, into two functions:
  - `drawFrame(t)`: draws the arcs, plus pulses at phase `t`.
  - A scheduler that calls it from `requestAnimationFrame`.
- Under reduced motion there is no scheduler. `drawFrame` is called once on mount and again on every data, viewport (Leaflet `move`/`zoom`/`resize`) and theme change. That draws the arcs with no pulses.
- Unit tests:
  - `resolveToken`
  - under reduced motion, `drawFrame` runs on mount and on each trigger, with no rAF
  - with motion allowed, the rAF loop runs
- The harness checks the populated Live map in both modes (§5.2).

**Fonts:**
- Add variable woff2 files, latin subset, to `web/static/fonts/`: Sora, Manrope and JetBrains Mono (OFL 1.1), each with its `OFL.txt`.
- Add `@font-face` rules with `font-display: swap`.
- Remove the Google Fonts `<link>`s from `+layout.svelte`.
- Add the fonts to `THIRD-PARTY-LICENSES.md`.

**Theme picker:**

| Part | Behaviour |
|---|---|
| Storage key | `nettap-theme`. Values: `ember`, `graphite`, `spectrum`. Anything else means Ember. |
| Bootstrap (in `app.html` `<head>`, before `%sveltekit.head%`) | `try { const v = localStorage.getItem('nettap-theme'); if (v === 'graphite' \|\| v === 'spectrum') document.documentElement.dataset.variant = v; } catch {}` Ember is the absence of the attribute. |
| `web/src/lib/stores/theme.ts` | On the server the value is always `ember`, with no browser access. In the browser it starts from `document.documentElement.dataset.variant` (the bootstrap result), never from its own storage read, and nothing writes on initialisation. |
| `setTheme(v)` | Validates `v`, then, in this order: 1. sets or removes the root `data-variant` attribute; 2. publishes the store value, so subscribers such as `GeoMap` already read the new computed tokens; 3. tries the `localStorage` write. If the write throws, the theme still applies for the session. This is the only writer. |
| Settings picker | Renders Ember on the server. Adopts the store value in `onMount`, so SSR and hydration never disagree on attributes. Changes go through `setTheme`. |
| Unit tests | Server default; browser start from the attribute; invalid attribute; `setTheme` sets the attribute and storage; storage that throws still applies the theme; no write on init; a subscriber that reads a computed token during its notification sees the new variant's value. |
| Harness tests | 1. Saved Graphite: only JavaScript is held back. `page.route` matches `/_app/immutable/**/*.js` and parks those requests until the test releases them. Stylesheets (`/_app/immutable/assets/*.css`) load normally. The test navigates with `waitUntil: 'commit'`, waits for the SSR body and for every `link[rel=stylesheet]` to finish loading, then checks that the root has `data-variant="graphite"`, that the body's computed background is black, and that a Graphite-only token (`--accent`) resolves to Graphite's value. Then it releases the JavaScript. 2. After release and hydration, the picker shows Graphite. 3. It survives client navigation and a reload. 4. With storage denied (an init script stubs a throwing `localStorage`), the page is Ember, switching works for the session, and there are no console errors. 5. The same for Spectrum. |

**Docs:** rewrite `web/DESIGN-SYSTEM.md` with the token tables, the severity rules, the colour gate, canvas guidance and the patterns from the mockup.

**Also:** the colour gate and the visual harness (§5), with PR 1 coverage.

### PR 2: Shell (sidebar, header, mobile menu); no new data or actions

**`+layout.svelte` layout:**
- Floating, grouped sidebar with the existing 17 hrefs:
  - Overview: Home, Live Monitor, Bandwidth
  - Investigate: Alerts, Threats, Connections, Log Explorer, DNS Analytics, Certificates, PCAP Search
  - Devices: Devices, IoT & LAN, Changelog
  - System: Infrastructure, System, Tools, Settings
- Investigations and Security Posture stay out of the menu.

**Shell contents.** It keeps only what it owns today:
- capture-mode badge
- daemon-liveness status
- `NotificationBell` (unread notifications, not alerts)
- the POST `/api/auth/logout` form

The mockup's global search, "updated" time, refresh button, storage meter and nav alert count are **not** added. Search, refresh and timestamps stay page-owned, as they are now. A global version of any of them is a separate follow-up with its own data contract.

**Mobile:** below 760 px a menu button (`aria-expanded`, `aria-controls`) opens the sidebar as an overlay with a scrim. Open moves focus to the first link and Tab stays inside the overlay. Escape, the scrim, choosing a link, or crossing the 760 px breakpoint (`matchMedia` change) closes it, and focus returns to the button.

**Tests:**
- `layout.test.ts`: all 17 links with the right hrefs; the active state on nested routes (`/alerts/foo` highlights Alerts); no shell on `/login` and `/setup` (as today); the logout form posts to `/api/auth/logout`; the menu toggle's `aria-expanded`; Escape closes; focus moves in and back; choosing a link closes.
- Harness: the menu at 390 (opens, contains focus, closes on Escape and on navigation), and a resize from 390 to 1440 with the menu open (the overlay is gone, the sidebar shows normally).

### PR 3: Shared components restyled in place (props and callbacks unchanged)

| Component | Change |
|---|---|
| `TimeSeriesChart`, `DualSeriesChart` | Monotone curves, gradient fill, dashed grid, peak marker, pill tooltip. |
| `DonutChart`, `ProtocolDonut` | Rounded segmented ring. Geometry rules are below the table. `ProtocolDonut`'s centre still shows the supplied connection count, or `—`, and never a sum of percentages. |
| `HorizontalBarList`, `TopConsumers`, `TopTalkersChart` | Gradient capsule bars. |
| `SankeyDiagram`, `NetworkMap` | Palette (via tokens or `resolveToken`) and typography. Both leave the colour-gate allowlist. |
| Drawers (`DetailDrawer`, `drawer/*`), `Breadcrumb`, `Collapsible`, `SearchBar`, `DashboardFilters`, `DeviceGrid` | Restyle only. |

**Donut geometry.** Each segment `i` has a proportional length `pᵢ = C·vᵢ/Σv`, where `C` is the circumference. Its gap is bounded by its own share, `gᵢ = min(G, pᵢ/2)`, so `pᵢ − gᵢ ≥ pᵢ/2 > 0` for any non-zero value. The cap overhang is `c = strokeWidth/2` on each end.
- If `pᵢ − gᵢ − 2c ≥ 0.5`, draw a round-capped dash of length `pᵢ − gᵢ − 2c`. Its visual extent is `pᵢ − gᵢ`.
- Otherwise, draw a butt-capped dash of length `pᵢ − gᵢ`.
- Where a dash starts depends on its caps. With `Oᵢ` as the cumulative offset:
  - butt-capped dashes start at `Oᵢ + gᵢ/2`
  - round-capped dashes start at `Oᵢ + gᵢ/2 + c`, because a round cap reaches `c` back from the dash start
- Either way, the visual extent is exactly `[Oᵢ + gᵢ/2, Oᵢ + pᵢ − gᵢ/2]`, inside the segment's own share. Neighbours never overlap, including the last and first segments where the ring closes.
- A zero value is not drawn, but it keeps its original index, so click and filter callbacks still receive the original item and index.
- A single non-zero segment draws the full ring.

**Global styles:** table header pill row, card, pills, severity pill with a shape plus the label.

**New components, only when a PR 4 page needs them** (added in that PR, with tests): `Sparkline`, `SegmentedGauge`, `Radar`, `Ring`.

**Chart regression matrix (vitest), in PR 3:**
- **Donut geometry:** every dash length and offset is finite and ≥ 0. Each visual extent (dash ± `c` when round-capped) lies within its segment's share, so no two overlap, and their sum is ≤ the circumference. Covers:
  - segments smaller than the gap
  - segments smaller than the cap
  - a butt-capped segment next to round-capped ones, on both sides
  - overlap across the ring's start/end boundary
  - zero segments mixed with non-zero ones (callbacks get the original indices)
  - a single segment
  - all-zero data (empty state)
- **`ProtocolDonut` centre:** with a count it shows that count; with an unknown count it shows `—`.
- **Callbacks:** segment and bar click and filter callbacks fire with the same arguments as before.
- **Time series:** `[]` shows the empty state; `[x]` draws no NaN in path data; a constant series and a series with gaps are handled.
- **Tooltips:** exact formatted values for a known point (bytes, counts, durations, using the fixed duration formatter).

### PR 4a–4g: Pages in batches (layout per the mockup, data untouched)

| PR | Pages |
|---|---|
| 4a | Home (`/`) |
| 4b | Alerts, `alerts/[category]`, Threats |
| 4c | Devices, `devices/[ip]`, `devices/mac/[mac]`, IoT & LAN |
| 4d | Connections, Live Monitor, Bandwidth, `traffic/[category]` |
| 4e | DNS Analytics, Certificates, Changelog, Log Explorer, PCAP Search |
| 4f | Infrastructure, System (+ updates, cyberchef), Settings (+ subpages), Tools (+ 9 tools), lookup and geoip pages |
| 4g | Setup wizard, Go Live, Login, Investigations, Security Posture |

**For each batch:**
- Restructure into the card grid: page header, KPI row, main chart plus side card, detail cards and tables.
- Keep every request, state, message and action.
- Add populated, slow and stale fixtures plus harness specs for its routes.
- Run vitest and svelte-check.
- Do the G11 real-data check.
- If a batch exceeds ~1.5k changed lines, its biggest page goes in its own PR. The candidates are setup (2.9k), infrastructure (2.9k) and settings (2.5k).

## 7. Tracking

- **Linear:** a parent issue "feat(ui): pure-black redesign" plus one issue per PR. Each moves to Done when merged.
- **Tracking doc:** `tracking-fixes/2026-11-03-ui-redesign.md`, with one row per PR (branch, what changed, files, tests, harness and G11 results, status).
- **Build plan:** `plans/comprehensive-build-plan.md` gets a Phase 4 task entry, ticked off per PR.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| A legacy alias reads wrong for a use the audit missed | The audit runs before aliasing, and the PR 1 harness screenshots every route in all variants. Fix it by pointing the consumer at the semantic token, not by changing the alias. |
| Severity colours drift by theme | `--sev-*` are identical in every variant, and every severity consumer uses them after PR 1. |
| Tests assert class names or inline styles | Change a test only when it asserted styling, never behaviour. Note each one in the PR body. |
| PR size and review fatigue | One PR per batch, and the biggest pages are split out (§6). |
| Theme bootstrap blocked or storage denied | No CSP today. The script is try/catch and Ember is the fallback. Covered by harness test 4. |
| Canvas map ignores tokens | `resolveToken` plus re-resolving on variant change (PR 1). |
| Fixture drift from real API shapes | Fixtures are TS modules that `satisfies` the `web/src/lib/api/*.ts` interfaces, checked by `npm run check:e2e` locally and in CI. The G11 check covers real data. |
| Setup wizard regressions block first-run installs | Restyled only by tokens in PR 1 (harness-covered on a first-run data dir) and restructured last (4g). |

## 9. Rollback

The PRs form a dependency chain: PR 2 and later use PR 1's tokens, `resolveToken`, theme store and harness. Rollback is therefore dependency-aware:

1. **Fastest:** redeploy the last verified revision to the G11. Set `BRANCH`/commit in the deploy script to the previous squash commit on `main`. This needs no git surgery.
2. **Undoing one phase on `main`:** revert dependent phases in reverse order (4g … 4a, 3, 2), then PR 1. Never revert PR 1 alone while later phases are on `main`.
3. **Old palette only, keeping later phases:** do not revert PR 1. Change the token values in `global.css`. The legacy and new token names, `resolveToken`, the theme store and `setTheme` all stay, so nothing that depends on them breaks.

The theme picker only writes `localStorage`. After any rollback an unknown or stale value is ignored (Ember).

## 10. Out of scope

- Backend or daemon changes
- New metrics, endpoints or shell features
- Light mode (tokens keep it possible)
- Behaviour changes on any page
- The DNS, IoT and certificate totals audit (resumes after the redesign)
