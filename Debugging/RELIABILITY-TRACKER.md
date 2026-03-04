# NetTap Reliability Tracker — Source of Truth

> Last updated: 2026-03-04
> Status: 5/7 subsystems production-ready

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
