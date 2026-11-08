# Security Review

## Review Metadata

* Review Folder: `fix-threat-score-accuracy`
* Report Path: `security-reviews/fix-threat-score-accuracy/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-08T10:56:11-08:00`
* Inspected Branch or PR: `fix/threat-score-accuracy` (NET-209)
* Current Commit: `a64ab622` (no commits beyond the base; the change is staged)
* Review Scope: `uncommitted-only` (staged), plus post-review deltas checked by the coordinator: `daemon/services/alert_findings.py` (`findings_by_group`, `finding_severity`, `epoch_ms`), `daemon/services/alert_intelligence.py` (reputation group severity; unused port-boost helpers moved to OLD CODE) and `daemon/api/risk.py` (`_ms`, day-range key check)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes`

## Files Reviewed

- daemon/api/risk.py
- daemon/api/devices.py
- daemon/api/alerts.py
- daemon/api/threats.py
- daemon/api/drilldown_runner.py
- daemon/services/alert_findings.py (new)
- daemon/services/alert_intelligence.py
- daemon/services/risk_scoring.py
- daemon/services/investigation.py
- scripts/remote/deploy-threat-accuracy.sh (new)
- scripts/remote/verify_threat_accuracy.py (new)
- web/src/routes/devices/[ip]/+page.svelte
- web/src/routes/threats/+page.svelte
- web/src/routes/+page.svelte
- web/src/lib/api/alerts.ts
- Tests and docs: excluded by rule

## Coverage Summary

* Changed symbols analyzed: 16
* Inbound callers inspected: 12 (routes in api/alerts.py, api/risk.py, api/devices.py, api/threats.py, api/domains.py, api/addresses.py; services/investigation.py; web proxy routes and hooks)
* Outbound callees inspected: 9 (all_buckets, checked, total_hits, parse_time_range, lan_subnets_of, cidr, build_lan_filter, is_suppressed, write_file_atomic)
* Sinks considered: OpenSearch query DSL injection, path/route parameter handling, authorization on device routes, secret handling in deploy scripts, detection and suppression controls, client-side redirects
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: not confirmed whether Malcolm's Zeek writes interim long-connection records into `event.dataset: conn` (that file is not in the repo)
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
