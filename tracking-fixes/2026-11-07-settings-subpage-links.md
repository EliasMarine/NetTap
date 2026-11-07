# 2026-11-07 — Settings links its own pages (NET-199)

**Status:** merged as PR #212 (`1bf4a94`) and deployed to the G11 on 2026-11-07. Every check in `deploy-settings-links.sh` passed.

## Problem

The owner reported that Settings had no Suricata page. The page existed at `/settings/suricata-rules`, built for NET-191 slices 2 and 3. Nothing led to it: no tab, no sidebar entry, only a link inside a sentence on the API keys tab. `/settings/notifications` (notification channels) and `/settings/backup` (backup and restore) had no way in at all.

## Root cause

These sub-pages were never linked, even before the redesign (#166). The old `Breadcrumb.svelte` named them, but a breadcrumb only shows once you are already on the page. Each sub-page links back to Settings; Settings had no link forward.

## Fix

- **`web/src/routes/settings/+page.svelte`:** the page head has a `nav.head-actions` labelled "More settings", with three `.btn` links: Suricata rules, Notification channels, and Backup and restore. They sit outside the tab panel, so they show on every tab. Page recipe step 1 allows head actions.
- **`web/src/routes/settings/settings.test.ts`:** a new test pins the three labels and addresses, and checks the links are still there after switching tabs. It failed before the change.
- **`scripts/remote/deploy-settings-links.sh`:** a web-only deploy for the G11. It defaults to `main`; set `BRANCH=` to try a branch. It checks that the running app carries the new text, that each page redirects to `/login` without a session, and that `/api/health` answers.

## Verification

- **Web:** Vitest 3,955 passed; svelte-check 0 errors; `check:colors` and `check:e2e` clean; the build passes; visual tests for `/settings*` 21 passed. On phones the links wrap onto two rows with no overflow.
- **CI:** 18 of 18 checks passed.
- **G11, at `1bf4a94`:** the running app contains "More settings" and "Notification channels"; `/settings` and each sub-page redirect to `/login`; `/api/health` answers 200; the web log is clean.

## Lesson

A new sub-page needs a way in from its parent page. A back link from the child doesn't make the child findable.
