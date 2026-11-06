# Plan Review Log: NET-160 slice 2b-1 (exact alert pairs, 6h, Home KPI windows)
Started 2026-11-06 evening. MAX_ROUNDS=5.

## Round 1 - Codex

The plan does not yet satisfy the exact-count requirement. These are material correctness gaps.

1. **High — A fixed time window does not freeze the counted records.**

   **Evidence:** Sections A and C equate identical filters and timestamps with identical counts. Counts and lists execute independent searches: `daemon/api/traffic.py:188`, `daemon/api/alerts.py:518`, and `daemon/api/logs.py:648`. Smart-alert aggregation also performs separate searches across composite pages (`daemon/services/alert_intelligence.py:1245–1258`).

   **Impact:** A delayed event indexed after the count request, with `@timestamp` inside the fixed window, appears in the linked list. Deletion or retention can cause the reverse discrepancy. This can happen even when every proposed filter is correct.

   **Fix:** Add a shared search-snapshot contract: compute the count against a snapshot and carry its token into the list and pagination requests. An expired snapshot must produce an explicit expiration state rather than silently rerun against current data. Test insertion of an in-window event between counting and opening the link.

2. **High — The proposed Alerts KPI uses the wrong timestamps after a failed refresh.**

   **Evidence:** Section C explicitly uses `snapshot.from` and `snapshot.to`. In `web/src/lib/stores/alertSnapshot.ts:70`, failure constructs a snapshot with the **new attempted window** but retains the **previous successful data**. Existing severity tiles correctly use `snapshot.data.from/to` (`web/src/routes/alerts/+page.svelte:865–869`); the regression test at `alerts-page.test.ts:860–876` demonstrates this distinction.

   **Impact:** Home displays the old alert count but links to a newer window, violating exactness during an ordinary refresh failure.

   **Fix:** Build the KPI link from `alertCount.from/to`—the response containing the displayed count. Add a success → clock advance → failed refresh test asserting that both displayed count and URL retain the successful response’s window.

3. **High — The traffic failure fallback discards filters while retaining the displayed count.**

   **Evidence:** Section C specifies a range-only `/logs` link when the summary “failed.” Home retains `trafficSummary` on refresh failure: its `settle` call supplies no clearing callback (`web/src/routes/+page.svelte:149`), and failure only marks the source failed (`:124–128`). Connections continues displaying that retained summary (`:627`).

   **Impact:** After a successful load followed by a failed refresh, the old connection count links to all log types over a newly anchored window, without the source exclusions.

   **Fix:** Use the retained summary’s window and exclusions whenever a summary exists, regardless of the latest request’s failure flag. Reserve the range-only fallback for a card with no numeric result. Test initial failure separately from failed refresh.

4. **High — Missing composite keys are deliberately converted into broader or incorrect searches.**

   **Evidence:** Section A falls back to device-wide `ip` when either endpoint is missing; Home’s helper omits empty values. The aggregation explicitly enables `missing_bucket` for all three keys (`daemon/services/alert_intelligence.py:1328–1350`). The plan also acknowledges that a missing `rule.name` is replaced by a display signature.

   **Impact:** For a bucket `(signature=S, source=A, destination=missing)` containing 3 alerts, the fallback also includes `(S, A, B)` alerts. Missing `rule.name` can instead produce zero results. A tooltip does not make either list equal ×3.

   **Fix:** Preserve nullable bucket keys and add explicit missing-field selectors implemented with `must_not exists`. Never interpret a missing bucket key as “omit this restriction.” Test missing source, destination, and signature against neighboring populated buckets.

5. **High — The displayed signature is not necessarily the aggregation key.**

   **Evidence:** Buckets use `rule.name`, but `_normalize_alert_source` prefers an existing `alert.signature` over `rule.name` (`daemon/api/alerts.py:180–185`). Smart alerts then return that normalized display signature preferentially (`daemon/services/alert_intelligence.py:1417–1421`). Section A uses `sa.signature` to filter `rule.name`.

   **Impact:** A bucket keyed by `rule.name=A` whose sample has `alert.signature=B` links to B. This fails even with the keyword mapping fully verified; it is not limited to missing names.

   **Fix:** Return a separate drill-down key taken directly from the composite bucket and use it for an exact `term` filter on the aggregation field. Keep the display signature separate. Add a fixture where `alert.signature` differs from `rule.name`.

