# Device traffic compare (NET-265, part of NET-261)

Branch: `feature/device-traffic-compare` (from `origin/main` 89ff557f), PR #265. Status: review fixes in; not yet deployed.

## What changed

- **Daemon:** new `GET /api/moment/device-compare?ip=&a_from=&a_to=&b_from=&b_to=` (`daemon/api/device_compare.py`), registered after the moment routes in `api/server.py`. It sits under `/api/moment/`, so the catch-all proxy already gives it 30 s.
  - One msearch with a body per period. Each body uses Moment's "started" predicate on `source.ip`, the Zeek conn filters, the excluded IPs and a **half-open** `[from, to)` range (this endpoint only; the shared `lte` filter is unchanged).
  - `total` is an independent byte sum. `destinations` is terms `destination.ip`, size and shard_size 10,000, in the default doc-count order, with a bytes sum and the top `destination.as.full`. Bytes are ranked in Python.
  - It runs through `run_drilldown` on the plain no-retry drill-down client (`drill_client`, installed by `register_device_compare_routes(app, drill_client)`), not the exact-terms client. That client re-asks a cut shard at 100,000 terms, which cannot complete a list capped at 10,000 anyway, so a cut shard now just means not exact, after one msearch. Each body carries the budget's remainder as its `timeout`, and the msearch gets it as `request_timeout`; a timed-out reply is a 503 "took too long".
  - Each period reports `list_complete` (`sum_other_doc_count == 0`) and `buckets_exact` (`storage.exact_terms.truncated()` is false).
  - Per period, `list_complete` and `buckets_exact` replace the plan's single `destinations_at_least`: the destination count is a lower bound when that period's list is incomplete, and null when its counts are not exact. One top-level flag would have marked a complete period as "at least" too.
  - What is returned: if both are complete and exact, `new`, `gone` and `changed`. If exact but a list is incomplete, `new`/`gone` are null and `changed` (destinations listed in both) has `partial: true`. If either period is not exact, only the totals are sent (`exact: false`, `destinations: null`, every list null).
  - Lists are capped at 50, each with its full `total`. Validation answers a 400 with a plain sentence for: ip not an IP literal; a time missing or not ISO; a time out of range (year 1 at +01:00 overflows); from >= to; lengths more than 1 s apart; either period over 7 days; overlapping periods; a period ending more than 60 s in the future.
- **Web:**
  - `web/src/lib/api/device-compare.ts` is the typed client with a shape check. It requires null where the daemon withholds a list, and cross-checks the flags: `exact` must equal both periods' `buckets_exact`, `complete` must equal `exact` and both `list_complete`, and `changed.partial` must equal `!complete`.
  - `web/src/lib/utils/device-compare.ts` holds the lengths, the default starts, the periods built from datetime-local text, the scope line and the summary wording.
  - `web/src/lib/components/DeviceCompareCard.svelte` is the card: length select, two start inputs, Compare, the always-visible scope line, the compared periods in the browser's time with its offset, the summary, and three `DataTable`s ("New in the second period", "No longer seen", "Largest changes" with an arrow and a sign, in neutral text) with "and N more". A partial changes list reads "Largest changes among destinations listed in both periods" and "and at least N more".
  - Any input change clears the result, the controls are off while a compare runs, and a result shows only for the IP it was asked for. The grids use `minmax(min(…, 100%), 1fr)`, so nothing overflows at 390 px.
  - On `/devices/[ip]`, a "Compare periods" head-action button (shown once the device loads) opens the card, keyed by IP, scrolls it into view and focuses Length.

## Why

The Moment breakdown is a top 5, so it cannot say what a device started talking to, or stopped talking to, between two periods.

## Checked on the G11 (read-only, 2026-11-13)

- Busiest LAN device, 24 h vs the 24 h before, using the real msearch body (shard_size 10,000, as the exact-terms client sends):
  - 312 ms and 426 ms per period (0.83 s with SSH)
  - 2,753 and 5,919 destinations
  - `sum_other_doc_count` 0, error 0: complete and exact
  - bucket byte sum equals the independent total in both periods
  - 273 and 701 buckets with no AS organisation (LAN destinations and the like), so `org` is nullable
- The same device over 7 days: 549 ms, 10,000 buckets, `sum_other_doc_count` 966, error 0. This is the "exact but incomplete" case, which is real at 7 days for a busy device. The 7 days before had no data (retention).

## Tests

- `daemon/tests/test_device_compare_api.py` (22): boundary fixture (records on A's start, on A/B's shared edge, on B's end), the predicate and half-open range in each body, one budget for both reads, either order, token required, the 50 cap with full count, the list-incomplete case (sum_other > 0, error 0, through a smaller terms size), the not-exact cases (error > 0 after exactly one msearch, error -1, a cut sub-list, only the first period cut), an excluded source counting nothing, validation 400s (both 7-day caps, out of range, the 60 s skew either side), shard failure 502, a timed-out reply 503, a plain OpenSearch failure 502 "failed", ConnectionTimeout 503, a short reply 502, and a G11-shaped reply.
- Web: `device-compare.test.ts` (client, 15), `utils/device-compare.test.ts` (11), `DeviceCompareCard.test.ts` (9: defaults, request, results, length change, 400 sentence, missing start, incomplete, not exact, empty, one at a time), and the page toggle in `device-detail-lan.test.ts`.
- Full daemon pytest: 4838 passed, 0 failed (baseline 4816). Full vitest: 372 files, 4902 passed. svelte-check: 0 errors. check:colors: clean. ruff 0.17.3 format --check and check on daemon/: clean.

## Lessons

- At 7 days a busy home device already passes 10,000 destinations, so the incomplete path is a normal result, not a corner case.
- Many destinations carry no `destination.as.full`, so the org must be optional all the way to the UI.

## Next steps

- Deploy and verify on the G11 (PLAN verification 4: a busy device, 24 h vs the 24 h before).
- shortcut: the compare keys on the IP, so after an IP change the earlier traffic sits under the old address. Upgrade when compare keys on MAC.
- shortcut: datetime-local has no zone, so a start in the hour a DST change repeats reads as its first occurrence and the default periods can overlap; the daemon's overlap 400 says so.
