# NetTap Reliability Tracker — Source of Truth

> Last updated: 2026-03-03
> Status: 2/7 subsystems production-ready

## Purpose

This document tracks production reliability of each NetTap subsystem. Read this before starting any reliability or health-check work. Update after every fix.

## Subsystem Reliability Status

| Subsystem | Status | Verified On | Issues | Notes |
|-----------|--------|-------------|--------|-------|
| OpenSearch | Fixing | -- | Auth missing in daemon | `StorageManager._create_client()` has no `http_auth` |
| SMART Monitoring | Fixing | -- | All metrics null | NVMe admin cmds may need /dev write access |
| Bridge Health | Fixing | -- | Shows "down" when not configured | Missing `not_configured` state |
| Internet Health | Fixing | -- | Shows "down" when not configured | Missing `not_configured` state |
| Web UI (Dashboard) | Fixing | -- | Scary error states | No distinction between "unreachable" vs "not configured" |
| Web UI (System) | Fixing | -- | No actionable messages | Needs contextual error/info messages |
| Storage Daemon | OK | 2026-03-03 | -- | Disk monitoring and retention working |

### Status Legend
- **OK**: Verified working in production
- **Fixing**: Known issue, fix in progress
- **Broken**: Non-functional, blocking
- **Untested**: Not yet verified on production hardware

## Issues Found & Fixed

| Date | Subsystem | Issue | Root Cause | Fix | Linear | Branch |
|------|-----------|-------|------------|-----|--------|--------|
| 2026-03-03 | OpenSearch | Daemon gets 403 from OpenSearch | `_create_client()` has no http_auth | Add curlrc mount + credential parsing | -- | infra/reliability-overhaul |
| 2026-03-03 | SMART | All SMART metrics null | /dev mounted :ro, NVMe needs write for admin cmds | Remove :ro from /dev mount | -- | infra/reliability-overhaul |
| 2026-03-03 | Bridge | Bridge shows "Down" when br0 doesn't exist | No `not_configured` state | Add not_configured status to bridge_health.py | -- | infra/reliability-overhaul |
| 2026-03-03 | Web UI | Dashboard shows generic error for all failure modes | Single error banner for all states | Distinguish daemon unreachable vs OS connecting vs no data | -- | infra/reliability-overhaul |

## Reliability Lessons Learned

1. **Always mount curlrc in every container that talks to OpenSearch.** The security bootstrap requires Basic Auth — containers without credentials get silent 403 errors.
2. **NVMe SMART queries require write access to /dev.** The smartctl tool sends NVMe admin commands that need write access to the controller device. `:ro` mounts block this silently.
3. **"Not configured" is not the same as "down".** Services that haven't been set up (bridge, internet) should show an informational state, not an error state. Users who haven't configured the bridge yet shouldn't see red badges.
4. **Log stderr from subprocess calls.** When smartctl fails, the exception message alone doesn't show why — the stderr output contains the actual error (e.g., "Permission denied", "No such device").
5. **Parse curlrc files for credentials.** Malcolm stores OpenSearch credentials in curlrc format (`user = "username:password"`). The daemon needs a parser for this format.

## Verification Checklist

After deploying reliability fixes to N100 hardware:

- [ ] `curl -sk https://localhost/api/health | python3 -m json.tool | grep opensearch_reachable` → `true`
- [ ] `curl -sk https://localhost/api/health | python3 -m json.tool | grep -A5 smart` → real temperature/power_on_hours values
- [ ] `curl -sk https://localhost/api/bridge/health | python3 -m json.tool` → `health_status: "not_configured"` (not "down")
- [ ] Dashboard shows "Healthy" or informational states, no red badges for unconfigured services
- [ ] System page shows actionable messages for unreachable OpenSearch

## Test Results

| Date | Test | Environment | Result | Notes |
|------|------|-------------|--------|-------|
| -- | Pending deployment | N100 production | -- | -- |
