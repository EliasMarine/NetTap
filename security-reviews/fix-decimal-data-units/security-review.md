# Security Review

## Review Metadata

* Review Folder: `fix-decimal-data-units`
* Report Path: `security-reviews/fix-decimal-data-units/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-06T13:19:32-08:00`
* Inspected Branch or PR: `fix/decimal-data-units`
* Current Commit: `3c9bd51`
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no` (the only untracked file is the tracking doc)

## Files Reviewed

Security-relevant cluster (full diff and surrounding code):
* `daemon/api/bandwidth.py`: `PUT /api/settings/bandwidth-cap` input conversion
* `daemon/api/opensearch_cluster.py`: `GET /api/opensearch/indices`, `_cat` call and `_byte_count`
* `daemon/services/bandwidth_tracker.py`, `daemon/services/malcolm_upgrade.py`, `daemon/services/nl_search.py`, `daemon/services/update_checker.py`, `daemon/storage/manager.py`
* `web/src/routes/api/setup/storage/+server.ts`: mock fallback constants

Triaged by file list and added-line grep (large-diff mode, 74 files): the other web display formatters, page copies, fixtures and tests, `plans/2026-11-06-net166-decimal-data-units.md`. No new raw-HTML, eval, navigation or fetch sinks in added lines.

## Coverage Summary

* Changed symbols analyzed: 7 (handle_set_cap, _byte_count/handle_indices, _kib_as_gb, NL large-traffic filter, disk_*_gb, release size, get_cap) plus the setup storage fallback
* Inbound callers inspected: daemon auth middleware (`daemon/api/server.py`), route registration, web proxy and session hook
* Outbound callees inspected: BandwidthTracker.save_cap, opensearch-py `cat.indices`
* Sinks considered: injection (OpenSearch query DSL), file-io (cap file write), auth, parsing of upstream output
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: large diff triaged by file list and grep outside the security cluster
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
