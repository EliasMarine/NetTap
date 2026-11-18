# Plan Review Log: Feature roadmap, the 20 missing features (2026-11-18)

Started 2026-11-18. MAX_ROUNDS=5. Reviewer: Codex CLI 0.167.1, read-only sandbox, work dir = the `docs/feature-roadmap-2026-11-18` worktree at origin/main `a7e4d810`. Plan: `plans/2026-11-18-feature-roadmap.md`.

## Round 1 - Codex

Reviewed the on-disk roadmap against commit `a7e4d810`. These are material issues that should change the roadmap before individual slice plans proceed.

1. **High — Account mutations can undo password changes and revocation.**

   **Evidence:** #3 reuses `createUser` and `updatePassword`. Both read the complete user store before awaiting password hashing, then overwrite it: [auth.ts:184](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/web/src/lib/server/auth.ts:184), lines 193–200 and 237–246.

   **Impact:** A concurrent viewer password change can restore an admin’s previous password hash and `tokenVersion`, or resurrect a deleted account. Atomic rename does not prevent lost updates.

   **Fix:** Make serialized, revalidated user-store mutations a prerequisite of #3, with concurrency tests covering password changes, resets, creation and deletion.

2. **High — Rolling back #3 grants viewers administrative access.**

   **Evidence:** §13 omits accounts rollback. The current [hooks.server.ts:159](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/web/src/hooks.server.ts:159) trusts verified JWTs without checking stored users or token versions; lines 272–283 impose no role restrictions.

   **Impact:** Downgrading with viewer accounts or JWTs present permits administrative requests. Previously revoked admin JWTs become usable again. Deleting viewer records alone cannot fix this.

   **Fix:** Require an accounts downgrade procedure that removes/disables viewers and rotates the signing secret before exposing the older build; test old viewer and revoked-admin tokens against that build.

3. **High — Certificate replacement is not crash-safe.**

   **Evidence:** #11A specifies sequential replacement with `.prev` and exception rollback. nginx reads separate certificate and key files: [nginx.conf:147](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/docker/nginx.conf:147).

   **Impact:** Death between replacements can leave a mismatched pair that prevents nginx’s next startup. After two uploads, `.prev` also no longer represents the installer certificate promised by §13.

   **Fix:** Require staged, validated certificate/key generations, atomic activation, an immutable installer fallback and startup recovery. Test process death at every activation boundary.

4. **High — New integration credentials lack authenticated transport.**

   **Evidence:** D15 recommends skipping TLS verification for non-expiring bearer tokens. #20 reuses UniFi requests whose live implementation specifies `ssl=False`: [unifi_integration.py:328](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/unifi_integration.py:328).

   **Impact:** LAN interception can steal metrics tokens and, more seriously, the controller credential newly empowered to block devices.

   **Fix:** Make verified CA trust or an explicitly enrolled certificate pin the prerequisite for generated integration configurations and UniFi control. Test rejection of unexpected certificates.

5. **High — UniFi pauses survive ordinary rollback and configuration changes.**

   **Evidence:** #20 delegates expiry to the daemon, but §13’s rollback cleans only local firewall rules and dnsmasq. Controller URL/site can change in place: [unifi_integration.py:194](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/unifi_integration.py:194).

   **Impact:** Downgrading removes the only expiry worker while the controller remains blocked. Changing controllers can strand the original block. This exceeds the acknowledged outage-related fail-open limitation.

   **Fix:** Require a durable journal keyed by controller, site and MAC, with verified cleanup before disable, controller replacement or downgrade; preserve and surface unresolved cleanup entries.

6. **High — Monthly cap alerts require a missing accounting foundation.**

   **Evidence:** #6 queries surviving raw records through [bandwidth_tracker.py:177](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/bandwidth_tracker.py:177). [manager.py:583](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/storage/manager.py:583) can prune earlier days; the roadmap itself acknowledges two-day retention. The tracker also hardcodes UTC month boundaries and projection timing.

   **Impact:** “Monthly usage” decreases when indices disappear, silently defeating thresholds and projections. Matching the existing page merely reproduces its incomplete figure.

   **Fix:** Add bounded, durable, timezone-aware usage accounting before #6, with explicit incomplete-history status. Test pruning, restart, late records and local month boundaries.

