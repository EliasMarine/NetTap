# Plan: NET-160 Section D, a drill-down list states its difference from the figure clicked

_Round 3, revised after Codex rounds 1–3. The owner chose option A on 2026-11-07. The design follows Section D of `plans/2026-11-06-net160-drill-down-slice2b1.md`, which Codex approved in round 5 (2b-1 review log, round 3 #1 and #2), widened to every count link built since._

## Goal

A count and the list it opens are two searches made at different moments. Records indexed in between can make them differ. Zeek logs a connection when it ends but stamps it with its start time, and retention deletes old records. Filters alone cannot make the two equal.

The owner chose A: **the list stays live, and when its own total differs from the number clicked, it says so exactly.** For example: "You clicked 1,234. This search now matches 1,240 alerts (6 more)." When the two are equal, nothing is shown.

## Approach

### 1. Shared helpers (`web/src/lib/utils/drilldown.ts`)

- **`withCount(href: string, count: number | null | undefined): string`.** It appends `count=<N>` with `&`, or with `?` when the href has no query, when `count` is a safe integer of 0 or more. Otherwise it returns the href unchanged. Every count link goes through it, so no builder's signature changes.
- **`linkedCount(raw: string | null): number | null`.** Only `^[0-9]{1,15}$` is accepted; anything else is `null` and ignored.
- **`countDifference(expected: number, observed: number, what: { lead: string; one: string; many: string }): string | null`.** It returns `null` when the two are equal. Otherwise:
  - **Higher:** "You clicked 1,234. This search now matches 1,240 alerts (6 more)."
  - **Lower:** "You clicked 1,234. This search now matches 1,200 alerts (34 fewer)."
  - Both are followed by: "Records can be logged after a figure is counted (a connection is logged when it ends), and old records are deleted to free disk space."
  - `lead` is the page's phrase:
    - "This search now matches" on Alerts and Log Explorer;
    - "This window now has" on Devices (round 1 #4, see below).
  - Numbers use `fmt` (en-GB grouping). The noun is `one` when `observed` is 1 ("1 alert"), else `many`.

### 2. Destination pages: one comparison per hand-off (2b-1 round 3 #1)

Each destination keeps `linked: { expected: number; gen: number | null; observed: number | null } | null`.

- **Starting a comparison.** A hand-off whose URL has a valid `count` sets `linked = { expected: N, gen: null, observed: null }`. It then starts its first list request and stores that request's guard generation in `linked.gen`.
- **Recording the result.** `observed` is set only in that request's success branch, and only when the request's generation equals `linked.gen`.
- **Showing the line.** It shows when `observed !== null` and `observed !== expected`.
  - It sits above the list as `<p class="notice" role="status">` with an info icon, the existing notice style used on Log Explorer.
  - It is neutral, not a warning.
  - It uses sentence case, UK spelling and design-system tokens only.
- **Anything else clears it.** Every other list load sets `linked = null` when it starts:
  - sorting, paging or Load more;
  - a refresh, manual or automatic;
  - a control that writes the URL. The new URL has no `count`, so its hand-off starts no comparison.
  - a new typed search.
- **A failed or superseded first request** never shows the line. The page's normal error state shows instead.

**`count` has a key of its own (Codex round 2 #2).** It never joins the keys pages use for window identity: Alerts' `LIST_PARAMS` slice, which decides a full dashboard load against a list-only load, and Devices' `windowKey`, which decides whether to discard the loaded reading.
- Each page tracks an `appliedCount` beside its existing applied key.
- **Only `count` changed** (the other key unchanged): the page makes the one list request it needs (Alerts: `fetchAlerts(1, …)`; Log Explorer: `fetchLogs()`; Devices: `refresh.run()`), and keeps its loaded data and the stale-data fallback. With a valid `count`, that request is the comparison.
- **The other key changed:** the existing behaviour runs exactly as today, and the new `count` (or none) decides whether a comparison starts. A filter control that drops `count` together with a filter change is still one list request, with no dashboard requests.

**Per page:**

- **Alerts (`web/src/routes/alerts/+page.svelte`).**
  - **The hand-off key:** `count` is tracked as `appliedCount` beside `appliedUrl`. It is not added to `LIST_PARAMS`, so `next.slice(WINDOW_AT)` still compares the window fields only.
  - **Controls drop it:** `setListParams` deletes `count` whenever a control writes the URL.
  - **The request:** the first load is the page-1 request, made through `refresh.run()` on the first run or `fetchAlerts(1, …)` later. `linked.gen` is that request's `listGuard` token.
  - **The total:** `observed = totalAlerts` from that request's `applyList`.
  - **The noun:** "alert" / "alerts".
- **Log Explorer (`web/src/routes/logs/+page.svelte`).**
  - **The hand-off key:** `count` is tracked beside the existing key (`filter, ip, query, range, from, to, type, exclude_src`), not inside it.
  - **A count-only change rebuilds the whole search from the URL** (Codex round 3).
    - The effect returns early only when both the key and `count` are unchanged.
    - Otherwise it runs the existing hand-off body, which restores the window, `activeIpFilter`, `query`, `logType` and `excludeSrc` from the URL. It now also resets **`activeDnsFilter = ''`**, which no URL carries, so a DNS-bar choice never survives a hand-off. That was a gap for every hand-off, not only counted ones.
    - It then takes the existing branch by the **actual window transition**:
      - `handleTimeRangeChange`, a full reload, only when restoring the URL changed the shown window;
      - otherwise one `fetchLogs()`.
    - So local type, DNS-filter or range changes made after the first hand-off never leak into the counted search.
  - **The request:** `linked.gen` is the hand-off search's `tableGuard` generation.
  - **The total:** `observed = totalHits` from that search (an exact total; the daemon sets `track_total_hits`).
  - **Clearing** (Codex round 2 #1): Log Explorer's own controls change local state without writing the URL: `setLogType`, the type-chip removal, `clearAllFilters` and the `drillBy*` bars.
    - Today they fetch only once `initialized` is true, which happens after the whole first refresh, dashboard requests included. A type change made during that time neither clears the comparison nor replaces the table request, so the connection reply could fill the table under a DNS selection.
    - **The fix:** each user-triggered search change sets `linked = null` at once and always starts a guarded `fetchLogs()`. The `initialized` gate stays only on the non-table work (`fetchFieldDefs()`, scrolling).
    - The table guard drops the first refresh's older table reply.
  - **The noun:** "record" / "records".
- **Devices (`web/src/routes/devices/+page.svelte`).**
  - **What it is compared with** (Codex round 1 #4): the page's **Total devices** figure (`loaded.total`). That is the number the Home card counted. The local search box, the type pills and the table's own sort only narrow or reorder the rows; they never change `loaded.total`.
    - So the line reads "You clicked 53. This window now has 54 devices (1 more)", which stays true whatever the local controls show.
    - It sits with the KPI row, next to Total devices, not above the table.
    - The local controls therefore do not clear it, and `DataTable`'s client-side sorting is untouched.
  - **The hand-off key:** `count` is tracked beside `windowKey`, not inside it. A count-only change runs one load and keeps the loaded reading (round 2 #2).
  - **The request:** `linked.gen` is the generation of the `load` that the key change starts.
  - **The total:** `observed = loaded.total`, from that one reading (slice 2b-3).
  - **Clearing:** `pickRange` writes a URL without `count`. The page's auto-refresh is a refresh, so it clears `linked`.
  - **The noun:** "device" / "devices".

### 3. Source links that carry `count` (cross-page links to a record list only)

**Scope (Codex round 1 #1, #2, #5):** Section D covers links that carry a figure **from one page to a list on another page**. That is where the moment of counting and the moment of listing are far apart, and where the user cannot see both numbers at once.

**In-page interactions carry no `count` in this slice:**
- **On Alerts,** the severity tiles and Top signatures rows, which filter the list below them. The figure and the list's own total are on screen together. The tiles' re-click toggle and the same-URL repeat (round 1 #2, #5) would need their own hand-off entry point.
- **On Log Explorer,** the protocol, talker, destination and DNS bars, and the Total events card. These are filters that combine with the page's other filters by design. They are not exact drill-downs: `drillByIp` searches both sides while Top talkers counts one.

Making them exact is its own slice, with a new Linear issue (see Out of scope).

These come from the read-only inventory of every link site. Each one wraps its existing href in `withCount(href, figure)`, with the exact figure the link shows:

| Page | Link | Figure |
|---|---|---|
| Home | Connections card | `trafficSummary.connection_count` |
| Home | Alerts card | `alertCount.counts.total`, only on the `from`/`to` path. The `?range=` fallback, used when there is no reply, carries no count. |
| Home | Devices card | `deviceCountReply.count`, only on the `from`/`to` path |
| Home | smart alert ×N | `sa.count` |
| Device page | smart alert ×N, and its signature link (same href) | `sa.count` |
| Device page | a port's connections | `p.connections` |
| Address page | a port's connections | `p.connections` |
| Address page | Alerts card (**link fixed first**, see 4) | `data.alerts` |
| Address page | "Showing N of M connections" (**link fixed first**, see 4) | `connTotal` |
| Alert category page | Top signatures bar | `sig.count`, except the "Unknown" and empty-name bars (see 4) |
| Suricata category page | Alerts card, severity tiles, rules, sources, targets | `data.total`, `data.severity[level]`, `r.count` |

No count is carried by:
- Bandwidth: it is a byte sum.
- Links without a number, such as certificates links and nav links.
- Single-alert drawer and row links.
- "Also tagged": it is plain text, an intersection.
- The domain page's HTTP-requests link: the page already says its count ignores case and the search does not.
- The domain page's tagged-alerts link: it opens every alert, not a tagged list.
- The alert category bars on the Alerts page (see Out of scope).

### 4. Two links fixed so they can carry a count, and one bar left without

- **The address page's Alerts card** (`address/[ip]/+page.svelte:570`). It links `/alerts?ip=…&range=…` with no window, so the list opens on a window anchored at click time.
  - It will add `windowQuery(addressWindow)` when the window is known, as the page's other links already do.
  - Then it carries `count=data.alerts`. `data.alerts` uses the same filter as `?ip=`.
- **The address page's "search them all in Log Explorer"** (`:714`). `logsHrefForIp` searches `(source.ip OR destination.ip)` across every log type, while `connTotal` counts Zeek conn records only.
  - `logsHrefForIp` gains an optional `type`, and this caller passes `zeek.conn`. Home's Connections card uses the same `type=zeek.conn` path, and Step 6 (2b-1) checked it equal on the G11.
  - It then carries `count=connTotal`.
  - `logsHrefForIp` has no other caller.
- **The alert category page's "Unknown" and empty-name Top signatures bars become plain rows, with no link and no count** (Codex round 1 #3).
  - The daemon groups alerts with no `rule.name` under the name "Unknown" (`alerts.py` `_every_signature`), but `/alerts?signature=Unknown` matches the literal name only.
  - An empty name keeps its own bucket, but the list applies its signature filter only when it is truthy (`alerts.py` around line 482). So `signature=` would list every alert in the window.
  - Neither link can list its figure exactly, so both rows are non-interactive, as the category page's table already renders an empty signature.

## Key decisions & tradeoffs

1. **Option A, as the owner chose:** a live list plus an exact difference line. No PIT ids, no expiry state, and no held-open snapshots on a 16 GB N100.
2. **The line states the net difference and possible causes, not a diagnosis.** NetTap cannot tell which records arrived or expired in between. The sentence names the two known ways it happens.
3. **`withCount` wraps hrefs instead of adding a parameter to every builder.** That is one helper, and no signature changes across 9 builders. The cost is that a caller must remember to wrap; each counted link gets a test.
4. **The comparison is tied to one request generation.** A later refresh with new data would otherwise compare a stale "You clicked" with a fresh total and describe drift the user did not cause. When the moment passes, the line goes.
5. **An invalid or missing `count` is ignored, not an error.** The parameter is informational, and the list is correct either way.
6. **Only record counts carry `count`.** A byte sum, or a count whose list is known not to match exactly (the domain HTTP link, "Unknown"), would produce a misleading line.

## Risks / open questions

- **Log Explorer's hand-off** may run `handleTimeRangeChange` when the window changes, not `fetchLogs`. The generation stored must be that of the request that sets `totalHits`. To be confirmed in code; a test checks it.
- **Devices auto-refresh:** if a refresh lands before the hand-off load finishes, the guard drops the older reply and `linked` is cleared, so no line shows. That is correct.

## Verification plan

- **Vitest, helpers:**
  - `withCount` with no query, with a query, with an invalid or negative count, and with 0.
  - `linkedCount`, which rejects `"1e3"`, `"-1"`, `" 5"`, 16 digits and `""`.
  - `countDifference`: higher, lower and equal (null); 1 vs many; en-GB grouping.
- **Vitest, each destination (Alerts, Log Explorer, Devices)** (Codex round 1 #6). These are rendered pages with their real guards and `registerPageRefresh`, and deferred API replies (the existing component-test helpers). There is no fake guard.
  - `?count=N` with a reply total of N shows no line.
  - A total of N+6 shows the "6 more" line; N−34 shows "34 fewer".
  - **A count-only URL change** (same filters, new `count`) starts one new comparison, with one request.
  - **Hand-off A then B, both reply orders:**
    - B's reply first, then A's late reply: B's line (or none) shows, and A's total is never compared.
    - A's reply first, then B's: B's comparison replaces A's.

    Assert the shown notice, the shown total and the request count.
  - **Refreshes while the hand-off request is pending** (Codex round 2 #3; `runIfIdle()` is unchanged):
    - **A manual refresh** supersedes the hand-off request and clears the comparison: no line, and the refresh's total shows.
    - **An automatic tick during the first load** sends no request, and the pending comparison survives and resolves.
    - **The next idle tick** starts a refresh, which clears the line.
  - **Later loads clear the line:** a sort, a page or Load more, or a refresh after the line shows.
  - **Alerts:** a control that writes the URL leaves no `count` in it, and starts no comparison.
  - **Log Explorer:** a hand-off that changes the window, through `handleTimeRangeChange`, compares the total of the request that set `totalHits`.
    - Changing the type through the local controls clears the line, in two cases: while the hand-off's table request is pending, and when the table has answered but a dashboard request has not. Either way it starts one guarded table request for the new type, and the hand-off's late reply never fills the table.
  - **Log Explorer, a count-only hand-off after local changes** (Codex round 3): open `type=zeek.conn&from=A&to=B&count=100`, then pick DNS, set a DNS-bar filter and change the range locally, then navigate to the same URL with `count=101`.
    - The outgoing request carries `type=zeek.conn`, no DNS filter, and window A–B.
    - The table answers once, and the comparison is with 101.
    - Restoring A–B is a window change, so the full reload runs; without the local range change, it is one table request.
  - **Count-only changes:**
    - On Alerts, the same filters with a new `count` make one list request and no dashboard requests.
    - On Alerts, a filter control that drops `count` makes one list request.
    - On Devices, a count-only change makes one load and keeps the shown reading until it answers.
  - **Devices:** the local search, type and sort leave the line in place and leave the table's sorting client-side.
  - An invalid `count` shows no line.
  - A failed first request shows the error state and no line.
- **Vitest, sources:** each counted link in the table has `count=<figure>` in its href. Bandwidth, the domain links, and the Alerts page's tiles and rows have none. The category page's "Unknown" and empty-name bars have no href at all, with fixtures for both.
  - The address Alerts card carries `from`/`to` and its count.
  - "search them all" carries `type=zeek.conn` and its count.
- **`npm run check:colors`, `svelte-check`, `test:visual`.** The visual fixtures get one difference line, on Alerts.
- **On the device (`scripts/remote/deploy-drill-down.sh`, new Step 7f):** over a settled window it checks that:
  - the address page's Alerts figure equals `/api/alerts?ip=&from=&to=` `total`;
  - its conn total lies between OpenSearch's counts, before and after;
  - `/alerts?…&count=5` through nginx answers 200 or the login redirect.

  The line itself is UI and is covered by the tests.

## Rollback / migration safety

The change is web-only plus one deploy-script step. There is no daemon, data or schema change. Revert the PR and redeploy the web container. Old links without `count` keep working.

## Observability

None needed. The line is the user-facing statement of the difference.

## Out of scope

- **In-page drill-downs on Alerts and Log Explorer** (Codex round 1 #1, #2, #5). The Alerts severity tiles and Top signatures rows, and the Log Explorer bars and Total events card. A new Linear issue covers making the Log Explorer bars exact:
  - a source bar filters `source.ip` only, and a destination bar `destination.ip` only;
  - a bar's click replaces the filters that its figure did not apply;
  - with an exact filter in place, each bar can take a difference line.

- **The Alerts page's category bars → `/alerts/[category]`.** The link carries no window, and that page reads no URL parameters. It is a separate exactness fix, the same kind of work as 2b-3's URL window, and gets its own Linear issue.
- **Grouping "Unknown" signatures apart from a literal "Unknown" name on the category endpoint.** The 2b-2 Alerts top lists already did this; the category endpoint has not.
- **NET-182:** a fresh box with no index, and the 20,000-source signal.
