# Security Review

## Review Metadata

* Review Folder: `feature-display-default-range`
* Report Path: `security-reviews/feature-display-default-range/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T09:35:42-08:00`
* Inspected Branch or PR: `feature/display-default-range`
* Current Commit: `97f4a5cc`
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

* `scripts/remote/deploy-display-default-range.sh`
* `web/src/lib/utils/drilldown.ts`
* `web/src/routes/+page.svelte`
* `web/src/routes/address/[ip]/+page.svelte`
* `web/src/routes/alerts/+page.svelte`
* `web/src/routes/alerts/[category]/+page.svelte`
* `web/src/routes/alerts/suricata/[name]/+page.svelte`
* `web/src/routes/alerts/suricata/[name]/suricata-view.ts`
* `web/src/routes/certificates/cert-view.ts`
* `web/src/routes/connections/+page.svelte`
* `web/src/routes/devices/+page.svelte`
* `web/src/routes/devices/[ip]/+page.svelte`
* `web/src/routes/devices/mac/[mac]/+page.svelte`
* `web/src/routes/dns/+page.svelte`
* `web/src/routes/domain/[name]/+page.svelte`
* `web/src/routes/iot/+page.svelte`
* `web/src/routes/logs/+page.svelte`
* `web/src/routes/pcap/+page.svelte`
* `web/src/routes/settings/+page.svelte`
* `web/src/routes/threats/+page.svelte`
* `web/src/routes/traffic/[category]/+page.svelte`
* Excluded as test, doc or generated (hard exclusion 7): `web/src/lib/utils/drilldown.test.ts`, `web/e2e/visual/default-range.visual.ts`, the eight `*.test.ts` files under `web/src/routes`, `tracking-fixes/2026-11-07-display-default-range.md`
* Unchanged context read: `web/src/routes/certificates/+page.svelte`, `web/src/routes/certificates/CertDetail.svelte`, `web/src/routes/api/notifications/from-alerts/+server.ts`, `web/src/lib/server/daemon.ts`, `web/src/lib/components/ui/Icon.svelte`, other `scripts/remote/deploy-*.sh`

## Coverage Summary

* Changed symbols analyzed: 27 (2 new helpers, Settings load and save, 2 shared-list aliases, 12 page range lists, 4 window helpers, 4 URL range handlers, 1 device script)
* Inbound callers inspected: 22 (17 `startRange` call sites, Settings, the unchanged Certificates page and CertDetail, the Suricata page, the one server importer of `drilldown.ts`)
* Outbound callees inspected: 7 (`localStorage`/`JSON.parse`, `rangeWindow`, `customRange`, `windowQuery`, and `git`, `docker`, `curl` in the script)
* Sinks considered: xss (raw-HTML sinks), query-string injection, command injection, secret exposure, SSR cross-user state
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: no server, auth or API file is changed; the daemon's own checks on `from`/`to` were not re-read (unchanged)
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
