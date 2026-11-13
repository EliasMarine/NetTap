# Chart drill-down, slice 2: every other time chart can be clicked and dragged, 2026-11-13

**Linear:** NET-249 (slice 2 of 4)
**Branch:** `feature/chart-drilldown-slice2`, with `feature/chart-drilldown-slice2-daemon` and `feature/chart-drilldown-slice2-pages` merged in, all from `main` b487c383 (main merged in later).
**Plan:** `.codex-review/2026-11-13-093645-chart-drilldown-slice2/PLAN.md`. Codex returned REVISE in rounds 1–4 (10, 7, 3 and 1 findings) and APPROVED in round 5. Two findings were rejected with reasons in `PLAN-REVIEW-LOG.md`.
**Status:** deployed on the G11 from the branch and checked: 148 checks passed and 1 failed (see below). The PR is in review.

## Why

The owner: "I need to be able to drag on any chart to drill down." Slice 1 did Home's bandwidth chart. This slice does every other time chart that has stored data behind it.

## What changed

**Buckets and windows (daemon).**
- **One bucket table.** Every time chart asks for the owner's table: 1h → 1 min, 6h and 24h → 5 min, 7d → 1 h, 30d → 3 h.
- **The alerts and logs timelines accept `3h`.**
- **New `interval` parameter** on the address, domain, Suricata category, device and IoT activity routes. The address, domain and Suricata routes also keep accepting their old buckets, `10m 6h 1d`.
- **`slot_interval`** (`daemon/api/time_range.py`) checks the bucket together with the window before any search. An unknown bucket is a 400. So is more than 1,000 slots (1,500 for DNS, whose default is 1,441). The check is the same whether the bucket was sent or defaulted, and `slot_count` is the count `time_slots` itself builds.
  - Routes that silently replaced a bad bucket with 1h now refuse it.
  - Date-histogram routes had no slot cap before: 1 min over 30 days was 43,200 buckets.
- **Every chart reply echoes the `from`, `to` and `interval` it counted over.** The device route uses `bandwidth_interval`. The IoT route also returns the `excluded_ips` it applied.
- **The live connection drawer's history** builds one absolute 24 h window in 5 min slots (289). The same strings go into the filter, the slots and the reply (`history.from/to/interval/port`). Before, the filter used `now-24h`/`now` date math, so it could disagree with the slots.

**Picks (web).**
- **Shared helpers.**
  - `TimeChart`, `pickWindow`, `pickedTotal` and `stepMs` live in `drilldown.ts`.
  - `toTimeChart` in `chart-pick.ts` turns a reply into a `TimeChart`. Its step is the bucket the reply echoes, never the one asked for. A reply with an unknown bucket or no window stays a picture.
  - `bucketWords` in `narrow-page.ts` gives the subtitle's bucket words.
- **Alerts and Log Explorer** narrow themselves to the picked window and clear every filter their timeline ignores. They carry `count`.
- **Suricata category** opens the Alerts list for that category, with `count`.
- **Connections, address, IoT and the live drawer** open Log Explorer's conn records:
  - IoT passes the reply's `excluded_ips` as `exclude_src`;
  - the live drawer matches the pair both ways, with the port when the history applied one.
- **DNS, domain, traffic category, device and alert category** narrow themselves: the page reads `?from=&to=` as Custom, and every card follows it.
  - Period comparisons are hidden in Custom mode.
  - `pickedLine` compares the picked figure with the narrowed chart's own total, and stays silent when they agree, the request failed or the reply was superseded.
  - The device page adds why IPv6 ownership can differ.
- **Bandwidth's Daily usage** opens `/moment` for the picked UTC days.
- **PCAP's chart** filters the file list by `modified`, with buckets now aligned to the epoch.
- **Packet analysis** filters rows by the chart's own BigInt bucket membership.
- **Connections and the live drawer** now use `AreaChart` instead of their hand-drawn bars. The old markup is OLD CODE.

