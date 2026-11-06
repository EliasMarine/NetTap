# Plan: NET-160 slice 1 — drill down from every IP and domain
_Round 4 - revised after Codex rounds 1-4 (see PLAN-REVIEW-LOG.md)_

Repo: `/Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/drilldown` (branch `feature/drill-down-links` from main `615e8f6`).

## Goal

The owner (2026-11-06): a user must be able to drill down from any entry to granular detail. The owner decided the targets:
- A LAN device IP goes to the existing `/devices/<ip>`.
- An internet address goes to a NEW page: which devices talked to it, its connections, alerts, certificates, GeoIP and WHOIS.
- A domain goes to a NEW page: which devices looked it up, the addresses it resolved to, its certificates and alerts.
- Investigations and Security posture (`/compliance`) are added to the nav.

The top rule is data accuracy.
- Every figure is exact for its window, or the page says it is partial or not measured.
- Nothing is silently capped.
- A page never shows a 0 it can't back.

Slice 1 covers IPs, domains, the nav, certificate drill-in and the broken links. Slice 2 is a later PR: raw Suricata categories, signatures, ports, Log Explorer columns, Home KPI windows.

## Approach

### Daemon (aiohttp, `daemon/api/`, token-protected like every route)

0. **A shared snapshot-search helper, `daemon/storage/snapshot_search.py`**, extracted from `services/cert_overview.py` (its `Budget`, `_open_pit`, `_close_pit`, `_search` and `_checked`).
   - **`SnapshotSearch(client, index, budget)`**, a context manager:
     - Opens a PIT (`allow_partial_pit_creation=false`).
     - Passes each search the PIT and a timeout from the budget.
     - Closes the PIT in `finally`.
   - **`search(body, what)`** returns a checked reply. It raises `QueryFailed` on:
     - a non-dict reply;
     - `timed_out`;
     - `_shards.failed > 0`;
     - a missing aggregation the caller names as required.
   - **`groups(query, sources, metrics, what, max_buckets)`** pages a composite aggregation over the PIT. Composite with `after`, under the same PIT, so every page sees the same data.
     - Sub-aggs are metrics only: `sum`, `max`, `min`, `value_count`.
     - Returns `(buckets, complete)`. `complete` is False only when `max_buckets` (default 100,000) stopped it.
     - It never uses a `terms` agg for a list the page presents as whole, so no nested terms need completing.
   - **The execution boundary is `run_drilldown(request, work)`** in `daemon/api/drilldown_runner.py`, the same pattern as `api/certificates.py:_run` (87-118).
     - The `Budget` starts when the request arrives, so queue time counts against it.
     - `app["drill_slots"] = asyncio.Semaphore(2)` is shared by the address and domain endpoints. A request waits at most the budget for a permit, then gets a 503 "busy".
     - The work runs in `run_in_executor`, so the event loop and `/api/health` are never blocked.
     - The permit is released in the future's done-callback, so it is held until the worker thread finishes, even when the client gave up (`asyncio.shield`).
     - Tests:
       - a slow drill-down does not delay `/api/health`;
       - a third concurrent request waits, or gets a 503, and never runs a third scan;
       - a cancelled request keeps its permit until its worker ends.
   - `cert_overview.py` imports `Budget`, `_checked` and the PIT functions from the new module. Its old definitions are kept as OLD CODE comments, and its behaviour is unchanged, so the existing 37 tests must still pass.
   - Unit tests:
     - every rejection;
     - composite paging across pages;
     - `complete=False` at the cap;
     - the PIT closed on error.

1. **`GET /api/network/lan`** in a new file, `daemon/api/network.py`. It returns the daemon's own LAN policy:
   ```
   {version, subnets: ["a.b.c.d/n", …], source: "env"|"detected"|"rfc1918", ipv6: "not-lan"}
   ```
   - The subnets come from `lan_subnets_of(app["lan_filter"])`, with `[]` meaning RFC1918.
   - `version` is a short hash of the subnets.
   - IPv6 is never LAN: the daemon's filters reject non-IPv4 (`services/excluded_ips.py:281,314`), so the web app must not claim otherwise.