6. **High — Device links drop an original filter that is not redundant for array-valued IPs.**

   **Evidence:** Device smart-alert queries include `source.ip=device OR destination.ip=device` (`daemon/services/alert_intelligence.py:1293–1304`). Section A replaces that restriction with only `src` and `dst`. The repository explicitly supports array-valued endpoint fields (`daemon/api/alerts.py:217–228`).

   **Impact:** A document with `source.ip=[device,A]` and `destination.ip=B` contributes to the `(A,B)` composite bucket in the device-filtered aggregation. The proposed link also matches ordinary A→B documents that never involve the device, increasing the count.

   **Fix:** Device links should carry **all three** restrictions: `{ ip: countedDeviceIp, src: bucketSource, dst: bucketDestination }`. Use the stored device identity associated with the response. Add a multivalued-IP fixture containing an unrelated A→B document.

7. **High — Paging during a new Alerts hand-off can replace the correct search with a mixed-window request.**

   **Evidence:** The URL hand-off changes active filters immediately (`web/src/routes/alerts/+page.svelte:1019–1029`), while existing rows and pagination remain visible. `goToPage` uses the old `shownWindow` (`:884–888`), but `listParams` reads the new filters (`:642–650`). Starting that paging request advances `listGuard`, invalidating the intended page-one request (`:771–781`).

   **Impact:** While a new pair/window search is pending, clicking the existing pager can load the new pair over the previous list’s window. The correct response is subsequently discarded, leaving results inconsistent with the URL.

   **Fix:** Disable pagination whenever the requested query identity differs from the displayed query identity, until the replacement search settles. Add a deferred-response test: load A/W1, navigate to B/W2, attempt paging before B resolves, and verify that no B/W1 request can win.

8. **Medium — `parse_single_ip` does not establish the escaping guarantee assumed by the plan.**

   **Evidence:** `daemon/services/excluded_ips.py:497–507` delegates directly to Python’s `ipaddress.ip_address`. A read-only reproduction confirmed that it accepts both `fe80::1%eth0` and `fe80::1%" OR *:* OR "` unchanged. Settings uses this same validator (`daemon/api/settings.py:237`). Section C interpolates validated values inside double quotes without escaping them.

   **Impact:** “Validated IP” does not currently mean an unscoped OpenSearch IP literal or query-safe string. The proposed validation can pass unsupported values downstream instead of returning 400, and the generated query’s quoting assumption is unsound.

   **Fix:** Reject scoped IPv6 addresses in the shared validator and escape quotes/backslashes in a centralized query-literal formatter. Add rejection tests for scope IDs, including embedded quotes and backslashes, plus an actual search test for ordinary IPv6 exclusions.

The proposed request-shape tests and one sampled live comparison would miss several of these failures. The regression cases above need to be part of acceptance, particularly failed refreshes, missing keys, multivalued endpoints, and overlapping navigation.

VERDICT: REVISE

### Claude response
- **#1, PIT snapshot: rejected, but the user-facing part is taken.**
  - Why rejected: PIT ids expire after their keep-alive. Every count on every page would need one. A click minutes later would usually meet "expired", which is worse than a list that includes records that arrived after the count.
  - What's taken: new section D, a one-line note on Alerts and Log Explorer when a link's window ended under an hour before the page loaded. It explains that later records (Zeek logs a connection when it ends) can make the total a little higher.
- **#2, accepted.** The Alerts KPI link uses `alertCount.from/to` (`snapshot.data`), with a failed-refresh test.
- **#3, accepted.** The traffic links use the summary on screen: its window and its exclusions. The range-only fallback is only for a card with no number. Tests cover a first-load failure and a failed refresh.
- **#4, accepted, with a simpler fix.**
  - A group with a null key part gets no link (plain ×N with a title). No new "missing field" selectors.
  - A missing part is never turned into "no filter".
