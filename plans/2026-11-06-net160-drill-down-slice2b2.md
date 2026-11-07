# Plan: NET-160 slice 2b-2: a page for each raw Suricata category

_Approved by Codex in round 3 (two low corrections applied)._  The page is a snapshot drill-down like the address and domain pages, not a copy of the NetTap-key page._

## Goal

Suricata gives every alert its own category, its classtype: "Misc activity", "Potentially Bad Traffic", and so on. NetTap shows that value in four places, and none of them is a link:
- the Alerts table's Category column;
- the "By category" group headings;
- the alert drawer's Category fact;
- the live connection drawer.

The owner decided on 2026-11-06 that a raw Suricata category opens its own route, `/alerts/suricata/<name>`. NetTap's 13 keys keep `/alerts/<key>`.

The page answers "what is this category doing on my network": how many alerts, at what severity, over time, which rules, which addresses, and which other categories the same alerts carry. Every figure comes from one checked OpenSearch snapshot, and every figure links to a list built from the same filters.

## Facts (checked on the G11, 2026-11-06, last 7 days, 712,843 Suricata alerts)

- **Only `rule.category` is mapped.** It is a keyword with `ignore_above` 1024. `suricata.alert.category` and `alert.category` are not mapped in any `arkime_sessions3-*` index. Every alert has a `rule.category` (missing: 0).
- **28 distinct values.** "Misc activity" has 520,625; the long tail runs down to single alerts.
- **34,513 alerts (4.8%) carry two values.**
  - The second is a MITRE ATT&CK tactic that Malcolm adds from the rule's metadata, for example `["Potentially Bad Traffic", "Command_And_Control"]`.
  - It is spelled two ways: "Command and Control" and "Command_And_Control".
- **What the UI shows.** The value comes from `_normalize_alert_source` (`daemon/api/alerts.py:193-210`). It reads `alert.category`, then `rule.category`, then `suricata.alert.category`, and takes the first item of a list. `live_connections.py:1300` does the same.
- **The pattern to follow.** The address and domain pages already compute every figure inside one PIT:
  - `storage/snapshot_search.SnapshotSearch`, whose `checked()` raises on `timed_out`, failed shards and missing aggregations;
  - `api/drilldown_runner.run_drilldown`, which provides slots, a time budget and error replies;
  - `chart_slots` and `timeline` for the chart.

## Approach

### A. Daemon

1. **The filter, one function.** `suricata_category_clause(name) -> dict` returns `{"term": {"rule.category": name}}`. It lives in `daemon/api/alerts.py`.
   - `valid_suricata_category(raw) -> str | None` accepts a value whose length is 1–1,024 characters and that isn't only whitespace. It returns the value as given: a term query on a keyword matches the stored value exactly, and links send that stored value.
   - Both the list and the page use these two functions.
