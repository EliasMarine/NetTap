# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NetTap is an open-source, hardware-agnostic network visibility appliance that sits transparently inline between an ISP modem and a home/small business router. It provides enterprise-grade network telemetry via a polished web dashboard without requiring deep networking knowledge.

The project wraps CISA's Malcolm stack (Zeek, Suricata, Arkime, OpenSearch) with simplified deployment, a consumer-friendly setup wizard, and intelligent storage management.

**PRD:** `NetTap_PRD_v1.0.md` contains the full product specification.

## Git Strategy

### Branch Model

- **`main`** — Protected. NEVER push directly. Only receives merges at project completion (v1.0.0).
- **`develop`** — Integration branch. All feature branches merge here via PR.
- **Feature branches** — All work happens here. Branch from `develop`, merge back to `develop`.

**Branch naming convention:** `phase-N/short-description`
```
phase-1/bridge-hardening
phase-1/malcolm-integration
phase-2/ilm-policies
phase-2/smart-alerting
phase-3/sveltekit-init
phase-3/setup-wizard
phase-4/dashboard-home
phase-5/ci-pipeline
```

For cross-cutting work that spans phases: `infra/description` or `chore/description`.

### Workflow

```
1. git checkout develop
2. git pull origin develop
3. git checkout -b phase-N/description
4. ... work, commit ...
5. git push -u origin phase-N/description
6. Create PR: phase-N/description → develop
7. After merge, delete feature branch
```

**NEVER push to `main`.** All PRs target `develop`. At project completion, `develop` merges to `main` with the `v1.0.0` tag.

### Commit Convention: Conventional Commits

Every commit message MUST follow this format:

```
type(scope): short description

Optional body explaining the "why" (not the "what").

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

**Types (required):**
| Type | When to use |
|------|-------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code restructuring, no behavior change |
| `test` | Adding or updating tests |
| `chore` | Maintenance, dependencies, config |
| `ci` | CI/CD pipeline changes |
| `perf` | Performance improvement |
| `style` | Formatting, whitespace, no logic change |

**Scope (optional but encouraged):** The component affected.
```
feat(bridge): add netplan persistence for br0
fix(daemon): handle OpenSearch connection timeout in prune cycle
test(storage): add pytest coverage for disk threshold logic
docs(readme): update architecture diagram
chore(docker): pin Malcolm images to v26.02.0
ci(github): add shellcheck workflow
```

### Versioning: Phase-Based SemVer

Development versions increment with each phase milestone. Tags are applied on `develop` at phase completion.

| Milestone | Version | Tag on |
|-----------|---------|--------|
| Phase 1 complete (Core Infrastructure) | `v0.1.0` | `develop` |
| Phase 2 complete (Storage Management) | `v0.2.0` | `develop` |
| Phase 3 complete (Onboarding UX) | `v0.3.0` | `develop` |
| Phase 4 complete (Dashboard Polish) | `v0.4.0` | `develop` |
| Phase 5 complete (Community Release) | `v1.0.0` | `main` (after final merge) |

**Patch versions** for hotfixes within a phase: `v0.1.1`, `v0.1.2`, etc.
**Pre-release versions** for testing: `v1.0.0-alpha.1`, `v1.0.0-beta.1`, `v1.0.0-rc.1`.

### Rules for Claude Code

1. **Always create a new branch** before making code changes. Never commit directly to `develop` or `main`.
2. **Always use conventional commit format.** No exceptions.
3. **Push to the feature branch only.** Never push to `develop` or `main`.
4. **One logical change per commit.** Don't bundle unrelated changes.
5. **Create PRs targeting `develop`** — never targeting `main`.
6. **Include the Linear issue ID** in the PR description (e.g., "Closes NET-7").
7. **Tag phase milestones** only when all tasks for that phase are complete and merged to `develop`.

---

## Code Preservation Policy

- **Never delete** replaced logic; wrap with `// OLD CODE START/END` and comment why.
- Don't remove commented blocks unless explicitly approved and stable for 3+ cycles.
- **Never checkout/pull `main`** without instruction.

## Tracking (Mandatory — DO NOT SKIP)

### Linear (primary tracker)

**CRITICAL: If you changed ANY code, you MUST create a Linear issue before responding that the task is done.** This is non-negotiable. No code change is complete without a corresponding Linear issue. Forgetting this is a failure condition.

