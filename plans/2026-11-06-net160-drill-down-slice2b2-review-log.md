# Plan Review Log: NET-160 slice 2b-2 (raw Suricata category pages)
Started session start. MAX_ROUNDS=5.

## Round 1 - Codex

The plan needs revision. Its central “one filter means matching counts” claim misses several existing behaviours.

1. **High — The web list proxy drops the new filter.**

   **Evidence:** Plan A2/B7; [web/src/routes/api/alerts/+server.ts:10](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/web/src/routes/api/alerts/+server.ts:10>) explicitly copies allowed query parameters and has no `suricata_category`. The catch-all proxy handles the new detail/timeline paths, but cannot override this explicit list route.

   **Impact:** Detail and timeline show one category while the table lists all categories. Daemon-only checks and mocked fetch tests can both pass.

   **Fix:** Add `suricata_category` to the client serializer and explicit list proxy, with a proxy test asserting that its exact value reaches the daemon, including special characters and an explicitly empty value.

2. **High — The assumed URL-window handling does not exist, and pagination changes the window.**

   **Evidence:** Plan B10 claims existing category-page support for `from`/`to`/`range`. In [the category page:106](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/web/src/routes/alerts/[category]/+page.svelte:106>), the range starts at `24h`; `getTimeRange()` at line 280 always uses `Date.now()`. `fetchAlerts()` at line 415 recomputes it for paging and sorting. During overlapping refresh/paging, `loadAll()` can commit detail and `shownWindow` while rejecting its stale list.

   **Impact:** A link from a historical seven-day list opens the current 24 hours. Paging can then produce rows and totals from a different window than the headline/chart; overlapping loads can associate links with the wrong window.

   **Fix:** Explicitly implement URL-window ingestion and a committed query context containing `{kind, name, from, to}`. Paging/sorting must retain that context; refresh must coordinate its replacement across cards and list. Add tests with an advanced clock, same-route URL changes, and paging during refresh.

3. **High — Top-signature links discard the raw-category constraint.**

   **Evidence:** Plan B7 reuses the page unchanged apart from fetcher selection. [The category page:665](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/web/src/routes/alerts/[category]/+page.svelte:665>) builds signature-only links; lines 858–865 attach them to category-filtered signature counts. The Alerts destination’s `LIST_PARAMS` and `listParams()` also omit `suricata_category`.

   **Impact:** If the same rule name occurs under multiple raw categories during the window, a bar showing three alerts opens a list containing additional categories. Nothing in the plan establishes an invariant preventing this.

   **Fix:** Make signature drill-downs preserve the category predicate end to end, either within the category page’s list or through supported Alerts URL state. Test one signature shared by two categories and assert destination document IDs as well as totals.

4. **Medium — Missing signatures become links to the literal rule name `"Unknown"`.**

   **Evidence:** Plan explicitly seeds missing `rule.name`. [daemon/api/alerts.py:1051](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/api/alerts.py:1051>) converts the missing bucket key to `"Unknown"`; the top-signature response loses that distinction. The signature list filter at line 402 is a literal term query.

   **Impact:** A nonzero missing-signature bar opens an empty or unrelated list. A real `"Unknown"` signature plus the missing bucket also produces duplicate `BarList` keys.

   **Fix:** Preserve the nullable raw signature key separately from its display label. Give missing buckets distinct UI keys and leave them unlinked unless an explicit missing-signature filter is implemented. Test missing and literal `"Unknown"` together.

5. **High — Identical filters and time bounds do not provide a consistent data snapshot.**

   **Evidence:** Plan A3/A4 promises equality across independent searches. [daemon/storage/all_buckets.py:38](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/storage/all_buckets.py:38>) searches the live index for every composite page; detail, address queries, timeline and list likewise run separately.

   **Impact:** A late-indexed alert whose timestamp falls inside the fixed window can appear in only some results. Even one detail response can combine signature counts and address counts from different index states. Absolute `from`/`to` alone cannot prevent this.

   **Fix:** Define a shared snapshot contract for a page load and its pagination—for example, a combined initial response backed by one PIT, with a bounded snapshot token for subsequent list requests. Add a fake test that inserts an in-window document between searches.

