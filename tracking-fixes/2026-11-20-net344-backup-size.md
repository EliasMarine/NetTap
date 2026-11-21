# NET-344: every downloadable backup restores

**Status:** built and reviewed on `fix/backup-size`; next are the PR, the two-angle review, the merge, and the G11 deploy (`bash scripts/remote/deploy-backup-size.sh`). Merging it unblocks F2 (NET-320, draft PR #341).

**Plan:** `plans/2026-11-20-net344-backup-size.md`. Codex reviewed it for the owner's six-round cap without approving (12, 9, 8, 7, 7 and 8 findings). Round 6 took 7 of 8 findings and rejected one, which is pre-existing (§14). The owner's standing rule is to take the recommendation and keep going. The log is `plans/2026-11-20-net344-backup-size.review-log.md`.

## Problem

A config backup could download fine and then fail to restore. There were four causes:

- **No byte-for-byte path.** The web app re-encoded the JSON both ways: its proxy re-serialised the export, the download pretty-printed it, and the upload stringified it again. So the bytes the owner saved were never the bytes measured.
- **No size limits on the history.** Alert acknowledgements are kept forever and were exported in full, so a backup could pass the 16 MiB restore limit.
- **Validate and import disagreed.** Validation checked a few sections, and the import checked every section as it applied them. A backup could validate, then have a section refused after earlier sections were already applied. Examples: a suppression `reason: null`, and a legacy excluded-IP range.
- **Hidden refusals.** An oversized upload's 413 surfaced as "Invalid JSON body".

## What changed

- **One serialisation, kept byte for byte.**
  - The daemon answers the export with exact compact UTF-8 JSON (`services/backup_fit.py` `encode`, lone surrogates escaped per character).
  - The web proxy streams that 200 through with `Content-Type`, `Content-Disposition` and `Cache-Control`.
  - The download saves the blob unchanged.
  - The upload sends the file's own text, or one compaction for an old pretty-printed file, or refuses locally.
- **Fitting.** `fit` trims the oldest acknowledgements, ordered by UTC instant, to a body strictly under 16 MiB. The arithmetic is exact (commas and the count's digits), and the final encode is asserted to match. `metadata.acknowledgements_left_out` records the number left out, and the download shows a note.
- **Refusals.**
  - **413 `backup_too_large`:** zero acknowledgements still don't fit. The message names the largest part, in decimal MB.
  - **422 `legacy_excluded_ips`:** a range, a non-IP string, or more than 10,000 entries that an older NetTap allowed. The message says what to remove in Settings › Network.
  - **422 `invalid_section`:** anything else that wouldn't restore.
  - **503:** an export is already running. It carries `Retry-After: 30`, which the proxy forwards, and nothing is queued.
- **One preflight.** `services/backup_checks.py` `section_errors` holds every section's content check. Validate, import and export share it, and it runs off the event loop. A content failure applies nothing. The importer calls the same rules, so the two can't drift.
- **Notifications are exported from the running hub** (`NotificationHub.backup_state`). A channel the hub skipped at load would otherwise have blocked every backup.
- **Validate and import answer a plain 413** for a body at or over the limit, instead of "Invalid JSON body".
- **Excluded IPs:**
  - capped at 10,000;
  - duplicates are removed on load and on import;
  - the Settings save and the import both write atomically.
- **Suppression reasons:**
  - the suppress and false-positive APIs store `str(reason or "")`;
  - the export copy turns any non-string reason into text;
  - the restore accepts `null` from older backups.
- **nginx:** the backup location gets `proxy_read_timeout 300s` (the web app's import budget is 290 s).
- **The Backup tab:**
  - a generation counter, so Apply only sends the body validated for the current file;
  - Remove is locked while an import runs;
  - the left-out note;
  - the daemon's export errors shown as written.
- **Device scripts:**
  - `deploy-backup-size.sh`;
  - `classify_backup_export.py`, standard library only, so F2 reuses it;
  - `verify_backup_size.py`.

### Files

- **Daemon:**
  - API: `api/backup.py`, `api/settings.py`, `api/alerts.py`;
  - services: `services/config_backup.py`, new `services/backup_fit.py`, new `services/backup_checks.py`, `services/excluded_ips.py`, `services/device_custom.py`, `services/notification_hub.py`;
  - tests: `tests/test_backup_fit.py`, `test_backup_preflight.py`, `test_backup_http.py`, `test_backup_limits.py`, `test_classify_backup_export.py`, and updates to existing tests.
- **Web:**
  - code: `routes/api/[...path]/+server.ts`, `lib/api/backup.ts`, `routes/settings/tabs/BackupTab.svelte`;
  - tests: new `routes/api/catchall-backup.test.ts`, and updated backup tests.
- **Docker:** `docker/nginx.conf`.
- **Scripts:** the three in `scripts/remote/` above.

### Departures from the plan

- **`fit` returns a `bytearray`,** which saves a 16 MiB copy at the peak. `ConfigBackup.export_file()` runs `fit`, then the preflight on the fitted config.
- **Notifications come from the hub's live state,** not the file (above).
- **The 413 and 422 replies carry only `error` and `code`.** Nothing read the other fields.
- **A capture section with a bad interface name** is refused at validate, even without `apply_capture`.

## Test results

- **Daemon pytest:** 5,730 passed and 5 skipped, against 5,594 passed on `main` 07e1c1cd. ruff 0.17.3 check and format are clean over `daemon/`.
- **Web:**
  - vitest: 5,874 passed;
  - svelte-check: 0 errors (2 old warnings);
  - check:colors: clean;
  - visual tests for Settings › Backup: 6 passed, 1 skipped.
- **Scripts:** shellcheck is clean on `deploy-backup-size.sh`. The classifier passes 18 cases in a fresh interpreter.
- **Isolated verifier** (locally and in a Python 3.12 container): 32 pictures and 70,100 acknowledgements export to 16,777,138 bytes, 78 under the limit. It leaves out 15,444 and keeps exactly the 54,656 newest. The restore brings back every name and picture, and prints `BACKUP-SIZE-OK`.
- **Measured on the Mac:**
  - a 32 MiB acknowledgement history exports in 1.5 s;
  - a second export gets the 503 at once;
  - `fit`'s own workspace is 19.7 MiB;
  - the whole path peaks at about 330 MiB, mostly from parsing the file.
- **Gates:**
  - `/deep-review`: no findings from its four agents (report in `security-reviews/fix-backup-size/`);
  - `/ponytail-review`: no must-fix. Its should-fix (old non-IP excluded entries got `invalid_section`) and its three nice-to-haves are all taken. They were decimal MB, one rule in one place, and dropping unused reply fields and `exportConfig`. It also flagged the notification-hub case, which is fixed.

## Lessons

- **Each round 4–5 addition opened a new class of findings.** Restoring legacy ranges brought a new predicate and a rollback schema gate. A repair script brought archive, overwrite and conflict problems. A 16 MiB Settings save brought the OpenSearch term limit and UI size. Cutting them, and adding a cap, closed more than it opened.
- **aiohttp refuses a body whose length is `>=` `client_max_size`,** while nginx and adapter-node accept exactly the limit. The daemon is the real cutoff, one byte lower.
- **`app["excluded_ips"]` is the raw stored list,** so legacy CIDRs still affect Live Connections and Top Destinations. Most other views use `valid_excluded_ips`, which skips them.
- **Found on the way:** NET-345 (an expired suppression blocks suppressing the same alert again) and NET-346 (no way to list or remove suppressions).
