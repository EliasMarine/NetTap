# Security Review

## Review Metadata

* Review Folder: `feature-ui-redesign-full`
* Report Path: `security-reviews/feature-ui-redesign-full/security-review.md`
* Base Ref: `661c37a`
* Base Ref Commit Date: `2026-11-03T20:00:07-08:00`
* Inspected Branch or PR: `feature/ui-redesign-full`
* Current Commit: `3500a80`
* Review Scope: `committed-only`
* Diff Sources: `661c37a...HEAD` (35 commits, 227 files, +24145 / -41302)
* Dirty Working Tree Included: `no` (no staged or unstaged changes; the five untracked `scripts/remote/*` files predate the branch, are not part of it, and handle no secrets)

## Files Reviewed

Large-diff path. The changed files were grouped into clusters, and only the security-relevant ones were reviewed in depth:

* Auth forms: `web/src/routes/login/+page.svelte`, `web/src/routes/setup/+page.svelte` (the `?/createAdmin` form and the wizard step indicator)
* Alert actions: `web/src/routes/alerts/AlertDetail.svelte` (new), `web/src/routes/alerts/alert-view.ts` (new), `web/src/routes/alerts/+page.svelte`, `web/src/routes/alerts/[category]/+page.svelte`
* Links built from data: `web/src/routes/+page.svelte`, `web/src/routes/bandwidth/+page.svelte`, `web/src/routes/logs/+page.svelte`, `web/src/routes/geoip/[ip]/+page.svelte`, `web/src/routes/threats/+page.svelte`, `web/src/routes/devices/+page.svelte`, `web/src/routes/tools/ping/+page.svelte`, `web/src/routes/tools/ssl-cert/+page.svelte`
* Raw HTML and icons: `web/src/routes/changelog/+page.svelte`, `web/src/lib/components/golive/DhcpGoLive.svelte`, `web/src/routes/go-live/+page.svelte`, `web/src/routes/tools/+page.svelte`
* Iframes: `web/src/routes/system/cyberchef/+page.svelte`, `web/src/routes/tools/cyberchef/+page.svelte`
* Secrets in settings: `web/src/routes/settings/+page.svelte`, `web/src/routes/settings/notifications/+page.svelte`, `web/src/routes/settings/backup/+page.svelte`, `web/src/routes/system/updates/+page.svelte`
* Modified shared components: `ContextMenu`, `ConnectionDrawer`, `drawer/content/*`, `SessionTimeline`, `SankeyDiagram`, `NewDeviceBanner`, `SearchBar`, `tshark/FilterInput`, `ui/DataTable`, `stores/pageRefresh.ts`, `stores/alertSnapshot.ts`, `web/package.json`, `web/scripts/check-colors.mjs`
* Unchanged files read for context: `web/src/hooks.server.ts`, `web/src/routes/setup/+page.server.ts`, `web/src/routes/api/alerts/[id]/+server.ts`, `web/src/lib/api/alerts.ts`, `web/src/lib/components/ui/Icon.svelte`, `ui/icons.ts`, `ui/device-icon.ts`, `ui/BarList.svelte`, `web/svelte.config.js`

## Coverage Summary

* Changed symbols analyzed: 14
* Inbound callers inspected: 12
* Outbound callees inspected: 11
* Sinks considered: XSS (`{@html}`, DOM HTML APIs, `javascript:` and protocol-relative URLs in href/src), iframe src and sandbox, query building, auth/session gates, form actions and CSRF, secret exposure in inputs, URLs and attributes
* Regression patterns checked: removed sanitizers or `encodeURIComponent`, weakened types, auth-default flips, tenant-filter removal, visibility changes, password-to-text input changes
* Trusted rule memory: none (no `security-reviews/_rules/`)
* Limitations / unresolved edges: the change is front-end only. These have an empty diff in this range: `web/src/lib/server`, `web/src/hooks.server.ts`, `web/src/routes/api`, `daemon`, `web/src/lib/api`, `web/src/lib/components/shell` (Sidebar logout form), the layouts and every `*.server.ts`. The added lines bring in no raw-HTML sinks, `fetch` calls, mutating HTTP methods or `<form>` elements. Markup-only parts of large pages were covered by these diff-wide checks, not line-by-line reading.
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
