# Security Review

## Review Metadata

* Review Folder: `feature-certificates-findings`
* Report Path: `security-reviews/feature-certificates-findings/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-05T19:08:18-08:00`
* Inspected Branch or PR: `feature/certificates-findings`
* Current Commit: `983dff5`
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `no` (working tree equals the staged tree for every reviewed file)

## Files Reviewed

* daemon/api/certificates.py
* daemon/api/server.py
* daemon/services/cert_overview.py (new)
* daemon/services/cert_findings.py (new)
* daemon/services/cert_monitor.py
* daemon/storage/manager.py
* web/src/routes/api/[...path]/+server.ts
* web/src/lib/api/certificates.ts
* web/src/routes/certificates/+page.svelte
* web/src/routes/certificates/CertDetail.svelte (new)
* web/src/routes/certificates/cert-view.ts (new)
* scripts/remote/deploy-certificates-findings.sh (new)
* scripts/remote/verify-certificates.py (new)
* scripts/remote/verify-figures.sh
* Tests, fixtures and docs (daemon/tests/*, web/**/*.test.ts, web/e2e/visual/fixtures/*, plans/*, tracking-fixes/*) were excluded by design.

## Coverage Summary

* Changed symbols analyzed: 14 (6 route handlers, `_run`, `CertOverview` and its query builders, `paginate`, `encode_bounded`, `StorageManager.client_kwargs`, the cert client in `server.py`, the drawer and page link builders, the proxy timeout table)
* Inbound callers inspected: 7 (route registration in `server.py`, the daemon auth middleware, the web session hook, the catch-all proxy, `verify-certificates.py`, `verify-figures.sh`, the deploy script)
* Outbound callees inspected: 9 (opensearch-py `search`/`create_pit`/`delete_pit`, `build_excluded_ips_filter`, `parse_time_range`, `cert_findings.build`, `json.JSONEncoder.iterencode`, `daemonFetch`, Svelte interpolation, `encodeURIComponent` hrefs, `docker exec`)
* Sinks considered: injection (OpenSearch DSL, shell), XSS/href, SSRF, auth, secret exposure, error disclosure
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: edits made after the review (failing-sessions-only finding tallies, the after-expiry recount, and the reply sending certificates once) were re-checked by the coordinator only: the new recount query uses structured `term`/`range` filters built from stored fingerprints and a date normalised through `datetime`, so it adds no new sink; large diff reviewed per cluster; the existing `/tools/ssl-cert` handler (now linked from the drawer with the SNI as `host`) was not re-reviewed because it is unchanged
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