- **Team:** NetTap
- **Labels:** `Bug`, `Feature`, `Improvement`, or `Info`
- **Priority:** 1=Urgent, 2=High, 3=Normal, 4=Low
- **Title format:** `type: short description` (e.g., `fix: NotificationProvider import causes build failure`)
- **Description must include:** Problem, Root Cause, Fix/Solution, Files Changed, Branch/PR link, Lessons Learned
- **Set state:** `Done` if already fixed, `In Progress` if actively working, `Todo` if planned
- **Link PRs** using the `links` parameter: `[{"url": "https://github.com/EliasMarine/NetTap/pull/N", "title": "PR #N: Description"}]`

**Workflow**: Implement → **Create/update Linear issue** → Update tracking doc → Verify.

### Debugging Log (source of truth for deployment issues)

**CRITICAL: Before starting ANY deployment fix, read `Debugging/DEPLOYMENT-ISSUES.md` first.** This document tracks every deployment bug, its causal chain, what was tried, what worked, and what didn't. After completing a fix, update this document with the new issue, root cause, fix, files changed, and lessons learned. This prevents re-introducing previously fixed bugs or repeating failed approaches.

- **Location:** `Debugging/DEPLOYMENT-ISSUES.md`
- **Before each fix:** Check the "Key Files Modified" table and "Lessons Learned" section
- **After each fix:** Add a new entry, update "Current Stack Health", and add to "Known Risks" if applicable

### Tracking Docs (secondary)

Also update relevant `/tracking-fixes/*.md` **immediately after each fix/feature**:
- What changed, root cause, steps/solution, files touched, status, test results, lessons, next steps.
- Key trackers:
  - Create new per feature/bugfix/chore as needed

---

## Project Structure

```
Debugging/         Deployment issue tracking (source of truth)
  DEPLOYMENT-ISSUES.md   All deployment bugs, causal chains, fixes, lessons
scripts/           Shell scripts for system setup
  bridge/          Linux bridge configuration (setup-bridge.sh)
  install/         Installation automation (install.sh)
  common.sh        Shared shell utilities (logging, root check, env loading)
daemon/            Python storage & health daemon
  storage/         Rolling retention manager (OpenSearch ILM + disk monitoring)
  smart/           SSD SMART health monitoring
  main.py          Daemon entry point (periodic storage + health checks)
web/               Web UI (framework TBD)
  wizard/          First-run setup wizard
  dashboard/       Main traffic dashboard
config/            Configuration files mounted into containers
  malcolm/         Malcolm stack overrides
  opensearch/      ILM policies (ilm-policy.json)
  suricata/        Suricata config overrides (nettap.yaml)
  zeek/            Zeek script overrides (nettap.zeek)
  grafana/         Grafana dashboard JSON + provisioning
docker/            Docker Compose and Dockerfiles
  docker-compose.yml   NetTap services (extends Malcolm)
  Dockerfile.daemon    Python daemon container
  Dockerfile.web       Web UI container
```

## Commands

```bash
# Install (on target Ubuntu host, as root)
sudo scripts/install/install.sh

# Bridge setup only
sudo scripts/bridge/setup-bridge.sh --wan eth0 --lan eth1

# Start NetTap services
docker compose -f docker/docker-compose.yml up -d

# Run daemon locally (development)
cd daemon && python3 main.py
```

## Technology Stack

- **Host OS:** Ubuntu Server 22.04 LTS
- **Orchestration:** Docker + Docker Compose
- **Network Analysis:** Zeek 6.x (metadata), Suricata 7.x (IDS), Arkime 5.x (PCAP)
- **Data Store:** OpenSearch 2.x + OpenSearch Dashboards
- **Visualization:** Grafana 10.x (optional enhanced dashboards)
- **Storage Daemon:** Python (custom rolling retention + SMART monitoring)
- **Log Forwarding:** Logstash (optional SIEM export)

## Architecture

### Network Layer
- Linux software bridge (`br0`) binding two physical NICs — transparent Layer 2 forwarding
- WAN NIC (`eth0`) connects to ISP modem, LAN NIC (`eth1`) connects to router
- Separate management interface (3rd NIC, Wi-Fi, or VLAN) for dashboard access
- Passive capture in promiscuous mode — appliance is invisible on the data path

### Data Pipeline
1. Raw packets captured on bridge interface
2. Zeek generates structured metadata logs (conn, DNS, HTTP, TLS, files, DHCP, SMTP)
3. Suricata performs signature/anomaly-based IDS with Emerging Threats ruleset
4. Logs enriched with GeoIP, ASN, hostname resolution
5. OpenSearch indexes all logs and alerts
6. Dashboards (OpenSearch Dashboards + Grafana) visualize the data

