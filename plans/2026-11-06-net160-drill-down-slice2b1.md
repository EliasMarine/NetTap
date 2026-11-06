# Plan: NET-160 slice 2b-1 — exact alert pairs, a 6h range, Home KPI links with their window
_Round 4 - revised after Codex round 4_

## Goal
Every count this slice touches opens a list that holds exactly that count:
1. A smart alert's "×N" (Home and the device page) opens the Alerts list filtered to its signature, source and destination over the window it was counted in. Today the device page uses `ip`, which matches either end and can add the device's other pairs; Home links every group to `/threats`.
2. Alerts and Log Explorer offer 6h, so every Home range has the same range there (owner decision, 2026-11-06).
3. Home's Bandwidth, Connections and Alerts KPI cards open their list with Home's exact `from`/`to`. Today they open `/logs` or `/alerts` with no window, so the list shows the default 24 hours whatever Home shows.

Slice 2b-2 (raw Suricata categories at `/alerts/suricata/<name>`) and 2b-3 (the Devices KPI's "seen in the last …" window, after NET-180's Devices page change merges) are separate plans.

Builds on slice 2a (PR #184): `windowQuery`, `customRange`, `alertsHrefForSignature`, `logsHrefForQuery` in `web/src/lib/utils/drilldown.ts`, and the Alerts URL hand-off (one guarded `$effect` keyed on `[severity, signature, ip, range, from, to]`). This branch is cut from `main` after #184 merges.

## Approach

### A. Source and destination filters on the Alerts list
**Daemon (`daemon/api/alerts.py`, `handle_alerts_list`):**
- New optional `src` and `dst` query parameters: `{"term": {"source.ip": src}}` and `{"term": {"destination.ip": dst}}` in `filter_clauses`, next to the existing `ip` filter.
- Each of `ip`, `src`, `dst` is parsed with `services.excluded_ips.parse_single_ip` (canonical form, rejects CIDR, host names, junk). **`parse_single_ip` also starts rejecting scoped IPv6 (`fe80::1%eth0`)** (Codex #8). Python's `ip_address` accepts any scope text, including quotes. OpenSearch's `ip` type can't hold one. Settings' excluded-address check uses the same function, so a scoped entry is refused there too. A non-empty value that doesn't parse returns 400 `{"error": "ip, src and dst must each be one IPv4 or IPv6 address"}`. Today a bad `ip` goes to OpenSearch, which rejects it, and the user gets a 502.
- The filters combine with AND, as the others do. `ip` is kept for its current callers (address/device links).

**The `signature` filter becomes `term` on `rule.name`** (it was `match_phrase`; kept as OLD CODE). On a keyword field the two match the same documents, but `term` states the exact-match contract outright, and the test evaluator (`tests/fake_drill_opensearch.py`) runs `term` but not `match_phrase`.

**Smart-alert drill-down key (Codex #4, #5):** each group in `/api/alerts/smart` gains `key: {"rule_name", "source_ip", "destination_ip"}`. These are the composite bucket's own values, null when the bucket's value was missing. The displayed `signature` stays as it is. It comes from the sample's normalised alert, which prefers a top-level `alert.signature` over `rule.name`, so it isn't always the bucket key.

**Why this is exact:** a smart-alert group (`services/alert_intelligence.get_smart_alerts`) is one composite bucket keyed on `rule.name`, `source.ip`, `destination.ip`. Its query is the time range (`gte`/`lte`, `strict_date_optional_time`), `event.provider: suricata`, `event.dataset: alert`, and `must_not` `prefix rule.name "SURICATA "`. The list's query is `_time_range_filter` (identical range), `_SURICATA_ALERT_FILTERS` (identical two terms), and `must_not` `_SURICATA_NOISE_EXCLUSION` (identical prefix). `signature` is `match_phrase` on `rule.name`. That field is a keyword in Malcolm's mapping (it's aggregated with `terms` and filtered with `prefix` throughout `alerts.py`), so the phrase is analysed as one token and the match is exact. So with no severity filter, `signature + src + dst + from + to` selects exactly the bucket's `doc_count`. A group dropped by suppression, engine noise or the info cut-off isn't shown, so it has no link.
- **Device groups:** the device page's groups are counted with `source.ip = device OR destination.ip = device` as well, so their link also carries `ip=<device>`. An endpoint field can hold an array (`_normalize_alert_source` handles lists). A document with `source.ip = [device, A]` and `destination.ip = B` is counted in the device's `(S, A, B)` group. An ordinary `A → B` document that never involves the device isn't. `ip + src + dst` keeps exactly that set (Codex #6).
- **Home groups** have no device filter, so `src + dst` alone is exact. A multi-valued document sits in every `(src, dst)` bucket it has values for, and the list's terms match it the same way.

**Web:**
- `routes/api/alerts/+server.ts` forwards `src` and `dst`.
- `lib/api/alerts.ts` `getAlerts` takes `src?` and `dst?`.
- **Alert table and detail signature links** (2a): they link by the row's raw `rule.name` (still in `_source`, since `_normalize_alert_source` doesn't remove it), not the normalised `alert.signature`. With no `rule.name`, there is no link, because the list's `signature` filter can only match `rule.name`. `AlertsListResponse`'s alert type gains `rule?: { name?: string }`.
- `routes/alerts/+page.svelte`:
  - The hand-off key gains `src` and `dst`, so it becomes `[severity, signature, ip, src, dst, range, from, to]`. A change to them alone is a new page-1 list search, as `ip` is.
  - Two chips, "From <src>" and "To <dst>", each with a clear button. Clearing writes the URL without that parameter and keeps every other one, as the IP chip does.
  - `fetchAlerts` sends them. Paging keeps them.
- `lib/utils/drilldown.ts`: the third parameter of `alertsHrefForSignature` changes from `ip?: string` to `narrow?: { ip?: string; src?: string; dst?: string }`. Empty values are left out of the URL.
- **Device page** (`routes/devices/[ip]/+page.svelte:772` and `:780`): **the ×N count is the link** (an anchor named "×N alerts: <signature>"), and the signature line links to the same URL (round 2 #4). An ineligible group's ×N stays a plain `<span>`. A smart alert links with `sa.key.rule_name`, `{ ip: smartAlertsWindow.ip, src: sa.key.source_ip, dst: sa.key.destination_ip }` and the stored `smartAlertsWindow`. `smartAlertsWindow.ip` is the device the response was counted for.
- **A group with any null or empty key part gets no link** (Codex #4, round 2 #2). An empty `rule_name` would otherwise drop the signature filter: the proxy and the daemon both skip an empty `signature`. The ×N is plain text, with the title "This group has no signature, source or destination recorded, so it can't be listed exactly". A missing part is never turned into "no filter on this field". Missing values are rare in Malcolm's ECS output, and an approximate link would break the rule.
- **Home** (`routes/+page.svelte:749`): each smart-alert row links to the exact list (`key.rule_name`, `{ src, dst }`), not `/threats`. A row with a null key part stays a plain row. It isn't a link, so the row doesn't point at a list it can't match.
  - Its window is the smart-alert response's own `from`/`to`, stored when it lands (`smartWindow`, the 2a pattern). It isn't the `win` of a later load.
  - "View threat intelligence" stays as the card's link.

### B. 6h on Alerts and Log Explorer
- Add `{ value: '6h', label: '6h', ms: 6 * 3_600_000, words: 'last 6 hours' }` between 4h and 24h in both `TIME_RANGES` (`routes/alerts/+page.svelte:77`, `routes/logs/+page.svelte:114`). Add `'6h'` to Log Explorer's `TimeRange` type.
- Map `'6h'` in each `INTERVAL_MAP` to `'15m'`, between 4h's and 24h's buckets; the daemon allows `15m` (`_ALLOWED_INTERVALS`).
- Nothing else changes: `?range=6h` already resolves through `TIME_RANGES.some(...)`, and a Custom window's bucket fit (`TIME_RANGES.find(r => r.ms >= …)`) gains a closer step.

### C. Home KPI links with the card's own window
The rule from 2a applies: the link carries the window of the response that produced the figure, stored when it lands, and `range` for the words.
- **Alerts card:** `alertCount` is `snapshot.data`, the count response on screen. After a failed refresh, the snapshot keeps the old data but takes the attempted window. So the link uses **`alertCount.from`/`alertCount.to`** (the response's own window), never `snapshot.from`/`to` (Codex #2). The link is `/alerts?from=<alertCount.from>&to=<alertCount.to>&range=<Home range>`. Its total is `/api/alerts/count`'s `counts.total`. That is the same filter set as the list with severity "all": time range, the two Suricata terms, and the noise exclusion. 2a's severity tiles already rely on this.
- **Connections and Bandwidth cards:** both come from `/api/traffic/summary`. Its query is the time range, `_ZEEK_CONN_FILTERS` (`event.provider: zeek`, `event.dataset: conn`), and `must_not` `build_excluded_ips_filter(excluded_ips)`, which is `terms source.ip [...]`. Log Explorer shows excluded addresses (Settings promises that), so a plain conn link would show more records than the card.
  - **Daemon:** the summary response gains `excluded_ips`, the exact validated list its `must_not` used. It is built with the same loop as `build_excluded_ips_filter`; the plan adds one shared `valid_excluded_ips(entries)` in `services/excluded_ips.py`, and `build_excluded_ips_filter` calls it.
  - **Web (round 3 #4: structured, not query text):** the link is `/logs?type=zeek.conn&exclude_src=<a,b>&from=<summary.from>&to=<summary.to>&range=<Home range>`.
    - Log Explorer's URL hand-off gains `type` (one of its `LogType` keys, else ignored) and `exclude_src`.
    - `type` sets `logType`, which the search already sends as `log_type`. `logs.LOG_TYPE_FILTERS["zeek.conn"]` is the same two terms as `traffic._ZEEK_CONN_FILTERS`.
    - `exclude_src` shows as a chip: "Leaving out sources 192.168.1.199 (excluded in Settings, as Home counts)".
    - **Clearing the chip, "Clear all" and every other Log Explorer control change local state only, as the page's controls do today (round 4 #2).** They don't write the URL. The URL is a one-time hand-off, and `appliedSearch` keeps the same URL from being applied again. So a cleared exclusion or type can't come back from the old URL.
    - Clearing the chip sets `excludeSrc = []`. "Clear all" (`clearAllFilters`) also clears `excludeSrc`. Both set `linked = null` (D), and so does every user-initiated change of type, query, IP or range. Then one search runs with the current local filters.
  - **Daemon (`api/logs.py` `handle_log_search`):** new optional `exclude_src`, a comma list with **no count limit (round 4 #1)**, because Settings has none and the summary applies the whole list. Each entry is parsed with `parse_single_ip`, and a bad entry gets a 400. It adds `{"terms": {"source.ip": [...]}}` to `must_not`, the same clause `build_excluded_ips_filter` makes. The web proxy `routes/api/logs/search/+server.ts` forwards it. No `query_string` is involved, so there is nothing to quote; `queryLiteral` is dropped.
  - **Exactness on Log Explorer:** the search uses the same `@timestamp` range, the `zeek.conn` terms and the same `must_not` terms. Its other `must_not` clauses (`_EXCLUDE_DNS_NOISE`, the alert exclusion) can't match a conn record. So "Showing … of N results" is the card's count. The controlled-data test below proves it.
  - **Same link on both cards:** Bandwidth's link opens the records whose bytes make up its total. The Log Explorer doesn't show a byte sum, so the card's tooltip/`title` says "Opens the connections this total is summed from".
  - **Which summary:** Home keeps the last summary on screen when a refresh fails, with a stale note. The link always uses the summary that is on screen: its `from`, `to` and `excluded_ips`. It never uses the latest request's failure flag (Codex #3).
  - **The range-only fallback** (`/logs?range=<Home range>`) is only for a card that shows no number, before the first summary lands or after a range change whose summary failed.
- **Devices card:** unchanged here (2b-3).

### D. A list that differs from the number clicked (Codex #1; **owner decision pending**, built as option A unless the owner picks B)
A count and its list are two searches made at different times. Records indexed in between, with an `@timestamp` inside the window, are in the list but weren't in the count. This is real for Zeek `conn`: a connection is logged when it ends, but stamped with its start time. Retention can also remove records. Filters alone can't make the two equal, so the owner decides which promise NetTap makes. The question was put on 2026-11-06:
- **A (recommended, the plan's default): a live list, with any net difference stated.**
  - **The value:** the link carries the number clicked as `count=<N>`. Only `^[0-9]{1,15}$` is accepted; anything else is ignored.
  - **The comparison is tied to one hand-off and one request (round 3 #1):**
    - `count` joins the hand-off key on both pages. On Alerts the key becomes `[severity, signature, ip, src, dst, range, from, to, count]`. On Log Explorer it is the existing key plus `type`, `exclude_src` and `count`. So a count-only URL change is a hand-off.
    - The hand-off sets `linked = { expected: N, gen: null, observed: null }`, then starts its list request. It stores that request's guard generation in `linked.gen`. On Alerts that is `listGuard`'s token for the page-1 request the hand-off makes, directly or through `refresh.run()`. On Log Explorer it is the search's own guard.
    - `observed` is set only in that request's success branch, and only when its generation equals `linked.gen`.
    - The line shows only when `observed !== null && observed !== expected`.
  - **Anything else clears it.** Every other list load sets `linked = null` when it starts: sorting, paging or "Load more", a refresh (manual or automatic), a control that writes the URL (its hand-off has no `count`, because `setListParams` drops it), or a new typed search on Log Explorer.
  - **A failed or superseded first request:** the line never shows. The page's normal error state shows instead.
  - **The wording states the net difference only (round 3 #2):**
    - Higher: "You clicked 1,234. This search now matches 1,240 records (6 more)."
    - Lower: "You clicked 1,234. This search now matches 1,200 records (34 fewer)."
    - Then, as possibilities, not a diagnosis: "Records can be logged after a figure is counted (a connection is logged when it ends), and old records are deleted to free disk space."
    - Equal: no line.
  - **Links that carry `count`:**
    - a smart alert's ×N (Home and device page);
    - Home's Alerts KPI;
    - Home's Connections KPI.

    Bandwidth is a byte sum, so it carries none.
- **B: a frozen snapshot.** OpenSearch PIT ids made by every counting endpoint and carried in links, with keep-alive extension, and an explicit "This snapshot has expired" state. If the owner picks B, this section is re-planned and re-reviewed before any code.

## Key decisions & tradeoffs
1. **The excluded-address filter goes in the link's query text, not in a new Log Explorer parameter.** The user sees in the search box exactly what was filtered and can remove it. A new parameter would need wiring through six Log Explorer handlers. The cost is a long query when many addresses are excluded. The Settings list is short (a handful).
2. **The summary reports the excluded list it applied** rather than Home fetching Settings. That avoids a race where Settings changes between the two requests, and it's the exact list that produced the figure.
3. **`ip`/`src`/`dst` validation returns 400**, not a silent drop. A dropped filter would list more alerts than the link promised.
4. **No link when a smart-alert key part is missing** (replaces round 0's fallback to `ip`, which listed more than ×N).
5. **Live list plus an exact difference line (D, option A), pending the owner's choice.** A snapshot would need a PIT per counting response across Home and the other pages, held open on a 16 GB N100, plus an expired state. The difference line keeps every link working and states any gap in numbers, with its cause.
6. **Home smart-alert rows stop linking to `/threats`.** The row's ×N is an alert count, so the alert list holding it is the right target. Threat intelligence stays one click away via the card's link.

## Risks / open questions
- `rule.name` mapping: if some index maps it as `text`, `match_phrase` would match sub-phrases. Malcolm's template maps it as keyword. The deploy check (below) confirms it on the G11 with `_mapping/field/rule.name`.
- A smart group whose `rule.name`, `source.ip` or `destination.ip` was missing has no link (A). It still shows its ×N.
- Excluded entries that aren't single IPs are skipped by both the filter and the list (same helper), so the two can't disagree.

## Verification plan
**Daemon (pytest):**
- `src` and `dst` each add their `term`; together with `signature` the body holds all three.
- An invalid `ip`, `src` or `dst` (`"1.2.3"`, `"10.0.0.0/8"`, `"host"`) gets a 400, and no search is sent.
- IPv6 is canonicalised (`"2001:DB8::1"` → `"2001:db8::1"`).
- The summary returns `excluded_ips` equal to the filter's `terms` list, and skips a stored CIDR in both.
- `parse_single_ip` rejects `fe80::1%eth0` and `fe80::1%" OR *:* OR "`, and `/api/alerts?src=fe80::1%25eth0` gets a 400.
- **Smart alerts:**
  - `key` holds the bucket's values even when the sample's top-level `alert.signature` differs from `rule.name`. The fixture has `alert.signature = "B"` and the bucket `rule.name = "A"`, and `key.rule_name == "A"`.
  - A null `destination.ip` bucket gives `key.destination_ip: null`.

**Web (vitest):**
- **`alertsHrefForSignature` with `narrow`:**
  - `src` and `dst` appear in the URL;
  - empty values are left out;
  - `ip` still works.
- **Alerts page:**
  - `?signature&src&dst&from&to` sends one request carrying all five.
  - Clearing the "From" chip keeps `dst`, `signature`, `from` and `to`.
  - A src-only URL change is one page-1 request.
  - Paging keeps `src` and `dst`.
- **Device page:**
  - A smart-alert link carries `signature = key.rule_name`, `ip = the counted device`, `src` and `dst`, and the counts' window.
  - A group whose displayed `signature` differs from `key.rule_name` links by `key.rule_name`.
  - A group with a null key part renders no link and has the title.
- **Home:**
  - Smart-alert rows link to the exact list with the response's own window, including while a refresh is held in flight (fake clock).
  - A null-key row isn't a link.
  - **Alerts card:**
    - It carries `alertCount.from`/`to` and `range=6h` when Home is on 6h.
    - After a success, then the clock moving and a failed refresh, the card keeps the old number, and its link keeps the old response's window.
  - **Connections and Bandwidth cards:**
    - They carry the summary's `from`/`to`, `type=zeek.conn` and `exclude_src` from the summary's `excluded_ips`. With none excluded, there is no `exclude_src`.
    - After a success then a failed refresh, the link keeps the shown summary's window and exclusion.
    - A first-load failure gives the range-only fallback.
- **Alert table:** the signature link uses `rule.name`. A row without one has no link. A row whose `alert.signature` differs links by `rule.name`.
- **6h:** `?range=6h` opens 6h on both pages with "last 6 hours", and the timeline asks for `15m`.
- Each test fails when the page's previous version is swapped in.
- **Suites:** vitest, svelte-check, `check:colors`, `check:e2e`, `test:visual` (refresh the snapshots if 6h changes a pill row), and daemon pytest.

**Exact equality is accepted on a controlled dataset, not on live data** (round 2 #3, round 3 #3 and #4).
- **Test adapter first:** `tests/fake_drill_opensearch.py` (the evaluator) gains what these endpoints use:
  - `search(index=…, body=…)` without a PIT;
  - ordinary hits honouring `from`, `size`, `sort` on `@timestamp`, and `track_total_hits`;
  - document-backed `top_hits`, with `size`, `sort` and `_source` projection, flat docs expanded to the nested `_source` shape;
  - `match_none`.

  Each new piece gets its own small test against hand-worked answers.
- **Smart alerts:**
  - One fixed document set:
    - neighbouring pairs `(S, A, B)` and `(S, A, C)`;
    - a second signature on the same pair;
    - a document whose top-level `alert.signature` differs from its `rule.name`;
    - a document with an empty `rule.name`;
    - a multi-valued `source.ip = [device, A]`;
    - a document with no `destination.ip`;
    - an `A → B` document that never involves the device;
    - an IPv6 pair.
  - The test runs `/api/alerts/smart`, with and without `device_ip`. **It first asserts the exact set of linkable groups it expects**, so it can't pass on an empty list.
  - For every linkable group, it builds the link's parameters as `alertsHrefForSignature` does, calls `/api/alerts` on the same documents, and asserts `total == count`. It also asserts the returned ids are that group's documents.
  - Groups with a null or empty key part are asserted to be the expected ones.
- **Connections:**
  - Documents:
    - conn records from an excluded IPv4 source and an excluded IPv6 source;
    - an included source;
    - a record whose **destination** is an excluded address (it must stay in);
    - a non-conn record.
  - The test runs `/api/traffic/summary` and then `/api/logs/search?log_type=zeek.conn&exclude_src=<summary.excluded_ips>` on the same window. It asserts equal totals and the expected document ids.
  - A second run uses **51 distinct excluded addresses** in Settings. The search accepts them all (no 400), and totals and membership still match (round 4 #1).
  - **Log Explorer local-state tests (round 4 #2):**
    - Open `type=zeek.conn&exclude_src=A&count=100`, change the type to All, then clear the chip. The search has neither `log_type` nor `exclude_src`, there is no difference line, and the URL hand-off doesn't run again.
    - A typed query survives clearing the chip.
    - "Clear all" clears the exclusion.
  - A web test asserts the Home link carries exactly `type=zeek.conn` and the summary's `excluded_ips` as `exclude_src`. A Log Explorer test asserts that URL makes one search with `log_type=zeek.conn` and `exclude_src`.
- **Difference line (A):**
  - equal, higher and lower;
  - an invalid `count`;
  - a count-only URL change;
  - a deferred first response superseded by a newer hand-off (no line from the old one);
  - a failed first request;
  - cleared on sort, paging, refresh and a control change.

**Device (G11), diagnostic only:** `scripts/remote/deploy-drill-down.sh` prints, for one linkable smart alert and for the Connections card, the count, the linked list's total, and their difference. A difference is shown with the D wording, not as a ✗. A ✗ is only for an error reply or a list total of 0 against a non-zero count.

## Rollback / migration safety
- Web and daemon only; no stored data or mapping changes.
- The new daemon parameters are optional. The new summary field is additive.
- Reverting the PR restores today's links.

## Observability
- A 400 from a bad address is logged at debug level with the parameter name (not the value).
- The deploy script prints both comparisons with their numbers.

## Out of scope
- Raw Suricata categories (2b-2) and the Devices KPI window (2b-3).
- The category page's own paging window (2a known limit).
- Changing Log Explorer to hide excluded addresses by default (Settings promises they show).
