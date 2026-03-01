# NetTap Deployment Issues — Source of Truth

> **Last updated:** 2026-03-01
> **Status:** All 10 issues resolved. Awaiting host verification of PR #65 (malcolm-zeek pipeline).

This document tracks every deployment bug encountered while bringing up the NetTap/Malcolm stack. It is the **single source of truth** — consult it before starting any new fix and update it after every change.

---

## Table of Contents

- [Current Stack Health](#current-stack-health)
- [Issue Chain Overview](#issue-chain-overview)
- [Chain 1: OpenSearch Auth & Bootstrap](#chain-1-opensearch-auth--bootstrap)
- [Chain 2: Privilege Drop & Service Startup](#chain-2-privilege-drop--service-startup)
- [Chain 3: Logstash JVM / Pipeline Compilation](#chain-3-logstash-jvm--pipeline-compilation)
- [Key Files Modified](#key-files-modified)
- [Lessons Learned (Global)](#lessons-learned-global)
- [Known Risks & Watch Items](#known-risks--watch-items)

---

## Current Stack Health

| Service Category | Status | Notes |
|---|---|---|
| OpenSearch | OK | Auth, roles_mapping, bootstrap all working |
| OpenSearch Dashboards | OK | Depends on OpenSearch healthy |
| Logstash (6/7 pipelines) | OK | input, output, filescan, suricata, beats, enrichment |
| Logstash (malcolm-zeek) | PENDING VERIFY | PR #65 deployed `-Xss8m` via jvm.options.d — awaiting host test |
| Zeek, Suricata, Arkime | OK | Capture services running after no-new-privileges removal |
| Redis, API, Filebeat | OK | Depend on logstash/opensearch chain |
| nginx-proxy, CyberChef | OK | Needed CHOWN/SETUID caps after security restructuring |
| NetTap custom services | OK | daemon, web, nginx keep strict security |

---

## Issue Chain Overview

The deployment bugs fall into **3 causal chains**. Each chain had a root cause that triggered cascading failures, and some fixes introduced new bugs that required follow-up fixes.

```
CHAIN 1: OpenSearch Auth & Bootstrap (NET-48 → NET-49)
  PR #54 → PR #55

CHAIN 2: Privilege Drop & Service Startup (NET-48 → NET-50 → NET-51 → NET-52 → NET-53 → NET-54 → NET-55)
  PR #54 → PR #56 → PR #57 → PR #58 → PR #59 → PR #60 → PR #61 → PR #62 → PR #63

CHAIN 3: Logstash JVM / Pipeline Compilation (NET-56 → NET-57)
  PR #64 → PR #65
```

---

## Chain 1: OpenSearch Auth & Bootstrap

### NET-48 (Part 1) — OpenSearch 403 Forbidden
| Field | Value |
|---|---|
| **Linear** | [NET-48](https://linear.app/nettap/issue/NET-48) |
| **PR** | [#54](https://github.com/EliasMarine/NetTap/pull/54) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-02-28 |

**Symptom:** OpenSearch healthcheck passes (200) but all API calls return 403 Forbidden. All 17 dependent services stuck in "Starting".

**Root Cause:** Malcolm's `setup-internal-users.sh` creates user `malcolm_internal` with `backend_roles: [admin]` in `internal_users.yml`, but `roles_mapping.yml` is left completely empty. No mapping from `admin` backend role to `all_access` OpenSearch role. Authentication succeeds but authorization fails.

**Fix:** Added `bootstrap_opensearch_security()` to `deploy-malcolm.sh` — writes correct `roles_mapping.yml` (admin -> all_access) and runs `securityadmin.sh` after OpenSearch is healthy.

**Files Changed:**
- `scripts/install/deploy-malcolm.sh` — new `bootstrap_opensearch_security()` function
- `tests/scripts/test_deploy_malcolm.bats` — 5 new tests

**Key Insight:** Malcolm's security plugin has a two-layer system: `internal_users.yml` for authentication, `roles_mapping.yml` for authorization. The `.opendistro_security` index is the source of truth — YAML changes must be pushed via `securityadmin.sh`.

---

### NET-49 — OpenSearch Bootstrap Deadlock on Fresh Deployments
| Field | Value |
|---|---|
| **Linear** | [NET-49](https://linear.app/nettap/issue/NET-49) |
| **PR** | [#55](https://github.com/EliasMarine/NetTap/pull/55) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-02-28 |

**Symptom:** On fresh deployments (clean volume), `.opendistro_security` index doesn't exist. Healthcheck always returns 401. Docker marks OpenSearch unhealthy. All 17 dependent services refuse to start.

**Root Cause:** `bootstrap_opensearch_security()` (from NET-48 fix) was placed **after** `docker compose up -d`. But `up -d` blocks ~244s waiting for healthcheck → deadlock: security can't bootstrap until `up -d` returns, but `up -d` won't return until security is bootstrapped.

**Fix:** Restructured `start_services()`:
1. Start OpenSearch alone: `docker compose up -d opensearch`
2. Wait for HTTP API (even 401 = REST API is up)
3. Run `bootstrap_opensearch_security()`
4. Start full stack: `docker compose up -d`

**Files Changed:**
- `scripts/install/deploy-malcolm.sh` — reordered startup, added `_wait_for_opensearch_http()`
- `tests/scripts/test_deploy_malcolm.bats` — 3 new tests

**Key Insight:** Docker Compose `service_healthy` conditions create blocking dependency chains. Bootstrap must happen between "HTTP API responding" and "healthcheck passing".

---

## Chain 2: Privilege Drop & Service Startup

This was the most complex chain — 7 issues across 8 PRs, with several fixes that introduced new problems.

### NET-48 (Part 2) / NET-50 — Logstash EACCES on /dev/fd/1
| Field | Value |
|---|---|
| **Linear** | [NET-50](https://linear.app/nettap/issue/NET-50) (supersedes NET-48 Part 2) |
| **PR** | [#54](https://github.com/EliasMarine/NetTap/pull/54) (initial), [#56](https://github.com/EliasMarine/NetTap/pull/56) (refined) |
| **Status** | Done (but this fix was later revised multiple times) |
| **Severity** | Urgent |
| **Date** | 2026-02-28 |

**Symptom:** `FATAL unknown error making dispatchers for 'logstash': EACCES`. Supervisord cannot open `stdout_logfile=/dev/fd/1`.

**Root Cause (Initial theory — NET-48):** Blamed `no-new-privileges:true` restricting `/proc/self/fd` access after privilege drop. Removed no-new-privileges from logstash.

**Root Cause (Corrected — NET-50):** The actual cause is Malcolm's `su -s /bin/bash -p logstash << EOF` heredoc privilege drop. After `su` changes UID, `/proc/self/fd/1` retains `l-wx------ root root` permissions. A new `open()` on `/dev/fd/1` fails with EACCES. This is a **kernel procfs security restriction**, not a Docker security option.

**Fix (NET-50):** Set `PUSER_PRIV_DROP=false` for logstash — skips the `su` call, supervisord runs as root, can open `/dev/fd/1`.

**Files Changed:**
- `docker/docker-compose.yml` — `PUSER_PRIV_DROP: "false"` for logstash
- `tests/scripts/test_compose_validation.bats`

**Key Insight:** `docker exec -u 1000` is NOT equivalent to testing inside `su` heredoc — different fd contexts. The `su` binary changes UID but inherited fd permissions are enforced by the kernel on reopen.

> **IMPORTANT:** This fix (PUSER_PRIV_DROP=false) caused a cascade of follow-up issues (NET-51 through NET-55). See below.

---

### NET-51 — Global PUSER_PRIV_DROP=false Breaks 8+ Services
| Field | Value |
|---|---|
| **Linear** | [NET-51](https://linear.app/nettap/issue/NET-51) |
| **PR** | [#57](https://github.com/EliasMarine/NetTap/pull/57) (global), [#58](https://github.com/EliasMarine/NetTap/pull/58) (OpenSearch override), [#59](https://github.com/EliasMarine/NetTap/pull/59) (per-service) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-02-28 |

**Symptom:** 8+ services crash-looping: Dashboards ("should not be run as root"), Redis, Zeek, Suricata, Arkime, pcap-capture, API, nginx-proxy.

**Root Cause:** PR #57 put `PUSER_PRIV_DROP=false` in the global `x-process-env` YAML anchor to fix logstash. PR #58 added `PUSER_PRIV_DROP=true` override for OpenSearch. But 8+ other services also refuse root. The "global false + per-service true override" approach was backwards.

**Fix (PR #59):** Removed from global anchor. Added `PUSER_PRIV_DROP=false` only to the 2 services that need it (logstash, dashboards-helper).

**Files Changed:**
- `docker/docker-compose.yml` — moved PUSER_PRIV_DROP from global to per-service
- `tests/scripts/test_compose_validation.bats`

**Key Insight:** When fixing a privilege issue, apply the fix **only where needed** — don't apply globally then add exceptions. The exception list is always larger than the affected list.

---

### NET-52 — no-new-privileges Breaks Malcolm Services + Template Deadlock
| Field | Value |
|---|---|
| **Linear** | [NET-52](https://linear.app/nettap/issue/NET-52) |
| **PR** | [#60](https://github.com/EliasMarine/NetTap/pull/60) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-02-28 |

**Symptom:** 10+ Malcolm services crash-looping or exiting silently:
- Redis, API: Exit code 0, no server process started
- Zeek, Suricata, pcap-capture, Arkime: `su: cannot set groups: Operation not permitted`
- CyberChef: `chown failed: Operation not permitted`
- Logstash: Stuck waiting for `malcolm_template` on fresh deploys

**Root Cause (3 separate issues):**

1. **`no-new-privileges` blocks `su` setuid**: Malcolm's entrypoint uses `su` (setuid binary). Docker's `no-new-privileges` blocks setuid transitions. `su` silently fails, process never starts, exit 0.

2. **`cap_drop: ALL` removes SETGID + CHOWN**: Capture services had `cap_drop: ALL`. `su` needs `setgroups()` (SETGID), nginx needs `chown()` (CHOWN).

3. **Template bootstrap deadlock**: `idxinit` waits for logs in OpenSearch -> needs logstash -> logstash needs `malcolm_template` -> needs `index-refresh.py` (part of idxinit) -> circular.

**Fix:**
- Removed `no-new-privileges` from ALL 12 Malcolm services (their entrypoint requires setuid)
- Removed `cap_drop: ALL` from 4 capture services
- Added `cap_add: [CHOWN, SETUID, SETGID]` to CyberChef and nginx
- NetTap custom services (daemon, web, nginx) KEEP strict security
- Added `bootstrap_index_templates()` to `deploy-malcolm.sh` — pushes 42 ECS + 10 custom templates + `malcolm_template` directly via API

**Files Changed:**
- `docker/docker-compose.yml` — security restructuring
- `scripts/install/deploy-malcolm.sh` — `bootstrap_index_templates()`
- `tests/scripts/test_compose_validation.bats` — 119 tests pass
- `tests/scripts/test_deploy_malcolm.bats`

**Key Insight:** Malcolm's entrypoint is **fundamentally incompatible** with `no-new-privileges`. `su` failing silently (exit 0) is extremely hard to debug. Separate Malcolm services (use Docker defaults) from NetTap services (strict security).

---

### NET-53 — PUSER_PRIV_DROP=false Now Harmful After no-new-privileges Removed
| Field | Value |
|---|---|
| **Linear** | [NET-53](https://linear.app/nettap/issue/NET-53) |
| **PR** | [#61](https://github.com/EliasMarine/NetTap/pull/61) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-01 |

**Symptom:** Logstash crash-loops: `RuntimeError: Logstash cannot be run as superuser.`

**Root Cause:** NET-50 misdiagnosed the EACCES as caused by `su` heredoc. The actual cause was `no-new-privileges` blocking `su`. Now that NET-52 removed `no-new-privileges`, Malcolm's normal `su` privilege drop works. But `PUSER_PRIV_DROP=false` was still set, bypassing `su`, leaving logstash running as root.

**Fix:** Removed `PUSER_PRIV_DROP=false` from logstash and dashboards-helper. Let default (true) take effect.

**Files Changed:**
- `docker/docker-compose.yml`
- `tests/scripts/test_compose_validation.bats`

**Key Insight:** Always re-evaluate workarounds when the underlying issue they address is fixed. NET-53's diagnosis retroactively corrected NET-50's root cause analysis.

> **BUT:** This reintroduced the EACCES. See NET-54.

---

### NET-54 — EACCES Returns: The Dual Problem
| Field | Value |
|---|---|
| **Linear** | [NET-54](https://linear.app/nettap/issue/NET-54) |
| **PR** | [#62](https://github.com/EliasMarine/NetTap/pull/62) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-01 |

**Symptom:** EACCES on `/dev/fd/1` returned after NET-53 re-enabled the default privilege drop.

**Root Cause:** The EACCES is inherent to the `su` mechanism (kernel procfs restriction), **independent of** `no-new-privileges`. There are actually TWO problems that must be solved simultaneously:

| Setting | EACCES | Superuser refusal |
|---|---|---|
| Default (PUSER_PRIV_DROP=true) | FAILS | OK |
| PUSER_PRIV_DROP=false | OK | FAILS |
| **PUSER_PRIV_DROP=false + user=logstash** | **OK** | **OK** |

**Fix (the final correct solution):**
1. `PUSER_PRIV_DROP=false` — supervisord runs as root, CAN open `/dev/fd/1`
2. Custom `config/logstash/supervisord.conf` with `user=logstash` — supervisord drops to logstash user when spawning the process
3. Result: supervisord opens /dev/fd/1 as root (works), logstash runs as uid 1000 (not root)

**Files Changed:**
- `config/logstash/supervisord.conf` — NEW: custom supervisord config with `user=logstash`
- `docker/docker-compose.yml` — PUSER_PRIV_DROP=false + supervisord.conf volume mount
- `tests/scripts/test_compose_validation.bats`

**Key Insight:** This was the correct diagnosis all along (NET-50 was right about the mechanism, wrong about the solution). The fix requires addressing BOTH the fd access problem AND the root-refusal problem at different layers: entrypoint (root for fd) and supervisord (user= for process).

---

### NET-55 — Data Queue Not Writable After PUSER_PRIV_DROP=false
| Field | Value |
|---|---|
| **Linear** | [NET-55](https://linear.app/nettap/issue/NET-55) |
| **PR** | [#63](https://github.com/EliasMarine/NetTap/pull/63) |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-01 |

**Symptom:** `Path "/usr/share/logstash/data/queue" must be a writable directory. It is not writable.`

**Root Cause:** NET-54 set `PUSER_PRIV_DROP=false` so supervisord runs as root. But this also skips the entrypoint's `chown` of data directories. The persistent queue volume stays owned by root, while logstash runs as uid 1000 via `user=logstash`.

**Fix:** Added `[program:fix-perms]` to `config/logstash/supervisord.conf`:
- Runs as root (no `user=` directive)
- `chown -R logstash:logstash /usr/share/logstash/data`
- Priority 1 (before logstash at priority 999)

**Files Changed:**
- `config/logstash/supervisord.conf` — added fix-perms program

**Key Insight:** When bypassing an entrypoint's privilege drop mechanism, you must also handle ALL side effects that the mechanism provided (uid/gid setup, chown, env setup, etc.).

---

## Chain 3: Logstash JVM / Pipeline Compilation

### NET-56 — malcolm-zeek StackOverflowError (Wrong Delivery Method)
| Field | Value |
|---|---|
| **Linear** | [NET-56](https://linear.app/nettap/issue/NET-56) |
| **PR** | [#64](https://github.com/EliasMarine/NetTap/pull/64) |
| **Status** | Done (superseded by NET-57) |
| **Severity** | High |
| **Date** | 2026-03-01 |

**Symptom:** 6/7 logstash pipelines start. `malcolm-zeek` fails: `Stack overflow error while compiling Pipeline. Please increase thread stack size using -Xss`

**Root Cause:** Malcolm's zeek pipeline has ~75 config files with deeply nested conditionals. The JVM's default thread stack (1MB) overflows during recursive `compileDependencies` -> `flatten` -> `filterDataset`/`split`.

**Fix (WRONG METHOD):** Added `-Xss4m` to `LS_JAVA_OPTS` environment variable.

**Why It Failed:** Logstash 9.x's launcher script **silently filters** `-Xss` from `LS_JAVA_OPTS`. Only heap flags (`-Xms`, `-Xmx`) and `-D` properties pass through. The JVM bootstrap flags log confirmed: `-Xms2g -Xmx2g` appeared but no `-Xss`.

**Key Insight:** Always verify JVM flags in the bootstrap flags log line after changing options. `LS_JAVA_OPTS` is NOT a transparent pass-through in Logstash 9.x.

---

### NET-57 — malcolm-zeek Fix via jvm.options.d Drop-in (Correct Method)
| Field | Value |
|---|---|
| **Linear** | [NET-57](https://linear.app/nettap/issue/NET-57) |
| **PR** | [#65](https://github.com/EliasMarine/NetTap/pull/65) |
| **Status** | Done — AWAITING HOST VERIFICATION |
| **Severity** | High |
| **Date** | 2026-03-01 |

**Symptom:** Same as NET-56 — PR #64's `-Xss4m` had no effect.

**Root Cause:** Logstash 9.x filters `-Xss` from `LS_JAVA_OPTS`.

**Fix (CORRECT METHOD):**
1. Created `config/logstash/jvm.options.d/99-nettap.options` with `-Xss8m`
2. Volume-mounted at `/usr/share/logstash/config/jvm.options.d/99-nettap.options:ro`
3. Reverted dead `-Xss4m` from `LS_JAVA_OPTS`
4. Bumped to 8m (from 4m) for headroom

**Files Changed:**
- `config/logstash/jvm.options.d/99-nettap.options` (NEW)
- `docker/docker-compose.yml`

**Verification Steps (on nettap host):**
```bash
cd ~/NetTap && git pull origin develop
docker compose -f docker/docker-compose.yml up -d --force-recreate logstash
docker logs -f nettap-logstash 2>&1 | head -100
```
Look for:
1. `-Xss8m` in the JVM bootstrap flags line
2. All 7 pipelines reported as running (including `malcolm-zeek`)

**Key Insight:** For non-heap JVM tuning in Logstash 8+/9.x, **always use `jvm.options.d/` drop-in files**. `LS_JAVA_OPTS` only reliably passes `-Xms`, `-Xmx`, and `-D` flags.

---

## Key Files Modified

These files were touched repeatedly across the 10 PRs. Check their current state before making changes.

| File | PRs | Current State |
|---|---|---|
| `docker/docker-compose.yml` | #54-#65 (all 10) | Logstash: PUSER_PRIV_DROP=false, supervisord.conf mount, jvm.options.d mount, LS_JAVA_OPTS=-Xmx2g -Xms2g |
| `config/logstash/supervisord.conf` | #62, #63 | Custom: fix-perms (priority 1) + logstash with user=logstash (priority 999) |
| `config/logstash/jvm.options.d/99-nettap.options` | #65 | `-Xss8m` |
| `scripts/install/deploy-malcolm.sh` | #54, #55, #60 | bootstrap_opensearch_security() + bootstrap_index_templates() + staged startup |
| `tests/scripts/test_compose_validation.bats` | #54, #56-#62 | 119+ tests, validates security per Malcolm vs NetTap services |
| `tests/scripts/test_deploy_malcolm.bats` | #54, #55, #60 | Template bootstrap + security bootstrap + startup ordering tests |

---

## Lessons Learned (Global)

### Malcolm Architecture Constraints
1. **Malcolm's entrypoint is incompatible with `no-new-privileges`** — it uses `su` (setuid), which Docker's `no-new-privileges` blocks. Must use Docker defaults for Malcolm services.
2. **Malcolm's `su` heredoc breaks `/dev/fd/` access** — kernel procfs restriction makes fd entries inaccessible after UID change. Cannot be fixed without controlling how supervisord runs.
3. **Malcolm's security plugin has 2 layers** — `internal_users.yml` (auth) + `roles_mapping.yml` (authz). Both must be configured AND pushed via `securityadmin.sh`.
4. **Fresh deployments have circular template dependencies** — must bootstrap templates before logstash starts.

### Docker / Container Gotchas
5. **`su` failing silently (exit 0)** is extremely hard to debug — the process simply never starts.
6. **Docker creates missing file bind-mount sources as directories** — always pre-create files before container start.
7. **`docker compose up -d` blocks on `service_healthy`** — bootstrap logic that runs after `up -d` will deadlock if the healthcheck depends on that bootstrap.
8. **`id -u` under sudo returns 0** — use `SUDO_UID` or `stat` for real user detection.

### JVM / Logstash Specifics
9. **Logstash 9.x filters `-Xss` from `LS_JAVA_OPTS`** — use `jvm.options.d/` drop-in files for all non-heap JVM flags.
10. **Always verify JVM flags in bootstrap log** — don't assume env vars pass through.

### Process Lessons
11. **Don't apply privilege fixes globally** — scope to only the affected services.
12. **Re-evaluate workarounds when the root cause is fixed** — leftover workarounds become harmful.
13. **Bypassing an entrypoint's privilege drop skips ALL its side effects** — you must replicate chown, env setup, etc.
14. **Test with the actual execution path** — `docker exec -u 1000` is NOT equivalent to the entrypoint's `su` heredoc.

---

## Known Risks & Watch Items

| Risk | Impact | Mitigation |
|---|---|---|
| Malcolm upgrade may change entrypoint behavior | Supervisord.conf override and PUSER_PRIV_DROP could break | Pin Malcolm image tags; test upgrades in staging |
| `-Xss8m` may not be enough for future zeek plugins | StackOverflowError returns | Monitor pipeline startup; increase to 16m if needed |
| `fix-perms` runs chown on every container restart | Slow startup on large data dirs | Consider conditional check (`stat -c %U`) |
| `no-new-privileges` removed from Malcolm services | Reduced container isolation | Acceptable — Malcolm's design requires setuid; NetTap services keep strict security |
| Template bootstrap pushes 52 templates on every start | Unnecessary API calls on existing deployments | Add idempotency check (check if `malcolm_template` exists first) |

---

## Quick Reference: Issue-to-PR Mapping

| Linear | PR | Title | Date |
|---|---|---|---|
| NET-48 | #54 | OpenSearch 403 + Logstash EACCES | 2026-02-28 |
| NET-49 | #55 | OpenSearch bootstrap deadlock | 2026-02-28 |
| NET-50 | #56 | Logstash PUSER_PRIV_DROP=false | 2026-02-28 |
| NET-51 | #57, #58, #59 | Global priv-drop breaks services | 2026-02-28 |
| NET-52 | #60 | no-new-privileges + template deadlock | 2026-02-28 |
| NET-53 | #61 | Remove now-harmful PUSER_PRIV_DROP | 2026-03-01 |
| NET-54 | #62 | Correct fix: supervisord user= | 2026-03-01 |
| NET-55 | #63 | fix-perms for data/queue chown | 2026-03-01 |
| NET-56 | #64 | StackOverflow via LS_JAVA_OPTS (wrong) | 2026-03-01 |
| NET-57 | #65 | StackOverflow via jvm.options.d (correct) | 2026-03-01 |
