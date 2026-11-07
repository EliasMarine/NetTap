# Security Review

## Review Metadata

* Review Folder: `fix-tools-require-login`
* Report Path: `security-reviews/fix-tools-require-login/security-review.md`
* Base Ref: `origin/main` (`08a9f2f`)
* Base Ref Commit Date: `2026-11-07T01:08:00-08:00` (approximate; the merge of #202)
* Inspected Branch or PR: `fix/tools-require-login` (NET-193)
* Current Commit: reviewed at `bb5c9de8`; the findings below were re-checked against the fix commits that followed
* Review Scope: `committed`
* Diff Sources: `git diff --find-renames origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

* web/src/hooks.server.ts
* web/src/hooks.server.test.ts (test-only, excluded from findings)
* scripts/remote/deploy-tools-login.sh and scripts/remote/deploy-pr110-review-fixes.sh (device scripts, excluded under hard exclusion 16)

## Coverage Summary

* Changed symbols analyzed: `PUBLIC_PATHS`, `isPublicPath`, `isUnder`, `isFirstRunPath`, the `handle` order (health, remote-call guard, public, first-run, auth).
* Inbound callers inspected: every SvelteKit route under `web/src/routes/api/auth`, `api/tools`, `api/lookup`, `tools`, `lookup`, `login`, `setup` and `go-live`; the catch-all proxy `web/src/routes/api/[...path]/+server.ts`; `web/src/lib/server/daemon.ts` (`daemonFetch` adds the daemon token).
* Outbound callees inspected: `daemon/api/daemon_auth.py` (token middleware; every route except `GET /api/health`), and the daemon's route table (no `/api/auth` route, no catch-all).
* Sinks considered: anonymous requests reaching the daemon with the daemon token through the proxy; URL normalisation (`%2e%2e`, `%2F`, `//`, case, trailing slash, `__data.json`); first-run paths; remote-function pathnames.
* Regression patterns checked: auth default flips, newly public paths, prefix over-matching.
* Trusted rule memory: none.
* Limitations / unresolved edges:
  * Agent B and the coordinator reviewed this; Stage 3 voting was not needed because there were no candidates.
  * A separate security-engineer review ran in parallel and probed SvelteKit 2.70.3 and aiohttp 3.13.3 behaviour locally. Its Low finding is fixed on the branch: `/api/auth/<route>/x` fell through to the proxy, and public paths are now matched exactly.
  * Pre-existing and not changed: `/cyberchef/` has no `auth_request` in nginx. It is a static app that runs in the browser.
* Not covered (by design): DoS, rate limiting, dependency CVEs.
* External analysis consumed: none.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
