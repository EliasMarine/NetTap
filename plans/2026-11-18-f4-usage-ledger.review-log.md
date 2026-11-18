# Plan Review Log: F4 durable usage ledger (NET-329)
Started 2026-11-18. MAX_ROUNDS=5. Plan: /Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/plans/2026-11-18-f4-usage-ledger.md

## Round 1 - Codex

The plan needs revision. These are material correctness and operational issues.

1. **High — A rules change can erase settled, pruned history.**

   **Evidence:** Plan §4.3 exempts settled days from pruning evidence, then allows a different-rules recount to replace any day with `complete: true`.

   **Impact:** A settled 100 GB day remains complete after its raw indices disappear. Adding an excluded IP or changing LAN detection then replaces that durable total with a zero or partial recount.

   **Fix:** Track raw-data availability separately from settlement and displayed completeness. Record deletions even for settled days; permit replacement under new rules only when the original raw coverage remains available. Add a settle → prune → rules-change test.

2. **High — Independent direction maxima manufacture bytes.**

   **Evidence:** Plan §4.3 takes separate upload/download maxima. Gateway classification depends on records within the query window, not just the rules hash: [device_accounting.py:198](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/services/device_accounting.py:198>) and [split_direction:430](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/services/device_accounting.py:430>). Recent and nightly passes use different windows.

   **Impact:** I reproduced this using the existing `split_direction`: identical IPv6 traffic yields `(upload=100, download=10)` without gateway evidence and `(10,100)` with it. The proposed merge stores `(100,100)`—200 bytes from 110 bytes of traffic. This can happen without pruning or a rules change.

   **Fix:** Preserve a high-water mark for the Internet total and retain a coherent breakdown from one recount, rather than independently maximizing its components. Require tests with identical records under three-day and seven-day windows and with late gateway evidence.

3. **High — The locking contract does not prevent stale jobs from committing into a replacement ledger.**

   **Evidence:** Plan §4.3 specifies a lock around read-modify-write but no generation check. F1 prevents overlap by job name, so `usage-recent` and `usage-nightly` can run together: [scheduled_jobs.py:133](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/services/scheduled_jobs.py:133>).

   **Impact:** A pass starts a UTC query; a timezone PUT creates a Los Angeles ledger; the old pass subsequently merges UTC totals under Los Angeles date keys. Old-rules results can similarly overwrite newer-rules results. Holding the same lock during searches instead makes API snapshot reads wait on OpenSearch.

   **Fix:** Specify short state-lock sections and generation-checked commits using an immutable `{generation, tz, rules, filters}` snapshot. Serialize recount work separately without holding the API snapshot lock during queries. Add barrier-based tests for both jobs, timezone changes, and API reads during a blocked search.

4. **High — Pruning between inventory and recount can permanently certify incomplete history.**

   **Evidence:** Plan §4.4 updates inventory before querying; §4.3 immediately marks new entries complete and allows historical entries to settle after 72 hours.

   **Impact:** During first catch-up, an index can disappear after inventory collection but before its chunk. The wildcard query succeeds with a reduced or zero total. The day becomes complete and settled; the next pass ignores the disappearance because it is settled.

   **Fix:** Validate source-index identities around each chunk and allow initial completeness or settlement only when coverage remained verified throughout the recount. Add a test deleting an index between inventory collection and the first historical query.

5. **High — Names-only inventory misses deletion followed by recreation.**

   **Evidence:** Plan §4.3 stores index names and timestamp bounds only. The repository explicitly documents Logstash recreating deleted indices: [manager.py:610](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/storage/manager.py:610>).

   **Impact:** An index deleted and recreated between passes has the same name in both inventories. If late records offset deleted bytes, neither disappearance detection nor falling-total detection identifies the loss.

   **Fix:** Store index UUIDs and treat a changed UUID as deletion of the previous index’s coverage. Test same-name replacement where the recount increases.

