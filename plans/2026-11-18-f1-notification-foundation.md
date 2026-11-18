# Slice plan: F1, notification events, the event journal and background jobs (NET-319)

_Roadmap: `plans/2026-11-18-feature-roadmap.md` §8 F1. Branch `feature/f1-notification-foundation` off `ac452991`. Round 1 revision: all 7 Codex findings accepted (see "Round 1 changes" at the end)._

## Goal

After this slice:
- New devices reach the owner on the same channels as alerts, with the same daily limit, retries and digest.
- A durable event journal records each new device.
- A small background-job runner exists that later slices plug into: F4 ledger, #5 watched devices, #6 data cap, #2 internet, #1 report.
- Settings shows the state of each background check and can run one now.

## Delivery guarantee (the failure model)

**An event committed to the journal is never lost while the journal and the event state file (`notification-events.json`) are intact.**

- **Duplicates.** A send is followed by the state saves. A crash between the two repeats that message once on restart, and every further crash at the same point repeats it once more. No receiver offers idempotency, so NetTap promises **no loss, with a possible duplicate per crash**, not "at most twice".
- **Lost event state** (the file is deleted or unreadable while the journal exists): the dispatcher re-reads the journal from the start, bounded to events recorded in the last 24 h. Those may repeat. Older ones aren't re-sent; they stay in the journal for the report. A warning is logged.
- **Rollback, then re-upgrade:** the old dispatcher never touches `notification-events.json`, so queued events and the cursor survive. Events journaled before the rollback but not yet admitted are read on re-upgrade.
- **A channel that keeps failing:** its events stay queued, with retries backing off to every 15 min and refused sends counting against the daily budget as today. They are sent once it works again. The queue is bounded (see the dispatcher section), and overflow is counted and reported in the next message, never silently dropped.

## Changes from the roadmap's F1 text (simpler, same guarantees)

1. **New devices are journaled where the registry already detects them, instead of polling the registry.**
   - `DeviceRegistry.register_device` already knows the exact moment a MAC is first written (`existing is None`, `device_registry.py:287`). That is where it logs `device_joined` to the changelog.
   - The journal append happens **before** the registry document is indexed, and **a failed append skips registering that device** (logged; retried on the next refresh). So a device is never registered without its event. So the journal is the commit point and the registry doc is the producer's state.
   - This drops the polling job, the `registered_at` field and its backfill.
2. **The outbox is the journal plus a sequence cursor.** Each journal line carries a monotonic `seq`. `AlertDispatcher` keeps `journal_seq` (the last seq admitted) and the per-channel event queues in **its own file, `notification-events.json`**, next to the alert state file. The pre-F1 dispatcher rewrites `notification-dispatch.json` with only `cursor` and `channels` (`notification_dispatcher.py:257`), so after a rollback it would erase event state kept there.
3. **Event types are added by the slice that sends them.** F1 sends only `new_device`. `device_offline`/`device_online` come with #5, `data_cap` with #6, `report` with #1. The rule builder already offers only `alert` (NET-224, `NotificationsTab.svelte:193`); F1 adds `new_device` to it.
4. **The jobs endpoints are `GET /api/jobs` and `POST /api/jobs/{name}/run`,** because later jobs (ledger, internet) aren't notifications.
5. **`GET /api/events` waits for #1,** its only caller. The deploy check reads the journal file through `docker exec`.

## Design

### Event journal: `daemon/services/event_journal.py` (new)

- **File:** `/opt/nettap/data/events.jsonl` (env `EVENT_JOURNAL_FILE`), mode 600. Each line is `{seq, id, type, key, observed_at, recorded_at, data}`.
  - `seq` is monotonic. It continues from the last line's seq after a restart. **Compaction always keeps the newest line, whatever its age,** so the high-water seq can never be lost, even when every other line is old enough to drop.
  - `id` is `sha256(f"{type}|{key}|{instance}")[:32]`. `instance` defaults to `observed_at`. `new_device` passes `""`, so a MAC is new once.
