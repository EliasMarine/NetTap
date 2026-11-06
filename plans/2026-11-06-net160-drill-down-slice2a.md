# Plan: NET-160 drill-down slice 2a — exact windows, signatures, ports, Log Explorer domains, slice-1 misses
_Round 4 - revised after Codex round 4_

## Goal

The owner's rule for NET-160: if a user can reasonably want to go deeper from an entry, they can drill down, and **a count links to a list that holds the same number over the same window** (web/DESIGN-SYSTEM.md "Drill-down links"). Slice 1 (PR #175) did IPs, domains and certificates. This slice does the parts of slice 2 that need no owner decision:
0. Exact windows: a link from a count carries the count's own `from`/`to`, and Log Explorer and Alerts hold that window (and any search's window) fixed through paging.
1. Alert signatures link to the alerts list filtered to that signature.
2. The top-ports cards on the device and address pages link to Log Explorer with a query that matches each count's definition exactly.
3. Log Explorer's domain columns link to the domain page.
4. Five slice-1 misses.

**Deferred to slice 2b (owner decisions recorded 2026-11-06):** raw Suricata categories (`/alerts/suricata/<name>`), Home KPI windows (6h on Alerts and Log Explorer; Connections KPI → Log Explorer; Devices KPI → Devices page).

Load: one household. Web only; no daemon change in 2a.

## Approach

### 0. Exact windows ("Custom"), following the Certificates page

Certificates already takes `?from=&to=` and shows a **Custom** range pill for that exact window until the user picks another range (`routes/certificates/+page.svelte:100-121`, `cert-view.ts:43-56` `customRange`). Log Explorer and Alerts get the same behaviour.

