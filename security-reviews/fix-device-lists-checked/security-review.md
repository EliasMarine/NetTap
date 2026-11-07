# Security Review

## Review Metadata

* Review Folder: `fix-device-lists-checked`
* Report Path: `security-reviews/fix-device-lists-checked/security-review.md`
* Base Ref: `origin/main` (`005d941`)
* Base Ref Commit Date: `2026-11-06T17:34:49-08:00`
* Inspected Branch or PR: `fix/device-lists-checked`
* Current Commit: `005d941` (staged changes on top)
* Review Scope: `staged`
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes` (staged; no unstaged changes)

## Files Reviewed

**Security-relevant source:**
- `daemon/api/risk.py`: `handle_risk_scores` (`_risk_scores`), `handle_risk_score_single` and `_all_unsafe_ports`
- `daemon/storage/all_buckets.py`: `all_buckets` in checked mode
- `daemon/api/devices_v2.py`: `refresh_device_registry`
- `daemon/services/device_registry.py`: `enrich_from_dhcp`, `enrich_from_mdns` and `enrich_from_ssdp`
- `scripts/remote/deploy-drill-down.sh`: Step 7e

**Out of scope:** test, plan, tracking and documentation files (hard exclusion 7).

**Unchanged files read for context:**
- `daemon/api/devices.py`
- `daemon/storage/snapshot_search.py`
- `daemon/api/daemon_auth.py`
- `daemon/api/server.py`
- `daemon/api/time_range.py`
- `daemon/api/alerts.py`
- `daemon/main.py`
- `web/src/hooks.server.ts`
- `web/src/routes/api/risk/scores/+server.ts`
- `web/src/routes/api/risk/scores/[ip]/+server.ts`

## Coverage Summary

* **Changed symbols analysed:** 8.
  - **Daemon routes:** the two risk routes.
  - **Daemon helpers:** `_all_unsafe_ports` and `all_buckets` (checked mode).
  - **Background job:** the registry refresh.
  - **Registry lookups:** the three enrichment methods.
  - **Script:** Step 7e.
* **Inbound callers inspected:**
  - every `all_buckets(..., what=...)` caller: `alerts.py` via `_every_key`, `devices.py` via `_lan_device_buckets`, `devices_v2.py` and `risk.py`;
  - every `_lan_device_buckets` call site;
  - the refresh loop in `main.py`;
  - the risk route registration and the token middleware;
  - the two SvelteKit risk proxies behind the session gate.
* **Outbound callees inspected:**
  - `checked()` and `total_hits()`, which raise only `QueryFailed` or its subclass `TooSlow`;
  - `_incomplete`, a fixed 502 body with the reason logged on the server only;
  - the opensearch-py `search` bodies.
* **Sinks considered:**
  - OpenSearch DSL injection: `ip`, `from`, `to` and `limit` are unchanged, and they go in as dict values;
  - error-text leaks: the new 502 carries a fixed message, so this exposes less than the old `OpenSearch query failed: {exc}` replies, which are untouched;
  - uncaught exceptions reaching a route or killing the background loop: every caller catches;
  - the script's handling of the token and IPs: the IP is validated by a regex before use, and the token is read inside the container.
* **Regression patterns checked:** removed filters, auth-default flips and visibility changes.
  - No query filter changed.
  - The new checks only make replies stricter.
  - Unchecked `all_buckets` callers keep their behaviour.
* **Trusted rule memory:** none.
* **Limitations / unresolved edges:** none.
* **Not covered (by design):** DoS, rate limiting, dependency CVEs and generic hardening. A partial read now gives a 502 or a skipped registry cycle. That is availability only (hard exclusion 1), and it is the intended behaviour.
* **External analysis consumed:** none.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
