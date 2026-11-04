# Security Review

## Review Metadata

* Review Folder: `feature-ui-redesign-foundation`
* Report Path: `security-reviews/feature-ui-redesign-foundation/security-review.md`
* Base Ref: `HEAD` (`2c66270`, which is `origin/main` `c6448e7` plus one docs-only commit)
* Base Ref Commit Date: `2026-11-03T11:52:35-08:00`
* Inspected Branch or PR: `feature/ui-redesign-foundation`
* Current Commit: `2c66270`
* Review Scope: `staged` (the foundation commit, before it is committed)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: no. The unstaged visual-harness files are a separate later commit and were not reviewed here.

## Files Reviewed

The diff has 86 files, so it was reviewed in large-diff mode, by cluster:

* **Theme bootstrap and store:** `web/src/app.html`, `web/src/lib/stores/theme.ts`, `web/src/lib/components/ThemePicker.svelte`, `web/src/routes/settings/+page.svelte`
* **Canvas and scheduling:** `web/src/lib/components/live/GeoMap.svelte`, `web/src/lib/components/live/arc-scheduler.ts`, `web/src/lib/utils/tokens.ts`
* **Tooling and CI:** `web/scripts/check-colors.mjs`, `web/scripts/check-colors.allowlist`, `.github/workflows/ci.yml`, `web/package.json`
* **Device script:** `scripts/remote/deploy-ui-redesign.sh`
* **Server:** `web/src/lib/server/notifications.ts` (one comment line)
* **Layout:** `web/src/routes/+layout.svelte` (the Google Fonts links were removed)
* **Colour-token swaps** in about 55 `.svelte`/`.ts`/`.css` files, plus `web/src/lib/api/logs.ts` and `web/src/lib/utils/thresholds.ts`. Every new `style=` binding was checked: each one uses only constant token strings.
* **Static font files** under `web/static/fonts/`, and docs (`web/DESIGN-SYSTEM.md`, `THIRD-PARTY-LICENSES.md`)

## Coverage Summary

* **Changed symbols analyzed:** 7 (the bootstrap script; `setTheme`/`isThemeVariant`; `ThemePicker`; GeoMap `drawFrame`/`readColors`/scheduler wiring; `createArcScheduler`; `findColorLiterals`/`main`; `web_get` and the deploy flow)
* **Inbound callers inspected:** 6
* **Outbound callees inspected:** 9
* **Sinks considered:** XSS (raw-HTML sinks, `style=` injection), DOM attribute writes, command injection (shell, `docker exec`, `node -e`), SSRF (in-container fetch), secret exposure (deploy script output, CI step), CI trigger/permissions
* **Regression patterns checked:** removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* **Trusted rule memory:** none (`security-reviews/_rules/` does not exist)
* **Limitations / unresolved edges:** large-diff mode. The colour-token swaps were checked for new data-bound `style=` bindings and new raw-HTML sinks, not read line by line. The GeoMap `bindTooltip` label (GeoIP city/country) is pre-existing and unchanged by this diff.
* **Not covered (by design):** DoS/ReDoS, rate limiting, dependency CVEs, generic hardening. Run the two-angle review for those.
* **External analysis consumed:** none
* **Visual harness commit (follow-up):** fast path; no multi-agent stages were run. It is test-only: `web/e2e/visual/**` and `web/playwright.visual.config.ts`, a local fixture daemon bound to 127.0.0.1 with synthetic data, and a random per-run token file at mode 0600. It also adds two `package.json` scripts and one CI step that runs `tsc --noEmit` on the harness, with no new permissions, secrets or triggers. Nothing in it ships in the app image.
* **Delta after review fixes:** re-checked by the coordinator. The ponytail fixes are CSS/token values, a shared category-colour map, colour-gate logic, and the deploy script now looping over its own server's stylesheet links (fixed host, `grep -q`, nothing printed). They add no new trust edge.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