- **#5, accepted.**
  - `/api/alerts/smart` returns `key` (the bucket's raw `rule_name`, `source_ip`, `destination_ip`). Links filter on it.
  - The 2a alert table and detail links switch to the row's raw `rule.name`, with no link when it's absent.
- **#6, accepted.** Device links carry `ip` plus `src` and `dst`, using a multi-valued fixture.
- **#7, accepted and already fixed in slice 2a** (PR #184, commit 8f4929d).
  - While a list request is out, the pager is off (`listPending`; `DataTable` pager `disabled`), and `goToPage` ignores calls.
  - Two tests: paging during a refresh waits, then goes through the new rows' window; paging during an A→B hand-off sends nothing until B lands, then pages B.
  - Both fail on the previous page.
- **#8, accepted.**
  - `parse_single_ip` rejects scoped IPv6 (also tightens Settings).
  - `queryLiteral` escapes `"` and `\` for the Log Explorer query.
  - Tests cover both.

## Round 2 - Codex

The revisions address the stale-response, device-filter, and escaping issues. I also inspected `listPending` and its regression tests; previous finding #7 is resolved. Four issues remain.

1. **High — Section D still contradicts the required exact-count contract.**

   **Evidence:** The Goal promises exactly the displayed count, while §D explicitly permits different totals. The latest Claude response rejects snapshots because clicks minutes later would “usually” encounter expiration. That premise is unsupported: PIT keep-alive is configurable and extendable, and one PIT supports multiple queries. [OpenSearch PIT documentation](https://docs.opensearch.org/latest/search-plugins/searching-data/point-in-time/).

   **Impact:** Correct filters still cannot ensure count equality. The new note also understates the discrepancy: long connections can arrive more than an hour later, backfills need not increase totals only “a little,” and deletion can reduce them. The one-hour cutoff hides the warning without establishing that older windows are immutable.

   **Fix:** Replace §D with a bounded snapshot contract shared by the relevant counts and linked searches, including explicit expiration behavior. Alternatively, weakening the owner’s exact-count requirement needs an explicit owner decision; the review response alone does not establish one.

2. **High — The null-only guard still allows an empty signature to remove the signature restriction.**

   **Evidence:** §A suppresses links only when a key part is `null`. An empty keyword string is an indexed value, distinct from missing. [OpenSearch documentation](https://docs.opensearch.org/latest/query-dsl/term/exists/). However, `web/src/routes/api/alerts/+server.ts:24–25` drops an empty signature, and `daemon/api/alerts.py:379–381` applies no signature filter when it is empty.

   **Impact:** A smart bucket with `key.rule_name=""` and valid endpoints passes the proposed null check. Its link lists every signature for those endpoints instead of that bucket. A sample containing a meaningful `alert.signature` can make this row look entirely normal.

   **Fix:** Extend the shared link-eligibility rule to reject an empty `rule_name`, preserving the plan’s simpler “no exact link available” behavior. Add a fixture with an empty bucket key, a nonempty display signature, and another signature for the same pair; assert that no link is rendered.

3. **Medium — The deployment acceptance checks are incompatible with the newly admitted live-data behavior.**

   **Evidence:** “Verification plan — Device (G11)” still asserts equality between successive live searches, although §D now explicitly permits intervening records. The existing deployment script already recognizes this problem: `scripts/remote/deploy-drill-down.sh:100–104` compares values before and after the API request. The proposed smart-alert selection also does not exclude groups that intentionally have no link.

   **Impact:** A correct filter implementation can fail deployment because of normal ingestion or selection of a null-key group. Conversely, one coincidentally matching live group does not establish query equivalence.

   **Fix:** Make exact equality an acceptance test against a controlled, non-mutating fixture dataset, exercising the aggregation and linked-list queries against the same documents. Include neighboring pairs, mismatched display signatures, multivalued IPs, and IPv6 exclusions. Keep unsnapshotted live comparisons diagnostic.

4. **Medium — The device implementation still targets the signature link, not ×N.**

   **Evidence:** §A explicitly targets `web/src/routes/devices/[ip]/+page.svelte:780`, the signature anchor. The count remains a plain `<span>` at line 772. The proposed device test merely checks “a smart-alert link,” so it would pass with ×N still unclickable.

   **Impact:** The requested interaction—clicking a smart alert’s count—remains absent on the device page despite the signature link receiving correct filters.

   **Fix:** Explicitly make the non-null, eligible group’s ×N an anchor using the same exact-group URL, and test that count link by its accessible name. Keep ineligible counts as plain text.

VERDICT: REVISE

### Claude response
- **#1, accepted as an owner decision.** I put it to the owner on 2026-11-06 as two options:
  - A: a live list, with the exact difference stated. This is my recommendation.
  - B: a PIT snapshot, with an expired state.
  - D now specifies A completely and says B would be re-planned and re-reviewed before any code. Nothing in D is built until the owner answers. The rest of the plan doesn't depend on the answer.
- **#2, accepted.** Eligibility rejects null **and empty** key parts, with a fixture test.
- **#3, accepted.**
  - Equality is tested on a controlled dataset in the existing evaluator fake. It runs the composite aggregation and every eligible link's list over the same documents, with every edge case listed.
  - The signature filter becomes `term`, which the fake evaluates and which states exactness outright.
  - Live device numbers are diagnostic only.
  - For Connections, equality is checked at the query level (shared constants, the excluded list). The `query_string` exclusion is the one part checked only on the device.
- **#4, accepted.** On the device page the ×N is the anchor, with a test by accessible name. Ineligible counts stay plain.

## Round 3 - Codex

Option A still needs four revisions. These findings concern its implementation and verification, not the owner’s choice between A and B.

1. **High — The comparison is not fully bound to the correct navigation and request.**

   **Evidence:** §D assumes every Alerts control uses `setListParams`, but sorting calls `fetchAlerts` directly (`web/src/routes/alerts/+page.svelte:452–456`), paging does likewise (`:900–905`), and refresh uses `loadAll` (`:690`). Neither the proposed Alerts hand-off key nor Log Explorer’s existing key (`web/src/routes/logs/+page.svelte:936–941`) includes `count`.

   **Impact:** A count-only URL change can be ignored. Sorting or refreshing can leave the original comparison attached to newer results. During navigation, a newly parsed count could also be compared with the previous list’s total unless the comparison is committed under the list’s request guard. The plan does not specify what happens when the initial request fails.

   **Fix:** Specify one comparison context tied to the hand-off identity and request generation. Include `count` in navigation detection, commit its observed total only with the corresponding successful response, and explicitly invalidate it on every non-handoff load path covered by §D. Replace the obsolete “10 minutes versus 2 hours” note tests with equal/higher/lower, invalid count, count-only navigation, deferred-response replacement, failure, sorting, paging, and refresh cases.

2. **Medium — The difference text claims causes that the totals cannot establish.**

   **Evidence:** §D says a rise of six means “6 records were logged after that figure was counted,” and explains a decrease through disk-driven deletion. The inputs provide only the clicked count and current total.

   **Impact:** Those values establish a **net difference**, not an arrival or deletion count. Ten additions and four deletions also produce +6. Updated documents, backfills, or query defects can change membership. The current wording would confidently explain a filtering bug as normal ingestion.

   **Fix:** Use factual wording: “You clicked 1,234. This search now matches 1,240 records—6 more.” Describe ingestion, updates, and retention only as possible explanations, without asserting which occurred.

3. **Medium — The proposed evaluator cannot currently run the promised smart-alert acceptance test.**

   **Evidence:** `daemon/tests/fake_drill_opensearch.py:253–256` requires a PIT and does not accept the `index` argument used by these endpoints. Its aggregation evaluator ends with `NotImplementedError` for unsupported kinds (`:167–201`); it does not implement `top_hits`, which smart alerts require (`daemon/services/alert_intelligence.py:1358–1363`). Its ordinary search hits are always empty (`fake_drill_opensearch.py:267`).

   **Impact:** Changing `match_phrase` to `term` is insufficient. The planned endpoint test fails before comparing counts, or risks becoming vacuous if sample hits are bypassed and no eligible groups are returned.

   **Fix:** Explicitly include a test adapter supporting non-PIT indexed searches, document-backed `top_hits` with the expected `_source` shape, and ordinary list hits. Require assertions that the expected eligible groups exist before checking every group’s equality.

4. **Medium — Connections query-string equivalence still has no meaningful acceptance check.**

   **Evidence:** The revised verification checks backend constants and the summary’s exclusions separately. It delegates the actual generated `query_string` to a live diagnostic that accepts any nonzero mismatch.

   **Impact:** An omitted exclusion can return extra records and still pass, with §D presenting the discrepancy as subsequent ingestion. A device without IPv6 exclusions also never exercises the quoted IPv6 expression. Matching backend constants does not verify the frontend’s generated query.

   **Fix:** Add an isolated OpenSearch fixture test comparing the summary query with the actual generated Log Explorer query over fixed documents. Include excluded IPv4 and IPv6 sources, an included source, and a destination-only occurrence of an excluded address. Assert equal totals and expected document membership; keep live-device comparisons diagnostic.

VERDICT: REVISE

### Claude response
- **#1, accepted.**
  - D now ties the comparison to one hand-off and one request: `count` is in both hand-off keys, `linked.gen` is the hand-off request's guard token, and `observed` is set only in that request's success branch.
  - Every other load path clears it: sort, paging and load more, refresh, a control, a typed search.
  - A failed or superseded first request shows no line.
  - The tests cover each case.
- **#2, accepted.** The wording states only the net difference ("1,240 records (6 more)"). Ingestion and retention are listed as possibilities, not as the cause.
- **#3, accepted.**
  - The evaluator fake gains non-PIT `search(index=…)`, ordinary hits (`from`/`size`/`sort`/`track_total_hits`), document-backed `top_hits` with `_source` projection, and `match_none`. Each gets its own test.
  - The equality test first asserts the exact set of linkable groups, so it can't pass empty. It then checks totals and document ids for each.
- **#4, accepted, by changing the design.** The Connections link no longer uses `query_string`.
  - Log Explorer takes `type=zeek.conn` (its existing `log_type`) and a new structured `exclude_src`, which the daemon validates and turns into the same `must_not terms source.ip` clause.
  - That makes equality testable in the fake over fixed documents: excluded IPv4 and IPv6 sources, an included source, and a destination-only excluded address.
  - `queryLiteral` and the quoting concern are gone.

## Round 4 - Codex

The revised comparison logic and test adapter address the previous round. Two problems remain in the new structured-filter design.

1. **Medium — The 50-entry limit can reject links generated from valid Settings data.**

   **Evidence:** §C limits `exclude_src` to 50 entries. Settings validates and deduplicates addresses without a count limit (`daemon/api/settings.py:223–257`), and `build_excluded_ips_filter` applies the complete list (`daemon/services/excluded_ips.py:528–537`).

   **Impact:** With 51 valid excluded addresses, Home successfully displays its count and generates a link that Log Explorer rejects with 400. Truncating the link’s list would instead produce an incorrect count.

   **Fix:** Remove the independent 50-entry limit so search accepts the complete exclusion list the summary applies. Add a regression with 51 distinct valid addresses, asserting successful navigation and matching document membership.

2. **Medium — Clearing the new exclusion chip can restore stale filters and reactivate the count comparison.**

   **Evidence:** §C says the chip clears by writing the URL without `exclude_src`. Existing Log Explorer controls modify local state without updating the URL: `setLogType` at `web/src/routes/logs/+page.svelte:695–700`, the type-chip removal at `:1190`, and `clearAllFilters` at `:761–768`. The revised hand-off reapplies `type` from the URL. Section D relies on `setListParams` removing `count`, but Log Explorer currently has no such helper.

   **Impact:** Open a Home link with `type=zeek.conn&exclude_src=A&count=100`, change the type to All, then clear the exclusion chip. Removing only `exclude_src` from the original URL restores `type=zeek.conn` and retains `count=100`. The ensuing hand-off can compare an intentionally broadened search against the original count. “Clear all” also needs explicit handling of the new exclusion.

   **Fix:** Add a unified Log Explorer filter-update path that serializes the **current effective filters**, removes `count` for user-initiated changes, and clears `exclude_src` through both its chip and “Clear all.” Test changing type before clearing the exclusion, preserving a newly typed query, and ensuring none of these actions resurrects the comparison.

VERDICT: REVISE

### Claude response
- **#1, accepted.** `exclude_src` has no count limit, matching Settings and the summary. Regression: 51 distinct excluded addresses, with search accepted and totals and membership equal.
- **#2, accepted, with the smallest change.** Log Explorer controls stay local, as they are today. Neither clearing the chip nor "Clear all" writes the URL, so nothing can come back from the old URL (the `appliedSearch` guard stops a re-apply).
  - Both clear `excludeSrc`, and every user-initiated change clears the comparison (`linked = null`).
  - A unified URL-writing path for Log Explorer isn't needed for this, and isn't part of this slice.
  - Tests: change the type then clear the chip; a typed query survives; Clear all clears the exclusion; there is never a line afterwards.

## Round 5 - Codex

No remaining material plan issues found. The exclusion-limit and local-filter fixes address the previous findings, with targeted regression coverage.

Option A is sufficiently specified for implementation once the owner selects it. This approves the plan, not an implementation or completed test results.

VERDICT: APPROVED

**Final status:** APPROVED in round 5 (2026-11-06). Section D is built as option A unless the owner picks B.
