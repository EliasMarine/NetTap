# Plan Review Log: #6 data cap warnings (NET-339)
Started session start. MAX_ROUNDS=5.

## Round 1 - Codex

1. **High — Incomplete usage is not necessarily a lower bound.**  
   **Evidence:** Plan §3.3 and §4.2 allow absolute thresholds for every incomplete month. [usage_report.py:67](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/daemon/services/usage_report.py:67) retains totals marked `old_rules` or `recount_pending`; these contribute to the monthly sum. [test_usage_ledger.py:551](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/daemon/tests/test_usage_ledger.py:551) demonstrates retained usage exceeding the total under current exclusions.  
   **Impact:** After exclusions change, the watcher can issue a false “at least” overage and consume the monthly warning permanently. This is different from preserving a warning issued before the change.  
   **Fix:** Require explicit ledger evidence that the total remains a valid lower bound under current accounting rules. Test pending recounts, retained old-rule totals, and stale rows whose rules also changed.

2. **High — A successful digest can discard a warning the owner never sees.**  
   **Evidence:** Plan §4.2 relies on existing digest behavior. [notification_dispatcher.py:197](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/daemon/services/notification_dispatcher.py:197) renders only ten items, but successful delivery clears the entire event queue at line 701.  
   **Impact:** Ten competing alerts can push the cap warning into “and N more.” The warning is then removed, and journal deduplication prevents another attempt that month.  
   **Fix:** Retain cap events omitted from the delivered message until a later message includes them. Add a dispatcher test with at least ten competing alerts.

3. **Medium — Cap persistence can activate a failed save and destroy the previous setting.**  
   **Evidence:** Plan §4.5 reuses `save_cap` unchanged. [bandwidth_tracker.py:145](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/daemon/services/bandwidth_tracker.py:145) changes the live value before directly truncating and rewriting the file. An unreadable file subsequently loads as cap zero.  
   **Impact:** A failed Save can trigger warnings for the rejected value. A partial write can also lose the previous cap and disable warnings after restart.  
   **Fix:** Persist atomically before publishing the live value, with serialized saves and controlled error handling. Test that write failure preserves both the live and persisted cap.

4. **Medium — Journal retention does not guarantee monthly deduplication.**  
   **Evidence:** Plan §2 describes 120-day retention, but [event_journal.py:186](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/daemon/services/event_journal.py:186) also limits retained history to 50,000 entries and rebuilds `_ids` from that history.  
   **Impact:** Sufficient journal traffic can evict an already-consumed cap event during its own month. The next watcher run appends it again.  
   **Fix:** Protect current-month cap deduplication records from the journal’s line limit, or maintain a separate durable monthly index. Test compaction using a small `max_lines`.

5. **Medium — Crossings first accounted after midnight are never evaluated.**  
   **Evidence:** Plan §4.2 reads only the current month. [usage.py:74](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/daemon/api/usage.py:74) selects that month from the clock, while [usage_ledger.py:422](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/daemon/services/usage_ledger.py:422) continues recounting previous days. Equal scheduling intervals do not impose execution order.  
   **Impact:** November can rise from 99 GB to 101 GB in a post-midnight recount, while every subsequent watcher run checks December. November’s 100% warning never fires.  
   **Fix:** Add month-close reconciliation for the preceding month using its applicable cap and zone. Test delayed final-day accounting and restart across the boundary.

6. **Medium — Copying the existing quick-setting behavior loses an early opt-out.**  
   **Evidence:** Plan §4.1 follows the new-device pattern. [notification_config.py:334](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/daemon/services/notification_config.py:334) returns without saving a fixed rule when no Settings channel exists; an absent rule is interpreted as enabled.  
   **Impact:** An owner can switch warnings off before configuring channels, then have that preference revert to default-on.  
   **Fix:** Persist an explicit disabled rule with `channels: []`. Test opt-out → restart → channel setup.

7. **Medium — The new Settings card presents incomplete usage as a complete monthly figure.**  
   **Evidence:** Plan §4.5 specifies unconditional “82.4 GB of 100 GB used this month.” The roadmap explicitly requires an incomplete-month caveat. The API already supplies `complete` and `since`, but [bandwidth.ts:89](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/f6/web/src/lib/api/bandwidth.ts:89) omits them from `BandwidthCap`.  
   **Impact:** Mid-month installation understates usage without disclosing the missing period, making remaining allowance appear larger.  
   **Fix:** Extend the client contract and require coverage/status wording in the card, including tests for mid-month startup and an uninitialized ledger.

VERDICT: REVISE

### Claude response (round 1)

