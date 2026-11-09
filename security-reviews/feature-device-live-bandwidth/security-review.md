# Security Review

## Review Metadata

* Review Folder: `feature-device-live-bandwidth`
* Report Path: `security-reviews/feature-device-live-bandwidth/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-07T17:38:30-08:00`
* Inspected Branch or PR: `feature/device-live-bandwidth`
* Current Commit: `ae66847b`
* Review Scope: `uncommitted-only`
* Diff Sources: `git diff --cached` (no commits ahead of `origin/main`)
* Dirty Working Tree Included: `yes`

## Files Reviewed

* `daemon/api/live_bandwidth.py` (new route `GET /api/live-bandwidth`)
* `daemon/services/live_bandwidth.py` (new meter: tc filters on the capture interface)
* `daemon/services/live_bandwidth_tc.py` (new: tc batch lines, dump parser, subprocess runner)
* `daemon/api/server.py`, `daemon/main.py` (wiring)
* `web/src/lib/api/live-bandwidth.ts`, `web/src/lib/components/LiveBandwidthCard.svelte` (client)
* `scripts/remote/verify_live_bandwidth.py`, `scripts/remote/live_bandwidth_reference.py`, `scripts/remote/deploy-device-live-bandwidth.sh` (operator tooling)
* Unchanged files read for context: `daemon/api/daemon_auth.py`, `daemon/services/device_custom.py`, `daemon/services/device_registry.py`, `daemon/services/excluded_ips.py`, `daemon/services/dhcp_gateway_net.py`, `daemon/services/capture_manager.py`, `web/src/hooks.server.ts`, `web/src/routes/api/[...path]/+server.ts`, `web/src/lib/server/auth.ts`, `scripts/bridge/bypass-mode.sh`
* Tests, docs, the visual fixture and the AreaChart `gaps` prop were excluded (test/doc-only or no sink)

## Coverage Summary

* Changed symbols analyzed: 12
* Inbound callers inspected: 5 (aiohttp router, web catch-all proxy, `main.py` startup, `on_cleanup`, the web client)
* Outbound callees inspected: 9 (`normalize_mac`, `_normalize_mac`, `parse_single_ip`, `lan_subnets_of`, `validate_interface_name`, `build_filter_lines`, `delete_args`, `run_tool`, `asyncio.create_subprocess_exec`)
* Sinks considered: command_injection (tc argv and `tc -batch` stdin as root), path_traversal (sysfs operstate path), auth (daemon token middleware, web session), secret_exposure (daemon token in operator scripts, tc stderr in responses), xss (client rendering)
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: tc's batch and flower-without-action behaviour was taken from known iproute2/kernel semantics, not run against a kernel here; the G11 veth gate covers the filter lines
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
