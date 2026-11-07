# Security Review

## Review Metadata

* Review Folder: `feature-packet-analysis-redesign`
* Report Path: `security-reviews/feature-packet-analysis-redesign/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-06T19:15:08-08:00`
* Inspected Branch or PR: `feature/packet-analysis-redesign`
* Current Commit: `483c089`
* Review Scope: `uncommitted-only` (staged)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes` (the staged changes are the whole change)

## Files Reviewed

- `daemon/api/packets.py` (new)
- `daemon/services/container_exec.py` (new)
- `daemon/services/packet_search.py` (new)
- `daemon/services/packet_manifest.py` (new)
- `daemon/services/capture_index.py` (new)
- `daemon/services/packet_parse.py` (new)
- `daemon/api/server.py`, `daemon/services/pcap_search.py`, `daemon/services/tshark_service.py` (modified)
- `web/src/routes/api/packets/download/+server.ts` (new)
- `web/src/lib/api/packets.ts` (new)
- `web/src/routes/api/[...path]/+server.ts` (modified)
- `scripts/remote/deploy-packet-analysis.sh`, `scripts/remote/verify-packet-analysis.py` (new, operator-run)
- Tests and fixtures under `daemon/tests/` and `*.test.ts` (out of scope under hard exclusion 7)

## Coverage Summary

* Changed symbols analyzed: 12
* Inbound callers inspected: 9
* Outbound callees inspected: 21
* Sinks considered:
  - command injection (the container shell scripts via `docker exec`, and awk `-v`);
  - path traversal (manifest file ids, capture-file id, the daemon realpath vs the container path);
  - XXE / unsafe parsing (PDML iterparse);
  - control-channel forgery (stderr markers deciding which process group is killed);
  - auth (daemon token middleware, the web session guard and its public prefixes);
  - CSRF (the form-post download route);
  - secret exposure (the daemon token in the scripts and proxies);
  - error detail leakage.
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges:
  - Large diff, reviewed per cluster (daemon API and jobs, web proxies, operator scripts).
  - The supervisor's process-group behaviour was checked on the device, not statically.
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
