# Extreme years in a time window are a 400, 2026-11-14

**Linear:** NET-275
**Branch:** `fix/time-range-extreme-years`
**Status:** done. PR #283 merged (`ac99aaac`); verified on the G11 at `d39ecfcb` (`deploy-triage-fixes-2-2026-11-14.sh` steps 5-6, every check passed).

## Problem

A signed-in request with an extreme window crashed after OpenSearch had already been queried:

- `GET /api/devices/registry/<mac>/traffic?from=9999-12-31T23:59:59Z&to=9999-12-31T23:59:59Z`
- the same with `from=to=0001-01-01T00:00:00+14:00`
- the IP device page (`/api/devices/<ip>`) with either window

The device searches ran, then `time_slots` raised `ValueError: year 10000 is out of range` (or
`year 0`). The handlers catch only `QueryFailed` and `OpenSearchException`, so
`safe_error_middleware` logged a traceback and answered a generic 500. Rated Low: a log traceback
and a few wasted queries.

## Root cause

`parse_time_range` (`daemon/api/time_range.py`) accepted any year Python can parse. Both values
parse, compare and pass the slot budget (one slot). But the last slot of `9999-12-31T23:59:59Z`
ends in year 10000, and `0001-01-01T00:00:00+14:00` is year 0 in UTC.

## Fix

`parse_time_range` now converts each bound to UTC and answers 400 unless its UTC year is from 1970
to 9998: `{"error": "from must be a time between 1970 and 9998"}` (or `to`). A bound that
overflows on the way to UTC gets the same 400. The check runs before the from/to order check, so
it covers every route that calls `parse_time_range` (17 modules, plus `moment` and
`dhcp_timeline` through `devices`), before any search.

- 9998 is the top year because the longest bucket is 1 day: a 1 d slot of 9998-12-31 still ends
  inside year 9999.
- 1970 is the bottom year. The web never sends an earlier one: every range is "last N hours" from
  now (`rangeWindow`), and custom windows come from data timestamps (`customRange`).

- `GET /api/devices/registry/new-count?since=` (found while fixing this) parses `since` itself
  and called `astimezone(timezone.utc)` outside its `try`: `since=0001-01-01T00:00:00+14:00` was a
  500 with an `OverflowError`, and a year-9999 `since` went on to the count. It now uses the same
  1970–9998 rule (`_utc_in_years`), so both are a 400 before the count.

Files: `daemon/api/time_range.py`, `daemon/api/devices_v2.py`, `daemon/tests/test_time_range.py`,
`daemon/tests/test_registry_new_count.py`, `daemon/tests/test_suricata_category_page.py`.

## Tests

- `parse_time_range`: 9999, 0001 at +14:00, 9999 at -14:00 and 1969 (including 1970-01-01 at
  +01:00, which is 1969 in UTC) are refused, for `from` and for `to`. 1970-01-01 and 9998-12-31 are
  accepted.
- Route test through the production stack (`make_app`: token check + `safe_error_middleware`): the
  MAC traffic route and the IP device route answer 400 to both extreme windows, and neither the
  registry client nor OpenSearch is called.
- Before the fix, both routes answered 500 with the `year 10000` / `year 0` traceback.
- `test_suricata_category_page` used `from=1900-01-01` to build a too-long window. It now uses
  1970, which is still far over the slot budget, so it still checks the budget message.
- New-count route through `make_app`: `since=0001-01-01T00:00:00+14:00` and
  `since=9999-12-31T23:59:59Z` both get 400 and `count` is never called. Before the fix: 500 with
  `OverflowError: date value out of range`, and 200 after a count.
- Full daemon suite: 5023 passed, 5 skipped.

## Not changed (time parsed without `parse_time_range`)

- `api/pcap.py` (`iso_param` for from/to), `api/changelog.py` (`iso_param`, absent stays None),
  `api/devices.py` `active_since` (`iso_param`), `api/device_compare.py` (its own checks, which
  already refuse an out-of-range year).

## Follow-up from the security review: two routes' own 1 d slots

`GET /api/alerts/categories?from=1970-01-01T00:00:00Z` and `GET /api/bandwidth/daily?from=…` (same
window) answered 500. 1970 passes the year rule, and both routes build 1 d slots of their own (the
categories sparkline from `_sparkline_interval`, the daily totals in `get_daily_usage`): 20,772 of
them, over `MAX_SLOTS`, so `time_slots` raised `ValueError` and neither route caught it. The
comment "the sparkline interval fits any range" was wrong past about 27 years.

- Both routes now call `slot_interval` before any search, as the chart routes do, with their own
  bucket as the only allowed one: `{sparkline}` for categories, `{"1d"}` for daily. Over budget is
  the usual 400 `TOO_MANY_SLOTS`. The wrong comment is corrected and kept as OLD CODE.
- Behaviour change: the cap is now `SLOT_BUDGET` (1,000 slots, about 2.7 years of 1 d), not
  `MAX_SLOTS` (about 27 years). A stray `?interval=` other than the route's own bucket is a 400.
  The web sends neither: the Bandwidth page asks for the current UTC month, alert categories get
  the range picker's window, and both send only `from`/`to`.
- Test (`test_chart_buckets.py`, through `make_app`): `from=1970-01-01T00:00:00Z` on both routes
  gets 400 `TOO_MANY_SLOTS` and no search. Before the fix both answered 500 with
  `ValueError: 20772 slots of 1d …`.
- Files: `daemon/api/alerts.py`, `daemon/api/bandwidth.py`, `daemon/tests/test_chart_buckets.py`.
- Full daemon suite: 5025 passed, 5 skipped.

## Lessons

Parsing a time is not enough. Every value has to survive the arithmetic done on it later, here a
bucket's slot end in UTC. Check the range where the value enters, not where it overflows.
