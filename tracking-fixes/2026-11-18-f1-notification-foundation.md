# F1: new-device notifications, event journal and background checks, 2026-11-18

**Linear:** NET-319 (roadmap project P-NET-1, slice F1)
**Branch:** `feature/f1-notification-foundation` (from `origin/main` ac452991)
**Plan:** `plans/2026-11-18-f1-notification-foundation.md`. Codex APPROVED it in round 3.
**Status:** implemented and tested locally; PR, merge and G11 deploy follow.

## What changed

- **Event journal** (`daemon/services/event_journal.py`):
  - `events.jsonl` (mode 600) is the commit point for every event NetTap notifies about or will later report on.
  - Each line has a monotonic `seq` and a stable id `sha256(type|key|instance)[:32]`.
  - Appends are fsynced. A failed write is truncated back, and a torn tail is cut at start-up.
  - Compaction keeps 120 days or 50,000 lines, everything after the dispatcher's saved cursor, and the newest line.
- **New devices are journaled before they are indexed** (`device_registry.py`). If the append fails, that device is skipped and retried on the next refresh. Raising would end the whole registry pass.
- **Dispatcher event intake** (`notification_dispatcher.py`):
  - Up to 200 journal events are read per poll into per-channel queues in `notification-events.json`.
  - Queued events go out with alerts under the same budget. They never give up.
  - Each queue holds at most 500 events; anything over that is counted.
  - The cursor (`committed_seq`) advances only after the event state is saved.
- **Background checks** (`scheduled_jobs.py`, `api/jobs.py`):
  - The runner has 2 threads of its own and no overlap. A slot is held until the thread returns.
  - Each run's last result, error, duration and memory figures are saved.
  - `GET /api/jobs` lists the checks. `POST /api/jobs/{name}/run` returns 202, 404, or 409 when the check is already running.
  - F1 has one job: `journal-compact`, daily.
- **Rules have an `enabled` flag:**
  - The quick setting `new_device` is backed by the fixed rule `settings-newdevice`, on by default (decision D1).
  - Deleting that rule turns it off.
  - The default is seeded once, at load and on backup restore.
- **Web** (Settings › Notifications):
  - a "Tell me about new devices" switch;
  - a Background checks table, every column sortable, with each state shown and a Run now button;
  - the rule form offers New device;
  - an "Off" tag on turned-off rules.

## Failure model

- Nothing committed to the journal is lost while the files are intact.
- A crash between a send and the saves repeats that message once per crash.
- After a rollback to the old dispatcher, queued events survive, because the old dispatcher rewrites only `notification-dispatch.json`.

## Tests

- **Daemon:** 5,353 passed. The 45 new tests are in:
  - `test_event_journal.py` (14);
  - `test_scheduled_jobs.py` (6);
  - `test_registry_new_device_journal.py` (5);
  - `test_new_device_rule.py` (8);
  - `test_dispatcher_events.py` (12).
- **Lint:** ruff 0.17.3 check and format are clean.
- **Web:**
  - vitest: 5,724 passed;
  - svelte-check: no new errors;
  - `check:colors` and `check:e2e`: clean;
  - `test:visual`: see the PR.

## Gates

- `/codex-review` on the plan: APPROVED in round 3.
- `/deep-review`: no findings. The report is in `security-reviews/feature-f1-notification-foundation/`.
- `/ponytail-review` found two things, both fixed:
  1. **Skipped runs were counted wrongly.** The runner counted a skipped overlap on every tick of a run that started because it was due, since "due" is measured from the last finished run. Now a skip counts only after the run has lasted a whole interval.
  2. **An unused `SENT_EVENTS` constant.** Deleted.
- The two-angle review runs on the PR.

## Lessons

- **Keep event state in a file the old code doesn't own.** A rollback to the pre-change dispatcher would rewrite its own state file and wipe anything new kept in it.
- **"Due" from the last finished run is not "overdue".** An overlap counter has to measure from the current run's start.
- **Recovery cost grows with the journal.** At 200 lines a poll, a lost event state re-reads the whole journal. The online/offline slice, which writes many events, should start recovery at the first entry inside the 24-hour window.

## Next

- PR, the two-angle review, squash merge.
- Deploy to the G11 with `bash scripts/remote/deploy-notification-foundation.sh`.
- Then F4 (NET-329) on the critical path.
