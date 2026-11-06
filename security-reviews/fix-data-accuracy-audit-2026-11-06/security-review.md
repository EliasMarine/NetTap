# Security Review

## Review Metadata

* Review Folder: `fix-data-accuracy-audit-2026-11-06`
* Report Path: `security-reviews/fix-data-accuracy-audit-2026-11-06/security-review.md`
* Base Ref: `origin/fix/data-accuracy-audit-2026-11-06` (upstream, equal to HEAD); the first run used `origin/main`
* Base Ref Commit Date: `2026-11-06T00:06:03-08:00` (origin/main at 7bb2cfd)
* Inspected Branch or PR: `fix/data-accuracy-audit-2026-11-06` (PR #174)
* Current Commit: `daf9d9a` plus staged changes
* Review Scope: `staged-only` (delta re-run over 85b43a9..staged; the first run over `origin/main...85b43a9` found nothing)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `staged only`

## Files Reviewed

* First run: the daemon API, services and web clients the branch touches (see git history of this file at 4727d17).
* Delta run (the fixes from the PR #174 reviews):
  * daemon/services/ssl_cert_service.py: line-bounded verify regex, first verify result, subprocess kill on timeout
  * daemon/api/tools.py: `trusted` requires code 0 and no verify-callback errors
  * daemon/api/devices.py: device-list alert count over source or destination
  * web: NewDeviceBanner (localStorage dismissal), healthStage, wording on Home, System, IoT, Connections and the SSL tool
* Tests were excluded by design.

## Coverage Summary

* Changed symbols analyzed (delta): 5 (SslCertService verify parsing and inspect, the handle_ssl_cert verdict, the device-list alert-count query, NewDeviceBanner, healthStage)
* Inbound callers inspected: handle_ssl_cert → SslCertService.inspect; handle_device_list → the chunked alert query; the Devices page → NewDeviceBanner
* Outbound callees inspected: create_subprocess_exec (argv unchanged), the opensearch-py search body (structured DSL, values only), localStorage
* Sinks considered:
  * a TLS verdict spoofed by text the server sends after the handshake;
  * injection into the OpenSearch DSL from IPs learned from traffic;
  * a raw-HTML sink in the banner.
* Regression patterns checked: removed validators, loosened regex, verdict defaults (the change can only turn "trusted" into "not trusted", never the reverse)
* Trusted rule memory: none
* Limitations / unresolved edges: openssl's output order (its own result before application data) and its escaping of certificate names were not run live
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
