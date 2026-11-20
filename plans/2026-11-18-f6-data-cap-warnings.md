# #6: Data cap warnings, 2026-11-18

**Linear:** NET-339 · **Roadmap:** `plans/2026-11-18-feature-roadmap.md` §8 #6, decisions D1 and D4 · **Depends on:** F1 (#336), F4 (#337/#338)
**Branch:** `feature/f6-data-cap-warnings` (from `origin/main` 966fe873) · _Revised after Codex rounds 1–4 (§10–§13). Round 3 simplified the design; see §12._

## 1. What the owner gets

- **A place to set the cap.** A "Monthly data cap" card on Settings › Network. The Bandwidth page links to it when no cap is set.
- **Three warnings per month, for each cap, each sent at most once:**
  - **80%** of the cap (medium);
  - **100%** of the cap (high);
  - **"on track to go over"** (medium), only from day 3, and only when the ledger can project the month.
- **The usual channels.** Warnings go out through the same channels, limits and retries as alerts.
  - A "Tell me when I near my data cap" switch in Settings › Notifications is on by default (D1).
  - The rule builder offers "Data cap".
- **Honest figures.** Warnings and the Settings card use a figure that is never too high. When the month isn't fully counted, they say "at least" and "counted since …".

## 2. Facts (code at 966fe873)

- **The month's figures:** `usage_report.month(snapshot, year, month, now, rules, owner)` (F4) computes the month from one ledger snapshot. `api/usage.month_reply(ledger)` calls it for the owner's current local month.
  - It is an in-memory read, with no OpenSearch query.
  - It gives `bytes.total`, `complete`, `since`, `tz`, `days[*].status`, `month_start`, `month_end` and `projected` (null unless every elapsed day is `counted`).
  - `/api/bandwidth/cap` reports `bytes.total` as `current_usage_bytes`.
- **The cap:** `BandwidthTracker.get_cap()` / `save_cap(bytes)` store it in `/opt/nettap/data/bandwidth_cap.json`, where `0` means none.
  - `save_cap` sets the live value, then truncates and rewrites the file (`bandwidth_tracker.py:145`).
  - `PUT /api/settings/bandwidth-cap` takes `{monthly_cap_gb}` in decimal GB.
  - The web's `setBandwidthCap` has no caller.
- **The F1 journal:**
  - `append(type, key, observed_at, data, instance)` returns None when the id `sha256(type|key|instance)` is already retained (`event_journal.py:140`).
  - `compact()` (`:173`) keeps 120 days, then the newest 50,000 lines, plus everything after the dispatcher's cursor and the newest line.
- **The dispatcher:**
  - `_take_events` makes items via `event_item` (`:216`; only `new_device` today).
  - It trims each channel queue oldest-first past `MAX_EVENTS` (`:372`).
  - `digest()` renders at most `DIGEST_LINES = 10` lines (`:197`).
  - A successful send clears the whole event queue (`:701` returns `_NO_EVENTS`).
  - Services clip messages: Pushover at 1,024 characters, Discord and Telegram at 4,096 (`notification_hub.py:748/807/836`).
- **Quick settings:**
  - `QUICK_NEWDEVICE` / `_newdevice_rule` / `with_default_event_rules` live in `notification_config.py`.
  - `_with_quick_rule` returns early, saving no event rule, when no Settings channel exists (`:334`).
  - `rule_ok` accepts `channels: []`.

## 3. Decisions

1. **The journal is the only record of "sent".**
   - A warning is `append("data_cap", key=<"80" | "100" | "projected">, instance="<YYYY-MM>|<cap bytes>")`.
   - The id dedupe makes "once per month, for this cap" durable. The append is also the commit point for delivery (F1).
   - Compaction keeps `data_cap` lines recorded in the last 62 days, even past the 50,000-line cap, so this month's ids can't be evicted (§4.2). That is one predicate in `compact()`.
   - There is no separate state file, so there is nothing to keep in step and no state write that can fail after an append.
