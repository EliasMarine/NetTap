# Plan: Certificates page, what needs a look, with accurate figures

_Round 3 revision, after Codex rounds 1–3; see PLAN-REVIEW-LOG.md. Round 3 replaced chain-membership matching with ordered leaf extraction (Codex r3-1..3); round 4 tightened expiry, detail references and runtime bounds; round 5's two points (no age-only cache; bounded serialisation) are folded in. Final: 5 rounds, ending REVISE with every point accepted._ Replaces the UI-redesign plan (git history `983dff5:PLAN.md`). The owner approved the mockup on 2026-11-05 (https://claude.ai/artifact/23wLS6BpjpWrwfpffn57Ga): "ship it and merge". Linear: NET-154. Branch: `feature/certificates-findings`._

## 1. Goal

/certificates tells the owner which certificates need a look and why, in plain English. Every figure on it must be factually correct for the chosen window (24 h / 7 d / 30 d). When a figure can't be complete, the page says so instead of showing a smaller number as fact.

## 2. Accuracy problems in the current code

1. **Certificates used in a window go missing.** Zeek writes a certificate to x509.log about once a day while it is in use. Every query starts from x509 records inside the window (`cert_monitor.py:405–450, 338–379, 570–629`).
2. **Session data is cut to the top 10 or the top 1** (`cert_monitor.py:486–491`). This applies to server names, clients, the destination, the TLS version and the validation status, so failures in a minority of sessions are hidden.
3. **Whole-certificate figures are credited to its busiest server name** (`:194–208, 234`). A certificate that serves `a.example` 90 times and `b.example` 10 times shows 100 sessions for `a.example`.
4. **x509 log records count as sessions when there is no matching session** (`:225–238`).
5. **"Expired" is judged against now, not against when the certificate was used** (`:160–169`).
6. **Every site that uses two authorities is labelled MITM** (`+page.svelte:306–318`). Big sites do this routinely.
7. **No pager** (`+page.svelte:341`).
8. **Partial searches are used as if complete:**
   - `_all_buckets` logs `complete=False` and carries on (`:332–336`).
   - No search checks `timed_out` or `_shards.failed`.
9. **The handlers run their searches on the daemon's event loop** (`api/certificates.py:65, 144, 169`). A slow search blocks every other request, including health checks.

## 3. Definitions (the page's facts)

- **Session:** an ssl record in [from, to] with a non-empty `zeek.ssl.cert_chain_fps`, after excluded IPs are removed. TLS 1.3 sessions and resumed sessions carry no chain and are not counted. The page says this.
- **The session's certificate** is the first entry of its chain, read in order from `_source`. Zeek logs the server's chain leaf first, and doc values lose that order.
  - This is exact per session: no matching against known certificates, no ambiguity (Codex r3-1..3).
  - Every session is credited to exactly one certificate.
- **Certificate details** come from the newest x509 record with that fingerprint, at any time OpenSearch holds. A certificate's content is the same whatever its role, so the role is not used.
  - When no record is held, the certificate is **"details unavailable"**: still a certificate, with exact sessions, sites, statuses and times, but no issuer, dates or key.
  - **Reconciliation:** sessions = sessions with details + sessions without details. This is asserted in code and tests.
- **Fields read per session:**
  - `cert_chain_fps` (`_source`, ordered)
  - `zeek.ssl.server_name`, `destination.ip`, `destination.port`, `source.ip`, `zeek.ssl.validation_status`, `zeek.ssl.ssl_version` and `@timestamp` (doc values)
  - A missing field is kept as "none", never dropped.
- **Site:** the server name (SNI). A session with no SNI is filed under "no server name", per server IP. A name is never borrowed from the CN or SAN.
- **Endpoint:** (server IP, server port, site).
- **On your network:** the server IP is in 10/8, 172.16/12, 192.168/16, 169.254/16, fc00::/7 or fe80::/10. An unknown server IP is "unknown", which is neither public nor yours.
- **Verified:** at least one session, and every session's status is "ok".
- **Failed verification:** a present, non-empty status that isn't "ok". A missing status is "not checked", never a failure and never "verified".

## 4. Daemon changes

1. **`CertificateMonitor.overview(from, to, excluded_ips, pit_id=None, budget)`** builds every figure from complete data:
   1. **PIT:** opens a PIT on the network index unless one is passed. It closes only a PIT it opened, in `finally` (Codex r3-7).
   2. **Session scan:**
      - Query: ssl, [from, to], `exists cert_chain_fps`, excluded IPs as `must_not`.
      - `_source: ["zeek.ssl.cert_chain_fps"]` plus `docvalue_fields` for the rest.
      - Sort `_shard_doc`, `size` 10,000, paged with `search_after` on the PIT.
      - Each page is folded straight into accumulators keyed by (fp, site, server IP, port, status, version) → sessions, first, last, and by (fp, site, server IP, port, client) → sessions. The raw hits are not kept.
   3. **Details:** x509 records with the distinct fingerprints, in chunks of 1,000.
      - A `terms` aggregation on the fingerprint with `size` = chunk length and `shard_size` = chunk length × 2.
      - `top_hits` gives the newest record per fingerprint.
      - With `size` at least the number of candidates, every bucket comes back.