6. **High — Partial nightly passes can repeatedly process the same prefix.**

   **Evidence:** Plan §4.4 says the next night “starts from the oldest day again” while also claiming unfinished days come first. The persisted schema contains no continuation cursor.

   **Impact:** If the deadline consistently permits only the first 60 days, later historical days never get counted. The recent job covers only the final three days.

   **Fix:** Persist a generation-scoped continuation cursor and resume unfinished work before restarting the sweep. Test repeated deadline exits across a restart and verify eventual coverage of every eligible day.

7. **High — The stated deadline does not bound all OpenSearch work.**

   **Evidence:** Plan §4.2 supplies `request_timeout` only for the main search. Gateway discovery calls `msearch` without a deadline: [device_accounting.py:238](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/services/device_accounting.py:238>). Inventory calls have no specified budget. The shared client retries connection failures and certain HTTP errors: [manager.py:303](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/storage/manager.py:303>). F1 deliberately retains a worker until it actually returns.

   **Impact:** The claim that the deadline “caps it at 600 s” is unsupported. Auxiliary queries and retries can occupy both workers beyond their deadlines; a client timeout alone also does not specify a server-side query limit.

   **Fix:** Thread one absolute deadline through every inventory, aggregation, gateway, and retry path, using a dedicated no-retry client plus remaining-budget request and query timeouts. Test auxiliary-call overruns, not only stopping between fake chunks.

8. **High — Timezone reset lacks safe recovery and reliable rebuild scheduling.**

   **Evidence:** Plan §4.1 falls back to UTC when the timezone file is unreadable; §4.3 resets the ledger when its timezone changes. Separately, F1 drops a request made while that job is running: [scheduled_jobs.py:121](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/services/scheduled_jobs.py:121>).

   **Impact:** A corrupt setting can be mistaken for an intentional UTC reset. A legitimate timezone change during nightly catch-up cannot rely on “request at once”: the rebuild request returns `running` without queuing another run. Once stale results are rejected, history may remain missing until the next night.

   **Fix:** Define a durable timezone-transition record initiated only by explicit PUT, with a pending rebuild generation that survives active jobs and restarts. An existing ledger’s timezone must remain authoritative on settings-read failure. Test corruption and crashes between transition steps.

9. **Medium — Failure handling assumes the wrong client behavior and F1 result contract.**

   **Evidence:** Plan §2 claims the current monthly search silently accepts partial replies. In production, the tracker receives `storage._client` ([server.py:1411](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/api/server.py:1411>)), an `ExactTermsOpenSearch` client that already raises `PartialResultsError`/`SearchTimedOut` ([exact_terms.py:124](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/storage/exact_terms.py:124>)). These are not `QueryFailed`. Also, F1 records `last_error` only from raised exceptions, not caught chunk failures: [scheduled_jobs.py:186](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/services/scheduled_jobs.py:186>).

   **Impact:** Actual partial-search failures can bypass the promised per-day handling. Conversely, caught failures can leave F1 reporting a successful run.

   **Fix:** Define one explicit failure adapter covering the actual client exceptions, then report the accumulated failure through a supported F1 outcome after saving successful chunks. Test using the real client wrapper’s exception types.

10. **Medium — The API hides stale totals and mislabels pending work as pruning.**

    **Evidence:** Plan §4.3 stores `recounted_at` and `last_error`, but §4.5 exposes neither. Failed recounts preserve previously complete entries. Section 4.6 describes every incomplete month as raw data cleared early.

    **Impact:** Today’s morning total can remain `complete: true` after hours of failures, while successful page refreshes imply current data. First-run catch-up, timezone rebuilds, and the interval after midnight can instead falsely claim pruning.

    **Fix:** Add freshness and processing status alongside historical coverage: last successful recount time, pending work, and failed/stale status. Test a successful recount followed by repeated failures, initial catch-up, and midnight before the next pass.