All 7 findings taken; plan section 10 maps each to its change. Rejected: none. New tradeoffs: a second small state file (data-cap.json) duplicates the journal dedup on purpose (the journal is bounded); the digest now orders data_cap first, a small change to F1 dispatcher behaviour; the opt-out fix also changes F1 new-device rule persistence when no channel exists.

## Round 2 - Codex

The latest Claude response and §10 mark all seven findings addressed, but these revisions remain inadequate:

1. **High — Putting cap warnings first does not guarantee delivery.**  
   **Evidence:** Plan §4.3 assumes at most five queued cap warnings. That bounds one instance, not a retry queue: cap changes create additional instances, and events retry indefinitely. [notification_dispatcher.py:197](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/services/notification_dispatcher.py:197>) renders ten items; successful delivery still clears everything.  
   **Impact:** Six cap revisions during an outage can accumulate twelve warnings, losing those beyond the tenth. Cap-first ordering also pushes critical alerts behind medium warnings. Exempting cap events from `MAX_EVENTS` makes their queue unbounded.  
   **Fix:** Replace ordering-only protection with bounded delivery batches that acknowledge only items actually included in the transmitted payload. Preserve severity ordering and defer remaining items durably. Test more than ten cap events, a critical alert, and channel character limits.

2. **Medium — The new deduplication file loses records that remain eligible for evaluation.**  
   **Evidence:** Plan §3.4 stores the current instance; §4.2 step 5 replaces it when the instance changes. Step 6 also alternates between current and previous months.  
   **Impact:** Cap A → cap B → cap A loses A’s auxiliary record. After journal compaction, A sends again. The single-instance schema also conflicts with retaining both reconciliation months. Separately, an append followed by a failed state write remains vulnerable if compaction removes the journal entry before recovery.  
   **Fix:** Define a durable map covering every still-eligible instance, and protect journal entries from compaction until their corresponding map entries are durable. Test A → B → A after compaction, repeated two-month reconciliation, and append-success/state-write-failure recovery.

3. **Medium — Reconciliation applies December’s cap to November.**  
   **Evidence:** Plan §3.5 explicitly uses the **current cap and ledger zone**, rather than the closing month’s applicable configuration. This does not implement round-one finding 5’s requested fix.  
   **Impact:** November usage of 900 GB under a 1,000 GB cap becomes a false November “cap reached” warning when the owner selects 500 GB on December 1. Raising December’s cap can suppress a genuine November overage.  
   **Fix:** Persist and use the closing month’s applicable cap and accounting zone. Skip historical reconciliation when that context is unavailable. Test cap increases, decreases, and zone changes at rollover.

4. **Medium — Reconciliation stops before the ledger’s settlement window completes.**  
   **Evidence:** Plan §3.5 stops after December 3. [usage_days.py:291](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/services/usage_days.py:291>) requires a successful recount at least 72 hours **after the day ends** before settlement—December 4 for November 30. Older days continue receiving sweep updates.  
   **Impact:** A supported late record first incorporated by the December 4 sweep can cross November’s threshold after the watcher has stopped checking November.  
   **Fix:** Close reconciliation only after evaluating a successful ledger update covering the final days’ settlement window, with an explicit bounded outage policy. Test a crossing first published on December 4.

5. **Medium — Projection and lower-bound calculations can use different accounting states.**  
   **Evidence:** Plan §4.2 separately calls `month_reply(ledger)` and `lower_bound(snapshot, …, current_rules)`. [usage.py:74](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/api/usage.py:74>) captures its own snapshot, clock, and rules internally.  
   **Impact:** The first call can produce a complete 180 GB projection under old exclusions; exclusions then change and the second calculation returns a zero lower bound. The producer combines those results and emits an obsolete projection warning, consuming its monthly key.  
   **Fix:** Compute both figures from one captured snapshot/clock/rules context, preferably inside `usage_report.month`. Add a deterministic test that changes accounting rules between the currently separate reads.

6. **Medium — The revised card labels an unsafe total “at least.”**  
   **Evidence:** Plan §4.5 still displays `/api/bandwidth/cap.current_usage_bytes`, now with “at least” whenever incomplete. [bandwidth.py:338](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/api/bandwidth.py:338>) returns the unfiltered monthly total, including old-rule figures. The new safe lower bound is only specified for the producer.  
   **Impact:** After exclusions change, the card can claim “at least 120 GB” while the valid current-rule bound is 20 GB. The caveat is false, and the card disagrees with warnings.  
   **Fix:** Expose the safe lower bound through the cap API and use it for “at least” wording; distinguish earlier-rule/recounting totals explicitly. Test changed exclusions, not only mid-month startup.

VERDICT: REVISE

### Claude response (round 2)

