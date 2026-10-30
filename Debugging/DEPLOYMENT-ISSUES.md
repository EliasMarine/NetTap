# NetTap Deployment Issues — Source of Truth

> **Last updated:** 2026-03-16
> **Status:** 58 issues tracked. 58 RESOLVED. Latest: Fixed category drill-down page crash (`each_key_duplicate`) — 3 daemon→frontend data contract mismatches in `handle_alert_category_detail()` and `handle_alert_category_timeline()`. Lessons 97–99 added.

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
- [Chain 9: NIC LED Identification Permission + Fallback](#chain-9-nic-led-identification-permission--fallback)
- [Chain 10: Malcolm Capture Services + Proxy Env Vars](#chain-10-malcolm-capture-services--proxy-env-vars)
- [Chain 13: OpenSearch .keyword Suffix + Log Search Format + CSP Fonts](#chain-13-opensearch-keyword-suffix--log-search-format--csp-fonts)
- [Chain 14: Logstash Index Pattern Env Vars Missing](#chain-14-logstash-index-pattern-env-vars-missing)
- [Chain 15: pcap-capture Restart Loop + nginx-proxy Healthcheck + Boot Persistence](#chain-15-pcap-capture-restart-loop--nginx-proxy-healthcheck--boot-persistence)
- [Key Files Modified](#key-files-modified)
- [Lessons Learned (Global)](#lessons-learned-global)
- [Known Risks & Watch Items](#known-risks--watch-items)

---

## Current Stack Health

| Service Category | Status | Notes |
|---|---|---|
| OpenSearch | OK | Auth, roles_mapping, bootstrap all working |
| OpenSearch Dashboards | OK | Depends on OpenSearch healthy |
| Logstash (all 7 pipelines) | OK | PR #67 verified — -Xss8m delivered, all 7 pipelines running. Index pattern env vars fixed (717bd24) — MALCOLM_NETWORK_INDEX_PATTERN/SUFFIX now set on logstash service. |
| Redis | OK | Fixed in PR #71 — list-form command |
| API | OK | Fixed in PR #69 — explicit `command: gunicorn ...` added |
| Filebeat | OK | Fixed — REDIS_HOST/PORT/PASSWORD env vars added (NET-79) |
| Zeek, Suricata, Arkime | OK | Fixed — `EXTRA_TAGS: ""` + `MANAGE_PCAP_FILES` env vars added (NET-79). Running on N100. |
| nginx-proxy | OK | Fixed: healthcheck changed to test `:9200` (OpenSearch proxy) instead of `:443` (broken arkime vhost). Removed `:443` port binding. nginx-proxy's real role is OpenSearch proxy for host-networked containers. |
| CyberChef | OK | Fixed NET-86: healthcheck `wget /` → `wget /health`. Service was always running fine. |
| Dashboards | OK | Fixed NET-86: healthcheck curl needed auth credentials. Added `--config curlrc`. |
| Dashboards Helper | OK | Fixed NET-86: `container_health.sh` may not exist → `test -d /proc/1`. |
| Filebeat | OK | Fixed NET-85: `pgrep` not available in Malcolm image → `test -d /proc/1`. Service was running fine (7 inputs, cron jobs succeeding). |
| Logstash startup | **FRAGILE** | `opensearch_status.sh` waits for `malcolm_template` — requires `securityadmin.sh` + template bootstrap. Breaks on `--force-recreate` if roles_mapping.yml resets. Bootstrap commands now in CLAUDE.md (NET-84). |
| NetTap daemon NIC discovery | OK | Fixed in PR #70 — full /sys mount resolves symlinks. Verified correct. |
| NetTap setup wizard API | OK | Fixed in PR #71 — auth middleware skips `/api/setup/*` |
| NetTap web (nettap-web) | OK | Dashboard loads. CSRF 403 fully fixed: NET-81 (PROTOCOL_HEADER/HOST_HEADER env vars + volume chown) + NET-82 (nginx proxy_set_header inheritance — must repeat headers in every location block). System page fixed NET-83 (null-safe SMART health). SSE streaming fixed (proxy_buffering off). |
| NetTap storage API | OK | Fixed NET-80 — `get_status()` now returns `disk_free_gb`, numeric percentages, top-level retention fields matching frontend StorageStatus interface. |
| NetTap custom services | OK | daemon, web, nginx keep strict security |

---

## Issue Chain Overview

The deployment bugs fall into **18 causal chains**. Each chain had a root cause that triggered cascading failures, and some fixes introduced new bugs that required follow-up fixes.

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

CHAIN 8: Storage API Format Mismatch (NET-67 → NET-80)
  PR #72 (docs only) → develop (code fix NET-80)

CHAIN 9: NIC LED Identification Permission + Fallback (NET-68)
  PR #73

CHAIN 10: Malcolm Capture Services + Proxy Env Vars (NET-79)
  fix/malcolm-capture-env-vars → develop

CHAIN 11: OpenSearch Security Reset on Container Recreate
  Manual fix (securityadmin.sh re-run). No code fix yet — needs automation.
  Logstash blocked waiting for malcolm_template because roles_mapping.yml
  reverts to empty on --force-recreate.

CHAIN 12: Setup Wizard CSRF + Volume Permissions (NET-81)
  fix/nic-led-identify-fallback → develop
  Admin account creation silently fails: SvelteKit CSRF 403 behind nginx
  + /var/lib/nettap-web owned by root (nettap user can't write users.json).

CHAIN 13: OpenSearch .keyword Suffix + Log Search Format + CSP Fonts
  PR #92 (phase-4/webui-v2)
  All dashboard aggregations fail 400: text fields not optimised for aggregations.
  Log search returns flat docs instead of _source wrapper. CSP blocks Google Fonts.

CHAIN 14: Logstash Index Pattern Env Vars Missing
  Commit 717bd24 (phase-4/webui-v2)
  Logstash format_index_string.rb crashes: MALCOLM_NETWORK_INDEX_PATTERN env var missing.
  89K+ events land in broken literal index %{[@metadata][malcolm_opensearch_index]}.

CHAIN 15: pcap-capture Restart Loop + nginx-proxy Healthcheck + Boot Persistence
  Commits 65e31cf + ed3cf84 (phase-4/webui-v2)
  pcap-capture: usermod root PID 1 crash. nginx-proxy: arkime:8005 upstream unresolvable.
  nettap-nginx: SSL key permission denied. OpenSearch: security not initialized.
  nettap.service: no systemd unit for boot persistence.

CHAIN 16: Mirror/SPAN Full-Stack Test Issues (phase-5/mirror-span-mode)
  Commit f6b40b5
  1. Daemon crash-loop: PyYAML missing from requirements.txt (suricata_rules.py imports yaml).
  2. Full-stack test HTTP 000 on all API checks: port 8880 is Docker `expose` only (internal),
     not `ports` published. Fix: use `docker exec` to curl from inside daemon container.
  3. Full-stack test script dies mid-way: `set -euo pipefail` kills on first non-zero. Fix: remove set -e.
  4. $HOME resolves to /root under sudo: hard-coded NETTAP_DIR=/home/nettap/NetTap.
  5. Web UI unchanged after rebuild: only daemon was rebuilt, not nettap-web. Fix: rebuild both.
  6. Nav items invisible: new sidebar entries referenced icon names with no SVG paths. Fix: added 8 SVG icon paths.
  7. Web checks fail HTTP 301: nginx HTTP→HTTPS redirect not in accepted codes. Fix: accept 301.
  8. Nginx stale upstream after web recreate: full-stack script only recreated daemon+web, not nginx.
     Fix: added nettap-nginx to `docker compose up -d ... --force-recreate`.
  9. OpenSearch _cat/indices returns empty: wrong auth credentials (-u admin:admin). Must use curlrc.
  10. OpenSearch queries via curl return empty with http://: daemon uses https://opensearch:9200
      (set via OPENSEARCH_URL env var). Must use https:// + --insecure for all manual queries.
  11. Dashboard pages (traffic, devices, bandwidth, DNS, IoT, live) all show zeros despite 15M+
      docs in OpenSearch: ALL dashboard queries filter on event.dataset=conn (Zeek connection logs).
      Root cause: ZEEK_JSON env var missing from zeek-live service in docker-compose.yml.
      Zeek's local.zeek checks `getenv("ZEEK_JSON")` — without it, Zeek outputs TSV format
      instead of JSON. Logstash can't parse TSV → conn/dns/http/tls logs land in broken
      `%{[@metadata][malcolm_opensearch_index]}` index (124K orphaned docs) or get dropped entirely.
      Metadata logs (known_hosts, etc.) use a different code path that works without JSON.
      Fix: Added `ZEEK_JSON: "true"` to zeek-live environment in docker-compose.yml.
  12. Docker compose service names don't include `nettap-` prefix: `docker compose up -d
      zeek-live` not `nettap-zeek-live`. Container names have the prefix (set via
      container_name), but compose commands use the service name from the YAML key.
  13. Malcolm Filebeat processes ROTATED Zeek logs, not active current/ files.
      `filebeat-process-zeek-folder.sh` runs every minute via cron. Zeek rotates logs hourly.
      After fixing ZEEK_JSON, conn.log in current/ is JSON but won't reach OpenSearch until
      the next hourly rotation. Restarting Filebeat alone doesn't help — must wait for rotation
      or manually trigger it.
  14. OpenSearch mapper_parsing_exception on event.id: type [long] vs string UID.
      arkime_sessions3-260310 was created by Suricata alerts first (Zeek was broken).
      Suricata's event.id is numeric → mapped as long. Zeek's event.id is string UID
      (e.g., "Ctn46L1IGV1awTb9wj") → ALL Zeek conn docs rejected with 400.
      Fix: delete today's index and let it recreate with correct template mapping.
      Prevention: ensure Malcolm index template maps event.id as keyword, not dynamic.
  15. Mirror/SPAN feature pages show no data — missing SvelteKit proxy routes.
      7 new pages (Live Monitor, Bandwidth, DNS Analytics, IoT & LAN, Changelog,
      Certificates, PCAP Search) all empty despite data flowing in OpenSearch.
      Root cause: client-side API files fetch `/api/live/connections`, `/api/bandwidth/monthly`,
      etc. — no `+server.ts` route handlers existed. SvelteKit returned 404 silently.
      Additionally, changelog.ts/certificates.ts used `VITE_API_URL || 'http://localhost:8880'`
      which tries to reach daemon port 8880 directly from browser — but 8880 is Docker
      `expose`-only (container-to-container), not published to host.
      Fix: (a) Created catch-all `web/src/routes/api/[...path]/+server.ts` that proxies
      unhandled `/api/*` requests to daemon via `daemonFetch()`. SvelteKit routing gives
      priority to existing explicit routes. (b) Fixed 5 API client files + setup page to
      use relative paths instead of `VITE_API_URL`.

CHAIN 17: PCAP Search Filter Syntax + DNS Analytics Field Mismatch (phase-5/mirror-span-mode)
  Commits 6a853e4 + 8763d07 + 5e8acf8
  1. PCAP Search quick filters used BPF syntax (`udp port 53`) but tshark `-Y` requires
     Wireshark display filter syntax (`dns`, `http || tls`, etc.). Changed all quick filters.
  2. Filter validation regex `[;&|` + backtick + `$]` blocked `|` and `&` chars needed for
     display filter `||` and `&&` operators. Removed `|` and `&` from forbidden chars — safe
     because `asyncio.create_subprocess_exec` prevents shell injection (no shell involved).
  3. No per-file PCAP download — only full search results download existed. Added
     `GET /api/pcap/download-file` daemon endpoint + Download buttons in UI.
  4. Preview button appeared broken — no auto-scroll to preview section. Added scrollIntoView.
  5. Tables unsortable — added ascending/descending column sorting to both tables.
  6. DNS Analytics all aggregations returned 0: field names used ECS `dns.*` prefix instead of
     Malcolm's `zeek.dns.*` prefix. Remapped: `dns.question.name` → `zeek.dns.query`,
     `dns.question.type` → `zeek.dns.qtype_name`, `dns.response_code` → `zeek.dns.rcode_name`,
     `event.duration` → `zeek.dns.rtt`.
  7. DNS RTT conversion inverted: divided by 1,000,000 assuming nanoseconds, but Zeek stores
     RTT in seconds. Fixed to multiply by 1000 for milliseconds display.
  8. Complete DNS Analytics page redesign: interactive SVG timeline with tooltips, sortable
     tables, cross-section linking, time range pills, per-device DNS split panel, empty states.

CHAIN 18: PCAP Search Page Redesign (phase-5/mirror-span-mode)
  Commit c02cb9f
  Full interactive redesign of PCAP Search page to match DNS Analytics quality level.
  1. Hero stats row: total files, total size, date range, protocol distribution.
  2. Capture timeline: interactive SVG chart with per-day bars, tooltips, click-to-filter.
  3. Quick filter chips: protocol-based quick filters (DNS, HTTP, TLS, SSH, etc.).
  4. Sortable search results: ascending/descending column sorting on all columns.
  5. Packet preview panel: expandable preview with protocol details.
  6. Protocol breakdown: visual protocol distribution chart.
  7. Two-column file browser: side-by-side layout for file list + details.
  8. Cross-section linking: click stats/timeline to filter results.
  9. Time range pills: quick time range selection (1h, 6h, 24h, 7d, 30d).
  10. DNS copy button CSS fix: bigger icon (1.25rem), accent-blue color.
  11. Added formatRelativeTime and PROTO_FILTER_MAP helpers to pcap.ts API client.
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

## Chain 9: NIC LED Identification Permission + Fallback

### NET-68 — NIC LED blink fails with HTTP 500 on Intel I226-V (igc driver, kernel 6.8)
| Field | Value |
|---|---|
| **Linear** | [NET-68](https://linear.app/nettap/issue/NET-68) |
| **PR** | [#73](https://github.com/EliasMarine/NetTap/pull/73) |
| **Status** | Done |
| **Severity** | Medium |
| **Date** | 2026-03-02 |

**Symptoms:**
- Setup wizard Step 2 "Identify" button returns HTTP 500 for all Intel I226-V NICs
- Console shows: `nsenter: cannot open /proc/1/ns/net: Permission denied`
- Even without nsenter, `ethtool -p` returns "Operation not supported" on igc driver

**Root Cause:**
Three compounding issues:

1. **`no-new-privileges:true`** from `*security-defaults` YAML anchor blocks `nsenter` — the `setns` syscall requires privilege escalation, which `no-new-privileges` prevents. Error: `Permission denied` on `/proc/1/ns/net`.

2. **`ethtool -p` not supported** on igc driver (kernel 6.8) — the `set_phys_id` callback was added to the igc driver in kernel ~6.11. On 6.8, ethtool returns "Operation not supported".

3. **sysfs LEDs empty** — `CONFIG_IGC_LEDS` was added in kernel 6.9. On 6.8, `/sys/class/leds/igc-*` entries don't exist, so the sysfs fallback also fails.

**Causal Chain:**
```
daemon inherits *security-defaults (no-new-privileges:true)
  → nsenter setns syscall blocked → "Permission denied"
    → ethtool -p falls through to sysfs fallback
      → igc driver on kernel 6.8 has no set_phys_id → "Operation not supported"
        → sysfs LED paths don't exist (CONFIG_IGC_LEDS needs kernel 6.9+)
          → both strategies fail → HTTP 500 error → UI shows error
```

**Fix:**
1. **docker-compose.yml** — Override `security_opt: [no-new-privileges:false]` on daemon service. Security maintained via `cap_drop: ALL` + selective `cap_add` + `read_only: true`.

2. **daemon/api/nic_identify.py** — When both strategies fail, return HTTP 200 with `result: "info"` containing MAC address, PCI slot, and driver name read from sysfs. This gives the user enough information to physically identify the NIC.

3. **web/src/routes/setup/+page.svelte** — Handle `method: "info"` response by displaying MAC/PCI/driver badges instead of an error message.

**Files Changed:**
- `docker/docker-compose.yml` — Override `security_opt` on daemon service
- `daemon/api/nic_identify.py` — Add `_get_nic_info()` helper + info fallback response
- `web/src/routes/setup/+page.svelte` — Handle info fallback in `identifyNic()` + display blinkInfo badges
- `daemon/tests/test_nic_identify.py` — Update tests for 200 info response instead of 500
- `web/src/lib/components/NicIdentify.test.ts` — Add tests for info fallback parsing

**Key Insight:** On consumer hardware (Intel I226-V on kernel 6.8), NIC LED identification is impossible — the driver lacks both `set_phys_id` and sysfs LED support. Rather than showing a cryptic error, provide actionable NIC metadata (MAC/PCI) so the user can cross-reference with `ip link` output or physical labels on the hardware.

---

## Chain 10: Malcolm Capture Services + Proxy Env Vars

### NET-79 — Zeek/Suricata/Arkime crash-loop, filebeat exits, nginx-proxy crash, CyberChef/Dashboards unhealthy

| Field | Value |
|---|---|
| **Linear** | [NET-79](https://linear.app/nettap/issue/NET-79) |
| **Branch** | `fix/malcolm-capture-env-vars` → merged to `develop` |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-02 |

**Symptoms:**
First full Docker stack spin-up on N100. Of 18 containers, 6 were failing:
- **zeek-live, suricata-live, arkime-live**: Crash-loop with `KeyError: 'ENV_EXTRA_TAGS'` from supervisord
- **filebeat**: Exits immediately: `missing field accessing 'output.redis.password'`
- **nginx-proxy**: Unhealthy — `nginx: [emerg] invalid number of arguments in "map" directive in /etc/nginx/conf.d/01_template_variables.conf:21`
- **cyberchef**: Unhealthy — healthcheck hitting `/health` which doesn't exist (static nginx)
- **dashboards**: Healthcheck 404 — checking `/api/status` instead of `/dashboards/api/status`

**Root Cause:**
Five distinct but related issues, all caused by incomplete env var mapping from Malcolm's upstream env files:

1. **Capture services (`EXTRA_TAGS`)** — Malcolm's supervisord configs for zeek/suricata/arkime reference `%(ENV_EXTRA_TAGS)s`. Unlike shell `$VAR` which defaults to empty, supervisord's `%(ENV_*)s` is **strictly fatal** on missing vars. Malcolm's upstream compose loads this via `upload-common.env` file, which we don't use.

2. **Filebeat (`REDIS_PASSWORD`)** — Filebeat's config references `output.redis.password` from env vars. Malcolm's upstream provides this via `redis.env`. We had partial filebeat env from Chain 4 but missed the Redis connection vars.

3. **nginx-proxy (`ARKIME_SSL`, `ROLE_BASED_ACCESS`)** — Malcolm's nginx uses `envsubst` to render `01_template_variables.conf.template`. The template uses env vars as nginx `map` KEYS: `map $ARKIME_SSL $arkime_protocol { ... }`. When env vars are unset, envsubst replaces them with empty string, producing `map  $arkime_protocol {` (1 argument instead of required 2) — invalid nginx syntax. Multiple template vars (`ARKIME_SSL`, `ROLE_BASED_ACCESS`, `DASHBOARDS_URL`, etc.) needed to be set.

4. **CyberChef healthcheck** — CyberChef is static nginx serving a single-page app. It has no `/health` endpoint — the correct healthcheck is just `/`.

5. **Dashboards healthcheck** — Malcolm serves OpenSearch Dashboards at the `/dashboards/` prefix, not at root. The status API is at `/dashboards/api/status`, not `/api/status`.

**Causal Chain:**
```
Malcolm capture images reference %(ENV_EXTRA_TAGS)s in supervisord.conf
  → env var not in compose environment → supervisord KeyError → crash-loop (zeek, suricata, arkime)

Malcolm filebeat config references output.redis.password
  → REDIS_PASSWORD not in compose env → filebeat exits immediately

Malcolm nginx template uses $ARKIME_SSL as map key
  → envsubst replaces unset var with empty → "map  $var {" (1 arg) → nginx parse error → crash

CyberChef healthcheck tests /health
  → static nginx has no /health route → 404 → unhealthy

Dashboards healthcheck tests /api/status
  → Malcolm prefix is /dashboards/ → /api/status returns 404 → unhealthy
```

**Fix:**
Added missing environment variables and fixed healthcheck endpoints in `docker/docker-compose.yml`:

1. **zeek-live, suricata-live, arkime-live** — Added `EXTRA_TAGS: ""`
2. **arkime-live** — Also added `MANAGE_PCAP_FILES: "false"`, `MALCOLM_USERNAME: "${MALCOLM_USERNAME:-admin}"`
3. **filebeat** — Added `REDIS_HOST: "redis"`, `REDIS_PORT: "6379"`, `REDIS_PASSWORD: "${REDIS_PASSWORD:-NetTap_Redis_Secret}"`
4. **nginx-proxy** — Added `ARKIME_SSL: "true"`, `ROLE_BASED_ACCESS: "false"`, `DASHBOARDS_URL: "http://dashboards:5601/dashboards"`, `ARKIME_VIEWER_PORT: "8005"`, `MANAGE_PCAP_FILES: "false"`, `MALCOLM_NETWORK_INDEX_PATTERN: "arkime_sessions3-*"`, `ROLE_ADMIN: "admin"`, `ROLE_CAPTURE_SERVICE: "capture_service"`
5. **cyberchef** — Changed healthcheck from `http://localhost:8443/health` to `http://localhost:8443/`
6. **dashboards** — Changed healthcheck from `http://localhost:5601/api/status` to `http://localhost:5601/dashboards/api/status`

**Files Changed:**
- `docker/docker-compose.yml` — 31 insertions, 2 deletions across 6 services

**Key Insight:** Malcolm's upstream compose relies on `env_file:` directives to load dozens of env vars from `.env` files (`upload-common.env`, `redis.env`, `nginx.env`, `auth-common.env`, etc.). When writing a custom compose that extends Malcolm images, you must either (a) use the same env files, or (b) explicitly replicate every env var that supervisord, nginx templates, and service configs reference. The safest approach is to check Malcolm's upstream compose AND the actual template files inside the images (e.g., `01_template_variables.conf.template`) to find all required vars.

---

## Chain 11: OpenSearch Security Reset + Logstash Bootstrap Deadlock

### Logstash stuck waiting for malcolm_template after --force-recreate

| Field | Value |
|---|---|
| **Linear** | Not yet filed (manual fix applied) |
| **Status** | Workaround applied; needs automation |
| **Severity** | High |
| **Date** | 2026-03-03 |

**Symptoms:**
- After `docker compose up -d --force-recreate`, logstash container is "unhealthy" after 693s
- Logstash uses only 54MB RAM (JVM never started — should use 2GB with `-Xms2g`)
- `ps aux` inside container shows `opensearch_status.sh -t malcolm_template` in a sleep loop
- `curl` to logstash API port 9600 returns empty (API never started)
- `roles_mapping.yml` inside OpenSearch container reverted to empty (only `_meta` header)

**Root Cause:**
`--force-recreate` recreates the OpenSearch container with a fresh filesystem. The `roles_mapping.yml` file (which maps `admin` backend role → `all_access` OpenSearch role) reverts to the image default (empty). The `.opendistro_security` index in the data volume retains the OLD config, but `securityadmin.sh` needs to be re-run to push the updated config file into the index.

Without the role mapping, `malcolm_internal` authenticates (200) but has no authorization (403 on all endpoints). Logstash's `opensearch_status.sh -t malcolm_template` can't check if the template exists → loops forever → logstash JVM never starts → healthcheck fails.

**Causal Chain:**
```
docker compose up --force-recreate
  → OpenSearch container filesystem reset → roles_mapping.yml empty
    → .opendistro_security index still has old config (data volume)
      → securityadmin.sh not re-run → security config stale
        → malcolm_internal gets 403 on all endpoints
          → opensearch_status.sh can't check templates → infinite loop
            → logstash JVM never starts → unhealthy after 693s
              → filebeat depends on logstash healthy → also fails
```

**Fix (manual):**
1. Write `roles_mapping.yml` with `admin → all_access` mapping inside OpenSearch container
2. Run `securityadmin.sh` to push config to `.opendistro_security` index
3. Restart logstash

**TODO:** Automate this — add a startup script or init container that checks if `malcolm_internal` can authenticate AND authorize, and re-runs `securityadmin.sh` if not. This should be part of `deploy-malcolm.sh` or a dedicated healthcheck.

**Key Insight:** `--force-recreate` resets container filesystems but NOT named volumes. Security config lives in TWO places: the config FILES (reset on recreate) and the `.opendistro_security` INDEX (preserved in volume). These can get out of sync. The security plugin reads from the index, not the files — so the files must be pushed to the index via `securityadmin.sh` after any container recreation.

---

### NET-80 — Storage API format mismatch: disk_free_gb missing, wrong types break setup wizard

| Field | Value |
|---|---|
| **Linear** | [NET-80](https://linear.app/nettap/issue/NET-80) |
| **Branch** | develop |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-03 |

**Symptoms:**
- Setup wizard Step 1 "Sufficient disk space (100GB+)" always shows red X despite 1TB+ storage
- Step 4 "Loading storage information" stuck forever, never loads any data

**Root Cause:**
The daemon's `get_status()` returned a completely different format than the frontend's `StorageStatus` TypeScript interface expected. The original NET-67 code fix was documented but never merged to develop — only the docs made it.

| Frontend expects | Daemon returned |
|---|---|
| `disk_free_gb: 1800` (number, GB) | **Not present at all** |
| `disk_total_gb: 1830` (number, GB) | **Not present at all** |
| `disk_usage_percent: 2.3` (number) | `"2.3%"` (string with % sign) |
| `hot_days: 90` (top-level) | `retention.hot_days: 90` (nested) |
| `disk_threshold_percent: 80` (0-100) | `disk_threshold: 0.80` (fraction 0-1) |

Frontend did `storageData.disk_free_gb || 0` → `undefined || 0` = 0 → `0 >= 100` → fail.

**Fix:**
1. Updated daemon's `get_status()` to return absolute GB values via `shutil.disk_usage()`, numeric 0-100 percentages, top-level retention days, and `source: "daemon"`
2. Added `normalizeStorageStatus()` in SvelteKit proxy as safety net for both old and new daemon formats
3. Wrapped `list_indices()` in try/except for OpenSearch-down resilience during setup

**Files Changed:**
- `daemon/storage/manager.py` — Updated `get_status()` response format
- `daemon/tests/test_storage_manager.py` — Updated test for new response fields
- `web/src/routes/api/setup/storage/+server.ts` — Added `normalizeStorageStatus()` transform
- `web/src/routes/api/setup/storage/server.test.ts` — New: 5 tests for normalization

**Key Insight:** TypeScript interfaces define the *desired* shape but don't enforce it at runtime. When a proxy layer passes through external data (like daemon responses), it MUST validate/transform the data to match the interface. The `normalizeStorageStatus()` function handles both old (fraction-based) and new (GB-based) formats, making the system resilient to daemon version differences.

---

## Chain 12: Setup Wizard CSRF + Volume Permissions

### NET-81 — Admin account creation silently fails: CSRF 403 behind nginx + volume write permissions

| Field | Value |
|---|---|
| **Linear** | NET-81 |
| **Branch** | fix/nic-led-identify-fallback |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-03 |

**Symptoms:**
- User enters valid username + password on setup wizard Step 5 and clicks "Complete Setup"
- Nothing happens — no error message, no success message, button returns to default state
- All other wizard steps work (NIC discovery, bridge config, storage API)

**Root Cause (two issues):**

1. **SvelteKit CSRF rejection (403):** Nginx terminates TLS and proxies to `nettap-web:3000` over HTTP. The browser sends `Origin: https://192.168.x.x` on form POST. SvelteKit adapter-node, without `PROTOCOL_HEADER` configured, constructs origin from raw TCP connection: `http://192.168.x.x`. Protocol mismatch → 403 CSRF rejection BEFORE the form action runs.

2. **Volume ownership:** Docker named volume `web-data` mounts at `/var/lib/nettap-web`. The Dockerfile only does `chown nettap:nettap /app`, not the data dir. Docker creates the mount point as root. Even if CSRF passed, `writeFileSync('/var/lib/nettap-web/users.json')` would throw EACCES.

**Why "nothing happens":** SvelteKit's `use:enhance` callback receives the 403 as `result.type === 'error'`, not as a form action failure. The default `update()` sets `$page.error` but the form template only checks `form?.error` (set by `fail()` action responses). No visible error → user sees no feedback.

**Causal Chain:**
```
Browser sends Origin: https://192.168.x.x (TLS terminated by nginx)
  → nginx proxies to http://nettap-web:3000 (plain HTTP internally)
    → SvelteKit has no PROTOCOL_HEADER → derives origin from raw HTTP
      → Origin comparison: https:// vs http:// → MISMATCH
        → SvelteKit returns 403 CSRF before form action runs
          → use:enhance receives error result, not action failure
            → form?.error not set → no visible feedback → "nothing happens"
```

**Fix:**
1. **docker-compose.yml** — Added `PROTOCOL_HEADER: "x-forwarded-proto"` and `HOST_HEADER: "host"` to nettap-web environment. SvelteKit now trusts nginx's proxy headers, constructs correct `https://` origin.
2. **Dockerfile.web** — Added `mkdir -p /var/lib/nettap-web && chown nettap:nettap /var/lib/nettap-web` before `USER nettap`. Docker named volume inherits correct ownership on first creation.
3. **+page.svelte** — Added `result` parameter to `use:enhance` async callback. Non-action errors (CSRF, 500, etc.) now surface as `clientError` with status code.

**Files Changed:**
- `docker/docker-compose.yml` — Added PROTOCOL_HEADER + HOST_HEADER env vars to nettap-web
- `docker/Dockerfile.web` — mkdir + chown /var/lib/nettap-web before USER switch
- `web/src/routes/setup/+page.svelte` — Enhanced error handling in use:enhance callback

**Key Insight:** SvelteKit adapter-node behind a reverse proxy that terminates TLS MUST have `PROTOCOL_HEADER` set to trust `X-Forwarded-Proto`. Without it, the CSRF check compares `https://` (browser) with `http://` (raw connection) and silently rejects all form POSTs. This is invisible because `use:enhance` doesn't surface non-action errors by default.

---

## Chain 13: OpenSearch .keyword Suffix + Log Search Format + CSP Fonts

### Issue 13a — All dashboard aggregations fail with 400 error

| Field | Value |
|---|---|
| **Branch** | `phase-4/webui-v2` |
| **PR** | #92 |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-05 |
| **Environment** | N100 production hardware |

**Symptoms:**
Every dashboard page (traffic summary, devices, protocols, top talkers, categories) returned empty data or 400 errors. OpenSearch returned: `"Text fields are not optimised for operations that require per-document field data like aggregations and sorting, so these operations are disabled by default."` on all `terms` aggregation queries.

**Root Cause:**
Malcolm maps all text fields (source.ip, network.transport, destination.ip, network.protocol, zeek.dns.query, etc.) as **text+keyword multi-fields** in OpenSearch. The `text` type supports full-text search but NOT aggregations. Any `terms` aggregation must use the `.keyword` subfield (e.g., `source.ip.keyword`, `network.transport.keyword`). Without the `.keyword` suffix, OpenSearch refuses the aggregation with a 400 error.

**Causal Chain:**
```
Malcolm indexes all fields as text+keyword multi-fields
  → daemon queries use bare field names (source.ip, network.transport)
    → OpenSearch tries terms aggregation on text field → 400 error
      → ALL dashboard pages show empty/error states
```

**Fix:**
Added `.keyword` suffix to all 22 field references used in `terms` aggregations across 6 daemon files:
- `daemon/api/traffic.py` — source.ip.keyword, destination.ip.keyword, network.transport.keyword, network.protocol.keyword
- `daemon/api/devices.py` — source.ip.keyword, destination.ip.keyword, source.mac.keyword, destination.mac.keyword
- `daemon/api/alerts.py` — rule.category.keyword, rule.name.keyword, source.ip.keyword, destination.ip.keyword
- `daemon/api/risk.py` — source.ip.keyword, destination.ip.keyword, rule.category.keyword
- `daemon/services/traffic_classifier.py` — network.protocol.keyword, destination.port, zeek.dns.query.keyword
- `daemon/services/device_fingerprint.py` — zeek.dns.query.keyword, zeek.http.user_agent.keyword, source.ip.keyword

### Issue 13b — Log search API returns flat docs instead of _source wrapper

| Field | Value |
|---|---|
| **Branch** | `phase-4/webui-v2` |
| **PR** | #92 |
| **Status** | Done |
| **Severity** | Medium |
| **Date** | 2026-03-05 |

**Symptoms:**
Log Explorer page showed empty rows or crashed when trying to access log fields. The frontend expected documents in `{_id, _source: {...}}` format (standard OpenSearch hit structure), but the daemon API was returning flattened documents like `{_id, "source.ip": "...", "destination.ip": "..."}`.

**Root Cause:**
The `daemon/api/logs.py` endpoint was flattening the `_source` wrapper when serializing search results. The frontend `LogExplorer` component destructured `hit._source` to access fields, which returned `undefined` on flat docs.

**Fix:**
Updated `daemon/api/logs.py` to preserve the `{_id, _source: {...}}` wrapper format that the frontend expects. Added test coverage in `daemon/tests/test_logs_api.py`.

### Issue 13c — CSP blocking Google Fonts

| Field | Value |
|---|---|
| **Branch** | `phase-4/webui-v2` |
| **PR** | #92 |
| **Status** | Done |
| **Severity** | Low |
| **Date** | 2026-03-05 |

**Symptoms:**
Dashboard rendered with fallback system fonts instead of the intended Inter/JetBrains Mono web fonts. Browser console showed Content-Security-Policy violations for `fonts.googleapis.com` and `fonts.gstatic.com`.

**Root Cause:**
The `docker/nginx.conf` Content-Security-Policy header did not include `fonts.googleapis.com` in the `style-src` directive or `fonts.gstatic.com` in the `font-src` directive.

**Fix:**
Updated `docker/nginx.conf` CSP header to allow:
- `style-src`: added `fonts.googleapis.com`
- `font-src`: added `fonts.gstatic.com`

**Files Changed (all three issues):**
- `daemon/api/traffic.py` — .keyword suffix on aggregation fields
- `daemon/api/devices.py` — .keyword suffix on aggregation fields
- `daemon/api/alerts.py` — .keyword suffix on aggregation fields
- `daemon/api/risk.py` — .keyword suffix on aggregation fields
- `daemon/services/traffic_classifier.py` — .keyword suffix on aggregation fields
- `daemon/services/device_fingerprint.py` — .keyword suffix on aggregation fields
- `daemon/api/logs.py` — _source wrapper format fix
- `daemon/tests/test_logs_api.py` — test coverage for _source format
- `docker/nginx.conf` — CSP font allowlisting

---

## Chain 14: Logstash Index Pattern Env Vars Missing

### Logstash format_index_string.rb crashes — 89K+ events misindexed

| Field | Value |
|---|---|
| **Commit** | `717bd24` |
| **Branch** | `phase-4/webui-v2` |
| **Status** | Done |
| **Severity** | Urgent |
| **Date** | 2026-03-05 |
| **Environment** | N100 production hardware |

**Symptoms:**
- Logstash logs flooded with `NoMethodError: undefined method 'delete_suffix' for nil:NilClass` from Malcolm's `format_index_string.rb` filter plugin
- 89,000+ events (including ALL Suricata events) landed in a broken literal index named `%{[@metadata][malcolm_opensearch_index]}` instead of the correct `arkime_sessions3-YYMMDD`
- Suricata event count in `arkime_sessions3-*` was 0 despite Suricata generating alerts
- Dashboard showed zero Suricata alerts despite the IDS engine running correctly

**Root Cause:**
Malcolm's `format_index_string.rb` Logstash filter plugin constructs the destination index name using two environment variables:
- `MALCOLM_NETWORK_INDEX_PATTERN` — the base index pattern (e.g., `arkime_sessions3-*`)
- `MALCOLM_NETWORK_INDEX_SUFFIX` — the date suffix format (e.g., `%{%y%m%d}`)

The plugin calls `.delete_suffix('*')` on the pattern value to strip the wildcard and construct the final index name (e.g., `arkime_sessions3-260305`). When the env var is missing, Ruby's `ENV.fetch()` returns `nil`, and calling `.delete_suffix` on `nil` raises `NoMethodError`.

These 4 env vars (`MALCOLM_NETWORK_INDEX_PATTERN`, `MALCOLM_NETWORK_INDEX_SUFFIX`, `MALCOLM_OTHER_INDEX_PATTERN`, `MALCOLM_OTHER_INDEX_SUFFIX`) were set on the `nginx-proxy` service (added in Chain 10 / NET-79 for template rendering) but were never added to the `logstash` service. Malcolm's upstream compose loads these from `opensearch.env` via `env_file:`, which we don't use.

When the Ruby filter crashed, Logstash's error handling set `[@metadata][malcolm_opensearch_index]` to the literal string `%{[@metadata][malcolm_opensearch_index]}` (unexpanded). The OpenSearch output plugin then created an index with that literal name — a valid index name that silently swallowed all events.

**Causal Chain:**
```
Malcolm's format_index_string.rb reads MALCOLM_NETWORK_INDEX_PATTERN from ENV
  → env var not set on logstash service (only on nginx-proxy)
    → ENV.fetch returns nil → .delete_suffix('*') on nil → NoMethodError
      → Logstash error handler sets index to literal "%{[@metadata][malcolm_opensearch_index]}"
        → OpenSearch creates index with that literal name
          → 89K+ events land in broken index → 0 events in arkime_sessions3-*
            → ALL dashboard Suricata data missing
```

**Fix:**
Added 4 env vars to the logstash service in `docker/docker-compose.yml`:
```yaml
MALCOLM_NETWORK_INDEX_PATTERN: "arkime_sessions3-*"
MALCOLM_NETWORK_INDEX_SUFFIX: "%{%y%m%d}"
MALCOLM_OTHER_INDEX_PATTERN: "malcolm_beats_*"
MALCOLM_OTHER_INDEX_SUFFIX: "%{%y%m%d}"
```

**Post-fix recovery:**
Reindexed 34,992 documents from the broken literal index to correct `arkime_sessions3-*` indices using the OpenSearch `_reindex` API. Deleted the broken index afterward.

**Verification:**
- Zero Ruby exceptions in logstash logs after fix
- Suricata events flowing to correct `arkime_sessions3-*` index (count went from 0 to 20+ within minutes)
- Dashboard Suricata alert panels populated correctly

**Files Changed:**
- `docker/docker-compose.yml` — Added 4 MALCOLM_*_INDEX env vars to logstash service

**Key Insight:** Malcolm's Logstash plugins reference env vars from multiple `.env` files (`opensearch.env`, `upload-common.env`, etc.). When a service needs an env var, check ALL Malcolm services that use that image — the same env vars may be needed by logstash, nginx-proxy, and filebeat independently. An env var set on one service does NOT propagate to others. The `format_index_string.rb` crash was particularly insidious because Logstash didn't stop — it silently misindexed 89K+ events into a garbage index name that looks like an unexpanded variable reference.

---

## Chain 15: pcap-capture Restart Loop + nginx-proxy Healthcheck + Boot Persistence

This chain covers 5 deployment issues discovered during N100 hardware testing on 2026-03-07.

### Fix 1: pcap-capture usermod restart loop

| Field | Value |
|---|---|
| **Commit** | `65e31cf` |
| **Branch** | `phase-4/webui-v2` |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-07 |
| **Environment** | N100 production hardware |

**Symptom:** `nettap-pcap-capture` container restart-looping. Logs showed: `usermod: user root is currently used by process 1`.

**Root Cause:** Malcolm's `docker-uid-gid-setup.sh` entrypoint tries to `usermod -u 1000 root`, but root is PID 1 inside the container. The `usermod` command refuses to change the UID of a user that owns the init process. This script is unnecessary when `PUSER=root` because no UID remapping is needed — we run as root for netsniff-ng raw packet capture capabilities.

**Fix:** Set `PUSER=root` environment variable instead of removing the entrypoint script from the chain. With `PUSER=root`, Malcolm's `docker-uid-gid-setup.sh` detects no remapping is needed and skips the `usermod` call entirely.

**Files Changed:**
- `docker/docker-compose.yml` — pcap-capture entrypoint/environment section

**Key Insight:** Malcolm's `docker-uid-gid-setup.sh` checks `PUSER` and only runs `usermod` if the target user is not already root. Setting `PUSER=root` is the correct way to skip UID remapping, rather than removing the entrypoint script from the chain.

---

### Fix 2: nginx-proxy healthcheck targeting broken vhost

| Field | Value |
|---|---|
| **Commit** | `65e31cf` |
| **Branch** | `phase-4/webui-v2` |
| **Status** | Done |
| **Severity** | Normal |
| **Date** | 2026-03-07 |
| **Environment** | N100 production hardware |

**Symptom:** `nettap-nginx-proxy` marked unhealthy, restart-looping. Logs showed: `host not found in upstream "arkime:8005"`.

**Root Cause:** Malcolm's baked-in `nginx.conf` references upstream `arkime:8005`, but `arkime-live` uses `network_mode: host` so Docker DNS cannot resolve the `arkime` hostname. The `:443` vhost fails to load, but the `:9200` OpenSearch proxy vhost works correctly. The healthcheck was testing `:443`, which was the failing vhost.

**Fix:**
1. Changed healthcheck to test `:9200` (OpenSearch proxy — the vhost that actually works) instead of `:443` (broken arkime vhost)
2. Removed the `:443` port binding since NetTap doesn't use it (nettap-nginx handles all user-facing HTTPS)
3. Updated comments to clarify nginx-proxy's actual role: OpenSearch reverse proxy for host-networked containers

**Files Changed:**
- `docker/docker-compose.yml` — nginx-proxy section (healthcheck, ports, comments)

**Key Insight:** nginx-proxy's real purpose in NetTap is to provide an OpenSearch proxy endpoint for containers that use `network_mode: host` (like arkime-live). The `:443` vhost with arkime upstream is a Malcolm feature we don't use. Health checks should test the service's actual function, not a baked-in feature that's broken in our topology.

---

### Fix 3: nettap.service boot persistence

| Field | Value |
|---|---|
| **Branch** | `phase-4/webui-v2` |
| **Status** | Done |
| **Severity** | Normal |
| **Date** | 2026-03-07 |
| **Environment** | N100 production hardware |

**Symptom:** After a reboot, the Docker Compose stack did not start automatically. Manual `docker compose up -d` was required each time.

**Root Cause:** No systemd service unit existed to auto-start the NetTap Docker stack on boot.

**Fix:** Created `scripts/remote/nettap.service` — a systemd unit that runs `docker compose -f /opt/nettap/docker/docker-compose.yml up -d` after `docker.service` starts. Installed on the N100 via `systemctl enable nettap.service`.

**Files Changed:**
- `scripts/remote/nettap.service` (new file)

---

### Fix 4: nettap-nginx SSL key permission denied

| Field | Value |
|---|---|
| **Branch** | `phase-4/webui-v2` |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-07 |
| **Environment** | N100 production hardware |

**Symptom:** `nettap-nginx` crash-looping with: `cannot load certificate key "/etc/nginx/ssl/nettap.key": Permission denied`.

**Root Cause:** The SSL key file had `0600` permissions (owner-only read/write), but the nginx container drops to a non-root user. Combined with `no-new-privileges` and `read_only: true` security options, the nginx worker process could not read the key.

**Fix:** `chmod 644` on the SSL key file on the device. The key is self-signed and local-only (LAN access), so relaxed permissions are acceptable.

**Key Insight:** Containers with `no-new-privileges` + user drop need files readable by the target user. Self-signed SSL keys on a local-only appliance don't require strict `0600` permissions — `0644` is sufficient since the threat model is LAN-only.

---

### Fix 5: OpenSearch security not initialized after recreate

| Field | Value |
|---|---|
| **Branch** | `phase-4/webui-v2` |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-07 |
| **Environment** | N100 production hardware |

**Symptom:** OpenSearch showing `Security not initialized (run securityadmin)` after container recreation. All services using `malcolm_internal` get 403.

**Root Cause:** Every time the OpenSearch container is recreated, the `roles_mapping.yml` reverts to empty (the image default). The `.opendistro_security` index may also need re-initialization. This is the same root cause as Chain 11 but now has a reusable fix script.

**Fix:** Ran security bootstrap (write `roles_mapping.yml` + run `securityadmin.sh`). Created `scripts/remote/fix-opensearch.sh` as a reusable script for future occurrences.

**Files Changed:**
- `scripts/remote/fix-opensearch.sh` (new file)

**Key Insight:** This is a recurring issue (Chain 11 documented it first). The fix script should be part of the standard deployment workflow. TODO: automate in `nettap.service` post-start hook or an init container.

---

### Fix 6: netsniff-ng EPERM due to file capabilities exceeding bounding set

| Field | Value |
|---|---|
| **Branch** | `phase-4/webui-v2` |
| **Status** | Done |
| **Severity** | High |
| **Date** | 2026-03-07 |
| **Environment** | N100 production hardware |

**Symptom:** netsniff-ng in pcap-capture container gets EPERM on exec. supervisord logs show: `couldn't exec /usr/sbin/netsniff-ng: EPERM`.

**Root Cause:** The netsniff-ng binary ships with file capabilities `cap_net_admin,cap_net_raw,cap_ipc_lock,cap_sys_admin=eip`. `cap_sys_admin` is NOT in the container's bounding set (cap_add only has IPC_LOCK, SYS_RESOURCE, NET_ADMIN, NET_RAW, SYS_NICE). The Linux kernel blocks exec of binaries whose file capabilities exceed the bounding set. The entrypoint runs `setcap -r` to strip file caps, but `setcap` itself needs `CAP_SETFCAP`, which Docker doesn't grant by default — so `setcap -r` fails silently (was hidden by `2>/dev/null`).

**Fix (attempt 1 — FAILED):** Added `SETFCAP` to pcap-capture's `cap_add` list in `docker/docker-compose.yml`. This allows `setcap -r` to run (exit 0), but on Docker's overlay2 filesystem the xattrs from the image layer persist — `getcap` still shows the original file capabilities after `setcap -r` returns success. The removal writes to the writable upper layer but does NOT override the lower (image) layer's xattrs.

**Fix (attempt 2 — WORKING):** Added `SYS_ADMIN` directly to pcap-capture's `cap_add`. Since netsniff-ng's file caps include `cap_sys_admin=eip`, the bounding set now covers all file caps, and exec succeeds. Removed the useless `setcap -r` from the entrypoint. This is acceptable because pcap-capture already runs as root with `network_mode: host` — `SYS_ADMIN` doesn't meaningfully expand the attack surface.

**Files Changed:**
- `docker/docker-compose.yml` — Added `SYS_ADMIN` to pcap-capture `cap_add` section, removed `SETFCAP` (useless on overlay2), removed `setcap -r` from entrypoint

**Key Insight:** `setcap -r` is unreliable on Docker overlay2 filesystems. It returns exit 0 (appears to succeed) but `getcap` still shows the original file capabilities — xattrs from image layers persist through the overlay and the writable layer's "removal" doesn't override them. **Never rely on runtime `setcap` in Docker containers.** Instead, ensure the container's bounding set covers all file capabilities (add the missing caps to `cap_add`), or build a custom image without file caps. The SETFCAP approach was a red herring — it let `setcap -r` run without error, but the underlying overlay2 limitation made the operation a no-op.

---

## Key Files Modified

These files were touched repeatedly across the 16+ PRs. Check their current state before making changes.

| File | PRs | Current State |
|---|---|---|
| `docker/docker-compose.yml` | #54-#73, NET-79, NET-81, NET-95, 717bd24, 65e31cf | Logstash: PUSER_PRIV_DROP=false, supervisord.conf mount, LS_JAVA_OPTS includes -Xss8m, **MALCOLM_NETWORK_INDEX_PATTERN/SUFFIX + MALCOLM_OTHER_INDEX_PATTERN/SUFFIX env vars**. Redis: list-form command (sh -c). API: explicit gunicorn command. Filebeat: upload-common + Redis env vars. Daemon: full /sys mount + healthcheck + no-new-privileges:false + **OPENSEARCH_NETWORK_INDEX env var**. Capture services: EXTRA_TAGS + MANAGE_PCAP_FILES + **PUSER=root (skip usermod)** + **SYS_ADMIN cap_add (covers netsniff-ng file caps — setcap -r unreliable on overlay2)**. nginx-proxy: ARKIME_SSL, ROLE_BASED_ACCESS, DASHBOARDS_URL, ARKIME_VIEWER_PORT, **healthcheck on :9200 (not :443), :443 port removed**. CyberChef healthcheck: `/`. Dashboards healthcheck: `/dashboards/api/status`. **Web: PROTOCOL_HEADER + HOST_HEADER for CSRF behind nginx.** |
| `docker/Dockerfile.web` | NET-81 | mkdir + chown `/var/lib/nettap-web` before USER switch. Volume inherits correct ownership. npm/yarn/corepack stripped for CVE mitigation. |
| `daemon/storage/manager.py` | NET-80 | `get_status()` returns `disk_total_gb`, `disk_free_gb`, numeric percentages, top-level retention days. Matches frontend `StorageStatus` interface. |
| `web/src/routes/api/setup/storage/+server.ts` | NET-80 | `normalizeStorageStatus()` transforms old or new daemon format to frontend interface. Safety net for version mismatches. |
| `web/src/hooks.server.ts` | #71 | PUBLIC_PATHS includes `/api/setup`; first-run redirect skips `/api/setup/*` |
| `daemon/api/nic_identify.py` | #68, #73 | Graceful info fallback when LED blink unavailable; returns MAC/PCI/driver |
| `config/logstash/supervisord.conf` | #62, #63, #66, #67 | fix-perms (chown + -Xss8m inject + supervisorctl start logstash) + logstash (autostart=false, user=logstash) |
| `config/logstash/jvm.options.d/99-nettap.options` | #65 | DEAD FILE — Logstash ignores jvm.options.d/ (Elasticsearch-only). Volume mount removed in #66. |
| `scripts/install/deploy-malcolm.sh` | #54, #55, #60 | bootstrap_opensearch_security() + bootstrap_index_templates() + staged startup |
| `daemon/api/traffic.py` | NET-95, PR #92 | All queries use `NETWORK_INDEX` (arkime_sessions3-*) + ECS field names + event.provider/dataset filters. **All aggregation fields use .keyword suffix.** |
| `daemon/api/alerts.py` | NET-95, PR #92, cf960e4+4c26c26+5b1b4d4, 4009faf | Suricata alerts query `NETWORK_INDEX` with `event.provider: suricata` + `event.dataset: alert` + ECS fields. **Aggregation fields use .keyword suffix.** `_normalize_alert_source()` merges ECS/Malcolm/raw field paths. IP filter (`source.ip` OR `destination.ip`) via `ip` query param. **4 new aggregation endpoints: /api/alerts/timeline (date_histogram), /api/alerts/top-signatures (terms), /api/alerts/top-ips (src/dest), /api/alerts/categories. 8 endpoints total. _ALLOWED_INTERVALS, _SEVERITY_MAP constants.** |
| `daemon/api/lookup.py` | 5b1b4d4 | NEW: WHOIS + DNS lookup endpoints. Async subprocess for whois, thread executor for socket DNS. IP validation, 15s timeout, parsed field extraction. |
| `daemon/api/devices.py` | NET-95, PR #92 | Device queries use `NETWORK_INDEX` + ECS fields. **Aggregation fields use .keyword suffix.** |
| `daemon/api/risk.py` | NET-95, PR #92 | Risk scoring uses `NETWORK_INDEX` + ECS fields. **Aggregation fields use .keyword suffix.** |
| `daemon/services/traffic_classifier.py` | NET-95, PR #92 | Category classification uses `NETWORK_INDEX` + ECS fields. **Aggregation fields use .keyword suffix.** |
| `daemon/services/device_fingerprint.py` | NET-95, PR #92 | Fingerprinting uses `NETWORK_INDEX` + ECS fields. **Aggregation fields use .keyword suffix (zeek.dns.query.keyword, etc.).** |
| `daemon/services/nl_search.py` | NET-95 | NL search uses `NETWORK_INDEX` + ECS fields |
| `daemon/api/logs.py` | NET-100, PR #92 | Log Search API — generic Zeek/Suricata browser. **Fixed _source wrapper format for frontend compatibility.** |
| `docker/nginx.conf` | PR #92 | CSP header updated to allow fonts.googleapis.com (style-src) and fonts.gstatic.com (font-src) |
| `daemon/api/opensearch_cluster.py` | NET-100 | OpenSearch cluster visibility API |
| `daemon/api/logstash.py` | NET-100 | Logstash monitoring API |
| `web/src/lib/styles/global.css` | NET-100 | Complete CSS redesign (Datadog/Grafana aesthetic) |
| `web/src/routes/+layout.svelte` | NET-100 | New layout shell + navigation |
| `web/src/routes/logs/+page.svelte` | NET-100, 5b1b4d4 | NEW: Log Explorer page. **IPAddress component added for IP columns.** |
| `web/src/routes/devices/+page.svelte` | 5b1b4d4 | **IPAddress component added in 3 locations** (table row, detail panel, connections dest IP). |
| `web/src/routes/alerts/+page.svelte` | 5b1b4d4, 4009faf | **Full redesign (4009faf):** hero stats, SVG timeline chart with hover tooltips, two-col signatures+categories, two-col attacked+source IPs with copy buttons, sortable table, time range pills, severity filter pills, Promise.allSettled, initialized guard. **Previous:** IP filter support via `ip` URL param. |
| `web/src/lib/api/alerts.ts` | 4009faf | **4 new fetch functions** (getAlertTimeline, getAlertTopSignatures, getAlertTopIps, getAlertCategories), 7 new types, 3 formatting helpers (formatNumber, severityLabel, severityBadgeClass). |
| `web/src/lib/api/alerts.test.ts` | 4009faf | **25 total tests** (18 new) covering all 4 new API functions + formatting helpers. |
| `web/src/routes/api/alerts/timeline/+server.ts` | 4009faf | NEW: SvelteKit proxy route for `/api/alerts/timeline`. |
| `web/src/routes/api/alerts/top-signatures/+server.ts` | 4009faf | NEW: SvelteKit proxy route for `/api/alerts/top-signatures`. |
| `web/src/routes/api/alerts/top-ips/+server.ts` | 4009faf | NEW: SvelteKit proxy route for `/api/alerts/top-ips`. |
| `web/src/routes/api/alerts/categories/+server.ts` | 4009faf | NEW: SvelteKit proxy route for `/api/alerts/categories`. |
| `web/src/lib/components/IPAddress.svelte` | 5b1b4d4 | **8 menu items** (was 5). Fixed filter from/to bug. Added WHOIS, DNS, View Alerts actions. |
| `web/src/lib/components/ContextMenu.svelte` | 5b1b4d4 | **3 new icons** (whois, dns, alert). |
| `web/src/routes/lookup/whois/[ip]/+page.svelte` | 5b1b4d4 | NEW: WHOIS lookup page with parsed fields + raw output toggle. |
| `web/src/routes/lookup/dns/[ip]/+page.svelte` | 5b1b4d4 | NEW: DNS lookup page with reverse/forward DNS display. |
| `web/src/routes/infrastructure/+page.svelte` | NET-100 | NEW: Infrastructure page |
| `scripts/remote/nettap.service` | Chain 15 | NEW: systemd unit for boot persistence — starts Docker stack after docker.service |
| `scripts/remote/fix-opensearch.sh` | Chain 15 | NEW: reusable OpenSearch security bootstrap script |
| `scripts/remote/fix-pcap-and-proxy.sh` | Chain 15 | NEW: deploy script for pcap-capture + nginx-proxy fixes |
| `web/src/routes/api/[...path]/+server.ts` | Chain 16.15 | NEW: Catch-all SvelteKit proxy — forwards unhandled `/api/*` requests to daemon via `daemonFetch()`. Lowest priority (existing explicit routes take precedence). |
| `web/src/lib/api/changelog.ts` | Chain 16.15 | Removed `VITE_API_URL`, uses relative `/api/` paths |
| `web/src/lib/api/certificates.ts` | Chain 16.15 | Removed `VITE_API_URL`, uses relative `/api/` paths |
| `web/src/lib/api/capture.ts` | Chain 16.15 | Removed `VITE_API_URL`, uses relative `/api/` paths |
| `web/src/lib/api/devices-registry.ts` | Chain 16.15 | Removed `VITE_API_URL`, uses relative `/api/` paths |
| `web/src/lib/api/notification-hub.ts` | Chain 16.15 | Removed `VITE_API_URL`, uses relative `/api/` paths |
| `web/src/routes/setup/+page.svelte` | Chain 16.15 | Removed `VITE_API_URL`, uses relative `/api/` paths |
| `daemon/api/pcap.py` | Chain 17 | Added `GET /api/pcap/download-file` endpoint for per-file PCAP download. |
| `daemon/services/pcap_search.py` | Chain 17 | Fixed filter validation: removed `|` and `&` from forbidden chars (safe with `create_subprocess_exec`). |
| `web/src/routes/pcap/+page.svelte` | Chain 17 | Fixed quick filters from BPF to display filter syntax. Added Download buttons, auto-scroll to preview, sortable columns. |
| `web/src/lib/api/pcap.ts` | Chain 17 | Added `downloadPcapFile()` API client function for per-file download. |
| `daemon/services/dns_analytics.py` | Chain 17 | Remapped all field names: `dns.*` → `zeek.dns.*`. Fixed RTT conversion: `÷1M` → `×1000`. |
| `web/src/routes/dns/+page.svelte` | Chain 17, Chain 18 | Complete redesign: interactive SVG timeline, sortable tables, time range pills, per-device DNS panel, empty states. **Chain 18: copy button CSS fix (1.25rem, accent-blue).** |
| `web/src/routes/pcap/+page.svelte` | Chain 17, Chain 18 | Chain 17: BPF→display filter, download buttons, auto-scroll, sortable columns. **Chain 18: Full redesign — hero stats, capture timeline SVG, quick filter chips, packet preview panel, protocol breakdown, two-column file browser, cross-section linking, time range pills.** |
| `web/src/lib/api/pcap.ts` | Chain 17, Chain 18 | Chain 17: `downloadPcapFile()`. **Chain 18: Added `formatRelativeTime`, `PROTO_FILTER_MAP` helpers.** |
| `daemon/api/logs.py` | NET-100, 1f85e8e+245d4af+8e09867 | Log Explorer: .keyword suffix on 6 agg fields, `track_total_hits: True`, `_EXCLUDE_ALERTS_FILTER` (must_not event.dataset:alert), `_EXCLUDE_DNS_NOISE` (must_not zeek.dns.query:pcap-monitor). Applied to all 6 agg endpoints + search endpoint. |
| `web/src/routes/logs/+page.svelte` | NET-100, 6c70af4 | Log Explorer: text-white stat fix, SVG→HTML tooltip overlay (flicker fix), removed 'alert' from PROTOCOL_KEYS. |
| `web/src/lib/api/logs.ts` | NET-100, 6c70af4 | `protocolColor()` changed from CSS vars to bold hex values (#00b8d4, #00e676, #ff9100, #aa66ff, #ffd600, #ff4081, #18ffff). |
| `web/DESIGN-SYSTEM.md` | 0e10121 | NEW: Canonical design reference — CSS variables, component patterns, layout rules, 10 mandatory rules. Reference impl: Log Explorer page. |
| `web/src/lib/utils/tshark-filter.ts` | 7912342 | NEW: Extracted `buildTSharkFilter`, `getField`, `asString`. Handles TCP/UDP/ICMP/ICMPv6/IPv4/IPv6. |
| `web/src/lib/utils/tshark-filter.test.ts` | 7912342 | NEW: 18 tests — TCP, UDP, ICMP, ICMPv6, IPv4, IPv6, mixed addressing, OpenSearch array values. |
| `web/src/routes/connections/+page.svelte` | 7912342 | TShark filter fix: imports from tshark-filter.ts utility, removed inline getField/asString/buildTSharkFilter. |
| `scripts/remote/deploy-log-explorer.sh` | 1ce47e3 | Deploy script: checks OpenSearch health before deploying, restarts if unhealthy, waits up to 180s, runs security bootstrap as fallback. |
| `tests/scripts/test_compose_validation.bats` | #54, #56-#62 | 119+ tests, validates security per Malcolm vs NetTap services |
| `tests/scripts/test_deploy_malcolm.bats` | #54, #55, #60 | Template bootstrap + security bootstrap + startup ordering tests |

---

## Lessons Learned (Global)

### Malcolm Architecture Constraints
1. **Malcolm's entrypoint is incompatible with `no-new-privileges`** — it uses `su` (setuid), which Docker's `no-new-privileges` blocks. Must use Docker defaults for Malcolm services.
2. **Malcolm's `su` heredoc breaks `/dev/fd/` access** — kernel procfs restriction makes fd entries inaccessible after UID change. Cannot be fixed without controlling how supervisord runs.
3. **Malcolm's security plugin has 2 layers** — `internal_users.yml` (auth) + `roles_mapping.yml` (authz). Both must be configured AND pushed via `securityadmin.sh`.
4. **Fresh deployments have circular template dependencies** — must bootstrap templates before logstash starts.
41. **`--force-recreate` resets container filesystems but NOT volumes** — security config lives in TWO places: config FILES (reset on recreate) and the `.opendistro_security` INDEX (preserved in volume). These get out of sync. Must re-run `securityadmin.sh` after any `--force-recreate` that touches OpenSearch.
42. **`roles_mapping.yml` is dynamically generated, not in git** — `deploy-malcolm.sh` writes it at deploy time. The image default is empty (just `_meta` header). If the container is recreated without running the deploy script, all service accounts lose authorization (403 on everything).

### Docker / Container Gotchas
5. **`su` failing silently (exit 0)** is extremely hard to debug — the process simply never starts.
6. **Docker creates missing file bind-mount sources as directories** — always pre-create files before container start.
7. **`docker compose up -d` blocks on `service_healthy`** — bootstrap logic that runs after `up -d` will deadlock if the healthcheck depends on that bootstrap.
8. **`id -u` under sudo returns 0** — use `SUDO_UID` or `stat` for real user detection.
35. **`no-new-privileges` blocks `nsenter`** — the `setns` syscall used by nsenter requires privilege escalation. If a container needs nsenter (e.g., to access host network namespace), it must override `security_opt: [no-new-privileges:false]`. Maintain security via other mechanisms (cap_drop, read_only).

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
43. **SvelteKit adapter-node CSRF requires `PROTOCOL_HEADER` behind TLS-terminating proxies** — without it, SvelteKit compares `https://` (browser Origin) with `http://` (raw TCP) and silently rejects all form POSTs with 403. The `use:enhance` callback doesn't surface non-action errors by default — no visible feedback to the user.
44. **Docker named volumes inherit mount point ownership from the image** — if the Dockerfile doesn't `mkdir + chown` the mount point path before switching to a non-root `USER`, the volume is created as root and the app can't write to it. Always create and chown data dirs in the Dockerfile.

### sysfs / Filesystem Gotchas
26. **`/sys/class/*` directories are symlink farms** — entries like `/sys/class/net/eth0` are symlinks to `/sys/devices/pci.../net/eth0`. Mounting only a `/sys/class/` subdirectory brings the symlinks but not their targets. Always mount all of `/sys:ro` and overlay writable paths as needed.
27. **Directory listing succeeds even with broken symlinks** — `iterdir()` / `ls` shows entries, but reading files inside those entries fails silently with empty strings (OSError caught by sysfs read helpers). This makes the bug subtle: the daemon appears to work (returns valid JSON with interface names) but all metadata is empty.
34. **Kernel driver features have version requirements** — igc `set_phys_id` (ethtool -p) requires kernel ~6.11, and `CONFIG_IGC_LEDS` requires kernel 6.9. Always provide a graceful fallback when hardware/driver features may be unavailable.

### Malcolm Env / Template Rendering (NEW — Chain 10)
36. **Malcolm nginx templates use `envsubst` with vars as map keys** — `map $ARKIME_SSL $arkime_protocol { ... }`. When `$ARKIME_SSL` is unset, envsubst replaces it with empty string, producing `map  $arkime_protocol {` (1 argument) which is invalid nginx syntax. The error message (`invalid number of arguments in "map" directive`) doesn't mention the env var — you must read the template source to find the culprit.
37. **Malcolm env files are not optional** — Malcolm's upstream compose uses `env_file:` to load `.env` files (upload-common.env, redis.env, nginx.env, etc.). Each contains dozens of vars referenced by supervisord, nginx templates, and service configs. Missing even one can cause crash-loops, parse errors, or silent misconfiguration.
38. **Always check Malcolm's template files inside the image** — the compose file doesn't show which env vars nginx-proxy needs. You must check the actual template files (e.g., `nginx/templates/01_template_variables.conf.template`) to find all `$VAR` references that envsubst will expand.
39. **CyberChef has a `/health` endpoint** — our Dockerfile.cyberchef adds a `/health` endpoint returning JSON. Use `/health` for healthchecks, not `/` (which returns full HTML and can confuse `wget --spider`).
40. **Malcolm Dashboards uses a URL prefix** — OpenSearch Dashboards serves at `/dashboards/`, not at root. API endpoints like `/api/status` must be prefixed: `/dashboards/api/status`.
45. **Nginx `proxy_set_header` inheritance is location-level, not additive** — if ANY `proxy_set_header` directive is defined in a `location` block, ALL server-level `proxy_set_header` directives are silently dropped. Must repeat ALL proxy headers in every location block. This caused CSRF 403: WebSocket headers (`Upgrade`, `Connection`) killed `X-Forwarded-Proto` → SvelteKit origin mismatch.
46. **Malcolm container images are minimal — never assume standard tools exist** — Malcolm's filebeat-oss image doesn't have `pgrep` or `ps`. The dashboards image needs auth for its status endpoint. Always test healthcheck commands inside the actual container before deploying. Use shell builtins (`test -d /proc/1`) as a universal fallback.
47. **SSE (Server-Sent Events) streams require explicit nginx configuration** — must set `proxy_buffering off`, `proxy_cache off`, and `proxy_read_timeout 86400s` in the location block. Without this, nginx buffers the SSE response and the client never receives real-time events.
48. **Null-check ALL template values from daemon APIs** — SMART health, storage stats, and any other daemon data can return null fields when hardware isn't available or monitoring hasn't started. Calling `.toLocaleString()` on null crashes the entire page. Always use null-coalescing (`??`) or explicit null checks in Svelte templates.

### Malcolm Data Pipeline (NEW — Chain 11)
49. **Malcolm's Logstash routes ALL data into `arkime_sessions3-*`** — there are no separate `zeek-*` or `suricata-*` indices. Zeek and Suricata data are distinguished by `event.provider` and `event.dataset` fields. Never assume a separate index per tool.
50. **ECS field naming is universal in Malcolm** — all Zeek-native field names (`id.orig_h`, `orig_bytes`, `ts`) are remapped to ECS format (`source.ip`, `client.bytes`, `@timestamp`). Zeek-specific fields are prefixed: `zeek.dns.query`, `zeek.http.user_agent`, `zeek.ssl.ja3`. Suricata fields: `suricata.severity`, `rule.name`, `rule.category`.
51. **Use `NETWORK_INDEX` env var for index configurability** — hardcoded index names break across Malcolm versions. The `OPENSEARCH_NETWORK_INDEX` env var lets operators override the index pattern without code changes.
53. **Malcolm maps ALL text fields as text+keyword multi-fields. Every OpenSearch `terms` aggregation MUST use `.keyword` suffix** (e.g., `source.ip.keyword`, `network.transport.keyword`). Without it, aggregations fail with 400: "Text fields are not optimised for operations that require per-document field data like aggregations." This applies to every field used in `terms`, `cardinality`, or `composite` aggregations — NOT to `match`, `range`, or `bool` filter queries.
54. **Preserve OpenSearch `_source` wrapper in API responses** — frontends expect `{_id, _source: {...}}` (the standard OpenSearch hit structure). Flattening to `{_id, "field": "value"}` breaks destructuring like `hit._source.field`. Always pass through the raw hit structure.
55. **CSP headers must explicitly allow external font CDNs** — Google Fonts requires `fonts.googleapis.com` in `style-src` (for CSS) and `fonts.gstatic.com` in `font-src` (for font files). Missing either causes silent fallback to system fonts with only console CSP violations as evidence.
56. **Logstash env vars must be set on the logstash service, not just nginx-proxy** — Malcolm's `format_index_string.rb` filter reads `MALCOLM_NETWORK_INDEX_PATTERN` and `MALCOLM_NETWORK_INDEX_SUFFIX` from the process environment. These were set on nginx-proxy (for template rendering) but missing from logstash. Each Docker service has its own isolated environment — env vars do NOT propagate between services. When an env var is needed by multiple services, it must be explicitly set on each one.
57. **Logstash silently misindexes on Ruby filter errors instead of dropping events** — When `format_index_string.rb` crashes with NoMethodError, Logstash catches the exception and sets `[@metadata][malcolm_opensearch_index]` to the literal unexpanded string `%{[@metadata][malcolm_opensearch_index]}`. OpenSearch happily creates an index with that name. The result is 89K+ events in a garbage index with zero errors visible in the pipeline stats — only the Ruby exception in logs reveals the problem.

### Alert/ECS Field Normalization (NEW — 2026-03-06)
58. **Malcolm stores Suricata fields under 3 different paths depending on ECS normalization** — ECS: `rule.name`/`rule.id`/`rule.category`. Malcolm: `suricata.alert.signature`/`suricata.severity`. Raw Suricata EVE: `alert.signature`/`alert.severity`. A normalization layer must check all 3 with fallback priority. The frontend only reads one path (`alert.signature`), so normalization must happen in the daemon before the response is sent.
59. **OpenSearch `.keyword` aggregation returns string keys, not ints** — `suricata.severity.keyword` bucket keys are `"1"`, `"2"`, `"3"` (strings). Severity map lookups using int keys silently return `None`. Always `int()` parse string keys before lookup.
60. **Malcolm may store ECS fields as arrays** — `rule.category` can be `["Generic Protocol Command Decode"]` or a plain string. Always `isinstance(val, list)` check and flatten to first element before using as display text.
61. **Prefer `@timestamp` (ISO 8601) over `timestamp` (epoch millis)** — Malcolm documents have both fields. Frontend `formatTimestamp()` expects ISO strings. Normalization must copy `@timestamp` into `timestamp` to avoid displaying raw epoch milliseconds.

### Container Capture & Proxy (NEW — Chain 15)
62. **Malcolm's `docker-uid-gid-setup.sh` fails when trying to `usermod` root as PID 1** — the `usermod` command refuses to change the UID of a user that owns the init process. For containers that must run as root (e.g., netsniff-ng packet capture), set `PUSER=root` to skip UID remapping entirely rather than removing the entrypoint script.
63. **Health checks must test the service's actual function, not a baked-in default** — nginx-proxy's real role in NetTap is OpenSearch proxy (`:9200`), not the Malcolm `:443` vhost with arkime upstream. Healthchecking a broken vhost causes unnecessary restart loops even though the service's useful function works fine.
64. **Self-signed SSL keys on LAN-only appliances don't need `0600` permissions** — when a container drops privileges, the target user must be able to read the key. `0644` is acceptable for a self-signed cert on a local network appliance. The threat model doesn't include protecting the key from other local users.
65. **Every `docker compose down` + `up` cycle requires OpenSearch security re-bootstrap** — create a reusable script (`fix-opensearch.sh`) and document it prominently. This is the #1 recurring deployment issue (Chain 11, Chain 15). TODO: automate via init container or systemd post-start hook.
66. **Systemd service units are essential for appliance-grade reliability** — without `nettap.service`, a reboot leaves the stack down until manual intervention. An appliance must self-heal on power cycle.
67. **File capabilities on binaries can cause EPERM even when the container has sufficient ambient caps** — if a binary has file capabilities (e.g., `cap_sys_admin=eip` on netsniff-ng), ALL file caps must be in the container's bounding set or `exec` fails. Do NOT rely on `setcap -r` to strip file caps at runtime — it returns exit 0 on overlay2 but the xattrs from image layers persist (see lesson 68). Instead, add the missing caps directly to `cap_add`.
68. **`setcap -r` is unreliable on Docker overlay2 filesystems** — it returns success (exit 0) but `getcap` still shows the original file capabilities. The xattrs from the image layer persist through the overlay — the writable layer's "removal" doesn't override the lower layer's xattrs. Never rely on runtime `setcap` in Docker containers. Instead, ensure the bounding set covers all file capabilities, or build a custom image without file caps.

### SvelteKit Proxy / API Routing (NEW — Chain 16.15)
69. **Client-side fetch to `/api/*` requires SvelteKit `+server.ts` route handlers** — in production, browser requests go through nginx → SvelteKit. If no `+server.ts` exists for a path, SvelteKit returns 404. The client error handling shows empty data with no visible error. Always create proxy routes for new daemon API endpoints.
70. **`VITE_API_URL` defaulting to `http://localhost:8880` is broken in Docker deployment** — port 8880 is `expose`-only (container-to-container), never published to host. Browser can never reach it. All API client files must use relative paths (`/api/...`) so requests flow through nginx → SvelteKit → daemon.
71. **SvelteKit `[...path]` catch-all routes are lowest priority** — they don't conflict with existing explicit route files. A catch-all `api/[...path]/+server.ts` is a safe fallback proxy for any daemon endpoint that doesn't have a dedicated SvelteKit route. Existing explicit routes (e.g., `api/traffic/+server.ts`) always win.

### PCAP / tshark / DNS Analytics (NEW — Chain 17)
72. **tshark `-Y` only accepts Wireshark display filter syntax, NOT BPF** — `udp port 53` is BPF (used by tcpdump/libpcap). tshark's `-Y` flag requires display filters like `dns`, `http`, `tls`, `tcp.port == 80`. Using BPF syntax with `-Y` produces `tshark: Neither "udp" nor "port" are field or protocol names`. Always verify filter syntax against the tool's documentation.
73. **`asyncio.create_subprocess_exec` prevents shell injection — filter validation can be relaxed** — `create_subprocess_exec` passes arguments directly to the kernel (no shell), so characters like `|`, `&`, `;` have no special meaning. Input validation that blocks these chars to prevent "shell injection" is overly aggressive and breaks legitimate display filter operators like `||` (or) and `&&` (and). Only validate against actual security risks for the execution method being used.
74. **Malcolm/Zeek stores DNS data with `zeek.dns.*` prefix, NOT ECS `dns.*` prefix** — Zeek DNS fields use `zeek.dns.query` (not `dns.question.name`), `zeek.dns.qtype_name` (not `dns.question.type`), `zeek.dns.rcode_name` (not `dns.response_code`), `zeek.dns.rtt` (not `event.duration`). Always verify field names against actual OpenSearch documents before writing queries — ECS and Zeek-prefixed fields coexist but map to different data.
75. **Zeek DNS RTT field (`zeek.dns.rtt`) is in seconds, NOT nanoseconds** — Zeek stores round-trip time as floating-point seconds (e.g., `0.045` = 45ms). Code that divides by 1,000,000 (assuming nanoseconds like ECS `event.duration`) will show microsecond-scale values instead of millisecond-scale. Multiply by 1000 for millisecond display.

### Log Explorer / TShark / Design System (NEW — 2026-03-10)
76. **OpenSearch `track_total_hits` defaults to 10,000** — queries without `"track_total_hits": true` in the body will report `total.value: 10000` as the cap, even when millions of documents match. Always set this for stats/count endpoints.
77. **SVG tooltip flickering in Svelte is caused by reactivity re-rendering the entire SVG** — when a state variable (like `hoveredBarIndex`) is used inside an SVG, Svelte re-renders the whole SVG on change, destroying and recreating tooltip elements. Fix: move tooltips to an HTML overlay `<div>` outside the SVG, positioned via absolute CSS.
78. **Suricata alerts can dominate log explorer stats** — with 4.3M+ alert events vs. a few hundred thousand Zeek logs, aggregation-based charts and stats become meaningless. Use `must_not: [{"term": {"event.dataset": "alert"}}]` to exclude alerts from log explorer views.
79. **Zeek pcap-monitor DNS noise pollutes real DNS analytics** — Zeek's internal `pcap-monitor` generates millions of DNS lookups that show up as the #1 query in DNS aggregations. Exclude with `must_not: [{"term": {"zeek.dns.query.keyword": "pcap-monitor"}}]` on both aggregation AND search endpoints.
80. **Wireshark `tcp.port` matches EITHER source or destination** — `tcp.port == 443 && tcp.port == 53284` requires BOTH ports to be found on one side of the packet, which is impossible. The ephemeral source port should NEVER be in TShark filters for rotated PCAP analysis.
81. **ICMP has no ports — `icmp.port` is not a valid TShark display filter field** — Zeek may store ICMP type/code in port fields, but TShark rejects `icmp.port`. For ICMP connections, use bare `icmp` or `icmpv6` as the protocol filter instead.
82. **IPv6 addresses require `ipv6.addr` in TShark filters, not `ip.addr`** — `ip.addr == 2001:db8::1` matches zero packets. Detect IPv6 by checking for `:` in the address string.
83. **Deploy scripts must check upstream dependency health before recreating dependent containers** — `docker compose up -d --force-recreate` fails when a dependency (OpenSearch) is unhealthy because `depends_on: condition: service_healthy` blocks startup. Always check and fix unhealthy dependencies first.
84. **CSS design tokens prevent cross-page inconsistency** — creating a canonical design system (`web/DESIGN-SYSTEM.md`) with CSS custom properties (`var(--red)`, `var(--space-md)`) and enforcing it across all 10+ pages prevents visual drift as different developers/sessions modify different pages.

### Docker Networking / Diagnostic Scripts (NEW — 2026-03-12)
85. **Container `expose:` ports are NOT reachable from the host** — `expose: ["3000"]` makes a port available container-to-container on the Docker network, but NOT on `localhost` from the host. Only `ports: ["3000:3000"]` publishes to the host. In NetTap, nettap-web exposes 3000 internally and nettap-nginx publishes 80/443 to the host. Diagnostic scripts that `curl http://localhost:3000` from the host will always get HTTP 000 (connection refused). Must either: (a) curl through nginx on the published port (`curl -k https://localhost/path`), or (b) `docker exec nettap-web curl http://localhost:3000/path` from inside the container.
86. **Diagnostic and debugging commands for the remote device MUST be scripts, not inline commands** — even a "quick" set of `curl` and `docker logs` commands must go in `scripts/remote/diagnose-*.sh`. Multi-command blocks break when copy-pasted over SSH, and the user has to re-run them one-by-one to debug which failed. A single script file is copy-paste-proof and reproducible.

### SMART Monitoring / nvme-cli (NEW — 2026-03-12)
87. **nvme-cli reports temperature in Kelvin, smartctl in Celsius** — `nvme smart-log` returns temperature as 311 (Kelvin) while smartctl returns 38 (Celsius). Must detect the source and convert: `temp_c = temp_k - 273` when value > 200 (heuristic: no drive runs above 200°C).
88. **nvme-cli field names differ from smartctl** — `percent_used` (nvme-cli) vs `percentage_used` (smartctl), `avail_spare` vs `available_spare`, `media_errors` is the same. The extraction layer must handle both naming conventions.
89. **nvme-cli admin commands target the controller, not the namespace** — `nvme smart-log /dev/nvme0` works, `nvme smart-log /dev/nvme0n1` may fail depending on version. Derive controller path by stripping the namespace suffix (`/dev/nvme0n1` → `/dev/nvme0`).
90. **NVMe admin commands require SYS_ADMIN capability** — both `nvme smart-log` and `nvme id-ctrl` use NVMe admin ioctls that need `CAP_SYS_ADMIN`. SYS_RAWIO alone is insufficient for NVMe (though it works for SATA smartctl). The daemon container needs both caps: SYS_ADMIN for NVMe, SYS_RAWIO for SATA.
91. **pySMART is unnecessary — nvme-cli + smartctl directly is better** — pySMART wraps smartctl with text parsing and has documented NVMe bugs. Using nvme-cli (native NVMe ioctl) + smartctl (SATA fallback) directly with JSON output is more reliable and removes a dependency.

### Svelte 5 / Frontend Build (NEW — 2026-03-13)
92. **Svelte 5 `{@const}` can ONLY be a direct child of block tags** — `{@const}` must be immediately inside `{#each}`, `{#if}`, `{:else}`, `{#snippet}`, or `<Component>`. It CANNOT be inside HTML elements like `<div>`, `<svg>`, `<td>`, etc. This causes silent build failures in Docker (vite build exits 1) while `svelte-check` may not catch it. Fix: move calculations to `$derived` in the script block or inline expressions in attributes.
93. **Multi-ASN organizations produce duplicate service names after ASN prefix stripping** — OpenSearch aggregates by `destination.as.full.keyword` (e.g., `AS16509 Amazon.com, Inc.`). After stripping the ASN number, the same org name appears multiple times if they operate multiple ASNs (Amazon, Rackspace, etc.). Must merge by name and sum bytes/connections. Duplicate names in Svelte `{#each (item.key)}` blocks crash the renderer with `each_key_duplicate`, leaving the DOM in a stale loading state.
94. **Svelte render crashes leave the DOM in the previous state** — if `{#each}` throws `each_key_duplicate` during rendering after `loading = false`, the DOM stays showing the loading spinner because the conditional branch that shows data never completed rendering. The error appears in console but the page looks "stuck". Always use index-suffixed keys (`${name}-${i}`) as a safety net.
95. **Device hostname resolution via DNS answer records works well** — querying `zeek.dns.answers` (the IPs a domain resolves to) and aggregating by `zeek.dns.query.keyword` with `terms size=1` returns the most common hostname for any IP. This is already implemented in `DeviceFingerprint.get_hostname_for_ip()` and adds ~15 hostnames per 37 devices (depends on DNS traffic volume).
96. **Risk scoring already returns full factor breakdown** — `GET /api/risk/scores/{ip}` returns not just the score/level but an array of `factors` with `{name, score, max, description}` for all 5 weighted factors. No new backend work needed to display the breakdown — just consume the existing API.

### Daemon→Frontend Data Contracts (NEW — 2026-03-16)
97. **Svelte 5 `{#each (device.ip)}` crashes with `each_key_duplicate` when keys are `undefined`** — if the daemon returns an array of strings (`["10.0.0.1"]`) but the component destructures objects (`device.ip`), every key evaluates to `undefined`, and ALL items share the same key. Svelte 5 throws `each_key_duplicate`, which crashes mid-render and leaves the DOM in a stale loading state (spinner never clears). The fix is always on the data source: return objects `{ip, count, severity}` not bare strings.
98. **Timeline/chart data contract mismatches cause silent rendering failures, not crashes** — if the daemon returns `{buckets: [{count, signatures}]}` but the component expects `{series: [{total, sub_categories}]}`, the guard clause (`{#if timelineData?.series?.length}`) evaluates to falsy and the section simply never renders. No error in console. Always verify field names AND structure between daemon response and TypeScript types.
99. **Always include `last_seen` (or equivalent timestamp) in aggregation responses** — OpenSearch `max` aggregation on `@timestamp` adds minimal query cost and prevents `formatRelativeTime(undefined)` rendering broken in the frontend. Add `"latest": {"max": {"field": "@timestamp"}}` as a sub-aggregation to any `terms` bucket that will be displayed with time context.

### Process Lessons
20. **Don't apply privilege fixes globally** — scope to only the affected services.
21. **Re-evaluate workarounds when the root cause is fixed** — leftover workarounds become harmful.
22. **Bypassing an entrypoint's privilege drop skips ALL its side effects** — you must replicate chown, env setup, etc.
23. **Test with the actual execution path** — `docker exec -u 1000` is NOT equivalent to the entrypoint's `su` heredoc.
24. **Always read the source code** — the assumption that `jvm.options.d/` works in Logstash came from Elasticsearch docs. Reading `JvmOptionsParser.java` would have caught this immediately.
25. **Test from `install.sh`, not just `docker compose up -d`** — individual service restarts may work while a full fresh deployment reveals missing dependencies.
52. **`.gitignore` rule `logs/` catches SvelteKit route directories like `web/src/routes/logs/`** — use `git add -f` to override.

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
| NIC LED blink unavailable on kernel <6.11 (igc) | Users cannot visually identify NICs via LED | Info fallback shows MAC/PCI/driver; document manual identification in setup guide |
| Malcolm env files may gain new vars on upgrade | Capture/proxy services crash-loop from missing env vars or broken nginx templates | After upgrading Malcolm tag, diff upstream env files and template files against our compose env vars |
| `--force-recreate` breaks OpenSearch security | Logstash, filebeat, and all services using `malcolm_internal` get 403 | Must re-run security bootstrap (write `roles_mapping.yml` + `securityadmin.sh`) after any `--force-recreate`. TODO: automate in deploy script or init container. |
| Storage API format can regress if daemon code is reverted | Setup wizard disk check fails, storage config page broken | `normalizeStorageStatus()` in SvelteKit proxy handles both old and new formats as safety net. Always verify `get_status()` output matches `StorageStatus` interface after daemon changes. |
| Removing PROTOCOL_HEADER/HOST_HEADER from web env | All form POSTs (setup wizard, login, settings) silently fail with CSRF 403 | These env vars are required for SvelteKit adapter-node behind any TLS-terminating reverse proxy. Document in deployment guide. |
| SSL key permissions reset on cert regeneration | nettap-nginx crash-loops with "Permission denied" on key file | After regenerating SSL certs, always `chmod 644` the key file. Document in deployment guide. |
| Malcolm image updates may add/change file capabilities on binaries | EPERM on exec if file caps exceed bounding set | After Malcolm tag bumps, run `getcap` on capture binaries inside the image. Ensure all file caps are in `cap_add`. Do NOT rely on `setcap -r` to strip caps at runtime — it silently fails on overlay2. |
| OpenSearch security bootstrap not automated on boot | After reboot + container recreate, all services get 403 until manual `fix-opensearch.sh` | TODO: add post-start hook to `nettap.service` or create an init container that runs securityadmin.sh |
| Missing index pattern env vars on new services | Logstash (or any Malcolm service) silently misindexes all events into garbage index names | After adding or modifying any Malcolm service in docker-compose.yml, check Malcolm's upstream env_file references and ensure ALL required env vars are set. Especially `MALCOLM_NETWORK_INDEX_PATTERN`, `MALCOLM_NETWORK_INDEX_SUFFIX`, `MALCOLM_OTHER_INDEX_PATTERN`, `MALCOLM_OTHER_INDEX_SUFFIX` for any service running Logstash filters. |
| TShark filter may not find packets in very old PCAPs | Arkime rotates PCAP files by size (256MB default), older sessions may span files not in the 5-file search window | The auto-analyze heuristic tries 5 closest PCAPs by modified time. For very old connections, manual PCAP search may be needed. Could increase window or improve heuristic later. |
| Suricata alert exclusion is hardcoded in logs.py | If event.dataset naming changes in Malcolm upgrade, alerts may leak back into log stats | Check `event.dataset` values after Malcolm version bumps. The `_EXCLUDE_ALERTS_FILTER` constant uses `{"term": {"event.dataset": "alert"}}`. |
| pcap-monitor DNS exclusion is query-name based | If Zeek internal monitoring changes, the exclusion pattern breaks | The `_EXCLUDE_DNS_NOISE` filter matches `zeek.dns.query.keyword: "pcap-monitor"` literally. Check after Zeek/Malcolm upgrades. |

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
| NET-68 | #73 | NIC LED identify: nsenter permission + info fallback | 2026-03-02 |
| NET-79 | develop | Malcolm capture + proxy env vars, healthcheck fixes | 2026-03-02 |
| NET-80 | develop | Storage API format mismatch — disk_free_gb, wrong types | 2026-03-03 |
| — | manual | OpenSearch security reset + logstash bootstrap deadlock | 2026-03-03 |
| NET-81 | develop | Setup wizard CSRF 403 + volume permissions | 2026-03-03 |
| — | 717bd24 | Logstash index pattern env vars missing — 89K+ events misindexed | 2026-03-05 |
| — | 32d4ab2 | Tools section: 4 backend services + API routes + Dockerfile + 97 tests | 2026-03-06 |
| — | 2c00031 | Tools section: design docs + mockups | 2026-03-06 |
| — | 65e31cf | pcap-capture PUSER=root + nginx-proxy healthcheck :9200 | 2026-03-07 |
| — | manual | nettap-nginx SSL key chmod 644 | 2026-03-07 |
| — | manual | OpenSearch security re-bootstrap + fix-opensearch.sh script | 2026-03-07 |
| — | manual | nettap.service systemd boot persistence | 2026-03-07 |
| — | phase-4/webui-v2 | netsniff-ng EPERM: SYS_ADMIN cap_add (setcap -r fails on overlay2) | 2026-03-07 |
| — | 6a853e4 + 8763d07 | PCAP Search: BPF→display filter syntax, filter validation fix, download endpoint, sortable columns | 2026-03-09 |
| — | 5e8acf8 | DNS Analytics: zeek.dns.* field remapping, RTT conversion fix, page redesign | 2026-03-09 |
| — | 4009faf | Alerts page redesign: 4 new aggregation endpoints, interactive SVG timeline, severity/time filters, sortable table | 2026-03-09 |
| NET-105 | 1f85e8e | Log Explorer: .keyword suffix on all 6 aggregation fields | 2026-03-10 |
| NET-106 | 6c70af4 | Log Explorer: 10K event cap fix, stat text color, chart flicker, bar colors | 2026-03-10 |
| NET-107 | 245d4af | Log Explorer: exclude Suricata alerts + pcap-monitor noise from aggregations | 2026-03-10 |
| NET-108 | 8e09867 | Log Explorer: exclude pcap-monitor noise from search results | 2026-03-10 |
| NET-109 | 0e10121 | Design system guide + 10-page standardization + sortable tables everywhere | 2026-03-10 |
| NET-110 | 7912342 | TShark filter fix: drop ephemeral port, handle ICMP/IPv6 | 2026-03-10 |
| — | 1ce47e3 | Deploy script: check OpenSearch health before deploying daemon/web | 2026-03-11 |
| — | 79fdc8e | Traffic category detail: duplicate ASN service names crash Svelte render | 2026-03-13 |
| — | a6f44c1 | Traffic category detail v2: bandwidth chart, hostnames, search, auto-refresh, service filter, % column | 2026-03-13 |
| — | ddfb627 | Svelte build fix: {@const} inside <div> invalid — inline expressions instead | 2026-03-13 |
| — | 7d44e5d | Device intelligence dashboard v2: 7 sections + TShark drill-down drawer | 2026-03-13 |
| — | c948e8c | Svelte build fix: {@const} inside <svg> invalid — $derived arc calc instead | 2026-03-13 |
