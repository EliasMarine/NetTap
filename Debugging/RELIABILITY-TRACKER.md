# NetTap Reliability Tracker — Source of Truth

> Last updated: 2026-03-04
> Status: 8/9 subsystems production-ready. **Full data pipeline VERIFIED on N100** — Zeek → Filebeat → Logstash → `arkime_sessions3-260304` → OpenSearch. opensearch-init bootstrap + index naming both working. 7,508+ docs indexed and growing.

## Purpose

This document tracks production reliability of each NetTap subsystem. Read this before starting any reliability or health-check work. Update after every fix.

## Subsystem Reliability Status

| Subsystem | Status | Verified On | Issues | Notes |
|-----------|--------|-------------|--------|-------|
| OpenSearch | OK | 2026-03-03 | -- | Fixed: curlrc credential parsing added (PR #81) |
| SMART Monitoring | OK | 2026-03-03 | NVMe data limited | smartctl code 2 (may lack SYS_RAWIO); health OK but temp/wear null on some devices |
| Bridge Health | OK | 2026-03-04 | -- | Fixed: not_configured state (PR #81), bypass promisc toggle (PR #83), 30s polling loop (PR #83), 8-point readiness check (PR #83) |
| Bridge Management | OK | 2026-03-04 | -- | NEW: BridgeManager service — create/teardown/readiness via nsenter, host persistence (PR #83) |
| Internet Health | Fixing | -- | Shows "down" when not configured | Missing `not_configured` state |
| Web UI (Dashboard) | OK | 2026-03-03 | -- | Fixed: distinct states for unreachable/connecting/no-data (PR #81) |
| Web UI (System) | OK | 2026-03-03 | -- | Fixed: null-safe SMART display, storage NaN fix (PR #82) |
| Web UI (Go Live) | OK | 2026-03-04 | -- | NEW: 3-phase Go Live page — readiness/wiring/monitoring (PR #83) |
| Web Auth | OK | 2026-03-04 | -- | Fixed: bridge API + /go-live added to public paths (PR #85) |
| Zeek Capture | OK | 2026-03-04 | -- | Fixed: entrypoint wrapper for fresh volume permissions, `user: "root"` in compose (PR #89 + develop commit) |
| Suricata Capture | OK | 2026-03-04 | -- | Fixed: removed SURICATA_RUNMODE conflict, entrypoint wrapper for /var/log/suricata/live (PR #89 + develop commit) |
| Logstash Pipeline | OK | 2026-03-04 | -- | **VERIFIED:** opensearch-init bootstrap (Chain 15) + index naming fix (Chain 16). All 7 pipelines running. Events flowing to `arkime_sessions3-260304` (7,508+ docs, growing). Full pipeline: Zeek → Filebeat → Logstash → OpenSearch. |
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
| 2026-03-04 | Zeek | Zeek still Permission denied after `user: "root"` | Malcolm entrypoint drops to PUID via `su` BEFORE zeekctl creates dirs; fresh volumes are root-owned | Entrypoint wrapper: mkdir+chown as root before exec original chain | NET-93 | develop (f45a8e2) |
| 2026-03-04 | Suricata | Suricata fails: /var/log/suricata/live missing | Same root cause as Zeek — privilege drop before dir creation | Entrypoint wrapper: mkdir+chown /var/log/suricata as root | NET-93 | develop (f45a8e2) |
| 2026-03-04 | Logstash | Filebeat can't connect to logstash:5044 (224 retries) | After `down -v`, OpenSearch roles_mapping.yml resets → logstash 403 → stuck on malcolm_template | Re-run security bootstrap (Chain 11 in DEPLOYMENT-ISSUES.md) | -- | Manual bootstrap |
| 2026-03-04 | Logstash | Permanent fix for Chain 11: automated bootstrap | opensearch-init one-shot container runs securityadmin.sh + pushes malcolm_template | Added opensearch-init service to docker-compose.yml, logstash depends_on service_completed_successfully | NET-94 | PR #90 (`infra/opensearch-bootstrap`) |
| 2026-03-04 | Logstash | opensearch-init iteration 1: securityadmin.sh path not found | Relative path `${SECURITY_DIR}/../plugins/` resolved to wrong dir | Use absolute path `/usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh` | NET-94 | PR #90 (commit `60ea2d1`) |
| 2026-03-04 | Logstash | opensearch-init iteration 2: auth broke after `-cd` push | `-cd` pushed ALL security configs from init container — overwrote `internal_users.yml` with image default password hashes | Changed to `-f /tmp/roles_mapping.yml -t rolesmapping` — push ONLY the roles_mapping file | NET-94 | PR #90 (commit `219e1ac`) |
| 2026-03-04 | Logstash | All events go to literal `%{[@metadata][malcolm_opensearch_index]}` | `format_index_string.rb:52` crashes: `@prefix` nil because `MALCOLM_NETWORK_INDEX_PATTERN` env var not set in logstash service | Added 4 Malcolm index env vars to shared `opensearch-env` anchor | NET-94 | PR #90 (commit `eecbcc8`) |

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
16. **`user: "root"` alone is NOT enough for Malcolm capture images.** Malcolm's `docker-uid-gid-setup.sh` entrypoint drops to PUID:PGID via `su` BEFORE the service creates log directories. Fresh Docker volumes (after `down -v`) are root-owned → mkdir fails after privilege drop. Must use a custom `entrypoint:` wrapper in docker-compose that creates directories and chowns them as root, then `exec`s the original Malcolm entrypoint chain.
17. **After `docker compose down -v`, the ENTIRE pipeline must be re-bootstrapped.** Not just OpenSearch security (Chain 11) — capture volumes also reset to root ownership. The full recovery sequence is: (1) security bootstrap → (2) restart logstash/filebeat → (3) capture containers auto-create dirs via entrypoint wrappers. Without step 1, logstash never starts → filebeat has nowhere to send logs → no data in OpenSearch → empty dashboards.
18. **Inspect entrypoint chains with `docker inspect`.** When overriding `entrypoint:` in compose, the EXACT chain must match the image's original. Use `docker inspect <container> --format '{{json .Config.Entrypoint}}'` and `'{{json .Config.Cmd}}'` to get the correct order. Getting it wrong means the service never starts (wrong binary executed).
19. **Use init containers with `service_completed_successfully` for startup ordering.** One-shot init containers (`restart: "no"`) with `depends_on: condition: service_completed_successfully` guarantee bootstrap tasks complete before dependent services start. More reliable than healthcheck-based ordering — eliminates manual bootstrap steps after `docker compose down -v` + `up`.
20. **Share certs via Docker named volumes, not host bind mounts.** When an init container needs TLS certs generated by the main service, share them via a named volume. No host-path coupling, works across any host filesystem layout.
21. **Break startup deadlocks with minimal templates.** When Service A waits for a template that Service B pushes (but B starts after A), inject a minimal version of the template in an init container. The full template is overwritten later by the proper service.
22. **NEVER use `securityadmin.sh -cd` from an init container.** The `-cd` flag pushes ALL config files from the container's filesystem — including `internal_users.yml` with IMAGE DEFAULT password hashes. This overwrites the correct hashes generated by Malcolm's `setup-internal-users.sh` from curlrc credentials. Use `-f <file> -t <type>` to push only the specific config file needed.
23. **Init containers see the IMAGE filesystem, not the running container's state.** An init container using the same image as opensearch gets a FRESH filesystem copy from the image. Files modified by the opensearch container's entrypoint (like `internal_users.yml` with regenerated password hashes) are NOT visible in the init container.
24. **Malcolm's Ruby filter env var fallbacks have a nil gap.** `format_index_string.rb` falls back to `prefix_default` ONLY when the env var is empty string, NOT when it's unset (nil). Always set `MALCOLM_NETWORK_INDEX_PATTERN` and `MALCOLM_OTHER_INDEX_PATTERN` explicitly — don't rely on in-script defaults.
25. **Diff Malcolm's `.env.example` files when debugging missing env vars.** Malcolm distributes config across `opensearch.env`, `upload-common.env`, `auth-common.env`, etc. NetTap replaces these with inline YAML anchors. After any "undefined method for nil" crash in Malcolm Ruby filters, check upstream env files for required variables.

## Verification Checklist

After deploying reliability fixes to N100 hardware:

- [x] `curl -sk https://localhost/api/health | python3 -m json.tool | grep opensearch_reachable` → `true` (verified 2026-03-03)
- [ ] `curl -sk https://localhost/api/health | python3 -m json.tool | grep -A5 smart` → real temperature/power_on_hours values (NVMe returns null — may need SYS_RAWIO)
- [x] `curl -sk https://localhost/api/bridge/health | python3 -m json.tool` → `health_status: "not_configured"` (verified 2026-03-03)
- [x] Dashboard shows "Healthy" or informational states, no red badges for unconfigured services (verified 2026-03-03)
- [x] System page shows actionable messages for unreachable OpenSearch (verified 2026-03-03)
- [x] `curl -sk https://localhost/api/bridge/readiness | python3 -m json.tool` → returns readiness JSON with all 8 checks PASS (verified 2026-03-04, PR #88+#89)
- [ ] Go Live page (`/go-live`) loads and shows readiness phase
- [ ] Bridge creation via `/api/bridge/create` works end-to-end
- [ ] Bypass toggle enables/disables promisc via nsenter
- [x] Bridge health auto-discovers interface names from br0 brif sysfs (verified 2026-03-04, PR #88)
- [x] Zeek capture running — producing logs in /zeek/live/logs/ (verified 2026-03-04)
- [x] Suricata capture running — af-packet on br0 with 12 worker threads (verified 2026-03-04)
- [x] Logstash healthy and processing logs → `arkime_sessions3-260304` index in OpenSearch (verified 2026-03-04, PR #90: opensearch-init + index naming fix)
- [ ] Dashboard shows real packet data from capture pipeline

## Test Results

| Date | Test | Environment | Result | Notes |
|------|------|-------------|--------|-------|
| 2026-03-03 | Reliability overhaul deploy | N100 production | PASS | OpenSearch auth working, bridge not_configured state, dashboard UX states |
| 2026-03-03 | System page fixes deploy | N100 production | PASS | Storage NaN fixed, SMART null-safe, compliance loop fixed |
| 2026-03-04 | Bridge Go Live deploy | N100 production | **PARTIAL** | Daemon healthy, bridge_loop running. Hit 302→/login on bridge API — fixed in PR #85 (auth bypass). Pending redeploy. |
| 2026-03-04 | Dev tests (pytest) | Dev macOS | PASS | 1036/1036 passed (104 bridge-specific) |
| 2026-03-04 | Dev tests (vitest) | Dev macOS | PASS | 683/683 passed (22 GoLive + 25 bridge API) |
| 2026-03-04 | Dev svelte-check | Dev macOS | PASS | 620 files, 0 errors, 0 warnings |
| 2026-03-04 | Bridge interface discovery deploy | N100 production | PASS | PR #88: Auto-discovered enp2s0/enp3s0 from br0 brif. Carrier + packet data now visible in bridge health API. |
| 2026-03-04 | Capture pipeline deploy | N100 production | **PARTIAL** | PR #89 + develop: Zeek producing logs, Suricata capturing on br0. BUT logstash down (Chain 11 — needs security bootstrap after `down -v`). Filebeat can't connect to logstash:5044. No data in OpenSearch yet. |
| 2026-03-04 | Bridge readiness all-pass | N100 production | PASS | All 8 readiness checks PASS: bridge exists, UP, WAN carrier, LAN carrier, promisc on both, STP off, forward_delay 0, netfilter disabled (br_netfilter not loaded). |
| 2026-03-04 | opensearch-init bootstrap deploy | N100 production | PASS (3 iterations) | **Iteration 1:** securityadmin.sh path not found (relative path bug). **Iteration 2:** `-cd` flag overwrote internal_users.yml → broke ALL auth → required manual recovery. **Iteration 3:** `-f`/`-t` flags → security pushed successfully, auth verified, malcolm_template created. |
| 2026-03-04 | Logstash pipeline startup | N100 production | **PARTIAL** | All 7 pipelines started: malcolm-input, malcolm-output, malcolm-zeek, malcolm-suricata, malcolm-enrichment, malcolm-beats, malcolm-filescan. 60,696+ events processed. BUT: format_index_string.rb crashes — @prefix nil, all events to literal `%{[@metadata][malcolm_opensearch_index]}`. Root cause: missing MALCOLM_NETWORK_INDEX_PATTERN env var. Fix committed (`eecbcc8`). |
| 2026-03-04 | Logstash index naming fix | N100 production | **PASS** | After adding 4 Malcolm index env vars to opensearch-env anchor and recreating logstash: `arkime_sessions3-260304` index appeared with 7,508+ docs, growing steadily. Full pipeline verified end-to-end. |