6. **High — Incomplete OpenSearch results are presented as exact.**

   **Evidence:** [daemon/storage/all_buckets.py:41](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/storage/all_buckets.py:41>) turns missing aggregation data into an empty, “complete” result and does not check timeouts or failed shards. `_every_signature` and `_alerts_by_ip` only log when enumeration hits its cap. Plan A3 nevertheless treats their output as exhaustive.

   **Impact:** Partial results can become successful undercounts or false empty states. The proposed happy-path equality fixtures do not exercise these failures.

   **Fix:** Use checked search responses and propagate incomplete enumeration as an error or explicitly unavailable figure. Reuse the validation patterns in `daemon/storage/snapshot_search.py`; test `timed_out`, failed shards, missing aggregations and forced enumeration caps.

7. **Medium — Address counts double-count an alert when the same IP occupies both ends.**

   **Evidence:** [daemon/api/alerts.py:1581](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/api/alerts.py:1581>) computes each address’s count as source count plus destination count. The page labels this “alerts per address.”

   **Impact:** One document with `source.ip == destination.ip` produces two “alerts” for that address, while an `ip=` list and OpenSearch document count return one.

   **Fix:** Count the source-or-destination union per address and add a same-IP fixture. Also correct the plan’s missing-name explanation: `_alerts_by_ip` already calls `_signature_filter`, whose missing-field branch at lines 1060–1065 includes unnamed alerts.

8. **Medium — Displayed-category links are not guaranteed to target the indexed category.**

   **Evidence:** Plan B9 claims the originating row is always in the destination list. [daemon/api/alerts.py:193](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/api/alerts.py:193>) prefers `alert.category` over `rule.category`; `daemon/services/live_connections.py:1300` does the same. Checking mapping absence does not establish that these source values cannot differ.

   **Impact:** A displayed fallback category can link to a `rule.category` query that excludes the originating alert. The current fake also constructs returned hits from its indexed view, so an unmapped-source fixture needs care.

   **Fix:** Establish an explicit canonical category key in both response paths, backed by `rule.category`, and use it consistently for display/linking. Test conflicting source values and missing canonical values rather than relying solely on mapping checks.

9. **Medium — Step 7c can pass a materially incorrect implementation.**

   **Evidence:** Plan C11 says totals “must be equal,” but fails only when a nonzero count opens an empty list.

   **Impact:** Detail `100`, timeline `80`, list `1,000`, and OpenSearch `100` all pass. That is an availability check, not the stated factual-accuracy gate.

   **Fix:** Add a strict equality gate using controlled stable data or the shared snapshot contract. Keep live-ingestion diagnostics separate; a mismatch must not be reported as successful verification.

VERDICT: REVISE
### Claude response

**The design changed.** The page is now a snapshot drill-down, like the address and domain pages: a new `daemon/api/suricata_categories.py`, using `run_drilldown`, `SnapshotSearch` and `chart_slots`. It is no longer the 941-line NetTap-key page reused. That answers #2, #5 (inside the page), #6 and #7 at the root, without touching the key page.

| # | Decision | Change to the plan |
|---|---|---|
| 1 | Accepted | The list proxy forwards `suricata_category`, with a proxy test. |
| 2 | Accepted, by avoiding it | The new page reads `range`/`from`/`to` from the URL, and its figures keep the response's window. The key page's limits stay as slice 2a recorded them; this slice doesn't touch the key page. |
| 3 | Accepted | The Alerts page gains a `suricata_category` URL parameter and chip. Rule links carry both `signature` and the category. |
| 4 | Accepted | `rule_name` is nullable. A null rule shows "No rule name", is not a link and has its own row key. |
| 5 | Partly accepted | Every figure on the page comes from one PIT. The lists the page links to are live searches, which is section D (owner decision pending), the same as slice 2b-1. Equality is tested on fixed data and on Step 7c's settled window. |
| 6 | Accepted | The page uses checked snapshot searches. The Alerts list reply is now checked too (`timed_out` or a failed shard gives 502). `complete` flags are surfaced in the UI. |
| 7 | Accepted | Sources and targets are reported separately, never summed. Each count links to `src=`/`dst=`. The plan's `_alerts_by_ip` note is gone with the reuse. |
| 8 | Accepted | The normalizer and the live drawer return `rule_category`. A shown category is a link only when `rule_category` contains it. |
| 9 | Accepted | Step 7c uses a settled window that ends 10 minutes ago. Page, list, `_count`, timeline sum and severity sum must be equal, or the step prints ✗. |

**New risks:**
- The list's shard check could turn a silent undercount on the G11 into a visible 502. This is checked before merge.
- The cost of the busiest category is timed in Step 7c.

## Round 2 - Codex

The revision resolves several earlier findings, but material correctness gaps remain.

