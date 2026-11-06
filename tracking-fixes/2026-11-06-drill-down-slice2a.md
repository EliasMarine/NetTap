# 2026-11-06 — A count opens a list holding exactly that count (NET-160, slice 2a)

**Status:** built on `feature/drill-down-slice2`; PR pending. Plan: `plans/2026-11-06-net160-drill-down-slice2a.md` (Codex approved in round 5).

**Problem**
- Slice 1 passed `?range=` when a count linked to a list, so the list recomputed "the last 24 hours" at click time. A figure loaded at 12:00 and clicked at 12:20 opened a different 24 hours.
- Paging recomputed the window too: page 2 of Alerts or "load more" in Log Explorer could skip or repeat rows.
- Log Explorer's stats and table worked out their windows separately, seconds apart.
- On Alerts:
  - A severity tile's count covered every alert in the window, but its list kept the signature and IP filters.
  - The pill numbers were the card's, not the list's.
  - URL changes after the first load were ignored.
- Ports, signatures and some IPs on the device, address, domain and threats pages were plain text.

**Fix**
- **Helpers** (`lib/utils/drilldown.ts`): `windowQuery`, `customRange`, `formatWhen`, `alertsHrefForSignature(sig, win?, ip?)` and `logsHrefForQuery`. `customRange` moved here from Certificates.
- **Log Explorer** (`routes/logs/+page.svelte`):
  - `?from=&to=` opens a Custom range.
  - `fetchAll` works out one window for the stats and the table.
  - "Load more" reuses the window of the rows on screen.
  - URL changes reload the page, and a window change clears the old figures first.
  - DNS, HTTP host and TLS server names link to the domain page.
- **Alerts** (`routes/alerts/+page.svelte`):
  - The URL holds `severity`, `signature`, `ip`, `range`, `from` and `to`. One guarded effect applies them and makes one request. The controls write only their own parameter.
  - A Custom window loads its own counts from `/api/alerts/count`.
  - A severity tile opens the displayed counts' own `data.from`/`data.to`, with no other filter.
  - The pills are labels only.
  - Paging and the table's signature links both use the window of the rows on screen, set when they land, so a page change during a refresh can't mix two windows.
  - The pager waits while a list request is out (`listPending`; `DataTable`'s pager takes `disabled`). A page asked for during a new search would have mixed the new filters with the shown rows' window, and its request would have discarded the new search's answer (found by Codex while reviewing slice 2b-1).
- **Category page:** signature links keep the window of the figures shown, even while a refresh is still loading.
- **Device page:**
  - Ports link to Log Explorer with the query behind each count.
  - Smart-alert signatures link to Alerts with the counts' window and the device's `ip`. This narrows the list to that device, but it isn't exact yet (see Known limits).
  - Destinations are address links.
- **Address and domain pages:** the figures keep the window they were loaded over. Port, HTTP and Certificates links use that window.
- **Threats:** both ends of a lateral movement are address links.
- **Certificates:** the device column uses `$ipHref`, so an internet server opens `/address/`.
- **Drawers:**
  - The alert, connection and live drawers, and the MAC page, link signatures with no window.
  - The Log Explorer drawer's "View source device" uses `$ipHref`.
- `web/DESIGN-SYSTEM.md`: the "Drill-down links" rules now cover exact windows, filters in the link, and the Alerts URL.

**Tests**
- About 35 new or updated tests. Each fails when the page's previous version is swapped in. The exception is "a row with no port stays plain", which guards the new branch.
- **Fake clocks and held requests:** a link carries the bounds the count's request used, not the click time's, including while a refresh is still loading.
- **Alerts:**
  - From page 8, a new signature and range send one page-1 request.
  - High → Low on the same bounds sends one request.
  - An invalid severity reads as all.
  - Each control keeps the other parameters.
  - Tiles use the displayed counts' window, on a rolling window and after a failed refresh.
- **Log Explorer:** the stats and the search carry the same bounds. A window-only URL change reloads all six aggregations.

**Known limits** (follow-ups, not regressions)
- The category page's own paging still works out a new window per page; only its links keep the window.
- A link with no range opens the default 24 hours rather than the range showing before.
- A smart alert's ×N counts one source → destination pair (the daemon groups by signature, source and destination). The list's `ip` filter matches either end, so the list can also hold the device's other pairs for that signature. Slice 2b adds source and destination filters to `/api/alerts`.

**Lessons**
- Store a figure's window when its response lands. Working it out at click time, or when the next request goes out, gives a list that doesn't hold the figure.
- Keep one source for filter state. Effects that read the URL alongside controls that set local state drifted apart.
