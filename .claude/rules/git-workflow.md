# Git Workflow

These rules govern all git/CI work in this repo. They apply globally — no `paths:` filter.

## Branch Strategy

This repo is **trunk-based**: everything merges into `main` via PR. There is no `develop`.

- **`main`** — the trunk. Never commit directly; always merge via PR. Protected by ruleset `26011127`.
- **Feature branches:** `feature/<short-description>` (e.g., `feature/iot-trust-score`)
- **Bug fixes:** `fix/<short-description>` (e.g., `fix/pcap-capture-timeout`)
- **Chores/infra:** `chore/<short-description>` (e.g., `chore/ci-pipeline`)
- **Docs:** `docs/<short-description>`
- **Syncs** (merging one long-lived line into another): `sync/<what>-YYYY-MM-DD`
- **Backups:** `backup/pre-<operation>-YYYY-MM-DD` (see Safety Backups)

In-flight `phase-N/*` and `infra/*` branches from the old model keep their names until they merge. New branches use the prefixes above.

### Why no develop (decided 2026-10-27)

The old model was `phase-N/* → develop → main`, with `main` untouched until v1.0.0. In practice `main` fell 303 commits behind, `develop` became the de-facto trunk, PRs stacked on top of each other, and two lines of history diverged (main carried a license switch and lint cleanup that develop never had). A staging buffer buys nothing here: **merging to `main` does not deploy anything.** The NetTap device is hand-deployed via `scripts/remote/` (see Deploys below), so the "deliberate, batched release" job of `develop` is already done by the human running the deploy script.

The consolidation happened in PR #127 (`sync/develop-into-main-2026-10-27`, true merge). `develop`'s final tip is preserved as tag `archive/develop-2026-10-27` (`e46fdb7`). Revisit only if a staging buffer is wanted later (e.g. an auto-update channel for other people's devices). Everything needed for that day is in the DORMANT section below — do not delete it.

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<optional body — explain WHY, not what>

Co-Authored-By: <model> <noreply@anthropic.com>
```

**Types:** `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `ci`, `perf`, `style`

