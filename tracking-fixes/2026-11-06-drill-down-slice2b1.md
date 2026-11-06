# 2026-11-06 — Exact alert pairs, a 6h range, Home KPI links with their window (NET-160, slice 2b-1)

**Status:** built on `feature/drill-down-slice2b1`, uncommitted; PR pending. Plan: `plans/2026-11-06-net160-drill-down-slice2b1.md` (Codex approved in round 5; review log beside it). Sections A, B and C are built. Section D (the `count=` parameter and the "You clicked N" line) waits for the owner's A/B decision: no D code is in this branch.

**Problem**
- A smart alert's ×N counts one composite bucket: signature (`rule.name`), source and destination.
  - The device page linked it with `ip`, which matches either end, so the list also held the device's other pairs for that signature.
  - It linked by the displayed signature. That can be the sample's `alert.signature`, not the `rule.name` the bucket and the list's filter use.
  - Home linked every smart-alert row to `/threats`.
- The Alerts table and the alert drawer linked by the shown signature too, so a row whose `alert.signature` differs from its `rule.name` opened an empty or wrong list.
- Home offers 6h; Alerts and Log Explorer didn't, so a 6h link opened 24 hours.
- Home's Bandwidth, Connections and Alerts cards opened `/logs` or `/alerts` with no window (the default 24 hours whatever Home showed).
- Connections counts conn records without the sources excluded in Settings. Log Explorer shows excluded sources, so a plain conn link listed more records than the card.
- A bad `ip` on `/api/alerts` went to OpenSearch, which rejected it: the user got a 502.

**Fix**
- **Daemon:**
  - `/api/alerts` takes `src` and `dst` (`term` on `source.ip` / `destination.ip`). `ip`, `src` and `dst` are each parsed with `parse_single_ip`; a bad one is a 400 before any search.
  - The `signature` filter is `term` on `rule.name` (was `match_phrase`, kept as OLD CODE). On the keyword field both match the same alerts; `term` states the exact match.
  - `parse_single_ip` rejects scoped IPv6 (`fe80::1%eth0`). `ip_address` accepted any scope text, quotes included. Settings' excluded-address check uses it too.
  - `/api/alerts/smart` groups carry `key: {rule_name, source_ip, destination_ip}`, the bucket's own values (null when missing).
  - `/api/traffic/summary` returns `excluded_ips`, the list its `must_not` applied. One helper, `valid_excluded_ips`, makes it; `build_excluded_ips_filter` calls it.
  - `/api/logs/search` takes `exclude_src` (comma list, no length limit, each entry parsed, 400 on a bad one). It adds the same `must_not terms source.ip` clause, through `build_excluded_ips_filter`.
