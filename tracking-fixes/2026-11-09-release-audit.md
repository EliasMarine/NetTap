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

## Wave 2 (2026-11-09): the six blockers and NET-237

Seven agents fixed one area each in their own worktree: notifications, capture mode, device accounting, backup and storage, alerts, first-run security, and data honesty. Each area has its own tracking note from today (`2026-11-09-*.md`). The lead cherry-picked each batch onto this branch.

The combined branch then got:
- a security review, a TypeScript review and a Python review;
- a delta round on the fixes those reviews produced.

The results are in section 6.2 of `Debugging/RELEASE-AUDIT-2026-11.md`.

Integration fixes made by the lead:
- **The bell's alert check passed every daemon failure on as a 502.** The visual suite's error mode treats a web-server 502 as a bug (48 failures), so the daemon's own status now passes on.
- **The Devices IPv6-note tests counted NET-225's new bridge-mode note.** They now filter it out.
- **CI ShellCheck.** The action's download had broken on `main` too, so CI uses the runner's own shellcheck.
- **Two agents' 5xx allowlists collided.** They are replaced by `public_json()` marking at the source, with AST guards.

## Lessons (wave 2)

- **An agent that starts Codex in the background and goes idle is not woken when Codex finishes.** Agents must run Codex in the foreground, and the lead must check real activity (ListAgents, the worktree's status) before saying an agent is running.
- **Cherry-pick each agent's batch from the merge-base of its branch**, and start follow-ups on fresh branches from the current audit tip. A rebased follow-up then applies cleanly.
- **An allowlist that several agents extend at once conflicts.** Mark the safe value at its source instead.

## Wave 3 (2026-11-09): the device checks, owner-approved

**What ran on the G11:**
- `deploy-release-audit-isolation.sh`: TShark and nginx recreated. Smoke test 28/28.
- `failure-injection-release.sh`:
  - a stopped Suricata, then a stopped Zeek, were each reported (1 s and 22 s) and recovered;
  - after an OpenSearch restart, auth held (Chain 21) and ingestion resumed;
  - smoke test 28/28.
- The rendered UI, once the owner accepted the certificate.
- A benign IDS trigger.

**What it found:**
- **NET-241 (P1, fixed).** Every logged-in full reload of a large page was a 502.
  - Root cause: SvelteKit's `Link` preload header (4.3–4.8 KB, on `main` too) outgrew nginx's 4 KB `proxy_buffer_size`.
  - Fix (`edfdd9a9`): `proxy_buffer_size 16k`, `proxy_buffers 8 16k`. A new bats test fails on the old config, and the smoke test now fails on the nginx error.
  - Delta `/deep-review`: no findings.
  - Deployed. Home and Live reload. Smoke test 29/29.
- **NET-242 (P2, open).** With Suricata stopped, Home's pipeline card says so but Alerts lists older alerts without a word.
- **NET-243 (Low, open).** One alert took 11.3 s from packet to index; the goal is under 10 s.
- **The test domain was blocked.** The LAN's DNS filter answers `0.0.0.0` for `testmynids.org`. The same signature went to example.com in a request header. ET rates the rule Informational, so it is listed under Activity.

**Files changed:**
- `docker/nginx.conf`
- `tests/scripts/test_nginx_conf.bats`
- `scripts/remote/smoke-test-release.sh`
- `scripts/remote/failure-injection-release.sh` (new)
- `scripts/remote/deploy-release-audit*.sh` (BRANCH defaults to main)
- the Debugging trackers

## Lessons (wave 3)

- **An unauthenticated `curl /` can't stand in for a page load.** It gets a 5-byte redirect, so it never meets the headers a logged-in page sends. Reload a real page after a deploy.
- **"Fresh" one second after a sensor restart is the freshness window, not proof that new records flow.** The smoke test's newest-record check, run afterwards, is what shows ingestion.
- **A test domain can be sinkholed by the user's own DNS filter.** Carry the signature to any HTTP site instead of working around the filter.

## Next steps

- [x] Owner: deploy (approval #1), recreate TShark and nginx, failure injection, IDS trigger, certificate. All done 2026-11-09.
- [x] Merge PR #236 (owner, 2026-11-09: "commit pr and merge main please. And deploy all fixes to the G11").
- [ ] NET-242, NET-243, NET-238, NET-239, NET-240 follow-ups.
- [ ] An owner-approved reboot, then the smoke test. A disk-full run on an isolated VM.