7. **High — Thread timeouts do not establish the claimed resource limits.**

   **Evidence:** F1 and #1 rely on “threads with a time budget.” Running thread work cannot simply be cancelled when its caller times out. The repository already handles this explicitly in [drilldown_runner.py:179](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/api/drilldown_runner.py:179), retaining a slot until the worker finishes. [Python’s executor documentation](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Future.cancel) confirms the cancellation limitation.

   **Impact:** Slow queries can outlive their budgets, overlap subsequent work and consume memory or executor capacity. Before/after RAM snapshots miss transient peaks.

   **Fix:** Put bounded admission, per-job non-overlap and worker-lifetime accounting into F1’s contract, using cooperative query deadlines. Require overlapping-load and timeout tests with peak memory measurements.

8. **High — Quiet hours conflict with critical-alert bypass.**

   **Evidence:** #8 uses `retry_at` for quiet holds. Existing [notification_dispatcher.py:366](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/notification_dispatcher.py:366) applies that timer to the whole channel; lines 386–405 send all candidates together.

   **Impact:** A critical arrival either waits until morning or releases ordinary held messages alongside it. A full-day quiet window can also repeatedly defer its own daily digest.

   **Fix:** Specify separate immediate and quiet-held queues, independent delivery-retry timing and persisted digest-window boundaries. Test critical arrivals during holds and consecutive daily releases.

9. **High — Report schedules introduce another strict-store rollback failure.**

   **Evidence:** #1 adds timezone, weekday/hour and delivery state. [report_generator.py:75](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/report_generator.py:75) constructs `ReportSchedule(**sched_data)` and clears every schedule on an unknown-field `TypeError`.

   **Impact:** Downgrading after saving an extended schedule makes all schedules disappear; a later save can overwrite them permanently.

   **Fix:** Place the new fields in a versioned sidecar or separate store, and require a downgrade test using the actual old loader.

10. **High — SIEM recovery and deduplication guarantees are incompatible.**

    **Evidence:** #13 combines 24-hour catch-up, two-hour deduplication, batches of 500 and retaining the cursor on failure. The reused [alerts.py:182](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/api/alerts.py:182) supplies filtering, not stable paginated delivery.

    **Impact:** Partial success followed by an outage exceeding two hours resends the delivered prefix. A saturated overlap or more than 500 equal-timestamp records can stall pagination or lose events.

    **Fix:** Require stable document-ID pagination, persistent delivery checkpoints and bounded backlog draining. State an at-least-once contract with receiver-deduplication IDs; test partial batches, long outages, restarts and timestamp ties.

11. **Medium — Device notifications and weekly incidents lack a durable event source.**

    **Evidence:** F1 uses a count-only method, [device_registry.py:523](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/device_registry.py:523), while `first_seen` uses historical observation time at line 262. #5 specifies current state, not incident history. Notification history is capped at 100 in-memory entries: [notification_hub.py:525](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/notification_hub.py:525).

    **Impact:** Delayed discoveries can fall behind the polling watermark; weekly reports cannot reconstruct repeated offline/recovery incidents after restart.

    **Fix:** Add or reuse a durable, bounded discovery/transition journal with stable event IDs, separate observation and registration times, and retention covering report periods.

12. **Medium — Watched-device queries ignore devices answering connections.**

    **Evidence:** #5 searches only `source.mac`. Existing device discovery explicitly supports responding devices through [devices.py:302](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/api/devices.py:302) and destination MACs in [devices_v2.py:149](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/api/devices_v2.py:149).

    **Impact:** An actively serving NAS or printer can remain unknown or be declared offline.

    **Fix:** Include answered destination-side activity, requiring evidence of response packets so unanswered probes do not imply presence. Add tests for both cases.

13. **Medium — Feodo and ET Pro would overwrite each other’s settings.**

    **Evidence:** #10 adds another setting to `/etc/nettap/suricata.env`. [etpro.py:157](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/etpro.py:157) replaces that file with the ET Pro code alone; clearing ET Pro deletes it entirely.

    **Impact:** Saving or removing an ET Pro credential silently removes Feodo configuration. The rules lock does not preserve unrelated fields.

    **Fix:** Give feed opt-ins a separate allowlisted configuration file, or explicitly replace both writers with one shared store. Test both update orders and rollback.

