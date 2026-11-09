# 2026-11-08 — Remove tracked files nothing needs (repo cleanup)

**Status:** NET-214. PR open on `chore/repo-cleanup`, not merged; the owner reviews the list first. Plan approved by Codex in round 3 of 5 (`.codex-review/2026-11-08-155021-repo-cleanup/`, gitignored).

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
  - `-batch17.sh`: the only code that writes the `arkime_sessions3_template` marker.
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

**Lessons**
- A merged branch doesn't make its deploy script dead. Codex found scripts that carry host or data migrations, and others a note still names as a step for other boxes. Scan script bodies for writes, not just their names for references.
- Searching by file name over-matches `index.html` and `design.md`. Check those by full path.

**Next steps (owner)**
- Review and merge the PR.
- Repoint or fold the nine kept scripts into the installer or a standing upgrade script. Do the same for `fix-index-template.sh` and `deploy-drop-nsenter.sh`, which still check out old branches.
- Installer gap: nothing at install time writes the `arkime_sessions3_template` marker.
