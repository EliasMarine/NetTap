# Security Review

## Review Metadata

* Review Folder: `feature-drill-down-slice2`
* Report Path: `security-reviews/feature-drill-down-slice2/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-06T13:19:32-08:00`
* Inspected Branch or PR: `feature/drill-down-slice2`
* Current Commit: `a4887f8` plus staged changes
* Review Scope: `committed + staged`
* Diff Sources: `origin/main...HEAD`, `git diff --cached`
* Dirty Working Tree Included: `yes` (staged slice 2a page changes)

## Files Reviewed

* `web/src/lib/utils/drilldown.ts` (href builders, `customRange`, `windowQuery`)
* `web/src/routes/alerts/+page.svelte`, `web/src/routes/alerts/[category]/+page.svelte`, `web/src/routes/alerts/AlertDetail.svelte`
* `web/src/routes/logs/+page.svelte`, `web/src/lib/components/drawer/content/LogDrawerContent.svelte`
* `web/src/routes/devices/[ip]/+page.svelte`, `web/src/routes/devices/mac/[mac]/+page.svelte`, `web/src/routes/address/[ip]/+page.svelte`, `web/src/routes/domain/[name]/+page.svelte`
* `web/src/routes/threats/+page.svelte`, `web/src/routes/certificates/+page.svelte`, `web/src/routes/certificates/cert-view.ts`
* `web/src/lib/components/drawer/content/ConnectionDrawerContent.svelte`, `LiveConnectionDrawerContent.svelte`
* Tests, the plan, the tracking doc and `web/DESIGN-SYSTEM.md` (out of scope by design)

## Coverage Summary

* Changed symbols analyzed: 6 clusters (Alerts URL hand-off and `setListParams`, Log Explorer URL hand-off and window, drill href builders, `goto($ipHref(...))` navigation, Log Explorer domain cells, page links built from response data)
* Inbound callers inspected: URL query parameters from `$page.url`, response data from the `$api` clients
* Outbound callees inspected: `web/src/lib/api/alerts.ts`, `logs.ts` clients → same-origin `/api/*` proxy → daemon handlers (unchanged); `web/src/lib/stores/lan.ts` `addressHref`
* Sinks considered: injection (query params to the daemon), open redirect / navigation, XSS via attribute or raw HTML, auth
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: client-side only; the daemon handlers these parameters reach were not changed by this diff
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