- **One writer:** one `threading.Lock` covers append, compaction and load. Registration runs in worker threads.
- **`append(type, key, observed_at, data, instance=None) -> dict | None`:**
  - Returns None when the id is already in the journal: a set of all ids in the file (at most 50,000 × 32 bytes).
  - Otherwise it notes the file size, writes the line plus `\n`, then calls `flush` and `os.fsync`.
  - **If any of that raises,** it truncates the file back to the noted size (`os.ftruncate` + fsync) and raises. So a partial write never sits in front of the next append.
  - On success, the entry joins the in-memory recent window (the last 1,000 entries).
- **Load at startup:** read the file. If the last byte isn't `\n`, truncate to the last `\n`. Skip an unparseable middle line with one warning. Fill the id set, `next_seq` and the recent window.
- **`after(seq, limit) -> list[dict]`:** up to `limit` entries with `seq > seq`, in order.
  - Served from the recent window when it covers `seq`.
  - Otherwise read from the file, so a backlog bigger than the window is paged from disk and never skipped.
- **`compact(now, keep_from_seq)`:** keep lines from the last 120 days, at most the last 50,000, **the newest line**, and **every line with `seq > keep_from_seq`**. It writes them with `write_file_atomic` (mode 600) under the same lock, so no append lands between the read and the swap.
  - `keep_from_seq` is the dispatcher's **committed** seq: the `journal_seq` of the last event state that was saved successfully. It is never the in-memory one.
  - When there is no committed state yet, compaction keeps everything.
- **`existed_at_start`:** whether the journal file existed when it was loaded. The dispatcher uses it to tell a first start from a lost state file.
- `read(type=None, since=None)` is left for #1.

### Notification events in the dispatcher: `notification_dispatcher.py`

- **Intake, every poll:**
  - Read `journal.after(events_state["journal_seq"], 200)`.
  - Admit the entries whose type is in `SENT_EVENTS = {"new_device"}` to each channel the rules route them to. They go into that channel's **event queue** in `notification-events.json`. The alert state and its `pending` list are untouched.
  - Each queued item carries its full title and line, so a sent or queued event never needs the journal again.
  - `journal_seq` moves to the last seq read, in the same atomic write as the event queues.
  - **`_save_events()` returns whether the write succeeded.** Only then does the dispatcher's `committed_seq` (used by compaction) advance. A failed save leaves the old file, so a restart re-reads from the old `journal_seq`, and compaction kept those lines.
  - **No age expiry for events,** unlike alerts' one-hour catch-up.
  - Unrouted types, and events nobody is routed for, just advance the cursor; they stay in the journal for the report.
  - A backlog over 200 is read over the following polls.
- **Bounded batches:** a message carries the channel's alerts (the existing ≤ 50 candidates) plus its queued events.
  - The `events` queue holds at most 500 per channel. Beyond that, the oldest are folded into an `events_overflow` count, which the next message reports ("and 37 more events not listed; see NetTap"). They are counted, never silently dropped.
