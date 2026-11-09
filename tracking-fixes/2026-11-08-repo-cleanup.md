# 2026-11-08 — Remove tracked files nothing needs (repo cleanup)

**Status:** NET-214. PR #229 open on `chore/repo-cleanup`, not merged; the owner reviews the list first. Plan approved by Codex in round 3 of 5 (`.codex-review/2026-11-08-155021-repo-cleanup/`, gitignored). The owner's follow-up (round 2 below) was approved in round 4 (`.codex-review/2026-11-08-163758-repo-cleanup-addendum/`).

## Round 1: files nothing uses

**What changed**
- 124 files deleted, nothing added or edited (apart from this note). 1.73 MB.
  - 86 `scripts/remote/` one-offs: 70 deploy scripts that check out a merged feature branch before rebuilding, 4 branchless one-offs nothing mentions, and 12 verify helpers only those scripts call.
  - 30 HTML mockups (`mockups/`, `web/mockups/`) and the 2 "Digital Sentinel" docs in `design/`. The full redesign (PR #166) and `nettap-design-system/` replaced them.
  - 4 strays: `tests/fixtures/sample.pcap` (no reader since Phase 3), an unreferenced PNG in `docs/plans/`, and two `.gitkeep` files in Grafana folders that already hold files.
  - `web/src/lib/utils/thresholds.ts` and its test: nothing imports it since the redesign.

**Why**
- Running any of the 70 branch-pinned deploy scripts today would roll the device back to stale code.
- The rest was dead weight: files that no code, config, CI job, test, docs page or runbook uses.

**The rule**
- A file goes only if no live file names it. Dated history notes don't count: `tracking-fixes/`, `security-reviews/`, `plans/`, `docs/plans/`, `docs/reviews/`, and the Debugging logs DEPLOYMENT-ISSUES, RELEASE-VERIFICATION and RELIABILITY-TRACKER. Git keeps every removed file.
- Two exceptions keep a script even when only history names it:
  - **Open step:** a note still says to run it (pending, not yet verified, "other boxes should run …").
  - **Functional migration:** it makes a one-time host, `.env`, container, volume or OpenSearch change that neither the installer nor a normal deploy makes.

**Kept on purpose (nine scripts that looked removable)**
- **Open steps:** `deploy-malcolm-field-names.sh` (the N100 and other boxes), `deploy-pr110-review-fixes.sh` (not yet verified on a device), `deploy-dhcp-gateway-mode.sh` (hardware trial), `deploy-display-default-range.sh` (G11 hand check pending).
- **Migrations:**
  - `deploy-review-batch-1.sh`: systemd units and the Grafana DB password.
  - `deploy-data-accuracy-batch5.sh` and `-batch16.sh`: remove the stale arkime-live and grafana containers.
  - `-batch17.sh`: writes the `arkime_sessions3_template` marker on boxes installed before 2026-11-02. (Corrected: an earlier version said it was the only code that writes it. The installer has written it since `3b53849`.)
  - `-batch24.sh`: resets a saved placeholder in `excluded_ips.json`.

**Tests (before → after, same tree)**
- daemon pytest: 4,093 passed, 4 skipped → identical.
- vitest: 331 files, 4,131 tests → 330 files, 4,082 tests. The 49 fewer are exactly `thresholds.test.ts`.
- svelte-check: 0 errors, 2 warnings → identical.
- `check:colors`: clean.
- bats: 245 ok, 0 not ok → identical.
- shellcheck: no new files flagged; 12 fewer lines, all from deleted scripts.
- `docker compose config`: OK.
- `mkdocs build --strict` with the docs workflow's plugins: OK. The built site differs only by the removed PNG.

## Round 2: the owner's follow-up (same PR)

**What changed**
- **Removed** the root `PLAN.md` (the merged 2026-11 redesign plan). `web/DESIGN-SYSTEM.md` now says `git show f71625ab:PLAN.md`.
- **Removed** `daemon/storage/pcap_integrity.py` and its 5 tests in `test_storage_hardening.py`. Nothing imported it (checked with an import graph of the daemon).
- **Untracked and gitignored, kept on disk:** `docs/`, `mkdocs.yml`, `.github/workflows/docs.yml`, `NetTap_PRD_v1.0.md`, `security-reviews/` and `CLAUDE.md`.
  - Before that, the README's logo and media moved to `.github/assets/`, and the README's links into `docs/` now point at the published site (all return 200).
  - `npm run capture:media` writes to `.github/assets/media/` now. The tour MP4 it also writes is gitignored there; copy it to `docs/assets/media/` by hand for the docs site.
  - The System page's help text and `DhcpGoLive.svelte` no longer point at `CLAUDE.md` on a live branch. System names `bash scripts/remote/fix-opensearch.sh`; DhcpGoLive links to CLAUDE.md at commit `deb9b219`.
  - `daemon/services/dhcp_gateway.py`'s docstring names the `git show` for its design doc.
- **Pointed at main:** the 11 kept device scripts (the nine above plus `fix-index-template.sh` and `deploy-drop-nsenter.sh`). Each old `BRANCH=` line is kept as `OLD CODE`.
- **DeviceList comment:** names `monotonePath` as the upgrade path. `ui/charts/Sparkline.svelte` is the KPI-foot chart (zero-based, 52 px, end dots), so it does not fit the mini line.

**Recommendations (no code change)**
- **Keep** `internet-health.ts`, `lan-security.ts`, `mac-correlation.ts` and `reports.ts`. Each has a working daemon endpoint and tests, but no page. LAN security lost its page in the IoT rewrite (`6c8b9247`); the other three never had one. Giving each a page is NET-215.
- **Keep** `Sparkline.svelte`. No page imports it yet, but it is the design system's KPI-foot sparkline (`nettap-design-system/components/KpiCard/README.md:10`, `Charts/README.md:10`) and `web/DESIGN-SYSTEM.md:77` lists it. It is not a drop-in for DeviceList's mini line, so only DeviceList's comment changed.
- **`arkime_sessions3_template`:** the installer already writes it. The real gap was `activate-bridge.sh` (the `--defer-bridge` path), which started the stack without the bootstrap. Fixed separately in PR #231 (NET-216).

**Tests (before → after round 2)**
- daemon pytest: 4,093 → 4,088 passed (the 5 removed checksum tests), 4 skipped.
- vitest: 332 files, 4,086 tests → identical.
- svelte-check: 0 errors, 2 warnings → identical.
- `check:colors`: clean. bats: 245 → identical. shellcheck: identical. `docker compose config`: OK.
- `npm run test:visual`: 286 passed, 49 skipped.

**What this means for the owner**
- **The docs site is frozen** at its last deploy: `docs.yml` and the docs source are no longer in the repo.
- **A fresh clone has no CLAUDE.md**, and neither do worktrees made outside `.claude/worktrees/` (Orca, `/tmp`). Edits to CLAUDE.md are no longer versioned.
- **`/deep-review` reports stay local.** Copy `security-reviews/`, `docs/`, the PRD and `CLAUDE.md` out of a worktree before removing it.
- **After merging and pulling**, git deletes the newly untracked files from the owner's checkout. Restore them from the backup taken first (the PR body has the exact commands).

**Lessons**
- A merged branch doesn't make its deploy script dead. Codex found scripts that carry host or data migrations, and others a note still names as a step for other boxes. Scan script bodies for writes, not just their names for references.
- Searching by file name over-matches `index.html` and `design.md`. Check those by full path.
- `git grep … | head -5` can be filled by history notes and hide the live hit. That is how the false "installer gap" claim got in.

**Next steps (owner)**
- Review and merge #229, then run the restore commands from its body.
- Review and merge #231.
- Fold the kept migration scripts into the installer or a standing upgrade script.
