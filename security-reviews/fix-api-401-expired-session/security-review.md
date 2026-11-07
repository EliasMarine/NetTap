# Security Review

## Review Metadata

* Review Folder: `fix-api-401-expired-session`
* Report Path: `security-reviews/fix-api-401-expired-session/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T08:36:01-08:00`
* Inspected Branch or PR: `fix/api-401-expired-session`
* Current Commit: `4376a547`
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

* `web/src/hooks.server.ts`
* `scripts/remote/deploy-api-401.sh`
* `web/e2e/visual/known-issues.ts` (test fixture, excluded)
* `web/src/hooks.server.test.ts` (test, excluded)
* `web/src/hooks.server.store.test.ts` (test, excluded)
* `web/e2e/visual/api-401.visual.ts` (test, excluded)
* `tracking-fixes/2026-11-07-api-401.md` (docs, excluded)
* Unchanged context: `web/src/routes/api/[...path]/+server.ts`, `web/src/lib/server/auth.ts` (`verifyToken`, `hasUsers`), `web/svelte.config.js`, `web/node_modules/@sveltejs/kit/src/runtime/server/respond.js`, `web/node_modules/@sveltejs/kit/src/exports/index.js`

## Coverage Summary

* Changed symbols analyzed: 4 (`handle`, `unauthorised`, the remote-function 401 branch, `deploy-api-401.sh`)
* Inbound callers inspected: 3 (`respond.js:457` hook call, `hooks.server.ts:112`, `hooks.server.ts:156`)
* Outbound callees inspected: 4 (`resolve` to the `api/[...path]` daemon proxy, `daemonFetch`, kit `json()`, kit CSRF and redirect handling in `respond.js`)
* Sinks considered: auth decision (resolve or refuse), daemon proxy with the daemon token, CSRF origin check, cookies and headers on the response, information disclosure, shell script input
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: none
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
