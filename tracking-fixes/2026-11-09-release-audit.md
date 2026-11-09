# Release audit fixes: interim records, silent pipeline failures, false successes (NET-223)

**Date:** 2026-11-09
**Branch:** `fix/release-audit-2026-11`
**Linear:** NET-223 (parent), fixes NET-230–NET-236, blockers NET-224–NET-229
**Report:** `Debugging/RELEASE-AUDIT-2026-11.md`
**Status:** Built, tested and reviewed. Not merged, not deployed. The G11 deploy (`deploy-release-audit.sh`) needs the owner's go.

## What the audit asked

Can a user trust what NetTap displays about their network, and understand what it cannot observe or establish? The audit traced every major figure from Zeek/Suricata through Logstash and OpenSearch to the page, reconciled live values on the G11 against independent OpenSearch sums and controlled downloads, and rendered the production build against a stopped and a silent OpenSearch.

## Fixes

| # | Problem (severity) | Root cause | Fix | Files |
|---|---|---|---|---|
| F1 | Bytes and connections over-counted by up to 9% a day (P1) | Malcolm's long-connections package writes cumulative interim records to `conn_long.log` with `event.dataset: conn`; every accounting query summed them with the final record | `CONN_ACCOUNTING` filter (`excluded_ips.py`) excludes `log.file.path: conn_long.log`; swapped into every byte/connection query. Live views and alert evidence keep the raw records | `daemon/services/excluded_ips.py`, `api/devices.py`, `traffic.py`, `risk.py`, `logs.py`, `drilldown_runner.py`, 10 services |
| F2 | Health and "no alerts" stayed green with Zeek/Suricata/Logstash/Filebeat stopped or nothing indexed (P1) | `/api/system/health` checked storage, SMART and an OpenSearch ping only | `services/pipeline_health.py`: newest `event.ingested` (stale after 15 min, no data after a 10 min grace) plus one `docker inspect` of the four sensors, 5 s budget, 30 s cache; `pipeline` in the health reply; a Data stage on Home and a "Data and sensors" row on System | `daemon/services/pipeline_health.py`, `api/server.py`, `web/src/lib/api/system.ts`, `routes/home.ts`, `+page.svelte`, `system/+page.svelte` |
| F3 | Notification settings "saved successfully" and every test "sent" (P1) | POST config discarded the body; the test swallowed SMTP errors and ignored the webhook's status | POST config answers 501 and says nothing was saved; the test sends through each enabled channel and answers 200 / 409 (none set up) / 502 (names the failures) | `web/src/routes/api/notifications/{config,test}/+server.ts`, `lib/server/notifications.ts` (the Settings form already shows a non-OK reply's error text) |
| F4 | Suppressions, false-positive marks, baselines and the threat-intel cache lost on every daemon restart (P1) | Default directory `/tmp`, a tmpfs in the daemon container | Default `/opt/nettap/data` (the `nettap-appdata` volume, as setup and device names already use); `migrate-daemon-state.sh` copies existing files before the recreate | `daemon/services/alert_intelligence.py`, `threat_intel.py`, `scripts/remote/migrate-daemon-state.sh` |
| F5 | Security posture graded "nothing measured" as A / Excellent (P1) | Empty inputs scored 100 | Each category is measured, empty or failed; the grade counts measured categories only and says so | `web/src/routes/compliance/+page.svelte` |
| F6 | Public `/api/health` returned the drive serial, model and storage; setup's final check said "daemon running" when it was down (P2) | It passed on the full `/api/system/health`, and always answered 200 | Calls the daemon's liveness check and returns only `daemon.status`; setup reads that status | `web/src/routes/api/health/+server.ts`, `routes/setup/+page.svelte` |
| F7 | The owner's public IP was committed as a placeholder (P2) | Copied from a live session | Replaced with 203.0.113.10 everywhere in HEAD (history unchanged) | Settings page, daemon/web docstrings, tests |
| F8 | PCAP Search "Download filtered" leaked its temp file on the daemon's 50 MB tmpfs until downloads failed (P1) | `_tmp_path` was set and never read | `_TempFileResponse` deletes the file once sent, however the send ends; the service deletes it on a write error or cancel | `daemon/api/pcap.py`, `services/pcap_search.py` |

Also: `test_prune_emergency_never_deletes_todays_index` pins that the emergency index prune keeps today's live index with the disk still full.

## Tests

Each fix has tests that fail on the old code and pass on the fix:

- F1 `test_conn_long_interim.py` + `test_the_connections_log_list_holds_the_connection_count`.
- F2 `test_pipeline_health.py`, health and Home/System tests.
- F3 `api/notifications/{config,test}/server.test.ts`, `notifications.test.ts`.
- F4 `test_data_dir_persistence.py`.
- F5 `compliance.test.ts`.
- F6 `api/health/server.test.ts`, `setup-wizard.test.ts`.
- F8 `test_pcap_download_cleanup.py`.
- Migration: `tests/scripts/test_migrate_daemon_state.bats`.

Suites (Dev, macOS): daemon pytest 4,271 passed / 4 skipped (baseline 4,243); vitest 4,331 passed (baseline 4,303); svelte-check 0 errors; colour gate clean; Playwright visual 294 passed (50 skipped by design); bats 6/6; shellcheck clean on the three new scripts.

## Review fixes (pre-commit, 2026-11-09)

- **Python (MEDIUM):** the freshness search shared the 8-thread route pool, so time queued behind a cold page load counted against the 5 s budget and read as "couldn't check", cached for 30 s. The probe now has its own thread, and "unknown" is cached for 5 s. Tests: `test_a_busy_route_pool_does_not_make_it_unknown`, `test_unknown_is_checked_again_sooner_than_a_real_answer`. Both fail on the earlier version.
- **TypeScript (MEDIUM):**
  - Zero alerts still said "your network looks clean" beside "Not measured"; it now reads "No rule matched in this period, so there is nothing to score".
  - A missing nodemailer returned Node's raw error with a file path; it now reads "not available in this build".
- **Security (LOW):**
  - The daemon token now goes to curl on stdin (`-H @-`), so it never shows in `ps`.
  - The migration accepts only a regular file owned by the user running it, never a link (bats test added).
- **Ponytail:**
  - The deploy script's copy of the smoke test's F1/F2/F6 checks is gone (−40 lines); a failed smoke test now fails the deploy.
  - The smoke test's traffic check brackets the API call with two independent sums. A connection closing mid-check lands in the window, because its record carries the start time.
- **Deep review:** no findings.

## Lessons

- **Malcolm's `event.dataset: conn` is not one record per connection.** The long-connections package writes interim cumulative records under the same dataset and uid. Filter on `log.file.path` for accounting.
- **A health check that only pings the database can't see a dead sensor.** Freshness (`event.ingested`) plus container state is the minimum.
- **A route that returns success without doing the work is worse than a 501.** Three such routes reached a release candidate.
- **`docker exec … sh -c "$(cat script)"` with `rm` inside trips Claude Code's removal safety check.** Test such scripts with bats on the host instead.

## Next steps

- Owner: deploy with `bash scripts/remote/deploy-release-audit.sh`, then `bash scripts/remote/smoke-test-release.sh`.
- Blockers NET-224–NET-229 stay open; the verdict is NOT READY until they close.
