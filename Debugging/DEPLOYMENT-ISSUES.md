# NetTap Deployment Issues — Source of Truth

> **Last updated:** 2026-03-02
> **Status:** 19 issues tracked. 19 RESOLVED. Latest: NET-67 storage API format mismatch (PR #72).

This document tracks every deployment bug encountered while bringing up the NetTap/Malcolm stack. It is the **single source of truth** — consult it before starting any new fix and update it after every change.

---

## Table of Contents

- [Current Stack Health](#current-stack-health)
- [Issue Chain Overview](#issue-chain-overview)
- [Chain 1: OpenSearch Auth & Bootstrap](#chain-1-opensearch-auth--bootstrap)
- [Chain 2: Privilege Drop & Service Startup](#chain-2-privilege-drop--service-startup)
- [Chain 3: Logstash JVM / Pipeline Compilation](#chain-3-logstash-jvm--pipeline-compilation)
- [Chain 4: Missing Malcolm Command/Env Overrides](#chain-4-missing-malcolm-commandenv-overrides)
- [Chain 5: Docker sysfs Symlink Resolution](#chain-5-docker-sysfs-symlink-resolution)
- [Chain 6: Redis Double-Shell Wrapping](#chain-6-redis-double-shell-wrapping)
- [Chain 7: Setup Wizard Auth Redirect](#chain-7-setup-wizard-auth-redirect)
- [Chain 8: Storage API Format Mismatch](#chain-8-storage-api-format-mismatch)
- [Key Files Modified](#key-files-modified)
- [Lessons Learned (Global)](#lessons-learned-global)
- [Known Risks & Watch Items](#known-risks--watch-items)

---

## Current Stack Health

| Service Category | Status | Notes |
|---|---|---|
| OpenSearch | OK | Auth, roles_mapping, bootstrap all working |
| OpenSearch Dashboards | OK | Depends on OpenSearch healthy |
| Logstash (all 7 pipelines) | OK | PR #67 verified — -Xss8m delivered, all 7 pipelines running |
| Redis | OK | Fixed in PR #71 — list-form command matching Malcolm upstream |
| API | OK | Fixed in PR #69 — explicit `command: gunicorn ...` added |
| Filebeat | OK | Fixed in PR #69 — upload-common env vars added |
| Zeek, Suricata, Arkime | RESTARTING | Expected: br0 has no carrier (cables not connected). Will stabilize when plugged in. |
| nginx-proxy | OK | Depends on API — now healthy after API fix |
| CyberChef | UNHEALTHY | Low priority — app runs but healthcheck endpoint may not exist |
| NetTap daemon NIC discovery | OK | Fixed in PR #70 — full /sys mount resolves symlinks. Verified correct. |
| NetTap setup wizard API | OK | Fixed in PR #71 (auth redirect) + PR #72 (storage format mismatch) |
| NetTap custom services | OK | daemon, web, nginx keep strict security |

---

## Issue Chain Overview

The deployment bugs fall into **7 causal chains**. Each chain had a root cause that triggered cascading failures, and some fixes introduced new bugs that required follow-up fixes.

```
CHAIN 1: OpenSearch Auth & Bootstrap (NET-48 → NET-49)
  PR #54 → PR #55

CHAIN 2: Privilege Drop & Service Startup (NET-48 → NET-50 → NET-51 → NET-52 → NET-53 → NET-54 → NET-55)
  PR #54 → PR #56 → PR #57 → PR #58 → PR #59 → PR #60 → PR #61 → PR #62 → PR #63

CHAIN 3: Logstash JVM / Pipeline Compilation (NET-56 → NET-57 → NET-58 → NET-59)
  PR #64 → PR #65 → PR #66 → PR #67

CHAIN 4: Missing Malcolm Command/Env Overrides (NET-61, NET-62, NET-63)
  PR #69

CHAIN 5: Docker sysfs Symlink Resolution (NET-64)
  PR #70

CHAIN 6: Redis Double-Shell Wrapping (NET-65)
  PR #69 (broke) → PR #71 (fix)

CHAIN 7: Setup Wizard Auth Redirect (NET-66)
  PR #71

CHAIN 8: Storage API Format Mismatch (NET-67)
  PR #72
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

### NET-57 — malcolm-zeek Fix via jvm.options.d Drop-in (WRONG — Logstash ignores jvm.options.d/)
| Field | Value |
|---|---|
| **Linear** | [NET-57](https://linear.app/nettap/issue/NET-57) |
| **PR** | [#65](https://github.com/EliasMarine/NetTap/pull/65) |
| **Status** | Done — BUT FIX WAS WRONG (superseded by NET-58) |
| **Severity** | High |
| **Date** | 2026-03-01 |

**Symptom:** Same as NET-56 — PR #64's `-Xss4m` had no effect.

**Root Cause:** Logstash 9.x filters `-Xss` from `LS_JAVA_OPTS`.

**Attempted Fix (WRONG):**
1. Created `config/logstash/jvm.options.d/99-nettap.options` with `-Xss8m`
2. Volume-mounted at `/usr/share/logstash/config/jvm.options.d/99-nettap.options:ro`
3. Reverted dead `-Xss4m` from `LS_JAVA_OPTS`
4. Bumped to 8m (from 4m) for headroom

**Why it failed:** **Logstash does NOT support `jvm.options.d/` drop-in directories.** This is an **Elasticsearch-only** feature. Logstash's `JvmOptionsParser.java` reads only a single `jvm.options` file. The mounted file was completely ignored.

**Key Insight (CORRECTED):** `jvm.options.d/` is **Elasticsearch-only**, NOT shared across the Elastic stack. Never assume features work across products without reading the source code.

---

### NET-58 — Inject -Xss8m into actual jvm.options at startup (Correct Fix)
| Field | Value |
|---|---|
| **Linear** | [NET-58](https://linear.app/nettap/issue/NET-58) |
| **PR** | [#66](https://github.com/EliasMarine/NetTap/pull/66) |
| **Status** | Done — AWAITING HOST VERIFICATION |
| **Severity** | Urgent |
| **Date** | 2026-03-01 |

**Symptom:** StackOverflowError persists after PR #65 deployed. Test run shows `compileDependencies` → `flatten` → `filterDataset`/`split` recursive overflow in malcolm-zeek pipeline compilation.

**Root Cause:** PR #65 mounted `-Xss8m` into `jvm.options.d/` which Logstash completely ignores. Three failed delivery mechanisms:
1. PR #64: `-Xss4m` in `LS_JAVA_OPTS` → filtered by Logstash 9.x launcher
2. PR #65: `jvm.options.d/99-nettap.options` → Elasticsearch-only feature, Logstash ignores
3. **This PR: inject into actual `jvm.options` file** ✅

**Fix:**
Modified the `fix-perms` supervisord program (runs as root, priority 1, before logstash starts) to also append `-Xss8m` to the actual `/usr/share/logstash/config/jvm.options` file:
```sh
sh -c "chown -R logstash:logstash /usr/share/logstash/data && grep -q '^-Xss' /usr/share/logstash/config/jvm.options || echo '-Xss8m' >> /usr/share/logstash/config/jvm.options"
```
The `grep -q '^-Xss'` guard ensures idempotency across container restarts.

Also removed the dead `jvm.options.d` volume mount from `docker-compose.yml`.

**Files Changed:**
- `config/logstash/supervisord.conf` — fix-perms now injects `-Xss8m` into jvm.options
- `docker/docker-compose.yml` — removed dead jvm.options.d volume mount

**Verification Steps (on nettap host):**
```bash
cd ~/NetTap && git pull origin develop
docker compose -f docker/docker-compose.yml up -d --force-recreate logstash
# Verify -Xss8m was injected
docker exec nettap-logstash cat /usr/share/logstash/config/jvm.options | grep Xss
# Check pipeline startup
docker logs -f nettap-logstash 2>&1 | head -200
# Verify idempotency (restart and check only one -Xss line)
docker compose -f docker/docker-compose.yml restart logstash
docker exec nettap-logstash grep -c '^-Xss' /usr/share/logstash/config/jvm.options
```
Look for:
1. `-Xss8m` in the JVM options output
2. All 7 pipelines reported as running (including `malcolm-zeek`)
3. Only 1 `-Xss` line after restart (idempotency check)

**Key Insight:** There are only **two** reliable ways to set `-Xss` in Logstash:
1. Edit the `jvm.options` file directly (before JVM starts)
2. Inject at container startup via a pre-logstash init script

`jvm.options.d/` doesn't exist in Logstash. Don't assume Elastic stack features are shared.

---

### NET-59 — Race condition: logstash starts before fix-perms completes
| Field | Value |
|---|---|
| **Linear** | [NET-59](https://linear.app/nettap/issue/NET-59) |
| **PR** | [#67](https://github.com/EliasMarine/NetTap/pull/67) |
| **Status** | Done — VERIFIED ON HOST 2026-03-02 |
| **Severity** | Urgent |
| **Date** | 2026-03-01 |

**Symptom:** StackOverflowError persists after PR #66 deployed. The `-Xss8m` injection into `jvm.options` had no effect — the JVM still started with default thread stack size.

**Verification (2026-03-02):** All 7 pipelines running. `-Xss8m` confirmed in JVM bootstrap flags. malcolm-zeek compiled in 4.18s with zero errors.

**Root Cause:** Three bugs in PR #66's approach:

1. **Race condition:** Supervisord's priority system only controls start ORDER, not completion order. With `startsecs=0`, supervisord considers fix-perms "started" immediately upon `fork()`. Logstash starts milliseconds later — before fix-perms finishes the `chown -R` and `echo -Xss8m >>` operations. The JVM reads `jvm.options` before our injection completes.

2. **LS_JAVA_OPTS override potential:** Malcolm's default environment includes `-Xss1536k` in `LS_JAVA_OPTS`. `JvmOptionsParser` processes `LS_JAVA_OPTS` AFTER `jvm.options` entries, so the last `-Xss` value wins — 1.5m overrides our 8m.

3. **Shell operator precedence:** `cmd1 && cmd2 || cmd3` runs `cmd3` when `cmd1` fails, masking chown failures.

**Fix (Two-Part):**
1. **Eliminate race:** Logstash set to `autostart=false` in supervisord. fix-perms does all init tasks (chown + jvm.options inject), then explicitly starts logstash via `supervisorctl start logstash`. This GUARANTEES init is complete before the JVM starts.
2. **Belt-and-suspenders:** Append `-Xss8m` to `LS_JAVA_OPTS` in docker-compose.yml after env expansion, ensuring it's always the last `-Xss` flag regardless of what the environment sets.
3. **Shell logic fix:** Replaced `&&`/`||` chain with proper `if ! grep; then echo; fi`.

**Files Changed:**
- `config/logstash/supervisord.conf` — logstash `autostart=false`, fix-perms starts it via supervisorctl
- `docker/docker-compose.yml` — `-Xss8m` appended to LS_JAVA_OPTS, dead comments removed

**Verification Steps (on nettap host):**
```bash
cd ~/NetTap && git pull origin develop
docker compose -f docker/docker-compose.yml up -d --force-recreate logstash
# Check fix-perms completed before logstash started
docker logs nettap-logstash 2>&1 | grep -E 'fix-perms|starting logstash'
# Verify -Xss8m in jvm.options
docker exec nettap-logstash cat /usr/share/logstash/config/jvm.options | grep Xss
# Verify malcolm-zeek pipeline compiles
docker logs -f nettap-logstash 2>&1 | head -200
```

**Key Insight:** For one-shot init tasks that MUST complete before another program starts, use `autostart=false` on the dependent program and start it via `supervisorctl` from the init task. Supervisord priority alone is NOT sufficient — it's start order, not a completion barrier.

---

## Chain 4: Missing Malcolm Command/Env Overrides

These three issues were discovered during a fresh `install.sh` deployment (2026-03-02). They share a common root cause: Malcolm's published Docker images do NOT include working default CMD/env for all services — the compose file must provide explicit `command:` overrides and all referenced environment variables.

### NET-61 — Redis Crash-Loop: Missing `command:` Override
| Field | Value |
|---|---|
| **Linear** | [NET-61](https://linear.app/nettap/issue/NET-61) |
| **PR** | [#69](https://github.com/EliasMarine/NetTap/pull/69) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-02 |

**Symptom:** Redis container runs entrypoint (usermod, uid=1000(redis)), then exits with code 0. No redis-server process ever starts. Crash-loops indefinitely.

**Root Cause:** Malcolm's redis Docker image does NOT have a default CMD that starts redis-server. Malcolm's own docker-compose.yml provides an explicit `command:` that starts redis-server with AOF persistence, memory limits, and authentication flags. Our compose had no `command:` override, so after the entrypoint completed uid/gid setup, there was no process to run — container exited cleanly.

**Fix:** Added explicit `command:` matching Malcolm's compose:
```yaml
command: >-
  redis-server --dir /data --appendonly yes --appendfsync everysec
    --no-appendfsync-on-rewrite yes --auto-aof-rewrite-percentage 100
    --auto-aof-rewrite-min-size $$REDIS_AUTO_AOF_REWRITE_MIN_SIZE
    --save '' --maxmemory $$REDIS_MAXMEMORY
    --maxmemory-policy $$REDIS_MAXMEMORY_POLICY
    --requirepass $$REDIS_PASSWORD
```
Also added required env vars: `REDIS_AUTO_AOF_REWRITE_MIN_SIZE`, `REDIS_MAXMEMORY`, `REDIS_MAXMEMORY_POLICY`. Fixed healthcheck to pass `-a` password flag to `redis-cli`.

**Files Changed:**
- `docker/docker-compose.yml` — redis service: command + env vars + healthcheck fix

**Key Insight:** Malcolm images use their entrypoint (`docker-uid-gid-setup.sh`) as ENTRYPOINT, not CMD. The actual service command MUST be provided by the compose file. An exit code 0 with no errors means "nothing to run" — not "success".

---

### NET-62 — API Crash-Loop: Missing `command:` Override
| Field | Value |
|---|---|
| **Linear** | [NET-62](https://linear.app/nettap/issue/NET-62) |
| **PR** | [#69](https://github.com/EliasMarine/NetTap/pull/69) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-02 |

**Symptom:** API container runs entrypoint, reports "opensearch-local is up and healthy", then exits and restarts. No Flask/gunicorn server ever starts.

**Root Cause:** Same pattern as Redis — Malcolm's API image does NOT have a default CMD for gunicorn. Malcolm's compose provides `command: gunicorn --bind 0:5000 manage:app`. Without this, the entrypoint's OpenSearch healthcheck runs, prints success, and the container exits.

**Fix:** Added explicit command and missing env vars:
```yaml
command: gunicorn --bind 0:5000 manage:app
environment:
  REDIS_HOST: "redis"
  REDIS_PORT: "6379"
  REDIS_PASSWORD: "..."
  NGINX_AUTH_MODE: "basic"
  DASHBOARDS_URL: "http://dashboards:5601/dashboards"
  ARKIME_VIEWER_PORT: "8005"
```

**Files Changed:**
- `docker/docker-compose.yml` — api service: command + env vars

**Key Insight:** The "opensearch-local is up and healthy" log line is NOT from the API server — it's from the entrypoint's pre-flight check. The actual server never started because no command was provided.

---

### NET-63 — Filebeat Crash-Loop: Missing `PCAP_PIPELINE_VERBOSITY` Env Var
| Field | Value |
|---|---|
| **Linear** | [NET-63](https://linear.app/nettap/issue/NET-63) |
| **PR** | [#69](https://github.com/EliasMarine/NetTap/pull/69) |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-02 |

**Symptom:** Filebeat crash-loops with: `Format string ... contains names ('ENV_PCAP_PIPELINE_VERBOSITY') which cannot be expanded`. Supervisord refuses to start any programs.

**Root Cause:** Malcolm's filebeat-oss:26.02.0 image has a `program:watch-upload` section in `/etc/supervisord.conf` that references `%(ENV_PCAP_PIPELINE_VERBOSITY)s`. Supervisord's `%(ENV_*)s` syntax expands process environment variables. Malcolm's compose passes this via `upload-common.env`, but our compose didn't include it.

**Fix:** Added all vars from Malcolm's `upload-common.env`:
```yaml
AUTO_TAG: "true"
PCAP_NODE_NAME: "malcolm"
PCAP_PIPELINE_VERBOSITY: ""
PCAP_PIPELINE_IGNORE_PREEXISTING: "false"
PCAP_PIPELINE_POLLING: "false"
PCAP_PIPELINE_POLLING_ASSUME_CLOSED_SEC: "10"
PCAP_MONITOR_HOST: "pcap-monitor"
```

**Files Changed:**
- `docker/docker-compose.yml` — filebeat service: env vars

**Key Insight:** Supervisord's `%(ENV_*)s` syntax is strict — if the env var doesn't exist, supervisord crashes immediately without starting ANY programs. Unlike shell variable expansion which can have defaults, supervisord treats missing vars as fatal errors. Always verify that ALL env vars referenced in Malcolm's supervisord configs are passed through the compose file.

---

## Chain 5: Docker sysfs Symlink Resolution

### NET-64 — NIC Discovery Returns Empty Metadata (sysfs Symlink Mount)

| Field | Value |
|---|---|
| **Linear** | NET-64 |
| **PR** | #70 |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-01 |

**Symptom:** Setup wizard shows red X on "Two or more network interfaces". The Interfaces page shows "Server returned invalid data — daemon may need restart". NIC dropdowns are empty. The daemon's `/api/setup/nics` endpoint returns interface names but ALL metadata fields are empty:
```json
{"interfaces": [{"name": "enp2s0", "mac": "", "state": "unknown", "speed": "", "driver": "", "type": "virtual"}, ...]}
```

All interfaces classified as `"virtual"` (no `device` symlink resolvable) — the setup wizard sees 0 physical NICs.

**Root Cause:** Linux's `/sys/class/net/<iface>` entries are **symlinks** that point to `/sys/devices/pci0000:00/0000:00:1c.0/0000:03:00.0/net/enp3s0`. When Docker mounts only `/sys/class/net:/host/sys/class/net:ro`, the symlink directory itself is visible (so `iterdir()` lists interface names), but the symlink targets (`/sys/devices/...`) don't exist inside the container.

This means:
- `Path("/host/sys/class/net").iterdir()` — works (lists interface names like `enp2s0`)
- `Path("/host/sys/class/net/enp2s0/address").read_text()` — **fails** (OSError, target path doesn't exist)
- `Path("/host/sys/class/net/enp2s0/device").exists()` — **False** (no device symlink → classified as "virtual")
- All `_read_sysfs()` calls return `""`, `_classify_type()` returns `"virtual"`, `_get_driver()` returns `""`

The daemon code was **correct** — it was the Docker volume mount that made sysfs data inaccessible.

**Fix:** Changed the volume mount from mounting only `/sys/class/net` to mounting all of `/sys`:

```yaml
# OLD (broken) — symlink targets don't exist inside container
- /sys/class/net:/host/sys/class/net:ro

# NEW (fixed) — entire sysfs tree available, symlinks resolve correctly
- /sys:/host/sys:ro
- /sys/class/leds:/host/sys/class/leds  # writable overlay for LED blink
```

The writable `/sys/class/leds` overlay is preserved because the igc LED blink feature needs to write to sysfs trigger files.

**Files Changed:**
- `docker/docker-compose.yml` — daemon volumes: `/sys:/host/sys:ro` replaces `/sys/class/net:/host/sys/class/net:ro`
- `daemon/api/nic_discovery.py` — updated comment explaining why full `/sys` mount is needed

**Key Insight:** Never bind-mount a single sysfs subdirectory that contains symlinks to other parts of the sysfs tree. Linux's `/sys/class/` directories are almost entirely symlinks — always mount the entire `/sys` tree (read-only) and overlay writable subdirectories as needed.

---

## Chain 6: Redis Double-Shell Wrapping

### NET-65 — Redis crash-loop: string-form command double-shell-wrapped

| Field | Value |
|---|---|
| **Linear** | NET-65 |
| **PR** | #71 |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-01 |

**Symptom:** Redis container exits with code 1 immediately after start. `Restarting (1)` in docker ps. No useful logs — redis-server never fully initializes.

**Root Cause:** PR #69 added a string-form `command:` to the redis service:
```yaml
command: >-
  redis-server --dir /data ... --save '' ... --requirepass $$REDIS_PASSWORD
```

Docker wraps string-form commands in `/bin/sh -c "..."`. Malcolm's entrypoint (`docker-uid-gid-setup.sh`) then passes this through `su -s /bin/bash -p` with `printf "%q "` quoting. This creates **double shell wrapping** — the `--save ''` single quotes get mangled through two shell layers, resulting in `--save` with no argument. Redis-server sees "bad directive or wrong number of arguments" and exits with code 1.

Malcolm's upstream compose uses **list-form** (exec form) with explicit `sh -c`:
```yaml
command: ["sh", "-c", "redis-server --dir /data ... --save '' ..."]
```

List-form passes discrete arguments to the entrypoint. The entrypoint execs `sh -c "redis-server ..."` — only ONE shell layer processes the command, preserving quoting.

**Fix:** Changed to list-form matching Malcolm's upstream:
```yaml
command:
  - sh
  - -c
  - >-
    redis-server --dir /data --appendonly yes ... --save '' ...
```

Also confirmed: Malcolm's entrypoint uses `su -s /bin/bash -p` (the `-p` flag **preserves** environment), so `$REDIS_PASSWORD` etc. expand correctly from container env vars.

**Files Changed:**
- `docker/docker-compose.yml` — redis `command:` changed from string-form to list-form

**Key Insight:** When using Malcolm images, ALWAYS use list-form `command:` (array syntax with `sh -c`) — never string-form. String-form gets double-shell-wrapped through Malcolm's entrypoint, mangling quoting. This matches Malcolm's upstream compose pattern exactly.

---

## Chain 7: Setup Wizard Auth Redirect

### NET-66 — Setup wizard API returns HTML instead of JSON (auth redirect)

| Field | Value |
|---|---|
| **Linear** | NET-66 |
| **PR** | #71 |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-01 |

**Symptom:** Setup wizard Step 2 (Interfaces) shows "Server returned invalid data — daemon may need restart". NIC dropdowns are empty. Step 1 shows red X on "Two or more network interfaces". The daemon is healthy and the sysfs mount is correct (PR #70).

**Root Cause:** The SvelteKit auth middleware in `web/src/hooks.server.ts` intercepts ALL requests before they reach route handlers. The `PUBLIC_PATHS` array was:
```typescript
const PUBLIC_PATHS = ['/login', '/setup', '/api/auth'];
```

The setup wizard page (`/setup`) is public, but its API calls (`/api/setup/nics`, `/api/setup/bridge`, `/api/setup/storage`) are NOT — they start with `/api/setup`, not `/setup`.

On first run (no users exist), the hooks middleware has TWO redirect traps:
1. **First-run redirect** (line 25): If `!hasUsers()`, redirect to `/setup` — applies to `/api/setup/nics` because it doesn't start with `/setup`
2. **Auth guard** (line 40): If not authenticated and not public, redirect to `/login`

Both traps fire on `/api/setup/nics`. The browser's `fetch()` follows the 302 redirect automatically, receives the HTML of `/setup` (or `/login`), and `JSON.parse()` fails on HTML.

**Why Step 1 appeared to "work":** It didn't. The `checkRequirements()` function catches ALL errors silently and just sets `requirements.nics.status = 'fail'` (red X). It never displays the error message. Step 2's `fetchNics()` displays the error message to the user.

**Fix:** Added `/api/setup` to both the PUBLIC_PATHS array and the first-run redirect exclusion:
```typescript
const PUBLIC_PATHS = ['/login', '/setup', '/api/auth', '/api/setup'];
// ...
if (!pathname.startsWith('/setup') && !pathname.startsWith('/api/auth') && !pathname.startsWith('/api/setup')) {
```

**Files Changed:**
- `web/src/hooks.server.ts` — added `/api/setup` to PUBLIC_PATHS and first-run redirect exclusion

**Key Insight:** When a page is public, ALL of its API calls must also be public. The setup wizard is public because it runs before any user account exists — but its `/api/setup/*` endpoints were behind auth. Always test the full request chain in first-run (no-users) state.

---

## Chain 8: Storage API Format Mismatch

### NET-67 — Storage API response format doesn't match frontend StorageStatus interface
| Field | Value |
|---|---|
| **Linear** | [NET-67](https://linear.app/nettap/issue/NET-67) |
| **PR** | [#72](https://github.com/EliasMarine/NetTap/pull/72) |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-02 |

**Symptoms:**
- Setup wizard Step 1 "Sufficient disk space (100GB+)" shows red X despite 1.8TB disk
- Step 4 "Storage Configuration" shows NaN/undefined values for disk bar and retention fields

**Root Cause:**
The daemon's `StorageManager.get_status()` returned a completely different format than the web frontend's `StorageStatus` TypeScript interface expected:

| Frontend expects | Daemon returned |
|---|---|
| `disk_free_gb: 1800` (number, GB) | **Not present at all** |
| `disk_total_gb: 1830` (number, GB) | **Not present at all** |
| `disk_usage_percent: 2.3` (number) | `"2.3%"` (string with % sign) |
| `hot_days: 90` (top-level) | `retention.hot_days: 90` (nested) |
| `disk_threshold_percent: 80` (0-100) | `disk_threshold: 0.80` (fraction 0-1) |
| `estimated_daily_gb: 1.2` | **Not present at all** |

The SvelteKit proxy at `/api/setup/storage` passed the daemon response through without transformation. Frontend did `storageData.disk_free_gb || 0` → `undefined || 0` = 0 → `0 >= 100` → fail.

**Causal Chain:**
```
daemon get_status() lacks absolute GB values
  → SvelteKit proxy passes through without transformation
    → frontend gets { disk_usage: 0.023 } instead of { disk_free_gb: 1800 }
      → disk_free_gb is undefined → defaults to 0
        → 0 < 100GB → Step 1 shows red X
        → Step 4 renders NaN for disk bar, undefined for retention fields
```

**Fix:**
1. Updated daemon's `get_status()` (`daemon/storage/manager.py`):
   - Added `disk_total_gb`, `disk_used_gb`, `disk_free_gb` via `shutil.disk_usage()`
   - Changed `disk_usage_percent` from string `"X.X%"` to number `X.X`
   - Flattened `retention.hot_days` → top-level `hot_days` (kept nested for backward compat)
   - Added `disk_threshold_percent` and `emergency_threshold_percent` as 0-100 values
   - Added `estimated_daily_gb: 1.2` and `source: "daemon"`
   - Wrapped `list_indices()` in try/except for OpenSearch-down resilience during setup
2. Added `normalizeStorageStatus()` in SvelteKit proxy as safety net for both old and new daemon formats
3. Fixed settings page to read normalized top-level fields instead of nested `data.retention`

**Files Changed:**
- `daemon/storage/manager.py` — Updated `get_status()` to include absolute disk sizes
- `daemon/tests/test_storage_manager.py` — Updated test to verify new response fields
- `web/src/routes/api/setup/storage/+server.ts` — Added normalize transform layer
- `web/src/routes/settings/+page.svelte` — Fixed to use normalized format

**Key Insight:** TypeScript interfaces define the *desired* shape but don't enforce it at runtime. When a proxy layer passes through external data (like daemon responses), it MUST validate/transform the data to match the interface. Always test the full chain: daemon response → proxy → frontend rendering.

---

## Key Files Modified

These files were touched repeatedly across the 10 PRs. Check their current state before making changes.

| File | PRs | Current State |
|---|---|---|
| `docker/docker-compose.yml` | #54-#71 (all 16) | Logstash: PUSER_PRIV_DROP=false, supervisord.conf mount, LS_JAVA_OPTS includes -Xss8m. Redis: list-form command (sh -c). API: explicit gunicorn command. Filebeat: upload-common env vars. Daemon: full /sys mount + healthcheck. |
| `web/src/hooks.server.ts` | #71 | PUBLIC_PATHS includes `/api/setup`; first-run redirect skips `/api/setup/*` |
| `config/logstash/supervisord.conf` | #62, #63, #66, #67 | fix-perms (chown + -Xss8m inject + supervisorctl start logstash) + logstash (autostart=false, user=logstash) |
| `config/logstash/jvm.options.d/99-nettap.options` | #65 | DEAD FILE — Logstash ignores jvm.options.d/ (Elasticsearch-only). Volume mount removed in #66. |
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
9. **Logstash 9.x filters `-Xss` from `LS_JAVA_OPTS`** — env vars are unreliable for non-heap JVM flags.
10. **Always verify JVM flags in bootstrap log** — don't assume env vars pass through.
11. **`jvm.options.d/` is Elasticsearch-only** — Logstash's `JvmOptionsParser.java` reads only a single `jvm.options` file. Never assume Elastic stack features are shared across products.
12. **Only two ways to set `-Xss` in Logstash:** (a) edit the `jvm.options` file directly, or (b) inject at container startup before the JVM launches.

### Supervisord Gotchas
13. **Supervisord priority ≠ sequential execution** — priority controls fork order, not completion barriers. Use `autostart=false` + `supervisorctl start` for true dependency ordering.
14. **`startsecs=0` means 'started immediately'** — supervisord considers the process running the instant it forks, not when it finishes.
15. **`&&`/`||` chains have surprising behavior** — `cmd1 && cmd2 || cmd3` runs cmd3 when cmd1 fails, masking errors. Use proper `if/then/fi`.

### Malcolm Image Contract (NEW — Chain 4)
16. **Malcolm images use ENTRYPOINT, not CMD** — the entrypoint (`docker-uid-gid-setup.sh`) handles uid/gid setup. The actual service command MUST be provided via `command:` in the compose file. Without it, the container exits cleanly after the entrypoint finishes.
17. **Exit code 0 + no logs = "nothing to run"** — for Malcolm images, a clean exit with only usermod/uid output means no CMD was provided. The entrypoint succeeded but there was no service to start.
18. **Supervisord `%(ENV_*)s` is strictly fatal** — unlike shell `$VAR` which expands to empty, supervisord treats missing env vars as a hard crash. Every `%(ENV_*)s` referenced in supervisord.conf MUST be passed via the compose environment.
19. **Always compare against Malcolm's upstream docker-compose** — Malcolm's images are designed to work with Malcolm's compose. When writing our own compose, we must provide equivalent `command:`, `env_file:`, and `volumes:` directives. Missing any of these causes silent failures.

### Docker Command Form
28. **Always use list-form `command:` with Malcolm images** — string-form commands get double-shell-wrapped through Malcolm's `docker-uid-gid-setup.sh` entrypoint, mangling quoting. Use `["sh", "-c", "..."]` to match Malcolm's upstream compose pattern.
29. **`su -s /bin/bash -p` preserves env; `su -` does not** — Malcolm's entrypoint uses `-p` (preserve). This means env vars in commands ARE expanded correctly. The problem is quoting, not env expansion.

### Web / Auth Gotchas
30. **Public pages need public API endpoints** — if a page is accessible without auth, all its `fetch()` calls must also bypass auth. Otherwise the auth middleware returns HTML redirects that break JSON parsing.
31. **Browser `fetch()` follows 302 redirects silently** — a redirect from an API endpoint to an HTML page succeeds (HTTP 200) but the body is HTML, not JSON. The only clue is `JSON.parse()` failing.

### API Contract Gotchas
32. **TypeScript interfaces don't enforce runtime shape** — when a proxy passes through external data (daemon responses), the TypeScript type parameter on `daemonJSON<T>()` only checks compile-time usage, not the actual JSON shape. Always validate/normalize at the boundary.
33. **Proxy layers must transform, not just forward** — a SvelteKit API route that proxies to a Python daemon must normalize the response (flatten nested fields, convert types, add defaults) rather than blindly passing JSON through. The daemon's internal format and the frontend's expected format are separate contracts.

### sysfs / Filesystem Gotchas
26. **`/sys/class/*` directories are symlink farms** — entries like `/sys/class/net/eth0` are symlinks to `/sys/devices/pci.../net/eth0`. Mounting only a `/sys/class/` subdirectory brings the symlinks but not their targets. Always mount all of `/sys:ro` and overlay writable paths as needed.
27. **Directory listing succeeds even with broken symlinks** — `iterdir()` / `ls` shows entries, but reading files inside those entries fails silently with empty strings (OSError caught by sysfs read helpers). This makes the bug subtle: the daemon appears to work (returns valid JSON with interface names) but all metadata is empty.

### Process Lessons
20. **Don't apply privilege fixes globally** — scope to only the affected services.
21. **Re-evaluate workarounds when the root cause is fixed** — leftover workarounds become harmful.
22. **Bypassing an entrypoint's privilege drop skips ALL its side effects** — you must replicate chown, env setup, etc.
23. **Test with the actual execution path** — `docker exec -u 1000` is NOT equivalent to the entrypoint's `su` heredoc.
24. **Always read the source code** — the assumption that `jvm.options.d/` works in Logstash came from Elasticsearch docs. Reading `JvmOptionsParser.java` would have caught this immediately.
25. **Test from `install.sh`, not just `docker compose up -d`** — individual service restarts may work while a full fresh deployment reveals missing dependencies.

---

## Known Risks & Watch Items

| Risk | Impact | Mitigation |
|---|---|---|
| Malcolm upgrade may change entrypoint behavior | Supervisord.conf override and PUSER_PRIV_DROP could break | Pin Malcolm image tags; test upgrades in staging |
| `-Xss8m` may not be enough for future zeek plugins | StackOverflowError returns | Monitor pipeline startup; increase to 16m if needed |
| `fix-perms` runs chown on every container restart | Slow startup on large data dirs | Consider conditional check (`stat -c %U`) |
| `no-new-privileges` removed from Malcolm services | Reduced container isolation | Acceptable — Malcolm's design requires setuid; NetTap services keep strict security |
| Template bootstrap pushes 52 templates on every start | Unnecessary API calls on existing deployments | Add idempotency check (check if `malcolm_template` exists first) |
| Malcolm image upgrades may add new supervisord env refs | Filebeat-style crash-loops from missing env vars | After upgrading Malcolm tag, check all supervisord.conf files inside images for new `%(ENV_*)s` references |
| More Malcolm services may need explicit `command:` | Silent exit code 0 crashes | Audit all Malcolm services against upstream compose after tag bumps |
| Full `/sys` mount exposes entire sysfs tree to daemon | Larger attack surface than just `/sys/class/net` | Mount is read-only (:ro), container has cap_drop: ALL + selective cap_add, read_only: true. Only `/sys/class/leds` is writable for LED blink. |

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
| NET-57 | #65 | StackOverflow via jvm.options.d (WRONG — ES-only) | 2026-03-01 |
| NET-58 | #66 | StackOverflow fix: inject -Xss8m into jvm.options (race condition) | 2026-03-01 |
| NET-59 | #67 | Race condition fix: autostart=false + supervisorctl + LS_JAVA_OPTS | 2026-03-01 |
| NET-60 | #68 | Setup wizard NIC detection + LED blink | 2026-03-02 |
| NET-61 | #69 | Redis crash-loop: missing command: override | 2026-03-02 |
| NET-62 | #69 | API crash-loop: missing gunicorn command | 2026-03-02 |
| NET-63 | #69 | Filebeat crash-loop: missing PCAP_PIPELINE_VERBOSITY | 2026-03-02 |
| NET-64 | #70 | NIC discovery empty metadata: sysfs symlink mount | 2026-03-01 |
| NET-65 | #71 | Redis crash-loop: double-shell-wrapping mangles command | 2026-03-01 |
| NET-66 | #71 | Setup wizard API returns HTML: auth redirect on /api/setup/* | 2026-03-01 |
| NET-67 | #72 | Storage API format mismatch: missing disk_free_gb, wrong types | 2026-03-02 |
