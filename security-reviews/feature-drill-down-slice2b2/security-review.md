# Security Review

## Review Metadata

* Review Folder: `feature-drill-down-slice2b2`
* Report Path: `security-reviews/feature-drill-down-slice2b2/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-06T15:23:52-08:00`
* Inspected Branch or PR: `feature/drill-down-slice2b2`
* Current Commit: `865c597` (staged changes on top)
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes` (staged; no unstaged changes)

## Files Reviewed

**Security-relevant source:**
- `daemon/api/suricata_categories.py` (new)
- `daemon/api/alerts.py`
- `daemon/api/server.py`
- `daemon/services/live_connections.py`
- `daemon/storage/all_buckets.py`
- `scripts/remote/deploy-drill-down.sh`
- `web/src/routes/api/[...path]/+server.ts`
- `web/src/routes/api/alerts/+server.ts`
- `web/src/routes/alerts/suricata/[name]/+page.svelte` and `suricata-view.ts` (new)
- `web/src/routes/alerts/+page.svelte`
- `web/src/routes/alerts/alert-view.ts`
- `web/src/routes/alerts/AlertDetail.svelte`
- `web/src/lib/api/alerts.ts`, `drilldown.ts` and `live.ts`
- `web/src/lib/utils/drilldown.ts`
- `web/src/lib/components/ui/AlertGroup.svelte` and `DataTable.svelte`
- `web/src/lib/components/drawer/content/LiveConnectionDrawerContent.svelte`

**Out of scope:** test, fixture and documentation files (hard exclusion 7).

**Unchanged files read for context:**
- `web/src/hooks.server.ts`
- `daemon/api/daemon_auth.py`
- `daemon/api/drilldown_runner.py`
- `daemon/storage/snapshot_search.py`
- the other callers of `all_buckets` in `daemon/api` and `daemon/services`

## Coverage Summary

* **Changed symbols analysed:** 11.
  - **Daemon routes:** `handle_suricata_category`/`suricata_category_figures`, `handle_alerts_list`, `handle_alerts_top_signatures` and `handle_alerts_top_ips`.
  - **Daemon helpers:** `alert_query`, `severity_clauses`, `valid_suricata_category`, `all_buckets`, and the normalizer's `rule_category`.
  - **Web:** the catch-all proxy and the list proxy, the link helpers and the new page, and `DataTable` `rowActivatable`.
  - **Script:** `deploy-drill-down.sh` Step 7c.
* **Inbound callers inspected:** about 30.
  - The route table, auth middleware and session gate.
  - Two web proxies.
  - About 25 unchanged `all_buckets` callers.
* **Outbound callees inspected:** 4: the opensearch-py `search` and `count` bodies, PIT through `SnapshotSearch`, and `checked()`.
* **Sinks considered:**
  - OpenSearch query DSL injection;
  - route shadowing and auth bypass through the greedy `{name:.+}` route;
  - proxy path forwarding;
  - XSS and link building in the new links;
  - secret exposure in the device script.
* **Regression patterns checked:** removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes.
  - The list query refactor keeps every existing filter and must-not.
  - The new checks only make replies stricter: an incomplete search returns a 502 instead of a smaller total.
* **Trusted rule memory:** none.
* **Limitations / unresolved edges:** none.
* **Not covered (by design):** DoS and ReDoS, rate limiting, dependency CVEs, generic hardening. Run the two-angle review for those.
* **External analysis consumed:** none.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
