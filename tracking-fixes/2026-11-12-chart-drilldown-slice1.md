# Chart drill-down, slice 1: the Home bandwidth chart opens that moment, 2026-11-12

**Linear:** NET-249 (slice 1 of 4)
**Branch:** `feature/chart-drilldown-net249` (web) with `feature/chart-drilldown-net249-daemon` merged in, both from `main` 233d0624
**Plan:** `.codex-review/2026-11-12-211442-chart-drilldown-slice1/PLAN.md` (Codex: round 1 REVISE, 9 findings; round 2 REVISE, 4; round 3 APPROVED with one Low fixed in the plan)
**Status:** built and tested locally; G11 check pending.

## Why

The owner wants to click or drag any dashboard chart and see what the network was doing at that moment (NET-249). Slice 1 does it for the chart people look at first, Home's bandwidth chart, and adds the page that answers "what was going on then?".

## What changed

**Finer chart buckets (web).**
- Home's bandwidth chart asks for one bucket per range instead of a fixed hour: 1h→1 min, 6h→5 min, 24h→5 min, 7d→1 h, 30d→3 h (`DRILL_RANGES` in `web/src/lib/utils/drilldown.ts`). On the G11 every range answers in 0.15–2.0 s.
- `bucketWindow` turns a picked slot into a link window: clipped to the chart's own window, with the end at the slot end − 1 ms. Daemon windows are `gte from, lte to` and slots are `[start, end)`, so the −1 ms makes a slot's figure and its window's figure the same records. The last slot of a range that ends on a slot edge is one instant (`from == to`), which `customRange` now accepts on Alerts, Log Explorer and Devices.

**Click, drag, keyboard and touch on AreaChart (web).**
- A page that passes `onpick(from, to)` gets a pickable chart: click or tap a point, drag across points, or use arrows/Home/End, Shift+arrows for a range, Enter or Space to open, Escape to cancel. `touch-action: pan-y` keeps vertical scrolling. A change of `series` cancels a selection.
- Without `onpick` the chart is unchanged (`role="img"`).

**New moment page `/moment?from=&to=` (web).**
- "What your network was doing": a bandwidth KPI, Connections, Alerts and Active devices as counted links, the window's own bandwidth chart (also pickable), top devices with what each talked to, protocols, categories, alerts and new devices.
- Widen links (±15 min, ±1 h, the whole chart) drop the carried figures, so they never show a stale difference line.
- When the chart's down/up split differs from the page's (IPv6 reclassified over the narrower window), the page says so; the total and the connection count always match.
- Protocol bars link to Log Explorer with the exact query their count used (`serviceLogsHref`): `network.protocol:"<p>"`, ssl without quic, and Unidentified as `NOT _exists_:network.protocol`, with the appliance's own address excluded.

**New daemon endpoint `GET /api/moment/devices?from&to&limit` (daemon/api/moment.py).**
- The busiest LAN devices, ranked exactly as `/api/devices?sort=bytes`, each with its top 5 destinations and apps by bytes and top 5 looked-up names, from one `msearch` left-joined onto the ranking.
- Runs in the shared drill-down slots off the route pool, on its own exact-terms client with no retries. Every read carries the request's 20 s budget (`_InBudget` adds it to each search, including the device accounting's), so a slot is held at most about 21 s.
- Replies: a partial, capped or malformed read is a written 502 "the device search was incomplete" (the words `/api/devices` uses); a busy slot, a spent budget or a client time-out a 503; a bad `limit` a 400.
- A device's `name` and `mac` are the ones its `/api/devices` row shows (the fingerprint's MAC first; owner's name, then UniFi's, then the hostname).
- Unlabelled flows appear as the app "unknown" (shown as Unidentified): on the G11 the busiest device moved ~3.5 GB unlabelled against 207 KB labelled.
- `/api/traffic/protocols` now reports the `excluded_ips` it applied, so its bars can link with the same exclusion.
- On the G11 (read-only, limit 25) the breakdown msearch took 0.49 s over 24 h, 0.96 s over 7 d and 0.31 s over 30 d, with no `too_many_buckets` and no cut-short lists.

**Protocols on the moment page follow NET-219.** The Unidentified bar shows two-way conversations only, with Home's "Not in the bars" note, and links to Log Explorer without a count (Log Explorer can't tell two-way from one-way). Home and `/moment` share `serviceBars`, `notInBars` and `serviceLabel` in `drilldown.ts`.

## Reviews

- `/codex-review` on the plan: APPROVED in round 3 of 5 (14 findings accepted over two rounds).
- `/deep-review`: no findings (`security-reviews/feature-chart-drilldown-net249/security-review.md`).
- security-engineer: one Low, fixed: the route ran on the retrying main client, so a long window could hold a shared drill slot for minutes and make the address, domain and category pages answer busy.
- Python reviewer: the same issue as a Medium, plus three Lows, all fixed: the reply's MAC could differ from `/api/devices`; the cap message differed from `/api/devices`; the test app lacked `safe_error_middleware` (the PR #255 bug class) and the hostname name path had no test.
- TypeScript reviewer: two Mediums and six Lows, all fixed: the moment page's Unidentified bar brought back NET-219; the tooltip stuck after keyboard focus left; text selection on drag; non-primary pointers; held Enter/Space; the empty-lists wording; a window-change test; a certificates `from == to` test.

## Device script

`scripts/remote/deploy-chart-drilldown-slice1.sh` rebuilds web and daemon, then checks over windows that ended 2 hours ago:
- Home's ranges give 61/73/289/169/241 slots, each under 3 s;
- for the two busiest slots of 24h, 7d and 30d, the clipped first and last 24h slots, and a one-instant trailing slot: the slot's total bytes and connections equal `/api/traffic/summary` over the slot's link window;
- the moment's top devices equal `/api/devices?sort=bytes` for 5-minute and 1-hour windows; no destination or app exceeds its device's total; `limit=26` is a 400;
- every protocol bar equals Log Explorer's total for its link;
- every read the moment page makes answers in under 3 s for 5 min, 1 h and 24 h;
- `/` and `/moment` render on a logged-in full reload through nginx (a 60-second session signed inside nettap-web, never printed), and nginx cut off no headers.

A dry run of the slot, summary and protocol checks against the current main passed all 15 slot checks; the protocol bars matched exactly once the appliance's own address was excluded, which is what the new `excluded_ips` field supplies.

## Verification (local)

- daemon pytest: 4792 passed, 5 skipped (baseline 4770). ruff check and format clean on the new files.
- Vitest: 357 files, 4709 passed (baseline 4644). svelte-check: 0 errors, the 2 warnings `main` has. `check:colors`: clean. test:visual: every `/moment` case passes; the only failures are the two `/go-live` firstrun cases, which fail the same way on 233d0624.

## G11 results

PENDING

## Lessons

- A chart slot and a window filter disagree by one millisecond at the edge: slots are `[start, end)`, filters `[from, to]`. Fix it at the link (end − 1 ms), not by changing every daemon filter.
- A count that leaves out the appliance's own address must say which addresses it left out, or no link can reproduce it.
- A new route that joins shared slots must use the same no-retry, budgeted client as the routes it shares them with. Using the main client "because it raises the partial-results error" traded one guarantee for another; two reviewers caught it.
- A new page that reuses a figure must reuse its rule too: the moment page took the raw `unknown` count and brought back the NET-219 bar Home had already fixed. Shared helpers (`serviceBars`) now hold the rule.

## Still to check by hand

- On a phone (iOS Safari): tap and drag on Home's bandwidth chart; vertical scrolling must still work.