11. **Medium — The Bandwidth switch-over leaves contradictory figures on the same card.**

    **Evidence:** Plan §4.6 changes the KPI but retains the old projection response. That response also supplies its cap percentage and meter: [bandwidth/+page.svelte:435](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/web/src/routes/bandwidth/+page.svelte:435>). Requests still select the UTC month at [line 362](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/web/src/routes/bandwidth/+page.svelte:362>).

    **Impact:** On November 30 at 17:00 Los Angeles time, the ledger counts November while the legacy requests select December. After pruning, the projection can also be lower than usage already preserved in the ledger.

    **Fix:** Move the entire current-usage card—including direction totals, cap percentage, and meter—to the ledger snapshot. Suppress legacy projections when their period or coverage differs, and identify the period of remaining raw-data cards. Add month-rollover and ledger-greater-than-raw tests.

12. **Medium — The deployment gate measures the wrong process for the main resource risk.**

    **Evidence:** Plan §8 measures daemon RSS/HWM, while the aggregation work runs in OpenSearch. Nested terms are additionally expanded to at least 10,000 candidates per shard by [exact_terms.py:29](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/storage/exact_terms.py:29>). The approved roadmap explicitly requires host memory, container memory, and swap checks ([roadmap:75](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/plans/2026-11-18-feature-roadmap.md:75>)).

    **Impact:** The deployment can pass its daemon-memory check while OpenSearch increases memory pressure, swap activity, and API latency on the constrained N100.

    **Fix:** Extend the acceptance gate to sample host swap and OpenSearch memory during catch-up and overlapping scheduled/API activity, with the roadmap’s stop thresholds. Base chunk size and recount concurrency on those measurements.

VERDICT: REVISE

### Claude response (round 1)

All 12 findings taken; the plan was restructured around one ledger job as the only writer. The table in plan section 10 maps each finding to its change. Rejected: none. New tradeoff: a single 15-minute job means a full sweep after a transition spreads over several runs (bounded by the 240 s deadline), instead of one long nightly pass.

## Round 2 - Codex

I read the latest Claude response and §10. The findings below are unresolved parts of the revision or new risks introduced by it.

1. **High — Missing-inventory recovery still permits destructive rules recounts.**

   **Evidence:** Plan §4.3, line 122 marks only *unsettled* days when inventory is missing. Line 114 allows replacement whenever `pruned_seen_at` is absent.

   **Impact:** Settle a day → lose its inventory → prune its raw data → change exclusions. The preserved total can still be replaced with zero. Section 10’s claim that pruning evidence is “always recorded” is therefore incomplete.

   **Fix:** Treat inventory loss as unknown raw coverage for **all existing days**, including settled days. Block destructive rules replacement until coverage is positively verified. Add this exact recovery sequence as a regression test.

2. **High — The timestamp-based completeness rule can erase earlier evidence of loss.**

   **Evidence:** Plan §4.3, lines 111/119 assign `pruned_seen_at`; line 124 allows settlement after a stable recount even when earlier pruning occurred. Line 126 determines completeness by comparing those timestamps.

   **Impact:** Pruning at T1 makes a day approximate. A stable recount establishes settlement at T2. Another deletion during a query records pruning at T3 and skips settlement. Now `T2 < T3`, so the formula calls the day complete despite the original T1 loss. Neither timestamp is explicitly defined as immutable.

   **Fix:** Make first-loss evidence immutable and establish settlement only when no earlier coverage loss or uncertainty exists. Test prune → stable recount after 72 hours → second prune; completeness must remain false.

3. **High — Normal passes publish state before making it durable.**

   **Evidence:** Plan §4.4 specifies “merge, swap, save” for recent work and advances/publishes the sweep cursor before saving. The timezone transition correctly uses the opposite order.

   **Impact:** A disk-full or write failure leaves the API serving newly counted totals and progress that never reached disk. Restarting reloads lower totals; intervening pruning can prevent recovery. Those published days still appear successfully counted.

   **Fix:** Build the candidate snapshot, atomically save it, then publish its reference. A failed save must leave the previous published totals and cursor intact. Add an injected write-failure test covering API reads and restart.