- **No event state file:**
  - **First start** (the journal file didn't exist either): start at seq 0. The journal is new in F1, so everything in it is genuinely new, including devices discovered before the first poll. There is no baseline to take and no startup race.
  - **Recovery** (the journal exists but the event state is missing or unreadable): read the journal from the start, limited to events recorded in the last 24 h (the failure model above).
- **Saves after a send:** the alert state (`notification-dispatch.json`, as today), then the event state. A crash between them repeats the events, never loses them, because neither file is saved before the send.
- **Routing per item:** `cid in hub.channels_for(item.get("event", "alert"), severity)`. Saved items without `event` are alerts, so old state keeps working. The "nothing routed for alerts" early return in `_new_items` stays alert-only. Targets = channels routed for any alert or event, plus channels with queued alerts or events.
- **Success** clears the sent events and `events_overflow`.
- **Failure:**
  - Events get `attempts + 1` and **stay queued with no give-up**. The delay is `RETRY_AFTER[min(attempts, 3) - 1]`.
  - Alerts keep today's give-up after 3 retries.
  - A refused send counts against the budget as today.
- **`digest()`:**
  - An all-alert list keeps today's exact title, lines and footer, so existing tests pass unchanged.
  - An event renders its own `line`, and a single event uses its own `title`.
  - A mixed list is titled "<n> new notifications (worst: <level>)", with the footer "Open NetTap for details."
- **Unchanged:** the daily budget, the hourly slow digest, alert retries, `done` and `KEEP_DONE`. Events count against the budget like alerts.
- **`new_device` content:**
  - Severity 3 (medium).
  - Title: "New device: <vendor or MAC>".
  - Line: "New device <MAC> (<vendor>) at <IP>, first seen <time>".

### Registry producer: `device_registry.py`

- `DeviceRegistry(..., journal=None)`.
- In the new-device branch, **before** `self._client.index(...)`:
  ```python
  journal.append("new_device", mac, doc["first_seen"], {mac, ip, vendor, source}, instance="")
  ```
- **A failed append skips this device only:** it is logged at error level, the device is **not indexed**, and `register_device` returns without raising. Raising would abort the whole pass, because the conn path in `devices_v2.py:170` has no per-device try, so every later device would miss its `last_seen` update. No caller uses the return value. The device stays unregistered and is retried on the next refresh, so registration never commits without its event.
- An index failure after a successful append raises as today. The next refresh's append is a no-op (same id), and the index retries.

### Rule on/off and the quick toggle: `notification_config.py`, `notification_hub.py`

- **Rules gain an optional `enabled` flag** (default true). `_matching_rules` skips `enabled is False`.
- **Quick settings gain `new_device: bool`,** backed by the fixed rule `settings-newdevice` (event `new_device`, min severity 4, channels = the quick channels).
  - **Absent** means never set, so the view shows it on (D1).
  - **Off** is the rule kept with `enabled: false`.
- **Deleting `settings-newdevice`** (rules list or API) is turned into `enabled: false`. So a delete can't re-enable it after a restart.
- **Default on for existing installs:** at hub load, if a quick channel exists and `settings-newdevice` is absent, add it enabled and commit once. A backup restore runs the same seeding.

### Background jobs: `daemon/services/scheduled_jobs.py` (new)

- **`Job(name, label, every_s, deadline_s, run)`** (frozen dataclass). `run(deadline: float) -> dict | None`, where `deadline` is a `time.monotonic()` value. Returning `{"partial": True}` reports a partial run.
- **`Scheduler(jobs, state_path, workers=2)`:** one cleanup_ctx task ticks every 30 s.
  - **Due:** `now - last_run >= every_s`, or a "run now" request.
  - **No overlap:** a due job that is still running is not started, and `skipped_overlaps` is incremented.
  - **Bounded:** at most `workers` running, on a dedicated `ThreadPoolExecutor(workers)`, never the default pool. A due job with no free slot waits for the next tick.
  - **Slot lifetime:** the running entry is removed in the future's done-callback, when the thread has really returned. A run past `deadline_s` keeps its slot and shows `running_for_s` and `overdue: true`. Its eventual end is recorded normally.
- **State** in `/opt/nettap/data/scheduled-jobs.json` (env `SCHEDULED_JOBS_FILE`), written atomically after each run.
  - Per job: `{last_run, last_duration_ms, last_error, partial, skipped_overlaps, rss_mb_before, rss_mb_after, peak_rss_mb}`.
  - RSS values come from `/proc/self/status` (VmRSS, and VmHWM for the peak); None off Linux.
  - Loaded at start, so a restart doesn't rerun a daily job early.
- **`POST /api/jobs/{name}/run`:**
  - Marks the job due and wakes the tick. 202 when accepted; 409 when it's already running; 404 for an unknown name.
  - It never runs a job outside the scheduler's admission, so the slot and overlap rules still apply.
  - Same daemon-token auth as every route. From #3 on it is admin-only, since viewers can't make non-GET calls.
- **F1's only job:** `journal-compact`, daily, deadline 60 s. It passes the dispatcher's `journal_seq` as `keep_from_seq`.
- **`GET /api/jobs`:** returns `{jobs: [{name, label, every_s, last_run, last_duration_ms, last_error, partial, running, running_for_s, overdue, skipped_overlaps, rss_mb_before, rss_mb_after, peak_rss_mb}]}`.

### Web

- **`NotificationsTab.svelte`:**
  - `ruleEventTypes` = alert + new device.
  - The rule list shows "off" for `enabled === false`.
  - A new "Background checks" card: a sortable `DataTable` of `/api/jobs`, a "Run now" button per row, and `CardState` for loading, empty and error.
- **`NotificationPrefsCard.svelte`:** a "Tell me about new devices" checkbox, saved with the rest.
- **API client** (`web/src/lib/api/notification-hub.ts`): `getJobs()`, `runJob(name)`, and `new_device` on the quick-settings type.
- **Copy:** sentence case, `…`, no emoji.

## Tests

- **`test_event_journal.py` (new):**
  - stable ids, and `new_device` deduplicated per MAC across a restart;
  - `seq` continues after a restart;
  - a torn tail is truncated at load;
  - **a failed write is truncated back** before the next append;
  - an unparseable middle line is skipped;
  - `after()` within the window, beyond it (from disk, a 1,500-entry backlog) and with a limit;
  - compaction keeps 120 days / 50,000 lines, **every line after the committed seq, and the newest line**;
  - consume, compact everything old, restart, append: seq continues and the event is delivered;
  - **concurrent compaction and appends** (threads) lose nothing;
  - the file is mode 600.
- **`test_notification_dispatcher.py`:** all existing tests unchanged. New tests:
  - a journal event becomes a queued event routed by the `new_device` rule;
  - first start (no journal file) delivers from seq 0, including **an event appended before the first poll**;
  - recovery (journal present, no event state) delivers the last 24 h only;
  - **rollback**: an event queued in `notification-events.json`, then the old alert-only state rewrites `notification-dispatch.json`, then F1 again: the event is still delivered;
  - **a failed event-state save** keeps `committed_seq`, and compaction keeps the lines; after a restart nothing is lost;
  - a backlog of 1,000 events over several polls, none lost;
  - recovery after 2 h of downtime delivers everything;
  - overflow over 500 is counted and reported;
  - a mixed alert and event backlog: alerts' 50-cap behaviour unchanged, and no event displaces an alert;
  - **events never give up** after repeated failures, then send when the channel works;
  - **repeated crash boundaries** (send OK, state not saved, three times): no loss, one duplicate per crash;
  - events count against the daily budget;
  - an old state without `event` loads as alerts;
  - mixed digest wording.
- **`test_device_registry.py`:**
  - a new MAC appends before index;
  - **a journal failure leaves the device unregistered without raising**: the rest of the pass continues, and the next registration journals and indexes it;
  - an index failure, then a retry, gives one event;
  - a known MAC appends nothing.
- **`test_notification_config.py` / `test_notification_hub.py`:**
  - an `enabled: false` rule is skipped;
  - quick `new_device` on, off and absent;
  - the load-time seed respects off and is idempotent;
  - **deleting `settings-newdevice` disables it**, and it stays off after a reload.
- **`test_scheduled_jobs.py` (new):**
  - overlap is skipped and counted;
  - a hung job keeps its slot and is shown overdue;
  - at most 2 run together;
  - partial is reported;
  - state survives a restart;
  - a daily job doesn't rerun after a restart;
  - run-now goes through admission (409 while running).
- **`test_jobs_api.py` (new):** `GET` shape; `POST` 202, 404 and 409.
- **Web (Vitest):**
  - `notifications-tab.test.ts`: new device offered, the hidden types not offered, the jobs table, run now, error state;
  - the prefs card: the toggle is saved;
  - `notification-hub.test.ts`: `getJobs` and `runJob`.
- **Full runs:** `cd daemon && python -m pytest`, `cd web && npx vitest run`, `npx svelte-check`, `npm run check:colors`, `npm run test:visual`.

## Gates

`/deep-review`, required because the slice touches `daemon/api` and is over 200 lines; `/ponytail-review` before commit; the two-angle review before merge.

## Deploy and G11 check: `scripts/remote/deploy-notification-foundation.sh`

1. **Before the rebuild:** record `free -m` (used memory and used swap) and `docker stats --no-stream` memory for `nettap-storage-daemon` and `nettap-web`.
2. Pull `main`, rebuild the daemon and web, recreate both containers, and wait until healthy. Allow 2 min to settle.
3. **Forced run:** `POST /api/jobs/journal-compact/run`. While it runs, sample the daemon's VmRSS every 0.5 s (`docker exec … cat /proc/1/status`). Poll `GET /api/jobs` until `last_run` is newer than the request (60 s limit). Assert `last_error` is null. Print the sampled RSS peak, `rss_mb_before` and `rss_mb_after`, with VmHWM as supplemental evidence.
4. **Memory compared with step 1:** the daemon and web container memory, total used memory and used swap.
   - ✗ if a container grew by more than 50 MB (the roadmap's stop rule).
   - ✗ if used swap grew by more than 5% of its baseline.
   - ✗ if the forced run took over 60 s.
5. Through `docker exec`:
   - the journal file exists (once there is an event), is mode 600 and every line parses;
   - `notification-events.json` exists with `journal_seq`;
   - the alert state `notification-dispatch.json` still has `cursor`.
6. `GET /api/notifications/config` shows `new_device` on when a quick channel exists.
7. The last 3 journal lines (no secrets in them: MAC, IP, vendor).

A real new device on the LAN is checked when one appears: one journal line and one "New device" entry in `/api/notifications/log`, with no repeat after a restart.

## Risks

- **This is the alert path.** The existing dispatcher tests must pass unchanged, and an all-alert digest stays byte-identical.
- **A registry reset would make every MAC new.** The dispatcher sends them as digests, one message per channel per poll, within the daily budget; overflow beyond 500 queued is counted.
- **A journal write failure now blocks new-device registration.** That is deliberate: the journal is the commit point. The refresh logs it, and the device is retried every refresh.
- **The id set holds up to 50,000 × 32-byte ids,** about 3 MB of Python strings at the cap. It is small today: there are tens of devices.

## Round 2 changes (Codex)

1. Compaction always keeps the newest line, so the seq high-water mark survives. Test: consume, compact everything old, restart, append, delivered.
2. Compaction uses the committed seq: the last successfully saved event state. `_save_events()` reports success. Test: a failed save, then compaction, then restart, loses nothing.
3. Event state lives in its own `notification-events.json`, which the pre-F1 dispatcher never rewrites. First start is "no journal file", so there is no baseline and no startup race. Test: an F1 event queued, an old-dispatcher poll rewrites the alert state, re-upgrade, the event is still delivered.
4. The deploy check records memory and swap before the deploy, samples VmRSS during the forced run, and compares after.

## Round 1 changes (Codex)

1. A failed journal append now fails the registration, and a partial write is truncated back.
2. Migration (state without the key) starts at the journal's end taken at construction, before producers start. Recovery (no state file) re-reads 24 h.
3. Intake pages by `seq` from disk when needed. Events have no age expiry. Compaction keeps unread lines.
4. Events have their own per-channel queue with no 50-cap displacement and no give-up. Overflow beyond 500 is counted and reported.
5. The guarantee is restated as "no loss, a duplicate per crash between send and save", with repeated-crash tests.
6. Deleting `settings-newdevice` disables it.
7. The deploy forces a run through the scheduler (`POST /api/jobs/{name}/run`) and checks a fresh `last_run`, the duration and the VmHWM change.
