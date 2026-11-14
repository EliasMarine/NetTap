# The device-by-MAC page shows its bandwidth chart, 2026-11-14

**Linear:** NET-260
**Branch:** `fix/mac-device-bandwidth`
**Status:** merged in #278. Deployed and verified on the G11 2026-11-14 at `35f684d4` (`scripts/remote/deploy-triage-fixes-2026-11-14.sh`, every check passed): a real device's series was 289 slots of 5m, 52,692,701 bytes, equal to its `total_bytes`.
**Plan:** `PLAN.md` (Codex review, 2 rounds, APPROVED).

## Problem

`/devices/mac/[mac]` draws "Bandwidth over time" only when `traffic.bandwidth_series` exists, and
`GET /api/devices/registry/{mac}/traffic` never sent one. The card never showed.

## Root cause

`DeviceRegistry.get_device_traffic` aggregated totals, protocols and top destinations, but no time
series. The IP device page's route (`/api/devices/{ip}`) has one, so only the MAC page was missing it.

## Fix

- `daemon/api/devices_v2.py`: the route picks the chart's bucket before any search, like the IP route
  (`slot_interval` with `_bandwidth_interval` as the default; a bad `?interval=` or too many slots is a
  400). It echoes `bandwidth_interval`.
- `daemon/services/device_registry.py`: `get_device_traffic` takes the bucket and adds one
  `bandwidth_series` aggregation to the same query (`time_slots` date ranges with `side_sums` per slot),
  parsed into `{timestamp, bytes, download_bytes, upload_bytes}`, the IP page's shape. Same filters as the
  totals, so the series sums to `total_bytes`.
- MAC page: `busiest` stays -1 for an all-zero series, so a quiet device gets the empty state instead of a
  flat chart labelled "Busiest at …". (Codex round 1 found this; `time_slots` zero-fills every slot.)
- Out of scope: click-or-drag picking on this chart (NET-249 target T13), which needs the MAC page to take
  a custom window first.

## Tests

- Daemon: the query is a `date_range` spaced by the bucket and covering the window, with the totals'
  sub-aggs; real range buckets (out of order, epoch-ms) parse in time order; the series sums to
  `total_bytes`; the route defaults to 5m for 12 h, honours `1h`, and answers 400 for `7s` and for 1m over
  7 days before any search. All three failed before the fix.
- Web: the card draws with its "Busiest at …" label; an all-zero series shows the empty state (failed
  before the `busiest` change).
- Daemon pytest: 5012 passed, 5 skipped, 0 failed. Vitest: 5226 passed, 1 failed (NET-274, pre-existing,
  fixed in PR #277). svelte-check: 0 errors.

## Reviews

- /ponytail-review: ship.
- /deep-review: no findings (`security-reviews/fix-mac-device-bandwidth/`).
- Two-angle review:
  - Security-engineer: no Medium or above. Its Low (extreme from/to years give a 500 on the device
    traffic routes, in `parse_time_range`) is filed as NET-275.
  - Code reviewer, one Medium: the card hid itself while traffic loaded or failed, which breaks design
    rule 6. It now shows CardState loading and error like its sibling cards (second commit). The
    reviewer also found the same all-zero "Busiest" bug on the IP device page (`devices/[ip]`), which
    is fixed there too.
- Review-fix tests (each failed first): the MAC card shows "Loading bandwidth over time" while another
  range loads, and the error inside the card on a 503; the IP page shows "No traffic in this range" for
  an all-zero series. Device tests 167 of 167, svelte-check 0 errors, visual `devices` 18 of 18.

## Deploy

`scripts/remote/deploy-triage-fixes-2026-11-14.sh` rebuilds the daemon and web, then checks that a
device's series sums to its `total_bytes` (with the NET-268 and NET-257 checks from the same day).

## Lessons

- A plan that says "filed as a separate bug" needs the issue filed at the time (this one was found unfiled).
- A zero-filled series needs its "busiest" pick to start from 0, not -1.