4. **High — The deadline fix misses retries inside `ExactTermsOpenSearch`.**

   **Evidence:** Plan §4.2 supplies request timeouts but no `budget=`. Disabling transport retries does not disable the wrapper’s larger-terms retry: [exact_terms.py:229](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/storage/exact_terms.py:229>). The repository already tests this distinction at [test_exact_terms.py:322](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/tests/test_exact_terms.py:322>). Inventory calls still lack an explicit budget contract, and gateway searches rely on a default request timeout without a query timeout.

   **Impact:** A second physical search can start after the deadline, reuse the original timeout, and request ten times as many terms. Post-query inventory adds further work. The claimed maximum overrun remains unsupported.

   **Fix:** Propagate one absolute budget through the wrapper, gateway searches, and inventory calls, refreshing request and query timeouts for each physical send. Test a truncated first response that exhausts the budget and verify no second search occurs.

5. **High — Bootstrap coverage is inferred from presence, not continuity.**

   **Evidence:** Plan §4.3, line 128 derives `since` from the oldest surviving `min_ts`. New successful recounts become counted, and the first-run tests cover only dates before `since`.

   **Impact:** Surviving records on November 1 and November 3 do not establish coverage for November 2 if its index disappeared before installation. There is no rule identifying that interior gap: it can become a complete zero if enumerated for recount, or remain misleadingly pending if omitted. An old surviving connection timestamp can similarly overstate how far continuous coverage extends.

   **Fix:** Define bootstrap coverage independently of the earliest record. Record missing or unverifiable intervals as permanent coverage gaps, including gaps after `since`. Add sparse-history and completely empty-store tests.

6. **Medium — Preserved totals under obsolete rules still qualify as complete.**

   **Evidence:** Plan §4.3, lines 114–115 retains a pruned day’s old figures and rules. Completeness at line 126 considers only settlement and pruning, and §4.5 exposes no rules-mismatch state.

   **Impact:** A settled, subsequently pruned day can retain traffic from a newly excluded IP while remaining `counted` and projection-eligible. The month silently combines incompatible accounting rules. Unpruned days awaiting their rules-change recount have the same visibility problem.

   **Fix:** Track validity under the currently requested rules separately from raw coverage. Preserve unrecountable totals, but expose their rules mismatch and suppress projections for mixed-rule months. Test the API after settle → prune → exclusion change.

7. **Medium — Future dates make a caught-up month say “Still counting.”**

   **Evidence:** Plan §4.5 returns the whole month, labels uncounted dates on or after `since` as `pending`, and includes every non-counted date in gaps. Section 4.6 displays “Still counting” when **any** day is pending. Only aggregate completeness explicitly excludes future days.

   **Impact:** On November 18, November 19–30 become pending gaps. The response can simultaneously be `complete: true` and make the page say counting is unfinished.

   **Fix:** Exclude future dates from coverage gaps and pending UI decisions, or give them a distinct future state. Add a fully caught-up, mid-month API/page test.

8. **Medium — The new projection has no defined accounting cutoff.**

   **Evidence:** Plan §4.5 introduces `total / days_elapsed × days_in_month` without defining the timestamp used for elapsed time. Totals update periodically; `updated_at` describes a successful pass, potentially after its historical sweep.

   **Impact:** A first-day total counted at 00:01 and read at 00:14 can produce a fourteenfold lower rate if elapsed time uses response time. Sweep completion is also later than the recent query. The projection therefore need not represent the same snapshot as its numerator.

   **Fix:** Record an explicit current-day query cutoff and calculate projection elapsed time from that cutoff and owner-local month boundaries. Test first-day reads between passes, zero elapsed time, and DST months.

9. **Medium — The remaining-card plan relies on a nonexistent range-picker flow.**

   **Evidence:** Plan §4.6, line 193 says the other cards already use a time-range picker and label its range. Their actual requests hardcode `utcMonthWindow(now)` at [bandwidth/+page.svelte:362](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/web/src/routes/bandwidth/+page.svelte:362>). Device-card subtitles still say only “this month” at [line 513](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/web/src/routes/bandwidth/+page.svelte:513>).

   **Impact:** The owner-local ledger card and neighboring device cards can still show different calendar months while both claim “this month.” The revision leaves the necessary implementation work unplanned.

   **Fix:** Explicitly retain and label the raw cards with their named UTC month, or pass owner-month boundaries to their requests. Include those cards in the non-UTC rollover test.

