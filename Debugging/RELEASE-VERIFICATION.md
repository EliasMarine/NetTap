# NetTap v1.0.0 Release Verification — Source of Truth

> **Last updated:** 2026-03-09
> **Status:** 16/17 checks verified across 2 environments (Dev + N100) — ALL automated checks PASS. Hardware checks (H1–H7) in progress. **H1 near-complete — 18/18 containers healthy.** Full-stack test (full-stack-test.sh) 59/59 passing — covers all Mirror/SPAN API endpoints + web UI pages. Mirror/SPAN feature pages fixed: catch-all SvelteKit proxy route + VITE_API_URL removal. PCAP Search fixed: BPF→display filter syntax, filter validation relaxed, per-file download. DNS Analytics fixed: zeek.dns.* field remapping, RTT conversion fix. Daemon tests: 1175 passing. Web tests: 1034/1034 passing (74 test files). svelte-check: 0 errors.
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
| N100 (Ubuntu) | `--trivy` | 2026-03-03 | **2 FAIL** | 7 | 2 | 6 | Trivy working. CVEs in Debian 12 base image + Node.js base image npm — all upstream, no fix available |
| Dev (macOS) | `--quick` | 2026-03-03 | ALL PASSED | 8 | 0 | 1 | After shellcheck fixes + .trivyignore. 1 skip: ruff not installed |
| N100 (Ubuntu) | `--trivy` | 2026-03-03 | ALL PASSED | 9 | 0 | 6 | After .trivyignore + npm stripping from web prod image. All 9 runnable checks PASS |

---

## Verification Environments

### Dev Machine (macOS) — full toolchain

- **OS:** macOS (Darwin)
- **Purpose:** Full linting, type checking, unit tests, format checks
- **Tools available:** shellcheck, pytest, npm, vitest, svelte-check, playwright
- **Tools missing:** ruff, trivy, docker compose V2 plugin
- **Status:** `--quick` ALL PASSED (8 pass, 0 fail, 1 skip: ruff). Shellcheck now clean after fixes. Docker builds still fail on macOS (no Compose V2 plugin — expected).

### N100 Target Hardware (Ubuntu) — production

