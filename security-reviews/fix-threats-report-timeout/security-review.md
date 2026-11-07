# Security Review

## Review Metadata

* Review Folder: `fix-threats-report-timeout`
* Report Path: `security-reviews/fix-threats-report-timeout/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-06T18:06:55-08:00`
* Inspected Branch or PR: `fix/threats-report-timeout`
* Current Commit: `b0c7f9e`
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

* web/src/lib/server/daemon.ts
* web/src/routes/api/threats/report/+server.ts
* web/src/routes/api/threats/beaconing/+server.ts
* web/src/lib/api/threats.ts
* web/src/routes/api/threats-proxy.test.ts (test only)

## Coverage Summary

* Changed symbols analysed: 3 (`THREAT_SCAN_TIMEOUT_MS`, the two proxy `GET` handlers, `getThreatReport`)
* Inbound callers inspected: 2 (the threats page through `getThreatReport`, and the proxy routes)
* Outbound callees inspected: 4 (`daemonFetch`, the auth guard in `hooks.server.ts`, the daemon's `handle_threat_report` and `handle_beaconing`, and `parse_time_range` and `iso_param`)
* Sinks considered: SSRF and path injection (daemon URL construction), auth bypass, secret exposure
* Regression patterns checked: removed sanitisers, weakened types, auth-default flips, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: `isFirstRunPath` (which paths are reachable before setup completes) was not read. The diff does not touch it.
* Not covered (by design): DoS and resource holding from the longer waits, rate limiting, dependency CVEs
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