10. **Medium — Forcing the job does not guarantee the deployment test exercises a sweep.**

    **Evidence:** Plan §4.4 starts a sweep only when due, unfinished, or transitioning. Section 8 forces the job through `/api/jobs/usage-ledger/run`; that endpoint requests execution, not a fresh sweep. Startup execution can also occur during the settling/baseline wait.

    **Impact:** If a sweep finished recently, the forced run performs only recent-day work and exits with `cursor: null`. The resource gate can pass without measuring the historical workload it claims to validate.

    **Fix:** Provide an explicit way to request a new sweep without resetting totals, and require the deployment check to observe a new sweep identifier and completed historical chunk count. A null cursor alone must not constitute proof.

VERDICT: REVISE

### Claude response (round 2)

All 10 findings taken; plan section 11 maps each to its change. Rejected: none. New tradeoffs: two shared functions gain an optional budget parameter (ExactTermsOpenSearch.msearch and gateways_if_needed, default None = unchanged for every existing caller); the Bandwidth page daily chart now reads ledger days rather than raw UTC buckets; a new POST /api/usage/recount endpoint exists for the deploy check and a future UI button.

## Round 3 - Codex

I read the latest Claude response and §11. Five material gaps remain.

1. **High — Bootstrap can permanently exclude today’s usage.**

   **Evidence:** Plan §4.3, lines 137–141 require every UTC date overlapping a local day to have an index, then permanently mark uncovered days through today as gaps. API lines 185/191 exclude those days’ figures.

   **Impact:** At noon on November 18 in Los Angeles, today spans November 18 08:00Z–November 19 08:00Z. The November 19 index does not exist yet. Bootstrap—or a timezone change—therefore permanently marks today `not_counted`. Subsequent recounts cannot repair this because the gap takes precedence.

   **Fix:** Evaluate the open day’s coverage only through its recount cutoff. Future portions of a local day must never create permanent gaps. Test bootstrap and timezone transition at Los Angeles noon, continuing through UTC midnight and local day-end.

2. **Medium — Ordinary index creation now becomes irreversible loss evidence.**

   **Evidence:** Plan §4.3, line 127 marks changed indices whenever the before/after listings differ. Line 125 makes that evidence permanent. This includes additions, unlike the earlier deletion/replacement rule.

   **Impact:** A normal daily index appearing during a recount can permanently mark intact coverage as approximate, prevent settlement, and block subsequent rules-based replacement. The first index appearing on an empty installation has the same problem.

   **Fix:** Classify inventory changes explicitly: missing UUIDs and same-name UUID replacements indicate loss; additions may require another recount or deferred settlement but must not set `coverage_lost_at`. Test additions separately from deletion/recreation.

3. **Medium — Recountable days under old rules still fall through to `counted`.**

   **Evidence:** Plan §4.3, line 134 requires current rules for completeness. However, §4.5 defines `pending` only for never-counted days and `old_rules` only for days that **cannot** be recounted. API completeness then depends on those statuses.

   **Impact:** After exclusions change, an already-counted, unpruned historical day awaiting its sweep matches neither condition. It becomes `counted`, allowing a mixed-rule month to remain projection-eligible. This is the unresolved portion of round-two finding 6.

   **Fix:** Make every rules mismatch non-complete: use `recount_pending` when raw coverage remains and `old_rules` otherwise, or use `old_rules` for both. Test the API immediately after an exclusion change, before historical recounts finish.

4. **Medium — Budget exhaustion inside a chunk can skip unfinished work and inflate completion counters.**

   **Evidence:** Plan §4.4, line 165 preserves the cursor for `TooSlow` from the pre-chunk check. But `TooSlow` can also arise inside a search, gateway lookup, or post-query inventory read. It belongs to the general failure adapter, while line 166 advances the cursor and increments `chunks_done`. The deployment gate accepts that count without requiring successful chunks.

   **Impact:** A chunk interrupted by the budget can be skipped until the next daily sweep instead of resumed next run. Failed attempts can also satisfy the deployment gate’s supposed proof of completed historical work.

   **Fix:** Treat budget exhaustion anywhere in a chunk as continuation: retain its cursor and do not increment completed work. Track failed attempts separately and require no failed or unfinished chunks for deployment acceptance. Test expiry inside the search and post-query inventory paths.

