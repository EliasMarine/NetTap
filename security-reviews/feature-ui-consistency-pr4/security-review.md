# Security Review

## Review Metadata

* Review Folder: `feature-ui-consistency-pr4`
* Report Path: `security-reviews/feature-ui-consistency-pr4/security-review.md`
* Base Ref: `origin/main` (`9174eda`)
* Base Ref Commit Date: `2026-11-07T00:37:35-08:00`
* Inspected Branch or PR: `feature/ui-consistency-pr4` (NET-192 PR 4)
* Current Commit: `c3496a6` (7 commits)
* Review Scope: `committed`
* Diff Sources: `git diff --find-renames origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

70 files, web only:

* web/src/lib/utils/time.ts (new `formatTime`) and its users across `web/src/routes/**` and `web/src/lib/components/**`
* web/src/lib/components/ui/AutoRefreshButton.svelte (new)
* web/src/lib/api/devices-registry.ts (`getDeviceTraffic` takes a window), web/src/lib/api/*.ts (formatter re-exports)
* web/src/routes/api/notifications/from-alerts/+server.ts (a number format in a notification message)
* range sets and refresh wiring in web/src/routes/{dns,connections,alerts,alerts/[category],logs,pcap,iot,address/[ip],domain/[name],certificates,devices/[ip],devices/mac,settings,threats,live,+page}.svelte
* web/DESIGN-SYSTEM.md

## Coverage Summary

* Changed symbols analyzed: `formatTime`, `AutoRefreshButton`, `getDeviceTraffic`, the `formatNumber` re-export, each page's range set and fallback, Settings `registerPageRefresh`, the from-alerts message text.
* Inbound callers inspected: devices/mac page for `getDeviceTraffic`; every page that renders `AutoRefreshButton`.
* Outbound callees inspected: `fetch` (same-origin `/api/devices/registry/{mac}/traffic`, with `encodeURIComponent(mac)` and a `URLSearchParams` query from the page's own window), `Intl.DateTimeFormat`, `Intl.NumberFormat`, and the existing `fmt` and `formatCompactNumber`.
* Sinks considered: DOM injection (`{@html}`, `innerHTML`), URL and href building, `fetch`, `goto`, storage and cookies, and server routes and hooks.
* Regression patterns checked: removed sanitizers, auth defaults, new public paths, hook changes. None found: no `{@html}`, `innerHTML`, new `href`, storage, hook or `lib/server` change.
* Trusted rule memory: none.
* Limitations / unresolved edges: the only server-side change is `from-alerts/+server.ts`, which swaps `toLocaleString()` for `fmt()` in a message string that Svelte renders as text. The one new client request adds `from`/`to` to an existing same-origin call; the daemon validates them (unreadable times are a 400 since batch 41). No changed symbol crosses a trust boundary, so the multi-agent stages were not run; this was a coordinator-only pass.
* Not covered (by design): DoS, rate limiting, dependency CVEs, general hardening.
* External analysis consumed: none.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
