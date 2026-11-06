# Security Review

## Review Metadata

* Review Folder: `fix-capture-loss-window`
* Report Path: `security-reviews/fix-capture-loss-window/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-06T10:17:40-08:00`
* Inspected Branch or PR: `fix/capture-loss-window`
* Current Commit: `91aa5b1` (the review fixes that follow it add a 5 s minimum gap between kept readings, a stricter web validator and tests; no new input, sink or route)
* Review Scope: `committed-only`
* Diff Sources: `origin/main...HEAD`
* Dirty Working Tree Included: `no`

## Files Reviewed

Security-relevant source (17 changed files in all; tests, the plan, the tracking note and visual fixtures fall under the doc/test exclusion):

* daemon/services/loss_window.py (new: sysfs counter reader and in-memory window)
* daemon/api/capture.py (background sampler from `cleanup_ctx`, `loss_window` on `GET /api/capture/stats`)
* daemon/services/capture_manager.py (`packet_loss_pct` formula)
* scripts/remote/deploy-capture-loss-window.sh (owner-run device check)
* web/src/lib/api/capture.ts (client-side validation of the new block)

## Coverage Summary

* Changed symbols analyzed: 6
* Inbound callers inspected: 7 (`register_capture_routes` from `api/server.py:1186`; the capture manager swap in `main.py:737`; the three `packet_loss_pct` callers; the two web callers of `getCaptureStats`)
* Outbound callees inspected: 5 (`get_capture_interface` in the bridge, mirror, DHCP-gateway and stub managers; `daemon_auth.py` middleware)
* Sinks considered: path traversal into sysfs, auth on the changed route, secret exposure (logs, error JSON, the deploy script's output), `eval` in the deploy script, background-task lifecycle, client-side parsing of daemon JSON
* Regression patterns checked: auth exemptions (still only `GET /api/health`), removed validation, new response fields
* Trusted rule memory: none
* Limitations / unresolved edges: the interface name comes from root-owned config or the environment (trusted per precedent) and reaches only fixed file names read as non-negative integers, the same paths the managers already read; Stage 2 ran the data-flow and controls/secrets angles, auth was verified directly in `daemon_auth.py`, and the cross-file reachability agent was skipped for a small impact map
* Not covered (by design): DoS / memory growth (a per-request reading kept for an hour was raised by the two-angle review as LOW and fixed with a 5 s minimum gap), rate limiting, dependency CVEs, generic hardening
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
