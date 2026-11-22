# Plan: roadmap #1, the weekly report (NET-340)
_Round 5 - final. Codex round 5 (1 blocker, 1 correction) applied by Claude; MAX_ROUNDS reached, so these two changes are not Codex-reviewed_

Roadmap: `plans/2026-11-18-feature-roadmap.md` §8 "#1: Weekly summary report", decision D6. Depends on F1 (#336), F4 (#337/#338), #6 (#339) and #5 (#343), all merged. Base: `main` at `ba4a3178`.

## 1. Goal

The owner gets a plain-text email once a week and a Reports page. Both say, in plain English, what the network did over the last full week:

- internet used;
- alerts per day and the worst few;
- devices seen for the first time;
- when watched devices went offline and came back;
- the month to date against the data cap.

Every section states its own coverage, so a short or broken history is never shown as a full, quiet week. The placeholder generator (zeros, plus made-up "compliance 100" and "risk low" sections) goes.

## 2. What already exists (facts the plan is built on)

- **`daemon/services/report_generator.py`**
  - `ReportSchedule` (:22-38): `id` (uuid4), `name`, `frequency` (daily|weekly|monthly), `format`, `recipients`, `sections`, `enabled`, `last_run`, `next_run`, `created_at`.
  - `_load` (:69-89) runs `ReportSchedule(**data)`. An unknown field empties `_schedules`, and the next `_save` overwrites the file. `_save` is not atomic and doesn't set mode 600.
  - `_compute_next_run` (:108) drifts. `generate_report` (:272) runs on the event loop.
  - All five section generators are placeholders, and nothing runs or sends.
  - Old schedules default to `enabled: True` with unchecked recipients. The old generator ignores unknown section names (:297).
- **`daemon/api/reports.py`**: 8 routes.
  - POST with a non-object body gives a 500.
  - PUT supports partial updates via `update_schedule(id, **body)`, mutating the live object before saving.
- **F1** (`services/scheduled_jobs.py:37`): `Job(name, label, every_s, deadline_s, run)`.
  - `run(deadline)` gets an *absolute* monotonic deadline, cooperative only.
  - 2 shared executor slots.
  - `storage/snapshot_search.py:48` has `Budget`/`checked`/`TooSlow`.
  - The route pool (`api/offload.py`) has 8 workers shared by every `@in_thread` route.
- **Atomic writes**: the repo's helper (`capture_config.py:245-263`) fsyncs the temp file and renames it, but doesn't fsync the directory.
- **Event journal** (`services/event_journal.py`): `events.jsonl` (mode 600), records `{seq,id,type,key,observed_at,recorded_at,data}`, appends deduped by `id` (:184).
  - One lock serves producers, the dispatcher and readers.
  - Compaction keeps unread entries, so the file has no hard line ceiling.
  - Only `after(seq, limit)` reads, plus `_read_all` (the whole file in memory, under the lock).
  - Types:
    - `new_device`: key MAC, `instance=""`, so one entry per MAC; `observed_at` = first seen.
    - `device_offline`/`device_online`: key MAC, instances `down|<seen_at>` / `up|<seen_at>`; data `{mac, name, after_min, seen_at}` plus `back_at, away_min` for online; `observed_at` = detection time.
    - `data_cap`: data `{month, used, cap, threshold, …}`.
- **Watched devices**: `WatchedDevices.view()` (:476) gives the current list and state. It has no history and no `enrolled_at`.
- **Device registry**: `get_devices(macs)` (:522) is a full-source `mget` with no timeout argument; `get_display_name()` is :899.
- **Usage ledger (F4)**
  - `usage_report.daily(snapshot, first, last, now, rules, owner)` (:93) is exactly `/api/usage/daily`.
  - A past day reads `counted` without comparing its `cutoff` to the day's end (:55-76).
  - `daily().bytes` sums every row with figures, including rows counted under old exclusion rules.
  - `_lower_bound(rows, snapshot, rules)` (:159) sums only days counted under the current rules (#6 uses it).
  - `ledger.snapshot()/now()/current_rules()` are in-memory.
- **Data cap**: `tracker.get_cap()["monthly_cap_bytes"]` holds only the current setting.
- **Alerts**
  - The Alerts page KPI is `GET /api/alerts/count` (`api/alerts.py:820`): `alert_query(from, to, activity)` (:198; the range is `gte`/`lte`, :182-193), `track_total_hits: true`, and a terms agg on `suricata.alert.severity`.
  - **On the G11 Suricata indexes only alerts** (24 h: 117,995 `event.dataset: alert`, nothing else).
  - `date_histogram` misplaces records on the G11's OpenSearch 3.5; `storage/time_slots.py` uses `date_range` instead.
  - The shared client's `with_exact_terms` (`storage/exact_terms.py:21`) raises any `terms` shard size to at least 10,000.
  - `_every_key()` (`api/alerts.py:1136`) does exact composite paging of one field under `alert_query` (cap 50,000 keys) and returns `complete`; `SEVERITY_AGG` and `_primary_severity` sit beside it.
  - `get_smart_alerts` walks up to 500,000 groups whatever its `limit`.
  - `rule_explainer.explain_name(name, severity)` (:434) gives `{family, what, risk, todo}` from a rule name.
  - `StorageManager` lists indices via `_cat/indices` (`storage/manager.py:345`).
- **Email**
  - `NotificationHub._smtp_send(...)` (:801) is sync and returns refused recipients.
  - `_send_email` (:696) tags severity and falls back to the Settings › API keys SMTP settings.
  - `_is_address` is `notification_config.py:119`.
- **Backups**
  - A section registry: `config_backup._VALID_SECTIONS` :109, and `backup_checks` LABELS/SECTION_FILES/_SECTION_CHECKS :36-63, :291.
  - `backup_notifications.py:156-174` restores unfamiliar destinations turned off, with a warning.
  - An older daemon given an unknown section at the same schema version **warns, skips that section and applies the rest** (`config_backup.py:374-401`, test `test_config_backup.py:293-304`).
- **Web**
  - `web/src/lib/api/reports.ts`: 8 helpers that swallow errors. Only its test imports it.
  - 5 proxies under `routes/api/reports/` (10 s default).
  - `settings/tabs/NotificationsTab.svelte`. `DataCapCard.svelte` is the card model.
  - `NAV_GROUPS` (`shell/nav.ts:38`); `changelog/+page.svelte` is the page model.

## 3. Approach

### 3.1 The period: whole local days in the ledger's zone

A report covers a completed period of whole local days in the ledger's zone (`ledger_tz`):

| Frequency | Period | Sent |
|---|---|---|
| weekly (default) | the 7 days before the send day | chosen weekday, chosen hour |
| daily | the day before | every day at the hour |
| monthly | the previous calendar month | the 1st at the hour |

- **A period's identity is its local dates `(first, last)`.** Its instants come from `usage_days.day_bounds`.
- **Every query is `[start, end)`.** Queries built on the shared inclusive helpers pass `to = end − 1 ms`. `@timestamp` is a millisecond `date`; the deploy script asserts the mapping.
- **Whole days make the traffic figure match `/api/usage/daily` byte for byte.** The hour only sets when it's sent (default 08:00).
- **One zone for every schedule.** The card shows it.
- **Skipped and repeated hours:** a send hour skipped by daylight saving uses the first valid instant after it. A repeated hour uses its first occurrence (`fold=0`).

### 3.2 Schedules, the sidecar, consent and the watermark

- **`report_schedules.json` keeps exactly today's fields and values the old code accepts.**
  - New schedules store `format: "json"` and `sections: ["traffic_summary","alerts","devices"]`.
  - `last_run` and `next_run` are kept truthful.
- **New state goes in `report_schedule_meta.json`**, keyed by id: `{weekday, hour, card, rev, confirmed_digest|null, last_period: {first,last}|null, claim|null, last_delivery|null}`.
- **Consent is explicit and bound to what was reviewed.**
  - A POST/PUT confirms only when its body has `"confirm": true`. The card always sends it; a name-only or old-client PUT never does.
  - Confirming stores `confirmed_digest = sha256(canonical JSON {recipients (exact validated strings, sorted, case preserved: a local part can be case-sensitive), sections (the stored legacy field, as is), frequency, weekday, hour, enabled, contents: "v1"})`. `contents: "v1"` names the five sections, so new contents later need a fresh confirmation. Because the stored `sections` field is in the digest, narrowing a schedule on an old daemon during a rollback pauses it after the upgrade.
  - **A confirmation must name exactly what was shown.** Every schedule reply carries `confirm_token = sha256(id | rev | consent digest of the settings as stored right now)`, the same canonical JSON as `confirmed_digest`, computed from the files and not from the sidecar alone. A confirming PUT or card upsert must send the token it was shown. Under `_state_lock` the server recomputes it from the current stored settings and returns 409 "These settings changed in another window. Reload and check them." on any mismatch. An old daemon's recipient edit during a rollback changes the digest, and a replaced card schedule changes the id, so neither can be confirmed by an outstanding request. A non-confirming edit still uses `rev` for ordinary conflict checks.
  - **A schedule runs only while the digest of its current configuration equals `confirmed_digest`**, and that's checked again under the claim (§3.3). Any change made without confirming leaves the schedule paused (`needs_review: true`), never sending to new destinations: an old daemon's edit during a rollback, a restore that stopped between the two files, a hand edit.
  - Legacy and restored schedules have no digest, so they never run until confirmed.
- **Every mutation goes through the live generator:** create, PUT, the card upsert, DELETE, the existing `POST …/enable` and `…/disable` routes, and backup restore. Each takes `_state_lock`, bumps `rev`, and is refused with 409 while a claim is active if it touches recipients, `enabled`, cadence or existence. A blocked restore gets a section error ("A report is being sent. Try the restore again in a minute.").
- **Restore order:** first a durable sidecar write that clears every affected schedule's `confirmed_digest` and bumps its `rev` (so an in-flight generation's recheck fails), then the schedules file. A restore interrupted between the two writes leaves schedules paused, never confirmed against new data.
- **Off the event loop:** request bodies are parsed on the loop; every generator call (each takes `_state_lock` and may do durable writes) runs in `asyncio.to_thread`, so a slow disk write can't stall `/api/health` or other pages.
- **`last_period` is a monotonic watermark of the last period attempted.** It never moves backwards.
  - Only an actual transition moves it: unconfirmed → confirmed, disabled → enabled, or a real change of frequency, weekday or hour. Then it becomes the later of `last_period` and the latest boundary's period (compared by `last`). A Save that changes nothing (the card always sends `confirm: true`) doesn't touch it, so it can't swallow a report that's due before the next tick.
  - So a delivered week can't come round again. Example: sent Monday 08:00, hour changed to 18:00 at 09:00. At 18:00 the boundary's period equals the stored one, so nothing is due.
  - A ledger-zone change keeps local dates, so it can't re-send.
- **The loader:**
  - keeps known fields only;
  - treats a file it can't parse, or one with an entry whose id isn't uuid4 or whose types are wrong, as **unavailable**: writes refused (503), the file left untouched;
  - writes both files with a durable atomic write: fsync the temp file, `os.replace`, fsync the directory, at mode 600.
- **One resolver, `schedule_dir(id)`**, validates the uuid4 pattern and returns `REPORTS_DIR/<id>`. Every read, list, write, prune and delete goes through it.
- **The Settings card manages a server-side singleton.** `PUT /api/reports/card` upserts it under `_state_lock`: it finds the one schedule with `card: true` or creates it (weekly, "Weekly report"). Two first saves from two tabs therefore make one schedule; the second gets a 409 if its `rev` is stale. Restore keeps at most one `card: true` (the first) and clears the flag on others. Other schedules are API-only.

### 3.3 Running, claiming and sending

- **Two locks:**
  - `_gen_lock`: one generation at a time, taken without blocking.
  - `_state_lock`: short; guards the in-memory schedules and sidecar and every file write. CRUD takes it.
- **The F1 job:** `Job("weekly-report", "Scheduled reports", every_s=300, deadline_s=240, run=report_generator.run_due)`. `run_due(deadline)`:
  1. **Recover** any claim left without a result (below).
  2. If `_gen_lock` is busy (a manual run), return.
  3. Pick **one** due schedule per tick:
     - enabled;
     - digest equal to `confirmed_digest`;
     - the latest boundary's period `last` later than `last_period.last`.

     Other due schedules wait for the next tick.
  4. Snapshot the schedule (with `rev`). Generate with one absolute monotonic deadline, `gen_deadline = min(deadline − 30 s, monotonic() + 180 s)`, passed to every section, request, scan and lock wait (§3.4).
  5. Under `_state_lock`, recheck: the schedule exists and is enabled, its digest matches, and `rev` is unchanged.
     - If not, discard the report. The next tick regenerates it if the period is still due.
     - If so, write the report **staged** (`<report_id>.json.staged`, which history and pruning ignore), take the current recipients, and save the claim `{claim_id, first, last, report_id, recipients, at}` with `last_period = {first, last}` in one durable sidecar write. **Any failure in that write means zero SMTP attempts.** Only then is the staged file renamed to `<report_id>.json` (with a directory fsync).
  6. **The claim is the send commitment.**
     - While a claim is active, a PUT that changes recipients, `enabled`, frequency, weekday or hour, or a DELETE, returns 409 "A report is being sent. Try again in a minute." Name-only edits are allowed.
     - The email goes to the claimed recipients.
     - Then, under `_state_lock`, only the matching `claim_id` is finalised, in this order: (1) the terminal result plus `claim_id` is written durably into the report file; (2) the sidecar gets `last_delivery` and the claim is cleared.
- **Recovery** (on load and at the start of each tick): first, a `.staged` file whose `report_id` matches the active claim is renamed into place, and any other `.staged` file (a crash before its claim) is deleted, so a crash at any boundary leaves at most one visible report per period. Then, for a claim still in the sidecar, read its report file. If the report holds a result with the same `claim_id`, copy it to `last_delivery` and clear the claim. Only when there is no durable result does it become `last_delivery: {result: "unknown", at: claim.at}`, with the report reading "Unknown: NetTap stopped while sending". The period is never re-sent (no retries, by design).
- **Generate now** (`POST /api/reports/generate/{id}`, `@in_thread`):
  - If `_gen_lock` is busy, it returns **409 at once**: "A report is being generated. It will appear in the history when it's done." It never waits, so at most one route worker is held.
  - Otherwise it generates the latest completed period with an absolute deadline of `monotonic() + 45 s`; sections past it come back `partial`.
  - Then, under `_state_lock`, it publishes only if the schedule still exists and `rev` is unchanged. Otherwise it returns 409 "The schedule changed while the report was being made".
  - It stores the report with `trigger: manual` and returns it. It doesn't email, and doesn't touch `last_run`, `next_run`, `last_period` or a claim.
  - Any schedule, confirmed or not, can be generated by hand.
- **Report files:** `schedule_dir(id)/<report_id>.json`, with `report_id = YYYYMMDDTHHMMSSZ-<6 random hex>`.
  - Atomic, mode 600, directories 700.
  - The newest 12 are kept.
  - DELETE removes the directory under `_state_lock` (refused with 409 during a claim).

### 3.4 Sections

Each section returns `{status: ok|partial|unavailable, coverage, …}`. A failing section never fails the report.

- **Pinning.** One `ledger.snapshot()`, `ledger.now()`, `current_rules()` and owner zone are read once per report and used by every section.
- **Budgets and transport.** Every OpenSearch request goes through a `Budget` derived from the absolute deadline and uses **a no-retry client**, built like F4's (`ExactTermsOpenSearch(**storage.client_kwargs(max_retries=0, retry_on_timeout=False))`, `server.py:1429-1432`). That covers the searches, the ranking pages, the index inventory and enrichment, so a slow 502/503/504 can't be retried past the deadline.

1. **Internet use**: `daily(pinned…, first, last)`. Two figures from the same rows:
   - **Total** = `daily().bytes` (download, upload and total; local separately). It equals `/api/usage/daily?from=first&to=last`, and reads "provisional" when any day isn't covered.
   - **Counted under the current rules** = `lower_bound(rows, snapshot, rules)` (`_lower_bound` made public). It's never too high after an exclusions change. Any "at least" wording uses only this figure.
   - A day is *covered* when `status == counted`, its rules are the current rules, and `cutoff ≥ end`. Coverage reads "N of 7 days counted".
   - The busiest day shows only when at least one day has figures. With none: "No usage was counted for this week."
   - **No `get_daily_usage` fallback.** That's a trade-off: F4 can count raw local days, but ledger-only keeps exact parity with Bandwidth and costs nothing on the G11.
2. **Alerts**, in three parts, so exact figures never depend on the optional ranking:
   - **Totals and days (one search):** `alert_query(start, end − 1 ms)` (counted, `activity=False`), `size: 0`, `track_total_hits: true`, with two aggregations:
     - `by_severity`: the endpoint's own terms agg, so alerts without a severity still count in `total`;
     - `per_day`: a **`date_range`** with one range per **local** day, bounds = that day's UTC `day_bounds()`.

     Totals equal `/api/alerts/count?from=start&to=end−1ms&activity=false`, and each day equals one range filter.
   - **Worst five (optional):**
     - `all_buckets(client, NETWORK_INDEX, alert_query(start, end − 1 ms), [{"key": {"terms": {"field": "rule.name", "missing_bucket": true}}}], {"worst": {"min": {"field": "suricata.alert.severity"}}}, page_size=1000, max_buckets=5000, budget=<the report Budget>, what="weekly report rule ranking")`. `what` makes `all_buckets` check each reply and raise on a malformed page instead of taking it as the last one. That's the same exact composite paging `_every_key` uses, but called directly so the deadline reaches every page and the limits are report-sized.
     - Ranked by the **highest observed severity** (lowest `worst`), then count, top five. The missing-name bucket is included as "Unnamed rule"; a null `worst` reads "Severity unknown" and sorts after severity 3.
     - Each name goes through `explain_name`.
     - Published only when paging completed inside the budget; otherwise "Not included this time" with the reason. The exact totals and days don't depend on it.
     - No `terms` ranking and no `get_smart_alerts`.
   - **Storage coverage:**
     - Reuse F4's budgeted network-index inventory (`UsageLedger._inventory`, `usage_ledger.py:248`; dated names plus min/max bounds for undated indices). It's extracted to a module function both call, with OLD CODE kept.
     - A dated index's interval is built as `[UTC midnight of its date, next UTC midnight)`, not from F4's stored `23:59:59` upper bound; undated indices use their observed min/max bounds.
     - Each local day is **full** (index spans cover all of `[day_start, day_end)`), **partial** (some of it), **absent** (none) or **unknown** (inventory failed or timed out). Observed counts are always kept: a partial day shows its alerts with "Only part of this day is stored".
     - A stored day with 0 alerts reads "No alerts recorded: a quiet day, or Suricata wasn't running". Suricata stores only alerts, so NetTap can't tell those apart.
     - There's no all-history minimum query. The shared `/api/alerts/count` handler is untouched.
3. **New devices**: journal `new_device` entries with `observed_at` in `[start, end)` (from the §3.6 scan).
   - There's one entry per MAC, the same record the notification used, so a registry retry can't move a device to another week.
   - Names for the (at most 50) listed MACs come from `registry.get_devices(macs, fields=…, timeout=remaining)` plus `get_display_name()`. `get_devices` gains optional `fields` (`_source_includes`) and `timeout`, and isn't retried.
   - Vendor and IP come from the entry. If enrichment fails, or the deadline is near, the list shows MACs and vendors and the count stands.
   - **Coverage wording:** "First sightings recorded between <examined range>". NetTap's discovery looks back one hour (`api/devices_v2.py:65`), so a device seen only while NetTap was down for longer isn't recorded; the section says "Devices seen only while NetTap was offline aren't listed" whenever the journal's examined range starts after `start` or the job history shows a gap.
4. **Offline incidents (watched devices)**: transitions recorded up to the **generation time**, so a return at Sunday 23:59 detected at 00:03 still pairs.
   - Pairs are keyed by `(MAC, seen_at)`; both instances carry it. **Pairing happens before any window filter** (§3.6), so a pre-week recovery always closes its pre-week opening.
   - An incident is `[seen_at, back_at)`. It's reported when it overlaps `[start, end)`, clipped to that window.
   - An online entry without its offline entry still gives a full interval.
   - **An unclosed opening is superseded** by any later transition for the same MAC with a later `seen_at` (the device was seen again), and becomes "returned before <later seen_at>, time not recorded". It's dropped if that is before `start`. So an outage abandoned by an unwatch never haunts later weeks.
   - A still-unclosed opening reads "still offline" only when `view()` shows that MAC watched, `state` offline, the same `seen_at`, and `check` succeeded within the last 10 minutes.
   - Without that evidence: an opening whose `seen_at` **or** whose declaration (`observed_at`) is inside the period is reported in that period with "Return time not recorded" (it did reach the week). An opening with both before the period is dropped, because nothing shows it reached the week (a permanent unwatch emits no closing transition). So an outage declared on Monday for a device last seen on Sunday, then unwatched on Tuesday, appears in that week and in no later week without further evidence.
   - Past incidents of devices no longer watched still appear, named from the entry. Coverage reads "Watched devices only".
5. **Data cap**: the month to date as of the period's last day, from `daily(pinned…, month_first, last)` rows.
   - The percentage uses `lower_bound`, as #6 does, so it's never overstated, and carries its **own** coverage: "N of M days this month counted under the current rules". The provisional total shows beside it when they differ.
   - Nothing after the period end is counted, and there's no projection.
   - The cap is labelled "your current cap": past caps aren't stored.
   - `data_cap` entries in the period show their recorded month and cap ("Passed 80% of 1,000 GB on 14 Nov").
   - With no current cap and no entries: "No data cap set".

There's no posture section (D6); the email and page link to Security posture. The `compliance` and `risk` generators are wrapped in OLD CODE markers.

### 3.5 Delivery

- **Email (plain text, D6):** a new `NotificationHub.send_report_email(recipients, subject, text) -> {result: sent|partly_sent|failed|not_configured, refused, error}`.
  - It uses `_smtp_send` with the SMTP settings `_send_email` falls back to, with no severity tag.
  - The subject is built from dates only: "NetTap weekly report: 10–16 November 2026".
  - Network text (device names, vendors, rule names) has control characters and CR/LF removed and is clipped to 120 characters.
  - No recipients means stored but not emailed.
- **Deferred, each with a roadmap amendment in this PR and a Linear follow-up:**
  - **The channel summary** (roadmap line 513: a `report` journal event to Pushover, Discord or Telegram).
    - Doing it properly needs its own consent (off by default, naming which channels get the figures), a durable pending event tied to the claim, digest carry-over in the dispatcher, and a downgrade purge of held report items. That's a slice of its own.
    - The email and the page deliver the feature. A `pending_event` field on the claim leaves room for it.
  - **`GET /api/events`** (F1 note, roadmap :149). Nothing consumes it.
  - NET-340 closes against the amended roadmap. The owner signs off on both deferrals at the plan gate.

### 3.6 Journal scan (bounded by the week, newest first, no long lock)

New `EventJournal.scan(window_start, until, deadline, max_bytes=32 MiB) -> {entries, examined_from, truncated}`:

- **Snapshot.** Under `_lock` (acquired with a timeout from `deadline`), it opens the file and records its committed size, then reads outside the lock up to that size.
  - The descriptor survives compaction's `os.replace`, so the read is consistent.
  - Producers and the dispatcher are never blocked.
- **Newest first.** If the committed size is over `max_bytes`, it starts at `size − max_bytes`, skipping to the next newline. `examined_from` = the first whole entry's `recorded_at` (excluding `data_cap`), and `truncated = True`.
- **Streaming.** It reads line by line, `json.loads` only lines containing a wanted type, and checks the deadline every 1,000 lines.
- **Kept rows are bounded by the week, not by history:**
  - `new_device` and `data_cap` entries only with `observed_at` in `[window_start, until)`;
  - transitions go into a dict keyed `(MAC, seen_at)` as they're read. A pair closed before `window_start` (online entry with `back_at < window_start`) is deleted on the spot; an opening superseded before `window_start` by a later `seen_at` for the same MAC is deleted too. So memory holds only pairs open at, or overlapping, the week.
  - At most 5,000 kept rows per type; hitting that sets `truncated`.
- **One scan per report** serves sections 3, 4 and 5. A truncated scan, or an `examined_from` after `window_start`, marks the affected sections `partial` and shows the examined range.

### 3.7 API (`daemon/api/reports.py`)

- **POST/PUT validation.** Each returns 400 on:
  - a non-object body;
  - `name` not a string of 1–100 characters;
  - `recipients` not a list of at most 10 strings, each passing `is_address` (public alias of `_is_address`) with no CR, LF or comma;
  - `weekday` not an int 0–6, `hour` not an int 0–23, `enabled` or `confirm` not a strict bool;
  - an invalid `frequency`.

  PUT builds a validated copy, swaps it in under `_state_lock`, and bumps `rev`. During a claim, §3.3's 409 applies. `format` is accepted and ignored. **An explicit `sections` field is refused with 400**: "Report emails always contain all five sections (internet use, alerts, new devices, offline incidents, data cap). Leave out `sections`." It's checked before anything is confirmed or saved, so neither a confirming traffic-only POST nor a narrowing PUT can succeed while all five are emailed. The legacy field stays on disk (new schedules store the old default) for rollback. Only `"confirm": true` confirms.
- **The schedule reply adds** `rev`, `confirm_token`, `weekday`, `hour`, `tz`, `next_send`, `confirmed` (digest matches), `needs_review`, `card`, `sending` (claim active), `last_period` and `last_delivery`.
- **`PUT /api/reports/card`:** the singleton upsert (§3.2); same validation; must carry `confirm_token` when the card schedule exists (none when creating it).
- **`POST …/enable` and `…/disable`:** kept, routed through the generator with the claim 409; enabling never confirms.
- **`POST /api/reports/generate/{id}`:** §3.3.
- **`GET /api/reports/history?schedule=<uuid>`:** newest first, without sections.
- **`GET /api/reports/history/{id}/{report_id}`:**
  - `id` must pass `schedule_dir` and `report_id` must match `^\d{8}T\d{6}Z-[0-9a-f]{6}$`; otherwise 404.
  - The path is checked with `resolve().is_relative_to(reports_dir)`.
- **Backups:** a new `report_schedules` section holding the schedules plus sidecar `weekday`, `hour`, `card`, `enabled` and `recipients`. It never holds digests, claims, delivery state or reports.
  - Restore brings schedules back **unconfirmed** and warns: "Report schedules restored paused. Check the recipients in Settings › Notifications and save to turn them on."
  - Touches `_VALID_SECTIONS`, export, restore, `backup_checks`, the `BackupTab` label and the backup tests.

### 3.8 Web

- **`reports.ts`:** helpers throw on failure (old bodies kept in OLD CODE markers); adds `getReportHistory`, `getReport` and the new fields.
- **Proxies:** generate gets 60 s; history goes through the catch-all.
- **New `/reports` page** (Overview, after Bandwidth, icon `logs`):
  - page head: h1 "Reports" plus "Generate now" (409 messages shown);
  - KPIs: Next report, Last sent, Delivery, Days covered;
  - hero: the latest report's five sections with coverage lines;
  - sortable history `DataTable` (Period, Generated, Trigger, Delivery), where choosing a row shows that report;
  - `CardState` everywhere, `registerPageRefresh` with the load guard;
  - empty state pointing to Settings › Notifications.
- **`ReportScheduleCard.svelte`** on Settings › Notifications (the `DataCapCard` pattern), bound to the `card: true` schedule:
  - fields: on/off, weekday, hour, recipients (one per line), Save (sends `confirm: true`);
  - it says what is sent: "Internet use, alerts, new devices, offline incidents and the data cap, as plain-text email to these addresses";
  - "Times are in <zone>";
  - when `needs_review`: "Paused until you check the recipients and save";
  - while `sending`, Save shows the 409 message.
- **Design system:** tokens only, UK spelling, sentence case.

## 4. Key decisions and trade-offs

1. **Whole local days:** exact traffic and one shared `[start, end)` window. The report ends at midnight.
2. **Explicit, digest-bound consent.** Nothing sends unless the current configuration is exactly what was confirmed.
3. **A durable claim before send, a monotonic watermark, no retries.** A crash or power loss means "delivery unknown", never a duplicate.
4. **The claim is a commitment:** destination edits and deletes get a 409 for the seconds a send takes.
5. **Exact figures are separate from the optional ranking.** Totals and days come from one bounded search; the worst five from exact composite paging or not at all.
6. **Storage coverage from index dates.** Suricata continuity is called unknown, because it stores only alerts.
7. **Provisional totals versus current-rules lower bound** for traffic and the cap.
8. **New devices from the journal**; the registry only enriches the listed 50.
9. **Channel summary and `GET /api/events` deferred** by roadmap amendment (owner sign-off at the gate).
10. **"Generate now" returns 409 rather than waiting**, sends nothing and moves nothing.

## 5. Risks and accepted limits

- **G11 memory (swap 91%).** A report is 2 searches plus composite paging of distinct rule names (hundreds) plus a ≤32 MiB streamed scan. The gate in §6 measures it.
- **`explain_name`** knows the ET, abuse.ch and DBL families; other names fall back to the rule name.
- **"No alerts recorded" can't say why.**
- **A schedule edited while it's being generated** discards that run; the next tick regenerates it.
- **The claim's 409** blocks destination edits for the length of one SMTP send (seconds; bounded by the SMTP timeout).

## 6. Verification plan

**Daemon (pytest):**
- **`test_report_generator.py`:**
  - period maths for weekly, daily and monthly, the Europe/London changes, and a send hour inside the skipped hour;
  - one due schedule per tick;
  - three missed boundaries give one report;
  - **consent:** a real legacy file through a tick gives nothing; a name-only PUT on a legacy schedule leaves it paused; a sidecar/schedules mismatch (a downgrade edit, then upgrade) pauses it; an interrupted restore (schedules written, sidecar not) pauses it;
  - **watermark:** hour 08:00→18:00 on send day gives one SMTP attempt; a weekday edit after a send gives no immediate send; a zone change gives no re-send; an unchanged Save between the boundary and the tick doesn't skip the report;
  - **consent token:** a token read at `rev=4`, then an old-daemon recipient edit (sidecar `rev` unchanged), then upgrade: the confirming PUT gets 409 and a tick makes 0 SMTP attempts; a deleted card replaced by a new schedule with the same `rev`: the old token gets 409;
  - **staging:** a crash after the staged write and before the claim, then a tick: exactly one visible report for the period;
  - **transport:** a delayed 503 on a ranking page: one transport attempt, exact totals kept, the worker released before the deadline;
  - **malformed page:** a second ranking page without a bucket list: ranking omitted, counts kept;
  - **permanent unwatch:** a pre-week opening, the watch removed, no later event: 0 incidents the next week; seen Sunday, declared Monday, unwatched Tuesday: one incident that week ("Return time not recorded"), none the week after;
  - **sections:** a confirming POST with `sections: ["traffic_summary"]` and a PUT narrowing `sections` both get 400 and change nothing;
  - **index bounds:** a fully retained non-UTC local day across two dated indices reads full;
  - **consent details:** a case-only recipient change pauses; narrowing `sections` on an old daemon then upgrading pauses (through the first tick); a two-client stale `rev` confirm gets 409; two first card saves make one schedule;
  - **mutation paths:** enable/disable POST and a restore during a paused SMTP send get 409 / a section error; a same-id, same-settings restore interrupted between the two writes leaves the schedule paused;
  - **recovery:** a crash between the report-result write and the sidecar write recovers the real result, not "unknown";
  - **event loop:** with a report-file commit paused, a Settings request is pending and `/api/health` still answers;
  - the old loader (a copy of today's dataclass and `_load`) reads a file written by the new code;
  - an invalid stored id makes the store unavailable with the file untouched;
  - distinct report ids under a frozen clock;
  - 12 kept; mode 600;
  - **durability:** failure injected in the temp write, the replace and the directory fsync each give 0 SMTP attempts; failure after SMTP acceptance and on the result save each give exactly one attempt and then "unknown";
  - **commitment:** with SMTP paused after the claim, a recipient PUT and a DELETE get 409, a name-only PUT succeeds, and only the matching `claim_id` finalises;
  - **manual:** a DELETE just before publication means no directory is recreated and a 409 comes back;
  - `_gen_lock` busy means the job skips and Generate now gets an immediate 409;
  - one absolute deadline reaches the scan, the searches and enrichment, and an expired deadline gives `partial` sections, never a hang.
- **Sections:**
  - traffic: parity with `daily()`; a midnight cutoff isn't covered; an exclusions change that lowers usage gives a provisional total plus a lower "counted under current rules" figure; an empty ledger has no busiest day;
  - alerts: the ranking budget expiring just before page two starts no further request and keeps exact totals; a rule with one high and 100 low alerts outranks five medium rules; an unnamed high alert appears; a local day with one of its two UTC segments stored reads partial with its counts; query bounds `lte = end − 1 ms`; one alert at exactly midnight across adjacent periods; per-day `date_range` bounds across both DST changes; `track_total_hits`; an alert without a severity; `_every_key` incomplete means no ranking; a stored zero-alert day is flagged; a missing middle index gives "Not stored"; a quiet week with intact indices isn't "expired";
  - incidents: a return at 23:59 detected at 00:03; Sunday offline and back Monday 02:00; unwatched while down (superseded later, never haunts); an online entry without its offline; 5,000 closed pre-week outages then one in-week outage; a re-enrolled MAC down again;
  - new devices: the registry-retry fixture across a boundary; enrichment timeout keeps the count;
  - data cap: month rollover with the cap changed or cleared; a delayed report counts no usage after `last`; the percentage uses `lower_bound`.
- **`test_event_journal.py` `scan()`:** a 60,000-line file; 5,000 older matches followed by one new device this week (kept); a file over `max_bytes` (newest kept, `examined_from` set); an append and a compaction during the scan; a lock-wait timeout.
- **`test_reports_api.py`:** a 400 for each of CR/LF or a comma in a recipient, 11 recipients, non-bool `enabled`/`confirm`, and a non-object body (POST and PUT); history traversal and bad ids give 404; PUT doesn't mutate on failure.
- **Email:** the real builder plus `send_report_email` with a monkeypatched `smtplib.SMTP`: envelope recipients, UTF-8 subject and body, partial and total refusal, persisted delivery.
- **Backups:** a round trip; restore comes back unconfirmed with the warning; `section_errors` clean; the new export through the importer with `report_schedules` removed from `_VALID_SECTIONS`, as an older daemon sees it, warns and applies the rest.
- **Wiring:** the server registers the job.

**Web (Vitest):** `reports.test.ts`; the page test (KPIs, hero, empty, error, sort/select, 409 messages); the `ReportScheduleCard` test (binding with a daily schedule listed first; `confirm: true` on save; the `needs_review` note; the `sending` 409); and the `nav`, `notifications-tab` and `BackupTab` updates.

**Visual:** `/reports` populated and empty, plus the card.

**Suites:** pytest, vitest, svelte-check, `check:colors`, `test:visual`, shellcheck.

**G11 (`scripts/remote/deploy-weekly-report.sh`, template format):**
1. **Before anything changes:** `free -m`, the daemon's settled VmRSS (the existing sampler in `deploy-usage-ledger.sh:54-76`), and OpenSearch cgroup `anon`.
   - Record the running daemon and web image IDs **once** in `/home/nettap/.nettap-rollback-net340` **and tag them** `:rollback-net340` before building (as `deploy-live-audit-fixes.sh:48-64` does). A rerun keeps the existing record and verifies the tags still point at it.
   - Build and recreate both, wait until healthy, then 5 minutes for daemon memory to settle.
2. Assert `@timestamp` is a millisecond `date` in the network index mapping.
3. Create schedule "deploy-check" with **frequency weekly, weekday = today, hour 00:00** in the ledger zone (so the latest completed week ends yesterday at any time of day) and no recipients. Keep its UUID; a `trap` deletes it on every exit path.
4. (Representativeness is checked after step 5's single measured run.)
5. Run Generate now, sampling every 2 s: daemon RSS (`docker top`), OpenSearch `anon`, swap used and `/api/health` latency.
   - **✗ (stop for review)** if it takes 30 s or more, health latency passes 2 s, the worst five didn't complete, the daemon's settled VmRSS (same sampler, 60 s after) is more than 50 MB above step 1's, or swap used rose measurably (more than 16 MB, the sampler's noise floor) (roadmap line 75).
   - Peak values are printed.
   - Then the same report is checked for representativeness: its `last` date is yesterday, the alerts section has 7 day rows, and yesterday has more than 0 counted alerts. If not, release verification stays **pending** ("unverified: no representative data"), not passed.
6. **Parity:** traffic bytes equal `/api/usage/daily` for the same dates, and alert totals equal `/api/alerts/count?from=start&to=end−1ms&activity=false`, exactly.
7. History lists the report; the file is mode 600.
8. Print "report email: unverified on device (the check emails no one)".
9. Delete the schedule; its directory is gone.

`rollback-weekly-report.sh` checks that the `:rollback-net340` tags still point at the recorded IDs, then recreates the daemon and web from them.

## 7. Rollback and migration safety

- **The old daemon** loads `report_schedules.json` unchanged. It ignores the sidecar and the reports directory, goes back to placeholder reports, and sends nothing.
  - No journal or dispatcher entries are added by this slice, because the channel summary is deferred, so nothing held can be routed after a rollback.
- **Backups:** a new export restored on an old daemon warns, skips `report_schedules` and applies the other sections (the existing behaviour). Report schedules then have to be set up again by hand.
- **Nothing is migrated in place.** The sidecar is created on first write; legacy schedules stay paused until confirmed.

## 8. Observability

- The job shows in `GET /api/jobs`.
- Each report records `delivery` and each section's status. Each schedule records `last_delivery` (including `unknown`).
- Logs record generation duration, section statuses, scan range and truncation, and the send result (no addresses).

## 9. Out of scope

- The channel summary and `GET /api/events` (deferred, roadmap amended).
- PDF, CSV and HTML email.
- A posture section.
- Per-schedule zones.
- UI for more than the card's schedule.
- Waiting for the last day to be counted.
- Email retries.
- Raw provisional traffic counts.

## 10. Gates

- `/codex-review` (this loop).
- `/deep-review` and `/ponytail-review` before commit (`daemon/api/`, external send, backups).
- The two-angle review before merge.
- One PR (daemon + web + tests + deploy and rollback scripts + roadmap amendment), squash-merged, then `deploy-weekly-report.sh` on the G11.