2. **`GET /api/addresses/{ip}?from&to`** in a new file, `daemon/api/addresses.py`.
   - **Validation:**
     - `ip` is checked with `ipaddress.ip_address` and then re-serialised to its canonical form, or the reply is a 400.
     - `from`/`to` use alerts' strict `_parse_time_range` (a 400 when unreadable). It is moved to a shared `api/time_range.py` with the old copies kept as aliases.
   - **One `SnapshotSearch`** per request, with a 25 s budget, inside `run_drilldown`. All datasets (conn, ssl, dns, http, Suricata) live in `NETWORK_INDEX` (`arkime_sessions3-*`), so one PIT covers every search. The base query:
     - `event.provider=zeek`, `event.dataset=conn`;
     - `@timestamp` in the window;
     - `bool.should` [`source.ip=ip`, `destination.ip=ip`].
     - **No excluded-IP filter.** Exclusions are for device-centric views and act on the source only (`services/excluded_ips.py:4-6,516-537`). They would bias one direction and disagree with the connections table below, which doesn't apply them (`api/devices.py:1217-1233`). A test covers an excluded IP appearing as both source and destination.
   - **Totals:** one search with filter aggs `to_it` (`destination.ip=ip`) and `from_it` (`source.ip=ip`). Each has:
     - `doc_count`;
     - `sum` and `value_count` of `source.bytes` and of `destination.bytes`;
     - `min` and `max` `@timestamp`.
   - **Byte direction:**
     - On `to_it` rows the peer opened the session: data to the address = `source.bytes`, data from it = `destination.bytes`.
     - On `from_it` rows the address opened it: data from it = `source.bytes`, to it = `destination.bytes`.
     - Each byte total ships with `measured` (the summed `value_count`) and `connections`. When `measured < connections` the total is flagged `partial: true`.
     - The page shows "Not measured" when `measured == 0`, and "at least X (N of M connections measured)" when partial.
   - **Peers:**
     - `groups` on `source.ip` within `to_it` and on `destination.ip` within `from_it`.
     - Metrics per peer: `doc_count`, the byte sums with their `value_count`s, and `max @timestamp`.
     - The two sides are merged per IP in Python. A self-connection (both sides the same IP) is counted once: it is grouped from `to_it` only, and `from_it` excludes `destination.ip=ip`.
     - Each peer is marked `lan` by the same policy as (1).
     - The reply carries `peers_complete`. The KPI "Devices that talked to it" is shown only when `peers_complete`, otherwise "—" with "too many to count".
   - **Ports:**
     - `groups` with composite sources `[destination.port, network.transport, network.protocol (missing_bucket)]` within `to_it` only. That covers the ports on this address the network reached.
     - Count = `doc_count`.
     - `ports_complete`.
   - **Timeline:** `date_histogram` with `time_slots` / `histogram_buckets` (`storage/`), as other charts do.
   - **TLS names it served:**
     - A second index search inside the same snapshot. If the ssl dataset is in the same network index, the PIT covers it; to verify in code.
     - `event.dataset=ssl`, `destination.ip=ip`.
     - `groups` on `[zeek.ssl.server_name (missing_bucket), zeek.ssl.validation_status (missing_bucket)]`.
     - The reply has `tls_names: [{name|null, sessions, statuses}]` and `tls_complete`.
   - **Alerts:** a count (Suricata, either side, the same `SURICATA_NOISE_EXCLUSION` and dataset filters as `/api/alerts`) through `search` with `track_total_hits: true`. The page links to `/alerts?ip=`.
   - **Threat intel:** the same initialisation as `/api/threats/intel` (`api/threats.py:168-175`), minus the Suricata scan.
     - `ti = ThreatIntelService(); ti.load_cache()`. The cache file is what `populate_from_suricata` saves (`services/threat_intel.py:315-320`), so it holds every indicator the Threats page has gathered.
     - A new `available` property means "at least one indicator in any set". It does not read `_loaded`, which only records a cache read.
     - The reply is `null` when not available, shown as "Not checked: no threat indicators loaded yet". Otherwise it is `{matched: bool(hits), feeds: hits, indicators: n}`, with `hits` from `lookup_ip`.
     - Tests:
       - no cache;
       - a cache with no match;
       - a match;
       - `add_indicators` followed immediately by a lookup with no reload.
   - **Errors:**
     - `QueryFailed` returns a 502 with the reason.
     - Budget exhausted returns a 503 "busy/too slow".
     - Each is logged with the IP.

