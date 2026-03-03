# NetTap v1.0.0 Release Verification — Source of Truth

> **Last updated:** 2026-03-02
> **Status:** 13/17 checks verified across 2 environments (Dev + N100) — 2 FAIL on Dev (shellcheck, Docker), E2E fixed
> **Target:** v1.0.0

This document tracks every verification test run, its environment, results, and what's still outstanding. It is the **single source of truth** for release readiness — consult it before any release-related work and update it after every test run.

---

## Table of Contents

- [Quick Reference](#quick-reference)
- [Verification Environments](#verification-environments)
- [Automated Checks (verify-release.sh)](#automated-checks-verify-releasesh)
- [Hardware Verification (Manual)](#hardware-verification-manual)
- [Pre-Release Gate](#pre-release-gate)
- [Test Execution Log](#test-execution-log)
- [Missing Tools on N100](#missing-tools-on-n100)

---

## Quick Reference

| Environment | Mode | Date | Result | Passed | Failed | Skipped |
|---|---|---|---|---|---|---|
| N100 (Ubuntu) | `--quick` | 2026-03-02 | ALL PASSED | 7 | 0 | 8 |
| N100 (Ubuntu) | `--full` | 2026-03-02 | ALL PASSED | 7 | 0 | 8 |
| Dev (macOS) | `--full` | 2026-03-02 | **3 FAIL** | 5 | 3 | 2 |

---

## Verification Environments

### Dev Machine (macOS) — full toolchain

- **OS:** macOS (Darwin)
- **Purpose:** Full linting, type checking, unit tests, format checks
- **Tools available:** shellcheck, pytest, npm, vitest, svelte-check, playwright
- **Tools missing:** ruff, trivy, docker compose V2 plugin
- **Status:** Tested `--full` — 6 pass, 2 fail (#3 shellcheck, #8 docker), 2 skip (#2 ruff, #9 trivy). E2E fixed (6/8 pass, 2 skip)

### N100 Target Hardware (Ubuntu) — production

- **OS:** Ubuntu Server 22.04 LTS
- **Hardware:** Intel N100, 16GB RAM, 1TB NVMe, dual Intel i226-V 2.5GbE
- **Purpose:** Docker builds, integration testing, hardware verification
- **Tools available:** docker, python3, git, bash
- **Tools missing:** ruff, shellcheck, pytest, npm, trivy, playwright (see [Missing Tools](#missing-tools-on-n100))
- **Status:** Partial — automated checks pass but 8 skipped due to missing tools

### GitHub Actions CI — automated

- **Purpose:** Full automated pipeline (lint + test + build + scan)
- **Status:** Not yet configured

---

## Automated Checks (verify-release.sh)

All 10 checks from `scripts/verify-release.sh`, tracked per environment and mode.

| # | Check | Dev (--quick) | Dev (--full) | N100 (--quick) | N100 (--full) | CI | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Secrets Audit | PASS | PASS | PASS | PASS | — | No hardcoded secrets, .env excluded from git |
| 2 | Python Lint (ruff) | SKIP | SKIP | SKIP | SKIP | — | ruff not installed on either machine |
| 3 | Shell Lint (shellcheck) | **FAIL** | **FAIL** | SKIP | SKIP | — | SC2221/SC2222 pattern overlap in deploy-malcolm.sh, SC2034 unused vars, SC2155 declare+assign |
| 4 | Python Tests (pytest) | PASS | PASS | SKIP | SKIP | — | 997/997 passed (1.65s) on Dev |
| 5 | Web Dependencies (npm ci) | PASS | PASS | SKIP | SKIP | — | 0 vulnerabilities, 212 packages |
| 6 | Web Type Check (svelte-check) | PASS | PASS | SKIP | SKIP | — | 0 errors, 0 warnings |
| 7 | Web Unit Tests (vitest) | PASS | PASS | SKIP | SKIP | — | 649/649 passed (2.61s) on Dev |
| 8 | Docker Builds | n/a (quick) | **FAIL** | n/a (quick) | PASS | — | macOS: `docker compose -f` not recognized (V2 plugin missing). N100: all 4 images build OK |
| 9 | Trivy CVE Scan | n/a (quick) | SKIP (no images) | n/a (quick) | SKIP (not installed) | — | Dev: trivy installed, but no Docker images to scan (builds fail on macOS). Fixed broken `docker-credential-desktop` symlink workaround. N100: trivy not installed |
| 10 | E2E Tests (Playwright) | n/a (quick) | PASS | n/a (quick) | SKIP | — | Dev: 6/8 passed, 2 skipped. Fixed selector + CSRF + DATA_DIR issues. See [E2E Failures](#e2e-test-failures-dev) |

**Legend:** PASS = verified passing, FAIL = verified failing, SKIP = tool not available, n/a = not included in mode, — = not yet run

---

## Hardware Verification (Manual)

These 7 checks require the full Docker stack running on the N100 target hardware. They cannot be automated and must be performed manually.

| # | Check | Target | Status | Date | Operator | Notes |
|---|---|---|---|---|---|---|
| H1 | Integration test — full Docker stack up | N100 | NOT TESTED | — | — | All Malcolm + NetTap containers healthy |
| H2 | Manual E2E install from scratch | N100 | NOT TESTED | — | — | Run `install.sh` on fresh Ubuntu, verify full setup |
| H3 | Bridge 500Mbps zero packet loss | N100 | NOT TESTED | — | — | iperf3 through br0, verify 0 drops at 500Mbps sustained |
| H4 | Dashboard loads < 3s on LAN | N100 | NOT TESTED | — | — | Measure TTFB + full load of main dashboard page |
| H5 | Suricata alerts surface < 10s | N100 | NOT TESTED | — | — | Trigger known signature, measure time to dashboard alert |
| H6 | Storage pruning at 80% threshold | N100 | NOT TESTED | — | — | Fill disk to >80%, verify daemon prunes oldest data |
| H7 | Setup wizard completes from scratch | N100 | NOT TESTED | — | — | Fresh install, complete wizard, verify all settings persist |

---

## Pre-Release Gate

All items must be checked before tagging `v1.0.0` on `main`.

- [ ] All automated checks PASS on Dev (`--full`) — no SKIPs
- [ ] All automated checks PASS on N100 (`--full`) — no SKIPs
- [ ] All automated checks PASS on CI — full pipeline green
- [ ] All 7 hardware verification checks completed (H1–H7)
- [ ] No CRITICAL/HIGH CVEs (Trivy scan clean)
- [ ] Release notes drafted
- [ ] Changelog generated (`git-cliff` or manual)
- [ ] Version bumped in `web/package.json` + `daemon/pyproject.toml`
- [ ] `develop` merged to `main` with `v1.0.0` tag
- [ ] GitHub Release created with assets

---

## Test Execution Log

Chronological log of all verification test runs. Add a new row after every run.

| Date | Environment | Mode | Result | Passed | Failed | Skipped | Operator | Notes |
|---|---|---|---|---|---|---|---|---|
| 2026-03-02 | N100 (Ubuntu) | `--quick` | ALL PASSED | 7 | 0 | 8 | Elias | First run. 8 checks skipped — dev tools not installed on production host. |
| 2026-03-02 | N100 (Ubuntu) | `--full` | ALL PASSED | 7 | 0 | 8 | Elias | Docker builds pass. Trivy + Playwright skipped (not installed). |
| 2026-03-02 | N100 (Ubuntu) | `--full` | ALL PASSED | 7 | 0 | 8 | Elias | Re-run, identical results. Same 8 skips — dev tools still not installed. |
| 2026-03-02 | Dev (macOS) | `--full` | **3 FAIL** | 5 | 3 | 2 | Elias | First dev run. FAIL: shellcheck (#3), docker builds (#8), E2E (#10). SKIP: ruff (#2), trivy (#9). pytest 997/997, vitest 649/649, svelte-check clean. |

---

## Failures to Fix

### Shellcheck Failures (Dev — Check #3)

shellcheck runs on Dev but reports warnings that cause non-zero exit. Key issues:

| File | Code | Severity | Issue |
|------|------|----------|-------|
| `scripts/install/deploy-malcolm.sh` | SC2221/SC2222 | warning | `*healthy*` pattern overrides later `*unhealthy*` pattern (lines 350/357). Same for `*starting*` overriding `*Restarting*` (lines 354/360) |
| `scripts/install/deploy-malcolm.sh` | SC2034 | warning | `critical_services` declared but unused (line 224) |
| `scripts/install/deploy-malcolm.sh` | SC2155 | warning | Declare and assign separately for `name` variable (lines 488, 502) |
| `scripts/verify-release.sh` | SC2034 | warning | `RUN_SECRETS` appears unused (line 126) |
| `scripts/verify-release.sh` | SC2086 | info | Unquoted `$DOCKER_CMD` (line 367) |
| Multiple scripts | SC1091 | info | `source` not following dynamic paths — safe to ignore with `shellcheck -x` |

**Fix priority:** Medium — warnings are real bugs (pattern overlap, unused vars). Info-level SC1091 can be suppressed with `# shellcheck source=path` directives.

### Docker Build Failures (Dev — Check #8)

macOS Docker doesn't have the Compose V2 plugin (`docker compose`). The script uses `docker compose -f ...` which fails with "unknown shorthand flag: 'f'". This is expected — **Docker builds should only run on the N100 production host** or in CI, not on the dev Mac.

**Fix priority:** Low — the script could detect the platform and skip Docker on macOS, or we accept this as a known limitation and only run Docker builds on N100/CI.

### E2E Test Failures (Dev — Check #10) — FIXED {#e2e-test-failures-dev}

3 of 8 Playwright tests failed, 3 passed, 2 skipped. All failures were in `e2e/setup-wizard.spec.ts`.

**Status:** All 3 failures fixed on `fix/nic-led-identify-fallback` branch. E2E now passes 6/8 (2 skipped).

| Test | Error | Root Cause | Fix |
|------|-------|------------|-----|
| `first-run redirects to /setup` | `getByText('Setup Wizard')` not found | Wizard page heading is "Welcome to NetTap", not "Setup Wizard" (title tag only) | Changed to `getByRole('heading', { name: 'Welcome to NetTap' })` |
| `wizard step navigation` | `getByText('Network Interfaces')` resolved to 2+ elements (strict mode) | `getByText` matched `<h2>` heading AND `<p>` description text | Changed to `getByRole('heading', ...)` for all step assertions (Interfaces, Bridge, Storage) |
| `account creation completes setup` | 403 "Cross-site POST form submissions are forbidden" | Missing `ORIGIN` env for adapter-node CSRF check; also missing `DATA_DIR` env for auth module; broken form action mock with wrong response format | Added `ORIGIN` + `DATA_DIR` to `playwright.config.ts` webServer env; removed broken mock, let real server handle form |

**Files changed:**
- `web/playwright.config.ts` — Added `DATA_DIR` (temp dir) and `ORIGIN` env vars to webServer config
- `web/e2e/setup-wizard.spec.ts` — Fixed selectors, added serial mode + beforeAll cleanup, removed broken form action mock

---

## Missing Tools on N100

These tools need to be installed on the N100 production host for full `--full` verification. Alternatively, run these checks on the dev machine or CI instead.

| Tool | Install Command | Purpose | Check(s) | Priority |
|---|---|---|---|---|
| ruff | `pip install ruff` | Python linting + formatting | #2 | Medium — can run on dev/CI |
| shellcheck | `sudo apt install shellcheck` | Shell script linting | #3 | Medium — can run on dev/CI |
| pytest | `pip install pytest` | Python unit tests | #4 | Medium — can run on dev/CI |
| npm | `curl -fsSL https://deb.nodesource.com/setup_20.x \| sudo -E bash - && sudo apt install -y nodejs` | Web dependency install, type check, unit tests | #5, #6, #7 | Medium — can run on dev/CI |
| trivy | `curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh \| sudo sh -s -- -b /usr/local/bin` | Container CVE scanning | #9 | High — should run on build host |
| playwright | `cd web && npx playwright install --with-deps` | End-to-end browser tests | #10 | Low — best run on dev/CI |

### Missing Tools on Dev (macOS)

| Tool | Install Command | Purpose | Check(s) |
|---|---|---|---|
| ruff | `pip install ruff` | Python linting + formatting | #2 |
| trivy | `brew install trivy` | Container CVE scanning | #9 |

**Recommended strategy:** Install ruff and trivy on both machines. Run lint/test/E2E on Dev. Run Docker builds + Trivy image scanning on N100. CI should run everything.

---

## Notes

- The `verify-release.sh` script treats SKIP as non-failure (exit 0), so "ALL PASSED" with SKIPs means "nothing failed, but coverage is incomplete."
- `--quick` mode runs checks 1–7 only (secrets, lint, tests). `--full` adds Docker builds (#8), Trivy (#9), and E2E (#10).
- Hardware checks (H1–H7) are derived from the project's key design constraints in `CLAUDE.md` and `NetTap_PRD_v1.0.md`.
