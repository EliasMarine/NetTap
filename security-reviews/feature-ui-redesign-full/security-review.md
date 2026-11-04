# Security Review

## Review Metadata

* Review Folder: `feature-ui-redesign-full`
* Report Path: `security-reviews/feature-ui-redesign-full/security-review.md`
* Base Ref: `HEAD` (`7823cf2`): staged changes only, as requested
* Base Ref Commit Date: `2026-11-03`
* Inspected Branch or PR: `feature/ui-redesign-full`
* Current Commit: `7823cf2`
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `no` (untracked `scripts/remote/*` files predate this work and are not part of the change)

## Files Reviewed

* `web/src/app.html`: theme bootstrap script (attribute rename)
* `web/src/lib/components/ui/Icon.svelte`, `web/src/lib/components/ui/icons.ts`: `{@html}` of static icon markup
* `web/src/lib/stores/alertSnapshot.ts`, `web/src/lib/stores/pageRefresh.ts`: new client stores with server-render guards
* `web/src/lib/styles/{tokens,system,forms,a11y,global}.css`: new and trimmed global CSS (checked for remote loads)
* `web/scripts/check-colors.mjs`: colour-gate path exemption
* `web/src/lib/stores/theme.ts`, `web/src/lib/components/ThemePicker.svelte`, `web/src/lib/components/live/GeoMap.svelte`, `web/src/lib/utils/tokens.ts`: theme attribute rename
* `web/src/lib/utils/{severity,series,category-colors}.ts`, `web/src/lib/components/ui/charts/geometry.ts`, `web/src/lib/api/logs.ts`: pure helpers
* Tests changed alongside (excluded by rule)

## Coverage Summary

* Changed symbols analyzed: 6
* Inbound callers inspected: 2 (new stores and Icon have no production callers yet)
* Outbound callees inspected: 4 (`getAlertCount`, `/api/alerts/count` route, `hooks.server.ts` public-path list, `icons.ts`)
* Sinks considered: xss (`{@html}`), DOM attribute writes, same-origin fetch, server-side shared module state, remote resource loads in CSS
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: the new stores and `Icon` have no consumers yet; their call sites are reviewed when the shell and pages land
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