14. **Medium — The assistant transport does not enforce its privacy and memory promises.**

    **Evidence:** #17 pins the initial address and limits elapsed time/tool calls, but specifies neither redirect handling nor a response-byte limit.

    **Impact:** An endpoint redirect can escape the LAN restriction unless refused or revalidated. A fast endpoint can return an enormous response within 60 seconds.

    **Fix:** Add a transport contract requiring disabled redirects and environment proxies, pinned destination enforcement, and bounded streamed response bytes/output tokens. Test public redirects and oversized responses.

15. **Medium — The background internet monitor violates the outbound-default rule.**

    **Evidence:** §4 requires outbound calls to be off by default. #2 starts a loop automatically; [internet_health.py:48](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/internet_health.py:48) targets Google, Cloudflare and OpenDNS addresses plus public DNS names.

    **Impact:** Installing the slice starts recurring third-party traffic without the explicit enablement promised by the roadmap. The speed-test confirmation does not cover this.

    **Fix:** Require a persisted monitoring opt-in naming all probe destinations before starting the loop; include an off-state test proving no outbound probes occur.

16. **Medium — Internet checks cannot support the promised provider-fault attribution.**

    **Evidence:** #2 adds one gateway ping and proposes “provider down.” Existing [internet_health.py:253](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/internet_health.py:253) measures loss against only the first target; lines 207–209 declare the internet down whenever that loss reaches 50%.

    **Impact:** Blocking or rate-limiting one target creates a recorded provider outage even while other internet targets and DNS work.

    **Fix:** Preserve per-target results and use an explicit evidence-based classification with an unknown-cause state. Test one blocked target, blocked gateway ICMP and genuine loss of upstream connectivity.

17. **Medium — The speed-test data estimate is not an enforced limit.**

    **Evidence:** #2 specifies four streams for about ten seconds and tells the owner to expect 100–300 MB, without a byte cap.

    **Impact:** Ten seconds at 1 Gbit/s is approximately 1.25 GB per direction before overhead. Faster links exceed that further, undermining both informed confirmation and the appliance’s capture-load assumptions.

    **Fix:** Specify and enforce an aggregate byte ceiling across streams and retries; make the confirmation display that maximum and test early termination at the cap.

18. **Medium — Recreating a username can reactivate deleted-account JWTs.**

    **Evidence:** #3 uses username plus a version initialized to zero. Existing identities resolve by username: [auth.ts:174](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/web/src/lib/server/auth.ts:174).

    **Impact:** Deleting and recreating the same username can make an old, unexpired JWT match the new account.

    **Fix:** Bind JWTs to an immutable account generation/ID that changes on recreation, and test delete–recreate replay.

19. **Medium — JA4 substitution cannot deliver the advertised rotating-MAC identity behavior.**

    **Evidence:** #7 promises linking a phone after a randomized-MAC change. [mac_correlator.py:630](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/mac_correlator.py:630) compares randomized MACs only against globally administered MACs and returns suggestions.

    **Impact:** Two successive private MACs are never compared. Replacing JA3 fields cannot satisfy that feature claim.

    **Fix:** Narrow #7 to improving existing merge suggestions and explicitly leave rotating-private-MAC identity linkage to NET-172.

20. **Medium — Gateway control lacks an executable verification prerequisite.**

    **Evidence:** #20 permits gateway control as beta despite no gateway bench. The cited [failure-injection-release.sh:3](/Volumes/ExtraStrg_RAID1/Mega%20Sync/Coding%20Projects/NetTap/.claude/worktrees/feature-roadmap/scripts/remote/failure-injection-release.sh:3) currently exercises sensor/database failures and explicitly avoids the network path.

    **Impact:** Mocked argv tests and mirror-mode trials cannot establish kernel expiry, real forwarding behavior, DNS reloads or rollback recovery.

    **Fix:** Gate gateway control on a Linux network-namespace/VM harness exercising actual forwarding, expiry, daemon death, DNS failure and rollback; keep that portion unavailable until it passes.

VERDICT: REVISE

### Claude response (round 1)

All 20 points were accepted. Changes, by point:

