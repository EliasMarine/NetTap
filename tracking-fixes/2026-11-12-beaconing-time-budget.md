# Beaconing scan: time budget and faster query, 2026-11-12

**Linear:** NET-187
**Branch:** `perf/beaconing-time-budget`
**Status:** code and tests done; device deploy pending (`scripts/remote/deploy-beaconing-budget.sh`).

## Why

A live beaconing scan took 15 s for 24 h and 63 s for 7 d on the G11. The threat report waited for it, and nothing
stopped it, so a 30 d window on a full month of data would end in the web proxy's generic failure after 120 s.

## Root cause (measured on the G11, read-only, 2026-11-13 UTC)

- **Where the time goes:** the report with `?snapshot=` (beaconing from the background store, everything else live)
  took 0.9 s (24 h), 2.7 s (7 d) and 1.7 s (30 d). The live report took 16.1 s, 60.9 s and 62.2 s. So the time is
  the beaconing scan. The G11 holds about 4 days of data, so 7 d and 30 d scan the same records.
- **Inside the scan:** the candidate list took 1–2 s. The batch histograms took 14.9 s (24 h) and 59.3 s (7 d), with
  OpenSearch's own `took` at 12.9 s and 52.2 s. Paging the one oversized pair took 0.8 s.
- **Inside a batch:** each pair was its own three-`term` clause. A `term` on an ip or port field rebuilds the busy
  source's whole record set, 500 times per batch. The `date_histogram` under `multi_terms` cost as much as the rest
  of the aggregation.

## What changed

- **Faster batch query** (`daemon/services/threat_detection.py`, `_batch_slots`):
  - One clause per (source, port), with that group's destinations in one `terms`. Each pair is exactly one source,
    port and destination, so the query matches the same records.
  - A numeric `histogram` on `@timestamp` with a 10,000 ms interval gives the same 10 s slots. Its keys come back
    as doubles and are turned into ints.
  - The old body is kept under OLD CODE markers.
- **Time budget** (`BEACON_BUDGET_SECONDS = 60` in `daemon/api/threats.py`, reusing `Budget`, `TooSlow` and the
  drill-downs' `_SLOW` message):
  - Each request the scan sends first checks the budget: the candidate list, every batch, and every page of
    `all_buckets` (new optional `budget` parameter).
  - A search the client gave up on (`ConnectionTimeout`), or one OpenSearch stopped at its own limit (the new
    `SearchTimedOut` subclass of `PartialResultsError` in `storage/exact_terms.py`), is `TooSlow`. A search with
    failed shards stays an ordinary failure.
  - The background snapshot scan passes no budget: nobody waits for it, and its 30 d scan must finish.
- **Nobody waits past the deadline:**
  - **Beaconing route (live):** waits until the budget runs out, then answers 503 "Working this out took too long.
    Try a shorter time range." A scan still queued in the route pool never starts.
  - **Threat report:** beaconing runs on its own 2-thread pool and is waited for until the budget runs out. The
    report then goes out with every other section, and beaconing in both `failed_checks` and the new
    `timed_out_checks`.
  - **Backstop:** the whole report gets 90 s (`REPORT_WAIT_SECONDS`), then a 503.
- **/threats page:** when beaconing ran out of time, the KPI says "Not checked in time: try a shorter range". The
  card says "Couldn't check for beaconing: this window is too large to check in time." and "Try a shorter range."
- **The threat score is unaffected:** beaconing adds no points (`Debugging/THREAT-SCORING.md`).

## Same results, shown on real data

Old and new scans ran back to back on the G11 over the same fixed window, comparing every pair's full slot list:

| window | old | new | pairs | slots | findings |
|---|---|---|---|---|---|
| 24 h (new first) | 13.2 s | 8.1 s | 3,313 = 3,313 | 381,350 = 381,350, 0 pairs differ | 786, identical |
| 24 h (old first) | 15.3 s | 6.2 s | 3,313 = 3,313 | 1 pair differs by 1 slot | 786, identical |
| 7 d (new first) | 63.4 s | 24.7 s | 9,623 = 9,623 | 1 pair differs by 1 slot | 998, identical |

Each one-slot difference is a record indexed between the two runs. In the 7 d case, a conn record with
`@timestamp` 01:19:41 was ingested at 01:42:42, and only the later run saw it.

## Tests

- **Daemon:** 19 new tests in `daemon/tests/test_beaconing_budget.py`; 18 of them fail on the old code. The 19th
  guards that the background scan's call has no time limit.
  - the batch query matches only the batch's pairs, and its keys are ints;
  - the budget stops the scan before the first search, after the candidate list, while paging candidates, and
    while paging a busy pair;
  - `all_buckets` checks its budget before every page;
  - `ConnectionTimeout` and a `timed_out` reply through the real `ExactTermsOpenSearch` are `TooSlow`; failed shards
    are not;
  - the report marks a time-out and keeps every other section, and another failure is not called a time-out;
  - the routes: 503 with the reason, at the deadline while the scan hangs, a queued scan never starts, a report
    with HTTP 200 and the other sections, and the report backstop.
  - `FakeOpenSearch` gained a numeric `histogram`. The route fakes in `test_beacon_snapshots.py` take `budget`.
- **Web:** 2 new tests in `threats-beaconing.test.ts`: the time-out wording, and that a plain failure still says
  "the query failed".
- **Results:**
  - daemon: 2 failed, 4,680 passed, 4 skipped. Baseline was 2 failed and 4,661 passed; the same two date-dependent
    `test_cert_monitor` failures.
  - vitest: 4,550 passed (baseline 4,548). svelte-check: 0 errors, 2 warnings (unchanged).
  - `check:colors` clean. `ruff check` and `ruff format --check` clean. `shellcheck` on the deploy script clean.

## Lessons

- Measure OpenSearch's `took` before tuning the client. Here the server did 85–90 % of the work.
- A disjunction of per-pair `term` clauses is expensive on ip and port fields. Group by the shared terms and put the
  varying field in one `terms`.
- `asyncio.run` waits for its default executor's threads when it exits. A check the report may abandon needs its
  own executor.

## Next steps

- Run `bash scripts/remote/deploy-beaconing-budget.sh` on the G11. It times the 24 h report against the 60 s budget,
  checks that 30 d answers within 75 s, and checks that the background scans publish.
- Possible follow-up: `filter_path` to shrink the replies (about 7 s of a 7 d scan is transfer and parsing). It must
  keep `timed_out`, `_shards` and `doc_count_error_upper_bound` for the partial-reply checks.
