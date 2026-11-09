# NetTap release audit: DNS, TLS/certificates, domain summaries (provenance and defects)

Repo: `.claude/worktrees/release-audit` at 446845ec. Paths below are relative to the repo root. Only production code was read. Debugging docs, tests and comments were not used as evidence.

Context that applies throughout:
- Index is `arkime_sessions3-*` (`OPENSEARCH_NETWORK_INDEX`), filtered to `event.provider: zeek` plus the right `event.dataset`. Arkime and Suricata documents in the same index are excluded by the provider filter.
- `config/zeek/nettap.zeek` is **not loaded**. Its mount is commented out at docker/docker-compose.yml:430-434, so Zeek runs Malcolm's own `local.zeek`. Certificate validation (`zeek.ssl.validation_status`) therefore depends on Malcolm's default for `validate-certs`. NetTap does not pin it.
- Time windows come from the browser as UTC ISO strings (`rangeWindow`, `toISOString`) and are parsed by daemon/api/time_range.py:33-43. An unreadable bound returns 400, and a value without a zone is read as UTC. Charts use epoch-aligned UTC slots (daemon/storage/time_slots.py:44-72) and are labelled in browser local time (`chartTime`).
- Refresh: pages load on mount, on a range change and on the top-bar refresh (`registerPageRefresh`). The DNS, Domain and Certificates pages have no auto-refresh. A failed section keeps its last good data and shows a stale notice.
- The daemon runs with host networking (docker/docker-compose.yml:836).

## Part 1: Provenance table

