# F4: durable usage ledger and the owner's time zone, 2026-11-18

**Linear:** NET-329 (roadmap project P-NET-1, slice F4)
**Branch:** `feature/f4-usage-ledger` (from `origin/main` 179db7cd)
**Plan:** `plans/2026-11-18-f4-usage-ledger.md`. Codex APPROVED it in round 5 of 5; the full argument is in `plans/2026-11-18-f4-usage-ledger.review-log.md`.
**Status:** implemented and tested locally; PR, merge and G11 deploy follow.

## Problem

- **Monthly usage could go down.** It was summed from whatever raw records still existed (`bandwidth_tracker.get_monthly_usage`), so pruning old daily indices lowered the month's total.
- **Month boundaries were UTC.** Cap warnings, weekly reports and Prometheus need a total that doesn't shrink, in the owner's own days.

## What changed

- **Owner time zone** (`daemon/services/owner_tz.py`, `GET`/`PUT /api/settings/timezone`):
  - It is stored in `/opt/nettap/data/owner-timezone.json`, defaults to UTC, and must be a name in the daemon's zone database (599 names on the G11, old aliases included).
  - An unreadable file keeps the ledger's own zone.
- **Ledger** (`daemon/services/usage_ledger.py`, `usage_days.py`, `usage_report.py`):
  - It lives in `/opt/nettap/data/usage-ledger.json`, holds up to 400 local days, and has one writer: the `usage-ledger` job (every 900 s, 240 s deadline).
  - Each pass:
    1. applies a pending zone change;
    2. updates the index inventory, keyed by UUID;
    3. recounts today and the 2 days before;
    4. continues a saved sweep cursor through older days in 7-day chunks.
  - Each chunk is saved, then published, so a failed save leaves both the published state and the cursor unchanged.
  - A day keeps the recount with the highest internet total (download + upload; local traffic kept beside it), with the split from that same recount.
  - **Coverage loss is permanent.** It is recorded on:
    - a vanished or replaced UUID;
    - a listing that changed during a query;
    - a lower recount;
    - an unknown inventory.

    It blocks replacement by a rules change.
  - **A day is final ("settled")** once it is counted at least 72 h after it ended, with no loss ever seen.
  - **Bootstrap** takes coverage from the index set. Interior gaps are permanently `not_counted`. Today's elapsed UTC dates are checked, but a zone change on install day doesn't count never-captured hours as loss.
  - **Timeouts:** every timeout type is a "continue next run". On the third in a row the chunk is recorded as failed.
- **OpenSearch:** the ledger has its own no-retry `ExactTermsOpenSearch` client. One `Budget` covers every send, including the wrapper's larger-terms re-ask and the gateway `msearch`. `ExactTermsOpenSearch.msearch` and `gateways_if_needed` gain an optional `budget`; with `None` every existing caller is unchanged.
- **API** (`daemon/api/usage.py`):
  - `GET /api/usage/daily` and `GET /api/usage/month` return per-day status (`future`, `not_counted`, `stale`, `pending`, `recount_pending`, `old_rules`, `approximate`, `counted`), each day's UTC `start`/`end`/`cutoff`, and a projection only when every elapsed day is counted.
  - `POST /api/usage/recount` requests a fresh sweep.
  - `/api/bandwidth/cap` reads the ledger. The old UTC computation is kept as OLD CODE.
