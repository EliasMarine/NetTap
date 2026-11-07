# Security Review

## Review Metadata

* Review Folder: `feature-drill-down-slice2b3`
* Report Path: `security-reviews/feature-drill-down-slice2b3/security-review.md`
* Base Ref: `origin/main` (`e62e368`)
* Base Ref Commit Date: `2026-11-06T16:39:42-08:00`
* Inspected Branch or PR: `feature/drill-down-slice2b3`
* Current Commit: `c413b21` (staged changes on top)
* Review Scope: `committed + staged`
* Diff Sources: `git diff origin/main...HEAD`, `git diff --cached`
* Dirty Working Tree Included: `yes` (staged; no unstaged changes)

## Files Reviewed

**Security-relevant source:**
- `daemon/api/devices.py`: `handle_device_list`, `handle_device_count`, `_lan_device_buckets`, and the new helpers `_now_ms`, `_iso_ms`, `_ranked`, `_ip_order`, `_alert_sides` and `_incomplete`
- `scripts/remote/deploy-drill-down.sh`: Step 7d and the `DEVICE_LIST_TIMEOUT_MS` constant
- `web/src/routes/api/devices/+server.ts`
- `web/src/routes/devices/+page.svelte`
- `web/src/routes/+page.svelte`
- `web/src/lib/api/devices.ts`

**Out of scope:** test, fixture, plan and documentation files (hard exclusion 7).

**Unchanged files read for context:**
- `web/src/hooks.server.ts`
- `web/src/lib/server/daemon.ts`
- `daemon/api/daemon_auth.py`
- `daemon/api/server.py`
- `daemon/api/time_range.py`
- `daemon/storage/all_buckets.py`
- `daemon/storage/snapshot_search.py`
- `daemon/api/devices_v2.py`
- `daemon/api/risk.py`
- `web/src/lib/utils/drilldown.ts`

## Coverage Summary

* **Changed symbols analysed:** 7.
  - **Daemon routes:** `handle_device_list` and `handle_device_count`.
  - **Daemon helpers:** `_lan_device_buckets` (`what=`) and the alert-count check `_alert_sides`.
  - **Web:** the `/api/devices` proxy, the Devices page's URL window, and Home's Devices card link.
  - **Script:** Step 7d.
* **Inbound callers inspected:** 6.
  - The route table, the daemon token middleware and the web session gate.
  - The `/api/devices` proxy.
  - `devices_v2.py` and `risk.py`, which are unchanged and pass no `what`.
  - Home's top-devices call.
* **Outbound callees inspected:** 3:
  - `all_buckets` composite paging;
  - `checked()`, where `TooSlow` is a subclass of `QueryFailed`, so both return the fixed 502;
  - the opensearch-py `search` bodies.
* **Sinks considered:**
  - OpenSearch DSL injection: `sort` and `order` are allow-listed, `limit` is an int capped at 500, and the window goes through `parse_time_range`;
  - error-text leaks: the new 502 carries a fixed message;
  - open redirects and link building on the web: `goto` stays on the page's own pathname, and hrefs are built with `URLSearchParams`;
  - secret exposure in the device script: the token is read inside the containers and never printed, and arguments are passed as argv, not through the shell.
* **Regression patterns checked:** removed filters, auth-default flips, and visibility changes.
  - The list keeps the count's exact bool query (time range, Zeek conn, the LAN filter, excluded IPs) through the shared helper.
  - The new checks only make replies stricter.
* **Trusted rule memory:** none.
* **Limitations / unresolved edges:** none.
* **Not covered (by design):** DoS, rate limiting, dependency CVEs and generic hardening.
  - The every-device composite is capped at 50,000 buckets, on a one-household appliance.
  - Run the two-angle review for those.
* **External analysis consumed:** none.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