| Item | UI location | Producer & source fields | Index / fields queried | Query (filters/agg/size/window/tz) | Backend calc | Frontend format & units | Refresh/freshness | Class | Absent/stale/error behaviour |
|---|---|---|---|---|---|---|---|---|---|
| Total queries | /dns KPI (web/src/routes/dns/+page.svelte:669) | Zeek dns.log rows (one per query/response transaction, unanswered included) | arkime_sessions3-*: event.provider, event.dataset=dns, zeek.dns.query, destination.port, destination.ip, source.ip (excluded IPs) | range on @timestamp [from,to]. must_not: query "pcap-monitor", and ports 5353/5355/137 to multicast/RFC1918/link-local, and excluded source IPs (dns_analytics.py:24-63, 90-112). size 0, track_total_hits true (531-533) | hits.total.value (558-563) | formatCompactNumber ("12.3K"). Note shows the range words | On load, range change, manual refresh. No ingest-lag marker | Observation (Zeek transactions, not name resolutions) | null before load shows "—". Failure shows a warn notice and keeps old stats (660-662). OpenSearch error returns 502 (dns.py:178-180). Partial shard failure is not detected |
| Unique domains | /dns KPI (:670) | zeek.dns.query | same | `cardinality` on zeek.dns.query (dns_analytics.py:535) | HLL value | compact number, presented as exact | same | Estimate (HLL, approximate above ~3,000 names) | as above |
| NXDOMAIN errors | /dns KPI (:671-678) | zeek.dns.rcode_name | same plus rcode_name | `filter` agg on rcode_name=NXDOMAIN (536-538) | doc_count | compact number. Note: "Lookups for names that don't exist" | same | Observation | as above |
| Average resolution | /dns KPI (:679-686) | zeek.dns.rtt (seconds, present only when a reply was seen) | same plus zeek.dns.rtt | `avg` of rtt (542). Median by HDR percentile is also computed (543-554) | avg×1000, rounded to 2 places. `None` becomes 0 (569-571). Median is returned but unused (572-576) | `toFixed(1)` + "ms". Median not shown (web/src/lib/api/dns.ts:47-52 has no median field) | same | Observation (mean). Measures the hop NetTap sees (router to upstream in bridge mode, device to router in LAN mirror) | No answered queries shows **"0.0 ms"**, not "—" |
| Queries over time | /dns hero chart (:688-699, 559-569) | dns rows | same | `date_range` slots aligned to the epoch in UTC, interval per range: 1h=5m, 6h=10m, 24h=15m, 7d=1h, 30d=6h (+page :76-85). Unknown interval falls back to 5m (dns_analytics.py:333-334). Too many slots returns 400 (dns.py:140-146) | doc_count per slot (356-364) | AreaChart. X in local time, Y compact. "Busiest" highlight | same. First slot starts before `from`, last slot is in progress | Observation | Empty: "No timeline data…". Failure: error card, or a stale notice if older data exists (625-638) |
| Most looked-up domains | /dns card (:701-706, 571-582) | zeek.dns.query, source.ip | same | `terms` zeek.dns.query size=limit(50), order _count, no shard_size. Subagg cardinality source.ip (dns_analytics.py:122-135) | buckets → {domain,count,unique_clients} | First 10 of 50. Detail "N clients" | same | Observation. Clients is an estimate. Counts can be low on windows spanning many indices (suspected, terms shard error) | Empty: "No domains recorded". Failure: error card. Non-integer `limit` gives an uncaught ValueError, so 500 (dns.py:55) |
| Domains table | /dns card "top 50" (:708-713, 583-599) | same | same | same request as above | same | DataTable, client-side filter and sort. Subtitle says "top 50" | same | Observation | same |
| Query types | /dns card (:715-720, 600-610) | zeek.dns.qtype_name | same | `terms` qtype_name size 20 (dns_analytics.py:293-304) | buckets | Share % = count / sum of returned types (:239, 607) | same | Observation | Empty or error card |
| DNS by device | /dns card (:722-780) | zeek.dns.query, qtype_name for source.ip=device | same plus term source.ip | `terms` zeek.dns.query size 200. Subagg qtype_name size 10 (dns_analytics.py:189-219) | buckets | First 50 of the sorted 200. Footer names the 200 cap (:772-778) | On Lookup, and re-run on range change | Observation | Empty: **"This device made no DNS queries in this time range."** (:754). Failure: error card (:751-752). An IP that isn't valid gives an OpenSearch 400, shown as 502 |
| NXDOMAIN errors table | /dns card (:782-788, 611-622) | zeek.dns.query, rcode_name, source.ip | same | filter rcode=NXDOMAIN. `terms` query size 100. Subagg `terms` source.ip size 10 (dns_analytics.py:243-272) | buckets | Clients: first 3 plus "+N", where N ≤ 7 (:549-557). No "top 100" in the subtitle | same | Observation | Empty: "No NXDOMAIN errors detected. That's a good sign." (:785) |
| Suspicious DNS patterns | /dns card (:790-825) | zeek.dns.query, qtype_name, source.ip | same | Two composite scans over every name (all_buckets, cap 500,000, no `what` check): all names, and TXT-only names (dns_analytics.py:151-180, 380, 452-457) | long_domain if len>50. high_frequency if count>500 and clients≤2. txt_abuse if TXT count>50. Fixed thresholds whatever the window. Reverse/plex names skipped for the first two (385-389) | List of 50 with "Show all". SeverityPill medium/low | same. No time budget. Runs on the route pool (offload.py:13) | Heuristic | Empty: "No suspicious DNS patterns detected." Failure: error card (:794-795). A truncated or partly failed scan reads as complete |
| Lookups | /domain/[name] KPI (web/src/routes/domain/[name]/+page.svelte:199) | dns rows for the name | zeek.dns.query (name_match, case-insensitive, ± trailing dot) plus the DNS page exclusions | Snapshot (PIT) search, track_total_hits (daemon/api/domains.py:187-196, 430-432). Mapping check that the field is keyword (hostnames.py:120-129) | total_hits | fmt. "DNS queries for this name" | Load, range change, manual. 25 s budget, then 503 | Observation | Not keyword, budget exceeded or shard failure gives 503 with a reason. The page shows an error card, or a stale notice with older data |
| Devices that looked it up | /domain KPI and table (:200-207, 257-272) | source.ip | same | composite source.ip, max 5,000, LAST_SEEN max @timestamp (domains.py:107-135, 197-199) | rows sorted. `askers_complete` | KPI shows "—" with "too many to count" when capped | same | Observation | Empty: "No device looked it up". Incomplete: notice |
| Addresses it resolved to / What it resolved to | /domain KPI and table (:208-215, 274-284) | zeek.dns.answers (IPs, CNAME targets, TXT) | zeek.dns.answers | composite terms, max 5,000 (domains.py:231-245) | normalised and merged. `addresses` = distinct IP answers, or null when capped (238-255) | "Lookups whose answer held each value" | same | Observation | Empty: "No answers recorded" |
| Response codes | /domain card (:316-324) | zeek.dns.rcode_name | same | composite with missing_bucket. Over 5,000 values raises QueryFailed (domains.py:166-178, 246) | sorted | BarList. Missing rcode shows as "No response code" | same | Observation | 503 on failure |
| Lookups over time | /domain chart (:220-235) | dns rows | same | chart_slots (drilldown_runner.py:119-125) | timeline() (128-133) | AreaChart | same | Observation | Empty: **"None of your devices asked for this name in this window."** (:224) |
| TLS sessions / servers / devices / verification | /domain KPI and TLS card (:216, 286-314) | Zeek ssl.log: zeek.ssl.server_name (SNI), destination.ip, source.ip, zeek.ssl.validation_status | zeek.ssl.server_name name_match, event.dataset=ssl. **No excluded-IP filter (disclosed)** | count, plus composite destination.ip and source.ip (max 5,000), plus every validation_status (domains.py:273-313, 433) | Missing status becomes "unchecked" (301-305) | "Verification: verified (n); not checked (n)" (:292). Note on TLS 1.3, resumption and exclusions (:305-310) | same | Observation (SNI as the client sent it). DNS and SNI are kept apart, not conflated | Empty: "No TLS sessions for this name…" |
| HTTP requests | /domain card (:326-338) | zeek.http.host | zeek.http.host name_match | count (domains.py:434-440) | count | big number | same | Observation (plaintext HTTP only) | 503 on failure |
| Alerts tagged with this name | /domain card (:237-253) | Suricata alert docs: related.hosts, dns.question.name, tls.client.server_name, url.domain | those fields (keyword or .keyword) | filter agg plus exists agg (domains.py:352-400) | tagged / with_host / in_window | "At least N" when partial (domain-view.ts:24-27). Coverage sentence | same | Observation (lower bound, disclosed) | 503 on failure |
| Needs a look (findings) | /certificates KPI and list (web/src/routes/certificates/+page.svelte:713-720, 759-797) | ssl.log zeek.ssl.cert_chain_fps (first fingerprint = server cert), server_name, destination.ip/port, source.ip, validation_status, ssl_version. x509.log zeek.x509.* | ssl: range, provider, dataset=ssl, exists cert_chain_fps, must_not excluded source IPs (cert_overview.py:486-511). PIT + search_after, page 10,000 (289-315). x509: terms fingerprint chunk 1,000 + top_hits newest (357-410) | Exact tallies. Findings: unverified / unverified-alongside-verified (public servers only), expired-at-use (sessions after not_after), chain-expired, weak (SHA-1/MD5, RSA/DSA <2048), device-expiry (local, ≤30 days) (cert_findings.py:533-595, 630-699) | AlertRow with severity, title, evidence, sessions, last seen. First 10, then show all | Load, range change, manual. 50 s budget. Proxy allows 60 s | Observation (Zeek validation) plus heuristic (weak, "unexpected authority"). Expiry is judged on the daemon clock | 503 with reason (busy/slow/too big/unavailable) (api/certificates.py:124-145). Error card or stale notice. Empty: "Nothing needs a look…" (:767-772) |
| Your devices' certificates | /certificates KPI and table (:721-730, 826-853) | same tallies, servers where scope_of(server)=="local" | same | same pass | One row per (server, port, site), using the last certificate. days_left = floor(not_after − now) (cert_findings.py:630-699) | "Runs out" in words (cert-view.ts:146-151). Verification words (310-317) | same | Observation. Local means fixed RFC 1918/ULA/link-local (cert_findings.py:37-63) | Empty: "None of your devices served a certificate over TLS 1.2 or older…" (:839) |
| Certificates seen | /certificates KPI (:731-738) | same | same | same | len(by_cert), len(by_site) (cert_findings.py:326-337) | "across N sites · TLS 1.2 and older" | same | Observation | as above |
| All certificates (sites) | /certificates table (:856-916) | same | same | same. Each list capped at 5,000 after computing (cert_overview.py:533-555) | site rows, status chip (cert-view.ts:302-308) | 25 per page. Truncation notice (:752-754) | same | Observation | Empty: "No certificates… TLS 1.3 hides them." (:869) |
| Certificate drawer facts | CertDetail.svelte:115-205 | x509 subject/issuer/validity/key/sig/SAN, tallies | zeek.x509 `_source` subfields (cert_overview.py:135-163) | newest x509 record at any time (not window-bound) | self_issued = subject_full == issuer_full (162) | formatDay / formatWhen (en-GB, local tz) | same | Observation. "Self-signed" means self-issued (heuristic) | No x509 record: "Details unavailable" (:169-171) plus a page notice (+page :743-750) |
| Quiet authority switches | /certificates foot (:798-819) | authorities per site | same | same | sites with ≥2 authorities, all verified (cert_findings.py:702-722) | collapsible list | same | Heuristic | Hidden when empty |
| DNS activity (device) | /devices/[ip] card (web/src/routes/devices/[ip]/+page.svelte:986-991) | zeek.dns.query for source.ip | provider, dataset=dns, source.ip, DNS_LOOKUP_EXCLUSION | `terms` zeek.dns.query size 50, shard_size _ALL_TERMS (daemon/api/devices.py:1124-1145) | buckets | Client drops `._tcp.`, `._udp.`, `.arpa`, then shows 10 (:650-654). Sub "Lookups by domain" | device page refresh | Observation | Empty: "No DNS data." A failure fails the whole device reply with 502 (devices.py:1155-1161) |
| Reverse DNS lookup | /lookup/dns/[ip] (web/src/routes/lookup/dns/[ip]/+page.svelte:115-149) | NetTap host resolver: gethostbyaddr, then getaddrinfo | none (live) | 6 s total. Cache 1 h for a hit, 5 min for a miss (daemon/api/lookup.py:24-29, 97-135) | Forward addresses fall back to gethostbyaddr's list (the queried IP) when the forward lookup fails (122-133) | facts list | Cached up to 1 h. Lookup time not shown | External enrichment (live) | Timeout: "Reverse DNS lookup timed out". NXDOMAIN shows the error card "No reverse DNS record found". Other errors give 500, then "Lookup failed" |
| WHOIS lookup | /lookup/whois/[ip] | `whois` CLI | none (live) | 15 s. Cache 24 h for success, 5 min for failure (lookup.py:138-168) | Regex fields (54-65). Failed if exit≠0, empty output or no parsed field (160) | facts, raw toggle | Cached up to 24 h, not shown | External enrichment | No parsed fields shows "Lookup failed" and hides the raw reply (whois page :118-119) |
| DNS recon | /tools/dns-recon | `dig` against NetTap's resolver | none (live) | Types allow-listed. Concurrent queries, +time=2 +tries=2, 10 s (dns_recon_service.py:143-187) | Parses only the ANSWER SECTION (107-141). Non-zero exit becomes an error | A card per type. "No X records found" (tools/dns-recon/+page.svelte:184-188). Errors in a notice | live | External (live) | SERVFAIL/REFUSED/NXDOMAIN read as "No X records found" (see DNS-6) |
| SSL cert check | /tools/ssl-cert (linked "Check it now" / "Its certificate now") | `openssl s_client` from the daemon (host network) | none (live) | Any host matching `[A-Za-z0-9.\-:]`, any port 1-65535, 10 s ×2 (ssl_cert_service.py:24-89, 196-332) | trusted = verify code 0 with no stderr verify errors (api/tools.py:268-271). name_match | Trust chip, expiry chip on the **browser** clock (ssl-cert/+page.svelte:97-110) | live | External (live) | Errors come back as 200 with `error`. The page shows "Inspection failed" (:185-186) |
| Home page | / | n/a | n/a | n/a | n/a | No DNS, TLS or certificate card. DNS and TLS appear only as protocol/category shares (traffic slice) | n/a | n/a | n/a |

