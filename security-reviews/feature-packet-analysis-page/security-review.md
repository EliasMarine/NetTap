# Security Review

## Review Metadata

* Review Folder: `feature-packet-analysis-page`
* Report Path: `security-reviews/feature-packet-analysis-page/security-review.md`
* Base Ref: `origin/main` (`19a479e`); merge-base `34a86c4`
* Base Ref Commit Date: `2026-11-06T22:33:13-08:00`
* Inspected Branch or PR: `feature/packet-analysis-page` (NET-188 PR 2), no commits yet
* Current Commit: `34a86c4` (HEAD) plus the staged changes
* Review Scope: the staged diff. It covers 53 files, +6,256/−50 lines; about 3,700 lines are source, the rest tests and fixtures.
* Diff Sources: `git diff --cached`, by file (the large-diff path)
* Dirty Working Tree Included: `yes` (the staged changes are the whole scope)

## Files Reviewed

- **Page input:** the URL state, user input and Connections records that become filters and links.
  - `web/src/lib/utils/packet-query.ts`, `web/src/lib/utils/connection-ref.ts`;
  - `web/src/routes/packets/packets-view.ts`, `+page.svelte`, `QuestionBuilder.svelte`, `ResultQuestion.svelte`, `PacketDrawer.svelte`;
  - `web/src/lib/components/ConnectionDrawer.svelte`, `web/src/lib/components/drawer/content/ConnectionDrawerContent.svelte`, `web/src/routes/connections/+page.svelte`.
- **Page rendering:** daemon data and device-chosen text.
  - `web/src/routes/packets/*.svelte`;
  - `web/src/lib/utils/packet-describe.ts`, `packet-stats.ts`, `packet-library.ts` and `packet-library.json`.
- **Download:** `web/src/routes/packets/DownloadForm.svelte`, against the unchanged `web/src/routes/api/packets/download/+server.ts`.
- **Server-side redirect:** `web/src/routes/tools/tshark/+page.ts`, with `tools/+page.svelte` and `tools/tshark/+page.svelte`.
- **Operator script:** `scripts/remote/verify-packet-library.py` and step 5b of `scripts/remote/deploy-packet-analysis.sh`.
- **Navigation:** `web/src/lib/components/shell/nav.ts`.
- **Not reviewed:** tests and visual fixtures, which hard exclusion 7 leaves out.

## Coverage Summary

* **Changed symbols analysed:** 16. They are `readUrlState`, `packetsUrl`, `filterFor`, `connectionFilter`, `connectionSegments`, `connectionUrl`, `writtenFilter`, `conversationFilter`, `connectionRef`, `packetsHrefFor`, `segmentHref`, `describePacket`, `packetStats`, `serverNames`, the 308 `load`, and `verify-packet-library.main`.
* **Inbound callers inspected:** 6.
  - `devices/[ip]/+page.svelte` renders `ConnectionDrawer`.
  - `connections/+page.svelte` renders `ConnectionDrawerContent` and the inline link.
  - The page's own `goto`, segment links and conversation links.
* **Outbound callees inspected:** 12.
  - `stores/lan.ts`: `isIpAddress`, `inCidr`, `lanStatus`, `addressHref`, `ipHref`, `domainHref`;
  - `drilldown.ts`: `isHostName`, `canonicalName`;
  - `dhcpSubnet.ts`: `toNumber`;
  - `api/packets.ts`: `captureFileUrl`;
  - `hooks.server.ts`;
  - `svelte.config.js`.
* **Sinks considered:**
  - the filter text sent to `/api/packets/*`;
  - every `href` and the `goto` target;
  - DOM text, attribute and style bindings;
  - the form POST and CSRF;
  - the 308 redirect target and query handling;
  - the daemon token in the operator script;
  - shell command construction in step 5b.
* **Daemon checks confirmed for what the page sends** (PR #196, unchanged):
  - the filter is at most 500 characters, NUL/CR/LF are refused, and it is passed as a positional argument with no shell;
  - epoch times must be in a strict format;
  - a window is at most 30 minutes and after 2000;
  - the limit must be 100, 250 or 1000;
  - field-name prefixes are checked against a regex.
* **Regression patterns checked:** removed sanitizers, auth-default flips, public-path changes, and a removed guarantee from the retired `/tools/tshark` page. None was found: the public TShark page is now a fixed redirect, which removes surface.
* **Trusted rule memory:** none.
* **Limitations / unresolved edges:**
  - **The filter in a `/packets` URL runs as written, by design.** The page shows it word for word, and its safety rests on the daemon's argv-only TShark boundary.
  - **A hand-crafted link can show a misleading label.** Its `conn`/`exact`/`device` parameters can put a "whole connection" segment label, or a direction anchor, beside a filter that isn't that connection's. The real filter stays on screen and editing drops the context. This is a display inconsistency for a single-admin app, not a security issue.
  - **Read only through grep:** `FilterEditor.svelte`, `PacketTable.svelte`, `HexDump.svelte` and `ResultCharts.svelte`. The grep found no raw-HTML or style sinks fed by data in them.
* **Not covered (by design):** DoS/ReDoS, rate limiting, dependency CVEs, generic hardening.
* **External analysis consumed:** none.

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
