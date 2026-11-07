# Security Review

## Review Metadata

* Review Folder: `fix-daemon-event-loop`
* Report Path: `security-reviews/fix-daemon-event-loop/security-review.md`
* Base Ref: `origin/main` (`fdafbba`)
* Base Ref Commit Date: `2026-11-07T00:10:16-08:00`
* Inspected Branch or PR: `fix/daemon-event-loop` (NET-192 PR 2, draft PR #200)
* Current Commit: `22cd2ba`
* Review Scope: `committed` (12 commits, clean working tree)
* Diff Sources: `git diff --find-renames origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

Source files (57 changed in total; the test, doc and script files are out of scope under hard exclusions 7 and 16):

* daemon/api/offload.py (new: `in_thread`, `run_blocking`, `lookup_slot`, `run_lookup`)
* daemon/api/{addresses,alerts,bandwidth,changelog,devices,devices_v2,dns,geoip,lan_security,live,logs,lookup,mac_correlation,opensearch_cluster,packets,pcap,risk,search,server,threats,tools,traffic,tshark}.py
* daemon/services/{alert_intelligence,geoip_service,investigation,live_connections,notification_hub,pcap_search,threat_intel,traffic_classifier,update_executor}.py
* daemon/storage/manager.py, daemon/main.py
* web/src/routes/api/[...path]/+server.ts, api/devices/+server.ts, api/risk/scores/+server.ts, api/lookup/whois/[ip]/+server.ts

## Coverage Summary

* Changed symbols analyzed: ~30, grouped in four clusters:
  * public lookups: `lookup_slot`, `run_lookup`, the WHOIS, DNS and MAC lookup handlers;
  * the route execution model: `in_thread`, `run_blocking`, 67 decorated handlers and 34 offloaded calls;
  * shared files: `write_file_atomic` call sites, `scan_suricata`, `merge_seen`, `_swap_in`;
  * outbound controls: `_smtp_send`, the OpenSearch client options, the web proxy timeouts.
* Inbound callers inspected: callers of the functions changed from `async def` to `def` (`get_category_*`, `get_smart_alerts`, `get_smart_alert_summary`), of `populate_from_suricata` and its replacements, and the route registration that the auth middleware relies on (`daemon/api/daemon_auth.py`, `daemon/api/server.py`).
* Outbound callees inspected: `socket.gethostbyaddr` and `socket.getaddrinfo`, the WHOIS subprocess, `MacLookupService.lookup`, `smtplib.SMTP` with STARTTLS, the OpenSearch client constructor options, `tempfile.mkstemp`, `shutil.copy2` and `os.replace`.
* Sinks considered: subprocess and tshark calls, PCAP file paths, OpenSearch queries, SMTP transport security, file writes and their permissions, and proxy timeouts and auth.
* Regression patterns checked: removed validation or path checks in rewritten handlers, auth middleware bypass through the handler wrapping, loss of request-scoped state in threads (no contextvars in the daemon), weaker TLS for SMTP and OpenSearch, and file mode changes on the atomic writes (acks, suppress list, baseline and threat-intel cache stay 0644; none holds secrets).
* Trusted rule memory: none (`security-reviews/_rules/` does not exist).
* Limitations / unresolved edges:
  * Large-diff mode (57 files). The reviewers read each cluster's diff with read-only `git diff origin/main...HEAD -- <path>` and the inline `OLD CODE` blocks; no global diff was used.
  * The public reach of `/api/lookup/*` and `/api/tools/*` without a login comes before this PR. It is tracked as NET-193 and was not assessed as a finding here.
* Not covered (by design): DoS and resource exhaustion (the pool sizes and the lookup cap), rate limiting, dependency CVEs and general hardening. The two-angle pre-merge review covers those.
* External analysis consumed: none.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