## Part 2: Findings

### DNS-1: P1. Absence messages claim facts NetTap cannot observe. Encrypted DNS and DNS that never crosses the tap are not mentioned anywhere.
- Evidence:
  - /dns device empty state: "This device made no DNS queries in this time range." (web/src/routes/dns/+page.svelte:754).
  - Domain page: "None of your devices asked for this name in this window." (web/src/routes/domain/[name]/+page.svelte:224).
  - NXDOMAIN empty state: "That's a good sign." (dns/+page.svelte:785).
  - Device page: "No DNS data." (devices/[ip]/+page.svelte:990).
  - Every DNS figure is Zeek dns.log only (dns_analytics.py:24-27). A grep of web/src for DoH, DoT, "encrypted DNS" or port 853 finds nothing on any DNS, domain or device page; the only match is an alert-category comment at web/src/lib/api/alerts.ts:510.
- Failure scenarios:
  - (a) A phone with Android Private DNS (DoT), or Firefox or Chrome using DoH, or iCloud Private Relay, makes thousands of lookups. NetTap states the device "made no DNS queries". On the domain page, a malware domain resolved over DoH reads "None of your devices asked for this name".
  - (b) In the default bridge placement (modem to router, CLAUDE.md "Architecture"), every DNS row's `source.ip` is the router's WAN address after NAT. Lookups answered from the router's cache never cross the tap. Every LAN IP typed into "DNS by device" therefore gets the false "made no DNS queries".