2. **A different cap is a new set of warnings.** Raising the cap from 100 GB to 200 GB re-arms 80% at 160 GB. Going back to 100 GB this month finds the earlier ids, so nothing is re-sent.
3. **The time zone is not part of the instance.** A zone change mid-month leaves "November" as November, so nothing is re-sent.
4. **Thresholds use a lower bound under the current rules** (Codex r1 #1).
   - `usage_report.month()` adds `bytes.lower_bound`: the sum of the month's day totals counted under the current rules hash (`counted`, `approximate`, and `stale` days whose rules match), computed in the same call as `projected` (Codex r2 #5).
   - Past a threshold, it is a true crossing.
5. **Only the current month is checked** (this reverses round 1 #5; see §12).
   - A record accounted after the month ends (a recount after midnight, or a sweep up to 3 days later) can raise last month's final figure.
   - That month is over, so a warning then can't change anything the owner does. The month's final figure is on the Bandwidth page.
   - **Stated limit:** a crossing first accounted after the last local midnight of the month is not warned about.
6. **The job reads the ledger snapshot every 15 min.** It makes no OpenSearch query, so the roadmap's hourly aggregation cost no longer applies.

## 4. Design

### 4.1 Event type, rule and quick setting (`notification_config.py`, `notification_hub.py`)

- **Event type:** add `"data_cap"` to `EVENT_TYPES`.
- **Fixed rule:** `QUICK_DATACAP = "settings-datacap"`, a sibling of `QUICK_NEWDEVICE`.
  - `_newdevice_rule` becomes `_event_rule(rid, event_type, rules, ids, on, now)`. The old function stays as OLD CODE.
  - Both fixed rules use `min_severity: 4`.
- **Defaults:** `with_default_event_rules` seeds both fixed rules, on by default (D1).
- **Quick settings:** `quick_view` reports `data_cap`. `apply_quick_settings` takes an optional `data_cap`; leaving it out keeps what is saved.
- **Deleting the rule:** `hub.delete_rule` turns it off, for both fixed event rules.
- **An opt-out made before any channel exists is kept** (Codex r1 #6). `_with_quick_rule` now always writes both fixed event rules, with `channels: []` when no Settings channel exists and their `enabled` value. This fixes F1's new-device rule too. The early return stays as OLD CODE.

### 4.2 Producer (`daemon/services/data_cap.py`, new) and journal protection

`DataCapWatch(tracker, ledger, journal)`, with `run(deadline)`:

1. **No cap means nothing to do.** If `cap = tracker.get_cap()["monthly_cap_bytes"]` is 0, return `{"sent": []}`.
2. **Read the month.** `m = month_reply(ledger)`. With no ledger snapshot yet, return.
3. **Check the thresholds.** `low = m["bytes"]["lower_bound"]`.
   - `"80"` when `low >= 0.8 × cap`;
   - `"100"` when `low >= cap`;
   - `"projected"` when `m["projected"]` is not null, `m["projected"] > cap`, `low < cap`, and today's `cutoff - month_start >= 3 days`.
4. **Append each due threshold,** in order: 80, 100, projected. Each is `journal.append("data_cap", key, observed_at=now, data, instance=f"{y:04d}-{mo:02d}|{cap}")`, with `data = {threshold, used: low, cap, projected, month_label, tz, since, complete}`. An append that returns None was already sent.
5. **Errors.** An `OSError` from an append is raised after the others are tried, so F1 records `last_error`. A failed append leaves the journal unchanged, so the next run retries it.
6. **Result.** It returns `{"sent": [keys appended]}`.

`EventJournal.compact()` gains one keep rule: lines of type `data_cap` recorded in the last 62 days are kept, even past `max_lines`.
- At most 3 warnings per cap per month are written, so the extra lines are bounded by what the owner does.
- The old keep expression stays as OLD CODE.

### 4.3 Message and delivery (`notification_dispatcher.py`)

- **`event_item` gains a `data_cap` branch.**
  - Severity: `"80"` → 3, `"100"` → 2, `"projected"` → 3.
  - Titles: "Data cap: 80% used", "Data cap reached", "Data cap: on track to go over".
  - The line is at most 140 characters, in decimal GB with one decimal place (NET-166). For example, "82.4 GB of your 100 GB cap used in November (Europe/London)", plus ", at least: counted since 13 Nov" when the month isn't complete. The projection reads "On track for 131.0 GB in November, over your 100 GB cap".
  - The sig is `event:<id>`.
- **Delivery: a journal event leaves its queue only once it was actually shown** (Codex r1 #2, r2 #1, r3 #1–2). Each point fixes the same loss for `new_device` too.
  - **The digest fits the channel's whole outbound payload** (Codex r4 #2). `digest(items, overflow, max_chars)` renders lines in the existing worst-first order while the body (with its footer and any budget notice) stays within `max_chars`. It still renders at most 10 lines, and returns which items it rendered.
    - `max_chars` comes from one hub function, `body_limit(channel_type)`, next to the clips it mirrors (`notification_hub.py:748/807/836`):
      - **Pushover:** 1,024. Its title is a separate field.
      - **Discord:** 4,096. Its title is a separate field.
      - **Telegram:** 4,096 − 300. Telegram sends `"[SEVERITY] {title}\n\n{message}"` as one text. Titles are clipped to 256 characters, so 300 covers the tag, the title and the separators.
      - **Everything else:** no limit.
    - A test builds the real outbound payload for each clipped service, with a journal event placed just at the limit, and checks that nothing rendered is cut.
  - **Every event fits on its own, and a misfit never blocks the rest** (Codex r4 #3).
    - `event_item` clips every journal event's `line` to 300 characters, ending in "…". This covers the unbounded vendor name in new-device lines (`:223`). The smallest `max_chars` (1,024 for Pushover) minus the footer and budget notice still fits several lines.
    - The fitter skips an item that doesn't fit and tries the next ones, rather than stopping. A skipped item stays queued for the next message.
  - **Acknowledge only what was rendered.** After a successful send, journal events that weren't rendered stay in the channel's queue for the next message. Alerts keep today's behaviour ("and N more", which are on the Alerts page).
  - **Never trimmed.** The `MAX_EVENTS` trim skips `data_cap` items.
  - **Only the current cap's warnings are sent** (Codex r4 #1). The dispatcher gets one callable, `data_cap_now()`, which returns `(owner month "YYYY-MM", current cap bytes)` from the same tracker and owner zone the producer uses. Before each send:
    - a `data_cap` item for an earlier month is dropped, with a log warning, because that month is over (§3.5);
    - an item for this month whose cap isn't the current cap (including a cap now set to 0) is **held, not sent and not dropped**. If the owner returns to that cap this month, it is sent then; A → B → A during an outage loses nothing;
    - a held item is never sent for a cap the owner has left, so raising or removing the cap silences old warnings.
    - **The bound:** at most 12 `data_cap` items per channel queue. Past that, the oldest held item is dropped with a log warning, as it belongs to a cap the owner has since replaced. Items are never merged: "80" and "projected" both stay.
  - **Critical alerts stay first.** The order is unchanged, so warnings never move a critical alert down. A `data_cap` line that doesn't fit this message goes in the next one.

### 4.4 Job wiring (`server.py`)

`Job("data-cap", "Data cap warnings", every_s=900, deadline_s=30, run=data_cap.run)`, using the `event_journal`, `bandwidth_tracker` and `usage_ledger` already built there.

### 4.5 Cap save, API and web

- **`save_cap` is atomic** (Codex r1 #3). Under a lock, it writes with `write_file_atomic` first, then sets the live value. A failed write raises, and `handle_set_cap` returns 500 "Couldn't save the cap", with the live and saved cap unchanged. The old body stays as OLD CODE.
- **`/api/bandwidth/cap`** adds `lower_bound_bytes` from the same `month_reply` (Codex r2 #6).
- **The Settings › Network "Monthly data cap" card** (`NetworkTab.svelte`, built from `ui/` components, with `CardState`):
  - a GB input (blank or 0 means no cap), checked against 0 to 1 PB, and a Save button;
  - helper text: "NetTap warns you at 80%, at 100%, and when the month is on track to go over."
  - **Its use line, from `getBandwidthCap`** (whose type gains `tz`, `since`, `complete` and `lower_bound_bytes`):
    - a complete month: "82.4 GB of 100 GB used this month";
    - otherwise: "At least {lower bound} of 100 GB … counted since 13 Nov";
    - days under earlier exclusions: "Recounting under your new exclusions";
    - no ledger yet: "Still counting".
- **Bandwidth page:** with no cap, the cap KPI shows "No cap set" and links to `/settings?tab=network`.
- **Settings › Notifications:** a "Tell me when I near my data cap" switch.
- **Rule form:** "Data cap" is an event type. Its severity field is hidden and 4 is sent.

## 5. Failure model

- **Exactly once per (month, cap, threshold):** the journal id, protected from compaction for 62 days. Delivery is at least once per channel (F1), and an event leaves a queue only once it was shown.
- **A crash anywhere** is safe. Before the append, the next run appends. After it, the id dedupes.
- **No ledger snapshot** means nothing is sent.
- **Exclusions changed:** `lower_bound` drops the days under old rules, so a false crossing can't be sent. A crossing already sent stays sent.
- **Stated limits:**
  - a crossing first accounted after the month's last local midnight is not warned about (§3.5);
  - a queued warning for a past month is dropped after the month ends.

## 6. Tests

- **`daemon/tests/test_data_cap.py`, with a ledger snapshot through `month_reply` and a real `EventJournal` in `tmp_path`:**
  - no cap sends nothing; 79.9% sends nothing; 80% sends once and a second run nothing;
  - 80 and 100 together in one run;
  - the projection: only from day 3, only when `projected > cap` and `low < cap`, never when `projected` is null; 80 and projected together both stay;
  - a cap change: raising it re-arms, and A → B → A doesn't re-send;
  - a zone change mid-month doesn't re-send;
  - a new month re-arms;
  - an incomplete month sends on the lower bound, with "at least";
  - after an exclusions change, `recount_pending` and `old_rules` days don't count;
  - a failed append raises after trying the others, and the next run retries;
  - the month's last local minute versus after midnight (not checked, per the stated limit).
- **`test_event_journal.py`:** compaction with a small `max_lines` keeps `data_cap` lines from the last 62 days and drops older ones.
- **`test_usage_report` cases:** `lower_bound` and `projected` come from one call; a rules change between two reads can't mix them.
- **`test_dispatcher_events.py`, with `data_cap_now` stubbed:**
  - a `data_cap` entry becomes an item with the right severity, title and line, routed by a `data_cap` rule;
  - 12 queued events plus a critical alert: the first message renders what fits, and the rest go in the next message;
  - Pushover's 1,024-character clip: what was rendered fits, and nothing unrendered is acknowledged;
  - a 500-event flood doesn't trim a `data_cap` item;
  - a channel down across three months keeps only the current month's items;
  - a cap raised above every threshold, or set to 0, while an item is queued: the item is held, not sent (r4 #1);
  - A → B → A during an outage: A's held items are sent once A is back, and never re-created (r4 #1);
  - more than 12 held items drop the oldest held one;
  - the real Telegram, Pushover and Discord payloads, with a journal event at the limit, are not cut (r4 #2);
  - a 2,000-character vendor name is clipped to a 300-character line, and a cap warning queued behind it is still sent in the same message (r4 #3).
- **Quick settings:**
  - the data cap switch defaults to on with a channel;
  - an off setting is kept;
  - deleting the rule turns it off;
  - opting out, restarting, then setting up a channel leaves both fixed rules off (`data_cap` and `new_device`).
- **Cap save:** an injected write failure leaves both the live and the saved cap unchanged, and the route returns 500.
- **Web (Vitest):**
  - the Network card: load, save, validation, error, no cap, and each use line (complete, at least, recounting, still counting);
  - the Bandwidth "No cap set" link;
  - the Notifications switch;
  - the rule form's Data cap choice;
  - visual fixtures for the card.

## 7. Gates

- `/codex-review`.
- `/deep-review`, which is mandatory.
- `/ponytail-review`.
- The two-angle review before merging.

## 8. Deploy and G11 check (`scripts/remote/deploy-data-cap-warnings.sh`)

Run it after `git pull` on `main`, or after checking out the branch first (F4 lesson). Memory is read with `docker top` and OpenSearch's cgroup `anon`, and a restarted daemon only after 5 minutes.

1. **Baseline, using only fields the running build already has** (Codex r4 #4):
   - the settled daemon memory;
   - the saved cap, `monthly_cap_bytes` from `/api/bandwidth/cap`.
2. **Build and recreate** the daemon and web, and wait until both are healthy.
3. **The real scheduler path:** with the owner's own cap, force `POST /api/jobs/data-cap/run`. `/api/jobs` shows the run with no error. With no cap set (the G11 today), the result is `{"sent": []}`.
4. **A synthetic crossing, isolated** (Codex r3 #6, r4 #4):
   - Read `lower_bound_bytes` from the new `/api/bandwidth/cap`.
   - **If it is under 2 GB,** skip this step and print "skipped: under 2 GB counted this month". That is a pass, because a correct watcher sends nothing then.
   - **Otherwise** a `trap … EXIT` that restores the saved cap is set first, so the cap is restored even if a later step fails. Then:
     - PUT `monthly_cap_gb = 1.234567` (a cap no owner would type) and force the job;
     - check `events.jsonl` has `data_cap` `"80"` and `"100"` for instance `<YYYY-MM>|1234567000`;
     - force it again and check there are no new lines;
     - restore the saved cap and check it.
   - The test ids are keyed by that odd cap, so a real cap set later is a different instance and keeps its warnings.
   - The G11 has no channel, so nothing is sent.
5. **Memory:** the settled daemon is within 50 MB of its baseline.

## 9. Risks

- **A mid-month ledger start undercounts that month.** The "counted since" line covers it.
- **An owner who types 1.234567 GB as their real cap this month** would find the G11 test's warnings already sent. Only the G11 is affected.

## 10. Round 1 changes (7 findings, all taken; #5 later withdrawn in round 3)

| # | Finding | Change |
|---|---|---|
| 1 | Incomplete usage isn't a lower bound under changed exclusions | thresholds use `lower_bound` (current-rules days only) |
| 2 | Digest truncation could drop a cap warning | see round 2 #1 and round 3 |
| 3 | `save_cap` isn't atomic | atomic write, then the live value; 500 on failure |
| 4 | The journal's line cap can evict this month's record | see round 3: a compaction keep rule for `data_cap` (62 days) |
| 5 | A crossing accounted after midnight isn't checked | withdrawn in round 3: a stated limit (§3.5) |
| 6 | An opt-out with no channel reverts to on | fixed event rules always written (`channels: []`) |
| 7 | The card hides an incomplete month | "at least … counted since" wording and the status lines |

## 11. Round 2 changes (6 findings)

| # | Finding | Change |
|---|---|---|
| 1 | Ordering alone doesn't guarantee delivery | events acknowledged only when rendered, with a per-channel length fit (§4.3) |
| 2 | The state file lost records | the state file was removed in round 3; the journal is the only record |
| 3 | Reconciliation used the new month's cap | reconciliation removed in round 3 |
| 4 | Reconciliation stopped before days settle | reconciliation removed in round 3 |
| 5 | The projection and the lower bound came from different snapshots | both come from one `usage_report.month()` call |
| 6 | The card's "at least" used the unsafe total | `lower_bound_bytes` on `/api/bandwidth/cap`, used by the card |

## 12. Round 3 changes (6 findings): simplified

| # | Finding | Change |
|---|---|---|
| 1 | Coalescing overwrote distinct warnings | no merging: "80", "100" and "projected" each stay queued until shown |
| 2 | Per-month coalescing didn't bound the queue | a queued item for a past month is dropped, and another cap's items for the same month are dropped: at most 3 a channel |
| 3 | A failed state write had no bounded recovery | no state file; the journal append is the single record, protected from compaction for 62 days |
| 4 | The closing month's cap wasn't reliably captured | no previous-month reconciliation (§3.5 stated limit), so a month's cap is needed only while it is current |
| 5 | An old zone doesn't give old-zone usage | the same: no reconciliation; a zone change mid-month doesn't re-send |
| 6 | The smoke test consumed real warnings | the test cap is an odd value (1.234567 GB), and its own instance leaves real caps eligible |

## 13. Round 4 changes (4 findings, all taken)

| # | Finding | Change |
|---|---|---|
| 1 | Cap changes could send obsolete warnings, or lose them on A → B → A | at send time, `data_cap_now()` gives the current month and cap. Other caps' items are held (not sent, not dropped) and sent if that cap returns this month. Past months are dropped. At most 12 per queue, oldest held dropped first |
| 2 | Telegram clips title and body together | `body_limit(channel_type)` reserves 300 characters for Telegram's tag and title; a test checks the real outbound payload of each clipped service |
| 3 | An oversized event could block the queue | `event_item` clips every line to 300 characters; the fitter skips a misfit and carries on |
| 4 | The deploy baseline read a field the old build lacks, and the synthetic crossing assumed enough usage | baseline reads only the cap; the lower bound is read after the upgrade; the synthetic test is skipped under 2 GB counted; a `trap` restores the cap on failure |

## 14. Changes after the code reviews (PR #339)

| Source | Finding | Change |
|---|---|---|
| Security review, LOW | Carrying every unshown event over to the next message turned a burst of 500 new MACs into about 50 one-a-minute messages, half the channel's daily budget; F1 sent one "and N more" | §4.3 narrowed: only unshown **data cap** warnings wait for the next message (they are at most 12 a queue). Other events a message didn't show are counted in its "and N more", as in F1 |
| Security review, LOW | The deploy check's test warnings could reach a real channel if a dispatcher poll fell inside the test window | §8 step 4 runs only when no notification channel is set up, and checks the month's format |
| Web review, MEDIUM | "At least" rounded half up, so 82.46 GB read "at least 82.5 GB" | the card and the warning floor an "at least" figure to 0.1 GB |
| Web review, LOW | Edits during a save were overwritten; `Number()` took "0x10" and refused "1,200"; a non-string error read "[object Object]" | the input is disabled while saving; the GB field takes digits with commas; the error text must be a string |
| `/ponytail-review` | A ledger begun on the 1st read "counted since 1 Nov"; a failed cap restore in the deploy check wasn't retried | "counted since" only after the month's first day, as on the card; the restore keeps its trap until it succeeds |
