# Security Review

## Review Metadata

* Review Folder: `fix-pr110-review`
* Report Path: `security-reviews/fix-pr110-review/security-review.md`
* Base Ref: `f378e85` (f378e851eee7775c14218c1848eb28c278b2962a)
* Base Ref Commit Date: `2026-10-29T19:15:27-07:00`
* Inspected Branch or PR: `fix/pr110-review` (fixes for the PR #110 pre-merge review), worktree `/private/tmp/claude-501/-Volumes-ExtraStrg-RAID1-Mega-Sync-Coding-Projects-NetTap/d3c8cf36-a292-4fdb-b05a-3c0a2d4a0d11/scratchpad/wt-fix`
* Current Commit: `af7104a`
* Review Scope: `committed-only`
* Diff Sources: `f378e85...HEAD` (31 commits, 69 files, 38 non-test source files, +2073/-486 source lines)
* Dirty Working Tree Included: `no` (clean tree)

## Files Reviewed

Trust-boundary clusters (read in full at HEAD, with the base code taken from the inline `OLD CODE` blocks and per-file diffs):

* `daemon/api/daemon_auth.py` (new)
* `daemon/api/server.py`
* `docker/docker-compose.yml`
* `web/src/lib/server/daemon.ts`
* `web/src/hooks.server.ts`
* `web/src/lib/server/auth.ts`
* `web/src/routes/setup/+page.server.ts`
* `web/src/routes/api/setup/storage/+server.ts`
* `daemon/api/devices_v2.py`
* `daemon/services/unifi_integration.py`
* `daemon/services/excluded_ips.py`
* `daemon/api/settings.py`
* `daemon/api/alerts.py`, `daemon/api/logs.py`, `daemon/api/search.py`, `daemon/api/lan_security.py`, `daemon/api/iot.py`
* `daemon/services/threat_detection.py`, `daemon/services/threat_intel.py`, `daemon/services/investigation.py`

Lower-risk changed files (triaged by diff):

* `daemon/api/traffic.py`, `daemon/services/live_connections.py`, `daemon/storage/retention_config.py`, `daemon/main.py`
* `web/src/lib/api/alerts.ts`, `capture.ts`, `infrastructure.ts`, `iot.ts`, `unifi.ts`
* `web/src/routes/alerts/+page.svelte`, `alerts/[category]/+page.svelte`, `connections/+page.svelte`, `devices/[ip]/+page.svelte`, `iot/+page.svelte`, `pcap/+page.svelte`, `settings/+page.svelte`, `setup/+page.svelte`
* `scripts/remote/deploy-pr110-review-fixes.sh`, `CLAUDE.md`, `Debugging/BRIDGE-ARCHITECTURE.md`

Unchanged files read to prove reachability: `web/src/routes/api/[...path]/+server.ts` (catch-all daemon proxy), `web/src/routes/api/tools/mac-lookup/[mac]/+server.ts`, `web/src/routes/api/lookup/whois/[ip]/+server.ts`, `web/src/routes/api/lookup/dns/[ip]/+server.ts`, `docker/nginx.conf`, `daemon/api/tools.py`, `daemon/api/lookup.py`, `web/src/lib/server/middleware.ts`, `web/src/routes/api/auth/login/+server.ts`, `web/src/routes/api/auth/me/+server.ts`, `web/src/routes/api/bridge/teardown/+server.ts`, `web/src/routes/api/setup/configure/+server.ts`, `web/svelte.config.js`, daemon route registrations across `daemon/api/*.py`.

## Coverage Summary

* Changed symbols analyzed: 30
* Inbound callers inspected: ~70 (every `daemonFetch` call site that builds a path from request data, the catch-all proxy, the public tools/lookup routes, the setup action, the UniFi config loader, and the callers of `readUsers`/`hasUsers`/`createUser`)
* Outbound callees inspected: 14 (aiohttp router and middleware chain, `hmac.compare_digest`, token file I/O, `fetch` in `daemonFetch`, `setAuthCookie`, users.json read/write, `UnifiIntegration._request`, OpenSearch query builders for alerts, logs, search and LAN detections)
* Sinks considered: auth (daemon token middleware, web first-run gate, session cookie), path traversal through web→daemon proxies, SSRF and credential redirect (UniFi `X-API-Key`), secret exposure (token in logs, responses, volume mounts), OpenSearch query construction, raw-HTML sinks in Svelte
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Non-diff read floor (5 per trust-boundary cluster): met for the two highest-risk clusters. A focused re-run read 7 unchanged files for the daemon token middleware and 6 for the web first-run gate (listed under Files Reviewed). It confirmed no findings. For the UniFi key cluster and the excluded-IP cluster, the first-pass reviewers did not report per-cluster read counts, so the floor is not verified there.
* Extra edges closed: only the daemon and `nettap-web` mount the `daemon-auth` volume. No daemon handler returns a redirect, and `normalize_path_middleware` is not used, so `daemonFetch` cannot be redirected and carry the token to another host. The only daemon routes under the public web prefixes are the tools and lookup routes, which were already public in the base.
* Limitations / unresolved edges: large diff reviewed per cluster rather than as one global diff; aiohttp is unpinned (`>=3.9,<4`), so the `GET /api/health` exemption was checked against both raw-path and `path_safe` router matching (it holds under both); first-run-only exposure before an admin exists is by design and was not counted; no runtime execution
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
