# NET-340: the weekly report

**Date:** 2026-11-21 · **Branch:** `feature/weekly-report` · **Status:** merged in PR #351 (`c479940e`) and deployed on the G11 on 2026-11-22

Roadmap #1 (`plans/2026-11-18-feature-roadmap.md` §8, decision D6). Every week the owner gets a plain-text email and a Reports page saying, in plain English, what the network did over the last full week:
- internet used;
- alerts per day and the worst few;
- devices seen for the first time;
- when watched devices went offline and came back;
- the month to date against the data cap.

Every section states its own coverage, so a short or broken history never reads as a full, quiet week. The old placeholder generator (zeros, a made-up "compliance 100" and "risk low") is gone.

**Plan:** `plans/2026-11-21-weekly-report.md`.
- `/codex-review` ran 5 rounds and reached `MAX_ROUNDS`. The round-5 blocker and correction were applied but not re-reviewed by Codex.
- The owner approved the plan on 2026-11-21, including both deferrals.

**Build contract:** `plans/2026-11-21-weekly-report.contract.md` (file ownership and JSON shapes). Three builders worked in parallel: daemon state, daemon sections, and web.

## What changed

### Daemon: schedules, consent, sending (`services/report_generator.py`, new `services/report_schedule.py`)

- **Periods.**
  - A report covers whole local days in the usage ledger's zone. Weekly is the 7 days before the send day, daily is the day before, monthly is the previous month.
  - Queries are `[start, end)`, so the traffic figure matches `/api/usage/daily` byte for byte.
  - A send hour skipped by a clock change sends at the change itself.
- **Files.**
  - `report_schedules.json` keeps only today's fields, so an older daemon still reads it.
  - New state lives in the sidecar `report_schedule_meta.json`: weekday, hour, card, rev, confirmed digest, watermark, claim and last delivery.
  - Both files are written durably (temp-file fsync, replace, directory fsync, mode 600).
- **Consent.**
  - A schedule emails only while the sha256 digest of its current settings equals the digest the owner confirmed. Confirming takes `confirm: true` plus the `confirm_token` the owner was shown.
  - A legacy, restored or half-written schedule stays paused until confirmed.
  - Writes go sidecar first, then schedules. The digest covers both files, so a half-finished change pauses the schedule.
- **Sending.**
  - A durable claim is written before any SMTP attempt. A crash means "delivery unknown", never a second email.
  - A monotonic watermark (`last_period`) means a delivered week never comes round again, even after an hour or weekday change.
  - While a claim is active, changes to recipients, cadence or existence get a 409.
- **Job and manual runs.**
  - F1 job `weekly-report` runs every 300 s with a 240 s deadline and makes one report per tick.
  - "Generate now" answers 409 at once while another report runs. It sends nothing and moves nothing.
  - The newest 12 reports are kept per schedule.

### Daemon: contents (new `services/report_sections.py`, new `services/report_text.py`)

- **Internet use:**
  - the ledger's own daily rows, so the figures equal Bandwidth;
  - a provisional total, plus a "counted under the current rules" lower bound;
  - "N of 7 days counted".
- **Alerts:**
  - exact totals and per-local-day counts from one search, using `date_range` because `date_histogram` misplaces records on the G11's OpenSearch 3.5;
  - the worst five via exact composite paging, or "Not included this time";
  - storage coverage per day from the network-index inventory.
- **New devices:** from the event journal's `new_device` entries. The registry only adds names for the 50 listed.
- **Offline incidents (watched devices):** offline and online pairs from the journal, clipped to the week. An outage abandoned by an unwatch never haunts later weeks.
- **Data cap:** the month to date as of the period's last day. The percentage uses the lower bound.
- **Email:** plain-text email. The subject is built from dates only. Network text has control characters removed and is clipped to 120 characters.
- **Resource limits:** one absolute deadline and a no-retry OpenSearch client reach every request. A failing section is `unavailable`; it never fails the report.

### Daemon: supporting changes

- **`event_journal.scan()`:**
  - takes a snapshot under the lock, then reads outside it;
  - reads newest first, at most 32 MiB;
  - keeps only rows bounded by the week.
- **`device_registry.get_devices`:** gains `fields`, `timeout` and `client`.
- **Usage helpers:** `usage_report.lower_bound` is now public, and the `usage_ledger` index inventory is a module function. Old code is kept in OLD CODE markers.
- **Email helpers:** `notification_hub.send_report_email` and `notification_config.is_address`.

### Daemon: API and backups

- **`api/reports.py`:**
  - validation: 400 for a non-object body, a bad name, more than 10 recipients, CR/LF or a comma, non-bool flags, or an explicit `sections`;
  - `PUT /api/reports/card` (201 on create, 200 on update);
  - `GET /api/reports/history` and `/history/{id}/{report_id}`, with strict patterns and a resolved-path check;
  - the list reply carries the ledger zone;
  - every generator call runs on the route pool.
- **`api/server.py`:** the generator is wired with a no-retry client and the job is registered.
- **Backups:** a new `report_schedules` section. Restore brings schedules back unconfirmed, with a warning.

### Web

- New `/reports` page (Overview, after Bandwidth):
  - KPIs: Next report, Last sent, Delivery, Days covered;
  - the hero is the latest report's five sections with coverage lines;
  - a sortable history; selecting a row shows that report;
  - Generate now shows the daemon's 409 messages.