1. **High — “Also tagged” links do not represent their counts.**

   **Evidence:** A3 counts category B within category A’s base query: `A AND B`. B6 links to B’s unrestricted category page. The verification plan incorrectly asserts that B’s total equals the intersection.

   **Impact:** With one alert tagged `[A, B]` and another tagged `[B]`, A shows B with count **1**, but its destination shows **2**. This fails even on immutable data.

   **Fix:** Give the count an intersection-list destination that preserves both category predicates. Add that filter end to end and test the `[A,B]` plus `[B]` counterexample. The category label can separately navigate to B’s overview.

2. **High — The timeline specification reintroduces a documented counting bug.**

   **Evidence:** A3 specifies a `date_histogram` with `extended_bounds`. However, [drilldown_runner.py:112](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/api/drilldown_runner.py:112>) returns a complete `date_range` aggregation. [time_slots.py:1](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/storage/time_slots.py:1>) documents why: the G11’s histogram implementation placed records in incorrect buckets.

   **Impact:** A histogram can misstate activity over time even when its bucket sum equals the headline total. The proposed sum assertion would miss that.

   **Fix:** Specify `"aggs": {"timeline": chart_slots(from, to)}` directly, as the domain endpoint does. Test individual bucket counts against their corresponding range queries, including boundary timestamps.

3. **Medium — Truncated enumeration cannot establish “Top 20 of N addresses.”**

   **Evidence:** A3/B6 promise `distinct` and “Top 20 of N,” including when enumeration is incomplete. [SnapshotSearch.groups:228](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/storage/snapshot_search.py:228>) pages composite keys and stops at its cap; it does not retrieve the globally busiest buckets first.

   **Impact:** Sorting the retrieved prefix produces neither a proven global top 20 nor an exact distinct count. A generic “incomplete” notice does not make those specific claims true.

   **Fix:** Define `distinct: null` when incomplete and remove the global “Top” claim in that state. Show “Highest counts among the N addresses examined.” Apply explicit incomplete-state handling to rules and co-categories too, with a forced-cap test whose busiest address lies beyond the cap.

4. **Medium — The proposed error handling does not match the helpers being reused.**

   **Evidence:** A2 calls `checked()` a one-line change returning 502. It actually raises `QueryFailed` or `TooSlow`; [alerts.py:545](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/api/alerts.py:545>) catches only `OpenSearchException`. Separately, A3 claims `run_drilldown` maps `TooSlow` to 504, but [drilldown_runner.py:218](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/api/drilldown_runner.py:218>) returns **503**.

   **Impact:** A literal implementation leaves list validation exceptions uncaught, producing 500s instead of the promised response. Page timeout tests and UI handling would target the wrong status. Also, `checked()` alone does not validate `hits.total`; the current list parser still defaults missing totals to zero.

   **Fix:** Explicitly catch `QueryFailed` around list validation, use `total_hits()` for the exact total, and document the existing 503 timeout contract for the page. Test these actual response paths.

5. **Medium — Empty rule names still produce an inexact drill-down.**

   **Evidence:** A3 preserves composite keys, while B6 excludes only `null` rule names from linking. An empty string is a separate bucket. [alerts.py:395](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/daemon/api/alerts.py:395>) ignores `signature=""`; the client serializer and web proxy also drop it. The repository already includes empty rule names in its drill-down fixtures.

   **Impact:** An empty-name bucket can open the entire category rather than its own count.

   **Fix:** Treat both null and empty rule keys as unlinked unless an explicit empty-signature filter is implemented. Preserve distinct row keys and add fixtures containing null, empty, literal `"Unknown"`, and an ordinary signature.

6. **High — Adding the category filter exposes another count mismatch on the Alerts destination.**

   **Evidence:** B7 adds persistent category filtering, but [alerts/+page.svelte:733](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/slice2b2/web/src/routes/alerts/+page.svelte:733>) loads Top signatures without list filters. Its activation handler at line 903 changes only `signature`, preserving the new category parameter.

   **Impact:** After arriving from a category page, a window-wide signature row showing **100** can filter the list to **3** category-specific alerts. The severity tiles already avoid this by constructing a fresh URL; signature rows do not.

   **Fix:** Make activation of a window-wide signature count construct a fresh signature-only URL using that count’s committed window, clearing `suricata_category` and other narrowing filters. Add a test starting from a category-filtered Alerts URL.

