# Security Review

## Review Metadata

* Review Folder: `feature-live-globe`
* Report Path: `security-reviews/feature-live-globe/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T20:22:23-08:00`
* Inspected Branch or PR: `feature/live-globe`
* Current Commit: `ae66847b`
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached` (the committed diff `origin/main...HEAD` is empty)
* Dirty Working Tree Included: `yes`

## Files Reviewed

Security-relevant (clustered, large-diff mode: 38 files, ~4,000 lines):

* `daemon/api/home_location.py` (new): GET/PUT/DELETE `/api/settings/home-location`, POST `/wan-lookup` (outbound HTTPS to a fixed URL)
* `daemon/services/home_location.py` (new): validation and atomic file store
* `daemon/api/server.py`: route registration
* `daemon/api/live.py`: detail `geo=` parameter, GeoIP enrichment target
* `daemon/services/live_connections.py`: `country_filter`, `_format_connection` remote-end rule, `fetch_connection_detail(geo_ip=)`
* `web/src/lib/api/home-location.ts`, `web/src/lib/api/live.ts`, `web/src/lib/utils/drilldown.ts`
* `web/src/routes/settings/LocationCard.svelte`, `web/src/routes/settings/+page.svelte`
* `web/src/lib/components/live/LiveGlobeCard.svelte`, `web/src/lib/components/ui/charts/Globe.svelte`, `web/src/lib/components/ui/charts/globe/land.js`
* `web/src/routes/live/+page.svelte`
* `scripts/remote/deploy-live-globe.sh`, `web/playwright.visual.config.ts`, `web/package.json`

Unchanged files read for reachability: `web/src/hooks.server.ts`, `web/src/routes/api/[...path]/+server.ts`, `web/src/lib/server/auth.ts`, `web/src/lib/server/middleware.ts`, `web/svelte.config.js`, `daemon/api/server.py` (middleware), `docker/docker-compose.yml` (data volume).

Not clustered (no trust boundary): tests, the client-only three.js canvas engine (`web/src/lib/components/ui/charts/globe/{engine,materials,geo,tokens}.js`), visual fixtures, docs, `package-lock.json`.

## Coverage Summary

* Changed symbols analyzed: 16
* Inbound callers inspected: 9
* Outbound callees inspected: 8
* Sinks considered: file-io, outbound HTTP (SSRF), OpenSearch query building (injection), JSON parsing of an untrusted reply, DOM rendering (XSS), auth/CSRF on the new mutating routes, secret handling in the deploy script
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: none
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
