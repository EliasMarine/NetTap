# Security Review

## Review Metadata

* Review Folder: `feature-install-experience`
* Report Path: `security-reviews/feature-install-experience/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T17:38:30-08:00`
* Inspected Branch or PR: `feature/install-experience` (NET-204)
* Current Commit: `ae66847b` (changes staged, not yet committed)
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes` (staged installer changes; unstaged docs and tracking note are doc-only)

## Files Reviewed

* `scripts/common.sh` — `log`/`warn`/`error`/`debug` gain a `NETTAP_UI=fancy` branch; new `status_line`
* `scripts/install/ui.sh` (new) — logo, step headers, cards, countdown, `ui_spin` (background command, `mktemp` output file, trap save/restore with `eval` of `trap -p`), failure and cancel cards
* `scripts/install/install.sh` — argument parsing moved into `parse_args` behind a `BASH_SOURCE` guard; EXIT/INT/TERM/HUP traps; `require_root` and `load_env` earlier in `main`; `installer_version` runs `git -c safe.directory=… describe` as root; summaries moved to cards
* `scripts/install/deploy-malcolm.sh` — `pull_images` runs `docker pull` through `ui_spin` in the fancy layout; a failed pull keeps its 0600 output file and prints its tail and path
* `scripts/install/validate-hardware.sh` — check lines through `status_line`; header box skipped in the fancy layout
* `tests/scripts/test_install_ui.bats` (new) — test-only, excluded
* Unchanged files read for context: every script that sources `scripts/common.sh` (bridge, install, remote helpers), `scripts/install/preflight.sh` (.env writer), `scripts/install/malcolm-versions.conf`

## Coverage Summary

* Changed symbols analyzed: 16
* Inbound callers inspected: 30
* Outbound callees inspected: 12
* Sinks considered: command execution (`eval`, background `"$@"`, git run as root), file-io (temp files in `/tmp`, `.env` sourcing), secret exposure (terminal output, retained logs), process/signal handling
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: `git describe` was reasoned about from git's behaviour (no `--dirty`, no index refresh, no hooks, no pager on a pipe), not run against a hostile `.git/config`; the checkout owner already controls every script root executes, so this adds no boundary
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