2. **Completeness:**
   - Each reply is checked:
     - `timed_out` false and `_shards.failed` 0;
     - the expected `hits.hits` list, with a `sort` on every hit;
     - the expected aggregation and bucket list.
   - Anything else raises `CertQueryFailed`, and the handler answers 503 "Certificate data is unavailable right now".
   - There is no bucket cap to hit: the scan is bounded by the budget below.
3. **One end-to-end budget (Codex r3-6):**
   - It starts when the request arrives (monotonic clock): 50 s, while the proxy timeout for this path is 60 s (`SLOW_PATH_TIMEOUT_MS`).
   - Admission is an `asyncio.Lock` taken in the handler before entering the executor, with a wait of at most the remaining budget. A request that can't get in answers 503 "busy".
   - Every search gets `request_timeout` and a body `timeout` from the remaining budget.
   - The monitor has its own OpenSearch client, built from the storage manager's settings with `max_retries=0` and `retry_on_timeout=False`. The manager exposes its client settings; `server.py:1205` builds the monitor with them.
   - The budget is checked between pages, before post-processing, and before the reply is serialised; past it, the pass raises "took too long" (503) (Codex r4-4).
   - **Runtime state limit:** the accumulators may hold at most 200,000 distinct keys in total. Past that, the pass stops and answers 503 "too many distinct certificate uses to show for this window" before allocating more.
   - **Bounded serialisation (Codex r5-2):**
     - The reply is encoded with `json.JSONEncoder().iterencode`, with the bytes and the deadline checked as chunks are produced.
     - Over 5 MB, or past the deadline, the encoding stops and the handler answers 503; it never sends a partial body.
     - Nested lists are capped too, each with its own total: a site's certificates, clients and servers at 200, and a certificate's sites, clients and servers at 200.
4. **Built in Python** (new `services/cert_findings.py`, pure functions over the accumulators):
   - `certificates` (one row per certificate, details or "unavailable")
   - `sites`
   - `findings` (§5)
   - `devices` (your-network endpoints)
   - `quiet_switches`
   - `summary`: certificates, certificates without details, sites, sessions, findings by severity, local certificates (distinct), local endpoints, and the window
   - **Everything is computed over the complete data before any truncation (Codex r3-4).** The reply then paginates each list separately: `sites`, `certificates`, `findings` and `devices` are each capped at 5,000 rows, with `<list>_total` and `<list>_truncated`. The page shows a notice for each truncated list.
   - **`details`:** a de-duplicated map {fp: certificate facts} covering every fingerprint referenced by any returned site, finding or device row, whether or not that certificate is in the capped `certificates` list (Codex r4-2). The drawer reads only this map.
     - "Details unavailable" means there's no stored x509 record.
     - A certificate left out only by truncation still has its details here.
5. **The old endpoints are projections of the complete internal data**, never of a truncated list:
   - `/api/certificates` returns `certificates` + `total`.
   - `/expiring`, `/self-signed`, `/issuer-changes` and `/stats` are filters and counts over the complete rows. "Self-signed" means subject equals issuer (self-issued); `expired_count` and `expiring_count` are as of now. These are documented.
   - New: `/api/certificates/overview`, which the page uses. The replaced methods stay in OLD CODE blocks.

## 5. Finding rules (`services/cert_findings.py`)

Each finding names its site, its certificate and its evidence. One finding is made per (site, certificate, kind).

| Severity | Kind | Rule | Title (example) |
|---|---|---|---|
| High | unverified-alongside-verified | At a site, a certificate has a failed-verification status (§3; not an expiry status) in sessions to a public server, and a certificate from a different authority (by issuer O, else issuer CN) is verified at the same site in the window. Coexistence only; no direction is claimed (Codex 10). | "bank.example presented a certificate that couldn't be verified, alongside a verified one from another authority" |
| Medium | unverified | As above, but with no verified certificate from another authority at the site. | "Couldn't verify the certificate for cdn.example.net" |
| Medium | expired-at-use | The certificate's `not_after` is before its last session at the site, with any server. The evidence gives the expiry date and the last session time. | "legacy.example.com was presented after its certificate expired" |
| Medium | chain-expired | Any session at the site carries an expiry status (contains "expired"). The status alone is the evidence, with or without certificate details. It is replaced by the more specific expired-at-use only when the leaf's dates show the leaf itself was past `not_after` at its last session (Codex 8, r4-1). | "Zeek found an expired certificate in the chain for api.example.org" |
| Low | weak | SHA-1 or MD5 signature, or an RSA/DSA key under 2,048 bits. Sites and servers are listed. | "printer.lan uses weak encryption (SHA-1)" |
| Low | device-expiry | For each your-network endpoint (server IP, port, site), the certificate with the latest session. If that certificate's details are unavailable, there's no finding and the device row reads "Runs out: unknown (details unavailable)". Otherwise the finding fires when `not_after` is within 30 days of now, or has already passed with no session after it (if there was one, it is expired-at-use). Worded "the certificate it last presented" (Codex 11, r2-3, r2-6). | "NAS (192.168.1.10): the certificate it last presented runs out in 12 days" |

