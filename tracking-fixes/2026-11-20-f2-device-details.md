# F2: device details store (NET-320)

**Status:** built on `feature/f2-device-details`. The PR stays a draft until NET-344 (every downloadable backup restores) has merged and its restore test passes on `main` (plan §3 decision 9). Then: rebase, re-run every suite, merge, and deploy with `scripts/remote/deploy-device-details.sh`.

**Plan:** `plans/2026-11-20-f2-device-details.md`. Codex approved it in round 6 of 6, after 12, 7, 4, 1 and 1 findings. The log is in `plans/2026-11-20-f2-device-details.review-log.md`.

## What changed

- **A new store,** `daemon/services/device_details.py`, writes `<data>/device_details.json` with mode 0600. It holds `watch_after_min` (15, 30, 60, 240 or 1440 minutes), `group` (up to 32 characters), `owner` (up to 64) and `notes` (up to 1,000) for each MAC.
  - The values are one line of text: control, format, surrogate, line-separator and paragraph-separator characters are refused before trimming.
  - At most 50 devices can be watched, and at most 2,000 can have details.
  - The file is capped at 512 KiB, measured on the exact compact UTF-8 bytes it is written in.
  - MACs are parsed strictly: exactly six octets, never truncated.
  - A damaged file switches the store off until the daemon restarts, and logs how to recover.
- **Rows:** every registry, IP-page and traffic row carries `group`, `owner` and `watch_after_min`. They come through `DeviceCustomStore.owner_fields`, which gets the details store passed in, and are merged before its early returns. A device with details but no name or picture still shows them.
- **Device pages:** both the MAC page (`GET /api/devices/registry/{mac}`) and the IP page (`GET /api/devices/{ip}`) carry all four fields, notes included, from one read. The IP page also returns `registry_mac`, the MAC to edit them with. An eight-octet DHCP address maps to its six-octet registry key.
- **API:** `PUT` and `DELETE /api/devices/registry/{mac}/details`.
  - Both parse the raw route MAC strictly.
  - PUT needs the device to be in the registry; DELETE works for any valid MAC.
  - The reply is exactly what was saved.
  - A damaged file gets its own 503 message.
- **Backup:** a new `device_details` section.
  - A preflight refuses the whole import for a bad section, or for a damaged details file on this box.
  - A backup from before F2 leaves the current details alone.
  - `handle_export` turns an unreadable device file into a fixed 503 that the owner can read. Before, the owner saw a generic 500.
  - `handle_validate` now runs off the event loop.
  - The web export error shows the daemon's reason, and the Backup tab labels and describes the new section.
- **Shared code:** `write_file_atomic` takes an optional `encoding`. The default is unchanged; F2 passes `"utf-8"`.
- **Deploy:** `scripts/remote/deploy-device-details.sh` checks backup headroom before anything is rebuilt. It rebuilds the daemon and web images, and its live checks are read-only. `verify_device_details.py` runs in a throwaway copy of the image (`DEVICE-DETAILS-OK`).

## Files

- **New daemon files:** `services/device_details.py` and the tests `test_device_details.py` (104), `test_device_details_api.py` (15) and `test_device_details_rows.py` (14).
- **Changed daemon files:**
  - services: `device_custom.py`, `device_registry.py`, `config_backup.py`, `capture_config.py`;
  - API: `device_custom.py`, `devices.py`, `devices_v2.py`, `backup.py`, `server.py`;
  - tests: `test_config_backup.py`, `test_backup_api.py`, `test_device_custom.py`.
- **Web:** `lib/api/backup.ts` and its test, `routes/settings/tabs/BackupTab.svelte` and `backup-import.test.ts`.
- **Deploy:** `scripts/remote/deploy-device-details.sh` and `verify_device_details.py`.

## Test results

- **Mutation check:** 11 deliberate bugs in the store were caught by its tests. One mutant behaves identically: `isinstance` instead of `type()` for the watch value, since `True` and `False` aren't in the choices.
- **Full suites:**
  - daemon pytest: 5,738 passed, 5 skipped;
  - web vitest: 5,853 passed;
  - svelte-check: 0 errors (2 old warnings);
  - check:colors clean, ruff 0.17.3 clean;
  - visual tests for Settings › Backup: 6 passed, 1 skipped;
  - shellcheck clean;
  - `verify_device_details.py` locally: `DEVICE-DETAILS-OK`.
- **Gates:**
  - `/deep-review`: no findings. The report is in `security-reviews/feature-f2-device-details/`.
  - `/ponytail-review`: "Ship", with 2 nice-to-haves, both taken: a duplicate `app["device_details"]` line, and two `deepcopy` calls that did nothing.

## Lessons

- **Bolting a backup-wide guard onto a feature slice produced new findings every round.** Rounds 2 to 5 were all about backup size, which is a problem older than F2. Splitting it into NET-344 and ordering the merges ended the loop.
- **The web app re-encodes JSON in both directions.** Its proxy parses and re-serialises JSON replies, the download pretty-prints, and the upload stringifies again. Any size guarantee has to measure, or preserve, the bytes the owner actually saves.
- **aiohttp refuses a body whose length is `>=` `client_max_size`.** nginx and adapter-node accept exactly the limit, so the daemon's limit is the real cutoff, one byte lower.

## Rebase requirements once NET-344 is merged

These come from the NET-344 plan, §4 (`plans/2026-11-20-net344-backup-size.md`). NET-344 trims the oldest alert acknowledgements to fit the restore limit. It never leaves out an owner setting: a backup too big even without acknowledgements gets a specific 413 naming the largest part.

- **The live checks in `deploy-device-details.sh` differ by stage:**
  - **Before the deploy,** the running build is NET-344 without F2, so it has no `device_details`. A valid 200 passes there, and `acknowledgements_left_out` is printed.
  - **After the recreate,** a 200 must carry `device_details`.
  - **At both stages,** the size 413 and the `legacy_excluded_ips` 422 are findings, not failures. An `invalid_section` 422 (for example on `device_details`) fails, and so does any other answer.
  - **The classifier** is NET-344's standard-library-only `scripts/remote/classify_backup_export.py`, which imports nothing from the daemon. The deploy script pipes it into whichever daemon image is running, so it works on the NET-344 image before F2 exists. `verify_device_details.py` imports F2 code, so it can't be the classifier. The F2 stage rule (is `device_details` required?) is a flag passed to the classifier.
  - The pre-deploy headroom arithmetic (the 768 KiB reserve) goes, because NET-344's `fit` measures the real file.
- **Shared checks:** `device_details` joins NET-344's `section_errors`, which validate, import and export share.
- **Serialisation test:** rewrite the serialisation-bound test in `test_config_backup.py` against `fit`, with ASCII and emoji notes.
- **Release fixture:** 32 photos, 46,000 acknowledgements and 480 notes. It must give:
  - a 200 whose `acknowledgements_left_out` equals the expected count;
  - kept acknowledgement IDs equal to an independently computed newest set;
  - after import, the names, pictures and notes intact.

## Next

1. Run `/deep-review` and `/ponytail-review`, commit, and open a draft PR.
2. NET-344: plan (in Codex review), build, merge.
3. Rebase F2 onto that `main`, re-run the suites and the release fixture (32 photos, 46,000 acknowledgements and 480 notes must give a restorable download), do the two-angle review, merge, and deploy to the G11.
