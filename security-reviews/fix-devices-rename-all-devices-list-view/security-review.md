# Security Review

## Review Metadata

* Review Folder: `fix-devices-rename-all-devices-list-view`
* Report Path: `security-reviews/fix-devices-rename-all-devices-list-view/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T15:22:22-08:00`
* Inspected Branch or PR: `fix/devices-rename-all-devices-list-view`
* Current Commit: `c7e09813`
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes`

## Files Reviewed

* `web/src/lib/components/shell/topbar.ts`
* `web/src/lib/components/shell/TopBar.svelte`
* `web/src/routes/devices/[ip]/+page.svelte`
* `web/src/lib/components/DeviceCustomise.svelte` (moved from `web/src/routes/devices/mac/[mac]/`)
* `web/src/routes/devices/mac/[mac]/+page.svelte`
* `web/src/routes/devices/+page.svelte`
* Tests and visual specs (excluded by rule 7): `topbar.test.ts`, `DeviceCustomise.test.ts`, `device-detail-customise.test.ts`, `devices-by-type.test.ts`, `e2e/visual/devices-layout.visual.ts`

## Coverage Summary

* Changed symbols analyzed: 9 (`searchTarget`, `isSearchIp`, `deviceSuggestions`, `toSuggestion`, TopBar `submit`/`searchDevices`/`loadLanPolicy`, IP page `customise`/`withOwner` and the load overlay, the `DeviceCustomise` prop)
* Inbound callers inspected: 3 (TopBar is the only importer of `searchTarget`; the IP and MAC device pages are the only importers of `DeviceCustomise`)
* Outbound callees inspected: 8:
  * web side: `getRegistryDevices`, `saveDevice` / `setDeviceName` / `clearDeviceName` / `setDevicePicture` (`web/src/lib/api/devices-registry.ts`), `addressHref` / `domainHref` (`web/src/lib/stores/lan.ts`), `canonicalName` / `isHostName` (`web/src/lib/utils/drilldown.ts`)
  * daemon side: `_run` / `_apply` / `normalize_mac` (`daemon/api/device_custom.py`, `daemon/services/device_custom.py`)
* Sinks considered: client navigation (open redirect / protocol-relative URLs), XSS through rendering of network-learned hostnames, authenticated write routes (PUT/DELETE `/api/devices/registry/{mac}/name|picture`), session and CSRF coverage of the newly called routes, and URL-parser use as a validator
* Regression patterns checked: removed sanitizers, weakened types (the `DeviceCustomise` prop widened), auth-default flips, tenant-filter removal, visibility changes (TopBar now calls `/api/devices/registry` and `/api/network/lan`)
* Trusted rule memory: none
* Limitations / unresolved edges: none. The PR is web-client only, and no server route, hook, `lib/server` or daemon file changed.
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening. Run the two-angle review for those.
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