**Scopes** match the component touched (taken from this repo's history): `web`, `daemon`, `docker`, `bridge`, `capture`, `install`, `scripts`, `deploy`, `storage`, `smart`, `traffic`, `alerts`, `devices`, `iot`, `pcap`, `tshark`, `logs`, `logstash`, `opensearch`, `malcolm`, `zeek`, `suricata`, `grafana`, `nginx`, `setup`, `dashboard`, `ui`, `ci`, `deps`, `debugging`, `plans`, `git`

Examples:
```
feat(bridge): add netplan persistence for br0
fix(daemon): handle OpenSearch connection timeout in prune cycle
test(storage): add pytest coverage for disk threshold logic
chore(docker): pin Malcolm images to v26.02.0
ci(github): add shellcheck workflow
```

One logical change per commit.

## Pull Requests

- PR title follows the same conventional commit format.
- PR description must include: **what changed, why, how to test**, and the Linear issue ID (e.g. "Closes NET-7").
- No human approval is required (solo repo; the ruleset sets `required_approving_review_count: 0`). The agent review gates below are the review. Zero required approvals is not licence to skip them.
- **Squash merge** `feature/` `fix/` `chore/` `docs/` branches into `main`.
- **True merge** (`gh pr merge --merge`) for any `sync/` branch — see CI Discipline. Squashing a sync destroys the ancestry link.
- Delete branches after merge (`gh pr merge --delete-branch`), then `git fetch --prune`.

## Merging Rules

- Rebase feature branches on `main` before opening a PR to keep history linear.
- Never force-push to `main`.
- Resolve merge conflicts locally, not in the GitHub UI.
- Run before pushing:
  ```bash
  cd daemon && python -m pytest
  cd web && npx vitest run
  cd web && npx svelte-check
  ```
  plus `shellcheck` on any changed `scripts/**/*.sh`.

## CI Discipline

These rules exist because PRs got merged through red CI unnoticed, PRs targeted the wrong base and showed inflated diffs, and stale branches piled up. All preventable:

- **Always `gh pr checks <n>` before `gh pr merge <n>`.** `mergeable: MERGEABLE` / `mergeStateStatus: CLEAN` only mean "no conflicts", not "CI is green". `pending` → wait. `fail` → stop. "No checks reported" → the workflow isn't firing; investigate the trigger.
- **Known red baseline (2026-10-27):** CI was already failing on `develop` before the migration — Lint Python (674 ruff errors, 99 files need formatting) and Lint Web (338 svelte-check errors). Because the test jobs depend on lint, they are skipped. Integration Tests (PRs to `main` only) have 24 pre-existing daemon test failures. Until a `fix/ci-baseline` PR makes CI green, a PR may merge only if it adds **no new failures** relative to that baseline, verified locally (daemon pytest failure set unchanged). Once CI is green, add the CI jobs as required status checks on the ruleset and delete this bullet.
- **Verify a PR's base branch before assessing its size.** A wrong base inflates the diff. Check with `gh pr view <n> --json baseRefName,changedFiles,additions,deletions`; fix with `gh pr edit <n> --base main`.
- **Workflow `pull_request` triggers must include `edited`** in `types:`. The default `[opened, synchronize, reopened]` does NOT fire when a PR's base changes. `.github/workflows/ci.yml` is the canonical shape: `types: [opened, synchronize, reopened, edited]`. Do not remove `edited`.
- **Run `git fetch --prune` after `gh pr merge --delete-branch`.** The flag deletes only the remote branch; stale remote-tracking refs stay until pruned.
- **Prune merged local branches periodically.** `git branch --merged origin/main` lists clean candidates. Squash-merged branches need `git branch -D` (squash rewrites history, so the tip is unreachable) — verify with `gh pr view <n>` that the PR is MERGED first.
- **Sync PRs MUST use `gh pr merge --merge` (NOT `--squash`).** A true merge commit keeps the source as a second parent, which is how git knows the histories are related. Squash discards it, and the next cross-branch merge re-resolves every conflict from scratch. Verify afterwards with `git merge-base --is-ancestor <source-sha> origin/main` — not by eyeballing the log.
- **Dependabot targets `main`** (`.github/dependabot.yml`). Its PRs follow the same squash + checks rules.

## Branch Protection (Ruleset `26011127`)

`main` is protected by an active GitHub ruleset, created 2026-10-27 (public repo — rulesets are free):

- Force-pushes blocked (`non_fast_forward`)
- Branch deletion blocked
- PR required before merge (zero approvals — solo repo — but the PR itself is mandatory)
- Admin bypass is `bypass_mode: pull_request` (RepositoryRole 5): you can merge your own PR past a failing gate in an emergency, but you cannot push straight to `main`.
- **No required status checks yet** — see the red-baseline bullet above. When CI is green, add the `CI` workflow's job names (`ShellCheck`, `Lint Python`, `Lint Web (svelte-check)`, `Test Daemon (Python)`, `Test Web (Vitest)`) as required checks with `strict_required_status_checks_policy: true`. Those context names must then stay exactly as they are; renaming a job wedges every merge.

Do NOT disable the ruleset without a replacement plan.

## Review Posture for High-Stakes PRs

For any PR that touches auth, credentials, the bridge/bypass path, the install script, OpenSearch security, or the daemon API, dispatch a **two-angle review** before merging. CI green is necessary but not sufficient:

- **security-engineer** agent — auth bypasses, CSRF, secret handling, command injection in shell/TShark/BPF paths, path traversal, SSRF from daemon lookups, privilege escalation via Docker socket or sudo.
- **Language reviewer for the diff** — `typescript-reviewer` agent for `web/`, `/python-review` for `daemon/`: type safety, async correctness, error handling, architectural boundaries, test coverage gaps, dead code.

The angles find disjoint classes of bugs; running only one ships the other's findings. Dispatch both in parallel (one message, two Agent calls). Give each: (a) the PR number + head SHA, (b) in-scope files, (c) out-of-scope files, (d) "the other agent covers X, stay on your angle".

## Plan Gate (`/codex-review`) and Over-Engineering Gate (`/ponytail-review`)

Mandatory for every new feature and every substantive code change (new behavior, multiple files, or non-trivial logic). **Exempt:** docs-only edits, comment/formatting changes, config or dependency bumps, trivial one-line fixes. Cost proportional to risk.

1. **`/codex-review` — plan gate, BEFORE any code (blocking).** Write the plan to `PLAN.md`; Codex reviews it read-only and returns `VERDICT:APPROVED` or `VERDICT:REVISE`; revise and re-submit to the same session until APPROVED or the round cap, then the human signs off. For a requirements interview first, use `/grill-me-codex`.
2. **`/ponytail-review` — over-engineering gate, AFTER code, before commit (blocking).** Hunts reinvented stdlib, unneeded dependencies, speculative abstractions, dead flexibility. Every finding is cut or explicitly justified before commit.

### Full gate order for a feature

1. Plan → `/codex-review` until `VERDICT:APPROVED` — before any code.
2. Implement.
3. Pre-commit: `/deep-review` (per triggers below) + `/ponytail-review` on the diff.
4. Pre-merge: two-angle review for high-stakes PRs.

## Pre-Commit Branch Scanning (`/deep-review`)

After implementation, before committing: stage the changes (`git add`) and run `/deep-review`. It writes `security-reviews/<branch-or-pr>/security-review.md` with HIGH/MEDIUM findings. Doc-only branches return "No findings".

**Mandatory triggers (no exceptions):**

- Any change under `web/src/lib/server/` (auth, cookies, sessions), `web/src/routes/api/`, `web/src/hooks.server.ts`, `daemon/api/`, `scripts/bridge/`, `scripts/install/`, `docker/`, or OpenSearch security config under `config/`.
- Any change touching credentials, role/permission checks, shelling out (TShark, BPF filters, `subprocess`), or external lookups (WHOIS, GeoIP, UniFi API).
- Any change ≥ 200 net lines of source code.

Recommended, not mandatory, for everything else. It does NOT replace the two-angle pre-merge review — run both. If it returns findings, fix in the working tree and re-run before committing. Do not commit "with findings tracked for follow-up".

## Safety Backups Before Risky Git Operations

Before merging `main` into a long-lived branch, rebasing across divergent history, resolving a conflict on untested code, force-pushing, or letting an agent make multiple automated commits to a sensitive branch, create a backup at the current tip:

```bash
git branch backup/pre-<operation>-$(date +%Y-%m-%d) <branch-you-are-about-to-modify>
```

Keep it until the operation is verified (merge landed, tests passing); delete at cleanup. Example: the 2026-10-27 migration used `backup/pre-trunk-migration-develop-2026-10-27` and `backup/pre-trunk-migration-main-2026-10-27`.

## Cascade-Rebasing a Stacked-PR Series

The `phase-4/*` PRs (#107 → #108 → #109 → #110) are a stack. Cascade-rebasing a stack can silently drop a child PR if any downstream local branch has drifted from origin: the rebase replays an empty range, the force-push lands an empty PR, and GitHub marks it merged with no content.

Before the first force-push of a cascade: for every branch in the stack, confirm `git rev-parse <branch>` equals `git rev-parse origin/<branch>`, AND create a `backup/pre-cascade-rebase-YYYY-MM-DD` branch for each. `--force-with-lease` only catches divergence from origin, not local drift from an earlier reset. Prefer merging the stack bottom-up over rebasing it.

## Deploys to the NetTap Device

- Merging to `main` deploys nothing. The device (`/home/nettap/NetTap`) is updated by hand with `scripts/remote/deploy-*.sh` (see CLAUDE.md "Remote Device Workflow").
- `main` is what the device runs when stable. To test a branch on the device, set `BRANCH="<branch>"` in the deploy script; after the PR merges, the next deploy goes back to `BRANCH="main"`.

## Versioning

Phase-based SemVer, **tagged on `main`**. Phases 1–3 finished under the old model but were never tagged; tag them retroactively on `main` only if a release needs them.

| Milestone | Version |
|-----------|---------|
| Phase 4 complete (Dashboard Polish) | `v0.4.0` |
| Phase 5 complete (Community Release) | `v1.0.0` |

Patch versions for fixes within a phase: `v0.4.1`, … Pre-releases: `v1.0.0-alpha.1`, `-beta.1`, `-rc.1`. Pushing a `v*.*.*` tag triggers `.github/workflows/release.yml`. Tag only when every task for the phase is merged to `main`.

---

## DORMANT — the retired develop model

> **This section does not apply today.** It is preserved (per the Code Preservation Policy) in case a staging branch is ever reintroduced. Read it the day you create that branch, not before.

### Retired Git Strategy (from CLAUDE.md before 2026-10-27; full text: `git show archive/develop-2026-10-27:CLAUDE.md`)

- **`main`** — Protected. NEVER push directly. Only receives merges at project completion (v1.0.0).
- **`develop`** — Integration branch. All feature branches merge here via PR.
- **Feature branches** — All work happens here. Branch from `develop`, merge back to `develop`.

Branch naming: `phase-N/short-description` (e.g. `phase-1/bridge-hardening`, `phase-3/setup-wizard`, `phase-5/ci-pipeline`). Cross-cutting: `infra/description` or `chore/description`.

```
1. git checkout develop
2. git pull origin develop
3. git checkout -b phase-N/description
4. ... work, commit ...
5. git push -u origin phase-N/description
6. Create PR: phase-N/description → develop
7. After merge, delete feature branch
```

Phase tags (`v0.1.0` … `v0.4.0`) were applied on `develop`; only `v1.0.0` was to go on `main` after the final develop → main merge.

### If develop ever returns: the release deadlock (criss-cross merge history)

Learned in another repo, where it cost ~85 minutes:

- Every `develop → main` release merge leaves a merge commit on `main` that `develop` lacks. If it is never synced back, the next release PR opens `mergeStateStatus: BEHIND` and the "up-to-date with base" rule blocks it. That rule is an ancestry check, not a content check — it fires even when `git diff origin/main origin/develop` is empty.
- `gh pr update-branch <release-pr>` fails on this topology with a generic `GraphQL: Something went wrong`. It is NOT a GitHub incident; do not wait it out. A sync PR with `head=main` also deadlocks.
- **Workaround:** cut a sync branch OFF `develop` with `main` merged INTO it, PR it into `develop`, true-merge it, then true-merge the release PR:
  ```bash
  git checkout -b sync/main-into-develop-YYYY-MM-DD origin/develop
  git merge origin/main
  git push -u origin sync/main-into-develop-YYYY-MM-DD
  gh pr create --base develop
  gh pr merge <n> --merge
  ```
  Verify with `git rev-list --count origin/develop..origin/main` == 0, not with `mergeStateStatus` (it reports spurious CLEAN).
- Hotfixes in that world: `hotfix/<desc>` cut from `main`, merged back into both `main` and `develop`, with the back-merge done as a true merge.