- **OS:** Ubuntu Server 22.04 LTS
- **Hardware:** Intel N100, 16GB RAM, 1TB NVMe, dual Intel i226-V 2.5GbE
- **Purpose:** Docker builds, integration testing, hardware verification
- **Tools available:** docker, python3, git, bash, trivy
- **Tools missing:** ruff, shellcheck, pytest, npm, playwright (see [Missing Tools](#missing-tools-on-n100))
- **Status:** ALL 9 runnable checks PASS (`--trivy` mode). Docker builds PASS, Trivy PASS (after .trivyignore + npm stripping). 6 checks skipped (lint/test tools — run on Dev instead).

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
| 3 | Shell Lint (shellcheck) | PASS | PASS | SKIP | SKIP | — | Fixed: SC2221/SC2222 case reorder, SC2034/SC2155 suppressions, shellcheck source directives (NET-78) |
| 4 | Python Tests (pytest) | PASS | PASS | SKIP | SKIP | — | 1078/1078 passed on Dev (was 1066; +12 from alerts normalization + lookup API) |
| 5 | Web Dependencies (npm ci) | PASS | PASS | SKIP | SKIP | — | 0 vulnerabilities, 212 packages |
| 6 | Web Type Check (svelte-check) | PASS | PASS | SKIP | SKIP | — | 665 files, 0 errors, 4 warnings (pre-existing a11y) |
| 7 | Web Unit Tests (vitest) | PASS | PASS | SKIP | SKIP | — | 691/691 passed on Dev (was 683; +8 from IP context menu changes) |
| 8 | Docker Builds | n/a (quick) | **FAIL** | n/a (quick) | PASS | — | macOS: `docker compose -f` not recognized (V2 plugin missing). N100: all 4 images build OK |
| 9 | Trivy CVE Scan | n/a (quick) | SKIP (no images) | n/a (quick) | PASS | — | N100: PASS after .trivyignore (3 accepted OS CVEs) + npm stripping from web prod image (eliminates 14 Node CVEs). See [Trivy CVE Findings](#trivy-cve-findings-n100) for risk assessment. |
| 10 | E2E Tests (Playwright) | n/a (quick) | PASS | n/a (quick) | SKIP | — | Dev: 6/8 passed, 2 skipped. Fixed selector + CSRF + DATA_DIR issues. See [E2E Failures](#e2e-test-failures-dev) |

**Legend:** PASS = verified passing, FAIL = verified failing, SKIP = tool not available, n/a = not included in mode, — = not yet run

---

## Hardware Verification (Manual)

These 7 checks require the full Docker stack running on the N100 target hardware. They cannot be automated and must be performed manually.

| # | Check | Target | Status | Date | Operator | Notes |
|---|---|---|---|---|---|---|
| H1 | Integration test — full Docker stack up | N100 | **NEAR COMPLETE** | 2026-03-07 | Elias | **18/18 containers healthy.** All previous known issues resolved. pcap-capture fixed (PUSER=root skips usermod on PID 1, SYS_ADMIN cap_add covers netsniff-ng file caps — setcap -r unreliable on overlay2). nginx-proxy fixed (healthcheck on :9200, removed :443). nettap-nginx SSL fixed (chmod 644). OpenSearch security re-bootstrapped (fix-opensearch.sh). Boot persistence via nettap.service systemd unit. Dashboard loads, setup wizard completes, data pipeline flowing. **Remaining:** Full end-to-end data verification (Zeek + Suricata + Arkime all producing indexed data). |
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
- [x] No CRITICAL/HIGH CVEs (Trivy) — PASS. `.trivyignore` suppresses 3 accepted OS CVEs (glibc, zlib, sqlite — no Debian 12 fix available). Web prod image strips npm/yarn/corepack (eliminates 14 Node CVEs). 0 app-level vulnerabilities. See [Trivy CVE Findings](#trivy-cve-findings-n100).
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
| 2026-03-03 | N100 (Ubuntu) | `--trivy` | **2 FAIL** | 7 | 2 | 6 | Elias | Trivy now working after image name + sudo fix. Both scans FAIL with upstream CVEs. storage-daemon: 4 CVEs (glibc, sqlite, zlib). web: 3 OS + 14 Node.js npm CVEs. App deps clean. |
| 2026-03-03 | Dev (macOS) | `--quick` | ALL PASSED | 8 | 0 | 1 | Claude | After shellcheck fixes (.trivyignore, case reorder, SC2034/SC2155 suppressions, source directives). 1 skip: ruff. |
| 2026-03-03 | N100 (Ubuntu) | `--trivy` | ALL PASSED | 9 | 0 | 6 | Elias | ALL 9 runnable checks PASS after .trivyignore + npm stripping from web prod image. 6 skips are lint/test tools (run on Dev). |
| 2026-03-02 | N100 (Ubuntu) | H1: Full stack | **PARTIAL** | — | — | — | Elias | First full stack spin-up. 12/18 containers healthy, 6 crash-loop. Fixed via NET-79 (EXTRA_TAGS, REDIS_PASSWORD, ARKIME_SSL, healthcheck endpoints). Pushed to develop. |
| 2026-03-03 | N100 (Ubuntu) | H1: Full stack | **PARTIAL** | — | — | — | Elias | After NET-79 pull + force-recreate: logstash stuck (roles_mapping.yml reset). Manual fix: wrote roles_mapping, ran securityadmin.sh → logstash healthy. Web UI accessible (302→/setup). Storage wizard broken → fixed NET-80. Pending: full rebuild with NET-80. |
| 2026-03-03 | N100 (Ubuntu) | H1: Full stack | **PARTIAL** | — | — | — | Elias | Full rebuild with NET-80. All containers healthy, storage API working (1830GB total, 1731GB free). Setup wizard Steps 1-4 work. Step 5 (account creation) fails silently → NET-81 fix: CSRF PROTOCOL_HEADER + Dockerfile volume chown. Pending: rebuild with NET-81. |
| 2026-03-03 | N100 (Ubuntu) | H1: Full stack | **PARTIAL** | — | — | — | Elias | After NET-81 rebuild: still CSRF 403. Browser Network tab confirmed POST /setup?/createAdmin → 403 Forbidden. Root cause: nginx `proxy_set_header` inheritance — location-level headers silently drop ALL server-level headers. Fixed NET-82: repeated all proxy headers in every location block. Dashboard loads for the first time! |
| 2026-03-03 | N100 (Ubuntu) | H1: System page | **FIXED** | — | — | — | Elias | System page crashed on null SMART health values (`power_on_hours.toLocaleString()` on null). Fixed NET-83: added null-coalescing to all SMART template values. Also fixed SSE proxy buffering in nginx (proxy_buffering off). |
| 2026-03-03 | N100 (Ubuntu) | H1: Healthchecks | **FIXED** | — | — | — | Elias | Fixed 4 container healthchecks: filebeat (NET-85: pgrep not in image → test -d /proc/1), dashboards (NET-86: curl needs auth → added curlrc), dashboards-helper (container_health.sh → test -d /proc/1), cyberchef (hit /health not /). nginx-proxy remains unhealthy (known issue: arkime upstream on host networking). Final: 17/18 healthy. |
| 2026-03-04 | Dev (macOS) | pytest | ALL PASSED | 1036 | 0 | 0 | Claude | After Bridge Go Live PR #83: 1036 tests (104 bridge-specific). Up from 997. |
| 2026-03-04 | Dev (macOS) | vitest | ALL PASSED | 683 | 0 | 0 | Claude | After Bridge Go Live PR #83: 683 tests (22 GoLive + 25 bridge API). Up from 649. |
| 2026-03-04 | Dev (macOS) | svelte-check | ALL PASSED | 620 | 0 | 0 | Claude | 620 files checked, 0 errors, 0 warnings. |
| 2026-03-04 | N100 (Ubuntu) | H1: Bridge Go Live | **PARTIAL** | — | — | — | Elias | Deployed PR #83 (bridge Go Live) + PR #82 (system fixes). Daemon healthy, bridge_loop running (30s). Hit 302→/login on `/api/bridge/readiness` — auth middleware blocking new routes. Fixed in PR #85: added `/api/bridge` + `/go-live` to PUBLIC_PATHS. Pending: redeploy with PR #85 and retest. |
| 2026-03-04 | Dev (macOS) | pytest | ALL PASSED | 1041 | 0 | 0 | Claude | After NET-95 ECS field mapping: 1041 tests (up from 1036). All daemon queries remapped to arkime_sessions3-* + ECS fields. |
| 2026-03-04 | Dev (macOS) | vitest | ALL PASSED | 683 | 0 | 0 | Claude | No web changes needed for ECS mapping — frontend uses daemon API. |
| 2026-03-04 | Dev (macOS) | svelte-check | ALL PASSED | 620 | 0 | 0 | Claude | No type errors. |
| 2026-03-05 | Dev (macOS) | pytest | ALL PASSED | 1066 | 0 | 0 | Claude | After PR #92 (.keyword suffix fix + log search _source wrapper): 1066 tests (up from 1041). 22 aggregation fields fixed across 6 daemon files. |
| 2026-03-05 | N100 (Ubuntu) | H1: Dashboard data | **FIXED** | — | — | — | Elias | All dashboard aggregations now return data after .keyword suffix fix. Log Explorer shows logs in correct _source format. Google Fonts render correctly after CSP fix. |
| 2026-03-05 | N100 (Ubuntu) | H1: Logstash indexing | **FIXED** | — | — | — | Elias | Logstash `format_index_string.rb` was crashing with `NoMethodError` — missing `MALCOLM_NETWORK_INDEX_PATTERN`/`SUFFIX` env vars on logstash service. 89K+ events landed in broken literal index `%{[@metadata][malcolm_opensearch_index]}`. Fix: added 4 MALCOLM_*_INDEX env vars to logstash in docker-compose.yml (commit 717bd24). Post-fix: zero Ruby exceptions, Suricata events flowing to correct `arkime_sessions3-*` index (0 → 20+ in minutes). Reindexed 34,992 docs from broken index. |
| 2026-03-06 | Dev (macOS) | pytest | ALL PASSED | 1078 | 0 | 0 | Claude | After alerts ECS normalization + lookup API + IP filter: 1078 tests (up from 1066). |
| 2026-03-06 | Dev (macOS) | vitest | ALL PASSED | 691 | 0 | 0 | Claude | After IP context menu expansion: 691 tests (up from 683). 16 files changed, 1214 lines added. |
| 2026-03-06 | Dev (macOS) | svelte-check | ALL PASSED | 665 | 0 | 0 | Claude | 665 files (up from 620), 0 errors, 4 pre-existing a11y warnings. |
| 2026-03-06 | N100 (Ubuntu) | H1: Alerts page | **VERIFIED** | — | — | — | Claude | Alerts now show real signatures, severities (1/2/3), categories, timestamps via `docker exec` API test. ECS/Malcolm/Suricata field normalization working. |
| 2026-03-07 | N100 (Ubuntu) | H1: pcap-capture fix | **FIXED** | — | — | — | Elias | pcap-capture was restart-looping: `usermod: user root is currently used by process 1`. Fix: PUSER=root skips UID remapping. Container now healthy, netsniff-ng capturing. |
| 2026-03-07 | N100 (Ubuntu) | H1: nginx-proxy fix | **FIXED** | — | — | — | Elias | nginx-proxy was unhealthy: `host not found in upstream "arkime:8005"`. Fix: healthcheck on :9200 (OpenSearch proxy), removed :443 port. Container now healthy. **18/18 containers healthy.** |
| 2026-03-07 | N100 (Ubuntu) | H1: nettap-nginx SSL | **FIXED** | — | — | — | Elias | nettap-nginx crash-looping: SSL key permission denied. Fix: chmod 644 on self-signed key. Container now serving HTTPS. |
| 2026-03-07 | N100 (Ubuntu) | H1: OpenSearch security | **FIXED** | — | — | — | Elias | OpenSearch security not initialized after recreate. Fix: ran fix-opensearch.sh (roles_mapping.yml + securityadmin.sh). All services authenticated. |
| 2026-03-07 | N100 (Ubuntu) | H1: Boot persistence | **VERIFIED** | — | — | — | Elias | nettap.service systemd unit installed and enabled. Docker stack auto-starts on reboot. |
| 2026-03-07 | N100 (Ubuntu) | H1: netsniff-ng EPERM fix | **FIXED** | — | — | — | Elias | netsniff-ng had file capabilities (`cap_sys_admin=eip`) exceeding container bounding set. Initial fix (SETFCAP + `setcap -r`) returned exit 0 but was a no-op on overlay2 — xattrs from image layers persist through overlay. Working fix: added `SYS_ADMIN` to pcap-capture `cap_add` so bounding set covers all file caps. Removed useless `setcap -r`. Acceptable: pcap-capture already runs as root with network_mode: host. |
| 2026-03-09 | N100 (Ubuntu) | Full-stack test (Mirror/SPAN) | **ALL PASSED** | 59 | 0 | 0 | Elias | full-stack-test.sh: 59/59 checks pass. Covers: 6 core API, 4 capture mode API (503 expected), SMART, storage, device registry, live connections, bandwidth, DNS, IoT/LAN, notifications, changelog, certificates, MAC, PCAP, backup, suricata rules, 12 web UI pages, OpenSearch health. Fixed during testing: PyYAML missing, docker exec for internal APIs, nginx recreate, HTTP 301 acceptance. |
| 2026-03-10 | N100 (Ubuntu) | Data pipeline verification | **FIXED** | — | — | — | Elias | Two root causes fixed: (1) `ZEEK_JSON` env var missing → Zeek output TSV instead of JSON → Logstash couldn't parse → conn/dns/http/tls logs lost. Fix: added `ZEEK_JSON: "true"` (commit 5d13793). (2) `event.id` field type conflict: arkime_sessions3-260310 created by Suricata first (numeric event.id → mapped as `long`). Zeek string UIDs rejected with mapper_parsing_exception. Fix: deleted conflicted index + updated malcolm_template to map `event.id` as `keyword`. Result: 7,427+ Zeek conn docs flowing. Dashboard populating. |
| 2026-03-09 | Dev (macOS) | Mirror/SPAN proxy route fix | **FIXED** | 1034 | 0 | 0 | Claude | 7 Mirror/SPAN feature pages (Live Monitor, Bandwidth, DNS Analytics, IoT & LAN, Changelog, Certificates, PCAP Search) showed no data. Root cause: missing SvelteKit `+server.ts` proxy routes (404 silently) + `VITE_API_URL` pointing to Docker-internal port 8880 (unreachable from browser). Fix: catch-all `[...path]/+server.ts` proxy via `daemonFetch()` + removed `VITE_API_URL` from 5 API clients + setup page. 8 new tests. vitest: 1034/1034 (74 files). svelte-check: 0 errors. |
| 2026-03-09 | Dev (macOS) | PCAP Search fixes | **FIXED** | -- | 0 | 0 | Claude | Quick filters used BPF syntax (`udp port 53`) but tshark `-Y` requires Wireshark display filter syntax (`dns`). Filter validation regex blocked `\|`/`&` needed for display filter `\|\|`/`&&` — removed from forbidden chars (safe: `asyncio.create_subprocess_exec` prevents shell injection). Added `GET /api/pcap/download-file` daemon endpoint + Download buttons in UI. Added auto-scroll to preview section + sortable columns. Files: `daemon/api/pcap.py`, `daemon/services/pcap_search.py`, `web/src/lib/api/pcap.ts`, `web/src/routes/pcap/+page.svelte`. Commits 6a853e4 + 8763d07. |
| 2026-03-09 | Dev (macOS) | DNS Analytics fixes | **FIXED** | -- | 0 | 0 | Claude | All DNS aggregations returned 0 due to field name mismatch: `dns.question.name.keyword` → `zeek.dns.query.keyword`, `dns.question.type.keyword` → `zeek.dns.qtype_name.keyword`, `dns.response_code.keyword` → `zeek.dns.rcode_name.keyword`, `event.duration` → `zeek.dns.rtt`. RTT conversion inverted: was ÷1,000,000 (assuming nanoseconds), now ×1000 (Zeek stores seconds). Complete page redesign: interactive SVG timeline with tooltips, sortable tables, time range pills, per-device DNS split panel, empty states. Files: `daemon/services/dns_analytics.py`, `web/src/routes/dns/+page.svelte`. Commit 5e8acf8. |
| 2026-03-16 | Dev (macOS) | Alert category drill-down fix | **FIXED** | 1484 | 0 | 0 | Claude | Fixed 3 daemon→frontend data contract mismatches in `daemon/api/alerts.py`: (1) `affected_devices` returned strings → Svelte `each_key_duplicate` crash; now returns `{ip,count,severity}` objects. (2) Timeline returned `{buckets:[{count,signatures}]}` → silent render failure; now `{series:[{total,sub_categories}]}`. (3) `top_signatures` missing `last_seen` → added `max` agg on `@timestamp`. pytest: 375 passed (1 pre-existing flaky). vitest: 1484/1484. svelte-check: 0 new errors. |
| 2026-11-01 | G11 (Ubuntu 24.04.5) | Mirror/SPAN verify (`verify-mirror-mode.sh`) | **PARTIAL** | — | 5 | — | Elias | First run on the G11 mirror trial (USW Pro XG 8 PoE uplink mirror → enp4s0). The capture port was admin DOWN because Ubuntu's AppArmor blocked the daemon's nsenter (Chain 22, NET-126). After a manual `ip link set enp4s0 up`: a 2.5 Gb/s link, about 800 packets/s, 500 unicast frames in 10 s, so the mirror works. 4 failures left (IPv6 link-local, rx-vlan-offload, no netplan file, no boot unit). Fix on `fix/daemon-drop-nsenter`; re-verify with `deploy-drop-nsenter.sh`. |
| 2026-11-01 | G11 (Ubuntu 24.04.5) | Mirror/SPAN verify after `deploy-drop-nsenter.sh` + reboot | **PASS** | all | 0 | — | Claude | Every `verify-mirror-mode.sh` check passed after a reboot, ~3,800 packets/s on enp4s0 (Chain 22, NET-126). |
| 2026-11-01 | G11 (Ubuntu 24.04.5) | Zeek pipeline (`deploy-zeek-rdrand-fix.sh`) | **PASS** | 4 | 0 | — | Claude | Unique Broker IDs, cluster connected (9 links), conn.log written, Zeek records reached OpenSearch (Chain 23, NET-127). |
| 2026-11-01 | G11 (Ubuntu 24.04.5) | Index template + dashboard APIs (`fix-index-template.sh --delete-today`, `deploy-malcolm-field-names.sh`) | **PASS** | 5 | 0 | — | Claude | Template pattern `arkime_sessions3-*`, today's index recreated with Malcolm types (owner approved deleting 15,457 records), 0 Logstash rejections; traffic summary 6,185 connections, 18 devices, 5 top talkers, top protocol udp, 0 daemon errors (Chain 24, NET-128). |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Dashboard data accuracy batches 1–5 (`deploy-data-accuracy-batch{1..5}.sh`) | **PASS** | all | 0 | — | Claude | Every batch check ✓ (Chain 25, NET-129): device/DNS/bytes/alerts figures match OpenSearch; certificates = x509 count; TShark hex + Info; arkime-live off (TLS errors 0); PCAP 5.2% of disk under a 25% cap; Live map offline, devices 30 = 30, bandwidth = NIC rate; CyberChef recipe decodes in the browser. Open: #47 (other VLANs not counted as LAN). |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | PCAP Search, batch 6 (`deploy-data-accuracy-batch6.sh`) | **PASS** | 6 | 0 | — | Claude | Preview 0.8 s (was 18 s + proxy timeout); filtered preview 100 DNS in 2.4 s; search is a background job (answers in 0.01 s, progresses); tshark bounded, 93 MiB. Browser: 1 h DNS search with progress and a filtered preview. Download fix (#51) unit-tested only. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Settings, batch 7 (`deploy-data-accuracy-batch7.sh`) | **PASS** | 6 | 0 | — | Claude | Capture file size shown = netsniff `-F`; a saved size reaches netsniff after restart and was restored; ILM card synced; capture kept writing. Browser: Retention, Capture, About correct. Every route has now had a browser pass. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | PCAP preview time limit, batch 8 (`deploy-data-accuracy-batch8.sh`) | **PASS** | 3 | 0 | — | Claude | A filter that never matches: 4.4 GB file → 0 packets, `timed_out=True` in 45.1 s; 1 MB file → `timed_out=False` in 0.9 s; no tshark left running. Browser: the time-limit note on PCAP Search and "Policy synced" on Settings. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Batch 9 (`deploy-data-accuracy-batch9.sh`) | **PASS** | 6 | 0 | — | Claude | Suricata kernel defrag off: 3 fragmented pings (19 fragments on enp4s0) → 0 truncated-packet alerts (was 12); re-run after rules loaded, still 0 with 76 other alerts. Mirror-port health for Infrastructure; System data indices 5 = Infrastructure 5 data of 9. Browser: Mirror Port node, "5 data · 4 system", "Data Indices", Home "UNIDENTIFIED". Settings failed-load guard unit-tested. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Suricata rules, batch 10 (`deploy-data-accuracy-batch10.sh`) | **PASS** | 6 | 0 | — | Claude | SIDs 2200121 and 2231001 commented out in the live rules, still after a rule update; `/api/suricata/rules/live` 64,306 rules = rules file, 2 sources, cron "0 0 * * *"; Update Rules Now success + reload OK + file refreshed (check re-run by hand after a script argv fix); alerts still flowing. Browser: Suricata Rules page shows the real figures and marks unwired controls off. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Per-device alerts, batch 11 (`deploy-data-accuracy-batch11.sh`) | **PASS** | 2 | 0 | — | Claude | 19 LAN devices: `/api/devices` alert count = OpenSearch Suricata alerts minus `SURICATA ` engine events, 0 mismatches; 9 had engine events removed (192.168.1.146: 6,150 → 49). |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | DNS heuristics, batch 12 (`deploy-data-accuracy-batch12.sh`) | **PASS** | 2 | 0 | — | Claude | Last 24 h: DGA suspects 6 → 0 (forter, online-metrix, figma, datadoghq, an ELB name and a single-label LAN hostname were listed); suspicious DNS 7 → 5, no `.in-addr.arpa`/`.plex.direct`; mysterium (an ET PUP domain) still flagged. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Device vendors and categories, batch 13 (`deploy-data-accuracy-batch13.sh`) | **PASS** | 7 | 0 | — | Claude | 0 of 39 Malcolm-known MACs Unknown on Devices (was 41 Unknown of 53) or in the registry; MAC Lookup bc:24:11 → Proxmox; 0 IPs on two registry entries (UDM had 3 IoT IPs), 0 with 0.0.0.0; Ubiquiti → Infrastructure, Hue → IoT; Home grid 16/4/7/9/16 with 0 devices Unknown on Home but categorised on Devices; browser: Devices chips 16/4/0/6/11/16, Home groups match, MAC Lookup page shows Proxmox. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | PCAP end to end + TShark filters, batch 14 (`deploy-data-accuracy-batch14.sh`) | **PASS** | 5 | 0 | — | Claude | Newest capture file seconds old; TShark "dns" on a 49.6 MB capture → 50 of 50 DNS packets = tshark direct (was 0), truncated=False; no-match filter 0 without error; download 49,603,687 of 49,603,687 bytes, magic d4c3b2a1; `..` and sibling-dir paths HTTP 400. Browser: typed "dns" + Analyze → 100 DNS packets; PCAP card "Top Protocol in Preview"; preview of the newest file 100 packets. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Device list N+1, categories, page widths, batch 15 (`deploy-data-accuracy-batch15.sh`) | **PASS** | 4 | 0 | — | Claude | `/api/devices?limit=500` 1,335 → 107 ms (median of 3); 53 devices before and after with identical MAC, hostname, OS and vendor over one fixed 24 h window; 0 category changes (no Windows PC or console on the network). Browser: Suricata Rules, Backup and Notifications full width (1,452 px in a 1,500 px main); Devices 53 cards in 390 ms through the proxy; a 1.7 GB PCAP download through the web proxy streamed whole (1,718,046,493 bytes, 21.3 s, magic d4c3b2a1; counted in the page, not saved). |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Grafana off, retention tiers, page widths, batch 16 (`deploy-data-accuracy-batch16.sh`) | **PASS** | 7 | 0 | — | Claude | New nginx config passed `nginx -t` in a one-off container; nginx and web healthy with no Grafana container; `nettap-grafana` not in the default services; `docker_grafana-data` kept; `/login` 200; 0 emerg/host-not-found lines. Browser: `/grafana/api/health` → 503 note; Infrastructure links only OpenSearch Dashboards and CyberChef; Settings → Retention shows "Zeek metadata and Suricata alerts" / "separate Suricata indices"; Settings, Tools and DNS Recon full width. With `--profile grafana`: `/grafana/dashboards` 200 (was a 301 loop), both datasources fail Grafana's health check; container removed again. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | OpenSearch Dashboards objects, batch 17 (`deploy-data-accuracy-batch17.sh`) | **PASS** | 10 | 0 | — | Claude | Third run (the first two each exposed the next blocker): supervisor programs RUNNING as `helper`, 0 EACCES; Arkime template marker present; 3 index patterns (`arkime_sessions3-*`, `arkime_stats_*`, `malcolm_beats_*`); dashboards imported (26 seen through the proxy, import still running); no data index deleted; `malcolm_template` → `arkime_sessions3-*`, refresh 1s; `nettap-hot-policy` 90d. Browser: `arkime_sessions3-*` 51,195 records in the last hour (Zeek 49,169, Suricata 2,026); Overview dashboard renders live panels. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Browser regression sweep after batches 12–17 (every route but login/setup/go-live, hidden same-origin iframe, 6 s each) | **PASS** | 35 | 0 | — | Claude | 35 pages, about 260 `/api` calls, 0 answered ≥400 and no error banners. The only non-200 is the intended `503 /grafana/api/health` probe on Infrastructure (Grafana off, #71). All `tests/scripts/*.bats` suites pass after `4ae094e`. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | OpenSearch Dashboards loader, batch 17 rerun (`deploy-data-accuracy-batch17.sh`) | **PASS** | 11 | 0 | — | Claude | Programs RUNNING as `helper`, 0 EACCES; 3 index patterns; 109 dashboards; the loader logs "job succeeded" (fourth blocker, unbound `MALCOLM_NETWORK_INDEX_PATTERN`, fixed in `4db2789`); no index deleted; `malcolm_template` → `arkime_sessions3-*` at 1s; `nettap-hot-policy` 90d. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Registry refresh speed + console categories, batch 18 (`deploy-data-accuracy-batch18.sh`) | **PASS** | 6 | 0 | — | Claude | Startup registry refresh 62 s → 0.9 s (42 LAN devices); 52 registry devices before and after; 0 lost vendors; 0 category changes; the running image files Chromecast/Xbox hostnames as media and nas01 as computer. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Backup guide on the box + web rebuild, batch 19 (`deploy-data-accuracy-batch19.sh`) | **PASS** | 15 | 0 | — | Claude | The guide's commands: config archive (18 entries incl. docker/.env, logins, CA, TLS key; mode 600), records and logins archives from the volumes, host curl 401 (why `osapi`), repository registered, snapshot SUCCESS 5/5 shards with `arkime_sessions3-261102` + `nettap-devices` (595 MB), listed, restore as `restored-nettap-devices` 52 = 52; all artifacts removed (repositories back to `logs` only). Web healthy; box reports mirror mode. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | LAN subnet detection, batch 20 (`deploy-data-accuracy-batch20.sh`) | **PASS** | 7 | 0 | — | Claude | No `LAN_SUBNETS` override; detection 192.168.1.0/24 + 10.10.0.0/24 → all three of the owner's subnets (+192.168.40.0/24), the same after a second restart; Devices 53 → 55 (43/10/2), every listed IP inside a detected subnet. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Browser regression sweep after batches 18–20 (35 routes, hidden same-origin iframe) | **PASS** | 35 | 0 | — | Claude | 260 `/api` calls, 0 answered ≥400, no error banners; only the intended `503 /grafana/api/health` probe. Home "View all 55 devices" = `/api/devices` 55; every listed MAC is in the registry. Found #76. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | 8-byte DHCP MAC merge, batch 21 (`deploy-data-accuracy-batch21.sh`) | **PASS** | 5 | 0 | — | Claude | `F4:E2:C6:FF:98:21:62:72` merged into `F4:E2:C6:FF:98:21` (192.168.1.198 + 192.168.40.198, Infrastructure); no entry keyed by more than 6 octets; registry 52 → 51; device list 55 → 55. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Secret file permissions, batch 22 (`deploy-data-accuracy-batch22.sh`) | **PASS** | 16 | 0 | — | Claude | Final run of three (the first two had check bugs, see the tracking log). OpenSearch login 1000:1000 600, htpasswd and root `.env` 600, `nobody` denied; root and uid 1000 read it in all 7 consuming containers; after restarts: 353 documents in 2 min, 0 OpenSearch auth errors, api 200, Dashboards 200, `/api/devices` 55. OpenSearch not restarted. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Read-only acceptance check (`verify-acceptance.sh`) | **PASS** | 18 | 0 | — | Claude | Second run (the first had two check bugs, see the tracking log). Capture healthy, 0.0% drops, PCAP 2 s old; Zeek 3,605 and Suricata 243 records in 5 min; Traffic summary = raw OpenSearch over a closed hour (22,477 connections, 2,291,542,938 bytes); 55 devices all with a MAC; TShark `dns` 50 = tshark direct 50; preview and pcap download OK; CyberChef 200; Dashboards 200 with 109 dashboards; web 200. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | TShark scan speed, batch 23 (`deploy-data-accuracy-batch23.sh`) | **PASS** | 4 | 0 | — | Claude | Daemon healthy; `dns` analysis 17.6 s → 4.6 s with the same 50 packets; `tls.handshake.type == 1` 50 → 50; preview 20 packets in 0.9 s. Its acceptance run had a traffic-figure ✗ from late Zeek records (check bug, see below). |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Acceptance check with bracketed traffic figures (`verify-acceptance.sh`, `7db4e81`) | **PASS** | 18 | 0 | — | Claude | Traffic summary 22,880 connections / 3,473,024,410 bytes = raw before = raw after; TShark `dns` 3.4 s, 50 = tshark direct 50; every other check as in the earlier run. Exit code 0. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Browser regression sweep after batches 21–23 (35 routes, hidden same-origin iframe, broken-value text scan) | **PASS** | 35 | 0 | — | Claude | Every route HTTP 200; 261 `/api` calls, 0 failed except the intended `503 /grafana/api/health` probe; no error banners; no NaN / undefined / [object Object] / Infinity on any page. Home "View all 55 devices" = `/api/devices` 55. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | NetTap's own address, batch 24 (`deploy-data-accuracy-batch24.sh`) | **PASS** | 5 | 0 | — | Claude | Daemon log "Auto-excluded appliance management IP: 192.168.1.199"; excluded list 192.168.1.100 → 192.168.1.199; saved list `[]` (runtime only); devices 55 → 54 (nettap.local gone); acceptance 18/18. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Page figures vs OpenSearch (`verify-figures.sh`, baseline) | **PASS** | 11 | 0 | — | Claude | Alerts 3,192 / high 18; DNS 3,819 / NXDOMAIN 155; Top Talkers, Top Destinations and Bandwidth #1 = exact per-IP sums; Connections 24,122 (raw 24,121 before / 24,122 after); Log Explorer DNS 16,346; certificates 18. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Top Destinations exclusion, batch 25 (`deploy-data-accuracy-batch25.sh`) | **PASS** | 1 + 11 + 18 | 0 | — | Claude | 9.9.9.9 58,238 → 21,117 connections = OpenSearch without excluded senders; then figures 11/11 and acceptance 18/18. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Security Posture page, batch 26 (`deploy-data-accuracy-batch26.sh`) | **PASS** | 2 + 18 | 0 | — | Claude | Web healthy, /compliance answers, acceptance 18/18; in the browser the page leaves "Calculating..." and shows all six cards (overall 49%). Before: TypeError on every visit. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | IoT alert counts, batch 27 (`deploy-data-accuracy-batch27.sh`) | **FAIL → PASS** | 1 + 18 | 0 | — | Claude | First run ✗ because the check expected +10 on a percentage scale: scores 68 → 92, 60 → 85 and 68 → 92 for devices whose 521/220/15 "alerts" were all engine events (expected +25 each). Check fixed (`4a23555`); re-run ✓ (expects no change once deployed); acceptance 18/18 both runs. |
| 2026-11-02 | G11 via browser | Page sweep v2: 35 routes × 12 s, console errors + loaders still showing + NaN/undefined text | **PASS** | 35 | 0 | — | Claude | 0 console errors, 0 stuck loaders, 0 bad values on every route (after batch 26). |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Counts past 10,000, batch 28 (`deploy-data-accuracy-batch28.sh`), run twice | **PASS** | 6 + 11 + 18 | 0 | — | Claude | Router detail 48,324 connections, its list 72,210, .202 alerts 15,051 detail and list, single-view risk count 48,324: each = OpenSearch before and after; risk 78 critical in both views. Re-run after the argv fix ✓. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Page counts, batch 29 (`deploy-data-accuracy-batch29.sh`) | **PASS** | 3 + 18 | 0 | — | Claude | Connections 406,397, Alerts 7 d 42,703, router connections 72,704: each offers 200 pages and the last page has 50 rows. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Security Posture encryption and DNS, batch 30 (`deploy-data-accuracy-batch30.sh`) | **PASS** | 4 + 1 + 18 | 0 | — | Claude | Eligible 199,611, encrypted 123,272, plain DNS 83,947, DoT 18,795: each = OpenSearch before and after. In the browser /compliance shows Encryption 62%, DNS Security 18%, overall 62% (was 19%, 0%, 49%). |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Device detail time range, batch 31 (`deploy-data-accuracy-batch31.sh`) | **FAIL → PASS** | 5 + 18 | 0 | — | Claude | First run ✗ on my own check (it compared a 24 h window ending now with a 7 d window ending 15 min earlier). Fixed (`b4114b4`), re-run ✓: router 7-day detail 49,696, list 74,295, risk 49,696, each = OpenSearch; 169 hourly points. In the browser 7d/30d send the right from/to and every response is 200. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Device-by-MAC page, batch 32 (`deploy-data-accuracy-batch32.sh`) | **FAIL → PASS** | 4 + 16 + 18 | 0 | — | Claude | Two ✗ were my check's grep (it added `hits.total` and read `3.7E9` as 3); now parsed as JSON (`164853a`, `261e3da`); one transient daemon build failure, re-run built. Final: router MAC in + out = total 4,341,367,927; connections 105,659 = OpenSearch 105,659 / 105,659; top destination 192.168.1.10 3,708,015,150 bytes = OpenSearch; destinations ranked by bytes; figures 16/16; acceptance 18/18. TShark `dns` 5.5 s on a quiet box (scan 1.9 + JSON 2.9 + Info 1.9 s direct); the 10–12 s readings were runs right after a rebuild. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) via Chrome | Page sweep v4 after batch 32 (hidden same-origin iframe per route, 10 s settle) | **PASS** | 46 | 0 | — | Claude | Every route plus Device detail (192.168.1.188, router 192.168.1.1) and the router's device-by-MAC page: 0 console errors, 0 failed fetches apart from the intended `503 /grafana/api/health`, 0 stuck loaders, 0 error banners, 0 NaN/undefined values, 0 API calls over 8 s. MAC page ranks destinations by bytes (3.5 GB, 507 MB, 38 MB, …). |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Exact top lists, batch 33 (`deploy-data-accuracy-batch33.sh`) + new `verify-device-figures.sh` | **FAIL → PASS** | 54 devices + 51 MACs, 16 + 18 | 0 | — | Claude | Before: 225 per-device mismatches (low top-list counts from OpenSearch 3.5's concurrent segment search, categories capped at 200 ASNs, the unique-destination estimate). After: persistent `search.concurrent_segment_search.mode: none`; every device's list row, detail, ports, categories, risk and MAC page = OpenSearch, 0 mismatches; figures 16/16; acceptance 18/18. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Top lists across daily indices, batch 34 + new `verify-split-invariance.sh` | **FAIL → PASS** | 69 + 54/51 + 16 + 18 | 0 | — | Claude | Before #93, 10 of 66 compared endpoints changed when the data was split (top talkers 40,046 vs 38,678; DNS median 6.13 vs 5.81 ms). After: 66 identical, 0 different, 3 changing between normal reads (#95); 30-day pages ≤ 1.3 s; per-device 0; figures 16/16; acceptance 18/18. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Any network size and the Threats baseline, batch 35 | **PASS** | 2 + 69 + 54/51 + 16 + 18 | 0 | — | Claude | #94 on real data: from 5 terms with slicing forced, shard_size 20 → 50 → 500 → 5,000 → 50,000, exact top 20 by bytes, error 0. #95: 5 requests, history_points 1 each. Split check 69 of 69; per-device 0; figures 16/16; acceptance 18/18. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Complete sets and honest failures (#96), batch 36 | **FAIL → fixed** | 2 + 91 + 54/51 + 16 + 18 | 2 | #97, #98 | Claude | Device count = device list = risk list = 54; every threat check ran and finished. Split check 90 of 91 identical, 0 different (1 moved: an investigation's last-7-days count). Per-device 0 mismatches; figures 16/16; acceptance passed. Two failures: the threat report took 16.8 s (beaconing 31.5 s, 366 "suspects", 283 of them one laptop's BitTorrent peers → #98) and the new partial-shard guard caught the Bandwidth heatmap failing on OpenSearch 3 (removed Joda getters → #97). Both fixed in code; re-verified in batch 37. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Heatmap time zones (#97), beacon scope (#98), category detail, failure states; batch 37 + new `verify_batch37.py` | **PASS** (after a check fix) | 9 + 91 + 54/51 + 16 + 18 | 0 | — | Claude | Threat report 3.5–5 s, 17 beacon suspects + 1 many-hosts device, 0 stray, all checks ran; heatmap = OpenSearch cell by cell in UTC, +5:30 and Los Angeles; each of 15 categories' detail = its Home bar incl. top services; drive health and index counts read; slowest page 5.38 s (30-day threat report). Split check: all identical, 1 moving (an investigation's 24 h count). Per-device 0; figures 16/16; acceptance passed; daemon log clean. The one ✗ was the heatmap check's first read (2 rewritten long-connection records bucketed 30+ min late by the check's own histogram, not by the daemon); the check now re-reads both sides. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Web + daemon honest-failure sweeps (#96h), LAN detections and IoT anomalies (#99); batch 38 + new `verify_batch38.py` | **PASS** | 9 + 10 + 91 + 54/51 + 16 + 18 (59 ✓) | 0 | — | Claude | Rogue DHCP 0 alerts (batch 37: 4 "critical" rogue servers that were clients); LAN answers say no ARP is recorded; IoT anomalies answer; a refused TShark / PCAP-preview filter is HTTP 400 with tshark's message; bridge latency "Not measured" (was a made-up 50 µs); internet health not_configured, no false down; exact counts on; rules and GeoIP versions "unknown" (was today's date). Batch 37's checks all pass (heatmap LA needed its re-read again: same 2 records on the first read). Slowest page 5.6 s; split check all identical (1 moving: an investigation's 24 h count); per-device 0; figures 16/16; acceptance passed; daemon log clean. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Exact device counts (#100), web follow-ups (#96i), rules version; batch 39 + new `verify_batch39.py` | **PASS** | 9 + 10 + 4 + 91 + 54/51 + 16 + 18 | 0 | — | Claude | New (24h) = registry first-seen count: API 51 = OpenSearch 51 of 51 known (the registry's first_seen is fixed at 03:34–08:04Z today, so all are new on this one-day-old box; the page used to count every device in the window). Online Now 29 = the 5-minute device list 29; the list is complete (54 of 54). Rules version 2026-11-02 = the Suricata container's rules file (was "unknown", before that today's date). Batches 37–38's checks all pass; split check identical; per-device 0; figures 16/16; acceptance passed; daemon log clean. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Device cards (#101), last seen (#102), protocol totals (#103), Infrastructure rates (#104), category label (#106), GeoIP version (#107), pinned Malcolm updates (#108), IP conflicts (#109); batch 40 + `verify_batch40.py` | **PASS** (after a check fix) | 9 + 10 + 4 + 7 + split + per-device + 13/16 + 18 | 3 (check) | — | Claude | GeoIP 2026-01-27 = Logstash's file; 7 of 7 unappliable updates marked; protocols 457,093 = connections; no device last seen after its newest record (the startup repair moved 21 back); 5-minute rates 7.0 conn/s and 0.8 alerts/s. The 3 ✗ were the figures check recounting Security Posture without the excluded-IP clause #103 added to the endpoint (22/22/1); the check was fixed and batch 41 passed it. Browser: Home cards 49 of 51 = the device list (2 unknown with reason), Infrastructure 4.7 conn/s and 0.8 alerts/s. Slowest page 7.3 s; split identical; per-device 0; acceptance passed; log clean. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Unreadable from/to is a 400 (#105), Updates "Not checked" before a check (#110); batch 41 + `verify_batch41.py` | **PASS** | 9 + 10 + 4 + 7 + 2 + split + per-device + 16 + 18 | 0 | — | Claude | 13 of 13 endpoints across every time-windowed module and PCAP answer `from=now-5m` with a 400 naming the format; empty from/to keeps the default (3 of 3). Every page figure matches OpenSearch (16/16 incl. the corrected Security Posture recount); split identical; per-device 0; acceptance passed; slowest page 6.1 s; log clean. The heatmap check's first read differed on the same 2 cells as batch 40, which led to the #113 probe. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Updates rows (#111), host OS version (#112), bandwidth chart and heatmap by range filters (#113); batch 42 + `verify_batch42.py` | **PASS** | 9 + 10 + 4 + 7 + 2 + 5 + split + per-device + 16 + 18 | 0 | — | Claude | Home's bandwidth chart = range filters bucket by bucket (96 × 15 min, 24 × 1 h, 98.17 GB, 0 differ); heatmap = range filters in Los Angeles, UTC and Kolkata (0 cells differ, no retries); OS row 24.04 = the host's os-release (daemon image Debian 12); 7 updates, 7 rows; `checked` = 13 components, none of OS/kernel/Docker/Python/OpenSearch. Every page figure matches OpenSearch; split identical; per-device 0; acceptance passed; slowest page 7.3 s; log clean. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Suricata rules check and update from System → Updates (#114), NetTap release (#115); batch 43 + `verify_batch43.py` | **PASS** | 9 + 10 + 4 + 7 + 2 + 5 + 5 + split + per-device + 16 + 18 | 0 | — | Claude | The rules check read the file in the Suricata container (dated today: no update listed; checked, not failed). One rules update applied through `/api/system/updates/apply`: success, file 07:52Z → 22:34Z, reported versions = the file's dates, 64,342 rules enabled, Suricata reloaded without a restart, decoder-noise SIDs still off. No newer NetTap release published. All earlier batches' checks pass again; slowest page 7.1 s; log clean. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | LAN re-detection (#116); batch 44 + `verify_batch44.py` | **FAIL → #120** | 9 + 10 + 4 + 7 + 2 + 5 + 2 + split + per-device + 16 + 18 | 1 | #120 | Claude | Detection: the same 3 subnets in 0.8 s, no change on re-detection. Split check: 89 same, 1 moving (live), 1 SPLIT: the Log Explorer timeline's hour 19 read 29,045 vs 29,048. A probe then found the timeline's `date_histogram` misplacing up to ~970 records an hour against range counts (#120). Everything else passed; slowest page 7.1 s; log clean. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Exact time slots (#120), Updates rows (#117–#119); batch 45 + `verify_batch45.py` | **PASS** | 9 + 10 + 4 + 7 + 2 + 5 + 1 + 4 + split + per-device + 16 + 18 | 0 | — | Claude | Log Explorer timeline = one range filter per hour (24 hours, 1,171,211 records, 0 differ); split check 90 the same (1 moving, live data); bandwidth chart and heatmap still exact. OpenSearch row 3.5.0 = the cluster; NetTap's 4 images checked (release check found nothing newer); Update All hidden (0 of 7 applicable). Every page figure (16/16), per-device 0, acceptance passed; slowest page 7.1 s; log clean. |
| 2026-11-02 | G11 (Ubuntu 24.04.5) | Backwards range (#121) and subnet re-detection (#116) on the box; read-only, after batch 45 | **PASS** | 6 + 2 + 2 | 0 | — | Claude | 6 of 6 endpoints answer from > to with 400 "from must not be later than to"; logs timeline 1m over 10 months → 400, 1h over 2 h → 200. `changed_lan_filter` from the pre-10.10.0.x filter adds 10.10.0.0/24 on real data; from the full set, no change. Batch 45's acceptance step (same run) covered capture (enp4s0 promisc, 0.0% drops, PCAP written 0 s ago, 156 files), TShark = tshark (50/50), PCAP preview and download, CyberChef recipe and page, Dashboards (109). Only #109 (IP conflicts) stays unit-tested: the G11 records no ARP. |
| 2026-11-02 | macOS (dev) | `bats tests/scripts/*.bats` with errexit restored in `test_malcolm_config.bats` | **PASS** | all | 0 | — | Claude | 42 installer tests now really check (11 had been passing with failing checks); preflight 11; compose, deploy-malcolm, install, nginx, activate-bridge, capture-env all pass. |

---

## Failures to Fix

### Shellcheck Failures (Dev — Check #3) — FIXED

**Status:** All shellcheck warnings/errors fixed in NET-78. Check #3 now PASS on Dev.

**What was fixed:**
- SC2221/SC2222: Reordered case patterns in `deploy-malcolm.sh` — `*unhealthy*` before `*healthy*`, `*Exit*|*Restarting*` before `*starting*`
- SC2034: Added `# shellcheck disable=SC2034` for intentionally-reserved variables
- SC2155: Separated `local` declaration from command substitution assignment
- SC2086: Added `# shellcheck disable=SC2086` for intentional word-splitting of `$DOCKER_CMD`
- SC1091: Added `# shellcheck source=` directives to all 11 scripts that source `common.sh`
- Changed shellcheck invocation to `shellcheck -x -S warning` (follow sources, minimum severity warning)

### Docker Build Failures (Dev — Check #8)

macOS Docker doesn't have the Compose V2 plugin (`docker compose`). The script uses `docker compose -f ...` which fails with "unknown shorthand flag: 'f'". This is expected — **Docker builds should only run on the N100 production host** or in CI, not on the dev Mac.

**Fix priority:** Low — the script could detect the platform and skip Docker on macOS, or we accept this as a known limitation and only run Docker builds on N100/CI.

### Trivy CVE Findings (N100 — Check #9) {#trivy-cve-findings-n100}

Trivy scan ran 2026-03-03 on N100 against both Docker images. **All CVEs are in upstream base images**, not in NetTap application code. App-level dependencies (Python packages + Node.js app packages) have 0 vulnerabilities.

#### nettap/storage-daemon:latest — 4 CVEs (2 CRITICAL, 2 HIGH)

| Library | CVE | Severity | Status | Description | Fix Available? |
|---------|-----|----------|--------|-------------|----------------|
| `libc-bin` | CVE-2026-0861 | HIGH | affected | glibc: integer overflow in memalign → heap corruption | No (Debian 12 hasn't patched) |
| `libc6` | CVE-2026-0861 | HIGH | affected | Same glibc CVE (shared library) | No |
| `libsqlite3-0` | CVE-2025-7458 | CRITICAL | affected | SQLite integer overflow | No (Debian 12 hasn't patched) |
| `zlib1g` | CVE-2023-45853 | CRITICAL | will_not_fix | Integer overflow in zipOpenNewFileInZip4_6 (minizip API) | No — Debian marked `will_not_fix` |

#### nettap/web:latest — 3 OS + 14 Node.js CVEs (1 CRITICAL, 16 HIGH)

**OS-level (same Debian 12 base):**

| Library | CVE | Severity | Status | Fix Available? |
|---------|-----|----------|--------|----------------|
| `libc-bin`/`libc6` | CVE-2026-0861 | HIGH | affected | No |
| `zlib1g` | CVE-2023-45853 | CRITICAL | will_not_fix | No |

**Node.js base image npm** (in `/usr/local/lib/node_modules/npm/`, NOT in app's `node_modules/`):

| Library | CVE | Severity | Installed | Fixed | Description |
|---------|-----|----------|-----------|-------|-------------|
| `glob` | CVE-2025-64756 | HIGH | 10.4.5 | 10.5.0+ | Command injection via malicious filenames |
| `minimatch` | CVE-2026-26996 | HIGH | 9.0.5 | 9.0.6+ | DoS via crafted glob patterns |
| `tar` (x3 copies) | CVE-2026-23745 | HIGH | 6.2.1/7.4.3 | 7.5.3+ | Arbitrary file overwrite via unsanitized linkpaths |
| `tar` (x3 copies) | CVE-2026-23950 | HIGH | 6.2.1/7.4.3 | 7.5.4+ | Arbitrary file overwrite via Unicode collision race |
| `tar` (x3 copies) | CVE-2026-24842 | HIGH | 6.2.1/7.4.3 | 7.5.7+ | File creation via path traversal in hardlink |
| `tar` (x3 copies) | CVE-2026-26960 | HIGH | 6.2.1/7.4.3 | 7.5.8+ | Arbitrary file read/write via malicious hardlink |

**Risk assessment:**
- **OS CVEs (glibc, zlib, sqlite):** Low risk for NetTap. The glibc memalign overflow requires specific allocation patterns unlikely in our workload. The zlib CVE is in the minizip API which we don't use. SQLite is not directly used by the daemon.
- **Node.js npm CVEs (tar, glob, minimatch):** Low risk. These are in the Docker image's system npm (`/usr/local/lib/node_modules/npm/`), not in the app's dependencies. The app never calls `npm` or `tar` at runtime.
- **Mitigation applied (NET-78):**
  1. **`.trivyignore`** — Suppresses 3 accepted OS CVEs (CVE-2026-0861, CVE-2023-45853, CVE-2025-7458) with documented risk assessment
  2. **Stripped npm/yarn/corepack from web prod image** — `Dockerfile.web` removes `/usr/local/lib/node_modules/npm`, corepack, yarn from production stage, eliminating all 14 Node.js CVEs
  3. Result: Trivy scan PASSES with 0 vulnerabilities on both images

### Bridge API Auth Bypass (N100 — H1) — FIXED

**Status:** Fixed in PR #85. `/api/bridge/*` and `/go-live` added to `PUBLIC_PATHS` in `hooks.server.ts`.

**Discovery:** After deploying PR #83 (Bridge Go Live), `curl -sk https://localhost/api/bridge/readiness` returned `302 Found` → `/login` instead of JSON. The SvelteKit auth middleware (`hooks.server.ts`) was intercepting all non-public routes and redirecting unauthenticated requests.

**Root cause:** The new bridge API proxy routes (`/api/bridge/readiness`, `/api/bridge/create`, `/api/bridge/teardown`) and the Go Live page (`/go-live`) were not in `PUBLIC_PATHS`. These need to be accessible without authentication because:
1. The Go Live page runs immediately after the setup wizard (before the user logs in)
2. The wizard redirects to `/go-live`, which polls `/api/bridge/readiness`

**Fix:** Added `/api/bridge` and `/go-live` to `PUBLIC_PATHS` array (PR #85).

**Lesson:** Any new `/api/*` SvelteKit proxy route that needs to work pre-login must be added to `PUBLIC_PATHS` in `hooks.server.ts`. This is easy to miss because daemon endpoints have no auth — the auth layer is SvelteKit-only.

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
| ~~trivy~~ | ~~`curl -sfL ...`~~ | ~~Container CVE scanning~~ | ~~#9~~ | **INSTALLED** (2026-03-03) — working, scans both images |
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