3. **`GET /api/domains/{name}?from&to`** in a new file, `daemon/api/domains.py`.
   - **Validation and canonical form:**
     - Strip one trailing dot, then lower-case.
     - Every name filter matches both stored forms, `name` and `name.`: a `bool.should` of two case-insensitive terms (`term` takes `case_insensitive`, `terms` doesn't).
     - Tests: dotted and undotted stored records, in mixed case, against a hand-computed combined count.
     - It must be an RFC 1123 hostname: labels 1–63 chars of `[a-z0-9_-]`, 253 in total. Otherwise a 400.
   - **Case-insensitive match:**
     - Each of the two terms above is `{"term": {field: {"value": v, "case_insensitive": true}}}`. OpenSearch supports that on keyword fields.
     - The deploy script checks the deployed mapping of `zeek.dns.query`, `zeek.ssl.server_name` and `zeek.http.host` (`GET <index>/_mapping/field/...`).
     - It also compares a mixed-case `term` count with a lower-case one on the G11.
     - If a field is not keyword, the endpoint fails loudly (a 502 "name matching unavailable"), never with a wrong count.
   - **DNS, the headline figures:** the same base as DNS analytics.
     - `_base_bool_filter` plus `DNS_LOOKUP_EXCLUSION` plus excluded IPs, imported from `services/dns_analytics.py`, not copied.
     - So "Lookups" and "Devices" mean what the DNS page means.
     - Plus the case-insensitive query term.
     - Aggregations:
       - **Total.**
       - **`askers`:** `groups` on `source.ip`, with `max @timestamp`, plus `askers_complete`.
       - **`rcodes`:** `groups` on `zeek.dns.rcode_name` (missing_bucket).
       - **`answers`:** `groups` on `zeek.dns.answers`. Each value is classified in Python:
         - a parsed IP becomes an address, flagged `lan`;
         - a valid hostname becomes a name;
         - anything else (TXT, MX text, and so on) becomes `other`, shown as text, never linked.
       - **The "Addresses it resolved to" KPI** = the number of distinct IP answers, shown only when `answers_complete`.
       - **Timeline.**
   - **TLS:**
     - ssl dataset, `zeek.ssl.server_name` term (case-insensitive).
     - `servers` = `groups destination.ip`, `clients` = `groups source.ip`.
     - `statuses` = `groups zeek.ssl.validation_status` (missing_bucket).
     - Total and `*_complete`.
   - **HTTP:** a count on the http dataset with the `zeek.http.host` term. The page shows the count, linking to Log Explorer with the same query.
   - **Alerts tagged with this name:** a narrow, labelled metric.
     - The count of Suricata alerts (same base as `/api/alerts`) where any of these equals the name (case-insensitive): `related.hosts`, `dns.question.name`, `tls.client.server_name`, `url.domain`.
     - It ships with `tagged_coverage: {alerts_in_window, with_host_field}` (an `exists` filter over the same fields).
     - The page labels it "Alerts tagged with this name" and always shows the coverage line: "Only N of M alerts in this window carry a host name".
     - When `with_host_field == 0` it shows "Not recorded" instead of a number.
     - It never claims to be all the alerts tied to the domain.

4. **Register the three route files** in `api/server.py`. The auth middleware covers them, and no new public path is added.

### Web (SvelteKit, `web/src`)

5. **`$lib/api/network.ts` and `$lib/stores/lan.ts`.**
   - **Loading:** the store fetches `/api/network/lan` on first use and again every 5 minutes. A `version` change replaces the policy.
   - **`isLan(ip)`:**
     - IPv4 is checked against the subnets, or RFC1918 when the list is empty.
     - IPv6 returns false, as the daemon does.
     - It returns `null` while the policy has not loaded yet.
   - **`ipHref(ip)`:**
     - LAN goes to `/devices/<enc ip>`.
     - Not LAN goes to `/address/<enc ip>`.
     - `null` (not loaded) goes to `/address/<enc ip>`, which needs no LAN knowledge: that page reads the authoritative `lan` from the daemon and shows "This address is on your network — open its device page" with a link.
     - So no link points at the wrong page for long, and none points at a device page for a non-device.
   - **`domainHref(name)`** goes to `/domain/<enc canonical name>`.
   - **Unit tests:** CIDR edges (/0, /32, the network and broadcast addresses), IPv6, the not-loaded state and a version change.

6. **`IPAddress.svelte`**, restructured. A wrapper `<span class="ip">` holds two SIBLINGS:
   - `<a href={ipHref(ip)} class="link">ip</a>`;
   - the existing context menu, whose trigger stays right-click / long-press on the wrapper. It renders as a sibling of the anchor (or in a portal), never inside it.
   - **`linked={false}`** renders plain text: no anchor, no `role`, no `tabindex`, no menu. It is used only where the component sits inside another interactive element:
     - `traffic/[category]:551-553` (inside a link);
     - `AlertRow` (inside a button);
     - any DataTable column 0 when `onrowactivate` is set.
   - At each of those sites the address stays reachable some other way. The row's own drawer or detail panel shows it with a link (checked per site).
   - **Find every site:** a grep for `<IPAddress` inside `<button`, `<a ` or `Column.cell` snippets used in column 0 of an `onrowactivate` table.
   - **A shared test helper, `expectNoNestedInteractive(container)`**, fails on any `a`/`button`/`[role=button]`/`[tabindex]` inside an `a` or `button`. It runs in the tests of every page that renders IPAddress, Live, Alerts, Connections, Logs, Bandwidth, the drawers, the device pages, DNS and Certificates, with the context menu open in at least the IPAddress unit test.

7. **New page `/address/[ip]`**, built to the page recipe (`web/DESIGN-SYSTEM.md`):
   - **Head:** h1 = the IP, with chips:
     - "On your network" with a device-page link (from the daemon's `lan`);
     - threat intel: "On a threat list", "Not on a threat list" or "Not checked".
   - **KPI row:**
     - Connections.
     - Data to it and Data from it (Not measured / at least … when partial).
     - Devices that talked to it: LAN peers, "—" when not complete.
     - Alerts, linking to `/alerts?ip=`.
     - Each card notes the window.
   - **Hero:** connections over time.
   - **Details:**
     - **"Who it is":** GeoIP and reverse DNS. WHOIS loads on a button press, so a slow WHOIS server can't hold the page or its refresh.
     - **"Devices that talked to it":** a sortable DataTable. LAN peers first by name (`namesByIp`); every peer links via `ipHref`.
     - **"Ports on this address"** and **"Names it served (TLS)":** each name links with `domainHref` and to `/certificates?server=<ip>&site=<name>` (see 9b).
     - **"Connections":** paged via `getDeviceConnections(ip)`, which matches either side. When `total > 10,000` the card says "Showing the newest 10,000 of N. Narrow the time range to reach older ones", and links to Log Explorer with the same filter. The endpoint caps paging at 10,000 (`api/devices.py:95,1279`).
   - **States:** `CardState` for loading, empty and error on every card. `registerPageRefresh` with the load guard and the global time range.

8. **New page `/domain/[name]`**, same recipe:
   - **KPI row:** Lookups, Devices that looked it up, Addresses it resolved to (distinct IPs), TLS sessions, and Alerts tagged with this name (with its coverage line, or "Not recorded").
   - **Hero:** lookups over time.
   - **Details:**
     - "Devices that looked it up".
     - "What it resolved to": IPs link via `ipHref`, validated names via `domainHref`, anything else as text.
     - "TLS": servers via `ipHref`, clients, statuses, and a link to `/certificates?site=<name>`.
     - "Response codes".
     - "HTTP" count, with a Log Explorer link.
     - "Look it up now": `/tools/dns-recon?domain=`. That page gains a `?domain=` prefill.
   - The page states that it matches the name exactly, ignoring case.

9. **Domain and certificate links.**
   - **(a) Domain links.**
     - DNS page domain columns (`routes/dns/+page.svelte:468/476/482`): the name becomes a link only when the table has no `onrowactivate`, or the link sits outside column 0. Otherwise the in-page drawer or detail gets the link.
     - Device page DNS domain (`devices/[ip]:604`) and the ConnectionDrawer SNI (`:466`).
     - `devices/mac/[mac]:174`.
   - **(b) Certificates.**
     - `/certificates` reads `?site=` and `?server=`. On load it filters sites, findings and devices to that site name or server address, using the overview it already loads for the global time range. When exactly one site matches, its detail opens.
     - Site links are built from the structured site identity, not the label: a real SNI (`CertSite.name`) links with `domainHref`; a no-SNI site (`name == null`, `server` set) links its server with `ipHref`; anything else stays text.
     - **Daemon-side filtering, not the browser.** The overview list is capped (`api/certificates.py:27`), and a site row merges servers (`cert_findings.py:33,222-234`). So `/api/certificates/overview` gains optional `site` and `server` parameters:
       - `site`: a canonical hostname, validated as in (3), matching both dotted forms, case-insensitive.
       - `server`: a canonical IP.
       - Both go into `CertOverview.overview()`'s session query (`services/cert_overview.py:437`) before tallying and pagination. When both are given they combine with AND.
       - All figures, findings and details then describe exactly those sessions.
       - Tests:
         - one SNI served by two IPs with different certificates: `site+server` shows only that server's certificate;
         - a target that ranks past the 5,000-row cap unfiltered;
         - the existing 37 tests unchanged.
     - **The window travels with the link.** Links from the address and domain pages carry `from` and `to`, the source page's resolved window. `/certificates` initialises its request and its displayed range from them instead of its own 7-day default (`routes/certificates/+page.svelte:58,80-85`). The time pill shows "Custom". A test uses a historical window holding a different certificate than the default 7 days would.
     - Certificates tables use `onrowactivate` with column 0 (`routes/certificates/+page.svelte:165-178,785,824`), so those links go in `CertDetail` (the drawer), not in column 0.

10. **Broken or wrong links fixed:**
    - **Connections' `?src_ip=` and `?dst_ip=`** (sent by the IPAddress menu, ignored at `connections/+page.svelte:779-782`):
      - The connections page has a single IP filter (`?ip=`), but it appends the IP to the free-text `q` (`connections/+page.svelte:460-475`). That goes to `query_string` (`api/traffic.py:662-670`), where an IPv6 colon is query syntax and any field can match.
      - **Daemon:** `/api/traffic/connections` gains a validated `ip` parameter, a canonical IP or a 400. It is applied as a structured filter, `bool.should [term source.ip, term destination.ip], minimum_should_match: 1`, kept separate from `q`.
      - **Web:** `getConnections` sends `ip` as its own parameter, and the page's IP filter uses it, not `q`. The old `q` concatenation is kept as OLD CODE.
      - **The explicit Connections proxy forwards `ip`.** `web/src/routes/api/traffic/connections/+server.ts:11-26` rebuilds the query from an allowlist that lacks it, and the catch-all proxy doesn't apply here. `web/src/routes/api/traffic-connections-proxy.test.ts` asserts that IPv4 and IPv6 values reach `daemonFetch` intact, together with `q`, pagination and sorting.
      - **Audit every explicit proxy:** any new or changed parameter in this plan (`site`, `server`, `from`, `to`, `ip`) is checked against an explicit `+server.ts` under `web/src/routes/api/` that rebuilds queries, and each gets a forwarding test.
      - The menu's two items become one, "Connections with this address" → `/connections?ip=`.
      - **Same-page navigation:** the page reads `?ip=` reactively from `$page.url`, not only in `onMount` (`:778-787`). A change resets pagination and reloads through the existing load guard, so a late reply for the old address can't overwrite the new one.
      - **Tests:**
        - daemon: IPv4, IPv6, the address on either side, and a document where it appears only in an unrelated field (excluded); 400 for a bad IP;
        - web: the request carries `ip`, not `q`;
        - same-page navigation from A to B shows B's request and rows, and a late reply for A is dropped.
    - **Alerts' top-destination bars** use `ipHref` (`alerts/+page.svelte:915`).
    - **"View device" links:** `alerts/[category]:701-703` and the AlertDetail and Connections drawers (`AlertDetail.svelte:113/114`, `connections/+page.svelte:1041/1046`) use `ipHref`, labelled "Open device" or "Open address".
    - **Lookup pages** (`geoip/[ip]:159`, `lookup/whois/[ip]:146`, `lookup/dns/[ip]:135`): "View device details" only for LAN, "Open address page" otherwise.
    - **`CertDetail.svelte:122` servers** use `ipHref`.
    - **Connections' top destinations (`:305`)** gain `href`.
    - **Bandwidth `:231`** encodes the IP.

11. **Nav** (`$lib/components/shell/nav.ts`): add "Investigations" under Investigate and "Security posture" (`/compliance`) under System. Update `nav.test.ts` and the header comment, with the old comment kept as OLD CODE.

12. **Proxy timeout.** The catch-all proxy gives the address, domain and filtered certificate paths the longer timeout that the certificate overview already gets (`web/src/routes/api/[...path]/+server.ts:22-25,54`). The value is the daemon budget plus 5 s. Tests:
    - a delayed (12 s) success passes through;
    - a daemon 503 "busy" reaches the page as that reason, not "Daemon unreachable".

13. **Visual fixtures** for the two new pages (loading, empty, error and partial/not-measured states), plus the route list in `web/e2e/visual`.

## Key decisions & tradeoffs

- **Composite aggregations over one PIT** for every presented list. `terms` with `exact_body`/`complete_terms` was rejected: it drops its completeness flag and doesn't complete nested aggs. Lists come back complete, or flagged and their KPI withheld.
- **The snapshot helper is extracted from the certificate pass**, not rewritten, so one tested implementation guards against timeouts and failed shards.
- **LAN policy comes from the daemon (IPv4 only, as the daemon), refreshed every 5 minutes.** Until it loads, links go to the address page, which knows the authoritative answer and offers the device page.
- **The connections table reuses `/api/devices/{ip}/connections`**, which matches either side, and discloses its 10,000-row reach. Cursor paging is deferred: the window and Log Explorer cover the rest.
- **Domain alerts are a narrow, labelled metric with its coverage** ("tagged with this name"), never "alerts for this domain".
- **Certificates drill-in reuses the observed-certificate workflow** (`/certificates?site=&server=`), not a live check, so it shows what was seen in the window.

## Risks / open questions

1. **Composite on `zeek.dns.answers`** (an array) gives one bucket per distinct answer, counting docs containing it. That's right for distinct addresses.
2. **Resolved:** ssl, dns, http, conn and Suricata are all in `NETWORK_INDEX` (`arkime_sessions3-*`; `services/dns_analytics.py:137`, `services/cert_overview.py:221`), so one PIT covers them.
3. **`case_insensitive` needs keyword fields.** It is verified on the G11 by the deploy script; the endpoint fails loudly otherwise.
4. **Load:** about 5 searches plus composite pages per address view, under a 25 s budget and a 30 s PIT keep-alive. Two concurrent drill-downs at most. The window defaults to 24 h.
5. **IPAddress as a link everywhere** has a big blast radius. The `expectNoNestedInteractive` helper on every page test, svelte-check a11y and the visual suite guard it.

## Verification plan

- **Daemon pytest:**
  - **Snapshot helper:** every rejection (timeout, failed shard, missing agg, non-dict), composite paging, the cap, and PIT close on error.
  - **Each endpoint:**
    - 400s (bad IP, bad name incl. a trailing dot handled, bad window) and 401 without the token.
    - Query bodies: both sides, the case-insensitive term, DNS exclusions shared with DNS analytics.
    - Byte directions on both sides, and a self-connection counted once.
    - Byte coverage: a missing field vs an explicit 0.
    - `*_complete=False` withholding KPIs.
    - Answers classification: A, AAAA, CNAME, TXT, empty.
    - Threat intel not loaded / no match / match.
    - Domain alerts coverage: enriched and unenriched mixed, and none at all.
  - **A fake OpenSearch** (in the style of `tests/fake_cert_opensearch.py`) evaluates composite/filter/metric aggs over fixture docs, so counts are checked against real semantics. It also has a test that changes the docs between searches to prove the PIT snapshot is used.
- **Web vitest:**
  - `isLan`, `ipHref` and `domainHref`.
  - IPAddress: link, `linked={false}`, menu open, no nesting.
  - Both new pages: figures, partial/not-measured/not-recorded copy, CardState states, the refresh contract, and the 10,000 notice.
  - `/certificates?site=&server=` filtering and auto-open, with no-SNI IPv4 and IPv6 sites.
  - `nav.test.ts`.
  - Each changed link site.
  - `expectNoNestedInteractive` across pages.
- **Gates:** svelte-check (0 errors), `check:colors`, `check:e2e`, visual.
- **Device:** `scripts/remote/deploy-drill-down.sh` builds the daemon and web, waits for health, then:
  - prints `/api/network/lan`;
  - prints the field mappings and the mixed-case vs lower-case counts;
  - picks a top internet destination and a top domain, and compares the endpoints' totals with direct OpenSearch counts using the same filters;
  - prints the alert host-field coverage.

## Rollback / migration safety

- Additive routes and pages. No index or mapping changes.
- `cert_overview.py` keeps its behaviour, and its 37 tests are the guard.
- Revert the squash commit to roll back.
- An older daemon (404) shows CardState errors, never zeros.

## Observability

- **Daemon:** each handler logs `QueryFailed` reasons and budget exhaustion with the IP or name, and logs incomplete groupings (`*_complete=False`) at info. No telemetry.

## Out of scope (slice 2)

- Raw Suricata category → `/alerts/{slug}`.
- Signatures, ports and Log Explorer domain columns.
- Home KPI windows.
- Domain WHOIS.
- Cursor paging past 10,000 connections.