- New `ReportScheduleCard` on Settings › Notifications: on/off, weekday, hour and recipients. Save sends `confirm: true` with the token. It shows "Times are in <zone>" and the paused note.
- `reports.ts` helpers now throw on failure. The generate proxy waits 60 s. There's a new nav entry and a backup label.

### Roadmap amendment (owner sign-off at the plan gate)

- The channel summary (a `report` event to Pushover, Discord or Telegram) is deferred to **NET-351**.
- `GET /api/events` is deferred to **NET-352**.

### Deploy

- **`scripts/remote/deploy-weekly-report.sh`:**
  - records and tags the running images `:rollback-net340` once;
  - builds the daemon and web, and waits for health and settled memory;
  - asserts the `@timestamp` mapping;
  - runs one Generate now on a throwaway schedule with no recipients, sampling memory, swap and health latency every 2 s, and applies the roadmap's stop rule;
  - checks parity with `/api/usage/daily` and `/api/alerts/count`, the history listing and file mode 600, then deletes the schedule.
- **`scripts/remote/rollback-weekly-report.sh`:** checks the tags still point at the recorded images, then recreates both containers from them.

## Tests

- **Daemon:** 6,304 passed, 5 skipped. New tests:
  - `test_report_state.py` (38) and `test_report_schedule.py` (35);
  - `test_backup_report_schedules.py` (7) and 10 new API tests;
  - `test_report_sections.py` (46), `test_report_text.py` (14) and `test_report_email.py` (8);
  - 10 `scan()` tests in `test_event_journal.py`.
- **Web:** Vitest 6,114 passed, svelte-check 0 errors, the colour gate clean. Visual specs cover `/reports` (populated and empty) and the card.
- **Lint and shell:** ruff 0.17.3 check and format are clean, and shellcheck is clean on both scripts.

## Review gates

- **`/deep-review`:** no findings (`security-reviews/feature-weekly-report/security-review.md`). Four reviewers covered injection and data flow, auth and the consent boundary, security controls, and cross-file reachability.
- **`/ponytail-review`:** "Ship" with no must-fix items. All 10 findings are fixed:
  1. a 503 reason the error middleware hid, and a backup export that reported a generic 500;
  2. a doubled "Not included this time";
  3. an "at least" figure the page could round up;
  4. the missing Security posture link;
  5. no backoff when the claim write keeps failing (now one hour, in memory);
  6. the counted-day rule written twice (now `usage_report.counted_now`);
  7. a dead alias;
  8. unused constructor options;
  9. a needless client factory;
  10. the SMTP settings read in two places (now `_smtp_settings`).
- `ReportRefused` is now in the error-reply guard's `SAFE_TEXT` list. Its messages are fixed sentences.
- **Two-angle review (PR #351)**. All findings are fixed with tests that fail before the fix.
  - **Security** (2 LOW):
    - The Settings card always saves its schedule as weekly, so saving it can never confirm a daily schedule restored from a backup or edited through the API.
    - Only the card's schedule can be confirmed for email. A confirming POST, or a confirming PUT on any other schedule, gets a 400 and saves nothing, so there are no hidden recurring emails.
  - **Python** (HIGH and MEDIUM):
    - A backup download leaves out any stored schedule a restore would refuse, and logs the ids, instead of refusing the whole download. The card's first save counts toward the 50-schedule limit.
    - Once the claim is durably saved, the email always goes out. A failed staged-file rename, reports-folder sync or prune is logged, and prune runs after the send. If only the claim's own folder sync fails, memory matches the file and nothing is sent (the plan's rule), and the period ends up "unknown" rather than risking a second email.
  - **TypeScript** (3 MEDIUM and a test):
    - The hero can no longer stick on "Loading the report".
    - Load failures show the daemon's own sentence.
    - The card re-reads the schedule after a 409, keeping unsaved edits.
    - A time-zone-dependent test is fixed.
  - **CodeQL** (2 high `py/path-injection`, 1 test warning):
    - `schedule_dir` adds the normalise-then-prefix guard CodeQL recognises, after the uuid4 check.
    - The flagged test asserts on the full addresses.

## G11 deploy (2026-11-22, `deploy-weekly-report.sh` at `c479940e`)

- **Baseline:** daemon VmRSS 307 MB on the old image, 154 MB settled on the new one. OpenSearch anon about 3,960 MB. Swap used 3,322 MB once settled.
- **`@timestamp`:** a `date` in all 9 network indices.
- **Generate now:** a throwaway weekly schedule with no recipients, zone UTC, covering 15–21 Nov.
  - It took 0.3 s. The worst five completed, and `/api/health` peaked at 1 ms.
  - Daemon VmRSS went 154 → 152 MB 60 s later, and swap peaked at 3,329 MB (+7 MB). The stop rule passed.
- **Representative:** yes. The last day was yesterday, there were 7 day rows, and yesterday had 704 alerts.
- **Parity:**
  - Traffic was 1,621,616,440,132 bytes, equal to `/api/usage/daily` exactly.
  - Alerts were 3,984. The script's check failed because it read the count endpoint's top level instead of `counts`, and PR #352 fixes that. A hand check on the G11 gave `/api/alerts/count` = 3,984 (high 1,052, medium 951, low 1,981) for the same week.
- **History and files:** the report was listed with file mode 600. Deleting the schedule removed its directory.
- **Email:** unverified on the device, because the check emails no one.

## Notes

- `config_backup.py` is 816 lines; it was 800 before.
- `report_generator.py` is about 800 live lines plus required OLD CODE.
- **Known limit:** the page's "at least" line shows whole tenths of a GB, so a near-idle daily report reads "At least 0 GB". It never reads too high.
