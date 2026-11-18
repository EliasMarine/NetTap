# F4: Durable usage ledger, 2026-11-18

**Linear:** NET-329 · **Roadmap:** `plans/2026-11-18-feature-roadmap.md` §8 F4, decision D4 · **Depends on:** F1, merged as #336 (`179db7cd`)
**Branch:** `feature/f4-usage-ledger` (from `origin/main` 179db7cd) · _Revised after Codex rounds 1–4 (see §10–§13)_

## 1. What the owner gets

- **Monthly usage that never goes down** when old raw data is pruned.
- **Counted in the owner's time zone.**
- **Honest about gaps.** The page says:
  - "counted since <date>";
  - "still counting" while a first count or rebuild runs;
  - "approximate" for days whose raw data was pruned before their totals settled;
  - "counted under earlier exclusions" when a total couldn't be recounted under the current rules;
  - "not updated since <time>" when recounts are failing.
- **The whole Bandwidth page uses the owner's month:** the KPI row, the daily chart and the device card. `/api/bandwidth/cap` uses the same ledger. #6, #1 and #12a will read the same API later.

## 2. Facts this plan rests on (code at 179db7cd)

- **Monthly usage today** comes from `BandwidthTracker.get_monthly_usage` (`daemon/services/bandwidth_tracker.py:149`). It covers a UTC month and is recomputed from raw `arkime_sessions3-*` on every request.
  - Filters: `_base_filters()` (zeek conn and `CONN_ACCOUNTING`) and the excluded-IP `must_not`.
  - Aggregation: `_bytes_aggs()` and `direction_aggs(lan_filter, gateways)`, then `split_direction()` (`device_accounting.py:330/430`).
  - **upload + download = orig + resp − local**, so the total doesn't depend on the gateway/inbound classification. That classification only moves bytes between upload and download.
- **Client:**
  - The production client is `ExactTermsOpenSearch` (`storage/exact_terms.py:226`). It raises `PartialResultsError` and `SearchTimedOut`.
  - Its `search(budget=Budget)` re-checks the budget before a larger-terms re-ask and refreshes `request_timeout` each send. Its `msearch` takes no budget.
  - `Budget(seconds)` and `TooSlow` (a subclass of `QueryFailed`) live in `storage/snapshot_search.py:44-62`.
  - `server.py:1555` builds a no-retry copy for the moment page: `ExactTermsOpenSearch(**storage.client_kwargs(max_retries=0, retry_on_timeout=False))`.
- **Bandwidth page:** `web/src/routes/bandwidth/+page.svelte:362` takes the UTC month from `utcMonthWindow(now)` for:
  - `getMonthlyUsage` (the KPI row: "Internet this month", "Daily rate", "Days remaining");
  - `getDeviceUsage({from, to})`, the device card;
  - the "Daily usage" chart (`getDailyUsage`), labelled "this month, UTC days" (`:479`).
- **`handle_cap`** (`daemon/api/bandwidth.py:298`) covers the current UTC month.
- **No owner time zone exists on the daemon.** NET-195 removed it, so times are browser-local.
- **Pruning:**
  - `prune_oldest_indices` and `prune_emergency` (`manager.py:515/583`) delete whole daily indices `arkime_sessions3-YYMMDD`, and ISM deletes by age.
  - Logstash can recreate a deleted index under the same name (`manager.py:610`).
  - Malcolm names indices from each record's `@timestamp` (Logstash `%{+YYMMdd}`), so an index holds one UTC day of `@timestamp`.
- **F1 jobs:**
  - `run(deadline)` gets an absolute monotonic deadline. `last_error` comes only from a raised exception.
  - A `request_run` made while the job is running queues nothing.

## 3. Changes from the roadmap text (each with its reason)

1. **A daemon-side owner time zone.** It defaults to UTC until the owner picks one, and #8 and #1 reuse it.
2. **One ledger job, the only writer.** It runs every 15 min: first the last 3 days, then it continues a saved sweep cursor through older days.
3. **A high-water mark on the total, with a coherent split** from the same recount.
4. **Coverage evidence is immutable and blocks destructive recounts:**
   - the first loss is recorded once;
   - a day settles only if no loss was ever seen;
   - a rules change replaces figures only on a day with no loss.