- **Web:**
  - `alertsHrefForSignature(sig, win?, narrow?)`: the third parameter is `{ ip?, src?, dst? }`; empty values are left out.
  - `smartAlertHref(key, win, device?)` returns null when any key part is null or empty. A missing part is never turned into "no filter".
  - `connLogsHref(summary, range)` builds `/logs?type=zeek.conn&exclude_src=…&from&to&range`.
  - The `/api/alerts` proxy and `getAlerts` forward `src` and `dst`. The log search proxy already forwarded every parameter.
  - **Alerts:** the URL hand-off key is `[severity, signature, ip, src, dst, range, from, to]`. "From …" and "To …" chips clear through `setListParams`. Paging keeps both. The table and drawer link by the row's `rule.name`, with no link without one. 6h (15-minute buckets).
  - **Device page:** the ×N is the link (named "×N alerts: <signature>"), and the signature line links to the same URL: `key.rule_name`, `{ ip: counted device, src, dst }`, the stored window. An ineligible group's ×N is plain text with a title saying why.
  - **Home:**
    - Smart-alert rows link the same way (no `ip`), over the response's own `from`/`to`, stored when it lands (`smartWindow`). An ineligible row is a plain row with the same title.
    - The Alerts card opens `alertCount.from`/`to` (the count on screen), never the snapshot's attempted window.
    - Connections and Bandwidth open the conn records of the summary on screen, with its exclusions. Bandwidth's title says "Opens the connections this total is summed from". Only a card with no number links by range alone.
    - `KpiCard` takes an optional `title`.
  - **Log Explorer:** the URL hand-off takes `type` and `exclude_src`. `exclude_src` shows as a chip ("Leaving out sources … (set by the link you followed)"; PR #189 review: it first said "excluded in Settings", which the page can't check, so a crafted link could hide a host under that claim). Clearing it and "Clear all" change local state only, as every control here does. 6h (15-minute buckets).
  - `a11y.css` correction 7: on phones `.head-actions` is capped at the page head's width, so the seven range pills scroll inside their track instead of scrolling the page sideways (the visual harness caught it at 390 px).

**Tests**
- **Test adapter** (`daemon/tests/fake_drill_opensearch.py`): non-PIT `search(index=…)`, ordinary hits (`from`, `size`, `sort` with missing values last, `track_total_hits`), document-backed `top_hits` (`size`, `sort`, `_source` projection, nested `_source`) and `match_none`. Each has its own test in `test_fake_drill_opensearch.py` against hand-worked answers.
- **Controlled-dataset equality** (`daemon/tests/test_drill_exact_lists.py`):
  - Smart alerts, with and without `device_ip`, over neighbouring pairs, a second signature on one pair, a shown signature that differs from `rule.name`, an empty `rule.name`, a multi-valued source, a missing destination, an A → B alert that never involves the device, an IPv6 pair, and three documents that belong in neither (outside the window, an engine event, a conn record).
  - Each test first asserts the exact set of linkable groups, then, for every one, that `/api/alerts` with the link's parameters returns `total == count` and exactly that group's document ids. The unlinked groups are asserted too.
  - Connections: excluded IPv4 and IPv6 sources, included sources, an excluded address as a destination (stays in), a DNS record and an out-of-window record. The summary's count equals the log search's total, with the expected ids. A second run with 51 excluded addresses: the search takes them all.
  - Request shape: `src`/`dst`/`signature` terms, 400s with no search sent (`1.2.3`, `10.0.0.0/8`, `host`, `fe80::1%eth0`), IPv6 canonicalised, the summary's `excluded_ips` equal to its `must_not` list (a stored CIDR skipped in both).
- **Web:** `drilldown.test.ts` (narrow, `smartAlertHref`, `connLogsHref`), `alerts-page.test.ts` (7), `device-detail.test.ts` (3), `home-drilldown-links.test.ts` (7, with a fake clock and held requests), `logs.test.ts` (6), `alerts-proxy.test.ts`, `alerts.test.ts` (`getAlerts`).
- **Swap check:** every new test fails when the previous version of its source file is swapped in (each source file swapped on its own, then restored).
- Suites: daemon pytest 3,191 passed; vitest 3,289 passed; svelte-check 0 errors; `check:colors` clean; `check:e2e` clean; `test:visual` 217 passed.

**Known limits**
- A count and its list are two searches at different times: records indexed in between (Zeek logs a connection when it ends, stamped with its start) or removed by retention can make them differ. Section D (owner's decision) states or freezes that difference.
- A smart group with a missing or empty `rule.name`, source or destination has no link. Its ×N still shows.
- Log Explorer: a hand-off with no `type` (or one that isn't ours) searches every type, as it replaces the IP filter and text.
- The connection drawers and the MAC page still link signatures by the shown name (outside this slice's plan).
- `exclude_src` has no limit of its own; the request line (about 8 KB in aiohttp and nginx) caps it at roughly 500 IPv4 or 200 IPv6 addresses (`shortcut:` comment in `daemon/api/logs.py`).

**Review follow-ups (PR #189)**
- **Gates:** `/deep-review` found nothing (`security-reviews/feature-drill-down-slice2b1/security-review.md`). The security engineer found one LOW and the code reviewer found one LOW. Both are fixed:
  - **Log Explorer chip:** it said the sources were "excluded in Settings, as Home counts". The page can't check that, so a crafted link could hide a host under that claim. It now says "(set by the link you followed)".
  - **Evaluator fake:** it treated every `term` value with a "/" as a CIDR, so a rule name like "ET MALWARE Win32/Foo" never matched its own term. Real ET names often contain one. The fake now reads a value as a CIDR only when it parses as one. S2 in `test_drill_exact_lists.py` now contains a "/". With the old fake, 3 tests fail.
- `deploy-drill-down.sh` Step 7b compares the live counts with their lists. It is a diagnostic: a ✗ only for no answer, or for an empty list behind a non-zero count.

**Lessons**
- A drill-down link should filter on the values the count grouped by, carried in the response, not on what the page displays.
- An endpoint test against canned replies can't prove a count equals a list; running both queries over the same documents can.