All 6 findings taken; plan section 11 maps each to its change. On #1 I chose ack-only-rendered for journal events plus per-month coalescing over a general batch protocol: it is the smaller change, bounds the cap items at 2 per channel, and keeps the existing worst-first ordering for everything else; the at-most-2 short cap lines go first so no service clip can cut them, which keeps a critical alert within the first 3 lines. Rejected: none.

## Round 3 - Codex

Six material gaps remain in the revised changes:

1. **Medium — Coalescing overwrites distinct warnings before delivery.**  
   **Evidence:** Plan §4.2 appends `80` before `projected`; §4.3 replaces any queued cap item for the same month with the newest item. Both thresholds are recorded as sent.  
   **Impact:** At 85 GB used against a 100 GB cap, with 150 GB projected, the forecast immediately replaces the 80% warning. The owner never receives the actual usage-threshold warning, and deduplication prevents another attempt.  
   **Fix:** Coalesce into a summary that merges crossed-threshold facts and event IDs, preserving the highest actual usage threshold alongside any forecast. Test `80 + projected` and `80 + 100` admitted together.

2. **Medium — Per-month coalescing does not establish the two-item queue bound.**  
   **Evidence:** Plan §4.3 asserts at most two cap items but specifies replacement only within the same month. Existing events retry indefinitely at [notification_dispatcher.py:717](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/services/notification_dispatcher.py:717>). No retirement policy for older queued months is defined.  
   **Impact:** An unavailable channel can retain January, February, and March warnings simultaneously. This invalidates the `MAX_EVENTS + 2`, character-limit, and critical-alert-position guarantees. Producer-state pruning does not remove dispatcher items.  
   **Fix:** Define an explicit queue-retention policy for older months—such as observable expiry outside the supported delivery window—and enforce it across restarts. Test an outage spanning at least three months.

3. **Medium — Failed state persistence does not have a bounded 15-minute recovery window.**  
   **Evidence:** Plan §4.2 steps 5–7 assume the next run repairs state through a duplicate append. However, step 1 returns when the cap is zero, and append attempts occur only for currently eligible thresholds.  
   **Impact:** After append succeeds and state persistence fails, disabling the cap can postpone repair for days. Ordinary journal traffic can then compact the entry; re-enabling the cap sends it again. Changed exclusions can similarly make the threshold temporarily ineligible. This does not require 50,000 events within 15 minutes.  
   **Fix:** Recover pending deduplication state before eligibility checks, with journal entries protected until that state is durable. Test append-success → state-write-failure → cap disabled → compaction → cap restored.

4. **Medium — The closing month’s applicable cap is still not reliably captured.**  
   **Evidence:** Plan §3.4 records the latest configuration observed by the 15-minute watcher; §4.2 explicitly writes state only after an append.  
   **Impact:** A month with no warning before midnight may have no reconciliation record. Even saving metadata every run misses a cap change after the final monthly run: a 100 GB cap observed at 23:45, raised to 1,000 GB at 23:59, can still produce a false November overage when late accounting reaches 101 GB after midnight.  
   **Fix:** Persist cap changes with their effective time/month in the atomic configuration-save path, and maintain month context independently of warning emission. Test both a last-minute cap change and a first threshold crossing discovered after rollover.

5. **Medium — Saving an old zone does not provide usage accounted in that zone.**  
   **Evidence:** Plan §3.5 promises reconciliation using the recorded zone. But [usage.py:70](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/api/usage.py:70>) accepts only year/month and reads the current ledger. [usage_ledger.py:391](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/services/usage_ledger.py:391>) replaces the published ledger on a zone transition; the archived generation receives no subsequent recounts.  
   **Impact:** After a rollover zone change, current-ledger totals use different month boundaries. Relabeling them with November’s saved zone is incorrect; reading the frozen archive misses late accounting.  
   **Fix:** Adopt the simpler explicit policy of skipping reconciliation when the recorded zone differs from the available ledger zone, with a recorded reason. Test the real ledger transition rather than only mocked month replies.

6. **Medium — The deployment smoke test now consumes real warning eligibility.**  
   **Evidence:** Plan §3.4 suppresses a threshold previously emitted at an equal or higher cap. §8 still injects a synthetic cap, restores only the configured cap, and calls the remaining records harmless.  
   **Impact:** With 500 GB usage and no cap, testing at 499 GB records both thresholds at 499 GB. After restoring zero, an owner setting a real 100 GB cap receives neither warning because `499 ≥ 100`. Cap-specific journal IDs no longer isolate the test.  
   **Fix:** Exercise synthetic crossings against isolated temporary journal/state files; check the production scheduler using the actual cap. Verify the smoke test leaves future real crossings eligible.

VERDICT: REVISE

### Claude response (round 3)