5. **Index identity is the UUID.** The listing is read around every recount query.
6. **Bootstrap coverage comes from the index set,** not the earliest record. Interior gaps are permanent `not_counted` days.
7. **One budget covers every OpenSearch send,** including the wrapper's re-asks, the gateway `msearch` and the inventory.
8. **Save, then publish.** A failed save leaves the published state and the cursor unchanged.
9. **The whole Bandwidth page moves to the owner's month,** and `/api/bandwidth/cap` follows (D4).

## 4. Design

### 4.1 Owner time zone (`daemon/services/owner_tz.py`, new)

- **Storage:** `/opt/nettap/data/owner-timezone.json` holds `{"tz": "<IANA>", "set_at": iso}`. It is written with `write_file_atomic` (0o644). The path comes from env `OWNER_TZ_FILE`.
- **Reading:** `read() -> {"tz", "set", "ok"}`.
  - With the file absent: `{"UTC", set: False, ok: True}`.
  - With the file unreadable or invalid: `{"UTC", set: False, ok: False}`, and a warning is logged.
- **Writing:** `set(name)` requires `name in zoneinfo.available_timezones()`.
- **Routes:**
  - `GET /api/settings/timezone` returns `{tz, set}`.
  - `PUT /api/settings/timezone` takes `{tz}` and returns 200 `{tz, set: true}`, or 400 "That isn't a time zone NetTap knows".
  - After a successful PUT, the handler calls `scheduler.request_run("usage-ledger")`.

### 4.2 Recount (`BandwidthTracker.usage_for_ranges`, new) and the one budget

- **Signature:** `usage_for_ranges(client, ranges: list[(key, start_iso, end_iso)], excluded_ips, lan_filter, budget: Budget) -> dict[key, {download, upload, local, total, connections}]`.
- **Query:**
  - It uses `_base_filters()`, a `@timestamp` range over `[min start, max end)` and the excluded-IP `must_not`.
  - It has one `date_range` aggregation (from inclusive, to exclusive). Each bucket carries `_bytes_aggs()` and `direction_aggs(lan_filter, gateways)`.
  - The result is `split_direction()` per bucket, the same arithmetic as `get_monthly_usage`.
- **One budget for every send.** The ledger builds `Budget(deadline - monotonic() - 5)` per pass and passes it to every call:
  - **The main search:** `client.search(body=..., budget=budget)`. The wrapper checks the budget before each physical send, including a larger-terms re-ask, and refreshes `request_timeout` each time. The body also carries `"timeout": "<max(1, int(remaining) - 2)>s"` so the cluster stops.
  - **Gateways:** `gateways_if_needed(client, ..., budget=None)` gains an optional `budget`, forwarded to `gateway_macs` and then to `client.msearch(body=..., budget=budget)`. `ExactTermsOpenSearch.msearch` gains the same optional `budget` and passes it to `_exact`, exactly as `search` does. With `budget=None` (every existing caller), nothing changes.
  - **Inventory:** `budget.check("the index listing")` comes first. `cat.indices(..., request_timeout=min(10, remaining))`. The min/max search goes through `search(budget=budget)`.
  - **So no send starts after the budget is spent.** A send already in flight is bounded by its own `request_timeout`, which is at most the remaining budget. The overrun is at most one send's timeout, and that timeout never exceeds the remaining budget plus 1 s.
- **Failure adapter:** `LEDGER_QUERY_ERRORS = (QueryFailed, PartialResultsError, opensearchpy.TransportError, opensearchpy.ConnectionError)`. It covers `TooSlow` and `SearchTimedOut`, which are subclasses.
- **Client:** the ledger gets its own `ExactTermsOpenSearch(**storage.client_kwargs(max_retries=0, retry_on_timeout=False))`.

