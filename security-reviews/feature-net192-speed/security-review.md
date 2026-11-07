# Security Review

## Review Metadata

* Review Folder: `feature-net192-speed`
* Report Path: `security-reviews/feature-net192-speed/security-review.md`
* Base Ref: `origin/main` (`00ece924`)
* Base Ref Commit Date: `2026-11-07T01:50:06-08:00`
* Inspected Branch or PR: `feature/net192-speed`
* Current Commit: `fc59a144`
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

* daemon/api/lookup.py
* daemon/api/threats.py
* daemon/api/traffic.py
* daemon/main.py
* daemon/services/beacon_snapshots.py
* daemon/services/excluded_ips.py
* daemon/services/investigation.py
* daemon/services/ttl_cache.py
* daemon/storage/manager.py
* daemon/storage/query_timing.py
* docker/docker-compose.yml
* scripts/remote/deploy-speed-timing.sh
* scripts/remote/speed-timing.compose.yml
* scripts/remote/verify_page_speed.py
* web/src/lib/api/lookup.ts
* web/src/lib/api/threats.ts
* web/src/routes/address/[ip]/+page.svelte
* web/src/routes/connections/+page.svelte
* web/src/routes/lookup/dns/[ip]/+page.svelte
* web/src/routes/threats/+page.svelte
* Excluded under Hard Exclusion 7 (tests/docs): daemon/tests/*, web/**/*.test.ts, tracking-fixes/2026-11-07-ui-consistency-speed.md, web/DESIGN-SYSTEM.md

## Coverage Summary

* Changed symbols analyzed: 20
* Inbound callers inspected: 14
* Outbound callees inspected: 9
* Sinks considered: command execution (whois subprocess argv), OpenSearch query construction (terms/CIDR, aggregation keys fed back into queries), auth middleware coverage of new query params and background-served data, secret/PII exposure in new logs and error responses, TLS/auth settings under the new transport class, raw-HTML rendering in Svelte
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: large-diff mode (35 files, ~3,067 changed lines, ~1,350 of them tests excluded); reviewers read the HEAD files and took base behavior from the inline OLD CODE blocks, not from a full base diff
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