- Affected UI: /dns "DNS by device" and NXDOMAIN, /domain/[name] timeline, /devices/[ip] DNS activity.

### DNS-2: P2. "Suspicious DNS patterns" uses fixed absolute thresholds whatever the window, and the beaconing rule cannot work behind NAT.
- Evidence:
  - `entry["count"] > 500 and entry["unique_clients"] <= 2` flags "potential beaconing" at severity medium (dns_analytics.py:405-416).
  - TXT `count > 50` (458-468).
  - The page offers 1h to 30d (dns/+page.svelte:61) and sends the selected window (:345).
  - `unique_clients` is a cardinality of `source.ip` (164).
- Failure scenarios:
  - At 30d, 500 lookups is 17 a day, so nearly every routinely used domain from a single device is flagged "potential beaconing" (medium).
  - In bridge mode all DNS has one source (the router WAN IP), so `unique_clients <= 2` is always true and every domain over 500 lookups is flagged.
  - The number of "findings" grows with the selected range rather than with behaviour.
- Affected UI: /dns Suspicious DNS patterns.

### DNS-3: P2. The "Average resolution" KPI shows the mean, which the daemon itself documents as skewed, and shows 0.0 ms when nothing was measured.
- Evidence:
  - The daemon computes an exact median "because a few 20 s retries skew the average" (dns_analytics.py:543-554, 572-576).
  - The web type has no median field (web/src/lib/api/dns.ts:47-52), and the KPI renders `avg_resolution_ms` (dns/+page.svelte:679-686).
  - A null average becomes 0: `(… .get("value", 0) or 0) * 1000` (dns_analytics.py:569-571).
