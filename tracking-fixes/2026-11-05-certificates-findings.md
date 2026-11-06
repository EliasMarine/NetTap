# 2026-11-05 — Certificates page: what needs a look, with accurate figures

**Status:** built, reviewed and tested on `feature/certificates-findings`. The PR and the G11 check are pending.
- Linear: NET-154.
- Plan: `plans/certificates-findings-plan.md`. Codex reviewed it over 5 rounds and every point raised was folded in.
- Approved mockup: https://claude.ai/artifact/23wLS6BpjpWrwfpffn57Ga

**Problem**

/certificates was an endless list of up to 1,000 certificates that never said whether anything was wrong. The owner wasn't sure what the page was for. Its figures were also wrong in several ways.

**Root cause (accuracy)**

- **The window was the wrong one.** Every query started from x509 records in the window. Zeek relogs a certificate at most once a day, so certificates used in the window went missing.
- **Sessions were credited to the wrong certificate.** A session counted for every fingerprint in its chain, intermediates included. Doc values sort the chain, so the server's own certificate (`chain[0]`) can only be read from `_source`.
- **Lists were cut short.** Each row kept only its top 10 server names and clients, and only its top validation status.
- **"Expired" was judged against now,** not against when the certificate was used.
- **The MITM banner fired for normal sites.** Any site with two issuers raised it, and big sites switch issuers all the time.
- **The handlers blocked the daemon:** they ran OpenSearch queries on the event loop.

**What changed**

- **`daemon/services/cert_overview.py`:** one complete pass per request.
  - It opens a point-in-time snapshot. Partial snapshots are refused.
  - It reads the ssl records that have a chain, sorted by `_shard_doc` and paged with `search_after`. `_source` holds only the chain; every other field comes from `docvalue_fields`.
  - Each session is credited to `chain[0]`.
  - Details come from the newest stored x509 record for each fingerprint, at any time, looked up in chunks of 1,000.
  - Every reply is checked. A timeout, a failed shard or a malformed reply raises `CertQueryFailed`.
  - The pass has a budget: 50 s, at most 200,000 distinct tallies and a 5 MB reply, encoded with `iterencode`.
- **`daemon/services/cert_findings.py`:** pure rules over the exact tallies.
  - Builds the sites, certificates, findings, devices, quiet switches and summary.
  - Finding rules are in §5 of the plan: High for "unverified alongside verified", then unverified, expired-at-use, chain-expired, weak and device-expiry.
  - Each finding names the devices whose sessions it counts.
- **`cert_monitor.py`:** the older endpoints now filter and count the complete pass. The old implementation is kept in an OLD CODE block.
- **`api/certificates.py`:** new `GET /api/certificates/overview`.
  - Every handler runs in a worker thread, one pass at a time behind an `asyncio.Lock`. The lock is held until the thread finishes, even when the client gives up.
  - Every failure answers 503 with its reason: busy, took too long, too much data, or unavailable.
- **`server.py`:** the monitor gets its own OpenSearch client, built from the storage manager's settings (`client_kwargs()`), with retries off.
- **Web:**
  - The proxy gives the overview path 60 s.
  - New `getCertificateOverview()`.
  - The page is rebuilt to the approved mockup:
    - KPIs.
    - Needs a look, as AlertRows with a drawer.
    - Your devices' certificates.
    - All certificates: search, filter pills, and a whole-list sort before the pager cuts a page.
  - The drawer (`CertDetail.svelte`) links every device to `/devices/<ip>`, every server to `/connections?ip=`, and every site to `/tools/ssl-cert?host=`.
  - The loaded figures keep their own window. A failed load of a different window names both windows.
- **Scripts:**
  - `deploy-certificates-findings.sh`.
  - `verify-certificates.py`, run inside the daemon container. It recounts the same snapshot for 24 h, 7 d and 30 d, and checks the limits.
  - `verify-figures.sh` now runs the 24-hour recount; the old x509 cardinality check is in an OLD CODE block.

**Review fixes (before commit)**

The over-engineering review (`/ponytail-review`) found that findings counted sessions they weren't about. All of these are fixed:
- **Verification findings** (couldn't verify, unexpected authority, expired in chain) counted, dated and named every session for that site and certificate, including the ones that verified. A site with 86 verified and 14 failed sessions read "For 100 sessions this one didn't pass" and could name a device whose sessions all verified. The device tally now carries the status, and a finding's sessions, last-seen time, servers and devices come only from its failing sessions.
- **Expired when used** counted, and named the devices from, sessions before the expiry date. After the details lookup, each such certificate (rare) gets one more scan of the same snapshot: sessions after `not_after` whose chain starts with it. The finding uses exactly those sessions.
- **Runs out soon** listed devices that only got an older certificate at that service. Device tallies are now kept per certificate; the device row still covers every certificate at the service.
- **The overview reply sent every certificate twice** (`certificates` and `details`), so a 30-day window reached the 5 MB cap about twice as early. Certificates now go out only as `details`.

**Tests**

- **Daemon:** `test_cert_findings.py` (30), `test_cert_overview.py` (32), `test_cert_monitor.py` (4) and `test_certificates_api.py` (9). They run on raw ssl and x509 documents (`fake_cert_opensearch.py`). Mutation checks were done on the key rules, the reply checks, the failing-sessions-only tally and the after-expiry recount. The full suite gives 2,963 passed.
- **Web:** `cert-view.test.ts` (14), `certificates-page.test.ts` (8), the API client (17) and the overview fixture (6). The full suite gives 2,922 passed. svelte-check reports 0 errors, and check:colors, check:e2e and the visual tests for /certificates all pass.

**Still to do**

- Run `deploy-certificates-findings.sh` on the G11. A 30-day pass within 45 s, 5 MB and 300 MB is a **release requirement**. If it doesn't fit, revise the retrieval before the next release tag.

**Lessons**

- Doc values sort array fields. Anything that depends on the order of an array (here, which certificate is the server's own) must be read from `_source`.
- A pager over a client-sorted table must sort the whole list first, or it ranks only the rows on screen. NET-140 was the same bug on Connections.
- A finding's count, time and devices must come from the sessions that make it a finding, not from the group it was found in. Test data with one status per group can't catch this, so mix the statuses in at least one test.