All 6 findings taken by simplifying rather than patching. (a) The data-cap.json state file is removed: the journal append is the single record of sent, with instance "<month>|<cap bytes>", and compaction keeps data_cap lines for 62 days past the line cap (one predicate). (b) Previous-month reconciliation (my round-1 #5 fix) is withdrawn and replaced with a stated limit: a crossing first accounted after the month ends is not warned about; a warning then cannot change anything the owner does, and the final figure is on the Bandwidth page. This removes r2 #3, r2 #4, r3 #4 and r3 #5 at the root. (c) No coalescing: items stay distinct; retention drops past-month items and other-cap items for the same month, bounding data_cap items at 3 per channel. (d) Delivery fits each channel clip and acknowledges only rendered events, with order unchanged. (e) The smoke test uses an odd cap value as its own instance. Rejected: none of the round-3 findings; round-1 #5 is withdrawn with the reason above.

## Round 4 - Codex

Four material gaps remain. The removed state file and explicit month-end limit resolve the corresponding earlier findings.

1. **Medium — Cap changes can deliver obsolete warnings or lose undelivered ones.**  
   **Evidence:** Plan §4.3 removes old-cap items only when another cap’s event is admitted. §3.2 suppresses previously journaled events when returning to an earlier cap.  
   **Impact:** Raising the cap above all thresholds—or disabling it—creates no replacement event, so an old warning can still send. During an outage, A → B → A can instead delete A’s pending warnings permanently: journal deduplication prevents their reconstruction.  
   **Fix:** Make delivery select the currently configured cap, including zero, while durably suspending undelivered superseded items so they can resume if that cap returns. Test both cap changes without new crossings and A → B → A during an outage.

2. **Medium — Telegram can still clip an acknowledged event.**  
   **Evidence:** Plan §4.3 allows a 4,096-character Telegram body. [notification_hub.py:807](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/services/notification_hub.py:807>) applies that limit to `"[SEVERITY] {title}\n\n{message}"`, including additional text outside the body.  
   **Impact:** A body accepted by the fitter can lose the end of its final event during transport formatting, while the dispatcher acknowledges that event as shown.  
   **Fix:** Fit the complete Telegram payload, reserving space for the title, severity prefix and separators. Test the actual outbound payload with a journal event near the limit.

3. **Medium — An individually oversized event has no delivery-progress policy.**  
   **Evidence:** Plan §4.3 defers events that do not fit, but only bounds `data_cap` lines. Existing new-device lines interpolate an unbounded vendor value at [notification_dispatcher.py:223](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/services/notification_dispatcher.py:223>).  
   **Impact:** An event larger than an otherwise empty message’s usable budget can remain queued indefinitely. A fitter that stops at the first non-fitting item can also block subsequent cap warnings.  
   **Fix:** Define a bounded single-event summary for oversized items, preserving their identifier and essential facts. Test an oversized new-device event followed by a cap warning.

4. **Medium — The deployment check assumes unavailable fields and sufficient usage.**  
   **Evidence:** Plan §8 requests `lower_bound_bytes` before upgrading, but the baseline [bandwidth.py:338](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f6/daemon/api/bandwidth.py:338>) does not expose it. The synthetic check then unconditionally expects both crossings at 1.234567 GB without checking the actual lower bound.  
   **Impact:** A first upgrade cannot provide the requested baseline field. A healthy new or early-month ledger can also correctly emit neither warning, causing the smoke check to fail.  
   **Fix:** Collect compatible fields before upgrading; fetch the lower bound after health checks and condition the live crossing test on sufficient usage. Otherwise use an isolated fixture, with cap restoration guaranteed on failure.

VERDICT: REVISE

### Claude response (round 4)

All 4 findings taken; plan section 13 maps each to its change. #1: cap filtering moves to send time through one callable, data_cap_now() -> (owner month, cap); other-cap items are held rather than dropped, so A -> B -> A loses nothing and a raised or removed cap silences old ones; bound of 12 per queue. #2: body_limit(channel_type) reserves 300 chars for Telegram framing; real-payload tests. #3: every event line clipped to 300 chars; the fitter skips a misfit and continues. #4: baseline reads only the cap; lower bound read after upgrade; synthetic crossing skipped under 2 GB; trap restores the cap. Rejected: none. New tradeoff: the dispatcher now depends on a data_cap_now callable (one parameter, stubbed in tests).

## Round 5 - Codex

The revised plan addresses the four outstanding findings. No remaining material blockers found, given the explicit month-end and queue-retention limits.

VERDICT: APPROVED

## Result

APPROVED in round 5 of 5. 23 findings across rounds 1-4 (7 + 6 + 6 + 4), all taken; round 3 simplified the design (no state file, no previous-month reconciliation, stated month-end limit). Owner standing rule: take the recommendation and keep going.
