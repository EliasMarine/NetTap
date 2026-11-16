# Software updates made reliable, 2026-11-16

**Linear:** to be created by the lead
**Branch:** `fix/updates-reliability` (from `origin/main` 9ce4f415)
**Status:** implemented and tested locally; not yet deployed. Plan approved after 4 Codex rounds.

## Problem

The owner: "Software updates need to be reliable, there are bugs there." Read-only checks on the G11
and a code read found 15 problems across check, apply, status, history, rollback and the page. The
ones the owner could see:

- The update history was empty after every deploy, including the 26.02.0 to 26.10.0 Malcolm update.
- The history table showed nothing useful: the client read each batch as a single result.
- The NetTap row never offered a NetTap release: `/releases/latest` is a 404 while every release is
  a pre-release, and `NETTAP_VERSION` said "0.4.0" while the tags are `v0.4.0-alpha.*`.
- "Couldn't check nettap-nginx for updates" on every page load.
- After a daemon restart every row read "Not checked" until someone pressed Check.
- A failed rollback or a refused update said "the request failed", and dropped the daemon's reason.

## Root causes and fixes

| # | Root cause | Fix |
|---|---|---|
| P1 | `UpdateExecutor._history` lived in memory only | saved to `/opt/nettap/data/update-history.json` (nettap-appdata, `UPDATE_HISTORY_FILE`) with `write_file_atomic`; bad entries are dropped or rebuilt on load; an unfinished Malcolm update is recorded once, then cleared only once saved |
| P2 | `getUpdateHistory()` typed batches as results | `UpdateBatch` + `getUpdateHistoryBatches()`; the table flattens batches with a stable key |
| P3 | `/releases/latest` 404s for pre-releases; version constant out of step with the tags | reads `/releases?per_page=20`, offers pre-releases only to a pre-release; `NETTAP_VERSION = "0.4.0-alpha.2"`; `scripts/check_release_version.py` fails the release workflow when the tag and the constant differ |
| P4 | the Malcolm update empties the backup volume before copying into it, even when an earlier attempt left the only copy there | refuses to start while that volume exists, and says how to remove it once the data is back |
| P5 | every non-Malcolm, non-nettap image was a failed check | `nettap-*` containers follow the NetTap release (the compose file pins nginx and grafana); other containers are "Not checked", not failed |
| P6 | the page adopted whatever batch `/status` reported | follows its batch by `started_at`; another batch means "read this one's result from the history", or "Update not confirmed" when the history lacks it |
| P7 | a batch's rules update gave up after 270 s and was recorded as failed while it ran on, then Malcolm restarted Suricata under it | the batch follows the rules update to its end (`update_rules(follow=True)`); the Malcolm update checks the rules lock before it starts and holds it around each suricata-live recreate (update and rollback), released before the health waits |
| P8 | the 6 h TTL was stored but never used; a caller during a check got a half-built result | one shared check task; `get_available()` serves the last finished check plus `stale`; the page checks on its own when `stale` |
| P9 | the check proxy used the 10 s default; the daemon's check can take two 15 s GitHub calls | `UPDATE_CHECK_TIMEOUT_MS = 55_000`; the page reloads the versions after a check |
| P10 | the Malcolm row said capture pauses; the progress note mentioned Malcolm for any update | copy corrected; the note names Malcolm only when it is updating |
| P11 | `ssl=False` on GitHub calls | removed (TLS to api.github.com verifies inside the daemon on the G11) |
| P12 | rules, GeoIP and OS rows gave the check's time as a release date | `release_date: ""` |
| P14 | `rollbackComponent` read a `{result}` nothing sends; `applyUpdates` dropped the 400's reason | `{success, message}` from the daemon or the proxy; `applyUpdates` throws the reason; the page shows both |
| P15 | a local GeoIP database was offered as applicable, but the daemon image has no `geoipupdate` | applicable only where `geoipupdate` exists, otherwise `applies_with` says how to replace the file |

Left alone on purpose (in the plan): the `latest_version` phrases, securityadmin in the Malcolm
update (Chain 21 env covers it), the rules/GeoIP backup folders on the read-only root, pruning the
13 old 26.02.0 images, "Update all" duplicating "Review", and config_backup's own version default.

## Files

- Daemon: `services/update_executor.py`, `services/malcolm_upgrade.py`, `services/update_checker.py`,
  `services/suricata_rules.py`, `services/os_updates.py`, `services/version_manager.py`, `api/updates.py`.
- Release: `scripts/check_release_version.py`, `.github/workflows/release.yml`.
- Web: `src/lib/api/updates.ts`, `src/lib/server/daemon.ts`,
  `src/routes/api/system/updates/check/+server.ts`, `src/routes/system/updates/+page.svelte`,
  `e2e/visual/fixtures/system.ts`.
- Tests (new): `test_update_history.py`, `test_nettap_release_check.py`,
  `test_release_version_guard.py`, `test_update_batch_follows_rules.py`,
  `test_update_check_sharing.py`, `check/server.test.ts`; plus additions to the existing update tests.

## Test results

- Daemon full suite: 5124 passed, 5 skipped, 0 failed.
- Web full suite: 400 files, 5396 tests passed. `svelte-check --threshold error`: 0 errors (2
  existing warnings in drawer components). `check:colors`: clean.
- Not run here: `npm run test:visual` (the lead runs it; `e2e/visual/fixtures/system.ts` changed).

## Process change

Bump `NETTAP_VERSION` in `daemon/services/version_manager.py` before tagging a release. The release
workflow now fails at its first step when the two differ.

## Lessons

- A status endpoint that reports "the current batch" can't tell a poller whether its own batch
  finished. Follow by an identity (`started_at`) and fall back to the history.
- A lock checked once before a long operation protects nothing later on. Hold it around the step
  that needs it.

## Next steps

- Deploy to the G11 (daemon + web). Then check that `/api/system/updates/available` has no
  `failed_checks`, that the history survives a daemon recreate, and that the NetTap row shows
  `0.4.0-alpha.2`.
- Follow-up: prune the 13 old Malcolm 26.02.0 images on the G11.
