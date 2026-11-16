# Chart dead spots and the Home chart resize, 2026-11-16

**Linear:** (the lead files it)
**Branch:** `fix/chart-gaps-and-resize` (base `origin/main` 9ce4f415)
**Status:** Fixed on the branch, web tests pass, not yet deployed on the G11

## What the owner reported
1. "In some charts like the live traffic charts for a device, there are empty or dead spots that are blank."
2. "For the homepage chart, on initial load, the chart abruptly changes size to fit its container."

## What was measured
- **Live bandwidth on the G11** (read-only, polled like the device page): every reply has 150 slots of 2 s. On a first view, 114 of 150 (one device) and 131 of 150 (another) had no rate ("Not measuring yet.": before this watch started). The chart drew nothing in those slots: no marker, no tooltip.
- **Network byte charts on the G11:** the 7-day Home chart had 66 hours with `connections: 0`, and Bandwidth's Daily usage had 26 of 31 days with `connections: 0`. This is time older than the G11's oldest record. They drew as a flat 0 B line on the zero gridline. No bucket was missing (`time_slots` returns every slot).
- **Home resize, measured per frame** in Chromium (fixture daemon + `vite dev` on ports 3299/3301, protocols reply delayed like on the G11, where it answers 0.08–0.75 s after bandwidth at every range). Before: the svg was 705×300 at 284 ms, then 705×569 at 651 ms. With bandwidth answering after protocols, the first frame was already 705×569. Width never changed, and the attachment's first measure runs before paint. So the shared chart code was right. The row grew when the taller Network protocols card settled after the chart had drawn.
- Other `col` chart pages: `/alerts`, `/devices/[ip]`, `/logs` and `/bandwidth` write their whole row after one `Promise.allSettled`, so they never jump. Only `/` and `/moment` wrote the chart and its neighbour from separate `settle` calls.

## Root causes
1. `AreaChart`'s `gaps` mode split the path at a missing value and drew nothing there, so a missing stretch was an unexplained blank.
2. The live card replaced its whole history on every poll (`data = res`). The daemon ends a watch 15 s after its last poll, and a hidden tab stops polling. So after a tab switch, the recreated watch's "Not measuring yet." slots wiped the 5 minutes on screen.
3. Home, Moment and Bandwidth plotted a slot with no connection record as 0 B.
4. Home and Moment wrote the bandwidth chart before the taller protocols card beside it, and a `col` chart fills its row (NET-192).

## Fix
- `ui/charts/AreaChart.svelte` and `geometry.ts`:
  - With `gaps`, each stretch where no series has a value is a hatched "No data" band, from the last point before it to the first after it. It carries a label when it is 64 px or wider, and its tooltip gives `formatTip(i)`.
  - A `gaps` chart is a focusable group that the arrow keys, Home and End read, with an `aria-live` line, even without `onpick`. Enter, ranges and dragging still need `onpick`.
  - `tipBox` wraps to the chart width: at most 3 lines, the last cut with "…", and one over-long word is hard-cut. A one-line tip is unchanged.
- `api/live-bandwidth.ts` `keepMeasured`: it puts the card's earlier rates back only when the device, interface, interval and tick are the same and `t` and `mono` are identical and non-null. The daemon's tick times are shared by every watch, so a recreated watch repeats them exactly. A daemon restart can never move or duplicate a measurement. A missing slot's tooltip gives the daemon's reason.
- `utils/up-down.ts` `recorded()`: Home, Moment and Bandwidth pass `NaN` (with `gaps`) for a slot with `connections === 0`. A window with no record at all shows the card's existing empty state, and a day with no record is never the busiest day.
- Home and Moment: both requests still start together, but the chart is written once the protocols request has settled or failed.
- `web/DESIGN-SYSTEM.md`: a "Missing data" rule under Charts.

## Files
`web/src/lib/components/ui/charts/{AreaChart.svelte,AreaChart.test.ts,geometry.ts,geometry.test.ts}`,
`web/src/lib/api/{live-bandwidth.ts,live-bandwidth.test.ts}`,
`web/src/lib/components/{LiveBandwidthCard.svelte,LiveBandwidthCard.test.ts}`,
`web/src/lib/utils/{up-down.ts,up-down.test.ts}`,
`web/src/routes/{+page.svelte,home-chart-gaps.test.ts,home-chart-row.test.ts,home-load-failed.test.ts}`,
`web/src/routes/moment/{+page.svelte,moment-page.test.ts}`,
`web/src/routes/bandwidth/{+page.svelte,bandwidth.test.ts,bandwidth-drilldown.test.ts}`,
`web/e2e/visual/live-bandwidth.visual.ts` (a new 390 px tooltip test), `web/DESIGN-SYSTEM.md`.

## Tests
- Vitest: 401 files, 5411 tests pass. `svelte-check --threshold error`: 0 errors. The 2 warnings are already on main, in files not touched here. `check:colors` is clean. `check:e2e` (tsc) is clean.
- The row, merge and gap tests were each confirmed to fail with their fix taken out.
- Frame harness after the fix: Home's first frame is 697×569 (protocols +400 ms and +750 ms) and Moment's is 697×392, and neither changes size afterwards.
- 390 px check (harness): a missing slot's tooltip with a 120-character tc error wraps to 3 lines inside the card (tip x 35–338, card x 16–363), and the page has no horizontal scroll.
- `npm run test:visual` wasn't run here (the lead runs it). The live-bandwidth and populated screenshots may change where fixtures hold missing slots.

## Lessons
- Measure the frames before blaming the chart: the chart was correct on its first frame, and the jump came from a neighbour's later data.
- For a network-wide byte chart, zero connection records means no data, not 0 B. For a device or a category, zero can be real.
- Reusing old live samples needs exact identity (tick plus identical `t` and `mono`). Matching by time or by tick alone can move or duplicate a measurement after a daemon restart.

## Next steps
- The lead: Linear issue, `test:visual`, PR, deploy to the G11 and check the device page's live chart after a tab switch.
- Device and category charts still draw zero for time older than the network's first record (follow-up if wanted).
