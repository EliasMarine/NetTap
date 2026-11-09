# Backup, restore and storage tell the truth (NET-227, NET-237)

**Date:** 2026-11-09
**Branch:** `fix/net-227-backup-storage` (from `fix/release-audit-2026-11`)
**Linear:** NET-227 (blocker B4, finding A9); A15, A16, B-l and B-m under NET-237
**Status:** Built, tested and reviewed on the branch. Not deployed yet.

## What was wrong

- **A9 (B4): a restore said "Import successful" and restored neither the capture mode nor retention.**
  - The backup read `capture_config.json` and `retention_config.json`. Neither file exists. The daemon uses `/etc/nettap/capture-mode.conf` (an INI file) and `/opt/nettap/data/retention.json`.
  - Both sections were always `{}`, and the restore wrote them back to the files nothing reads.
  - The export also carried every notification password, token and webhook URL in plain text.
- **A15: one ILM failure at startup was never retried.** If OpenSearch wasn't ready, `verify_ilm_policy` still set `_ilm_verified`, so Settings showed "Policy synced" with no policies applied.
- **A16: the setup wizard's Storage step made up a 1 TB disk** when the daemon didn't answer.
- **B-l: capture could stay paused for good.**
  - The cascade stops capture at 95%, deletes until usage is below 90%, and resumes only below 85%.
  - Between 85% and 90% nothing deleted and nothing resumed.
- **B-m: the retention estimate used a fixed 1.2 GB a day.** The G11 writes about 2 GB of indices and 66 GB of PCAP a day.

## Fix

### Backup and restore (A9)

- **`services/config_backup.py`:**
  - Reads the real files. The schema is now version 2, so an older daemon refuses a redacted backup instead of overwriting working channels.
  - The backup now also covers the home location, alert acknowledgements and alert suppressions. Each one is checked before it is written, and the write is atomic.
  - Excluded IPs go through `parse_single_ip`, the same check Settings uses.
  - The result lists `skipped` sections with a reason for each.
- **`services/backup_notifications.py` (new):**
  - The export keeps only public keys (NET-224's list) and names the keys it left out.
  - On restore, the box's own secrets are kept only when the channel type, SMTP host, port, user, TLS setting and any webhook URL are all unchanged, so a crafted backup can't send them elsewhere.
  - A channel that is still missing a secret is turned off and named in the report.
  - An email channel with no SMTP server gets a warning.
- **`api/backup.py`:**
  - Retention is restored through `save_retention_config`, which is POST /api/storage/config's path: save, hot-reload, ILM.
  - The capture mode is restored through setup's `_build_capture_config` and `_apply_configuration` under the capture lock, and only with `?apply_capture=1`.
    - Only validated values reach those files.
    - The box keeps its own PCAP rotation size.
    - A failed container restart counts as an error.
  - Excluded IPs, the bandwidth cap and notifications reload in memory. The box's own management IP stays excluded.
- **Web, `settings/backup`:**
  - The page says what a backup includes and what it leaves out.
  - It asks before restoring a different capture mode, because that restarts capture.
  - It shows "Restored", "Skipped (why)", the errors and the warnings, instead of a bare "Import successful".
- **Web, other files:** the catch-all proxy gives `/api/backup/import` setup's 290 s timeout.

### ILM retry (A15)

- **`storage/manager.py`:**
  - A failed apply, or an error result, is retried after 5, 10, 20, 40 and then every 60 minutes.
  - The apply reads the config inside the same lock as Settings saves.
  - The status reports `last_attempt`, `last_error` and `pending_retry`.
- **`storage/retention_config.py`:** `mark_ilm_failed` records the error and keeps the last success.
- **Web, Settings › Retention health:** shows "Last try …: <error>. NetTap tries again automatically."

### Setup storage step (A16)

- **`/api/setup/storage`:** answers 503 with a plain message instead of the mock disk.
- **Setup page:** shows a `CardState` error with "Try again".

### Capture pause (B-l)

- **`emergency_cascade`:**
  - While capture is paused, it deletes down to 85%, not 90%, so capture always comes back.
  - PCAP goes first, and the oldest files first. A file that can't be deleted is skipped and doesn't use up the batch.
  - Indices are pruned only when fewer than a full batch of PCAP could be deleted. Today's index is still never deleted.
- **`run_cycle`:** runs the cascade while paused at 85% or more.
- **Status:** reports `capture_paused_disk_full`.
- **Web:** the capture chip shows "Packet capture paused: disk full".

### Growth estimate (B-m)

- **Index rate:** the mean size of the complete UTC days in the last week, from `_cat/indices` in bytes.
- **PCAP rate:** total PCAP divided by the time its files span, once that is at least a day.
- **PCAP days kept:** cold days, or the PCAP cap (measured on the PCAP filesystem) divided by the rate, whichever is less.
- **Web:** `growthSummary` (`web/src/lib/utils/storage-estimate.ts`) gives the estimate in words with its basis, on the setup Storage step and on System. Until a day is measured it says "No estimate yet".

## Left out of backups, on purpose

The `.env` (API keys, SMTP password), the daemon token, the admin login, UniFi and ET Pro credentials, notification secrets, `notification-dispatch.json` (runtime state), investigations, own Suricata rules, report schedules, PCAP capture settings and the live-bandwidth toggle.

## Tests

- **Daemon:**
  - `test_backup_api.py` (new).
  - `test_config_backup.py`: TestA9Export, Validate, Import and NotificationRestore.
  - `test_storage_hardening.py`: hysteresis, ILM retry and growth estimate.
  - Also `test_retention_config.py` and `test_storage_config_api.py`.
- **Web:** `storage-estimate.test.ts` (new), plus `status`, `backup`, `backup-import`, `settings`, `setup-steps`, `api/setup/storage` and `catchall-timeout`.
- **Fail-before:**
  - With the old source restored, 48 daemon tests and 12 web tests failed (the storage-estimate file failed to import).
  - The three tests added after the review also failed on the pre-review code.
- **Suites:**
  - Daemon: 4322 passed, 4 skipped; `ruff check` clean.
  - Web: 4346 passed; svelte-check 0 errors; `check:colors` clean.
  - `test_prune_emergency_never_deletes_todays_index` still passes.

## Reviews

- **Codex plan review:** 3 rounds, all REVISE. Every material point was taken. Two were declined, with reasons in the review log:
  - No persisted "capture activation pending" state.
  - An email channel without SMTP gets a warning, not a disable.
- **ponytail-review findings, all fixed:**
  - A restore dropped the box's own IP from the excluded list.
  - The status said "synced" and "retrying" at once.
  - Errors showed code names.
  - One docstring was stale.

## Deploy

No compose change. Rebuild and recreate `nettap-storage-daemon` and `nettap-web`. Older daemons refuse the new backups (schema 2).

## Lessons

- A backup that reads a file path should have a test that checks the path is one the daemon actually writes. Both A9 paths were made up and nothing caught it.
- "Retry" needs a state the UI can show (last attempt, last error), or a failed retry looks like success.
- Hysteresis needs the clean-up target to match the resume line, or the system can stop in the gap between them.

## Out of scope, found on the way

- **Settings › Excluded IPs (`api/settings.py:289`):** replaces the in-memory list and drops the box's own management IP until the next restart.
- **Setup configure:** a re-run drops `[pcap] rotate_mb`.
- **STO-3 (ext4 reserved blocks):** not addressed.
