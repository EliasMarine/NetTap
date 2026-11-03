# CI Baseline Repair (2026-10-29)

**Status:** CI passing on PR #142 (stacked on #110, `phase-4/infrastructure-redesign`)
**Type:** fix / ci
**Branch:** `fix/ci-baseline` → `phase-4/infrastructure-redesign`

## Problem
CI had failed since March 2026 on every branch. Lint Python and Lint Web failed first, so Test Daemon, Test Web and the four Docker Build jobs were skipped and had never run in CI.

## Root causes
- **Lint Python (735 errors):** no `[tool.ruff]` config plus an unpinned `pip install ruff`. Ruff 0.17 widened its default rules from E4/E7/E9/F to ~400. The real count under the old rules was 5. 112 files had also never been formatted.
- **Lint Web (4 errors):** real bugs and dead code.
  - Alert Summary read a field that doesn't exist (`alertCount.count`).
  - The Top Devices bar showed a made-up 30/70 split, with sent bytes drawn as download.
  - One redundant TShark button condition.
- **Test Daemon (22 + 1):** tests that never caught up with deliberate code changes.
  - Python 3.12 event loop: 13 tests.
  - Display filters (`8763d07`): 4 tests.
  - Zeek rtt in seconds (`5e8acf8`): 1 test.
  - CyberChef HTTP health check (`6b1b1d5`): 2 tests.
  - `oui_database.json` never committed, because `.gitignore`'s `data/` rule also matched `daemon/data/`. It was missing from images built on the device too: 2 tests.
  - One test depended on the host's disks (GitHub runners have `/dev/sda`): 1 test.

## Fix
Commits on `fix/ci-baseline`: `9a7464b` ruff pin, `ea03265` ruff format, `a2b3aa8` lint, `9d53702` + `798ebe8` web/device bytes, `e0757bf` `6020742` `4dacb46` `dcca1d2` `bf54dff` `481a769` tests, `2052e94` OUI DB packaging, `11a46d2` docs, `4d26c07` drop aioresponses.

## Files changed
`.github/workflows/{ci,integration}.yml`, `.gitignore`, `daemon/pyproject.toml`, `daemon/api/devices.py`, `daemon/services/iot_monitor.py`, `daemon/data/oui_database.json`, `daemon/tests/*` (8 files), `web/src/routes/+page.svelte`, `web/src/lib/api/devices.ts`, `web/src/lib/components/drawer/content/ConnectionDrawerContent.svelte`, `CONTRIBUTING.md`, `docs/developer-guide/contributing.md`, plus 112 files reformatted.

## Test results
- **Local, from clean exports matching CI:**
  - ruff: clean
  - pytest (Python 3.12): 2005 passed, 0 failed
  - svelte-check: 0 errors
  - vitest: 1716 passed
  - `npm run build`: succeeds
- **CI on PR #142:** all 9 `ci.yml` jobs pass: ShellCheck, Lint Python, Lint Web, Test Daemon, Test Web, and Docker Build for daemon, web, tshark and cyberchef.
- `security.yml` and Integration Tests only run on PRs into `main`. They're first measured on #110.

## Gates
- `/codex-review` approved the plan in round 2.
- `/ponytail-review`: 2 fixes applied.
- `/deep-review`: no findings.

## Lessons
- Pin linters and formatters, both the version and the rule set. An unpinned tool can turn CI red with no code change.
- Reproduce CI in a clean export (`git archive` + a fresh venv or `npm ci`). The local venv hid two failures: the gitignored OUI file, and aioresponses breaking on the newest aiohttp.
- When the test jobs depend on lint, red lint hides every other failure.

## Next steps
1. Squash-merge #142 into `phase-4/infrastructure-redesign`, then run #110's own gates and merge #110 to `main`.
2. Add the `ci.yml` jobs and Integration Tests as required checks on ruleset `26011127`.
3. Remove the "Known red baseline" bullet from `.claude/rules/git-workflow.md` and add the `uvx ruff@0.17.3` commands to its pre-push list.
4. `fix/security-audit-baseline` for the `security.yml` failures (npm audit, Trivy).