- A certificate whose details are unavailable still takes part in every rule that doesn't need its details: unverified, unverified-alongside-verified (its authority counts as unknown, so it never counts as "another authority") and chain-expired. It is shown as "details unavailable".
- Sessions to a server on your network that fail verification (self-signed, a private CA) are **not** findings. They show in the Your devices table with their status. Sessions with an unknown server IP are treated like public ones, and the evidence says the address is unknown.
- **Status text:**
  - The statuses are OpenSSL's strings: "ok", "self signed certificate", "self-signed certificate in certificate chain", "unable to get local issuer certificate", "certificate has expired", and so on.
  - "Expiry status" means a status containing "expired".
  - The raw status is always shown in mono.

## 6. Web changes

- **`src/lib/api/certificates.ts`:**
  - Types for the overview reply.
  - `getCertificateOverview(from, to)` throws on failure.
  - The old helpers are kept; their types gain `statuses` and `total`.
- **Page (`src/routes/certificates/+page.svelte`)**, following the page recipe:
  - **Head:** title; a sub line ("Certificates sent in TLS 1.2 and older connections; TLS 1.3 hides them"); 24h / 7d / 30d pills (default 7d).
  - **KPIs (`c-4`):**
    - Needs a look: findings, with a High chip.
    - Your devices' certificates: `summary.local_certificates` (distinct certificates), with "on N services · soonest runs out in D days" (Codex r2-7).
    - Certificates seen: `summary.certificates`, with "across N sites · TLS 1.2 and older".
    - When `summary.certificates_without_details > 0`, a notice: "N certificates have no stored details. Their sessions are counted, with issuer and dates shown as unavailable."
    - A notice for each truncated list.
  - **Needs a look (`alert-layout`, `c-8` + drawer `c-4`):**
    - One `AlertRow` per finding: a plain title, raw evidence in mono, the server (named) and the session count.
    - Foot: "N sites used more than one authority and every certificate verified · Show them" (toggles a list).
    - Empty state: "Nothing needs a look" plus what was checked.
  - **Your devices' certificates (`c-12`, DataTable):** Device (registry name or IP) | Site | Authority | Verification | Runs out | Sessions | Last seen.
  - **All certificates (`alert-layout`, `c-8` + drawer):**
    - Search over site, authority and device; pills All / Needs a look / Your devices; DataTable of `sites` with a pager of 25.
    - Columns: Site | Used by | Authority | Certificates | Sessions | Last seen | Status.
    - A truncation notice when `sites_truncated`.
  - **Drawer (`CertDetail.svelte` beside the page)**, for a finding or a site:
    - Plain explanation, "What to do", and per certificate: authority, valid from and to, statuses with session counts, key and signature, TLS versions, sessions, first and last session, clients (named), servers and SHA-256.
    - Actions: View connections (`/connections?ip=<server>`) and Check it now (`/tools/ssl-cert?host=<site>`, only when the site is a name).
  - **Loading, empty and error:** each card has `CardState`. The loader uses `registerPageRefresh` with the load guard.
    - The loaded reply keeps its own window. All card subs and KPIs describe the loaded window, not the selected pill.
    - A failed load of a different window says: "Couldn't load the last 30 days; showing the last 24 hours loaded at 10:02." A failed refresh of the same window uses `loadFailed(what, true)` (Codex r2-10). Device names come from `getRegistryDevices({limit: 200})` + `namesByIp`; when that fails, IPs show.
- **Removed from the page:** the four old KPIs, the MITM banner and the Expiring and Self-signed filters. The old markup is kept in OLD CODE blocks.

## 7. Tests and verification