### Storage (Three-Tier)
| Tier | Data | Retention | Compression | Daily Size |
|------|------|-----------|-------------|------------|
| Hot | Zeek metadata logs | 90 days | zstd ~8:1 | 300-800 MB |
| Warm | Suricata alerts | 180 days | zstd ~6:1 | 10-50 MB |
| Cold | Raw PCAP (alert-triggered only) | 30 days | zstd ~3:1 | Variable |

OpenSearch ILM handles hot-tier rotation. A custom Python daemon monitors disk utilization with an 80% threshold safeguard.

## Development Phases

1. **Core Infrastructure** — Linux bridge scripts, Malcolm deployment automation, hardware validation
2. **Storage Management** — ILM config, retention daemon, SMART monitoring, compression
3. **Onboarding UX** — Setup wizard, NIC auto-detection, admin UI
4. **Dashboard Polish** — Custom Grafana dashboards, GeoIP maps, bandwidth trending, notifications
5. **Community Release** — Docs, install script, community setup

## Build Plan Task Tracking

**CRITICAL: After completing any task from `plans/comprehensive-build-plan.md`, you MUST update the task's status in that file.** Mark completed tasks with a `[x]` checkbox prefix and add a completion note. This applies to all phases going forward. When starting a new phase, review the plan to see what's already done.

## SIEM Feature Integration Policy

**Reference:** `plans/siem-features-gameplan.md` contains the full implementation plan for 20 SIEM-inspired features (10 Must-Have + 10 Should-Have).

### Implementation Rules

1. **Every feature must be FULLY integrated** — backend API + frontend UI + tests. No half-built features.
2. **Every feature must have complete test coverage:**
   - Daemon: pytest unit tests (mock OpenSearch, test query building, test error handling)
   - Web API clients: Vitest tests (mock fetch, test params, test responses)
   - Web components: Vitest + Testing Library (render with mock data, test interactions, test empty/loading/error states)
3. **ALL tests must pass** (existing + new) before any PR is created. Run `cd daemon && python -m pytest` and `cd web && npx vitest run` and `cd web && npx svelte-check`.
4. **Follow the dependency order:** Group A (data) → Group B (UI) → Group C (intelligence) → Group D (viz) → Group E (advanced). Do not build UI features before their data layer exists.
5. **Use existing patterns:** New API endpoints follow the same pattern as `daemon/api/traffic.py`. New pages follow the same layout as `web/src/routes/+page.svelte`. New components use the design system from `web/src/lib/styles/global.css`.

### Three Design Pillars

All SIEM features must embody these principles:
- **Device-Centric:** Organize data by "what are my devices doing?" — not by log type
- **Plain English:** Every alert, metric, and detection gets a human-readable explanation
- **Immediate Value:** Big numbers first, details on click. Progressive disclosure (overview → category → raw logs)

## Hooks

This project has two Claude Code hooks configured in `.claude/settings.json`:

### PreToolUse: File Protection (`.claude/hooks/protect-files.sh`)
A command hook on `Edit|Write` that blocks edits to protected files. Exit code 2 blocks the tool call; stderr is shown to Claude as feedback. Protected files:
- `.env` / `.env.*` — environment secrets, must be edited manually
- `package-lock.json` — auto-generated by `npm install`
- `yarn.lock` — auto-generated by `yarn install`
- `.git/*` — must use git commands

The script reads `tool_input.file_path` from stdin JSON using `python3` (not `jq`, which may not be available).

### Stop: Test Coverage Gatekeeper
An agent hook that fires when Claude tries to stop. It reads the session transcript to find all `.ts` files modified via Edit/Write, then uses Glob to verify each has a matching `.test.ts` or `.spec.ts` file. If tests are missing, it returns `{"ok": false, "reason": "..."}` to block the stop and instruct Claude to create them. Checks `stop_hook_active` to avoid infinite loops.

## Key Design Constraints

- Target hardware: Intel N100 mini PCs, 16GB RAM, 1TB NVMe, dual Intel i226-V 2.5GbE NICs (~$200 BOM)
- Must add <1ms latency to traffic path
- Zero packet loss at 500Mbps sustained, support up to 1Gbps line rate
- Dashboard loads <3s on LAN; alerts surface <10s from detection
- Pre-configure OpenSearch JVM heap caps to prevent OOM on 16GB systems
- Pin Malcolm to tested release tags to avoid upstream breaking changes
- SSD write endurance: implement write coalescing, 30s log flush intervals, SMART monitoring
- No cloud dependency, no telemetry, no subscription — fully self-contained
- v1.0 is read-only visibility (no blocking/firewall), no TLS payload decryption

## Licensing

All core components use permissive open-source licenses (Apache 2.0, BSD, GPLv2). Grafana is AGPLv3. The project itself should use a compatible open-source license.
