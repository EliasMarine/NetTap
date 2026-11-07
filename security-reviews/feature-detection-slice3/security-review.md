# Security Review

## Review Metadata

* Review Folder: `feature-detection-slice3`
* Report Path: `security-reviews/feature-detection-slice3/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T06:20:47-08:00`
* Inspected Branch or PR: `feature/detection-slice3`
* Current Commit: `bb5087df`
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

* `daemon/api/suricata_rules.py`
* `daemon/services/owner_rules.py` (new)
* `daemon/services/owner_rules_validator.py` (new)
* `daemon/services/suricata_rules.py`
* `docker/docker-compose.yml`
* `web/src/routes/api/suricata/rules/custom/+server.ts`
* `web/src/routes/api/suricata/rules/custom/check/+server.ts` (new)
* `web/src/lib/api/suricata-rules.ts`
* `web/src/routes/settings/suricata-rules/+page.svelte`, `OwnerRulesCard.svelte` (new)
* `scripts/remote/check-owner-rules.sh` (new), `scripts/remote/deploy-detection-slice3.sh` (new), `scripts/remote/deploy-detection-slice2.sh`, `scripts/remote/verify-detection.sh`, `scripts/remote/verify_detection.py`
* Tests and docs in the diff (excluded from findings): `daemon/tests/*`, `tests/scripts/*`, `web/**/*.test.ts`, `web/e2e/visual/fixtures/suricata.ts`, `docs/**`, `tracking-fixes/**`
* Unchanged files read for context: `web/src/hooks.server.ts`, `web/src/lib/server/daemon.ts`, `web/src/lib/server/auth.ts`, `daemon/api/daemon_auth.py`, `daemon/api/server.py`, `daemon/services/etpro.py` (`_run`), `daemon/services/rules_lock.py`, `config/suricata/nettap.yaml`, `config/suricata/nettap-rules-update.sh`, `scripts/remote/rules-checks.sh`

## Coverage Summary

* Changed symbols analyzed: 28
* Inbound callers inspected: 10
* Outbound callees inspected: 12
* Sinks considered: command/argv (docker run, cp, exec, inspect), file-io (root create, rename, unlink, rmtree and link-following in the suricata-custom-rules, nettap-rules-staging and nettap-rules-state volumes), rule-parser differential (validator vs Suricata loader), auth (session gate, daemon token, CSRF), secret/log exposure, xss
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: Suricata 8.0.7's rule-loader and parser source and Malcolm's generated suricata.yaml (Lua, datasets and filestore settings) are not in the repo; their behaviour was reasoned from upstream knowledge, not read or run.
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.

## Delta re-run over bb5087df..861dafae

### Review Metadata

* Mode: delta re-run over `bb5087df..861dafae` (the prior report above covered `origin/main...bb5087df`)
* Base Ref: `bb5087df` (verified an ancestor of HEAD; no rebase)
* Base Ref Commit Date: `2026-11-07T07:11:39-08:00`
* Inspected Branch or PR: `feature/detection-slice3`
* Current Commit: `861dafae`
* Review Scope: `committed-only`
* Diff Sources: `bb5087df...HEAD`
* Dirty Working Tree Included: `no` (only this untracked report folder)

### Files Reviewed

* `daemon/services/owner_rules_validator.py` (rewritten)
* `daemon/services/owner_rules.py` (`-T` plus engine-analysis run, `analysis_problem`, `write_file_atomic`, `run_blocking`, failure classes, reload retry)
* `daemon/services/etpro.py` (`_run` returns `None` on timeout)
* `daemon/api/suricata_rules.py`, `daemon/services/suricata_rules.py`
* `web/src/routes/api/suricata/rules/custom/+server.ts`, `web/src/routes/api/suricata/rules/custom/check/+server.ts`, `web/src/lib/api/suricata-rules.ts`, `web/src/routes/settings/suricata-rules/OwnerRulesCard.svelte`, `+page.svelte`
* `scripts/remote/check-owner-rules.sh`, `scripts/remote/deploy-detection-slice2.sh`, `scripts/remote/deploy-detection-slice3.sh`
* Tests and docs in the delta (excluded from findings)
* Unchanged files read for context: `daemon/services/capture_config.py` (`write_file_atomic`), `daemon/api/offload.py` (`run_blocking`), `daemon/services/malcolm_upgrade.py` (`DAEMON_CONTAINER`), `daemon/services/rules_lock.py`, `daemon/api/server.py` (`logging_middleware`)

### Probe Results

* **Validator vs Suricata.** No remaining disagreement found that lets a refused keyword or a non-`alert` action reach a loaded rule.
  * The quoted `;`: fixed.
  * The header gap: fixed. Where the space/tab and `[ ]` splitting still differs, Suricata ends up reading text from the `(` as a header field, so the rule fails `-T` instead of loading.
  * The line join (non-LF separators, NUL, trailing `\`, leading whitespace, over-length lines): fixed.
  * Option names are ASCII-only and compared case-insensitively.
  * `FORBIDDEN` covers every Suricata 8.0.x keyword and alias found that runs code, changes the engine, or reads or writes a file the rule names.
* **Engine-analysis step.** Its verdict could not be spoofed, and it does not fail open.
  * A save is accepted only on exit 0 plus "0 rules failed".
  * If `rules.json` is missing or has a different shape, the rule count check refuses the save.
  * A timeout returns 500 and the container is removed.
  * Rule text can't start a line in the output the daemon parses, and in `rules.json` it is JSON-escaped.
  * Residual: if one bidirectional rule writes two entries, the count check could hide one rule that fails to load. That matters only after a validator bypass, and none was found.
* **Extra `docker run`.**
  * `TEST_SH` and `"$@"` are daemon constants; nothing in them comes from the rule text or from suricata-live.
  * The only new writable area is an in-container 64 MB tmpfs; there is no new host mount.
  * Capabilities, user, network and no-new-privileges are unchanged.
  * `--log-driver none` keeps `-T` output out of container logs.
* **Root following links.**
  * `write_file_atomic` creates its temp file with O_EXCL (`mkstemp`) and renames it into place, only in directories no other container can write.
  * The stage directories are created by root before `docker cp` fills them.
  * `_clean_stale` and `rmtree` do not follow links.
* **Rule bodies in logs.** None. Daemon logs carry counts, exception type names and fixed reasons. Suricata's error text goes only into the reply to the admin who sent the rules. The web relays don't log.
* **`_run` timeout change.** The other callers (`etpro.py` L127, L184) compare with `rc == 0` / `rc != 0`, so `None` is still treated as a failure.

### Coverage Summary

* Changed symbols analyzed: 30
* Inbound callers inspected: 9
* Outbound callees inspected: 10
* Sinks considered: rule-parser differential (validator vs Suricata loader and parser), command/argv (docker run, cp, exec, rm), file-io (root temp, rename, rmtree in shared volumes), verdict parsing of combined process output, secret/log exposure, web relay status handling
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: Suricata 8.0.x `detect-parse.c` was read upstream (branch `main-8.0.x`, not tag 8.0.7). `DetectLoadSigFile` behaviour and Malcolm's generated suricata.yaml (Lua, datasets) were taken from upstream knowledge, not read. Nothing was run against Suricata.
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

### Findings

No high-confidence security vulnerabilities found in the reviewed changes.
