# Plan review log: NET-160 Section D

Codex thread `01a1b3cb-fcb4-7690-ab25-372900ba2e17`, read-only, MAX_ROUNDS=5. Approved in round 4. Option A was the owner's choice (2026-11-07) and was not up for review.

## Round 1 - Codex

The plan needs revisions. These findings concern count accuracy and hand-off behaviour; option A remains unchanged.

1. **High — The source inventory misses Log Explorer’s counted drill-downs.**

   **Evidence:** The plan’s source table omits Log Explorer. Its [Total events card](web/src/routes/logs/+page.svelte:1152) links to the table, and its protocol, source, destination and DNS bars invoke drill-down handlers at lines 1030–1098. Those handlers retain other filters; `drillByIp` searches both endpoints although the source and destination figures count one side.

   **Impact:** These counted interactions still provide no comparison. Simply adding `count` would also compare different populations—for example, a source count against source-or-destination records.

   **Fix:** Add these sites to the inventory. Construct each hand-off from the figure’s own window and exact predicates, replacing unrelated local filters, and carry its count. Test destination request parameters as well as the URL.

2. **High — A Top signatures click can remove the very filter its count requires.**

   **Evidence:** The plan includes every Top signatures row. However, [`filterBySignature`](web/src/routes/alerts/+page.svelte:940) clears `signature` when that signature is already selected. Contrary to the plan’s risk note, only this clearing branch uses `setListParams`; the selecting branch constructs a fresh URL.

   **Impact:** Applying the proposed count to both branches makes the second click compare one signature’s count with all remaining matching alerts. Omitting it from the clearing branch leaves a counted interaction outside the promised behaviour.

   **Fix:** Make counted row activation always open that signature alone over `signaturesWindow`, with its count. Use the existing signature chip to clear the filter. Test clicking a row when its signature is already selected, including when other filters are active.

3. **Medium — Empty category signatures are another non-exact counted link.**

   **Evidence:** The plan excludes only `"Unknown"`. The category page [links every signature bar](web/src/routes/alerts/[category]/+page.svelte:858), including `""`. The daemon preserves empty names in `_every_signature`, but [applies the list’s signature filter only when truthy](daemon/api/alerts.py:482).

   **Impact:** An empty-name bucket with five records becomes `signature=&count=5`, opening all alerts in the window and presenting the mismatch as a live-data difference.

   **Fix:** Render empty-name buckets as non-interactive, uncounted rows, as the other signature lists already do. Add an empty-name category fixture alongside the `"Unknown"` case.

4. **Medium — Devices’ local controls never reach the proposed clearing mechanism.**

   **Evidence:** The plan clears comparisons when another load starts. Devices’ [type and search controls](web/src/routes/devices/+page.svelte:803) modify local state; its table sorts locally. None starts `load()`.

   **Impact:** After a mismatch appears, searching, changing type or sorting leaves it visible. A search can show no matching devices while the notice still says “This search now matches 24 devices.”

   **Fix:** Explicitly invalidate the comparison on local search, category and sort interactions, including while the hand-off request is pending. Preserve local sorting: `DataTable`’s existing `onsortchange` switches it into server-sort mode, so merely attaching that callback would disable its automatic sorting.

5. **Medium — URL-value equality misses a repeated counted hand-off.**

   **Evidence:** The plan adds `count` to URL keys, but the [Alerts effect](web/src/routes/alerts/+page.svelte:1085) returns when the parameter values equal the previous values. `showSeverity` builds its URL from the displayed snapshot, so repeated clicks can produce identical URLs.

   **Impact:** Click a severity tile, sort or page—which clears the comparison—then click the same tile again. The URL still contains the same filter, window and count, so no hand-off request runs and no comparison returns. Paging may remain on page two.

   **Fix:** Give counted same-page activations an explicit hand-off entry point that resets to page one and starts one comparison even when the URL is unchanged. Keep URL deduplication for incidental reactive updates. Test this exact sequence.

6. **Medium — The verification plan weakens the previously approved race coverage.**

   **Evidence:** The new plan specifies supersession using “a fake guard” and omits count-only navigation tests. The [approved earlier verification](plans/2026-11-06-net160-drill-down-slice2b1.md:179) required count-only navigation and a deferred first response superseded by another hand-off. Existing component tests already provide real refresh integration and deferred-response helpers.

   **Impact:** A fake guard can pass without proving that the actual page assigns the right generation through `refresh.run()`, clears it on replacement, or avoids Svelte effects rerunning when comparison state changes.

   **Fix:** Use rendered components with the real guards and deferred API responses. Cover count-only navigation, both response orders for hand-off A→B, refresh during a pending hand-off, and a window-changing Log Explorer hand-off. Assert the surviving notice, displayed total and request count.

VERDICT: REVISE
### Claude response

- #1 (Log Explorer in-page bars) and #2/#5 (Alerts in-page tile/top-row gotos): scope narrowed explicitly to cross-page links. The in-page interactions carry no count in this slice: the figure and the list's total sit on one screen, and the Log Explorer bars are combinable filters, not exact drill-downs. Making them exact (one-sided IP filters, replacing other filters, then a difference line) gets its own Linear issue. Rationale is in plan section 3 and Out of scope.
- #3 accepted: the "Unknown" and empty-name category signature bars become plain rows with no link and no count; fixtures for both.
- #4 answered by design: on Devices the line compares with the Total devices figure (loaded.total) and reads "This window now has N devices". Local search, type and sort never change that figure, so they don't clear the line, and DataTable's client-side sort is untouched. The line sits with the KPI row.
- #6 accepted: the destination tests are rendered pages with their real guards and deferred replies. They cover count-only navigation, A→B in both reply orders, a refresh while the hand-off is pending, the Log Explorer window-changing hand-off, and clearing, asserting the notice, the total and the request count.