5. **Medium — The chart migration omits its existing interval-selection contract.**

   **Evidence:** The new daily response supplies dates but no explicit bucket boundaries or cutoff. Existing click/drag navigation uses a single fixed bucket duration in [drilldown.ts:323](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/web/src/lib/utils/drilldown.ts:323>) and is wired at [bandwidth/+page.svelte:498](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/web/src/routes/bandwidth/+page.svelte:498>).

   **Impact:** Simply replacing the response disables the existing drilldown metadata. Retaining a fixed 24-hour duration opens incorrect intervals for 23/25-hour local days and today’s partial bucket.

   **Fix:** Include each day’s UTC start, exclusive end, and counted cutoff in the API, and adapt chart selections to those variable boundaries. Add DST-day and partial-today click/drag tests.

VERDICT: REVISE

### Claude response (round 3)

All 5 findings taken; plan section 12 maps each to its change. Rejected: none. New tradeoff: a chunk that fails with a non-budget error advances the cursor (its days show stale) so one bad chunk cannot stall the sweep; the deploy gate requires chunks_failed == 0, and the next sweep retries those days.

## Round 4 - Codex

Two round-three fixes remain incomplete.

1. **High — Exempting today entirely hides genuine elapsed-data loss.**

   **Evidence:** Plan §4.3, lines 140–145 checks bootstrap coverage only for past days and declares today never a gap. Emergency pruning can delete every index before the current UTC date: [manager.py:615](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/storage/manager.py:615>).

   **Impact:** Bootstrap or change timezone at **November 18, 18:00 Los Angeles time**—November 19, 02:00Z—after pruning leaves only November 19’s UTC index. Today’s first **16 local hours** are missing, but the ledger counts the surviving two hours as complete. Its new inventory cannot detect the earlier deletion.

   **Fix:** Check today’s coverage over `[local_day_start, recount_cutoff)`. Ignore missing future UTC dates, but mark missing **elapsed** coverage as immutable loss and show today as approximate while continuing to count available bytes. Define `since = today` when no historical local day is covered. Test this evening case alongside the existing noon case.

2. **Medium — Budget continuation still misses actual in-flight timeout exceptions.**

   **Evidence:** Plan §4.4 preserves the cursor for `TooSlow`, but advances it for other errors. The wrapper propagates transport exceptions directly at [exact_terms.py:244](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/storage/exact_terms.py:244>); server timeouts raise `SearchTimedOut` at [line 131](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f4/daemon/storage/exact_terms.py:131>). Neither `ConnectionTimeout` nor `SearchTimedOut` is `TooSlow`.

   **Impact:** A request that consumes its remaining budget still follows the failure branch, advances the cursor, and postpones unfinished work until the next daily sweep. Checking only whether the budget has expired is insufficient: with three seconds remaining, the planned one-second server timeout can fire while budget remains.

   **Fix:** Normalize timeouts caused by the remaining-budget limits—including the server-timeout margin—into the continuation outcome before generic failure handling. Test actual `ConnectionTimeout` and `SearchTimedOut` paths, asserting unchanged cursor and counters.

VERDICT: REVISE

### Claude response (round 4)

Both findings taken; plan section 13. For #2 I chose to treat every timeout type as a continuation rather than classify which ones were budget-limited, and added a three-strikes rule so a chunk that always times out is eventually recorded as failed and skipped (no stall). Rejected: none.

## Round 5 - Codex

The latest Claude response and §13 resolve the remaining findings. Elapsed-day coverage and real timeout handling now have explicit rules and regression tests. No further material plan-level issues found.

VERDICT: APPROVED

## Resolution

APPROVED in round 5 of 5. Owner standing rule (default to recommendation, "start implementing!") is the sign-off to implement.
