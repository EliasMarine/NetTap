# 2026-11-07 — Settings › Display's default time range opens every range page (NET-195), from one range list (NET-196)

**Status:** built on `feature/display-default-range`. The PR, the reviews and the G11 deploy are pending. Plan: `.codex-review/2026-11-07-display-default-range/PLAN.md` (Codex approved in round 3 of 5).

**Problem**
- Settings › Display had three controls: "Default time range", "Auto-refresh" and "Timezone". They were saved to `localStorage['nettap-display-settings']`, but nothing outside Settings read that key. Picking "Last 7 days" changed nothing: every page still opened on its own default.
- Every range page kept its own copy of the same five ranges (`1h 6h 24h 7d 30d`), 15 tables in all, plus parallel maps of hours and words. Traffic's copy said "6 h" where every other page said "6 hours".

**Root causes**
- A setting with a writer and no reader. Nothing tied the saved key to where a page's range starts.
- NET-192 PR 4 made the ranges the same everywhere by editing each copy, so the copies stayed.

**Fix (NET-195)**
- `web/src/lib/utils/drilldown.ts`: `savedDefaultRange()` and `startRange(pageDefault)`, next to `DRILL_RANGES`.
  - It reads the new field `defaultRange` when it is one of `DRILL_RANGES`. An invalid new field gives null, with no fallback.
  - With no new field, a legacy `defaultTimeRange` of 6h, 24h, 7d or 30d is honoured. A legacy 1h is ignored: it was Settings' own fallback, so any Display save (a timezone change, say) wrote it. 15m and 4h are no longer offered.
  - Bad JSON, storage that throws and the server (no `localStorage`) give null, so the page's own default.
- Settings › Display: the select starts with "Each page's own (most open on 24 hours)", then the five ranges from `DRILL_RANGES`. Save writes `{ defaultRange }`; "Each page's own" removes the key. The help text names what it applies to, and that PCAP and Certificates keep their own.
- The auto-refresh and timezone controls are removed and kept as OLD CODE: each page owns its Auto toggle (15 s or 30 s), and every time on a page is browser-local.
- Each range page except PCAP and Certificates starts on `startRange(<its own default>)`, read where its range starts, never in an `onMount`, so the first load uses it and loads once:
  - `$state` initializers: Home, `alerts/[category]`, Connections (the range object for that value), DNS, `devices/[ip]`, `devices/mac/[mac]`, IoT, Threats, `traffic/[category]`, `address/[ip]`, `domain/[name]`, Logs.
  - URL fallbacks: the Alerts hand-off effect, the Suricata category page and the Devices list. A window or `?range` in the link still wins.
  - Logs' `'custom'` fallback. A later hand-off with no window keeps the range on screen, as before (the top-bar search re-opens `/logs?query=…`, and the page can't tell a pill's range from a link's).
- PCAP keeps 1 hour (a day is about 185 GB to search, #137) and Certificates 7 days (Zeek logs a certificate at most once a day).

**Fix (NET-196)**
- Every page's table is `DRILL_RANGES`, or a `.map` of it that adds the page's own field: `ms` (Alerts, Logs, Connections: the Custom-window fit and their windows), PCAP's capture-timeline `bucket` and `bucketMs` (one `BUCKET` table holds each bar's words and width, replacing the separate width ternary), Home's `previous` words (built from `words`). DNS and `alerts/[category]` use `DRILL_RANGES` as is and `rangeWindow(hours)` (ponytail review). `certificates/cert-view.ts` and `alerts/suricata/[name]/suricata-view.ts` export `DRILL_RANGES` under their old names.
- The parallel maps are lookups in it: IoT `RANGE_LABEL`/`RANGE_HOURS`, Traffic `RANGE_HOURS`, `devices/[ip]` `RANGE_HOURS`/`RANGE_LABEL`/`RANGE_KEYS`, Threats `RANGE_TEXT`. The `computeTimeParams` switches (IoT, Threats, Traffic) are `rangeWindow(hours)`.
- The page extras stay: every `INTERVAL_MAP`/`INTERVALS`, PCAP's bucket, Logs' `INTERVAL_WORDS`. `cert-view.ts`'s `RangeValue` is `DrillRangeValue | 'custom'`.
- Wording: Traffic and Home now say "6 hours" and "24 hours" ("last 6 hours", "vs previous 24 hours"), not "6 h" and "24 h". No other page's words changed.
- Departure from the plan: the plan kept Home's `previous` labels as a page extra. They now come from the shared `words` (`last …` → `previous …`), so Home and Traffic read the same; Home said "previous 6 h" while Traffic said "previous 6 hours".
- Every old table is kept as OLD CODE.

