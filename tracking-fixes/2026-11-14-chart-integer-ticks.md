# Count charts repeated y-axis labels, 2026-11-14

**Linear:** NET-286
**Branch:** `fix/chart-integer-ticks-net286`
**Status:** done. PR #294 merged (`2b38309f`); deployed to the G11 with `deploy-chart-ticks-net286.sh` (every check passed: the new web image runs, `/pcap` and `/` still go to `/login` signed out). The quiet-range axis itself is for the owner to look at once.

## Problem

On /pcap, when the counts were small, the capture timeline's y-axis repeated labels ("1, 1, 0, 0, 0"). Peaks of 2 gave
"2, 2, 1, 1, 0". A peak of 12 was worse: the label "3" sat at 2.5 and "13" at 12.5, so a tick was mislabelled.

## Root cause

- `niceAxis` (`web/src/lib/components/ui/charts/geometry.ts`) picks steps from 1/2/2.5/5 × 10ⁿ with n going below 0,
  so a peak of 1 or 2 gets steps of 0.2 or 0.5 and a peak of 11 or 12 gets 2.5.
- `AreaChart` draws every tick through the caller's `formatY`. /pcap's `String(Math.round(v))` collapsed 0, 0.2, 0.4 to "0".
- With whole-number data only peaks 1, 2, 11 and 12 were affected. Twelve count charts share the helper: pcap, iot,
  changelog, alerts (three pages), connections, logs, packets, address, dns and domain. The ones that format with `fmt` or
  `formatCompactNumber` printed "0.2" or "2.5" instead of repeating.

## Fix

- `niceAxis` and `fitAxis` take `whole` (default false). Whole: the scale is at least 1 and only integer steps are allowed,
  which only drops 2.5 at scale 1.
- `AreaChart` sets `whole` when every finite value in every series is an integer (not for `bytes` charts). No call site and
  no formatter changed, so the fix covers every count chart, present and future.
- Axes now: peak 1 gives 0, 1; peak 2 gives 0, 1, 2; peaks 11 and 12 give 0, 5, 10, 15. Every other whole-number peak keeps
  its old axis, and fractional and `bytes` axes are unchanged.

## Tests

- `geometry` (`wholeAxis.test.ts`): peaks 1, 2, 11, 12 give whole, distinct ticks; peaks 0, 3, 4, 5, 7, 10, 37, 125 and
  182406 equal the default axis; the default fractional axis is unchanged. 6 of 9 failed before the fix.
- `AreaChart.test.ts` (table-driven, `formatY={String}`): integer `[0, 1]` draws 0, 1; integer peak 12 draws 0, 5, 10, 15;
  fractional `[0, 0.5, 1]` keeps 0, 0.2 … 1; mixed series (either one fractional) keep the fractional ticks; a rerender
  integer → mixed → integer switches the axis each time. 3 of 6 failed before the fix (the fractional guards passed).
- Full Vitest: 396 files, 5278 passed. svelte-check: 0 errors. `check:colors`: clean.
- Visual suite (`npm run test:visual`, all projects): 317 passed, 0 failed, 54 skipped (8.8 min). The skips are by design in
  `e2e/visual/routes.visual.ts`: the reduced-motion project runs empty mode only, and two tests are covered by the app project.

## Lessons

- A tick formatter that rounds can hide a bad axis (repeats) or mislabel it (2.5 shown as "3"). Make the axis right, not the label.
- `DOWN` (peak 4.7) gets 0..5 in both modes, so it cannot guard this; a guard needs a peak of 1, 2, 11 or 12.
- Peak 11 or 12 now tops out at 15 (was 12.5), so the line fills 75-80% of the plot.
- An all-whole bit-rate series with peak 1, 2, 11 or 12 gets a coarser but still correct axis.
