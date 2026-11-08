# Security Review

## Review Metadata

* Review Folder: `fix-tools-timeouts`
* Report Path: `security-reviews/fix-tools-timeouts/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T17:11:50-08:00`
* Inspected Branch or PR: `fix/tools-timeouts`
* Current Commit: `c7e09813` (an ancestor of `origin/main` `0baac9bb`; the change is staged)
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes`

## Files Reviewed

* `daemon/services/dns_recon_service.py`
* `daemon/api/tools.py` (`handle_dns_recon` answers 503 when the lookup cap is reached)
* `web/src/lib/server/daemon.ts`
* `web/src/routes/api/tools/dns-recon/+server.ts`, `ping/+server.ts`, `traceroute/+server.ts`, `ssl-cert/+server.ts`
* Tests (excluded by rule 7): `daemon/tests/test_dns_recon_service.py`, `web/src/lib/server/daemon.test.ts`, `web/src/routes/api/tools/tools-timeouts.test.ts`

## Coverage Summary

* Changed symbols analyzed: 6:
  * `DnsReconService._query` (new)
  * `_dig_failure` (new)
  * `DnsReconService.validate_record_types` (dedupe)
  * `DnsReconService.lookup` (concurrent queries, at most 4 lookups at once, reject-fast)
  * the `daemonFetch` catch branch
  * `TOOL_TIMEOUT_MS` and its 4 proxy routes
* Inbound callers inspected: 2:
  * `daemon/api/tools.py` `handle_dns_recon` is the only caller of `lookup`.
  * The 4 Tools routes are the new users of `TOOL_TIMEOUT_MS`.
* Outbound callees inspected:
  * `asyncio.create_subprocess_exec` (dig argv)
  * `validate_domain` / `DOMAIN_PATTERN`
  * `_parse_dig_output`
  * the daemon token gate in `daemon/api/server.py`
  * the session gate for `/api/tools/*` in `web/src/hooks.server.ts`
* Sinks considered:
  * dig argument injection. The domain must start and end with a letter or digit, so it cannot begin with `+`, `-` or `@`, and record types come from a whitelist.
  * subprocess text now returned to the client: dig's diagnostic line, shown to a logged-in user only.
  * daemon token disclosure in error bodies: the timeout text is a fixed string.
  * child-process cleanup on timeout, error and cancellation.
* Regression patterns checked:
  * removed validators: none
  * widened inputs: record types deduplicated, so at most 9 per request
  * auth-default flips: none
  * visibility changes: none
* Trusted rule memory: none
* Limitations / unresolved edges: none. The ping, traceroute and ssl-cert routes carry the same one-argument change as dns-recon.
* Not covered (by design): DoS and resource use beyond the cap (one lookup starts up to 9 dig processes; at most 4 lookups run at once), rate limiting, dependency CVEs, generic hardening. Run the two-angle review for those.
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