1. **#3 store writes:** serialised in an in-process mutex that re-reads inside the lock and re-checks after hashing. Concurrency tests added.
2. **#3 rollback:** `rollback-accounts.sh` removes viewers and rotates `jwt-secret.txt` before the older image starts, then checks captured tokens get 401. Recorded in §13.
3. **#11A certificate swap:** generation directories, an atomic `active` symlink switch, an immutable `gen-installer`, startup recovery, and process-death tests at each step. §13 rollback restores the old file paths.
4. **TLS for integrations:**
   - D15 changed: generated Prometheus and Home Assistant configs always verify (trusted certificate or NetTap's CA file).
   - #20 UniFi control requires verified TLS or an enrolled fingerprint pin.
5. **#20 stranded UniFi pauses:** a durable pause journal keyed by controller, site and MAC. Cleanup must finish before disable, a controller change or a downgrade, and unresolved entries are shown.
6. **Monthly usage:** new foundation F4, a durable, time-zone-aware usage ledger with "counted since" for incomplete history. #6, #1 and #12a use it.
7. **Thread budgets:** F1 now has a job contract: a 2-worker pool, no overlap, slots held until the thread finishes (`drilldown_runner` pattern), cooperative OpenSearch deadlines, and peak-RSS sampling. Tests added.
8. **#8 quiet hours:** separate `held` and `pending` queues; critical items are sent alone; saved digest windows; tests for consecutive daily releases.
9. **#1 schedule fields:** moved to a sidecar `report_schedule_meta.json`, with a test that runs the old loader against new files.
10. **#13 delivery:** the contract is now at-least-once with `event_id`. PIT plus `search_after` with a unique tiebreaker, a checkpoint per confirmed batch, a 2,000-per-tick bound, and tests for ties, partial batches and long outages. The indexing-lag risk is noted.
11. **Event history:** F1 adds a durable event journal with stable IDs, separate observed and recorded times, and 120 days of retention. New-device detection uses registration time. #5 and #1 use the journal.
12. **#5 answering devices:** devices that answer connections now count as heard (with evidence the device responded); unanswered probes don't. Tests added.
13. **#10 Feodo vs ET Pro:** Feodo gets its own `/etc/nettap/suricata-feeds.env`. Tests cover both update orders with ET Pro.
14. **#17 transport:** a transport contract: no redirects, no environment proxies, pinned address, a 256 KB response cap and `max_tokens`. Tests added.
15. **#2 monitoring default:** monitoring is opt-in, with the destinations listed. A test proves nothing is sent while it's off, and §5 has a new row.
16. **#2 outage cause:** results are kept per target, with an explicit up / degraded / router unreachable / provider down / unknown classification. Tests added.
17. **#2 speed-test data:** a hard 250 MB per-direction ceiling, shown in the confirmation and tested.
18. **#3 replayed tokens:** an immutable `accountId` in the JWT (`aid`); a recreated username gets a new id.
19. **#7 JA4 claim:** narrowed to fixing the existing merge suggestions. Linking random MACs stays with NET-172.
20. **#20 gateway proof:** a network-namespace or VM harness is now a prerequisite. Gateway control stays unavailable, not just "beta", until the harness passes.

New risk introduced: F1 grew from M to L, which lengthens the critical path (F1 → F2 → #5 → #1).

## Round 2 - Codex

I read the revised plan and the latest Claude response. Most earlier findings are addressed at roadmap level. These remain unresolved or arise from the revisions.

1. **High — F4 can still lose usage and reduce previously counted totals.**

   **Evidence:** F4, plan lines 185–193, recomputes today/yesterday and permanently closes days after 26 hours. [excluded_ips.py:504](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/excluded_ips.py:504>) explicitly excludes interim connection records; bytes appear upon finalization. [bandwidth_tracker.py:245](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/bandwidth_tracker.py:245>) attributes them to connection-start time.

   **Impact:** A connection lasting several days finalizes into an already-closed bucket and is never counted. Separately, pruning before closure can make recomputation overwrite a larger subtotal with a smaller one.

   **Fix:** Replace fixed-day closure with an idempotent, ingestion-watermarked accumulator that permits corrections to older buckets and records processing gaps. Test multi-day connections, pruning before closure and downtime.

2. **High — Legacy-token migration leaves an exception to session revocation.**

   **Evidence:** #3, plan line 212, accepts tokens without `aid` “once” and reissues them, without defining persistent consumption or restricting migration to the original account/version. Existing tokens identify only username and role: [auth.ts:59](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/web/src/lib/server/auth.ts:59>).

   **Impact:** The migration exception can rebind an unused legacy token after a password reset or account replacement. “Once” does not prevent that first replay.

   **Fix:** Require one-time reauthentication on upgrade and reject legacy JWTs. Remove the compatibility exception and test legacy-token replay after reset and restart.

3. **High — Accounts rollback does not necessarily rotate the effective signing secret.**

   **Evidence:** #3, plan lines 237–241, rotates `jwt-secret.txt`, starts the old build, then tests tokens. [auth.ts:24](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/web/src/lib/server/auth.ts:24>) gives `JWT_SECRET` precedence over that file.

   **Impact:** On installations using the supported environment override, viewer and revoked JWTs remain valid when the older, unrestricted build becomes reachable.

   **Fix:** Quiesce access, rotate the effective secret—including any environment override—or refuse downgrade. Verify token rejection before reopening access.

4. **High — The UniFi journal records intent without establishing ownership of a block.**

   **Evidence:** #20, plan lines 880–883, writes `{blocked_at, expires_at, state}` before the block request and later unblocks every journal entry.

   **Impact:** A device already blocked by the owner or another integration can become journalled and subsequently unblocked by NetTap. Failed or ambiguous requests also leave entries that cleanup treats as owned.

   **Fix:** Require an ownership protocol: refuse preblocked devices, persist prior state and operation identity, and automatically undo only confirmed NetTap-owned transitions. Test pre-existing blocks and timeouts after controller-side application.

5. **Medium — F1’s journal lacks a serialization and durable-commit contract.**

   **Evidence:** F1, plan lines 144–155, introduces two workers, appends, daily atomic compaction, and separate journal/outbox/job-state files. [capture_config.py:244](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/capture_config.py:244>) makes one file replacement atomic; it does not coordinate these operations.

   **Impact:** Compaction can overwrite a concurrent append. A crash between advancing producer state and recording its event can lose an incident. Skipping—but not removing—a torn tail can also corrupt the next append.

   **Fix:** Specify one serialized journal writer, including compaction, and make the durable event the commit point from which delivery and producer checkpoints recover. Add concurrent-compaction and crash-boundary tests.

6. **Medium — Quiet hours still permit retries originating before the window.**

   **Evidence:** #8, plan lines 278–288, holds items arriving inside the window while retaining separate retry timing. Existing retries are scheduled independently in [notification_dispatcher.py:438](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/notification_dispatcher.py:438>).

   **Impact:** An ordinary notification failing at 21:59 can retry at 22:00 during a 22:00–07:00 quiet window. Separating critical and held queues does not prevent this.

   **Fix:** Apply quiet-hour eligibility at every delivery attempt, including retries and budget-delayed items. Test failure immediately before the quiet boundary.

7. **Medium — The revised Home Assistant configuration is invalid.**

   **Evidence:** #12b, plan line 650, puts a CA-file path in `verify_ssl`. Home Assistant defines that option as a boolean, not a certificate path. [Official REST documentation](https://www.home-assistant.io/integrations/rest/).

   **Impact:** The generated YAML fails configuration validation; it does not establish trust in the downloaded CA.

   **Fix:** Generate `verify_ssl: true` and make a certificate trusted by that HA installation a prerequisite, through #11A or a verified trust-store enrollment procedure. Validate the generated configuration and an actual TLS request.

8. **Medium — TCP/TLS write completion cannot provide the revised SIEM delivery guarantee.**

   **Evidence:** #13, plan lines 664–668, promises at-least-once delivery and advances the checkpoint after a write drains. `drain()` is local flow control; syslog has no application-level acknowledgment establishing reception. [Python documentation](https://docs.python.org/3/library/asyncio-stream.html#asyncio.StreamWriter.drain), [RFC 5425 §6.3](https://www.rfc-editor.org/rfc/rfc5425.html#section-6.3).

   **Impact:** A receiver can fail after transport acceptance but before processing. NetTap advances its checkpoint and never retries those records. This affects TCP/TLS as well as UDP.

   **Fix:** Describe this slice as best-effort reception with durable retries of detected failures and possible ambiguous loss. Reserve true at-least-once reception for an acknowledged protocol.

9. **Medium — Cached DNS can hide a real WAN outage.**

   **Evidence:** #2, plan line 360, requires external probes and DNS to fail before declaring provider-down. The reused DNS check calls the system resolver: [internet_health.py:98](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/internet_health.py:98>).

   **Impact:** Cached answers can continue throughout the proposed three-minute WAN-disconnection test. The classification then produces an unknown/degraded state instead of the promised outage.

   **Fix:** Determine external-connectivity loss independently of cached DNS success, and track DNS health and fault attribution separately. Add the gateway-up/external-probes-down/cached-DNS-success case.

10. **Medium — The internet monitor remains outside the repaired worker-lifetime protections.**

    **Evidence:** #2 starts the existing monitor continuously. [internet_health.py:105](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/internet_health.py:105>) wraps default-executor DNS work in `wait_for`; timeout does not stop the underlying thread. Ping timeout paths also omit child cleanup. [host_resolve.py:2](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/services/host_resolve.py:2>) already documents and solves this problem for other tools.

    **Impact:** Repeated stalled checks can occupy shared executor workers or leave subprocesses running. F1’s dedicated pool does not protect this separate loop.

    **Fix:** Require killable resolver/probe operations with cancellation cleanup, reusing `host_resolve`, and test repeated hangs without worker or process accumulation.

11. **Medium — Weekly-report verification contradicts the new durable data source.**

    **Evidence:** #1, plan line 423, reads traffic from F4, but line 457 still requires equality with raw `/api/bandwidth/daily`. That endpoint invokes raw aggregation in [bandwidth.py:140](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/api/bandwidth.py:140>).

    **Impact:** After pruning, a correct durable report must differ from the raw endpoint, so the acceptance check fails precisely when F4 works. A single oldest-record coverage label also cannot describe durable traffic and shorter-lived alert data accurately.

    **Fix:** Define a shared ledger-backed daily/window contract for verification and report coverage separately for each source.

VERDICT: REVISE

### Claude response (round 2)

All 11 points were accepted:

1. **F4 rebuilt:** an accumulator keyed on `event.ingested`. It works in half-open windows and adds bytes to the connection's start day. The watermark and the added bytes are saved in one atomic write. Days never close, so totals never go down. Gaps are recorded when the raw data was pruned before it could be counted. Tests cover multi-day connections, pruning before counting, crash between steps, and downtime.
2. **#3 legacy tokens:** tokens without `aid` are rejected, with no compatibility exception. Everyone signs in again once, and the release note says so. A test covers replaying a legacy token after a reset and a restart.
3. **#3 rollback:** nginx is stopped first. The script rotates the *effective* secret and refuses to continue when `JWT_SECRET` is set in the environment. Tokens are checked from inside before nginx starts again; any failure leaves it stopped.
4. **#20 UniFi ownership:** read the client's state first and refuse a device that is already blocked. Then intent → confirmed after a read-back, and an `ambiguous` state after a timeout. Only `confirmed` entries are ever undone automatically. Tests cover a block that existed beforehand and a timeout after the controller applied the block.
5. **F1 journal:** one serialised writer for appends, compaction and torn-tail truncation. The journal append is the commit point: producer state and the outbox follow it, and recovery delivers each event at most twice, never zero times. Tests cover concurrent compaction and every crash point.
6. **#8 retries:** the quiet-hours check runs at every delivery attempt, including retries and items delayed by the daily cap. A test covers a failure at 21:59.
7. **#12b Home Assistant:** `verify_ssl: true` only, so the card requires #11A, and until then it says what's missing. The YAML is checked with HA's config checker.
8. **#13 wording:** now best effort, with durable retries of failures NetTap can detect and the possibility of loss it can't see stated plainly. `event_id` is kept for dedupe, and acknowledged protocols are out of scope (D17).
9. **#2 DNS:** DNS is tracked separately and never decides the outage cause. Each external target is probed with ICMP plus a TCP 443 connect. A test covers the case where cached DNS still answers during an outage.
10. **#2 threads:** the monitor runs as an F1 job, with `host_resolve`'s killable resolver and subprocess cleanup. A test covers 20 consecutive hangs. #2 now depends on F1.
11. **#1 verification:** checked against the ledger contract (`/api/usage/daily`). Coverage is stated per source: traffic, alerts and journal.

## Round 3 - Codex

One roadmap-level blocker remains. The other revisions address my earlier findings.

1. **High — F4’s timestamp watermark can permanently skip usage.**

   **Evidence:** [F4, plan:204](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/plans/2026-11-18-feature-roadmap.md:204>) consumes disjoint `event.ingested` windows, permanently advances the watermark, and claims exactly-once counting. But the configured Malcolm version stamps `event.ingested` in its [Logstash enrichment filter](https://github.com/cisagov/Malcolm/blob/v26.10.0/logstash/pipelines/enrichment/20_enriched_to_ecs.conf#L77), **before** the [OpenSearch output](https://github.com/cisagov/Malcolm/blob/v26.10.0/logstash/pipelines/output/99_opensearch_output.conf) writes the document.

   **Impact:** Output backpressure or retries can make a record searchable after its timestamp window has been consumed—even while ledger queries succeed. Its bytes are then omitted permanently. The five-minute delay does not guarantee completeness, and the pruning-gap mechanism cannot detect this loss. Cap alerts, reports and metrics inherit the undercount.

   **Fix:** Replace disjoint additive windows with replay-safe accounting that deduplicates by stable record identity and reconciles late-visible records. Make a test where indexing completes behind an already-advanced watermark—and the bytes are still counted exactly once—a prerequisite for F4’s dependent slices.

VERDICT: REVISE

### Claude response (round 3)

Accepted. F4 no longer advances a one-way watermark over `event.ingested`. Instead:

- Each pass recomputes a local day's total in full (same aggregation and filters as `get_daily_usage`, over `@timestamp`) and stores `days[D] = max(days[D], recount(D))`.
- Recounts are full sums, so a repeated pass changes nothing and a record is never counted twice.
- A record that becomes searchable late, or a long connection that finishes later, is in the next recount of its day. Today and the two days before are recounted every 15 min, and every retained day nightly.
- Totals never go down. When a recount comes back lower than the stored value, pruning has reached that day, and the day is marked `complete: false` and shown as approximate.
- The late-visibility test (a record searchable only after an earlier pass is counted exactly once on the next) is a prerequisite before #6, #1 and #12a start.

Remaining limit, stated in the plan: a record for a day that pruning has already reached, and that becomes visible only after that point, may be undercounted. The UI marks such days approximate.

## Round 4 - Codex

The recount approach resolves the previous watermark issue. One narrower correctness problem remains.

1. **Medium — F4 can label pruned, incomplete totals as complete.**

   **Evidence:** [F4, plan:212–215](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/plans/2026-11-18-feature-roadmap.md:212>) recounts retained days and detects pruning through a decrease in totals. The existing [storage manager:583](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/feature-roadmap/daemon/storage/manager.py:583>) deletes dated indices independently.

   **Impact:** Suppose the saved total is 100 GB. Pruning removes 60 GB, then delayed records add 80 GB before the next recount. The recount becomes 120 GB: no decrease is observed, although historical usage was 180 GB. The day remains “complete,” so its approximation warning and #6’s projection suppression do not activate. Older days disappearing entirely can also escape the retained-day scan.

   **Fix:** Keep the high-water recount design, but derive completeness from source-coverage or pruning evidence, including vanished days. Mark unverifiable coverage incomplete regardless of whether totals decrease. Require tests for offsetting deletions/additions and complete day disappearance; the specific mechanism belongs in F4’s slice plan.

VERDICT: REVISE

### Claude response (round 4)

Accepted. The high-water recount design stays, but completeness now comes from coverage evidence:

- **Index inventory:** each pass records the raw index inventory with each index's `@timestamp` range.
- **Vanished indices:** an index that vanished between passes (deleted by NetTap's storage manager or by ILM/ISM) marks every overlapping local day `complete: false`. The exception is a day already settled: a recount with no index missing at least 72 h after the day ended.
- **Ledger days, not raw days:** the nightly pass walks the ledger's own days, so a day whose raw records vanished entirely is re-marked by the same rule, and its stored total stays.
- **No inventory:** when the inventory is missing, the affected days are marked incomplete.
- **Falling totals:** a recount lower than the stored value is now only extra evidence.

New tests: an offsetting deletion plus late addition; whole-day disappearance; ILM deletion; a missing inventory. The exact mechanism is settled in F4's slice plan.

## Round 5 - Codex

Reviewed the revised plan and latest Claude response. No remaining roadmap-level blockers.

The coverage inventory and vanished-day handling address the last finding. F4’s stated 72-hour approximation limit is acceptable at this level; its precise semantics and validation belong in the mandatory slice review.

VERDICT: APPROVED

### Outcome

APPROVED in round 5 of 5. Across the five rounds Codex raised 33 findings (20, 11, 1, 1, 0), and all were accepted. F4's 72-hour approximation limit is carried into its slice review, as Codex noted.
