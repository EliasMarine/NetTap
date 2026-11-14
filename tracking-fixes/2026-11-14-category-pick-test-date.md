# Alert category pick test aged out on 14 Nov, 2026-11-14

**Linear:** NET-274
**Branch:** `fix/category-pick-sub-filter`
**Status:** test-only fix. Nothing to deploy.

## Problem

`category-drilldown.test.ts` › "a pick clears the sub-category filter, which the chart never applied"
failed on main every run from 2026-11-14 10:01 UTC: `expected 2 to be greater than 2`.

## Root cause

- The test's stubbed timeline slots are fixed at 2026-11-13 10:00Z. The page asks for the rolling
  last 24 hours, and the stub echoed that window back.
- Once 10:00 on 13 Nov fell outside the last 24 hours, `bucketWindow` clipped the picked slot to a
  window whose `from` was after its `to`. `customRange` rejects that, so nothing refetched.
- No commit broke it: an unchanged copy passes with the clock pinned at 2026-11-14 10:00Z and fails
  at 10:02Z.
- Real users were not affected. The daemon's category timeline (`daemon/api/alerts.py:2073`) only
  returns slots inside the request's own window.

## Fix

The failing test's stubbed reply now carries the fixed window `F`..`T` that holds its slots, as the
test above it already does.

## Tests

- The file passes 9 of 9 at the real clock, at 2026-11-13T10:30Z and at 2027-06-01.
- Mutation check: removing `subCatFilter = null` from `pick()` makes the fixed test fail.
- Full Vitest: 5225 passed. svelte-check: 0 errors.

## Lessons

Same class as NET-250: a test with fixed timestamps must also fix the window it is judged against,
or it ages out.