- **Shared helper:** move `customRange` (and its `CustomRange` type) to `web/src/lib/utils/drilldown.ts`; `cert-view.ts` re-exports it, so Certificates is unchanged (old definition kept as OLD CODE). Add `windowQuery(win: { from: string; to: string }, range?: string): string` → `from=…&to=…[&range=…]`.
- **Log Explorer** (`routes/logs/+page.svelte`):
  - State `custom: CustomRange | null`; `selectedTimeRange` may be `'custom'`; the range pills list a "Custom" option only while `custom` is set (as Certificates, `:148`). Picking any other pill clears `custom`.
  - **One window per load:** `fetchAll` (the page refresh loader, `:614`) resolves the window once, `custom ? { from: custom.from, to: custom.to } : { from: now − range, to: now }`, and passes it to both `fetchDashboard` (the six aggregations, `:415-429`, today calling `getTimeRange` itself) and `fetchLogs`, so the stats, charts and table cover the same bounds. A filter/type/sort change that reloads only the table resolves a new window the same way (unless Custom). **"Load more" (`append`) reuses the table's last window**, so paging never moves it (today `:549-550` recomputes it per page).
  - The histogram interval and the window words for Custom come from the smallest standard range whose span is at least the custom span; the words are `custom.words`.
  - `LogDrawerContent`'s `timeRange` (`:1155`) gets `searchWindow.from`.
  - **URL hand-off (Codex finding 4 and round 2 #2):** the change key (`:854-856`) becomes `[filter, ip, query, range, from, to]`. On every change, first or not: `custom = customRange(from, to)`; `selectedTimeRange = custom ? 'custom' : (valid range param ?? (selectedTimeRange === 'custom' ? '24h' : selectedTimeRange))`; then the existing filter/query hand-off. If the resolved window or range changed, it takes the same path as picking a range (`handleTimeRangeChange`, `:635-648`: clear the old figures, `refresh.run()`), so the dashboard and the table both reload on the new bounds and no old figure sits under the new window's words; if only the filter or query changed, it keeps today's `fetchLogs()`.
- **Alerts** (`routes/alerts/+page.svelte`):
  - Same `custom` state and Custom pill; `getTimeRange()` returns the custom window when set. Range words, timeline interval and card subs follow `custom`.
  - **List window fixed per search:** `listWindow` is set by `loadAll` and by every new list search (severity, sort, signature, IP); `goToPage` reuses it (today `fetchAlerts(pg)` recomputes `getTimeRange()` per page, `:683`).
  - **Severity counts (round 2 #1):** rolling windows keep the shared snapshot (`$alertSnapshots[rangeHours]`, `:277`, shared with Home and the sidebar). **While Custom is on, `loadAll` also calls the existing `getAlertCount({ from, to })`** (`lib/api/alerts.ts:221-225`; `daemon/api/alerts.py:565-588` already takes the bounds, with the same Suricata filters and noise exclusion as the list), and the "Alerts by severity" card, its gauge and the severity pills read those page-local counts. No daemon change.
  - **A count opens the population it counts (round 2 #1, round 3):** the severity counts cover every alert in **their own response's window**, unfiltered. On rolling windows that window is the shared snapshot's (`alertSnapshot.ts:25-28`: rounded down to the minute, fixed per refresh generation, and on a failed refresh the counts shown are an older generation's, `:70`), not the list's. So a severity tile (`showSeverity`, `:714-716`) navigates to `/alerts?severity=<level>&from=<data.from>&to=<data.to>&range=<range>`: **`from`/`to` = the displayed count response's own `data.from`/`data.to`** (Custom), `range` kept for words, and **no `signature` or `ip`** (both filters cleared). "100 high" then opens a list of exactly those 100 high alerts, even after a delay or a failed refresh. In Custom mode the counts' response window is the Custom window, so the tile stays on it.
  - **The severity filter pills lose their numbers** (labels only, "All", "High", …): they are filters over the list's own window and filters, and the counts beside them are the card's, which can be a different window. The card's tiles above them carry the counts.
  - **The URL is the one source of the list's filters and window (finding 4, round 2 #3, round 4):** `severity` (`all`, `high`, `medium`, `low`, `info`: the `SEVERITY_FILTERS` values; missing or anything else is `all`), `signature`, `ip`, `range`, `from`, `to`.
    - One guarded `$effect` keyed on `[severity, signature, ip, range, from, to]` replaces the `ip` effect (`:856-862`, kept as OLD CODE) and the one-time reads of `signature` (`:142-144`) and `range` (`:118-119`). It applies all six to `activeFilter`, `signatureFilter`, `ipFilter`, `custom` and `selectedTimeRange` together, sets `currentPage = 1`, and makes **one** request: a new list search (page 1) when only `severity`, `signature` or `ip` changed, otherwise one `refresh.run()` (every card reloads on the new window). The first run is the page's first load.
    - **In-page controls write the URL instead of local state**, so the URL and what the list shows can't drift apart: the severity pills (`handleSeverityChange`), the top-signature bar toggle (`filterBySignature`, `:719-731`), the signature chip's clear (`clearSignatureFilter`), and the IP chip's clear (`goto('/alerts')`, `:1037`) each `goto` the current URL with only their parameter changed (`replaceState`, `keepFocus`, `noScroll`), and the hand-off does the rest. Clearing one filter keeps every other parameter. Picking a range pill writes `range` and drops `from`/`to` the same way.
    - Paging (`goToPage`) stays local: it reuses `listWindow` and the current filters, and doesn't touch the URL.
- **Which window a link carries:** the window of the response the count came from, stored when that response is applied (not the window of a refresh still in flight): device page `portsWindow`, address page `addressWindow`, category page `shownWindow`. Links from places without a count (drawers) carry no window and open Alerts' default 24 h.

### 1. Helpers in `web/src/lib/utils/drilldown.ts`

- `alertsHrefForSignature(signature: string, win?: { from: string; to: string; range?: string }): string` → `/alerts?signature=<encoded>[&from=…&to=…][&range=…]`.
- `logsHrefForQuery(clauses: string[], win: { from: string; to: string }, range: DrillRangeValue): string` → `/logs?query=<encoded clauses joined by " AND ">&from=…&to=…&range=…`; quoted values as `logsHrefForIp` does.
- `logsHrefForIp(ip, range, win?)`: the slice-1 links from the address, domain and device pages also pass their count's window, so they open on Custom too.

### 2. Signature links

`/alerts?signature=` is sent as `signature`, an exact `match_phrase` on keyword `rule.name` (`daemon/api/alerts.py:379-381`).
- Alerts "All alerts" table signature cell (`alerts/+page.svelte:952`, not column 0): `alertsHrefForSignature(sig, { ...listWindow, range })`.
- Category page table (`alerts/[category]/+page.svelte:688`) and its top-signature bars (`:847-853`, `BarList` `href`): `shownWindow` and `range=selectedRange`.
- Device smart alerts (`devices/[ip]/+page.svelte:756`): the device page's window.
- Without a window: alert drawer (`alerts/AlertDetail.svelte:78`), connection drawer (`ConnectionDrawerContent.svelte:475`), live drawer (`LiveConnectionDrawerContent.svelte:221`), `devices/mac/[mac]/+page.svelte:179`.
- Not inside buttons or links (Alerts list `AlertRow`, Home top categories, Threats investigations).

### 3. Port links, each query written out in full

- **Device page top ports** (`devices/[ip]/+page.svelte:608`; count = Zeek conn records with `source.ip = <device>`, grouped by `destination.port`, `daemon/api/devices.py:1455-1475`):
  `event.provider:zeek AND event.dataset:conn AND source.ip:"<ip>" AND destination.port:<port>`.
- **Address page ports** (`address/[ip]/+page.svelte:417`; count = conn records with `destination.ip = <addr>`, grouped by `destination.port` and `network.transport`, `daemon/api/addresses.py:251-261`; **no source filter**):
  `event.provider:zeek AND event.dataset:conn AND destination.ip:"<addr>" AND destination.port:<port> AND network.transport:<t>`.
  A row with a null port or transport stays plain text.
- Both carry the page's window (24h/7d/30d as `range`, plus the exact `from`/`to`).

### 4. Log Explorer domain columns

`logs/+page.svelte:83,84,89` (`zeek.dns.query`, `zeek.http.host`, `zeek.ssl.server_name`): a `DOMAIN_CELLS` set next to `IP_CELLS` (`:793-798`). A value links to `domainHref(v)` only when `isHostName(v) && !isIpAddress(canonicalName(v))` (`isIpAddress` from `lib/stores/lan.ts:29-33`; `isHostName` alone accepts `203.0.113.7`). Array-valued fields render each value the way `IP_CELLS` does after slice 1's array fix. IPv4, IPv6, `host:port` and empty values stay plain.

### 5. Slice-1 misses

- `LogDrawerContent.svelte:156` `/devices/${ip}` → `$ipHref(ip)` (an internet address goes to `/address/`).
- `devices/[ip]/+page.svelte:616` connection destination IP → `IPAddress` + `:port` text.
- Threats lateral movement source/destination (`threats/+page.svelte:241-242`) → `IPAddress`.
- `certificates/+page.svelte:663` hard-coded `/devices/` → `$ipHref`.

### 6. OLD CODE blocks for every replaced line (project policy).

## Key decisions & tradeoffs

- **Exact `from`/`to`, not just `range` (Codex finding 1):** a `range` link re-anchors the window at click time, so the list can differ from the count by whatever arrived or expired meanwhile. Carrying the count's own bounds makes them equal by construction. `range` still travels so the Custom window has words and a fallback.
- **Custom stays until another range is picked, through Refresh** (as Certificates): Refresh reloads the same window, so late-arriving logs for that window still appear; "up to now" is one pill away. Codex suggested Refresh move it to now; following the existing page keeps one rule across the app.
- **Paging reuses the search's window** on both pages, with or without Custom: it fixes duplicated and skipped rows when new data arrives between pages.
- **Alerts severity counts for a Custom window come from the existing `/api/alerts/count`** with the bounds; rolling windows keep the shared snapshot so Home, the sidebar and Alerts still agree.
- **Ports go to Log Explorer, not Connections:** Connections reads only `ip` and `protocol` from the URL and has no 30d window; Log Explorer takes `query=` and windows, and `query_string` handles numeric `destination.port`.
- **No daemon change in 2a.**

## Risks / open questions

- Log Explorer's table opens on "All logs", whose columns don't include ports; the total matches but the port isn't a column until the user picks "Connections". A `?type=` param is a 2b candidate.
- Log Explorer counts devices excluded in Settings (NET-165). The device top-ports query has no excluded-IP filter, and addresses.py applies none, so counts and lists agree.
- Moving `customRange` must not change Certificates: its tests run unchanged.

## Verification plan

- Vitest:
  - Helpers: encoding, IPv6 quoting, window params, `customRange` (moved) unchanged.
  - **Clock tests (finding 1):** with fake timers, render the device page, advance the clock, read the port href: its `from`/`to` equal the window sent with `getDevicePorts`. Same for the address page and the category bars.
  - **Paging (finding 1):** Log Explorer opened with `from`/`to`: the first search and the "load more" request send exactly those bounds after the clock advances. Without `from`/`to`: "load more" sends the first search's bounds, not new ones. Alerts page 2 likewise.
  - **Address query (finding 2):** the href contains `destination.ip`, port and transport and no `source.ip`.
  - **Domain cells (finding 3):** `example.com` links; `203.0.113.7`, `2001:db8::1`, `example.com:8080` and empty stay plain; an array value renders each element.
  - **Same-route navigation (finding 4, round 2, round 4):** on Alerts, from page 8, changing `signature` and `range` together sends one list request for page 1 with the new parameters; changing `ip` and `from`/`to` together sends one list request, not two; a window-only change sends one. **A fresh `/alerts?severity=high&from=…&to=…` load requests severity high on those bounds; High → Low with identical `from`/`to` sends exactly one page-1 request with severity low.** An invalid `severity` reads as all. A severity pill click updates the URL's `severity` and keeps `signature`, `ip`, `from`, `to`; clearing the IP chip keeps `severity` and `signature`; toggling a top-signature bar writes `signature` and the list follows it. On Log Explorer, a window-only URL change sends the dashboard's six aggregations and the search with the new bounds, and the old stats are cleared before the new ones arrive.
  - **Counts open their population (round 2 #1, round 3):** with Custom on, `getAlertCount` is called with the custom bounds and the severity card shows its figures; clicking the High tile with a signature filter active clears the signature and requests high alerts for the same bounds. **Rolling:** load the page, advance the clock several minutes, click High: the list request's `from`/`to` equal the displayed snapshot `data.from`/`data.to`. **Failed refresh:** a refresh whose count request fails keeps the older counts; clicking High uses the older counts' `data.from`/`data.to`, not the new generation's outer bounds. The severity pills show no numbers.
  - **One window per load:** on Log Explorer the stats request and the search request carry identical `from`/`to`.
  - Clearing Alerts' IP chip keeps `signature`/`range`/`from`/`to`.
  - Slice-1 misses go to `/address/` for an internet IP.
- svelte-check, check:colors, check:e2e, test:visual; `expectNoNestedInteractive` where pages already use it.
- Device: none new; `deploy-drill-down.sh` already exercises the pages.

## Rollback / migration safety

Web only; revert the PR. URLs without `from`/`to` behave as today except that paging keeps its window.

## Observability

None.

## Out of scope

Slice 2b: raw Suricata categories, Home KPI windows and targets, Log Explorer `?type=`, ports elsewhere (Connections table, live, threats, alert drawer).