- **Web:**
  - The Bandwidth page uses the owner's month: the KPI row, the cap meter, the daily chart (from the month reply's days, with non-final days flagged) and the device card.
  - The chart's click and drag use each day's real bounds (`bucketWindow` takes a point's optional `end`).
  - A one-click "Count in <browser zone>?" notice appears while the zone is unset.
  - Settings › Display has a time-zone select with the warning.

## Tests

- **Daemon:** 5,422 passed and 5 skipped (from 5,360). New:
  - `test_usage_ledger.py`;
  - `test_usage_api.py`;
  - cases in `test_bandwidth_tracker.py`, `test_exact_terms.py` and `test_device_accounting.py`.
- **Lint:** ruff 0.17.3 check and format are clean.
- **Web:**
  - vitest: 5,767 passed;
  - svelte-check: 0 errors (2 old warnings);
  - `check:colors` and `check:e2e`: clean;
  - `test:visual`: 385 passed, 64 skipped.

## Gates

- **`/codex-review` on the plan:** APPROVED in round 5 after 29 findings (12 + 10 + 5 + 2). Every finding was taken.
- **`/deep-review`:** no findings. The report is in `security-reviews/feature-f4-usage-ledger/`.
- **`/ponytail-review`:** six findings, all fixed:
  1. **A zone change on install day marked today approximate for good** (a real bug east of UTC). Bootstrap now takes a floor from the old ledger.
  2. **The page fetched the month's days twice,** so the KPI total and the chart could disagree. The chart now uses the month reply.
  3. **A fixture test asserted the wrong sum.**
  4. **An unknown inventory plus a failed listing let a pass continue.** It now stops before any recount.
  5. **Small duplicates.**
  6. **The deploy check would fail on a re-run once a zone was set.** It now compares yesterday in the ledger's own zone over that day's exact bounds.

- **Two-angle review on PR #337** (security engineer, Python reviewer, TypeScript reviewer): no critical issues. Fixed in the second commit:
  - **Python, HIGH: one OpenSearch outage burned the whole sweep.** Every chunk failed in one pass, and every older day showed `stale` for about 24 h. On the G11, OpenSearch answers 401 after every recreate until the bootstrap runs. Now:
    - a listing failure ends the pass before any recount;
    - a failed chunk stops the run, so an outage costs one chunk per run.

    Today's figure pauses for that pass too.
  - **Python, MEDIUM:**
    - `updated_at` moved on failure-only saves. It now moves only on a successful recount.
    - No test caught the gateway check losing its budget. One does now.
  - **Python, LOW:**
    - `SerializationError` and malformed buckets escaped the chunk handler. `LEDGER_QUERY_ERRORS` is now `(QueryFailed, OpenSearchException)`, and malformed replies are `QueryFailed`.
    - A chunk could start with under 1 s left. It now needs at least 30 s.
    - The time-zone write ran on the event loop. It now runs off it.
    - A corrupt time-zone file logged a warning on every request. It now logs once per distinct error.
  - **Security, LOW:**
    - A second zone change overwrote the only kept copy of the old ledger. Copies are now `usage-ledger.gen<N>.<last save>.json` and `usage-ledger.corrupt.<time>.json`, never overwritten. This replaces the plan's single `.prev`.
    - A recount request restarted a running sweep. While one runs, it is now a no-op.
  - **TypeScript, MEDIUM:**
    - A click on a day with no figures told the moment page "0 B".
    - There was no way to confirm UTC. Save is now enabled while the zone is unset, and the notice has a "Keep UTC" button.
    - The empty Daily rate card promised a figure this month when counting began mid-month.
    - Test gaps for the unsaved guard, stale responses, the `flagged` markers and a failed refresh.
  - **TypeScript, LOW:**
    - The month reply is validated.
    - `Intl.supportedValuesOf` is guarded.
    - The chart's window end is clamped.
  - **Accepted, not changed:**
    - A failed month request also holds back the device card, so every card always covers the same month.
    - Zone names vanishing from the image's zone database: tzdata keeps old names as links.
  - **After the fixes:**
    - daemon: 5,434 passed;
    - web: 5,784 passed;
    - svelte-check, colours and `check:e2e`: clean.

## Deploy

`bash scripts/remote/deploy-usage-ledger.sh`:

1. A baseline taken once the daemon's memory has settled.
2. A build of the daemon and web containers.
3. A forced full recount of every stored day, watched for swap, OpenSearch memory and API latency.
4. Yesterday compared against a raw count.
5. A repeat run, a restart and another run, checked to leave every total unchanged.
6. The ledger file's size, start date and gaps.
7. The daemon's settled memory.

### G11 results, 2026-11-18

PR #337 was merged as `476f4c1d`. The script ran twice: first from `main`, then from `fix/f4-deploy-measurements` with corrected measurements.

- **The recount:** a forced full sweep of every stored day finished in one run, in 1 chunk, with 0 failed chunks. The G11 holds 6 days: `since` is 2026-11-13, with no gaps.
- **Agreement with raw data:** yesterday (2026-11-17, UTC) reads 120,291,776,434 bytes in the ledger and 120,291,776,434 in a fresh raw count. Both runs matched exactly.
- **Stability:** a repeat run, a daemon restart and another run changed no total in the 4 days compared.
- **Ledger file:** 2,479 bytes for 6 days.
- **Swap:** 3,537 MB before, 3,540 MB peak during the sweep.
- **API latency:** `/api/bandwidth/daily` stayed at 692 ms, with no rise.
- **OpenSearch:** its heap is capped at `-Xms3g -Xmx3g`.
  - The first run's ✗ ("4,231 → 4,601 MB") came from `docker stats`, which counts active file cache: the index pages the sweep had just read, which the kernel can reclaim.
  - The cgroup's anonymous memory was 3,869 MB right after the sweep and 3,868 MB later.
  - On the second run, the docker stats figure didn't move during the sweep (4,689 → 4,689 MB).
- **Daemon:** 364 MB once settled, after 3 minutes of uptime, the same as F1's settled 364 MiB. So F4 adds no measurable daemon memory.
  - Both runs showed a ✗ at about 1.2 GB. Step 9 measured the daemon right after step 8 restarted it, during the start-up peak, which F1 also recorded (VmHWM 1.21 GB).
  - The first run's "before" figure of 6 MB was the script's own `sh -c`. The daemon shares the host's PID namespace.
- **Script fixes (`fix/f4-deploy-measurements`):**
  - the daemon is read through `docker top`;
  - OpenSearch is judged on its cgroup's `anon` memory;
  - a fresh daemon is read only after 5 minutes of uptime.

  Each probe was checked on the G11. The 5-minute wait has not yet run inside a full deploy.
- **Running a branch:** to deploy one, check it out on the device first, as in `git checkout <branch> && git pull`. The second run let the script pull itself mid-run, so step 1 ran the old version of its functions.

## Lessons

- **A plan review earns its keep on data that can't be recomputed.** Codex found 29 ways a "never goes down" figure could still lie: a rules change erasing a pruned day, a prune between listing and query, recreation under the same index name, retries escaping the deadline, and today's gap at bootstrap.
- **"Missing raw data" means two different things:** pruned (loss) and never captured (not loss). Any coverage check needs a floor for when capture began.
- **One reply, one snapshot.** A page that builds a total and its breakdown from two requests can show them disagreeing.

## Next

- PR, the two-angle review, squash merge, then deploy to the G11.
- Then #6, data cap warnings (NET-339), on the ledger.
