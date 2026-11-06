# Security Review

## Review Metadata

* Review Folder: `fix-data-accuracy-audit-2026-11-06`
* Report Path: `security-reviews/fix-data-accuracy-audit-2026-11-06/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-05T19:08:18-08:00`
* Inspected Branch or PR: `fix/data-accuracy-audit-2026-11-06`
* Current Commit: `85b43a9`
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

* daemon/api: alerts.py, devices.py, live.py, logs.py, risk.py, server.py, threats.py, tools.py
* daemon/services: ssl_cert_service.py, network_diag_service.py, live_connections.py, iot_monitor.py, iot_trust_scorer.py, threat_intel.py, bridge_health.py, bandwidth_tracker.py, changelog.py, excluded_ips.py, capture_manager.py, mirror_manager.py, dhcp_gateway_host.py, bridge_capture_adapter.py, device_registry.py, risk_scoring.py
* web/src/routes/api/devices/[ip]/connections/+server.ts
* The web pages and API clients the branch touches (they render only through Svelte interpolation).
* Tests, fixtures and docs were excluded by design.

## Coverage Summary

* Changed symbols analyzed: 22 (route handlers with new parameters `proto` and `active_since`, the SSL tool's s_client argv and verify parsing, ping parsing, risk and LAN filters, the changelog event time, the devices proxy)
* Inbound callers inspected: 9 (daemon auth middleware, web session hook and PUBLIC_PATHS, the /api/tools proxies, the devices connections proxy, route registration, the registry refresh that logs device joins)
* Outbound callees inspected: 8 (OpenSearch DSL builders, build_excluded_ips_filter, build_lan_filter, validate_host, create_subprocess_exec, changelog index naming, Svelte rendering, URLSearchParams)
* Sinks considered: injection (OpenSearch DSL, painless params, subprocess argv), auth, SSRF, secret exposure, error disclosure
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: large diff reviewed per cluster; the SSL tool sits on the public /api/tools path, and its new `-verify_hostname` / `-verify_ip` value is the already-validated host in an argv list
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