- **Daemon unit tests** use a fake OpenSearch built from **raw ssl and x509 documents**. The fake applies the query's time range, `terms`, `exists` and `must_not` filters, serves PIT `search_after` pages with `_source` and `docvalue_fields`, and computes terms and `top_hits` for the details lookup from the documents (Codex 14). Cases, each failing on today's code:
  - a certificate used in the window whose x509 record is 5 days older
  - details missing → counted in sessions without details
  - a client certificate (`client_cert` true) never listed
  - a certificate shared by two sites → per-site sessions are exact
  - a certificate served from a LAN and a public IP → the public failure is still a finding
  - 15 server names and 15 clients → none lost
  - a minority failing status → counted
  - a missing status → "unchecked", and the site is not "verified"
  - an expired intermediate → chain-expired
  - an expired leaf → expired-at-use
  - a renewed LAN certificate → no expiry reminder
  - excluded IPs
  - a timed-out reply, a failed shard, a malformed reply (no hits list, a hit without `sort`, no aggregation or buckets) → `CertQueryFailed` → 503
  - the handlers run off the event loop; a second pass waits for the lock; the deadline raises
  - every search carries the same PIT; a PIT the pass opened is closed even when it fails; a PIT passed in is left open
  - a chain `[A, B]` where B has details and A doesn't → the session goes to A ("details unavailable"), never to B
  - reconciliation: sessions = with details + without details
  - a 5,001-certificate fixture whose only finding and only local certificate are outside the first 5,000 rows → both still in findings, devices and the summary
  - the generated query: `_source` holds only the chain, `docvalue_fields` holds every §3 field, and a missing field is kept as "none"
  - budget: a slow fake search → the pass stops at the deadline, there are no retries, and a second request is refused once the budget is used up
  - a scan that finishes just before the deadline with heavy post-processing → 503, not a late reply
  - high cardinality above the 200,000-key limit → 503, with no partial figures
  - one site with 10,000 certificates → nested caps apply, and the reply stays under 5 MB
  - serialisation running past the deadline or past 5 MB → 503, with no partial body
  - a session with status "certificate has expired" and no certificate details → a chain-expired finding
  - a finding whose certificate is outside the capped `certificates` list → its drawer shows the stored issuer and dates from `details`, not "unavailable"
  - two clients on two servers with no SNI → separate sites, each with its own clients
  - a NAS with A (details) then B (no details) → no expiry reminder for A; its row reads "unknown"
  - unchecked-only sessions with a verified alternative → no unverified finding
  - two ports on one IP with separately renewed certificates → separate endpoints
- Web: the 24 h load succeeds, then the 30 d load fails → the notice names the window shown, and the KPIs keep their 24 h wording.
- **`cert_findings.py`:** table-driven tests for every rule and wording.
- **Web:** page tests (findings, the failure state never reads "none", notices, refresh contract, pills and pager, drawer and Escape) and fixture tests (`fixtures/certificates.ts` + `.test.ts`). `npm run test:visual` baselines are updated.
- **On the G11:** `scripts/remote/deploy-certificates-findings.sh`, then `scripts/remote/verify-certificates.py`, run inside the daemon container. The verifier opens and closes its own PIT and passes it to `overview()` (Codex r3-7).
  - **Independent recount for 24 h, 7 d and 30 d:** its own code pages the same PIT with `search_after`, takes `chain[0]` per session and counts per certificate, per site and per status.
  - **Assertions:**
    - resolved attribution: sessions per certificate and per site are equal;
    - coverage: certificates without details are equal;
    - reconciliation: total sessions equal the raw count of eligible ssl records (an exact `track_total_hits` count).
  - **Cross-check:** it reports how many sessions have their `chain[0]` certificate elsewhere in another session's chain, a data-quality figure for Malcolm's chain order.
  - **Limits, which fail the run:** each window's pass time (30 d ≤ 45 s), reply size ≤ 5 MB, daemon RSS growth during the pass ≤ 300 MB, all printed.
  - **A 30-day pass that succeeds within these limits is a release requirement** (Codex r4-3). The scan is benchmarked on the G11 before the UI work is finished.
    - If 30 d doesn't fit, the retrieval is revised before release, while keeping ordered attribution and the 30-day window.
    - Any cache needs its own reviewed design: invalidation on late data, exclusions, partial boundary days and snapshot consistency. It is not part of this change (Codex r5-1).
    - Removing the window is not an option.
  - It also reads Zeek's `X509::relog_known_certificates_after` from the zeek-live container, for the record.
- **Gates:** `npm run check:colors`, `npx svelte-check --threshold error`, `npx vitest run` and `cd daemon && python -m pytest`.

## 8. Not in this change (later)

- Old encryption (TLS 1.0/1.1) per device.
- Notifications before your devices' certificates expire.
- The share of connections hidden by TLS 1.3.
- Grouping by registered domain.
- A background snapshot cache: the pass runs per request in a thread, and is revisited if the G11's 30-day time is too slow.

## 9. Gates

`/codex-review` until APPROVED → implement → `/deep-review` (it touches `daemon/api/`) and `/ponytail-review` → PR → two-angle review → `gh pr checks` → squash merge (owner: "ship it and merge") → deploy script for the G11.
