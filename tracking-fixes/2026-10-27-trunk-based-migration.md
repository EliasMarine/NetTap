# Trunk-Based Git Migration (2026-10-27)

**Status:** Done
**Type:** chore / process

## What changed
- `develop` (303 commits ahead of `main`) merged into `main` via PR #127 (`sync/develop-into-main-2026-10-27`, true merge).
- `main` is now the trunk and default branch; `develop` retired. Final tip preserved as tag `archive/develop-2026-10-27` (`e46fdb7`).
- New rules: `.claude/rules/git-workflow.md` (adapted from the owner's Veya/ROWN workflow). CLAUDE.md "Git Strategy" now summarizes and points to it.
- CI workflows trigger on `main` and include `edited` in `pull_request` types; Dependabot targets `main`.
- Ruleset `26011127` on `main`: no force-push, no deletion, PR required (0 approvals), admin bypass via PR only.
- Open feature PRs retargeted to `main`; stale Dependabot PRs closed (Dependabot reopens against `main`); merged branches pruned.

## Root cause (why)
`main` sat untouched while `develop` became the real trunk, PRs stacked, and the two lines diverged (license + lint cleanup only on `main`). Merging to `main` deploys nothing (device is hand-deployed), so the staging buffer added cost without benefit.

## Merge resolution
9 conflicts (README Quick Start + 8 daemon files) resolved to develop's side — develop already carried its own F841/F401 cleanup, and its imports are used by newer code. Resulting daemon code is byte-identical to develop; main's Personal Use License, Docker license labels and README overhaul carried over.

## Test results
- Local daemon pytest: failure set identical to develop baseline (23 pre-existing failures, 1720 passed).
- `ruff --select F821`: 0. Ruff total unchanged (674).
- CI on #127: Lint Python / svelte-check / Integration Tests red — all pre-existing (see below).

## Known gap / next step
CI has been red on `develop` since March 2026: 674 ruff errors (99 files unformatted) and 338 svelte-check errors, so the test jobs never run in CI. Integration Tests also have 24 pre-existing failures. Next: a `fix/ci-baseline` PR, then add the CI jobs as required status checks on ruleset `26011127`.

## Lessons
- Check `gh pr checks` on the integration branch itself before a migration — the red baseline changes what "merge on green" can mean.
- `integration.yml` only ran on PRs to `main`, so it had never exercised `develop`; its first run surfaced failures nobody had seen.