- Failure scenarios:
  - A handful of 20 s timeouts turns a typical 6 ms resolver into "Average resolution 400 ms".
  - With zero answered queries (a resolver outage, or only unanswered queries), the KPI reads "0.0 ms", which looks perfect.
- Affected UI: /dns KPI row.

### DNS-4: P2. The suspicious-DNS scan can be silently partial.
- Evidence:
  - `_all_domains` calls `all_buckets` without `what` (dns_analytics.py:159-165). With no `what`, `all_buckets` skips `checked()`, so a page that timed out or failed on some shards reads as fewer buckets (storage/all_buckets.py:45-62).
  - Hitting the 500,000 cap is only logged (dns_analytics.py:166-170).
  - The other DNS aggregations do not inspect `_shards.failed` either (dns_analytics.py:137, 221, 274, 306, 354, 558).
- Failure scenario: a slow or shard-failing 30d window returns fewer names. The card then says "No suspicious DNS patterns detected." (dns/+page.svelte:798-799), and the KPIs show smaller counts with no warning.
- Affected UI: /dns Suspicious patterns and all /dns figures.
- Suspected magnitude: low on one node. Confirm by forcing a shard failure, or by checking `_shards.failed` in replies on the G11.

### DNS-5: P2. Reverse DNS shows the queried IP as the "Forward lookup addresses" when the forward lookup failed, so a forged PTR looks confirmed.
- Evidence:
  - `forward = list(addrs)` (gethostbyaddr's list, which is the queried address) is kept when `getaddrinfo` raises or times out (daemon/api/lookup.py:122-133).
  - The answer is cached for an hour as a hit (134).
  - The UI label is "Forward lookup addresses" (lookup/dns/[ip]/+page.svelte:135-138).
- Failure scenario: an attacker sets the PTR for their IP to `login.microsoftonline.com.` The forward lookup does not return that IP (or fails), yet the page shows the PTR name with "Forward lookup addresses: <attacker IP>". That reads as forward-confirmed.
- Affected UI: /lookup/dns/[ip].

### DNS-6: P2. DNS recon shows SERVFAIL, REFUSED and NXDOMAIN as "No X records found".
- Evidence:
  - dig exits 0 for any reply whatever its rcode. Only a non-zero exit is treated as an error (dns_recon_service.py:172-176).
  - The parser reads only the ANSWER SECTION and ignores the `status:` header line that `+comments` prints (107-141).
  - The UI shows "No {type} records found" (web/src/routes/tools/dns-recon/+page.svelte:184-188).
- Failure scenario: a domain with broken DNSSEC, a lame delegation, or a resolver that refuses the query shows "0 records found / No A records found". That is indistinguishable from "the name has no A record".
- Affected UI: /tools/dns-recon, reached from the domain page's "Look it up now" (domain/[name]/+page.svelte:340-345).

### DNS-7: P3. DNS recon offers SRV but rejects every SRV-style name.
- Evidence: `ALLOWED_RECORD_TYPES` includes SRV (dns_recon_service.py:24), but `DOMAIN_PATTERN` has no underscore (26).
- Failure scenario: `_sip._tcp.example.com` (SRV) and `_dmarc.example.com` (TXT) get 400 "Invalid domain name".

### DNS-8: P3. Truncation and approximation are not disclosed on several DNS lists.
- Evidence:
  - The NXDOMAIN list is `terms` size 100 (dns_analytics.py:259), with no cap in its subtitle (dns/+page.svelte:782).
  - Clients per NXDOMAIN name are capped at 10 (dns_analytics.py:265) and rendered as "+N" (dns/+page.svelte:554-556), so "+7" can mean +700.
  - "Unique domains" is an HLL `cardinality` (dns_analytics.py:535), presented as an exact count.
  - Top-50 `terms` have no `shard_size` (127-131). The device query sets `shard_size: _ALL_TERMS` for exactly this reason (devices.py:1141). Over 7d/30d windows spanning many daily indices, top-50 counts can be low or a domain can be missing. This is suspected; confirm with `show_term_doc_count_error` / `doc_count_error_upper_bound` on the G11.
  - The device page drops `._tcp.`, `._udp.` and `.arpa` names from the top 50 and shows 10 (devices/[ip]/+page.svelte:650-654) under "Lookups by domain", with no note.

### DNS-9: P3. "Queries" and "Lookups" count Zeek transactions, not name resolutions, and resolver failures never appear on /dns.
- Evidence:
  - Totals are dns.log hit counts (dns_analytics.py:558-563; domains.py:248). Each A and AAAA pair, each retransmission and each query to a second resolver is a separate row, and unanswered queries are included.
  - /dns shows only NXDOMAIN (KPI and table). It shows no SERVFAIL, REFUSED or "no reply" figure. Only the domain page shows rcodes (domain/[name]/+page.svelte:316-324).
  - The domain KPI sub says "DNS queries for this name" (:199), which is accurate. The /dns page sub "Domain queries…" (:647) does not explain what a query is.
- Failure scenario: an upstream resolver outage leaves "Total queries" steady and NXDOMAIN at zero, so /dns looks healthy.

### DNS-10: P3. The first and last timeline slots are partial and unmarked.
- Evidence: slots are aligned to the UTC epoch, starting at the slot that holds `from` (time_slots.py:55-62), while the query filter starts at `from` (dns_analytics.py:66-76). The last slot is still in progress and also lags ingest (Zeek, then Logstash, then OpenSearch).
- Failure scenario: the 24h chart always dips at both ends, which reads as a drop in DNS activity right now.
- Affected UI: /dns and /domain charts.

### DNS-11: P3 (suspected). The suspicious-DNS endpoint has no time budget.
- Evidence: two full composite scans of up to 500,000 names each (all_buckets.py:14) run on the 8-thread route pool (offload.py:13, dns.py:153-166). The web proxy gives up at 10 s (web/src/lib/server/daemon.ts:77), but the thread keeps running.
- Failure scenario: repeated 30d refreshes pile up blocked workers, which stalls other daemon routes.
- To confirm: time `/api/dns/suspicious` for 30d on the G11.

### DNS-12: P3. The `limit` parameter is unvalidated.
- Evidence: `int(request.query.get("limit","50"))` has no try and no upper bound (dns.py:55).
- Failure scenario: a non-integer limit returns 500. A huge limit sends an unbounded `terms` size to OpenSearch.

### TLS-1: P2. The certificate pages classify "your network" by a fixed list of private ranges, so LAN servers on IPv6 global or non-RFC 1918 addresses become internet servers with "Couldn't verify" findings.
- Evidence:
  - `_LOCAL_NETS` is RFC 1918, 169.254/16, fc00::/7 and fe80::/10 (cert_findings.py:37-47), and `scope_of` uses only that list (55-63).
  - Non-local cells feed the verification findings (227-232, 542-561), and only local cells feed "Your devices" and device-expiry (229-232, 630-699).
  - The daemon's own LAN rule is configurable (`lan_check`, drilldown_runner.py:65-75), but certificates don't use it.
- Failure scenario: a NAS or printer reached over its global IPv6 address (normal on a home IPv6 network), or a Tailscale node on 100.64.0.0/10, serves a self-signed admin certificate. It appears as "A device got a certificate for nas.home that couldn't be verified" at medium severity. The explanation raises interception (cert-view.ts:232-236). The device is missing from "Your devices' certificates", and its expiry is never warned about.
- Affected UI: /certificates findings, devices table and KPI.

### TLS-2: P3. "Nothing needs a look" can be shown when nothing was verified at all.
- Evidence:
  - Unchecked sessions never count as failures (cert_findings.py:66-68).
  - The empty state reads "None failed verification on a server outside your network…" (certificates/+page.svelte:771).
  - Verification depends on Malcolm's default `local.zeek` loading validate-certs. NetTap neither sets nor checks it: the compose file has no setting for it, and nettap.zeek is unmounted (docker-compose.yml:430-434).
- Failure scenario: an upstream Malcolm change, or an operator environment variable, disables validate-certs. Every session becomes "unchecked", and the page shows a green "Nothing needs a look" with that sentence. A "Not checked" chip shows only per site in the table (cert-view.ts:305).
- Affected UI: /certificates findings card.

### TLS-3: P3. The legacy certificate endpoints report unknown certificates as `status: "valid"`, and expired self-signed certificates as "self-signed".
- Evidence: `_status_now` returns "valid" when there are no details (cert_findings.py:358-359), and "self-signed" before the expiry check (356-357). The rows go out from /api/certificates, /expiring and /self-signed (api/certificates.py:153-272).
- Impact: the current UI does not call these (only commented-out imports in certificates/+page.svelte:266-270), but they remain public API.

### TLS-4: P3. The SSL check tool lets an authenticated user probe any host and port from the daemon's host network.
- Evidence:
  - `HOST_PATTERN` allows `127.0.0.1`, `::1`, `localhost` and `169.254.169.254`, with any port from 1 to 65535 (ssl_cert_service.py:24, 55-89).
  - `s_client -connect host:port` runs from a host-network container (docker-compose.yml:836).
  - A timeout ("timed out") is distinguishable from refused or non-TLS ("No certificate received") (254-259, 311-317). The request needs a session (hooks.server.ts PUBLIC_PATHS).
- Impact: the tool doubles as a loopback/LAN port and TLS-service probe. It is low risk on a single-admin appliance, and blocking private targets would break checking LAN devices. Consider at least denying loopback.

### TLS-5: P3. Two clocks and an off-by-one on expiry in the live tool.
- Evidence: the SSL tool computes `Math.floor((notAfter − Date.now())/day)` on the browser clock (tools/ssl-cert/+page.svelte:105-109). The Certificates page uses the daemon clock with Python's floor (cert_monitor.py:115; cert_findings.py:353-364).
- Failure scenario: a certificate that expired 2 hours ago reads "Expired 1 day ago" in the tool. A browser with a wrong clock disagrees with the Certificates page.

### TLS-6: P3 (suspected, adjacent slice). MAC correlation reads JA3 from `tls.ja3`.
- Evidence: `tls.ja3` is used at mac_correlator.py:61 and 343. Malcolm/ECS normally writes `zeek.ssl.ja3` and `tls.client.ja3`; the connection drawer reads `zeek.ssl.ja3` (ConnectionDrawer.svelte:132).
- Impact: if the field is absent, JA3 overlap is always 0 while its 0.25 weight stays in the score (mac_correlator.py:447-455), which caps similarity.
- To confirm: `GET arkime_sessions3-*/_mapping/field/tls.ja3,tls.client.ja3,zeek.ssl.ja3`.

### TLS-7: P3. Certificate "Sessions" are only full TLS 1.2-and-older handshakes, and the domain page shows TLS 1.3 as "not checked".
- Evidence:
  - The pass requires `exists cert_chain_fps` (cert_overview.py:500), so resumed and TLS 1.3 sessions are dropped. The page subtitle mentions TLS 1.3 but not resumption (certificates/+page.svelte:698-701).
  - The domain page counts every SNI session and folds a missing status into "unchecked" (domains.py:301-305), rendered as "not checked (N)" (domain/[name]/+page.svelte:292). The cause (an encrypted certificate) appears only indirectly in the note at :305-310.

### Checked and found sound (no finding)
- DNS and SNI are not conflated. /dns uses only `zeek.dns.query`. The domain page keeps DNS (`zeek.dns.query`), TLS (`zeek.ssl.server_name`) and HTTP (`zeek.http.host`) as separate, labelled figures.
- No wording in this slice implies decryption. TLS 1.3 hiding certificates is stated on /certificates (:698-701, 869).
- Failed requests are not turned into empty data. The DNS clients throw on non-2xx (lib/api/dns.ts:84 and following). Certificates answer 503 with a reason, and the client checks the reply's shape (lib/api/certificates.ts:409-419). The domain page uses a snapshot that raises on shard failure or timeout. The `pcap-monitor` and mDNS/LLMNR/NetBIOS exclusions apply consistently across /dns, /domain, the device page and Logs.
- No mock, random or hardcoded data in this slice.
- Certificate expiry ("expired-at-use") compares UTC session timestamps with UTC not_after. "Expired/expiring" is stated as judged against now.

## Part 3: OpenSearch fields queried

Grouped by field name. One line per use site, with file:line.

### Time and source filters
- `@timestamp`
  - daemon/services/dns_analytics.py:70 (range filter)
  - daemon/storage/time_slots.py:65 (date_range timeline)
  - daemon/services/cert_overview.py:300 (docvalue), :388 (top_hits sort), :446 (after-expiry range), :491 (range)
  - daemon/api/alerts.py:145 (`_time_range_filter`, used by domains.py:429 and devices.py:1129)
  - daemon/api/drilldown_runner.py:95 (LAST_SEEN max)
- `event.provider`
  - daemon/services/dns_analytics.py:25
  - daemon/services/cert_overview.py:370, :498
  - daemon/api/drilldown_runner.py:101 (domains.py:433, :435)
  - daemon/api/devices.py:1131
- `event.dataset`
  - daemon/services/dns_analytics.py:26 (dns)
  - daemon/services/cert_overview.py:371 (x509), :499 (ssl)
  - daemon/api/drilldown_runner.py:102 (ssl, http)
  - daemon/api/devices.py:1132 (dns)

### DNS fields
- `zeek.dns.query`
  - daemon/services/dns_analytics.py:31 (must_not term), :128 (top terms), :163 (composite), :205 (device terms), :258 (NXDOMAIN terms), :535 (cardinality)
  - daemon/api/domains.py:58 / :431 (name_match)
  - daemon/api/devices.py:1140 (terms)
  - daemon/api/logs.py:1092 (top-dns terms)
  - daemon/services/hostnames.py:98 (mapping check via domains.py:417)
- `zeek.dns.qtype_name`
  - daemon/services/dns_analytics.py:212, :299, :456
- `zeek.dns.rcode_name`
  - daemon/services/dns_analytics.py:251, :537
  - daemon/api/domains.py:246
- `zeek.dns.rtt`
  - daemon/services/dns_analytics.py:542 (avg), :550 (HDR percentile)
- `zeek.dns.answers`
  - daemon/api/domains.py:233

### Address and port fields
- `source.ip`
  - daemon/services/dns_analytics.py:132 (cardinality), :164 (cardinality), :198 (term), :265 (terms)
  - daemon/services/excluded_ips.py:637 (must_not terms, used by dns_analytics.py:111 and cert_overview.py:509)
  - daemon/services/cert_overview.py:58 (docvalue)
  - daemon/api/domains.py:198, :278 (composite)
  - daemon/api/devices.py:1130 (term)
- `destination.ip`
  - daemon/services/dns_analytics.py:59 (must_not terms)
  - daemon/services/cert_overview.py:56 (docvalue), :508 (term)
  - daemon/api/domains.py:275 (composite)
- `destination.port`
  - daemon/services/dns_analytics.py:58 (must_not terms)
  - daemon/services/cert_overview.py:57 (docvalue)

### TLS and certificate fields
- `zeek.ssl.cert_chain_fps`
  - daemon/services/cert_overview.py:51 (constant), :297 (`_source`), :443 (terms), :500 (exists)
- `zeek.ssl.server_name`
  - daemon/services/cert_overview.py:55 (docvalue), :505-506 (mapping check + name_match)
  - daemon/api/domains.py:59 / :433 (name_match)
- `zeek.ssl.validation_status`
  - daemon/services/cert_overview.py:59 (docvalue)
  - daemon/api/domains.py:303 (composite)
- `zeek.ssl.ssl_version`
  - daemon/services/cert_overview.py:60 (docvalue)
- `zeek.x509.fingerprint`
  - daemon/services/cert_overview.py:52 / :372 (terms filter), :380 (terms agg)
- `zeek.x509` (whole object `_source`)
  - daemon/services/cert_overview.py:389
  - Subfields read from `_source` at cert_overview.py:137-158: `certificate_subject` (.CN), `certificate_issuer` (.CN, .O), `certificate_subject_full`, `certificate_issuer_full`, `san_dns`, `certificate_not_valid_before`, `certificate_not_valid_after`, `certificate_key_type`, `certificate_key_length`, `certificate_sig_alg`, `certificate_serial`

### HTTP and alert host fields
- `zeek.http.host`
  - daemon/api/domains.py:60 / :435 (name_match)
- `related.hosts`: daemon/api/domains.py:63 (exists / name_match at :372-374; mapping check hostnames.py:159)
- `dns.question.name`: daemon/api/domains.py:64 (same as related.hosts)
- `tls.client.server_name`: daemon/api/domains.py:65 (same)
- `url.domain`: daemon/api/domains.py:66 (same)

### Adjacent (outside this slice)
- `tls.ja3`: daemon/services/mac_correlator.py:61, :343 (suspected not to exist, see TLS-6)
- `dns.question.name` on DNS docs: daemon/services/mac_correlator.py:59