**Files**
- `web/src/lib/utils/drilldown.ts`, `drilldown.test.ts`
- `web/src/routes/settings/+page.svelte`, `settings.test.ts`
- Pages: `+page.svelte` (Home), `alerts/+page.svelte`, `alerts/[category]/+page.svelte`, `alerts/suricata/[name]/+page.svelte` and `suricata-view.ts`, `certificates/cert-view.ts`, `connections/+page.svelte`, `devices/+page.svelte`, `devices/[ip]/+page.svelte`, `devices/mac/[mac]/+page.svelte`, `dns/+page.svelte`, `iot/+page.svelte`, `logs/+page.svelte`, `pcap/+page.svelte`, `threats/+page.svelte`, `traffic/[category]/+page.svelte`, `address/[ip]/+page.svelte`, `domain/[name]/+page.svelte`
- Tests: `home-trends.test.ts`, `iot/iot-page.test.ts`, `alerts/alerts-page.test.ts`, `devices/devices.test.ts`, `connections/connections.test.ts`, `pcap/pcap.test.ts`, `logs/logs.test.ts`, `traffic/[category]/category-page.test.ts`
- `web/e2e/visual/default-range.visual.ts` (new)
- `scripts/remote/deploy-display-default-range.sh` (new)

**Tests**
- Unit (`drilldown.test.ts`, 14): nothing saved, bad JSON and a throwing `getItem` give null; every row of the plan's legacy table; JSON that isn't an object; `startRange`.
- Settings (5): saving "Last 7 days" writes `{defaultRange:'7d'}`; "Each page's own" removes the key; a saved 30d shows selected; a legacy 1h shows "Each page's own"; no auto-refresh or timezone control.
- Pages, one per way a page starts (12):
  - IoT (`$state` + `$effect`): saved 7d gives one 7-day fleet request. Legacy `defaultTimeRange:'7d'` opens 7 days; legacy 1h is ignored; the new field wins over the legacy one.
  - Alerts (URL effect): one 7-day timeline request; `?range=1h` wins.
  - Devices list (derived): one 7-day reading; `?range=1h` wins.
  - Connections (the stored object): the first list, stats and timeline ask for 7 days.
  - PCAP: still one 1-hour file request.
  - Logs: `/logs` with no window opens 7 days. A picked 1h survives a windowless hand-off (`/logs?query=x`) with one search and no card reload.
- Home (`home-trends.test.ts`): picking 6h shows "vs previous 6 hours"; it fails on the page before the wording change.
- Traffic: the trend assertion was "vs previous 24 h", a prefix of the new "vs previous 24 hours", so it passed either way. It now pins the full new wording (old kept as OLD CODE).
- Browser (`e2e/visual/default-range.visual.ts`, no mocks): `addInitScript` saves 7d before the first navigation, then Home, Alerts and the Devices list are hard-loaded. Each asserts exactly one 7-day request to `/api/traffic/bandwidth`, `/api/alerts/timeline` or `/api/devices` (exact path), the 7d pill pressed after hydration, no console error or warning that mentions hydration, and no console errors.
- **Fails without the change:**
  - The reader tests import functions that don't exist on `origin/main`.
  - Settings: all 5 fail against `origin/main`'s Settings page.
  - Pages, against `origin/main`'s pages: the six "opens on the saved range" tests fail (IoT ×2, Alerts, Devices list, Connections, Logs).
  - The other six pin rules `origin/main` already keeps, so each was proved by breaking the rule: PCAP wired to `startRange('1h')` fails its test; Logs resetting a windowless hand-off to the saved default fails the kept-rule test; Alerts and the Devices list putting the saved range ahead of `?range` fail their link-wins tests; a reader that honours legacy 1h and prefers the legacy field fails both IoT legacy guards (and four unit rows).
  - Traffic: the new assertion fails on the previous Traffic page.
  - Browser: all three fail on `origin/main` with `[24]`, one 24-hour request each. That run is also the check that each watched endpoint is called once per load.
- Runs on the branch: vitest 318 files / 3,954 tests; svelte-check 0 errors; check:colors clean; check:e2e clean; test:e2e 14 passed; test:visual 283 passed, 49 skipped, 0 failed (no screenshot baselines exist, so none needed updating); shellcheck clean on the deploy script.

**Device check**
- `bash /home/nettap/NetTap/scripts/remote/deploy-display-default-range.sh` rebuilds and recreates the web container only, waits for healthy, then checks with no cookie that `/` and `/alerts` give 302 to `/login` and `/api/health` gives 200. The setting lives in the browser, so its last line asks for the hand check: Settings › Display, "Last 7 days", Save, then Home shows 7d selected.

**Lessons**
- A setting needs a reader, and a test that fails without it. Three Display controls shipped saving to a key nothing read.
- Read a stored preference where the state starts (a `$state` initializer or the URL fallback), not in an `onMount`: setting it later loads the page twice, or not at all on pages that fetch in `onMount`.
- A changed field name is the clean way past values written by accident. The old `'1h'` could not be told apart from a choice, so it is ignored, and only the values someone must have picked carry over.
- An assertion on a substring can stop pinning anything when the text grows ("24 h" is a prefix of "24 hours"). Assert the whole phrase.
- One list, imported, instead of copies edited in step: NET-192 PR 4 had to touch 15 tables to change one range.
