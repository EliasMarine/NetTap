# Security Review

## Review Metadata

* Review Folder: `feature-detection-slice2`
* Report Path: `security-reviews/feature-detection-slice2/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T02:56:46-08:00`
* Inspected Branch or PR: `feature/detection-slice2`
* Current Commit: `49650990` (the branch has no commits of its own; the review covers the staged changes)
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes` (staged changes, 47 files)

## Files Reviewed

- config/suricata/nettap-rules-update.sh (new)
- config/capture/nettap-capture-env.sh
- docker/docker-compose.yml
- daemon/api/suricata_rules.py, daemon/api/capture_control.py, daemon/api/settings.py
- daemon/services/etpro.py (new), daemon/services/rules_lock.py (new), daemon/services/suricata_rules.py
- web/src/routes/api/suricata/rules/commercial/+server.ts, web/src/routes/api/suricata/rules/update/+server.ts
- web/src/lib/server/daemon.ts, web/src/lib/api/suricata-rules.ts
- web/src/routes/settings/+page.svelte, web/src/routes/settings/suricata-rules/+page.svelte
- scripts/remote/: rules-lock.sh, rules-checks.sh, gate-detection-slice2.sh, deploy-detection-slice2.sh, rollback-detection-slice2.sh, check-etpro-canary.sh, check-rules-update-safety.sh (new); verify-detection.sh, verify_detection.py
- Test, fixture and documentation files: excluded (hard exclusion 7)

## Coverage Summary

* Changed symbols analyzed: 10 symbol clusters, covering 28 functions and handlers
* Inbound callers inspected: 14, including the compose entrypoint, the daemon routes and web proxies, the capture-mode restart, the shim callers (startup, cron, "Update now") and the other capture containers that source the loader
* Outbound callees inspected: 12, including write_file_atomic, aiohttp HEAD, the asyncio subprocess docker exec/restart calls, suricatasc, jq, the sed redaction, flock and daemonFetch
* Sinks considered: command injection, ssrf, path/symlink following, secret_exposure (ET Pro code, daemon token), auth/authorization (daemon token middleware, web session hook, new DELETE route), csrf
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges:
  - The Malcolm 26.10.0 image internals (file ownership under /var/lib/suricata, supervisord users) are not in the repo and could not be read.
  - Large-diff mode was used: per-cluster diffs.
  - A root `start` step writes and chowns a fixed temp path inside a directory the `suricata` user probably owns. Exploiting it needs prior code execution as that user, so it was not reported; it is noted as hardening only.
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.

## Delta after the review (hand-checked, same branch, before the first commit)

These changes came from the hardening note above and the over-engineering review. Each was checked against the same sinks.

* `start` hardening (the noted path): links in `/run/nettap-rules` are removed, the lock file is created with O_EXCL, and the sources file goes through a fresh temp file with `chown -h`. A bats test plants the links and checks nothing outside is written or chowned.
* ET Pro preflight: a one-byte GET (`Range: bytes=0-0`) replaces the HEAD. The URL is the same fixed Proofpoint host and path, redirects are followed as before, the body is not read, and failures still log only the exception type. No new SSRF surface; the code is still never logged or returned.
* Web proxies for DHCP gateway enable/disable and setup save: the timeout rises from 60 s to 290 s. Auth is unchanged (the hooks gate by path). Only a signed-in admin can hold the request open longer.
* `capture_control._restart_if_running`: a redundant `except RulesBusyError` was removed; the generic `except Exception` below it gives the same reply.
* `check-rules-update-safety.sh`: the last check reads the new container's log with `grep -q` (prints nothing from the log). The shared preflight moved to `rules-checks.sh` unchanged.

No findings.

## Review round 2 (security-engineer review of 6abb4a81, fixes hand-checked)

The security-engineer review found M1, L1–L4, I1, I3, I4 and I5; none critical. Each fix and its test is listed in `tracking-fixes/2026-11-06-detection-accuracy.md` under "Reviews (round 2)". These are the checks made on the fixes themselves:

* `rules_lock.open_regular` (M1) is the only way the daemon opens a file on the rules state volume: `O_NOFOLLOW | O_NONBLOCK`, regular files only, and the status read is capped at 64 KiB. The marker check (`os.path.exists`) only yields a boolean, so a link there exposes nothing.
* `start` (L1) refuses a linked parent before any wipe or write, and still installs the shim, so updates keep the lock. No process runs as `suricata` during `start`, so the check can't be raced.
* `update` (L3) refuses uid 0 before it reads or writes anything. The startup update (`su -p $PUSER`), supercronic, "Update now" (`docker exec -u suricata`) and the gate (`--user $PUID:$PGID`) all run as the user.
* Malcolm's output is redacted before it reaches the disk (I4), and the status reason has its control characters stripped (L4). Neither path prints the code.
* The rollback removes slice 2's source files with `docker exec -u suricata`, so root never follows a link in that directory.
* The legacy key cleanup (I5) logs the key name and the file path, never the value. An OSError logs only the exception type.
* I3 (root in other containers that mount `/etc/nettap` can read the code) is recorded as a follow-up. Nothing was changed for it.

Not re-run: the full multi-agent /deep-review. The round 2 diff is the fix set from a dedicated security review, checked by hand as above.