### 4.3 Ledger (`daemon/services/usage_ledger.py`, new)

**File:** `/opt/nettap/data/usage-ledger.json` (env `USAGE_LEDGER_FILE`), mode 0o644, bounded to the newest 400 days.

```
{version: 1, generation, tz, since,
 sweep: {id, cursor: "YYYY-MM-DD" | null, started_at, finished_at, chunks_done},
 inventory_ok: bool,
 indices: {uuid: {name, min_ts, max_ts}},
 gaps: ["YYYY-MM-DD", ...],                      # days without raw coverage when counting began
 days: {"YYYY-MM-DD" (local): {
     total, download, upload, local, rules,      # one coherent recount
     counted_at, cutoff,                         # cutoff: end of the range queried (today: query time)
     coverage_lost_at?,                          # first loss or unknown coverage; never cleared
     settled_at?,                                # only ever set while coverage_lost_at is absent
     failed_at?, error?}}}
```

**Single writer; save, then publish (Codex r2 #3).**
- Only the `usage-ledger` job thread changes the ledger. Each step builds a new state dict from the published one, writes it with `write_file_atomic`, and only then swaps the published reference. The swap happens under a `threading.Lock` held for the assignment alone.
- **If the save fails:** the published state, including the cursor, is unchanged. The pass stops and raises `UsageLedgerIncomplete` ("couldn't save the usage ledger: …").
- The API reads `ledger.snapshot()`.
- A time-zone PUT writes only `owner-timezone.json`.

**Rules hash:** `sha256` over the sorted excluded IPs, the LAN CIDRs and `LOCAL_DESTINATIONS`. It is read once at the start of a pass from `app["excluded_ips"]` and `app["lan_filter"]` (passed as callables). When it differs from the previous pass's hash, a sweep becomes due, so unpruned days are recounted under the new rules.

**Merge, per day D with recount `r` under the pass's `rules`:**
- **No entry:** store `r` with `rules`, `counted_at` and `cutoff`.
- **Same rules:**
  - When `r.total >= stored.total`, replace all four figures with `r`'s.
  - When it is lower, keep the stored figures and set `coverage_lost_at` if it is absent; a drop is evidence.
  - `counted_at` and `cutoff` are set, and `failed_at` and `error` are cleared.
- **Different rules:**
  - When `coverage_lost_at` is absent, replace with `r` and take the new rules.
  - Otherwise keep the stored figures and their old rules. The API reports this day as `old_rules`.
- **On a failed chunk:** each of its days gets `failed_at` and `error` (the exception name plus 120 characters). The figures are unchanged.

**Coverage evidence (Codex r2 #1, #2).**
- `coverage_lost_at` is set once, at the first evidence, and never cleared or overwritten. The evidence is:
  1. A UUID in the inventory is now missing. That covers deletion, and recreation under the same name, which gets a new UUID. Every local day overlapping its `[min_ts, max_ts]` is marked.
  2. **The listing changed between the reads just before and just after a recount query.** The change is classified (Codex r3 #2):
     - A UUID **missing**, or a name whose UUID **changed**, is loss. Its days are marked.
     - An **added** UUID (a new daily index, or the first index on an empty install) is **not** loss. That recount still sets no `settled_at` for any day in its chunk, because its sum may have missed records in the new index. The next recount repeats it.
  3. A recount lower than the stored total.
  4. **Inventory unknown:** `inventory_ok` is false, or `indices` is missing or unreadable in an existing ledger. **Every** existing day is marked, settled ones included.
     - A settled day stays complete, because it settled first, but its figures can no longer be replaced by a rules change.
     - The inventory then restarts.
- **Settled:** set only when `coverage_lost_at` is absent. It needs a successful recount at least 72 h after D ended locally, with an unchanged listing around its query.
- **Display completeness** is derived. Because settling requires no loss, `settled_at` present means it came first:
  `complete = counted and rules == current and (coverage_lost_at is None or settled_at is not None)`.

**Bootstrap coverage (Codex r2 #5).**
- On the first pass, which starts with an empty ledger, coverage comes from the index set. Each present index gives one covered UTC day: its name date `YYMMDD`. When a name doesn't parse, the UTC days of its `[min_ts, max_ts]` are used instead.
- A **past** local day is covered when every UTC date overlapping its span is covered.
- **Today is never a gap, but its elapsed hours are checked (Codex r3 #1, r4 #1):**
  - Only the UTC dates overlapping `[today's local start, now)` must have an index. Dates still in the future are ignored; at Los Angeles noon, today ends at 08:00Z tomorrow.
  - If an elapsed date has no index (say at 18:00 Los Angeles, 02:00Z, after an emergency prune left only the new UTC date), today gets `coverage_lost_at`. It still counts what survives and shows as `approximate`.
- **`since`** is the first covered past local day, or **today** when no past day is covered. Every uncovered past local day between `since` and yesterday goes into `gaps`. Those days are permanently `not_counted`, and the sweep never recounts them.
- The same rule applies at a time-zone transition, which re-runs bootstrap in the new zone.
- **An empty store:** `since` is today and `gaps` is empty.
- After bootstrap, coverage is tracked only through the evidence rules above. Today, and each new day, is always recounted.

**Time zone.**
- **When a pass reads the time zone:**
  - an unreadable file (`ok: False`) keeps the ledger's own `tz`, which is authoritative, and logs a warning;
  - a valid `set` zone that differs from the ledger's is a transition.
- **The transition, at the start of a pass:**
  1. Write the current ledger to `usage-ledger.prev.json`.
  2. Build a new ledger: `generation + 1`, the new `tz`, empty `days`, the bootstrap rule run in the new zone over the current index set, and a sweep due now.
  3. Save it, then publish it.
- A crash between the steps repeats the transition cleanly on the next pass.
- **Until then,** the API reports `pending_tz`, read from the time-zone file.

**Manual recount (Codex r2 #10):** `ledger.request_sweep()` sets an in-memory flag. The next pass starts a new sweep (`sweep.id + 1`, `chunks_done: 0`), even if one finished recently. No totals are reset.

### 4.4 The job (one entry in `server.py`'s Scheduler list)

**`usage-ledger`** ("Usage totals"): every 900 s, deadline 240 s. Each run, in order, with every step saving and then publishing:

1. **Time zone:** the transition, if due.
2. **Inventory:** update it and apply evidence 1 and 4.
3. **Recent:** one query for today, yesterday and the day before, with the listing read before and after. The `cutoff` for today is the query's start time.
4. **Sweep**, when one is due: none finished in the last 24 h, the cursor is set, a transition happened, the rules changed, or a recount was requested.
   - It walks every ledger day plus every covered day still in raw data, oldest first, from `sweep.cursor`, in 7-day chunks. Days in `gaps` are skipped.
   - **Any timeout anywhere in a chunk is a continuation, not a failure (Codex r3 #4, r4 #2).** That covers `TooSlow` from the budget check, `opensearchpy.ConnectionTimeout` from the transport, and `SearchTimedOut` from the server's `timeout`. They are normalised before the generic failure handling, in its search, gateway lookup or listing reads. On a continuation:
     - the chunk's results are discarded;
     - the cursor stays at that chunk;
     - `chunks_done` is unchanged;
     - the sweep ends for this run, and the next run resumes at that chunk;
     - `sweep.retries` counts the continuations of the chunk at the cursor. **On the third in a row,** the chunk is treated as failed (below), so a chunk that times out every time can't stall the sweep. `retries` resets when the cursor moves.
   - **After a successful chunk:** merge, advance the cursor, increment `chunks_done`, save, publish.
   - **After a chunk that failed with another error:** its days get `failed_at`, `chunks_failed` is incremented, and the cursor advances, so one bad chunk can't stall the sweep. Its days show `stale` until a later recount succeeds.
   - At the end: `cursor = null` and `finished_at = now`.
   - The next run, or a restart, resumes from the saved cursor.
5. **Result:**
   - If any chunk or save failed, the run raises `UsageLedgerIncomplete("<n> of <m> day groups failed: <first>")` after saving what succeeded. F1 records it as `last_error`.
   - Otherwise it returns `{"partial": True}` while the sweep cursor is still set.

**Cost:** one 3-day query every 15 minutes. A full sweep of about 90 days is about 13 week-sized queries, spread over runs by the deadline.

### 4.5 API (`daemon/api/usage.py`, new)

- **`GET /api/usage/daily?from=YYYY-MM-DD&to=YYYY-MM-DD`** takes local dates, inclusive, at most 400 days. It returns:
  ```
  {tz, pending_tz, since, generation, updated_at,
   days: [{date, start, end, cutoff, download, upload, local, total, status, counted_at}],
   # start/end: the local day's UTC bounds (end exclusive; 23 or 25 h on a daylight-saving day);
   # cutoff: the end of what was counted (today: the last recount's query time)
   bytes: {download, upload, local, total}, complete, gaps: [{date, reason}]}
  ```
  - **Each day's `status`** is the first that applies:
    - `future`: after today. It carries no figures, and it is excluded from `gaps` and from `complete` (Codex r2 #7).
    - `not_counted`: before `since`, or in the ledger's `gaps`.
    - `stale`: the last recount failed; or, for today, no successful recount in the last 45 min.
    - `pending`: on or after `since`, counted on no pass yet.
    - `recount_pending`: counted under an earlier rules hash, with no coverage loss; the sweep a rules change starts will recount it (Codex r3 #3).
    - `old_rules`: counted under an earlier rules hash, with coverage loss, so it can't be recounted.
    - `approximate`: coverage was lost before the day settled.
    - `counted`.
  - **`bytes`** sums every day that has figures (all except `future`, `not_counted` and `pending`).
  - **`gaps`** lists each non-`future` day whose status isn't `counted`, with that status as its reason.
  - **`complete`** is true when every non-future day in the range is `counted`.
- **`GET /api/usage/month?year&month`** defaults to the owner's current local month. It returns the same fields for that month, plus:
  - `{year, month, month_start, month_end}`, the local boundaries as ISO with their offsets;
  - `projected`, `daily_rate` and `days_remaining` (Codex r2 #8):
    - `elapsed = today.cutoff - month_start`, in seconds;
    - `daily_rate = total / elapsed × 86400`;
    - `projected = total / elapsed × (month_end - month_start)`. That uses real seconds, so a daylight-saving month has its true length.
    - All three are null for a past month, when `elapsed < 1 h`, or when any elapsed day isn't `counted` (mixed rules, approximate, pending or stale).
- **`/api/bandwidth/cap`** (`handle_cap`) takes its month total from the ledger. The old UTC computation stays in OLD CODE. The response keeps its keys and adds `tz`, `since` and `complete`.
- **`POST /api/usage/recount`** calls `ledger.request_sweep()` and `scheduler.request_run("usage-ledger")`, and returns 202 `{sweep_requested: true, sweep_id: <current id>}`.
- **Errors:** a bad date, an inverted range, or a range over 400 days returns 400. With no ledger yet, the reply is 200 with each non-future day `pending`.

### 4.6 Web (the whole page in the owner's month, Codex r2 #9)

- **Bandwidth page:**
  - **The month:** one `GET /api/usage/month` call gives the month and its `month_start` and `month_end`.
  - **KPI row:** "Internet this month" (`bytes.total`), "Daily rate" and "Days remaining" come from that reply. The cap percentage and meter use `bytes.total` with the cap value from `/api/bandwidth/cap`. The projection shows only when `projected` isn't null.
  - **"Daily usage" chart:** `GET /api/usage/daily` for the month. Each day's bar shows download, upload and local, and a day that isn't `counted` (excluding `future`) gets a visible marker with its status. The subtitle becomes "this month, <tz> days".
    - **Click and drag keep working, on real day boundaries (Codex r3 #5):**
      - each point carries its day's `start` as `timestamp` and its exclusive `end`;
      - `bucketWindow` (`web/src/lib/utils/drilldown.ts:323`) uses a point's `end` when present, instead of `timestamp + stepMs`, so a 23-hour or 25-hour day opens exactly its own window;
      - the chart's reply window is `month_start` to today's `cutoff`, so today's partial bucket is clipped at what was counted;
      - every other chart passes no `end` and is unchanged.
  - **Device card:** `getDeviceUsage({from: month_start, to: month_end, …})`, the owner-local month boundaries, so every card covers the same month.
  - **The month card's subtitle:**
    - "<Month>, <tz>";
    - "Since <since>" when the month starts before it;
    - "Still counting" when a non-future day is `pending`;
    - "Approximate: some raw data was cleared before the day was final";
    - "Counted under earlier exclusions" (`old_rules`);
    - "Not updated since <time>" when stale.
  - **Time-zone notice:** when the zone isn't set, "Days are counted in UTC. Count them in <browser zone>?" with one click. When `pending_tz` is set, "Switching to <tz>…".
  - `utcMonthWindow` stays exported for other callers, with OLD CODE where the page stops using it.
- **Settings › Display:** a "Your time zone" select (from `Intl.supportedValuesOf('timeZone')`), with the warning on change.
- **Client:** `web/src/lib/api/usage.ts`, with `getUsageMonth`, `getUsageDaily`, `getTimezone` and `setTimezone`.

## 5. Failure model

- **The total never goes down** under the same rules.
- **A record is never counted twice.** Every recount is a full sum.
- **Late records** reach their day's next recount: within 15 minutes for the last 3 days, and in the next sweep for older days.
- **A crash or a failed save** loses no published figure. The next pass recounts, and the sweep resumes from the saved cursor.
- **Once coverage is lost, the figures can only rise** (same rules) and never be replaced.
- **Stated limit:** a connection finishing more than 72 h after its day ended, after that day's raw data was pruned, is missed. Such days show `approximate` whenever the loss came first.
- **A lost ledger file** starts a new ledger by the bootstrap rule.

## 6. Tests

**`daemon/tests/test_usage_ledger.py`.** It uses a fake recount backed by an in-memory record list, and a fake inventory with name, UUID and bounds. It covers everything from round 1, plus:

- **Coverage evidence:**
  - settle, then lose the inventory, then prune, then change the rules: the figures are kept and the day is `old_rules` (r2 #1);
  - prune, then a stable recount after 72 h (no settle, because coverage was already lost), then a second prune: the day stays `approximate` (r2 #2).
- **Save before publish (r2 #3):** an injected `write_file_atomic` failure leaves the snapshot, the API and the cursor unchanged, the run raises, and a restart reloads the same totals.
- **Bootstrap (r2 #5):**
  - sparse history (indices for Nov 1 and Nov 3, not Nov 2): Nov 2 is `not_counted` and never recounted;
  - a completely empty store;
  - a local day spanning two UTC dates, one of them missing.
- **Rules (r2 #6):**
  - a rules change triggers a sweep;
  - an unpruned day is replaced;
  - a pruned day is `old_rules`, and the month's projection is null.
- **Future and projection (r2 #7, #8):**
  - mid-month and caught up: future days are excluded from `gaps`, `complete` is true and there's no "Still counting";
  - projection on the first day between passes, under 1 h elapsed (null), and in a daylight-saving month (real seconds).
- **Recount (r2 #10):** `request_sweep` starts a new sweep id even though one finished recently, and totals are unchanged.
- **Today at Los Angeles noon (r3 #1):** at bootstrap and at a transition, today is not a gap; it stays counted through UTC midnight and past local midnight, when it becomes yesterday.
- **Index added mid-query (r3 #2):** no `coverage_lost_at`, no settle from that recount, and the next recount can settle it. Deletion and same-name recreation are still loss.
- **Rules change before the sweep finishes (r3 #3):** days the sweep hasn't reached yet are `recount_pending`, the month isn't complete and has no projection. After the sweep, they are `counted`.
- **Budget runs out inside a chunk (r3 #4):** during the search, during the gateway lookup, and during the after-query listing. The cursor stays, `chunks_done` is unchanged, and the next run redoes that chunk. A non-timeout failure increments `chunks_failed` and advances.
- **Real timeout types (r4 #2):** an `opensearchpy.ConnectionTimeout` and a `SearchTimedOut` reply inside a chunk each keep the cursor and counters. A third consecutive timeout of the same chunk is recorded as failed and the cursor advances.
- **Today's elapsed coverage (r4 #1):**
  - at 18:00 Los Angeles, after only the new UTC date's index survives, today is `approximate`, counts the surviving bytes, and `since` is today;
  - at noon with yesterday's UTC index present, today is `counted`.

**`daemon/tests/test_bandwidth_tracker.py`** gains these cases for `usage_for_ranges`:
- the query shape;
- the same split as `get_monthly_usage`;
- a first reply truncated (more terms needed), with the budget then spent: **no second send** and `TooSlow` (r2 #4).

**`daemon/tests/test_exact_terms.py`** gains a case: `msearch(budget=…)` checks the budget before each send, and `budget=None` is unchanged.

**API tests** (`test_usage_api.py`):
- each status, including `future` and `old_rules`;
- the month boundaries and the projection;
- `/api/usage/recount`;
- the time-zone GET and PUT;
- `handle_cap` from the ledger.

**Web tests:**
- the KPI row, the daily chart and the device card all requested for the owner-local month;
- a rollover where UTC and local months differ (Nov 30 17:00 in Los Angeles);
- `bucketWindow` with per-point `end`: a 23-hour and a 25-hour day, a drag across a daylight-saving change, and today clipped at its `cutoff`. Points without `end` keep today's behaviour (r3 #5);
- every subtitle;
- the time-zone notice and `pending_tz`;
- the Display select;
- visual fixtures.

## 7. Gates

- `/codex-review` on this plan.
- `/deep-review`, which is mandatory.
- `/ponytail-review`.
- The two-angle review.

## 8. Deploy and G11 check (`scripts/remote/deploy-usage-ledger.sh`)

The roadmap rule applies: record `free -m` and `docker stats` before and after, and stop if a container gains more than 50 MB resident or swap rises measurably. Memory is read on settled processes: the script waits until the daemon's `VmRSS` stays within 10% across a minute, at most 5 minutes.

1. **Baseline:** host `free -m`, plus `docker stats` for the daemon, the web and the OpenSearch container.
2. **A real sweep under watch (Codex r2 #10):**
   - Read `sweep.id` from `GET /api/usage/month` (exposed as `sweep: {id, cursor, chunks_done, finished_at}`), then `POST /api/usage/recount`.
   - Every 5 s, sample host swap, the OpenSearch container's memory and `GET /api/bandwidth/daily` latency, until the sweep id has gone up, `finished_at` is newer than the request, and `chunks_done` equals the number of chunks expected from `since`, with `chunks_failed == 0` (r3 #4). The sweep object also exposes `chunks_failed`.
   - The script forces runs if the sweep stops early, up to 6.
   - **✗ if:**
     - swap rises by more than 5% of the baseline;
     - OpenSearch memory rises by more than 200 MB;
     - the API latency's peak passes 3× its baseline;
     - the sweep doesn't finish within 6 runs.
3. **Agreement with raw data:** yesterday's `/api/usage/daily` total equals a fresh raw recount of the same local day, made through `usage_for_ranges` on the main client inside the daemon container.
4. **Stability:** a forced repeat run, a daemon restart and another forced run change no total before today.
5. **Ledger file and memory:** the ledger is under 50 KB, `since` and `gaps` match the index set, and the settled daemon's `VmRSS` is within 50 MB of its pre-deploy reading.

## 9. Risks

- **The first sweep on the G11:** about 13 week-sized queries over several runs. Step 2 measures it, and the chunk size is one constant if 7-day chunks prove heavy.
- **A LAN-range flap** changes the rules hash and starts a sweep. Unpruned days are replaced by recounts, which is still correct. Pruned days go to `old_rules` until the hash flips back.

## 10. Round 1 changes (Codex REVISE, 12 findings, all taken)

| # | Finding | Change |
|---|---|---|
| 1 | A rules change erases a settled, pruned day | loss evidence blocks replacement (made immutable in round 2) |
| 2 | Per-direction maxima invent bytes | high-water mark on the total, with a coherent split |
| 3 | Stale passes commit into a new ledger | one job, one writer; the time-zone transition only in the job thread |
| 4 | Pruning between inventory and query | the listing is read around every query |
| 5 | Same-name recreation | the inventory is keyed by UUID |
| 6 | A partial nightly pass loops on the prefix | a saved sweep cursor |
| 7 | Deadline not enforced | no-retry client and a budget (extended in round 2) |
| 8 | Time-zone reset safety | an unreadable setting keeps the ledger's zone; a crash-safe transition |
| 9 | Wrong exceptions and F1 contract | an adapter over the real errors; the run raises after saving |
| 10 | Staleness and pending hidden | day `status` and `updated_at` |
| 11 | Mixed figures on the card | the card is ledger-only (the whole page in round 2) |
| 12 | Deploy gate measured the wrong process | swap, OpenSearch memory and latency sampled during the sweep |

## 11. Round 2 changes (Codex REVISE, 10 findings, all taken)

| # | Finding | Change |
|---|---|---|
| 1 | Inventory loss still allowed destructive rules recounts | inventory unknown marks **every** day; replacement needs no loss ever |
| 2 | Timestamp completeness could erase earlier loss | `coverage_lost_at` is immutable; settling requires no loss; completeness derived from that |
| 3 | State published before it was durable | save, then publish; a failed save leaves state and cursor unchanged and raises |
| 4 | The wrapper's re-ask and the gateway `msearch` escaped the deadline | one `Budget` on every send; `msearch(budget=)` and `gateways_if_needed(budget=)` added with `None` defaults |
| 5 | Bootstrap coverage inferred from the earliest record | coverage from the index set; interior gaps are permanent `not_counted` |
| 6 | Kept totals under old rules counted as complete | `old_rules` status; projection null for mixed months; a rules change starts a sweep |
| 7 | Future days showed "Still counting" | `future` status, excluded from gaps and completeness |
| 8 | Projection had no cutoff | per-day `cutoff`; elapsed from today's cutoff, in real seconds over local month bounds |
| 9 | The rest of the page stayed on the UTC month | the daily chart and the device card use the owner's month too |
| 10 | The deploy might not exercise a sweep | `POST /api/usage/recount`; the check waits for a new `sweep.id` and its chunk count |

## 12. Round 3 changes (Codex REVISE, 5 findings, all taken)

| # | Finding | Change |
|---|---|---|
| 1 | Bootstrap could make today a permanent gap | only past days can be gaps; today is always recounted |
| 2 | An index added during a query became permanent loss | listing changes are classified: missing or replaced UUID is loss; an addition only defers settling |
| 3 | Recountable days under old rules fell through to `counted` | a `recount_pending` status; every rules mismatch is non-complete and nulls the projection |
| 4 | Budget running out inside a chunk skipped it and inflated counts | it is a continuation (cursor kept, `chunks_done` unchanged); other failures increment `chunks_failed`; the deploy check requires zero |
| 5 | The chart's drill-down assumed 24-hour buckets | per-day `start`/`end`/`cutoff` in the API; `bucketWindow` uses a point's `end` when present |

## 13. Round 4 changes (Codex REVISE, 2 findings, both taken)

| # | Finding | Change |
|---|---|---|
| 1 | Exempting today hid the loss of its elapsed hours | the elapsed UTC dates of today must have an index, or today is `approximate`; `since` is today when no past day is covered |
| 2 | Real timeout exceptions took the failure branch | every timeout type is a continuation; on the third in a row for one chunk it is treated as failed, so the sweep can't stall |