## Reviews

- **/deep-review:** no findings (`security-reviews/feature-chart-drilldown-slice2/security-review.md`).
- **security-engineer:** one LOW, fixed. `slot_interval` logged the decoded `request.path` with `%s`, so a `%0A` in a MAC or category segment could forge a log line (probed with aiohttp 3.13.3). It now logs with `%r`, and a test fails on the old format.
- **Python review:** PASS, with three LOWs.
  - Fixed: the device and IoT routes added to the omitted-equals-default test.
  - Fixed: the DNS service's unreachable fallback now says why it stays.
  - Kept: the `chart_slots` `None` branches. They are dead under the 1,000 budget but guard `MAX_SLOTS` if a budget is ever raised.
- **TypeScript review:** one MEDIUM and four LOWs, all fixed.
  - MEDIUM: the Packets note took its span from row order.
  - LOW: a Log Explorer pick on the window already open kept the page's filters.
  - LOW: "superseded reply" tests were missing on four pages.
  - LOW: subtitles named the requested bucket instead of the echoed one.
  - LOW: a stale comment.
- **Merge fixups by the lead:** the two web halves had each written the same reply helper, and then the same bucket-words helper. Each is now one helper; the duplicates are OLD CODE.

## Test results

- **Daemon:** 4,792 → 4,814 + 2 passed, 5 skipped, 0 failed. ruff is clean on the 20 changed files.
- **Web:** 357 → 369 files and 4,712 → 4,856 tests, all passing. svelte-check: 0 errors (the same 2 warnings as before). The colour gate is clean.
- **Visual:** see the PR. The two `/go-live` failures predate this branch (NET-259).

## G11 (`scripts/remote/deploy-chart-drilldown-slice2.sh`, branch at `df5df08b`): 148 ✓, 1 ✗

- **Slots and timings:** 11 routes × 5 ranges, each with the expected slot count and echoed bucket.
  - Every fresh window answered in 0.02–2.6 s, except the device route at 30 d: 3.03 s once.
  - Re-timed over three fresh 30-day windows afterwards, the device route answered in 0.34–1.85 s.
  - That route already used 3 h buckets at 30 d before this slice (`_bandwidth_interval`), so its cost is unchanged.
- **Counts (24 h, 5 min slots):** for Alerts, Suricata category, Log Explorer, Connections, address and IoT, the busiest slot and both clipped edge slots each equal the total of the list their link opens: 18 of 18. Example: Log Explorer's busiest slot was 13,559 records, and the link opened 13,559.
- **Self-narrowing pages:** for alert category, DNS, domain and traffic category, the page over the picked window equals the slot. The device page also matched exactly in all three slots, so the IPv6 difference didn't occur on this data.
- **Rejects:** `42x` and 1 min over 7 days give a 400 with the exact message on all 11 routes.
- **Live drawer:** one pair (port 80) answered in 0.08 s with `5m`, a 24 h window, the port and 289 slots. A settled slot's 4 connections equal its Log Explorer link.
- **Pages:** every changed page and the pick targets answer 200 on a logged-in reload through nginx, and nginx cut no headers.

## Lessons

- **Parallel halves duplicate small helpers.** Two web agents each wrote the reply-to-chart helper and then the bucket-words helper. A brief that freezes the shared file should also name the helpers each half may add, or the lead should add them first, as `b4defc7e` did for the pick helpers.
- **A refusal log line is user input.** aiohttp decodes `request.path`, so log it with `%r`.

## Next

- **Slice 3:** donuts, bars, gauges, the bandwidth heatmap, the Threats StackBar, and the live bandwidth card. The card needs per-sample measurement bounds from the daemon.
- **Slice 4:** Connections, address and PCAP narrow themselves, and the self-narrowing pages get count receivers.
- **Owner:** the iOS touch check from slice 1 also covers these charts.
