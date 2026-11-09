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

## Out of scope, found on the way (all fixed in the follow-up below)

- **Settings › Excluded IPs (`api/settings.py:289`):** replaces the in-memory list and drops the box's own management IP until the next restart.
- **Setup configure:** a re-run drops `[pcap] rotate_mb`.
- **STO-3 (ext4 reserved blocks):** not addressed.

## Follow-up (branch `fix/net-227-followup`)

- **Excluded IPs:**
  - One rule, `with_appliance_ip` (`services/excluded_ips.py`), is used at startup, by the Settings save and by the restore reload. The box's own IP stays excluded after a save.
  - GET returns `appliance_ip`. The Settings form leaves it out of the list it edits and says "NetTap's own address, X, is always left out", so a save never stores it. Before, a save stored it, and after an address change it hid whichever device got the IP next (#79).
  - The setup wizard shows `appliance_ip` instead of `excluded_ips[0]`. The box's IP is appended last, so `[0]` was the owner's first entry whenever one existed.
- **Setup rotation size:**
  - `_apply_configuration` keeps the box's `pcap_rotate_mb`. It reads it after its last `await`, right before the INI and capture.env are written. The rotation save in Settings has no `await` in its read-modify-write either, so the two can't interleave.
  - The restore's own copy of this is now OLD CODE.
  - A broken INI no longer stops setup: the read is guarded, and setup rewrites the file.
- **STO-3:**
  - On the G11 (1965 GB, 81 GB reserved for root), the daemon read 28.4% used where `df` reads 29.6%. When the disk is full for OpenSearch and capture, which aren't root, the daemon would read 95.9%. So the 95% capture stop fired with about 18 GB left, and used + free didn't add up to the total.
  - Usage, the status figures, the fill-rate prediction and tier capacity now use the usable size, used + free, the same as `df`. System says "Usable" and setup says "GB usable".
  - The PCAP cap stays a share of the raw size. Moving it would delete about 20 GB of the G11's PCAP on deploy, and that can't be undone.
  - **Rollout:** the G11 will read about 1.2 points higher, crossing no threshold. A box just under a threshold may start the clean-up one cycle earlier, which is the intended, safer behaviour.
- **PCAP scan per status poll:**
  - Measured on the G11, read-only: 3,620 files (491 GB, at its 25% cap). The daemon's `rglob` + stat + sort takes 44–48 ms, and `os.scandir` 23 ms.
  - A box at the 10 MiB minimum rotation can hold about 47k files: 255 ms per scan, measured locally.
  - The measurement is now cached for 10 minutes behind a lock. Polls arriving together share one scan: 8 at once took 252 ms in total.
- **Tests:**
  - 14 new or updated. Every new one fails on the old code except the guard that the PCAP cap stays on the raw size.
  - Daemon 4442 passed, 4 skipped. Vitest 4395 passed, svelte-check 0 errors, `check:colors` clean.
- **Codex:** 1 round, REVISE with 4 findings, all taken (log in the scratchpad's `followup/PLAN-REVIEW-LOG.md`).
