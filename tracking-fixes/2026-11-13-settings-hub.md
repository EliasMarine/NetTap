# One Settings page: rules, notification channels and backup as tabs, 2026-11-13

**Linear:** NET-273
**Branch:** `feature/settings-hub`
**Status:** built and tested locally; deploy to the G11 after merge with `scripts/remote/deploy-settings-hub.sh`.
**Plan:** `PLAN.md` in the worktree (Codex review, 3 rounds, APPROVED). The log is kept in `.codex-review/`.

## Why

The owner asked for "a new all encompassing settings page that is intuitive and not confusing", with the
Suricata rules, notification channels and backup and restore inside the Settings tabs. Before, Settings had
eight tabs, plus three sub-pages reached only through buttons in its page head (NET-199). Notifications were
split across the Notifications tab (threshold, email, webhook) and a separate "Notification channels" page,
both editing the same notification hub records. The page file was 1,921 lines.

## What changed

- **Section menu.** A grouped side menu (`SettingsNav.svelte`, a WAI-ARIA tablist; one scrolling row on a phone):
  Alerts & detection (Notifications, Suricata rules) · Data (Storage & retention, Capture, Backup & restore) ·
  Network (Network, Integrations, API keys) · General (Display, About). Every tab opens with a one-line intro.
- **URL-driven tabs.** The open tab comes from the URL (`?tab=`), so links, Back and Forward all switch it.
  The old tab ids are kept, so existing deep links still work.
- **Old addresses redirect.** `/settings/suricata-rules`, `/settings/notifications` and `/settings/backup`
  redirect (308) to their tab.
- **Each tab is its own component** (`settings/tabs/`). Only the open tab is mounted, so it loads fresh.
  This makes a restore show at once on the other tabs. Each tab registers the top bar's Refresh itself, and
  only when it has read-only figures.
- **Unsaved edits are guarded, not silently lost.** A tab with unsaved changes holds navigation behind a
  Keep editing / Discard and continue bar. A tab sending a change holds it until the change lands. Back
  and Forward resume correctly after Discard.
- **One Notifications tab.** It holds the preferences card plus channels, routing rules and recent deliveries.
  The two halves stay in step: a preferences save reloads the lists, and a channel or rule change reloads
  the preferences, or flags a conflict when they have unsaved edits. Writes go one at a time.

## Files

`web/src/routes/settings/` (page, `SettingsNav`, `settings-helpers.ts`, `Feedback`, `settings.css`, `tabs/*`,
redirect `+page.ts` files), `web/e2e/visual/routes.ts`, `web/src/tests/app-navigation.svelte.ts` (test router),
`scripts/remote/deploy-settings-hub.sh`.

## Verification

- `npx vitest run`: 392 files, 5,166 tests passed (main: 387, 5,110). svelte-check: 0 errors, the 2 existing
  warnings. `check:colors`, `check:e2e` and `npm run build` pass. Visual harness for the settings routes: passes.
- `/deep-review`: no findings. `/ponytail-review`: nothing to cut.

## Lessons

- With one global refresh slot (`pageRefresh.ts`), keeping several self-loading panels mounted makes them
  fight over it. Mount only the active panel and let it own its loader.
- Two UIs that edit the same records must reconcile on every write once they share a page.

## Next steps / follow-ups

- `SuricataRulesTab.svelte` is 868 lines, most of it kept OLD CODE. It was 840 as a page. Trim the OLD CODE
  once it has been stable for 3 cycles (Code Preservation Policy).
