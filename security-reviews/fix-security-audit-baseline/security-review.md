# Security Review

## Review Metadata

* Review Folder: `fix-security-audit-baseline`
* Report Path: `security-reviews/fix-security-audit-baseline/security-review.md`
* Base Ref: `origin/phase-4/infrastructure-redesign` (`f378e85`)
* Base Ref Commit Date: `2026-10-29T19:15:27-07:00`
* Inspected Branch or PR: `fix/security-audit-baseline` (worktree, nothing committed yet)
* Current Commit: `f378e85`
* Review Scope: `staged`
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes` (staged changes only; nothing unstaged)

## Files Reviewed

* `docker/Dockerfile.daemon`
* `docker/Dockerfile.web`
* `web/package.json`
* `web/package-lock.json` was summarized from the resolved versions, not read (lockfile rule). The production bundle moves @sveltejs/kit 2.53.3 → 2.70.3, devalue → 5.9.4 and svelte → 5.57.3. Dev-only packages bumped: vite, vitest 3.2.7 → 4.1.12, ws, postcss, picomatch and esbuild.

## Coverage Summary

* Changed symbols analyzed: 3:
  * the docker-cli build stage
  * the web runtime `node_modules` (dev dependencies pruned)
  * the vitest devDependency, plus the kit version bundled into the server
* Inbound callers inspected:
  * `docker exec` argv builders in `daemon/services/pcap_search.py` and `daemon/services/tshark_service.py`
  * `web/src/hooks.server.ts`, `web/src/lib/server/auth.ts`, `web/src/lib/server/middleware.ts`
  * `web/svelte.config.js`, `web/vite.config.ts`
* Outbound callees inspected: the read-only `/var/run/docker.sock` mount (`docker/docker-compose.yml:700`)
* Sinks considered:
  * command injection through `docker exec` argv
  * auth and session controls after the framework bump: the JWT cookie flags, the CSRF origin check (default) and `PUBLIC_PATHS`
  * a fail-open import if pruning removed a runtime dependency
* Regression patterns checked: removed sanitizers, auth-default flips, weakened cookie flags (`NODE_ENV=production` still set in the runtime image, so `Secure` stays on)
* Trusted rule memory: none
* Limitations / unresolved edges:
  * The kit 2.53 → 2.70 source was not diffed for default changes. The review relied on the app's explicit cookie flags and the default CSRF config.
  * The two remaining kit advisories (low severity, fixed only in kit 3) are dependency-version issues and are not covered here.
* Not covered (by design): DoS, outdated dependencies and CVE counts (the security.yml job measures those), generic hardening
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
