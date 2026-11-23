# NET-354: chart "No data" stretches and repeated day labels

**Date:** 2026-11-23 · **Branch:** `fix/chart-no-data-gaps` · **Status:** in review

## What the owner saw
An 8-day bandwidth window (12–20 Nov, 3-hour buckets) on `/moment` was hatched "No data" from 12 Nov to 18 Nov. The x-axis read "11 Nov, 12 Nov, 13 Nov, 13 Nov, 14 Nov, 15 Nov, 15 Nov …". Home's 7d and 30d charts repeated day labels the same way.

## Root cause
- **The gap is real data loss.** The G11's `retention.json` had `hot_days: 5`. It overrides the 90-day env default, and who set it (Settings or a backup restore) isn't recorded. `nettap-hot-policy` therefore deleted each daily `arkime_sessions3-YYMMDD` index after 5 days, leaving only 19–23 Nov.
  - Disk use was 30 %, and the daemon only pruned PCAP.
  - Zeek's own archive (`nettap-zeek-live:/zeek/live/logs/2026-11-01` … `23`) has every day, so capture ran the whole time.
  - The lone dot near 13 Nov: 17 late records recreated `arkime_sessions3-261113` on 18 Nov.
- **The labels:**
  - Since NET-249, every chart bucket is ≤ 3 h. The day-only formatters (`chartTime` past 7 days, Home's `axisLabel` past 24 h) still label those buckets by day.
  - `AreaChart` labelled every Nth point whatever its text, so the same day printed twice, at times other than midnight.
  - The daemon's 3 h buckets are UTC-aligned, so in UTC−5 the first one starts at 22:00 the day before, which produced the stray "11 Nov".

## Fix
- **Device (2026-11-23 01:37 UTC):**
  - `POST /api/storage/config {"hot_days": 30}`; the ISM policy is now `30d`.
  - The daemon's `change_policy` moved all 10 managed indices onto it, so 19 Nov onward is kept.
  - Cost: about 1.34 GB/day, roughly 40 GB at 30 days.
- **`web/src/lib/components/ui/charts/geometry.ts`:** new `labelIndices(texts, every, slot, minGap, firstIsChange)`.
  - Distinct labels: every Nth point, as before.
  - Repeating labels: only where the text changes (each day's first bucket), at least `minGap` px apart.
  - Point 0 is labelled only when it starts its day.
- **`web/src/lib/components/ui/charts/AreaChart.svelte`:** uses it. `firstIsChange` formats the point one step before the first, in the first point's own form (number or ISO string), so the DNS page's `chartTime(String(t))` works too.
- **`web/src/routes/settings/tabs/RetentionTab.svelte`:** the Hot-tier help now says log-built charts can show gaps where older logs have been deleted, and that Bandwidth's daily totals are kept separately.
- **`scripts/remote/deploy-chart-gaps.sh`:** web-only deploy.

## Tests
- `geometry.test.ts` (`labelIndices`), all passing:
  - distinct labels
  - the owner's 22:00 / UTC−5 window
  - a midnight-start 30-day series at 640 px
  - a 05:00 7-day series
  - all-same labels
- `AreaChart.test.ts` (rendered): a midnight start labelled at x = 50; a 22:00 stub skipped through `chartTime`; hourly points label each day once.
- `settings.test.ts`: the new sentence.
- Full suite: 6,123 tests in 446 files pass. svelte-check: 0 errors. check:colors: clean.

## Lessons
- A short retention setting looks exactly like an outage on every chart. Check `_cat/indices`, the live `retention.json` and Zeek's archive first.
- When a bucket size changes (NET-249), check every formatter that assumed the old size.

## Next
- Restore 1–18 Nov from Zeek's archive. This is a separate task: it affects the usage ledger, data-cap warnings, the weekly report's coverage and live ingestion lag (Codex round 5 findings).
- Follow-ups: a retention-aware "No data" band; the Retention input's `min=7` isn't enforced on save; stray `arkime_sessions3-601120` / `700101` indices from bad timestamps.
