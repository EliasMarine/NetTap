# 2026-11-06 — A page for each raw Suricata category; exact top lists on Alerts (NET-160, slice 2b-2)

**Status:** built on `feature/drill-down-slice2b2`; PR pending. Plan: `plans/2026-11-06-net160-drill-down-slice2b2.md`. Codex approved it in round 3; the log is beside it.

## Problem

**Raw categories had nowhere to go.** Suricata's own category, the classtype ("Misc activity", "Potentially Bad Traffic" and so on), showed in four places, and none of them was a link:
- the Alerts table;
- the "By category" headings;
- the alert drawer;
- the live connection drawer.

**On the G11, only `rule.category` holds it.** 4.8% of alerts (34,513 of 712,843 over 7 days) also carry a MITRE ATT&CK tactic there, which Malcolm adds. Category totals therefore overlap.

**The Alerts page's Top signatures and Top IPs counts used a capped `terms` aggregation over 8 shards.**
- On the G11, 4 of the top 20 signature rows had a non-zero `doc_count_error_upper_bound` over 7 days, up to 29. For example, "GPL P2P BitTorrent transfer" read 1,914 with a possible 22 more. Choosing a row opened a list with the exact total, so the two numbers could disagree.
- `missing: "Unknown"` put alerts with no rule name into the same bucket as a rule literally named "Unknown". The row's list then held only the literal one.
- Choosing a Top signatures row changed only `signature`. Any `ip`, `src`, `dst` or category filter stayed applied, so the list held fewer alerts than the window-wide row said.

## Fix: daemon

- **Shared list query, in `api/alerts.py`.** New helpers: `alert_query`, `severity_clauses`, `valid_suricata_category`, `suricata_category_clause` and `rule_categories`. The list and every new figure count with the same query, so they can't drift apart.
- **`GET /api/alerts?suricata_category=`** takes 1–1,024 characters and returns a 400 otherwise.
  - The reply goes through `checked()` and `total_hits()`.
  - A timed-out search, a failed shard or a missing total returns 502 "The alert search was incomplete" instead of a smaller total.
- **`GET /api/alerts/suricata/{name}`** lives in the new module `api/suricata_categories.py`.
  - It follows the address and domain pages: one PIT through `SnapshotSearch`, run by `run_drilldown`, with `chart_slots` for the timeline.
  - It returns the total and four severity counts. Each severity count uses the list's own `severity=` clause; if the four don't add up to the total, the reply is a 502.
  - It also returns the timeline (`date_range`), the rules (null and `""` names kept apart), and sources and targets counted separately, each with a `missing` count.
  - It returns `also_tagged`: the other categories on the same alerts.
  - A list that stops at its cap says `complete: false`, gives `distinct: null`, and reports `examined`.
- **Normalizer.** It adds `alert.rule_category`: the stored values, with only valid names kept. Live connection alerts carry the same field.
- **Top signatures and Top IPs.** Both now count every key exactly, with `all_buckets` composite paging (cap 50,000) through the list's query, then sort.
  - A missing rule name comes back as `signature: null`.
  - Both replies gain `complete` and `examined`.
  - `all_buckets` takes an optional `what` and runs each page through `checked()`. Callers that don't pass it behave as before.

## Fix: web

- **The page `/alerts/suricata/[name]`, built on the domain page's recipe.**
  - The window comes from the URL (`range`, or `from` and `to`).
  - The KPI row has an Alerts card and a "By severity" card with High, Medium, Low and Info. Each links to `/alerts?suricata_category=…[&severity=…]` with the response's window.
  - The hero card is the timeline.
  - In the Rules table, a named rule links to `signature` plus `suricata_category`. A null or empty rule reads "No rule name" and is plain.
  - In the Sources and Targets tables, each count links to `src=` or `dst=`.
  - In "Also tagged", the name links to that category's page. The count stays plain, because it is an intersection.
- **Alerts page.**
  - `suricata_category` joins the URL's list parameters, with a chip.
  - A Top signatures row now sets a fresh URL: the signature plus the card's own window, with every other filter cleared.
  - Null and `""` rows are plain; "Unknown" is an ordinary row.
  - An incomplete list says "Highest counts among the N … read". `DataTable` gains `rowActivatable`.
- **Links into the page.**
  - Places: the table cell, the "By category" heading (title only; the page-row count stays plain), the alert drawer and the live drawer.
  - The table cell and the heading carry the window of the rows on screen; the two drawers open the default 24 hours, as slice 2a's drawer links do.
  - A category is a link only when the row's `rule_category` contains the shown value.
- **Proxy.** The list proxy forwards `suricata_category`. The catch-all proxy gives `/api/alerts/suricata/` 30 seconds.
- **`web/DESIGN-SYSTEM.md`** now states the raw-category link rule.

## Tests

- **Daemon:** 3,233 passed, 25 of them new.
  - The tests run on the evaluator fake.
  - On fixed data, every figure on the page equals the list its link opens: the KPI, each severity, each rule, each source and each target.
  - Each timeline bucket equals a range count of its own bounds.
  - The `[A,B]` and `[B]` case gives "Also tagged" a count of 1 and B's own page a total of 2.
  - Null, `""` and "Unknown" stay separate rows.
  - A document indexed after the snapshot doesn't appear on the page but does appear in a later list.
  - A forced cap reads as incomplete.
  - The 400, 502 and 503 paths are covered, and the route keeps a `/` in a name.
  - Top signatures and Top IPs rows each equal their `signature=`, `src=` or `dst=` list.
- **Web:** vitest 3,346 passed, 48 of them new. svelte-check shows 0 errors. `test:visual` passed 223.
  - A Playwright test opens `/alerts/suricata/A%2FB%20%26%20C%2050%25`. The request is encoded exactly once and the h1 reads "A/B & C 50%".
- **Swap check:** every new test fails when its source file's HEAD version is swapped in.

## Known limits

- **The page's figures come from one snapshot, but a list opened from them is a live search.** Records indexed afterwards can differ. Section D (the owner's A/B decision) will cover every drill-down link at once.
- **Top IPs rows still link to the address page.** Their counts mean exactly what `src=` and `dst=` list, but no list on screen holds them yet.
- **A category named "." or "..".** It can't be a URL path segment. Suricata's names are ordinary words.
- **The NetTap-key category pages keep slice 2a's window and paging limits.**

## Lessons

- A capped `terms` aggregation is not a count. Check `doc_count_error_upper_bound` before trusting it. Composite paging gives exact counts, and here it costs one search at the G11's scale: 440 rules and about 1,500 addresses over 30 days.
- When adding a filter to a list, check what each existing "choose a row" handler keeps. A handler that sets one parameter inherits the others.
