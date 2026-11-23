# NET-357: drill-down and Back keep the time range; the weekly report switch shows what is saved

**Date:** 2026-11-23 · **Branch:** `fix/browser-qa-2026-11-22` · **Status:** in review

## What the QA pass found (G11, 22 Nov)
1. **Category links lost the window.** On Home at **1h**, Traffic categories → Streaming opened the category page at **24h**: 245 MB on Home against 13.4 GB on the detail page. The same happened at 6h with Web Browsing.
2. **Back reset Home's range.** Home at 1h → Devices card → Back came back at **24h**. The same happened at 6h after a visit to Web Browsing.
3. **Reports and Settings disagreed.**
   - Reports said "No weekly report set up" and kept Generate now off.
   - Settings › Notifications showed **Email a weekly report** already switched on.

## Root causes
1. **Category links.** Home's category bars linked to `/traffic/<name>` with no window, and the category page never read `?range=`.
2. **Range kept in page state.** Home and the four pages that narrow themselves (traffic category, DNS, domain, device) kept their range only in page state. A pill never wrote the URL, so Back, Forward and a reload fell back to the default.
3. **Weekly report switch.** With no schedule saved yet, the weekly report card's form started at `enabled: true`. The daemon only creates the schedule on the first Save.

## What changed
- **The range is the URL.**
  - Home and the narrow pages derive their range from `?range=` every time the URL changes.
  - A pill only writes it. Home replaces the history entry. A narrow page replaces it, or pushes when it leaves a picked window, so Back returns to the pick.
  - `withRange` in `narrow-page.ts` replaces `withoutWindow`.
- **Home's category bars** link with the categories reply's own window (`from`/`to` + `range`), the way its KPI cards already link theirs.
- **Category and device pages record the view on screen when they clear it.** A partial failure can no longer leave another range's chart, or its port rows, under the restored label after Back.
- **The device page hides the Recent connections total** while its list loads.
- **Weekly report card:**
  - the switch starts off until a schedule is saved;
  - it is labelled "Make a weekly report", and the copy says email also needs the email server;
  - a save conflict now merges field by field. If both windows changed the addresses, the saved list stays and the message shows yours.
- **Reports** names the setup step: turn it on and save.

## Files
- `web/src/routes/+page.svelte`
- `web/src/routes/traffic/[category]/+page.svelte`
- `web/src/routes/dns/+page.svelte`
- `web/src/routes/domain/[name]/+page.svelte`
- `web/src/routes/devices/[ip]/+page.svelte`
- `web/src/lib/utils/narrow-page.ts`
- `web/src/routes/settings/ReportScheduleCard.svelte`
- `web/src/routes/reports/+page.svelte`
- `web/src/tests/app-navigation.svelte.ts` (`goto` honours `replace`)
- `web/DESIGN-SYSTEM.md`
- tests, listed below

## Tests
See the PR. Vitest covers:
- the URL-driven range on each page;
- history replace and push;
- Back across partial failures;
- the report card's merge.

Playwright `e2e/visual/range-history.visual.ts` checks Back, Forward and category links in a real browser. `default-range.visual.ts` now covers the four narrow pages.

## Reviews
- **Plan:** `/codex-review`, approved in round 4.
- **`/ponytail-review`:** "Ship". Applied:
  - the alert category page pushes when leaving a pick, like the other narrow pages;
  - the repeated `loadedView` writes are gone;
  - typing the same addresses in both windows is no clash;
  - a CNAME link carries the domain page's range.
- **Kept on purpose:** `categoriesWin` beside `categories`. Its `range=` fallback is only the type's null branch.
- **Not mandatory:** `/deep-review` (under 200 net source lines, no trigger paths).

## Checks
- Vitest: 452 files, 6,182 tests passed.
- `svelte-check`: 0 errors.
- `check:colors`: clean.
- `check:e2e`: clean.
- `test:visual`: 409 passed, 66 skipped (by design).

## Known, not fixed
- `Pills` still writes its own value on click. If a pill's `goto` were ever cancelled, the pressed pill and the figures would disagree. Nothing on these pages cancels navigation today.

## Deploy
- Deployed with NET-358 by `scripts/remote/deploy-change-password.sh`.
- NET-358 replaces the key older builds sign with, so the rollback of this pair is that PR's rollback.

## Lessons
- State the user picked (a time range) belongs in the URL. Derive it from the URL rather than seeding state from it, or Back within a page drifts.
- A switch shows what is saved, never a default for something that doesn't exist yet.
