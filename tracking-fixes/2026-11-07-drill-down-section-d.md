# 2026-11-07: A list opened from a figure says when it holds a different number (NET-160 section D)

**Status:** branch `feature/drill-down-section-d`, Linear NET-183. Owner decision 2026-11-07: option A, a live list that states the exact net difference from the clicked figure.
- **Plan:** `plans/2026-11-07-net160-drill-down-section-d.md`. Codex approved it in round 4, and the review log sits beside it.

## Problem

Slices 2a to 2b-3 made every count link open a list built from the same query, over the figure's own window. The list is still a fresh search, though:

- **Zeek logs a connection when it ends, stamped with its start time.** A connection that started inside the window can land after the figure was counted, so the list finds more than the figure.
- **Retention deletes old records to free disk space.** The list can then find fewer.

So a user who clicked "214" and saw 218 rows had no way to tell a NetTap bug from a real change. For investigation, every number on screen has to be explainable.

## Fix

- **`web/src/lib/utils/drilldown.ts`:**
  - `withCount(href, n)` adds `count=<n>` to a link, and only for a safe non-negative integer.
  - `linkedCount(raw)` reads it back, accepting `^[0-9]{1,15}$` only.
  - `countDifference(expected, observed, words)` returns null when the two agree. Otherwise it gives "You clicked N. This search now matches M alerts (K more)." followed by the two reasons, in plain English.
  - `logsHrefForIp` takes an optional log `type`.
- **Source links carry their figure:**
  - Home: Connections, Alerts and Devices, plus each smart-alert ×N.
  - Device page: the port links, and both the ×N and the signature links.
  - Address page: the port links; the Alerts card, which now opens the card's own window; and "search them all", which now opens conn records only, the set its figure counts.
  - Category page: the Top signatures bars. The bars "Unknown" and the empty name get no link, because no list holds their count.
  - Suricata category page: every figure link.
- **The pages that read the count (Alerts, Log Explorer, Devices):**
  - Each keeps one `LinkedCount {expected, gen, observed}`.
  - The URL hand-off sets it up, and the one request that hand-off starts claims it through the load guard's generation.
  - That request's total fills `observed`. Any other load, whether sort, page, refresh, retry or a control, ends the comparison.
  - The line shows only when the totals differ, as `<p class="notice" role="status">`.
  - `count` is tracked beside the window and filter keys, never inside them, so a change of count alone is one search.
  - Alerts' own controls drop `count` from the URL.
- **Log Explorer:**
  - The log type, drill bars and Clear filters now always search, including during the first load, so a click then also ends a comparison.
  - A hand-off resets the DNS bar choice, which no URL carries.
  - The column descriptions follow the picked type, during the first load too. A reply for a type no longer picked is dropped, so the first load's slower conn descriptions cannot overwrite the DNS ones (found by the over-engineering review, with a test).
- **`scripts/remote/deploy-drill-down.sh`, Step 7f:** over the settled 24 h window it checks that:
  - the address page's Alerts figure equals the alert list over its window;
  - its connection figure sits between two readings of the conn-only log search;
  - `/alerts?range=24h&count=5` answers through nginx (200, or the login redirect).

## Files

- `web/src/lib/utils/drilldown.ts`, `drilldown.test.ts`
- `web/src/routes/+page.svelte`, `home-drilldown-links.test.ts`
- `web/src/routes/alerts/+page.svelte`, `alerts-count.test.ts` (new, 22 tests)
- `web/src/routes/logs/+page.svelte`, `logs-count.test.ts` (new, 22 tests; `git add -f`, because `logs/` is in `.gitignore`)
- `web/src/routes/devices/+page.svelte`, `devices-count.test.ts` (new, 12 tests)
- `web/src/routes/devices/[ip]/+page.svelte`, `address/[ip]/+page.svelte`, `alerts/[category]/+page.svelte`, `alerts/suricata/[name]/+page.svelte`, and their tests
- `web/e2e/visual/drilldown.visual.ts`: Alerts at `?range=24h&count=210` against the fixture's 214 shows "You clicked 210. This search now matches 214 alerts (4 more)." in every theme, at 1440 and 390
- `scripts/remote/deploy-drill-down.sh`

## Tests

- **vitest:** 3,427 passed.
- **svelte-check:** 0 errors (2 warnings, both pre-existing).
- **check:colors:** clean.
- **test:visual:** 223 passed, plus the new Alerts scenario.

## Lessons

- **A comparison has to belong to one request.** A flag such as "came from a link" goes stale as soon as a refresh or a sort runs. Tying the comparison to the guard generation of the request the hand-off started means no other reply can fill it.
- **A count link must open the set its figure counts.** "Search them all" opened every log type while its figure counted conn records. Adding a count would have shown a false difference, so the link was fixed first.

## Reviews

- **/deep-review:** no findings (`security-reviews/feature-drill-down-section-d/security-review.md`).
- **/ponytail-review:** Ship. Both nice-to-haves taken: Log Explorer claims its comparison the same way as Alerts and Devices (without `tableGen`), and the column-descriptions fix above.

## Follow-ups (Linear)

- **NET-184, Log Explorer bars are not exact.** The source and destination bars filter one side of an IP and keep the other filters, so a bar's figure and its list can differ.
- **NET-185, the category page.** `/alerts/[category]` does not read its window from the URL, and the category endpoint does not tell "Unknown" apart from alerts with no rule name.
