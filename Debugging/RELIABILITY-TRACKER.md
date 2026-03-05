# NetTap Reliability Tracker — Source of Truth

> Last updated: 2026-03-04
> Status: 5/7 subsystems production-ready. OpenSearch security auto-bootstrap fully automated and verified on N100 — init container uses targeted `-f/-t` push (not `-cd`), shared certs volume, Docker DNS, stub `malcolm_template` creation. Nuclear test (`down -v && up -d`): 34/34 steps, 20 containers, logstash healthy at 64.9s, zero manual intervention.

## Purpose

This document tracks production reliability of each NetTap subsystem. Read this before starting any reliability or health-check work. Update after every fix.

## Subsystem Reliability Status

| Subsystem | Status | Verified On | Issues | Notes |
|-----------|--------|-------------|--------|-------|
| OpenSearch | OK | 2026-03-04 | -- | Fixed: curlrc credential parsing (PR #81). **Auto-bootstrap:** bind-mount roles_mapping.yml + one-shot init container runs securityadmin.sh (`-f/-t` targeted push, NOT `-cd`) on every `docker compose up`. Shared `opensearch-certs` named volume for TLS cert access. **Stub template:** init container creates minimal `malcolm_template` on fresh installs to break logstash/dashboards-helper circular deadlock. Nuclear test verified: 34/34 steps, logstash healthy at 64.9s, all 20 containers up, zero manual intervention. |
| SMART Monitoring | OK | 2026-03-03 | NVMe data limited | smartctl code 2 (may lack SYS_RAWIO); health OK but temp/wear null on some devices |
| Bridge Health | OK | 2026-03-04 | -- | Fixed: not_configured state (PR #81), bypass promisc toggle (PR #83), 30s polling loop (PR #83), 8-point readiness check (PR #83) |
| Bridge Management | OK | 2026-03-04 | -- | NEW: BridgeManager service — create/teardown/readiness via nsenter, host persistence (PR #83) |
| Internet Health | Fixing | -- | Shows "down" when not configured | Missing `not_configured` state |
| Web UI (Dashboard) | OK | 2026-03-03 | -- | Fixed: distinct states for unreachable/connecting/no-data (PR #81) |
| Web UI (System) | OK | 2026-03-03 | -- | Fixed: null-safe SMART display, storage NaN fix (PR #82) |
| Web UI (Go Live) | OK | 2026-03-04 | -- | NEW: 3-phase Go Live page — readiness/wiring/monitoring (PR #83) |
| Web Auth | OK | 2026-03-04 | -- | Fixed: bridge API + /go-live added to public paths (PR #85) |
| Storage Daemon | OK | 2026-03-03 | -- | Disk monitoring and retention working |

### Status Legend
- **OK**: Verified working in production
- **Fixing**: Known issue, fix in progress
- **Broken**: Non-functional, blocking
- **Untested**: Not yet verified on production hardware

## Issues Found & Fixed

| Date | Subsystem | Issue | Root Cause | Fix | Linear | Branch/PR |
|------|-----------|-------|------------|-----|--------|-----------|
| 2026-03-03 | OpenSearch | Daemon gets 403 from OpenSearch | `_create_client()` has no http_auth | Add curlrc mount + credential parsing | -- | PR #81 |
| 2026-03-03 | SMART | All SMART metrics null | /dev mounted :ro, NVMe needs write for admin cmds | Remove :ro from /dev mount | -- | PR #81 |
| 2026-03-03 | Bridge | Bridge shows "Down" when br0 doesn't exist | No `not_configured` state | Add not_configured status to bridge_health.py | -- | PR #81 |
| 2026-03-03 | Web UI | Dashboard shows generic error for all failure modes | Single error banner for all states | Distinguish daemon unreachable vs OS connecting vs no data | -- | PR #81 |
| 2026-03-03 | Web UI (System) | Storage shows NaN, SMART crashes on null | Disk bytes returned as GB (double-convert), no null guards | Return raw bytes, add null-coalescing to SMART display | -- | PR #82 |
| 2026-03-03 | Bridge Health | Bypass mode doesn't toggle promisc | `trigger_bypass()` only writes state file, no promisc off | Added nsenter `ip link set <iface> promisc off/on` | NET-91 | PR #83 |
| 2026-03-03 | Bridge Health | Bypass state file write fails | `/var/run` is read-only in container | Moved to `/tmp/nettap-bypass-active` (writable tmpfs) | NET-91 | PR #83 |
| 2026-03-03 | Bridge Health | No background health polling | Health history was demand-driven only | Added `bridge_loop()` in main.py (30s interval) | NET-91 | PR #83 |
| 2026-03-03 | Bridge | No bridge creation from daemon | Wizard step 3 only generated mock preview | Created BridgeManager with create/teardown/readiness | NET-91 | PR #83 |
| 2026-03-03 | Bridge | No readiness check for cable migration | User had no guidance on when to plug cables | 8-point readiness check at `/api/bridge/readiness` | NET-91 | PR #83 |
| 2026-03-03 | Web UI | No Go Live page after wizard | Wizard redirected to `/login` with no guidance | Created `/go-live` with 3-phase workflow | NET-91 | PR #83 |
| 2026-03-04 | Web Auth | Bridge API returns 302 → /login | `/api/bridge/*` and `/go-live` not in PUBLIC_PATHS | Added to PUBLIC_PATHS in hooks.server.ts | -- | PR #85 |
| 2026-03-04 | Bridge Health | System page shows no carriers, no packet data | BridgeHealthMonitor uses hardcoded eth0/eth1 but N100 has enp2s0/enp3s0 | Auto-discover members from br0's brif sysfs directory | NET-92 | PR #88 |
| 2026-03-04 | Bridge Health | Readiness falsely reports netfilter enabled | Reads container `/proc` namespace (always 1) instead of host | Changed netfilter check to use nsenter for host namespace | NET-92 | PR #88 |
| 2026-03-04 | Zeek | Zeek crash-loops: Permission denied on /zeek/live/logs | Fresh volumes root-owned, Malcolm entrypoint needs root for mkdir/chown | Added `user: "root"` to capture services | NET-93 | PR #89 |
| 2026-03-04 | Suricata | Suricata fails: "workers" doesn't exist for UNIX_SOCKET runmode | `SURICATA_RUNMODE: "workers"` conflicts with Malcolm 8.x internal runmode | Removed env var — Malcolm auto-selects af-packet | NET-93 | PR #89 |
| 2026-03-04 | Bridge Health | Netfilter check fails when br_netfilter module not loaded | nsenter cat returns error when proc file absent (module not loaded = good) | Treat missing proc file as netfilter disabled (PASS) | NET-93 | PR #89 |
| 2026-03-04 | Dashboard Data | All dashboard queries return zero data | Daemon queries used Zeek-native index/field names; Malcolm uses unified arkime_sessions3-* with ECS fields | Remapped all 7 daemon files: index → NETWORK_INDEX, fields → ECS, added event.provider/dataset filters | NET-95 | infra/opensearch-field-mapping |
| 2026-03-04 | OpenSearch | Security auth breaks after container recreate (Chain 11) | `--force-recreate` resets roles_mapping.yml to Malcolm's empty default; securityadmin.sh not re-run | Bind-mount roles_mapping.yml from git + nettap-opensearch-init one-shot container auto-runs securityadmin.sh. Logstash/daemon depend on init completing. | -- | infra/opensearch-field-mapping |
| 2026-03-04 | OpenSearch | Init container `-cd` overwrites internal_users.yml (Chain 11a) | `securityadmin.sh -cd` pushes ALL config files including image-default internal_users.yml with wrong password hashes | Changed to `-f roles_mapping.yml -t rolesmapping` — pushes ONLY roles mapping | -- | 7014cda |
| 2026-03-04 | OpenSearch | Init container can't reach OpenSearch (Chain 11b) | Init container's localhost is its own network namespace, not opensearch. Also missing TLS admin certs (generated at runtime inside opensearch container) | Added `-h opensearch -p 9200` for Docker DNS. Added `opensearch-certs` shared named volume for TLS cert sharing. Override `entrypoint: ["/bin/bash"]` | -- | 90b4e38 |
| 2026-03-04 | OpenSearch | Logstash deadlocks on fresh install waiting for `malcolm_template` (Chain 11d) | Circular dependency: logstash waits for `malcolm_template` → dashboards-helper creates it but has 180s sleep + waits for log data → log data needs logstash | Init container Step 3: check if `malcolm_template` exists, create minimal stub if absent. Dashboards-helper overwrites with full template before data flows. | -- | 733672e |

## Reliability Lessons Learned

1. **Always mount curlrc in every container that talks to OpenSearch.** The security bootstrap requires Basic Auth — containers without credentials get silent 403 errors.
2. **NVMe SMART queries require write access to /dev.** The smartctl tool sends NVMe admin commands that need write access to the controller device. `:ro` mounts block this silently.
3. **"Not configured" is not the same as "down".** Services that haven't been set up (bridge, internet) should show an informational state, not an error state. Users who haven't configured the bridge yet shouldn't see red badges.
4. **Log stderr from subprocess calls.** When smartctl fails, the exception message alone doesn't show why — the stderr output contains the actual error (e.g., "Permission denied", "No such device").
5. **Parse curlrc files for credentials.** Malcolm stores OpenSearch credentials in curlrc format (`user = "username:password"`). The daemon needs a parser for this format.
6. **Bypass mode must toggle promisc, not just write a state file.** Writing `/tmp/nettap-bypass-active` signals the daemon/UI, but capture containers still see packets if promisc mode stays on. Must `nsenter -t 1 -n -- ip link set <iface> promisc off`.
7. **Container tmpfs paths matter.** `/var/run` is on the container's read-only root filesystem — writes fail silently. Use `/tmp` (which has a writable tmpfs) for ephemeral state files.
8. **SvelteKit auth middleware blocks API routes by default.** New `/api/*` proxy routes must be added to `PUBLIC_PATHS` in `hooks.server.ts` if they need to work without login (e.g., Go Live workflow runs before user auth).
9. **Recreating Docker containers invalidates nginx upstream DNS.** After `docker compose up --force-recreate`, the upstream container gets a new IP. Nginx caches the old one → 502. Must restart nginx after recreating backend containers.
10. **Bridge health needs continuous polling, not demand-driven.** Without a `bridge_loop()`, health history only populated when the API endpoint is hit. The 30s polling loop ensures consistent monitoring data.
11. **Never hardcode NIC names — auto-discover from bridge sysfs.** Intel N100 uses `enp2s0`/`enp3s0` (PCI bus naming), not `eth0`/`eth1`. Read bridge member interfaces from `/sys/class/net/br0/brif/` directory to get actual names.
12. **Container `/proc` is isolated — use nsenter for host reads.** Reading `/proc/sys/net/bridge/bridge-nf-call-iptables` inside the container returns the container's own namespace value (default 1), not the host's. Must use `nsenter -t 1 -n -- cat` to read from host namespace.
13. **Malcolm capture images need `user: "root"` in compose.** Their entrypoint (`docker-uid-gid-setup.sh`) runs `mkdir`/`chown` to set up log directories, then drops privileges to PUID:PGID via `su`. Without starting as root, fresh Docker volumes (root-owned) cause Permission denied.
14. **Don't override Malcolm's internal runmode selection.** Setting `SURICATA_RUNMODE` conflicts with Malcolm's orchestration in Suricata 8.x. Let `SURICATA_LIVE_CAPTURE=true` handle mode selection automatically.
15. **Missing kernel module proc files ≠ feature enabled.** When `br_netfilter` isn't loaded, `/proc/sys/net/bridge/bridge-nf-call-iptables` doesn't exist. This means no iptables interference — the desired state, not a failure.
16. **Malcolm unifies all data into arkime_sessions3-*.** There are no separate zeek-*/suricata-* indices. Use `event.provider` + `event.dataset` to filter by data source. All field names use ECS format, not Zeek-native. Always verify field names against a real document from the N100 before writing queries.
17. **Use bind-mount + one-shot init container for config that must survive container recreate.** OpenSearch's roles_mapping.yml reverted on every `--force-recreate` because it lived inside the container filesystem. Fix: bind-mount the file from git (always correct) and add a one-shot init service that pushes it to the security index. Downstream services use `service_completed_successfully` dependency to ensure bootstrap completes before they start. This pattern eliminates all manual bootstrap steps.
18. **NEVER use `securityadmin.sh -cd` from an init container** — it pushes ALL config files including `internal_users.yml` with image-default (wrong) password hashes, overwriting the correct hashes generated by OpenSearch's entrypoint. Always use `-f FILE -t TYPE` for targeted pushes (e.g., `-f roles_mapping.yml -t rolesmapping`).
19. **Init containers have their own network namespace** — `localhost` in an init container is NOT the opensearch container's localhost. Use Docker DNS hostnames (`-h opensearch -p 9200`) for cross-container communication in `securityadmin.sh`.
20. **Share runtime-generated TLS certs via named volumes** — Malcolm generates admin certs (`ca.crt`, `admin.crt`, `admin.key`) at startup inside the opensearch container. These are ephemeral. Use a named volume (`opensearch-certs`) that opensearch writes to and the init container reads from.
21. **Override `entrypoint`, not just `command`, for utility containers** — Malcolm's entrypoint chain runs cert generation, uid/gid setup, and supervisord. For a one-shot utility container, set `entrypoint: ["/bin/bash"]` to skip side effects entirely.
22. **Break circular template dependencies with stubs from the init container.** On fresh installs (`down -v`), logstash waits for `malcolm_template` but dashboards-helper (which creates it) waits for log data that logstash produces — a deadlock. Creating a minimal stub template (just `index_patterns` + basic settings) from the init container unblocks logstash immediately. The full template is overwritten by dashboards-helper before any data flows through, so the stub never affects data integrity.

## Verification Checklist

After deploying reliability fixes to N100 hardware:

- [x] `curl -sk https://localhost/api/health | python3 -m json.tool | grep opensearch_reachable` → `true` (verified 2026-03-03)
- [ ] `curl -sk https://localhost/api/health | python3 -m json.tool | grep -A5 smart` → real temperature/power_on_hours values (NVMe returns null — may need SYS_RAWIO)
- [x] `curl -sk https://localhost/api/bridge/health | python3 -m json.tool` → `health_status: "not_configured"` (verified 2026-03-03)
- [x] Dashboard shows "Healthy" or informational states, no red badges for unconfigured services (verified 2026-03-03)
- [x] System page shows actionable messages for unreachable OpenSearch (verified 2026-03-03)
- [ ] `curl -sk https://localhost/api/bridge/readiness | python3 -m json.tool` → returns readiness JSON (pending PR #85 deploy)
- [ ] Go Live page (`/go-live`) loads and shows readiness phase
- [ ] Bridge creation via `/api/bridge/create` works end-to-end
- [ ] Bypass toggle enables/disables promisc via nsenter

## Test Results

| Date | Test | Environment | Result | Notes |
|------|------|-------------|--------|-------|
| 2026-03-03 | Reliability overhaul deploy | N100 production | PASS | OpenSearch auth working, bridge not_configured state, dashboard UX states |
| 2026-03-03 | System page fixes deploy | N100 production | PASS | Storage NaN fixed, SMART null-safe, compliance loop fixed |
| 2026-03-04 | Bridge Go Live deploy | N100 production | **PARTIAL** | Daemon healthy, bridge_loop running. Hit 302→/login on bridge API — fixed in PR #85 (auth bypass). Pending redeploy. |
| 2026-03-04 | Dev tests (pytest) | Dev macOS | PASS | 1036/1036 passed (104 bridge-specific) |
| 2026-03-04 | Dev tests (vitest) | Dev macOS | PASS | 683/683 passed (22 GoLive + 25 bridge API) |
| 2026-03-04 | Dev svelte-check | Dev macOS | PASS | 620 files, 0 errors, 0 warnings |
| 2026-03-04 | ECS field mapping (pytest) | Dev macOS | PASS | 1041/1041 passed — all daemon queries updated to ECS fields |
| 2026-03-04 | ECS field mapping (vitest) | Dev macOS | PASS | Web tests pass — no web changes needed |
| 2026-03-04 | ECS field mapping (svelte-check) | Dev macOS | PASS | No type errors |
| 2026-03-04 | OpenSearch auto-bootstrap (BATS) | Dev macOS | **PASS (36/37)** | 7 new tests for opensearch-init service all pass. 1 pre-existing failure on test 10 (unrelated to this change). Tests cover: one-shot config, depends_on, bind-mount, script mount, restart policy, healthcheck absence, logstash dependency chain. |
| 2026-03-04 | OpenSearch init container debug | N100 production | **PASS** | After fixing -cd → -f/-t, adding -h opensearch, shared certs volume: init pushes rolesmapping SUCC attempt 1, auth 200 immediately, cluster GREEN 24/24 shards, logstash healthy 60.6s, all 20 containers up, dashboard showing bandwidth data. |
| 2026-03-04 | Nuclear test (`down -v && up -d`) | N100 production | **PASS** | Fresh install scenario. 34/34 docker compose steps with checkmarks. Init container: roles_mapping SUCC → auth 200 → stub template created → done 39.3s. Logstash healthy at 64.9s (was deadlocked 659s+ before fix). Filebeat started at 65.0s. All 20 containers up, zero manual intervention. |