7. **High — The snapshot-to-live-list mismatch remains unresolved, rather than settled.**

   **Evidence:** Latest Claude response #5 explicitly accepts only page-internal consistency. Tradeoff 4 leaves destination lists live, and verification deliberately demonstrates that a later list can differ. The cited Section D is pending and unimplemented; this plan supplies neither snapshot-backed navigation nor a difference display.

   **Impact:** The revised page can still show a count that differs from its destination. Ending the device-check window ten minutes ago does not establish the required guarantee for normal users, backfills, or retention.

   **Fix:** Make Section D an explicit release dependency for these count links. Under the stated exact-equality requirement, implement snapshot-backed destinations with an expiry state; do not treat fixed-data equality as satisfying the live contract.

8. **Medium — Encoded-category routing is left without an executable integration test.**

   **Evidence:** The risks section substitutes an encoding-helper test for testing SvelteKit routing and defers verification to a device with no slash-containing category. The repository already has a Playwright fixture harness.

   **Impact:** Neither helper tests nor daemon route tests establish that `/alerts/suricata/A%2FB` survives browser navigation, SvelteKit parameter decoding, and proxy forwarding unchanged.

   **Fix:** Add a fixture-backed Playwright test navigating directly to a category containing `/`, `%`, `&`, and spaces, then assert the exact name received upstream and the rendered result. No real G11 category is needed.

VERDICT: REVISE
### Claude response

| # | Decision | Change to the plan |
|---|---|---|
| 1 | Accepted | The Also tagged count is plain text ("N of these alerts"); only the name links to that category's page. The test uses your `[A,B]` + `[B]` counterexample. |
| 2 | Accepted | The timeline is `chart_slots(from, to)` (`date_range`), as the domain page uses. Each bucket is tested against a `range` count of its bounds, boundaries included. |
| 3 | Accepted | When enumeration stops: `distinct: null`, `examined: N`, and the wording "Highest counts among the N … read". Applies to sources, targets, rules and also-tagged. A forced-cap test puts the busiest key beyond the cap. |
| 4 | Accepted | The list uses `checked()` + `total_hits()` and catches `QueryFailed` → 502. The page keeps `run_drilldown`'s contract: 502, and 503 for `TooSlow` or a busy slot. Tests cover these. |
| 5 | Accepted | A null or `""` rule is unlinked, with distinct row keys. A literal "Unknown" is linked. The fixtures cover all four. |
| 6 | Accepted, confirmed | `filterBySignature` (alerts/+page.svelte:903) changes only `signature`. A Top signatures row now sets a fresh URL with `signature` + the card's committed window, clearing every other list filter. This also fixes the same mismatch with `ip`/`src`/`dst` from slices 2a/2b-1. Choosing the row again still clears the filter. |
| 7 | Not accepted for this slice | Section D is the owner's open decision (A: state the net difference; B: snapshot list with expiry). It applies to every existing drill-down link (slices 1, 2a, 2b-1 are merged with the same contract), so it is built once, across all links, after the owner chooses. Building snapshot-backed navigation for this page alone would pre-empt that choice. The plan's tradeoff 4 now states this. |
| 8 | Accepted | A Playwright fixture test opens `/alerts/suricata/<encoded "A/B & C 50%">` and checks the request and the heading. If `[name]` can't carry a "/", the route becomes `[...name]`. |

**Live check before this round:** list-shaped and aggregation searches on the G11 return `timed_out: false` and 0 failed of 7 shards. "Misc activity" over 30 days (521,433 alerts) takes about 0.1 s, so the list's new incomplete-result check won't trip on the G11 today.

## Round 3 - Codex

No remaining material blockers. The revision addresses the prior count/filter issues, and Section D is accurately identified as outside this slice.

Two nonblocking corrections remain:

1. **Low — All 400 responses are labelled as invalid category names.**
   - **Evidence:** B6 specifies that wording, but A3 also returns 400 for invalid or excessive time windows; `daemon/api/time_range.py:17–48` validates timestamps.
   - **Impact:** A valid category with a rejected window gets misleading recovery guidance.
   - **Fix:** Distinguish name-validation errors from window-validation errors, using an error code or the daemon’s message. Test both.

2. **Low — The risk section retains the obsolete 504 statement.**
   - **Evidence:** “Cost on the largest category” says `TooSlow` returns 504, contradicting A3, the verification plan, and `daemon/api/drilldown_runner.py:218–220`, which returns 503.
   - **Impact:** The plan contains conflicting timeout expectations.
   - **Fix:** Change that remaining 504 reference to 503.

VERDICT: APPROVED
### Claude response

Both low findings applied: a 400 shows the daemon message (name vs window), with a test for each; the last 504 reference now says 503. Approved after 3 rounds.