2. **List.** `GET /api/alerts?suricata_category=<name>` adds the clause.
   - A bad value gets a 400, with no echo of the value.
   - It combines with every other list filter: severity, signature, ip, src, dst and the NetTap `category`.
   - **The list reply is checked (Codex r2 #4).**
     - `checked(reply, "alert list")` and `total_hits(reply, "alert list")` from `snapshot_search` replace the reply parsing. They raise `QueryFailed` on `timed_out`, on a failed shard, or on a missing or non-exact total.
     - The handler catches `QueryFailed` beside `OpenSearchException` and returns 502 "The alert search was incomplete", instead of a smaller total.
3. **Page figures.** `GET /api/alerts/suricata/{name:.+}?from=&to=` is a new module, `daemon/api/suricata_categories.py`, modelled on `api/domains.py`.
   - It uses `run_drilldown`, `chart_slots` and a single `SnapshotSearch`.
   - The base query is: window filter + `_SURICATA_ALERT_FILTERS` + the clause, with `SURICATA_NOISE_EXCLUSION` as `must_not`. That is exactly the list's query for `suricata_category=name` with no other filter.
   - The reply contains:
     - **`total`:** `snap.count(base)`.
     - **`severity`:** `{high, medium, low, other}`. Each value is `snap.count(base + clause)`, where the clause comes from the same function the list uses for `severity=` (extracted from `handle_alerts_list` if it is inline). `other` = `total` − the three, so the four always add up to `total`.
     - **`timeline`:** `"aggs": {"timeline": chart_slots(from, to)}`, the complete `date_range` the domain page uses (`time_slots.py` says why not a `date_histogram`), read with `timeline()`. A test checks each bucket against a `range` count of its own bounds, the boundary timestamps included, and checks that the buckets add up to `total`.
     - **`rules`:** `snap.groups(base, [{"sig": terms rule.name, missing_bucket}])` with a `max @timestamp` per bucket. Each row has `rule_name` (null when missing; `""` is kept as `""`), `count` and `last_seen`, plus `complete`.
     - **`sources` and `targets`:** `snap.groups` on `source.ip` and on `destination.ip`, each with `missing_bucket`. Each has `distinct` and the top 20 rows `{ip, count}` by count, plus `complete`.
       - A source count is "alerts with this address as a source", which is exactly what `/api/alerts?suricata_category&src=ip` lists. Targets are the same with `dst`.
       - Sources and targets are never added together, so an alert with the same address at both ends is never counted twice (Codex #7). A multi-valued `source.ip` counts once under each of its addresses, as the `src=` list does.
       - The number of alerts with no source address is reported as `sources_missing`, and likewise `targets_missing`.
       - **Incomplete enumeration (Codex r2 #3).** `snap.groups` pages keys in key order and stops at its cap, so a stopped enumeration is neither a true top 20 nor an exact distinct count. When `complete` is false:
         - `distinct` is `null`, with `examined` giving the number of keys read;
         - the page says "Highest counts among the N addresses read; the full set was too large to read".
         The same applies to `rules` and `also_tagged`.
         A test forces the cap, so the busiest address lies beyond it.
     - **`also_tagged`:** `snap.groups(base, [{"c": terms rule.category}])` without the page's own name. Each row has a category, a count (the alerts carrying both) and `complete`. It shows on the page as "Also tagged" and explains why category totals overlap.
   - **Validation:**
     - the name, with `valid_suricata_category`;
     - the window, with `parse_time_range`, and `chart_slots` returning `None` means a 400, as the domain page does.
   - **Errors:** `run_drilldown`'s existing contract applies: `QueryFailed` gives 502, `TooSlow` gives 503 with its message, and a busy slot gives 503. The page shows each with the domain page's wording.
   - **A "/" in a name.** `{name:.+}` lets a name with a "/" through even though aiohttp decodes `%2F` before routing. There is one route only (no `/timeline` sub-route), so the greedy match is safe. A route-table test checks that `a/b` arrives as `a/b`.
4. **A link target for every row.**
   - `_normalize_alert_source` adds `rule_category: list[str]`, the stored `rule.category` values, with a scalar read as `[value]` and missing as `[]`.
   - `live_connections` alerts gain the same field.
   - `category` (the shown value) is unchanged.

### B. Web

5. **API and proxy.**
   - `getSuricataCategory(name, {from, to})` returns `SuricataCategoryFigures` and calls `/api/alerts/suricata/${encodeURIComponent(name)}`.
   - `getAlerts` gains `suricata_category`.
   - The explicit list proxy `web/src/routes/api/alerts/+server.ts` forwards `suricata_category` (Codex #1). A proxy test sends "Misc activity", "A/B & C" and an empty value.
   - The catch-all proxy's long-timeout path list gains `/api/alerts/suricata/`, as the address and domain paths have.
6. **The page.** `web/src/routes/alerts/suricata/[name]/+page.svelte` follows the domain page's recipe and `registerPageRefresh` with its load guard. Every figure keeps the response's own `from`/`to`.
   - **Head:** `h1.page-title` is the name, under the eyebrow "Suricata category". One sentence says it is Suricata's own classification of the rule, and that an alert can carry more than one category: Malcolm adds the MITRE ATT&CK tactic beside it, so category totals overlap.
   - **Window:** it comes from the URL, `range` (15m … 30d, 6h included) or `from`/`to` through `customRange`, as Alerts and Log Explorer do. The range pills change the URL.
   - **KPI row:**
     - Alerts (`total`) links to `/alerts?suricata_category=<name>&<window>`.
     - High, Medium and Low each link to the same list with `&severity=`.
     - Other, shown only when it is above 0, is not a link, because the list has no "other" filter.
   - **Hero:** the timeline.
   - **Rules (DataTable, sortable):**
     - A rule with a name links to `/alerts?signature=<rule_name>&suricata_category=<name>&<window>`. It keeps the category, so a rule seen under two categories still opens exactly its count (Codex #3).
     - A null or empty `rule_name` shows "No rule name", is not a link, and has its own row key. The list can't filter on a missing or empty `rule.name` (`signature=""` is dropped by the client, the proxy and the daemon), so a link would open the whole category (Codex #4, r2 #5). A literal rule named "Unknown" is an ordinary, linked rule.
   - **Sources and Targets (two DataTables):**
     - The address goes to `$ipHref`.
     - The count links to the list with `src=` (sources) or `dst=` (targets), plus the category and the window.
     - The table says "Top 20 of N addresses", and says when the list is incomplete.
   - **Also tagged (Codex r2 #1):** the category name links to its own page over the same window. The count is plain text, "N of these alerts", because that page's total is every alert carrying that category, not only the ones carrying both.
   - **States:** CardState covers loading, empty ("No alerts in “X” over <window words>") and error. A 400 shows the daemon's own message ("That isn't a Suricata category name." for the name, the time-range message for the window), not the generic failure message. A test covers both (Codex r3 low).
7. **Alerts page.**
   - `suricata_category` joins `LIST_PARAMS` before `range`. `WINDOW_AT` is already computed with `indexOf`.
   - It is passed to `getAlerts`.
   - It shows a chip, "Suricata category: X", with a clear button that changes only its own parameter.
   - It does not change the severity tiles, which stay window-wide (slice 2a).
   - **The Top signatures card (Codex r2 #6).** Its rows are window-wide counts. Today, choosing a row sets only `signature`, so `ip`, `src`, `dst` and the new `suricata_category` stay applied and the list holds fewer alerts than the row says. Choosing a row now sets a fresh URL, as a severity tile does:
     - `signature` plus that card's own committed `from`/`to`/`range`;
     - every other list filter cleared.

     A test starts from `/alerts?suricata_category=X&src=…` and checks the URL and request after a row is chosen.
8. **Links into the page.** `suricataCategoryHref(name, win?)` in `lib/utils/drilldown.ts` builds `/alerts/suricata/${encodeURIComponent(name)}`, plus `windowQuery` when a window is given.
   - **Rule:** a shown category is a link only when the row's `rule_category` contains it. Then the row is always in the target's list (Codex #8). Otherwise it stays plain text, as "Uncategorised" does.
   - **Alerts table, Category cell:** the link uses `shownWindow`.
   - **"By category" heading (`AlertGroup.svelte`):** a new optional `href` makes the title a link, using `shownWindow`. The page-row count beside it stays plain, so no number on screen claims to equal the target's total. The link title is "Every alert in this Suricata category over the list's window".
   - **Alert drawer Category fact:** a link with no window, which is the default 24 hours. This follows slice 2a's drawer rule.
   - **Live connection drawer:** a link with no window.

### C. Device check (strict)

9. **`scripts/remote/deploy-drill-down.sh`, Step 7c.** It runs in the container, as Step 7b does.
   - The window is **settled**: `[now − 24 h − 10 min, now − 10 min]`. Suricata alerts are indexed within seconds, so nothing new lands inside it during the check.
   - It uses the busiest `rule.category` value, then the busiest two-valued value (a tactic).
   - **Each of these must be equal, or the step prints ✗ (Codex #9):**
     - the page's `total`;
     - the list's `total` (`/api/alerts?suricata_category=…&size=1`);
     - an OpenSearch `_count` from the opensearch container with the same query;
     - the sum of the timeline buckets;
     - the severity tiles' sum;
     - for the first source, its count against the list with `src=`;
     - for the first rule, its count against the list with `signature=` + `suricata_category=`.
   - It checks that a 1,025-character name returns a 400.
   - It reports whether `alert.category` or `suricata.alert.category` is mapped, as information only (·). If either is, rows whose shown category isn't in `rule_category` simply aren't links.

## Key decisions and tradeoffs

1. **A snapshot drill-down page, not the NetTap-key page reused.** The round 0 draft moved the 941-line key page into a component. Codex found that the key page:
   - doesn't read `from`/`to`;
   - works out a new window per page of results;
   - builds its figures from separate searches, some of them unchecked.

   The address and domain pages already solve all three, so the new page follows them. The key page's own limits stay as recorded in slice 2a's known limits; this slice doesn't touch the key page.
2. **`rule.category` only.** The G11 has no other category field. A term on a field later mapped as `text` would silently match nothing, which is the NET-178 trap. Linking only when `rule_category` contains the shown value keeps every link honest whichever field supplied the display.
3. **Sources and targets apart.** Their union per address needs a query per address to be exact with multi-valued IPs. Two exact lists are simpler and each one has an exact link.
4. **The lists the page opens are live, and section D owns that (Codex r1 #5, r2 #7, not accepted for this slice).**
   - The page's figures share one snapshot. A list opened from them is a new search, so records indexed after the snapshot (late ingestion, retention) can differ from it.
   - Both numbers are accurate for their own moment. Section D decides how the difference is shown: A states the net difference on the list, B opens a snapshot list that expires. The owner hasn't chosen yet.
   - Every NetTap drill-down link has the same property today, including slice 1, 2a and 2b-1 (merged). Section D will cover all of them at once, so making it a prerequisite of this one page would build half of D here before the owner chooses.
   - Exactness is shown where it is decidable: on fixed data (tests) and on a settled window on the G11 (Step 7c).
5. **No not-found state for a raw name.** Any name is a fair question. A name with no alerts in the window shows the empty state.

## Risks / open questions

- **SvelteKit params with `%2F` (Codex r2 #8).** A Playwright test in the fixture harness (`web/e2e/`) settles it: it opens `/alerts/suricata/<encoded "A/B & C 50%">` directly and checks two things. The figures request the page makes carries exactly that name, encoded once, and the heading shows it. If SvelteKit's `[name]` can't carry a "/", the route becomes `[...name]`; that is decided by the test.
- **Cost on the largest category.**
  - "Misc activity" has about 75,000 alerts a day.
  - The composite groups page every rule, source, target and co-category.
  - The page runs in a drill-down slot with the 20 s budget, and `TooSlow` gives a 503 with the existing message.
  - Step 7c times the page call on the busiest category.
- **The list's new shard check.** It turns a silent undercount into a 502. If the G11 has a shard that fails on these queries, the Alerts page would start showing an error. Step 7c and a list call before merge check the G11 first.

## Verification plan

- **Daemon, `tests/test_suricata_category_page.py`, on the evaluator fake.** The seed includes:
  - single-valued and two-valued categories;
  - an alert with no `rule.name`;
  - a "SURICATA " noise alert;
  - an alert whose source and destination are the same address;
  - a multi-valued `source.ip`;
  - a category with a "/";
  - alerts at every severity, plus one with none.

  For every figure on the page, the list it links to (through `handle_alerts_list`) has the same total:
  - KPI, each severity tile, every rule with a name (signature + category), every source (`src`) and every target (`dst`);
  - each Also tagged count equals the number of documents carrying both categories. With one alert tagged `[A, B]` and one tagged `[B]`, A's page shows B with count 1 and no link on the count; B's page total is 2;
  - each timeline bucket equals a `range` count of its own bounds, and the buckets add up to `total`;
  - `other` equals the alerts with no 1/2/3 severity.

  It also checks that a document inserted after the PIT opens doesn't change the page's figures, but does appear in a later list.
- **Daemon unit tests.**
  - 400s for an empty name, a whitespace-only name and a 1,025-character name; the list's `suricata_category` gets the same.
  - The list returns 502 on `timed_out`, on a failed shard and on a missing total.
  - Rules with null, `""`, a literal "Unknown" and an ordinary name come back as four separate rows.
  - A forced enumeration cap gives `complete: false` and `distinct: null`.
  - `TooSlow` gives 503.
  - `{name:.+}` passes `a/b` through.
  - The normalizer's `rule_category` handles a scalar, a list and missing.
- **Web (vitest).**
  - The page:
    - calls its endpoint with the URL's window and renders every card;
    - each link carries the window and filters stated above;
    - a null or empty rule is plain, and a literal "Unknown" links;
    - an incomplete enumeration shows the "among the N read" wording;
    - Other is plain;
    - the Also tagged links;
    - the empty, error and 400 states.
  - The Alerts page: the `suricata_category` URL parameter reaches `getAlerts`, the chip shows, and clearing it keeps the other parameters. Choosing a Top signatures row from a filtered URL gives a fresh, signature-only URL with the card's window.
  - Links: the cell, the heading, the drawer and the live drawer link only when `rule_category` contains the shown value.
  - `suricataCategoryHref` encodes "/", "&" and spaces.
  - The list proxy forwards `suricata_category`.
- **Playwright.** The encoded-name route test (Risks).
- **Visual.** `test:visual` adds the page at five widths in three themes.
- **Device.** Step 7c.

## Rollback / migration safety

The changes are additive: a new endpoint and module, a new page route, a new list parameter, a new normalizer field, and the list's shard check. To roll back, revert the PR. No data or config changes.

## Observability

A bad name or parameter logs one debug line with the parameter name only. A `QueryFailed` or `TooSlow` logs through `run_drilldown`, as the domain page does. The list's incomplete reply logs a warning with the shard count.

## Out of scope

- The NetTap-key page's window and paging limits (slice 2a's known limits).
- Showing the MITRE tactic as its own fact in the drawer.
- Section D, and slice 2b-3 (the Devices KPI window).
