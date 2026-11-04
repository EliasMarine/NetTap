# 2026-11-03 — UI redesign (pure black, Ember default)

**Status:** superseded by the **full redesign** on `feature/ui-redesign-full` (see the section below). Everything is built and tested; the review gates, the G11 deploy and the owner's check are left. Linear: NET-144 (parent), NET-145 (foundation), NET-147 (full redesign).

> The PR 1 sections further down describe the first, colours-only plan (PR #165). The owner rejected it ("I wanted a FULL REDESIGN") and supplied the design system in `nettap-design-system/`. They are kept as the record.

## Full redesign (`feature/ui-redesign-full`, NET-147)

**What changed**
- **Foundation:** the system's `tokens.css` and `bundle.css` copied in verbatim (`web/src/lib/styles/tokens.css`, `system.css`), plus `forms.css` (form controls the system lacks) and `a11y.css` (five numbered corrections). The theme attribute is now `data-theme`, and there are 48 icons with a drift test.
- **Components:** 20 in `web/src/lib/components/ui/` and 8 charts in `ui/charts/`. AreaChart, Donut, SeverityGauge, Ring, Sparkline, StackBar, Radar and DotMap replace the old charts and the Leaflet map.
- **Shell:** sidebar, top bar (search, refresh, "Updated", bell), phone drawer. `+layout.server.ts` returns only the username.
- **Pages:** all 45 rebuilt to the recipe in 8 parallel batches (B1–B8). Home has no device cards; they are on Devices → By type.
- **Data rules:** every loader registers with `registerPageRefresh`, returns ok/partial/failed/skipped, and uses the load guard. Alert counts come from the shared `alertSnapshots` store.
- **Cleanup:** 26 replaced components, the legacy token aliases and Leaflet are deleted. The colour gate also fails on undefined `var(--x)` and on emoji, and its allowlist is empty.
- **Deploy:** `scripts/remote/deploy-ui-redesign.sh` (records the deployed commit in `~/.nettap-last-deploy`) and `scripts/remote/rollback-ui-redesign.sh`.

**Bugs found and fixed on the way**
- The shared alert snapshot dropped its counts on a failed refresh, so Home showed "—" instead of the last count (#96 rule). It now keeps the last good counts.
- `input[type="checkbox"]` out-ranked `.switch`, so every switch was a 16 px dot.
- Settings said "Licence: Apache 2.0"; it is the NetTap Personal Use License.
- Pill groups and the TShark version chip pushed the page sideways at 390 px.
- NET-146: Log Explorer field tooltips never showed (`f.field` vs the daemon's `name`), and the connection drawer read Suricata severity 2 as High while everything else read Medium.
- The setup wizard spec, stale since the capture-mode step was added, is rewritten and passes.

**Found by the two-angle review, fixed (PR #166, `afe1427`…`1a435e0`)**
- Global search showed blank suggestions: the daemon's `suggest()` returns strings, the top bar read `.text`. The tests mocked `{ text }`, so they stayed green. A late debounce timer could also reopen the list after Enter or Escape.
- Auto-refresh on Alerts, an alert category, Logs, Devices and a device page cancelled its own slow load (each load cancels the one before), so it never landed. Timers now use `runIfIdle()`.
- Both alerts tables showed Time as the sort after remounting, while the server sorted by the chosen column.
- Home's Refresh re-used the old alert-count window, so its alert figures lagged the rest of Home by up to about 90 s.
- Device and threat links now URL-encode the IP (security-angle LOW).

**Tests:** vitest 270 files / 2845 tests; svelte-check 0 errors; colour gate clean; visual harness 180 pass, 44 skipped by design (3 themes × 1920/1440/390; empty, error and populated on every route); behavioural Playwright 14 pass; deploy and rollback dry-run in a scratch clone with a stub `sudo`.

**Behaviour changes for the owner to confirm:** Home's Custom date range is dropped; a newly clicked table column sorts descending first; page Refresh buttons moved to the top bar. The full list goes in the PR body.

**Lessons**
- Parallel page agents need hard ownership (their route folders only; shared needs come back as report items). All 8 merges then cherry-picked cleanly.
- Redirect a long Playwright run to a file. Piping it through `tail` in the background shows nothing until it ends.
- `{/regex/}` in Svelte markup is read as a closing block tag: the build fails, while vitest passed. Run svelte-check or a build after markup edits.
- `.gitignore` ignores directories named `logs` and `pcap`, so stage `web/src/routes/logs` with `git add -u`.
- Mock an API with the daemon's real wire shape, read from the daemon handler. A mock of the TypeScript type passes even when the type is wrong.
- A timer that calls a "newest load wins" loader must skip while a load is running, or a load slower than the interval never lands.

**Next steps**
1. ~~`/deep-review` and `/ponytail-review`~~ done. ~~Two-angle review~~ done, findings fixed. PR #166 is open (draft).
2. Owner: `bash scripts/remote/deploy-ui-redesign.sh` on the G11, then a check of every page in all three themes, and a yes or no on the two behaviour changes.
3. Mark #166 ready, `gh pr checks 166`, squash merge, then `BRANCH="main"` in the deploy script and close #165.

**Plan:** `PLAN.md` (repo root). Codex approved it after 4 rounds (19 findings: 6 High, 13 Medium; all taken on, one narrowed). The review log is in `.codex-review/2026-11-03-144402-ui-redesign/` (gitignored).
**Visual reference:** `mockups/redesign-2026-11/index.html` (owner-approved 2026-11-03).

## Owner decisions (2026-11-03)

- **Background:** pure black (#000) on every page.
- **Variants:** Ember is the default. Graphite and Spectrum ship too, picked in Settings → Display.
- **Navigation:** grouped left sidebar; a menu button on phones.
- **Replaced code:** CSS and markup are deleted, with git history as the record. Replaced logic keeps OLD CODE START/END.
- **Density:** balanced, for a 1920 px monitor; must work at 1440 and 390.

## Phases and branches

Each phase gets a fresh branch from `main`, created after the previous PR merges. Branches are never reused.

| Phase | Branch | PR | Linear | Status |
|---|---|---|---|---|
| PR 1 foundation | `feature/ui-redesign-foundation` | — | NET-145 | In progress |
| PR 2 shell | `feature/ui-redesign-shell` | — | — | Not started |
| PR 3 shared components | `feature/ui-redesign-components` | — | — | Not started |
| PR 4a–4g pages | `feature/ui-redesign-<batch>` | — | — | Not started |

## PR 1: foundation

**What changes**
- **Tokens:** `global.css` has a new token block for Ember, Graphite and Spectrum. Every legacy token maps onto it, so the whole app goes black at once.
- **Severity:** each severity has its own token (`--sev-*`), the same in every variant. The per-file audit is listed in the PR body.
- **Hard-coded colours:** about 310 across 49 files are replaced by tokens. Email HTML keeps its literals, with a per-line exemption.
- **Fonts:** Sora, Manrope and JetBrains Mono are bundled (OFL, `web/static/fonts/`). The Google Fonts links are gone.
- **Theme:** a bootstrap script in `app.html` applies the saved theme before first paint. `$lib/stores/theme` and `ThemePicker.svelte` live in Settings → Display.
- **GeoMap:** canvas colours come from tokens via `resolveToken`, and are re-read when the theme changes. Drawing and scheduling are split (`arc-scheduler.ts`), so reduced motion keeps the static arcs.
- **Colour gate:** `npm run check:colors`, run in the CI Lint Web job before svelte-check.
- **Visual harness:** `npm run test:visual`, with fixtures type-checked by `npm run check:e2e` (also in CI).
- **Contrast test:** `src/tests/token-contrast.test.ts`. Every text and severity token is AA on every surface, in every variant.
- **Deploy script:** `scripts/remote/deploy-ui-redesign.sh` rebuilds only `nettap-web`, then checks the bootstrap, the fonts and the new stylesheet.

**Test results (2026-11-03, local):**
- **Vitest:** 2,370 passed in 212 files.
- **svelte-check:** 0 errors and 44 warnings. The warnings are the same per file as on `main`.
- **Daemon pytest:** 2,914 passed, 1 skipped.
- **Colour gate:** clean. NetworkMap and charts/SankeyDiagram are allowlisted until PR 3.
- **Visual harness:** 139 passed, 0 failed, 43 skipped (3.7 min). Every route ran in all 3 variants at 1920, 1440 and 390.
- **Known issues:** these are recorded as annotations, not failures, in `web/e2e/visual/known-issues.ts`:
  - Overflow at 390 px from the old shell, fixed in PR 2.
  - Home is 1522 px wide after a resize from 1920 to 1440.
  - `/traffic/streaming` logs its own console.error in error mode.
  - The first-run EventSource on `/go-live` gets an HTML redirect.
- **Reviews:** `/deep-review` found nothing. The `/ponytail-review` findings (1 must-fix, 3 should-fix, 4 nice-to-have) are all fixed.

## Lessons

- In Playwright 1.58, `webServer` entries start before `globalSetup`. Anything the servers need (temp dirs, a fixture daemon) has to exist by the time the config loads, or be a `webServer` itself.
- The harness serves a copy of `build/` (`test-results/visual-build`). An unrelated `npm run build` mid-run otherwise replaced the chunks under the running server and failed 133 tests with `ERR_MODULE_NOT_FOUND`.
- Settings tabs are server-rendered buttons, so a click that lands before hydration does nothing. Tests retry the tab click until its content appears.
- A Svelte store notifies its subscribers synchronously. Anything that reads computed CSS when the theme changes needs the DOM attribute set *before* the store publishes.

## Next steps

1. Finish PR 1. Gates: `/ponytail-review`, `/deep-review`, then the PR, `gh pr checks`, a G11 deploy, and a check in Chrome in all three variants.
2. PR 2 (shell) on a fresh branch after PR 1 merges.
