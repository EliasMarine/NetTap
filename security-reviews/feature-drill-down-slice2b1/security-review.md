# Security Review

## Review Metadata

* Review Folder: `feature-drill-down-slice2b1`
* Report Path: `security-reviews/feature-drill-down-slice2b1/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-06T14:49:56-08:00`
* Inspected Branch or PR: `feature/drill-down-slice2b1` (PR #189)
* Current Commit: `3dbc005`
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

**Source files (security-relevant):**
- `daemon/api/alerts.py`
- `daemon/api/logs.py`
- `daemon/api/traffic.py`
- `daemon/services/alert_intelligence.py`
- `daemon/services/excluded_ips.py`
- `scripts/remote/deploy-drill-down.sh`
- `web/src/routes/api/alerts/+server.ts`
- `web/src/lib/api/alerts.ts`
- `web/src/lib/api/traffic.ts`
- `web/src/lib/utils/drilldown.ts`
- `web/src/lib/components/ui/KpiCard.svelte`
- `web/src/routes/+page.svelte`
- `web/src/routes/alerts/+page.svelte`
- `web/src/routes/alerts/AlertDetail.svelte`
- `web/src/routes/devices/[ip]/+page.svelte`
- `web/src/routes/logs/+page.svelte`
- `web/src/lib/styles/a11y.css`

**Outside the security scope:** 15 test, fixture and documentation files (hard exclusion 7):
- daemon tests;
- web tests;
- `web/e2e/visual/fixtures/traffic.ts`;
- `web/DESIGN-SYSTEM.md`;
- the plan;
- the review log;
- the tracking doc.

**Unchanged files read for context:**
- `web/src/hooks.server.ts`
- `web/src/lib/server/auth.ts`
- `web/src/routes/api/logs/search/+server.ts`
- `web/src/routes/api/settings/excluded-ips/+server.ts`
- `daemon/api/daemon_auth.py`
- `daemon/api/server.py`
- `daemon/api/settings.py`
- `daemon/api/drilldown_runner.py`
- the callers of `build_excluded_ips_filter` in `daemon/services/*`

## Coverage Summary

* **Changed symbols analysed:** 9.
  - The daemon handlers: `handle_alerts_list`, `handle_log_search` and `handle_traffic_summary`.
  - The helpers: `parse_single_ip`, `valid_excluded_ips`, `build_excluded_ips_filter` and `get_smart_alerts`.
  - The web code: the alerts proxy and the drill-down link builders.
  - The script: `deploy-drill-down.sh` Steps 7b and 8.
* **Inbound callers inspected:** 32.
  - 2 web proxies.
  - `settings.py:237`.
  - `drilldown_runner.py:59`.
  - 28 callers of `build_excluded_ips_filter`.
* **Outbound callees inspected:** 4: the opensearch-py `search` request bodies and the `ipaddress` parser.
* **Sinks considered:** OpenSearch query DSL injection, auth and session boundaries, information exposure in responses, XSS and open redirect in the rendered links, and secret exposure in the device script.
* **Regression patterns checked:** removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes. The only validation change makes it stricter: `parse_single_ip` now also rejects scoped IPv6.
* **Trusted rule memory:** none.
* **Limitations / unresolved edges:** none.
* **Not covered (by design):** DoS/ReDoS, rate limiting, dependency CVEs and generic hardening. The two-angle review covers those.
* **External analysis consumed:** none.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