## Round 2 - Codex

The empty-signature fix, Devices KPI placement, and real-guard tests resolve those earlier findings. Three issues remain.

1. **High — Log Explorer controls can change the search without invalidating the hand-off.**

   **Evidence:** Plan line 55 assumes each local control starts `fetchLogs()`. However, [`setLogType`](<web/src/routes/logs/+page.svelte:704>) and `clearAllFilters` (line 770) fetch only when `initialized` is true. That flag becomes true after the entire initial refresh finishes (line 979), including dashboard requests. The controls remain enabled.

   **Impact:** Open a counted connection link, then select DNS while the initial refresh is pending. The selected type changes, but no new generation starts and the comparison is not cleared. The connection reply can populate the table and display its difference under the DNS selection. This also occurs when the table finishes before a slow dashboard request.

   **Fix:** Remove the initialization gate from user-triggered search changes so they immediately clear the comparison and start a guarded replacement request. Test both a pending table response and a completed table with a still-pending dashboard response.

2. **Medium — Hand-off identity must remain separate from window identity.**

   **Evidence:** Plan lines 46 and 62 add `count` to existing keys. Alerts determines whether the window changed using [`next.slice(WINDOW_AT)`](<web/src/routes/alerts/+page.svelte:1106>). Appending `count` makes that comparison include it. Devices uses [`windowKey` to decide whether to discard its loaded reading](<web/src/routes/devices/+page.svelte:296>).

   **Impact:** On Alerts, adding, changing or removing only `count` can trigger the full dashboard load—eight API calls for a custom window—instead of one list request. This includes clearing `count` through an ordinary filter control. On Devices, changing only the informational count unnecessarily discards the existing reading and its stale-data fallback.

   **Fix:** Define a separate hand-off key containing `count`. Keep window comparisons explicitly limited to `range/from/to`, and preserve Devices’ existing window key for loaded-data identity. Test that removing `count` with an Alerts filter change performs one list request and no dashboard requests.

3. **Medium — The pending auto-refresh test contradicts the existing scheduler.**

   **Evidence:** Plan line 146 expects an automatic refresh during a pending hand-off to replace its result. Devices’ [timer](<web/src/routes/devices/+page.svelte:359>) calls `runIfIdle()`, as do Alerts and Log Explorer. [`runIfIdle`](<web/src/lib/stores/pageRefresh.ts:104>) skips while the initial registered load is running.

   **Impact:** With the promised real refresh integration, that test cannot observe a replacement refresh during the initial load. Changing timers to force replacement would remove the existing protection against repeatedly superseding slow requests.

   **Fix:** Split the test: a manual refresh supersedes and clears; an automatic tick during the initial load sends no request and preserves the pending comparison. The next idle tick starts a refresh and clears it. Keep `runIfIdle()` unchanged.

VERDICT: REVISE
### Claude response

- #1 accepted: on Log Explorer, a user-triggered search change (type, chip, clear, bars) clears `linked` at once and always starts a guarded fetchLogs(); the `initialized` gate stays only on fetchFieldDefs and scrolling. Tests cover a pending table reply and a pending dashboard reply.
- #2 accepted: `count` is tracked as `appliedCount` beside each page's existing key, never inside LIST_PARAMS or windowKey. A count-only change makes one list request and keeps loaded data. Tests count the requests.
- #3 accepted: the test is split. A manual refresh supersedes and clears; an auto tick during the first load sends nothing and the comparison survives; the next idle tick refreshes and clears. runIfIdle() is unchanged.


## Round 3 - Codex

The round 2 findings are addressed. One gap remains in the new count-only path.

**High — A count-only hand-off can compare against locally modified Log Explorer filters.**

**Evidence:** [Plan line 45](<plans/2026-11-07-net160-drill-down-section-d.md:45>) directs count-only changes to `fetchLogs()`. Lines 60–62 retain controls that modify local state without changing the URL. [`fetchLogs`](<web/src/routes/logs/+page.svelte:570>) reads those local filters and the local window. The existing URL application also does not reset `activeDnsFilter` (lines 970–976).

**Impact:** Open `type=zeek.conn&from=A&to=B&count=100`, select DNS locally, then receive a same-route navigation differing only in `count=101`. The URL still describes connections, but simply calling `fetchLogs()` searches DNS and compares its total with 101. A locally changed range or DNS-bar filter can similarly contaminate the comparison. The new count-only tests would miss this if local state still matches the URL.

**Fix:** For every counted hand-off, including count-only navigation, first reconstruct the complete search from the destination URL and clear filters absent from it, including `activeDnsFilter`. Then choose the request path using the actual window transition. Preserve one table request; reload dashboard data only if restoring the URL window changes the displayed window. Add a rendered test that changes local type, DNS filter and range before a count-only navigation, and assert the outgoing predicates/window and resulting comparison.

VERDICT: REVISE
### Claude response

- Accepted. On Log Explorer, a count-only change runs the existing hand-off body, which rebuilds window, IP filter, query, type and excluded sources from the URL. It now also resets activeDnsFilter on every hand-off. The branch is chosen by the actual window transition: a full reload only when the shown window changes, otherwise one fetchLogs(). A rendered test changes the local type, the DNS filter and the range before a count-only navigation, and asserts the outgoing predicates, the window and the comparison.

## Round 4 - Codex

No remaining material findings within the revised cross-page scope. The latest revision resolves the count-only filter leak and adds appropriate regression coverage for URL restoration, window changes and request ownership.

This approves the plan; implementation and test results still need review.

VERDICT: APPROVED