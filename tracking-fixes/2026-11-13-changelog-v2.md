# Changelog v2: what each device did, with drill-down, 2026-11-13

**Linear:** NET-272
**Branch:** `feature/changelog-v2`
**Status:** built and tested locally; deploy to the G11 after merge with `scripts/remote/deploy-changelog-v2.sh`.
**Plan:** `PLAN.md` in the worktree (Codex review, 4 rounds, APPROVED). The log is kept in `.codex-review/`.

## Why

The owner asked for a Changelog page with more information: first and last seen, how long a device was
connected, its IP address and what it transferred, with drill-down from the page. The old page listed thin
events ("New device aa:bb:…") with metadata chips and led nowhere.

## What changed

- `/changelog` loads the events and the existing device list (`GET /api/devices`, the Devices page's own
  NET-226 accounting) over the same window, and joins them in the browser (`changelog-rows.ts`). No daemon change.
- A device's figures are the sum of every list row with its MAC. The daemon groups traffic by IP, so the
  detail panel says the figures are counted per address.
- The table shows When, Event, What, IP (joined at), First seen, Last seen, Seen over, Sent, Received and
  Connections. Every column sorts, and "—" sorts last.
- "Seen over" is first to last record in the range, gaps included. It is not called a connection time,
  because the data cannot prove one.
- Missing figures show "—" with the reason: not a device event, the device list failed, or no address-level
  figures matched.
- KPIs cover matched devices only, and say so. The page states each coverage gap: events capped at 1,000
  (the uncounted part of the chart is a gap and cannot be picked), only the 500 busiest addresses have
  figures, and IPv6 notes.
- The hero chart counts events per bucket. A click or drag narrows the table (`?pickFrom`/`?pickTo`, built with
  `bucketWindow()`). It never changes a figure.
- The detail panel shows destinations from the busiest matched address, never the address the device joined at.
  Its links keep the window: `/devices/<ip>?from&to`, Log Explorer for that window, and the device overview.
  Focus moves to it and back to the row.
- The CSV and JSON exports carry the joined columns. The CSV puts `'` before cells starting with `= + - @`,
  tab or CR, against spreadsheet formula injection.

## Files

`web/src/routes/changelog/{+page.svelte, ChangelogTable.svelte, ChangelogDetail.svelte, changelog-rows.ts}`
plus tests, `web/e2e/visual/fixtures/changelog.ts`, `scripts/remote/deploy-changelog-v2.sh`.

## Verification

- `npx vitest run`: 389 files, 5,159 tests passed (main: 387, 5,110). svelte-check: 0 errors, the 2 existing
  warnings. `check:colors`: clean. `npm run build`: passes. Visual harness for /changelog: 6 passed,
  1 skipped by design.
- `/deep-review`: no findings. `/ponytail-review`: one nice-to-have (two identical handlers), fixed.

## Lessons

- The device list is per address, not per device. Any per-device figure built on it must sum by MAC and say so.
- Min and max record times are not a connection duration. Name the figure for what it measures.

## Next steps / follow-ups

- New event types (a device left or went quiet) need a writer in the daemon first.
- Log Explorer's CSV export has the same formula-injection gap.
