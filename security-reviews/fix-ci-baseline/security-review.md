# Security Review

## Review Metadata

* Review Folder: `fix-ci-baseline`
* Report Path: `security-reviews/fix-ci-baseline/security-review.md`
* Base Ref: `ea03265`
* Base Ref Commit Date: `2026-10-29T18:27:16-07:00`
* Inspected Branch or PR: `fix/ci-baseline`
* Current Commit: `4d26c07`
* Review Scope: `committed-only`
* Diff Sources: `ea03265...HEAD`, plus `9a7464b` (config-only, the commit just before the base) for context
* Dirty Working Tree Included: `no`

## Files Reviewed

* `daemon/api/devices.py`
* `daemon/services/iot_monitor.py`
* `.gitignore`
* `.github/workflows/ci.yml`
* `.github/workflows/integration.yml`
* `daemon/pyproject.toml`
* `web/src/routes/+page.svelte`
* `web/src/lib/api/devices.ts`
* `web/src/lib/components/drawer/content/ConnectionDrawerContent.svelte`
* Excluded by Hard Exclusion #7: `daemon/tests/*` (capture stub, cyberchef, devices API, dns, iot monitor, iot trust scorer, main, pcap search), `CONTRIBUTING.md`, `docs/developer-guide/contributing.md`, `daemon/data/oui_database.json` (static vendor data)

## Coverage Summary

* Changed symbols analyzed: 3 (`handle_device_list` route; `.gitignore` allowlist; CI install lines and ruff pin), plus the client-side web changes
* Inbound callers inspected: 4 (`daemon/api/devices.py:1039` route registration, `web/src/routes/+page.svelte:185`, `web/src/lib/api/devices.ts` `getDevices`, the `web/src/routes/api/[...path]/+server.ts` proxy)
* Outbound callees inspected: 1 (the OpenSearch `client.search` body; the new sub-aggregations use fixed field names)
* Sinks considered: injection (OpenSearch query body), XSS (Svelte attribute interpolation), authorization (new response fields compared with `handle_device_detail`), secret exposure (`.gitignore` allowlist, checked against `daemon/data/notifications.json`, nested paths, dotfiles and other `data/` folders), CI supply chain (install lines, triggers unchanged)
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges:
  * The mechanical `ruff format` commit `ea03265` (112 files) was excluded by request; it changes no behavior and daemon tests were identical before and after it.
  * `daemon/services/pcap_search.py` filter validation is not changed by this diff; only its tests are, so the filter rules themselves were not re-reviewed here.
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
