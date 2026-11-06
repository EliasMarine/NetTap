# Security Review

## Review Metadata

* Review Folder: `feature-network-flow-redesign`
* Report Path: `security-reviews/feature-network-flow-redesign/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-05T15:59:41-08:00`
* Inspected Branch or PR: `feature/network-flow-redesign`
* Current Commit: `f1b7457`
* Review Scope: `uncommitted-only` (staged; the branch has no commits ahead of `origin/main`)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes` (staged changes; unrelated untracked files under `scripts/remote/` and a PNG were out of scope)

## Files Reviewed

* `web/src/lib/components/ui/charts/flow.ts` (new)
* `web/src/lib/components/NetworkFlow.svelte` (new)
* `web/src/lib/components/NetworkFlowTable.svelte` (new)
* `web/src/lib/utils/device-names.ts` (new)
* `web/src/routes/connections/+page.svelte` (modified)
* `web/src/lib/components/SankeyDiagram.svelte` (header comment only)
* `web/DESIGN-SYSTEM.md` (doc)
* Tests and fixtures (excluded): `flow.test.ts`, `NetworkFlow.test.ts`, `device-names.test.ts`, `connections.test.ts`, `connections.refresh.test.ts`, `e2e/visual/fixtures/traffic.ts`, `e2e/visual/fixtures/traffic.test.ts`, `e2e/visual/network-flow.visual.ts`
* Context read (unchanged): `web/src/hooks.server.ts`, `web/src/routes/api/devices/[ip]/+server.ts`, `web/src/lib/api/devices-registry.ts`, `web/src/lib/components/ui/DataTable.svelte`, `web/src/lib/components/ui/Pills.svelte`

## Coverage Summary

* Changed symbols analyzed: 9 (`flowData`, `flowLayout`, `dodgeLabels`, `share`, `splitText`, `namesByIp`, `NetworkFlow`, `NetworkFlowTable`, Connections `loadAll`)
* Inbound callers inspected: 3 (Connections page → NetworkFlow → NetworkFlowTable)
* Outbound callees inspected: 4 (`getRegistryDevices`, `/api/devices/[ip]` proxy, `daemonFetch`, DataTable cell rendering)
* Sinks considered: xss (raw-HTML APIs, attribute and style bindings), ssrf, auth, secret/PII exposure
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, tenant-filter removal, visibility changes
* Trusted rule memory: none
* Limitations / unresolved edges: none. The change is browser-only. Attacker-influenced strings (LAN device hostnames, AS names, IPs) reach the page only through Svelte's escaped text and attribute bindings. The one new request (`GET /api/devices/registry?limit=200`) goes to an existing endpoint that still requires a session (not in `PUBLIC_PATHS`).
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening — run the two-angle review for those
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
