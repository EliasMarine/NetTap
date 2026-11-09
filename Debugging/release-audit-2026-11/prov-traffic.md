# NetTap release audit: traffic totals, direction, bandwidth (slice: TRF)

Repo: `.claude/worktrees/release-audit` at 446845ec. Read-only. Production code only; comments, tests and tracking docs are not taken as proof (where a code comment is cited, it is cited as the author's own statement, not as verification).

Paths below are relative to the repo root. `D/` = `daemon/`, `W/` = `web/src/`.

Ground facts used throughout (from code, labelled where they rest on Malcolm behaviour not visible in this repo):
- Every byte/connection figure in this slice reads Zeek `conn` docs only: `event.provider: zeek` + `event.dataset: conn` in `arkime_sessions3-*` (D/api/traffic.py:47-52, D/services/bandwidth_tracker.py:88-93, D/services/traffic_classifier.py:901-911, D/services/live_connections.py:463-466). Arkime sessions and Suricata flow docs are excluded, so there is **no Arkime + Zeek double counting at query level** (verified in code).
- `source.bytes` / `destination.bytes` are treated as Zeek `orig_ip_bytes` / `resp_ip_bytes` (IP-layer bytes incl. IP/TCP headers, excluding Ethernet framing) per D/services/bandwidth_tracker.py:104. The Malcolm Logstash mapping is not vendored here, so this is **not verified in-repo** (field list, part 3, says how to check).
- `@timestamp` of a Zeek conn doc is the connection's first packet (Zeek `ts`), and the doc is written only when Zeek closes or times out the connection. NetTap's own code states this (D/api/live.py:33-35). Every window filter and time bucket in this slice is on `@timestamp` (D/api/traffic.py:210-220, D/storage/time_slots.py:47-71).
- "Upload" = `source.bytes` (originator to responder), "Download" = `destination.bytes` (responder to originator) everywhere except the device page (D/api/devices.py:1304-1316, not in this slice).
- Units are decimal (1,000) everywhere in this slice: W/routes/home.ts:15-31, W/lib/api/logs.ts:239-251, W/routes/bandwidth/+page.svelte:66-78, W/lib/utils/bitrate.ts. Bits only on the device Live bandwidth card.

---

## Part 1: Provenance table

| Item | UI location | Producer & source fields | Index / fields queried | Query (filters/agg/size/window/tz) | Backend calc | Frontend format & units | Refresh/freshness | Class | Absent/stale/error behaviour |
|---|---|---|---|---|---|---|---|---|---|
| Bandwidth KPI (total) | Home, KPI 1 (W/routes/+page.svelte:688-699) | Zeek conn `orig_ip_bytes`+`resp_ip_bytes` via Malcolm | `arkime_sessions3-*`: `source.bytes`, `destination.bytes`, filter `event.provider`,`event.dataset`,`@timestamp`, must_not `source.ip` | `GET /api/traffic/summary` (D/api/traffic.py:235-322): range `@timestamp` gte from / lte to (UTC ISO), `sum` aggs, `track_total_hits`, excluded-IP must_not on **source only** (D/services/excluded_ips.py:613-637). Window = Home pill (1h..30d) ending at now floored to the minute (W/lib/stores/alertSnapshot.ts:26-29) | `orig+resp` (D/api/traffic.py:299-313) | `formatBytes` 1,000-based, "Bandwidth" label but a volume (GB) | Home loader, 30 s Auto (W/routes/+page.svelte:241-249). Only connections that **started** in the window **and have already ended + been ingested** | Observation (start-time attribution; in-progress flows absent) | Failure: keeps last value + "Couldn't load…" (475); a partial-shard reply is shown as complete (no `checked`, D/api/traffic.py:289) |
| Down / up split | Home KPI sub (W/routes/+page.svelte:473-479) | as above | `destination.bytes`=down, `source.bytes`=up | as above | none | "↓ X down · ↑ Y up" | as above | Heuristic direction (originator = LAN assumed) | as above |
| Bandwidth & Connections trend | Home KPI deltas (450-460) | two summary calls | as above | current window vs previous equal-length window (W/routes/home.ts:48-57) | `trendPercent` (home.ts:66-76) | "+12.5%" / "new" | 30 s | Derived | No trend if either call fails. Current window's tail is systematically incomplete (see TRF-6) |
| Connections KPI | Home KPI 2 (701-710) | Zeek conn record count | `hits.total` of the summary query | `track_total_hits: True` (D/api/traffic.py:248) | count | `formatCompactNumber` ("477K") | 30 s | Observation | as Bandwidth KPI |
| "Top protocol" | Home KPI 2 sub (480-486) | Zeek `proto` | `network.transport` terms size 1 (D/api/traffic.py:284) | as summary | first bucket | upper-case text | 30 s | Observation | "unknown" when no bucket |
| "No traffic data yet" banner | Home (W/routes/+page.svelte:673-676) | summary | — | — | shows only when `connection_count === 0` | notice | 30 s | — | Not shown when ingestion has merely stalled (TRF-2) |
| Bandwidth over time (hero) | Home (738-764) | Zeek conn bytes | `source.bytes`, `destination.bytes`, `@timestamp` | `GET /api/traffic/bandwidth` interval fixed `1h` for every range (W/routes/+page.svelte:179); `date_range` slots epoch/UTC-aligned (D/storage/time_slots.py:47-71), first slot starts before `from`, last ends after `to`; excluded-IP must_not (D/api/traffic.py:668-678) | per slot `orig`,`resp`,`total`, `doc_count` (722-732) | AreaChart; down=`resp_bytes`, up=`orig_bytes` (511-514); axis local time via `toLocale*`; "Bytes per hour"; "busiest at…" | 30 s | Observation (bytes land in the hour the connection **started**) | Failure keeps chart + stale note (756-758). Edge slots partial. No `checked` (D/api/traffic.py:707) |
| Network protocols donut + service bars | Home (766-793) | Zeek `proto`, `service` | `network.transport` terms 50; `network.protocol` terms 50 missing=unknown; exact filters quic/ssl/unlabelled; `zeek.conn.orig_bytes/resp_bytes` | `GET /api/traffic/protocols` (D/api/traffic.py:502-627), excluded-IP must_not, **the only route in the slice wrapped in `checked()`** (582-595) | services merged (123-155) | Donut counts, top 8 bars | 30 s | Observation | Incomplete search = 502 (correct). NET-219 details owned by other reviewers |
| Traffic categories card | Home (795-806) | Zeek conn + Malcolm ASN enrichment | `destination.as.full` composite (paged), sum painless `source.bytes+destination.bytes` | `GET /api/traffic/categories` → `_asn_buckets` (D/services/traffic_classifier.py:913-926) via `all_buckets` **without `what=`** (no partial-shard check); **no excluded-IP filter**; composite skips docs with no ASN | `classify_asn` substring map (traffic_classifier.py:240-247), sum per category | BarList bytes, "Bytes to internet services · local traffic isn't counted" | 30 s | Heuristic (ASN → category) + external enrichment | Failure: stale note. Docs without ASN silently excluded |
| Top devices card | Home (808-820) | `/api/devices` (devices slice) | `source.ip` terms, painless bytes (D/api/devices.py:575-588) | not traced further (devices slice) | — | formatBytes | 30 s | Observation | stale note |
| Capture pipeline | Home (866-870), stages W/routes/home.ts:115-170 | capture health, NIC counters, `/api/system/health` | none in OpenSearch for freshness | system health checks only `client.info()` reachability (D/api/server.py:571-578) | — | 4 stages ok/failing | 30 s | Status | **No check that new records are arriving** (TRF-2) |
| Category KPIs (bytes, devices, connections, % of network) | /traffic/[category] (W/routes/traffic/[category]/+page.svelte) | Zeek conn + ASN | composite `destination.as.full`, then composite `source.ip` with `download_bytes`=`destination.bytes`, `upload_bytes`=`source.bytes` (traffic_classifier.py:975-1066) | window = range ending now; prev window separately computed (309-325); **no excluded-IP filter** | totals over every device; `% of network` = category bytes / **summary** bytes (which does exclude) (472-475) | formatBytes, % | manual / 30 s Auto | Heuristic + observation | Failure flags; composite cap only logged (1100-1104) |
| Category bandwidth chart | /traffic/[category] | as above | `date_range` slots, sums `destination.bytes`/`source.bytes` | interval map 1h→1m … 30d→6h (96-102) | per slot (traffic_classifier.py:1252-1337) | AreaChart Download/Upload | as above | Observation | `[]` when no ASN in category → empty state (correct) |
| Category device table | /traffic/[category] | as above | as above | top 50 by bytes of all devices | percent of category total (D/api/traffic.py:976-985) | table | as above | Observation | — |
| This month (KPI, down/up, cap meter) | /bandwidth (W/routes/bandwidth/+page.svelte:393-412) | Zeek conn | `source.bytes`,`destination.bytes` | `GET /api/bandwidth/monthly`: **UTC** month `YYYY-MM-01T00:00:00Z` … `last-dayT23:59:59Z` (`lte`) (D/services/bandwidth_tracker.py:131-147), excluded-IP must_not | orig+resp (159-171) | GB (1e9), "↓ down · ↑ up", "November 2026 so far" | on load + top-bar refresh | Observation | Error → card error; partial shard → silently low (no `checked`) |
| Projected / Daily rate / Days remaining | /bandwidth (413-423) | monthly total | as above | days elapsed from UTC month start (bandwidth_tracker.py:366-376) | linear extrapolation (378-383) | GB, "GB a day", days | as above | Estimate | as above |
| Daily usage chart | /bandwidth (434-461) | Zeek conn | as above | `GET /api/bandwidth/daily`, `time_slots(...,'1d')` UTC days (bandwidth_tracker.py:211-216), from UTC month start to now (W/lib/api/bandwidth.ts `utcMonthWindow`) | per day orig/resp | dates formatted with `timeZone:'UTC'` (106-118), sub says "UTC days" | as above | Observation | stale note |
| Top consumers / Per-device breakdown | /bandwidth (463-495) | Zeek conn | terms `source.ip` size ≤200 ordered by painless total; filter **`lan_filter` (IPv4 CIDR terms on source.ip only)** (bandwidth_tracker.py:278-300, D/services/excluded_ips.py:299-315) | window = UTC month to now | per device orig/resp; `percent_of_total` over LAN-sourced (IPv4) docs (316-340) | Upload=`orig_bytes`, Download=`resp_bytes` (235-236); "top 200 devices" when capped (484) | as above | Observation (device = LAN source IPv4 only) | Bridge mode / IPv6: empty or missing rows with "No devices yet" (TRF-7, TRF-8) |
| Busiest-hours heatmap | /bandwidth (497-529) | Zeek conn | painless terms on `@timestamp` day-of-week (7) and hour (24) in viewer tz (bandwidth_tracker.py:458-488) | last 7 days, browser IANA tz passed (W/lib/api/bandwidth.ts getHeatmap) | sum bytes per cell | colour intensity, tooltip bytes | as above | Observation | Error → card error. Partial shard → silently low (this exact failure happened per the project's #97 note; guard still absent) |
| Sessions / Data / Alert events | /connections Summary (W/routes/connections/+page.svelte:342-373) | Zeek conn; Suricata alerts | conn: `source.bytes` (`bytes_in`), `destination.bytes` (`bytes_out`), hits.total; alerts: `event.provider:suricata`,`event.dataset:alert`, must_not `rule.name` prefix + `suricata.alert.metadata.signature_severity` | `GET /api/traffic/connections/stats` (D/api/traffic.py:1120-1324), **no excluded-IP filter** (1131-1141) | sums; `Data` = in+out | "X sent by source, Y sent by destination" (371) | Manual; Auto 15 s off by default | Observation | stale note; no `checked` |
| Active addresses (LAN) | /connections Summary, /live stats | Zeek conn | cardinality `source.ip` under `lan_filter`, last 5 min (live_connections.py:705-708) | `now-5m`..`now` | HLL cardinality | integer | per page poll | Observation (approx.) | IPv4 only |
| Session volume timeline | /connections (984-997) | Zeek conn count | `date_range` slots + terms `network.transport` size 10 | interval 1h→5m, 6h→15m, 24h→1h, 7d→6h, 30d→1d (98-100); no excluded filter (D/api/traffic.py:1636-1645) | counts | local-time labels | as page | Observation | error/empty states |
| Protocols bars | /connections (999-1009) | Zeek conn | `network.transport` terms size 20 | stats query | counts | BarList | as page | Observation | — |
| Network flow (Sankey) | /connections (1022-1043) | Zeek conn + ASN | terms `source.ip` size 10 ordered by painless bytes → `network.transport`; second search: terms `destination.as.full` (missing "Unknown") size 10 | no excluded or LAN filter (D/api/traffic.py:1401-1410, 1343-1386) | links aggregated (1569-1577); web adds "Other destinations" (W/lib/components/ui/charts/flow.ts) | bytes | as page | Observation | stale note |
| Top sources / Top destinations | /connections (1045-1068) | Zeek conn + ASN/GeoIP | terms `source.ip`/`destination.ip` size 10 ordered by `sum network.bytes`; winner details `destination.as.full`, `destination.geo.country_iso_code` | stats query | — | bytes, "conn" | as page | Observation | — |
| Sessions table | /connections (1070-1112) | Zeek conn docs | full `_source`; sort map (D/api/devices.py:1273-1301); state filter `zeek.conn.conn_state`; `q` → `query_string` over all fields; `ip` → either side | `GET /api/traffic/connections` (D/api/traffic.py:746-876), `track_total_hits`, pages capped at 10,000 results (866-869) | — | "Sent by source"=`source.bytes` (fallback `client.bytes`), "Sent by destination"=`destination.bytes` (473-474, 822-823) | as page | Observation | Error: empty table + message (632-638) |
| Related (connection drawer) | Connections drawer "Related" tab (W/lib/components/drawer/content/ConnectionDrawerContent.svelte:641-707) | Zeek conn | pair either direction; sums `source.bytes`,`destination.bytes`, min/max `@timestamp`, terms `network.transport` | `GET /api/traffic/connections/related` called **with no from/to** (372) → daemon default last 24 h (D/api/traffic.py:1724) | totals over all matches, 200 rows | "Total sessions", "Total bytes", "First seen", "Last seen" — no window stated | on open | Observation | Error state |
| Connections per second | /live "Right now" (W/routes/live/+page.svelte:318-322, 652) | Zeek conn | hits.total `@timestamp` gte `now-5m` (live_connections.py:520-524) | 5 min, excluded IPs (unvalidated list, 554-555) | total/300 (1023) | "x.y" | 3 s poll | Estimate (lagging) | error card; partial shard silent |
| Bandwidth (live) | /live "Right now" (322) | NIC sysfs counters `rx_bytes+tx_bytes` on capture iface (D/api/live.py:43-44; mirror D/services/mirror_manager.py:336-348; bridge reads br0 D/services/bridge_capture_adapter.py:175-198) | none, or fallback: sum `source.bytes`+`destination.bytes` over 5 min /300 (live_connections.py:696-699, 1025-1027) | line rate since the previous unfiltered request (shared sampler) | bytes/s | `formatBytes(..)/s` (359-361), e.g. "4.2 MB/s" | 3 s | Observation (L2, whole link) or Estimate (fallback) — not distinguished | Sampler failure silently switches to the ~2x low conn estimate (TRF-9) |
| Top country | /live | Malcolm GeoIP | terms `destination.geo.country_name` size 1 | 5 min | — | text | 3 s | External enrichment | "—" |
| Globe / Top destinations | /live (LiveGlobeCard) | GeoIP | terms `destination.geo.country_iso_code` size **30**, city size 20, `top_hits` location (live_connections.py:625-693) | 5 min | per-country count/bytes | "N countries" (LiveGlobeCard.svelte:292) | 3 s | External enrichment | "N" is capped at 30 |
| Top talkers | /live (696-710) | Zeek conn | terms `source.ip` size 5 under `lan_filter`, painless bytes (602-622) | 5 min | — | bytes · conn, sparkline of successive 5-min sums | 3 s | Observation | Bridge mode / IPv6: empty, "No devices talking yet" |
| Protocols donut | /live | Zeek conn | terms `network.transport` size 10 + `missing` | 5 min | tcp/udp/icmp/other/unknown (856-867) | Donut | 3 s | Observation | — |
| Live connections feed | /live (735-778) | Zeek conn docs | newest 200 by `@timestamp` in `now-5m` (live_connections.py:561-566); direction from LAN rule (105-127); `has_alert` from top 500 alert pairs (731-761) | 5 min | `_format_connection` (338-458) | table, "Dir", bytes, duration | 3 s | Observation | Long-lived/open connections never appear (TRF-1); empty state "No connections right now… within a few seconds" (771) |
| Live connection drawer | /live drawer | Zeek conn, Suricata | pair, `now-24h`, hourly slots | 24 h | — | "Last 24 hours" labelled | on open | Observation | error state |
| Device live bandwidth | Device pages (W/lib/components/LiveBandwidthCard.svelte) | kernel tc flower counters on capture iface ingress (D/services/live_bandwidth_tc.py:111-135) | none | MAC: dst_mac=down, src_mac=up; IP: IPv4 dst/src (+802.1Q). 2 s ticks, 5 min history | (Δbytes×8)/interval (D/services/live_bandwidth.py `_rate`) | `formatBitRate` decimal bit/s | 2 s poll, stale after 5 s | Observation (mirror mode only) | Off/unsupported/busy states explicit; IPv4-only disclosed |

---

## Part 2: Findings

### TRF-1 (P1): Live page never shows long-lived or still-open connections
- Evidence: every Live figure except the line rate is built from Zeek conn docs with `@timestamp` in `now-5m..now` (D/services/live_connections.py:275, 524, 725). A conn doc's `@timestamp` is its start and it is written when the connection ends (the code says so itself: D/api/live.py:33-35). Labels promise the present: card "Right now" (W/routes/live/+page.svelte:652), header comment "what is talking to the world right now", empty state "New connections appear here within a few seconds" (771).
- Failure scenario: a TV streams for 45 minutes over one TCP/QUIC connection. While it runs, Zeek has written nothing. When it ends, its doc is stamped 45 minutes ago, outside `now-5m`. The TV never appears in Top talkers, the feed, the globe, the protocol split or Connections per second. Only the NIC "Bandwidth" stat rises, so the page shows high throughput with no device responsible.
- Affected UI: /live (all cards except Bandwidth); /connections "Active addresses (LAN)".

### TRF-2 (P1): No freshness signal; stalled ingestion looks like a quiet network with a green pipeline
- Evidence: Home's pipeline stages are interface capture health, NIC packet counters, system health and OpenSearch reachability (W/routes/home.ts:115-170). System health only calls `client.info()` (D/api/server.py:571-578). Nothing in the slice reads the newest conn `@timestamp` or the Logstash event rate. Home's "No traffic data yet" notice needs `connection_count === 0` over the whole window (W/routes/+page.svelte:673). Live says "No connections right now" (W/routes/live/+page.svelte:771).
- Failure scenario: after a container recreate, Logstash/Filebeat get 403 from OpenSearch (the failure CLAUDE.md describes as "no data ingestion"). The daemon's admin client still reads, so Home shows Capture ok, Packets ok (packets do reach the NIC), System ok and OpenSearch Connected. The KPIs drift down, the hourly chart falls to 0 and Live is empty. The user concludes the network is idle. The same happens if Zeek crashes.
- Affected UI: Home KPIs, hero chart, pipeline card; /live; /bandwidth; /connections.

### TRF-3 (P1): Partial or failed-shard searches are shown as complete totals
- Evidence: only `/api/traffic/protocols` passes its reply through `checked()` (D/api/traffic.py:582-595). These do not: summary (289), top-talkers (381), bandwidth series (707), connections (843), connection stats (1243, 1281), sankey (1480, 1535), timeline (1665), related (1787); BandwidthTracker monthly/daily/devices/heatmap (D/services/bandwidth_tracker.py:159, 227, 312, 497); categories via `all_buckets` without `what=` (D/services/traffic_classifier.py:915-920) and category bandwidth (1318); Live dashboard (D/services/live_connections.py:781-782). OpenSearch answers HTTP 200 with `_shards.failed > 0` and aggregations over the surviving shards only.
- Failure scenario: one daily `arkime_sessions3-*` shard is unassigned, being deleted by retention, or fails a script. Home Bandwidth, Connections and the hourly chart, plus /bandwidth "This month", "Projected" and the heatmap, come back lower with no error. The project's own note (#97, heatmap) describes exactly this: one shard failed and the page showed zeros. That case was fixed by fixing the script; the guard was not added to these routes.
- Affected UI: almost every figure in the slice.

### TRF-4 (P2): Upload/download is originator/responder, not LAN side
- Evidence: down = `resp_bytes` (`destination.bytes`), up = `orig_bytes` (`source.bytes`): Home KPI (W/routes/+page.svelte:477), hero chart (512-513, 517); /bandwidth KPI (404), daily chart (161-162, 170), device table (235-236); category chart and devices (D/services/traffic_classifier.py:1083-1084, 1300-1301). No LAN-side test anywhere in these paths. The device page already flips direction when the device is the responder (D/api/devices.py:1304-1316), so the codebase knows about the issue.
- Failure scenarios: (a) inbound connections, such as a port-forwarded Plex or NAS, a home VPN server, P2P peers that connect in, or game hosting. The data the LAN sends is reported as "Download". (b) Per-device bandwidth filters on LAN `source.ip` only (D/services/bandwidth_tracker.py:283, 296), so a server's inbound-initiated traffic is not attributed to it at all. (c) LAN-to-LAN flows (mirror mode) appear as internet down/up. IPv6 follows the same originator rule, so it inherits all of the above.
- Affected UI: Home Bandwidth KPI and chart; /bandwidth; /traffic/[category].

### TRF-5 (P2): "This month", "Projected" and the cap are "everything Zeek saw", not internet/ISP usage
- Evidence: no LAN-to-LAN or multicast exclusion in summary or monthly queries (D/api/traffic.py:258-272, D/services/bandwidth_tracker.py:136-147). Cap usage = that total / cap (D/api/bandwidth.py:236-243; bandwidth_tracker.py:400-410). The /bandwidth labels read as ISP usage: "This month", "of your … cap", "Over your cap" (W/routes/bandwidth/+page.svelte:399-420).
- Failure scenario: in mirror mode on a switch uplink, a nightly 200 GB backup from a Wi-Fi laptop to a wired NAS crosses the mirrored link. "This month" rises by 200 GB and "Projected" can show "Over your cap". Wi-Fi clients on the router itself never cross the uplink, so their internet traffic is missing. No caveat about what the capture point can see. (Setting a cap has no UI yet, which lowers severity today.)
- Affected UI: /bandwidth KPIs; Home Bandwidth KPI.

### TRF-6 (P2): Window totals and hourly buckets count each connection once, at its start; open connections are absent
- Evidence: all windows and buckets are `@timestamp` ranges (D/api/traffic.py:210-220, D/storage/time_slots.py:47-71, D/services/bandwidth_tracker.py:140, 193). Home: "Bytes per hour" (W/routes/+page.svelte:738) and trends vs the previous window (450-460).
- Failure scenarios: a 3-hour download from 14:10 shows nothing until 17:10, then appears as one spike in the 14:00 bucket ("busiest at 14:00"). The Home 1h KPI at 15:00 includes none of it. A connection that started 25 h ago and ended 1 h ago is in no "last 24 hours" figure. Because the latest part of any window is still filling in, the Bandwidth and Connections deltas are biased downward, most for 1h and 6h ("−8% vs previous hour" on a steady network). Inferred from code; size not measured.
- Suspected extra: Malcolm may also index Zeek long-connection interim records under another `event.dataset` (for example `conn_long`). If so, the exact `term event.dataset: conn` excludes them (no double count, but also no interim data). The project's note on "_version 2 rewritten long connections" suggests docs are rewritten in place. Confirm with a terms aggregation on `event.dataset` and on `_version > 1` over a day.
- Affected UI: Home KPIs, deltas and hero chart; /bandwidth daily chart, heatmap and month boundary; /connections timeline.

### TRF-7 (P2): IPv4-only LAN rule drops or mislabels IPv6 device traffic
- Evidence: `build_lan_filter` builds IPv4 CIDR terms on `source.ip` (D/services/excluded_ips.py:299-315). `_in_lan` returns False for IPv6 (D/services/live_connections.py:79-82), so `connection_direction` yields "unknown" for every global IPv6 flow (105-127). Per-device bandwidth and its `percent_of_total` use that filter (D/services/bandwidth_tracker.py:283, 316-340). So do Live Top talkers and Active addresses (live_connections.py:602-622, 705-708).
- Failure scenario: a dual-stack home streams YouTube/Netflix over IPv6. /bandwidth shows the TV at 5 GB when it moved 60 GB. "% of total" is a share of IPv4 LAN traffic only, though it reads as a share of all traffic. Live lists IPv6 flows with Dir "Unknown". Home totals do include IPv6, so the pages disagree.
- Affected UI: /bandwidth Top consumers and Per-device; /live Top talkers, Active addresses, Dir column; /connections Active addresses.

### TRF-8 (P2, suspected): In bridge mode (the PRD's main topology), LAN-filtered views are empty with "no devices yet" wording
- Evidence: in bridge mode NetTap sits outside the router's NAT, so IPv4 sources are the router's public address. LAN detection finds no RFC1918 sources and falls back to all of RFC1918 (D/services/excluded_ips.py:415-442), which then matches nothing. Empty states say "No devices yet. Devices appear here once they use data this month." (W/routes/bandwidth/+page.svelte:474, 493) and "No devices talking yet" (W/routes/live/+page.svelte:705). Every Live direction is "unknown" (public to public). Only the device Live bandwidth card explains the bridge-mode limit (D/services/live_bandwidth.py UNSUPPORTED).
- Confirm on a bridge deployment: `/api/bandwidth/devices` returns `[]` while `/api/bandwidth/monthly` is non-zero.
- Affected UI: /bandwidth per-device, /live talkers and direction.

### TRF-9 (P2): Live "Connections per second" lags, and "Bandwidth" silently switches source
- Evidence: conns/s = docs in `now-5m` / 300 (D/services/live_connections.py:834, 1023). Docs for connections still open, or not yet rotated and ingested, are missing, so the figure is low. "Bandwidth" is the NIC line rate when `ThroughputSampler.rate` succeeds, otherwise the 5-minute conn-record estimate (D/api/live.py:208-216; live_connections.py:1025-1027). By the code's own comment the estimate is about half the real rate (148 vs 301 KB/s, live.py:33-35). The UI shows both under one label with sub "last 5 minutes" (W/routes/live/+page.svelte:322, 652), though the line rate covers about 3 s.
- Failure scenario: the capture manager is missing (capture not set up), errors, or counters reset. Live then halves its Bandwidth figure without notice.
- Affected UI: /live "Right now".

### TRF-10 (P2): Traffic categories are an ASN guess presented as fact
- Evidence: `"Google": "streaming"`, `"Microsoft": "work"`, `"Apple": "updates"` (D/services/traffic_classifier.py:220-222), `"Cloudflare": "security"` (185). The Home card says "Bytes to internet services" (W/routes/+page.svelte:795) and the category page names the category with no caveat. The composite on `destination.as.full` skips docs without an ASN (traffic_classifier.py:915-919), so unknown-ASN internet traffic is in no category, not even Other.
- Failure scenario: Gmail, Drive and 8.8.8.8 DNS count as "Streaming". Any Cloudflare-fronted website counts as "Security & VPN", so a user believes a VPN is in use.
- Affected UI: Home Traffic categories; /traffic/[category].

### TRF-11 (P2): Excluded IPs (NetTap's own traffic) are applied inconsistently across pages
- Evidence: excluded on Home summary, bandwidth series and protocols (D/api/traffic.py:271, 531, 675) and /bandwidth. Not excluded in: connection stats (1131-1141), sankey (1401-1410), timeline (1636-1645), connections table (770-812), categories (D/services/traffic_classifier.py:901-911). Live uses the raw, unvalidated list (D/services/live_connections.py:554-555) while the summary uses `valid_excluded_ips` (D/services/excluded_ips.py:597-610). Exclusion is source-side only (637), so connections to NetTap still count everywhere.
- Failure scenario: per the code's own G11 numbers (D/api/traffic.py:509-510), Home "Connections 24h" reads 477K while /connections "Sessions" for 24h reads about 516K. The category page's "% of network" divides unexcluded category bytes by excluded total bytes (W/routes/traffic/[category]/+page.svelte:472-475). A legacy CIDR or junk entry changes Live alone; a junk entry can make every Live poll fail with 502.
- Affected UI: /connections, Home categories card, /traffic/[category], /live.

### TRF-12 (P2): The Connections drawer's "Related" totals are fixed to the last 24 h and say nothing about it
- Evidence: `getRelatedConnections(srcIp, dstIp)` sends no window (W/lib/components/drawer/content/ConnectionDrawerContent.svelte:372). The daemon defaults to the last 24 h (D/api/traffic.py:1724, 160-191). Labels: "Total sessions", "Total bytes", "First seen", "Last seen" (652-671).
- Failure scenario: open a 3-day-old connection from /connections (7d). Related shows 0 sessions, or only today's, and a "First seen" that is just the 24 h cutoff.
- Affected UI: Connections drawer.

### TRF-13 (P2, suspected): Connections protocol pills are free-text searches; "TLS" probably misses TLS
- Evidence: pill values go into `q` as bare tokens (`tcp`/`udp`/`icmp`/`tls`) (W/routes/connections/+page.svelte:510; flow protocol 521). The daemon runs them as `query_string` over every field (D/api/traffic.py:796-805). Zeek labels TLS as service `ssl`, and the daemon itself filters `network.protocol: ssl` (D/api/traffic.py:108-117).
- Confirm: compare the count of conn docs for `q=tls` with `network.protocol:ssl` over 24 h.
- Affected UI: /connections Sessions table and its "N matching" total.

### TRF-14 (P3): Partial edge buckets and coarse Home intervals
- Evidence: slots start at the slot holding `from` and end at the slot holding `to` (D/storage/time_slots.py:52-60), while the query only covers `from..to`. Home always uses `1h` (W/routes/+page.svelte:179), so the 1h range is 2 partial points and every range ends in a partial "current hour" dip. Slots are UTC-epoch aligned, so in +5:30 or +5:45 zones an "hour" bucket is not a local clock hour.
- Affected UI: Home hero chart; /connections timeline; category chart.

### TRF-15 (P3): Capped lists shown as counts
- Evidence: Live "N countries" counts at most 30 (D/services/live_connections.py:664; W/lib/components/live/LiveGlobeCard.svelte:292). `has_alert` pairs are capped at 500 (live_connections.py:760). The feed says "200 connections · newest first" when the window held thousands (W/routes/live/+page.svelte:332-334). Connections table pages stop at 10,000 results while "N matching" shows the full total (D/api/traffic.py:194-196, 866-869). The category composite cap is only logged (D/services/traffic_classifier.py:921-925).
- Affected UI: /live, /connections, categories.

### TRF-16 (P3, suspected): Top-N by summed bytes across many daily shards can miss entries or under-sum them
- Evidence: terms ordered by a sum sub-aggregation, size 10, with no LAN filter (D/api/traffic.py:1146-1151, 1171-1176, 1414-1419). Over 7d/30d each daily index contributes only its local top `shard_size`, so a returned bucket's sum can exclude shards where it ranked lower. This is the issue #96 fixed for categories and devices by switching to composites.
- Confirm: compare against an exact composite run over 30 days.
- Affected UI: /connections Top sources, Top destinations, Network flow.

### TRF-17 (P3): Unit and label mismatches
- Evidence: Home "Bandwidth" KPI shows a volume, not a rate (W/routes/+page.svelte:690). Live Bandwidth is in bytes/s (W/routes/live/+page.svelte:359-361) while device Live bandwidth is in bit/s (W/lib/components/LiveBandwidthCard.svelte:233), and ISPs quote Mbit/s. `source.bytes` is described as "bytes on the wire" (D/services/bandwidth_tracker.py:104) but is IP-layer, while the Live line rate is L2 sysfs bytes (D/api/live.py:44). The API keys `bytes_in`/`bytes_out` mean source/destination, not in/out (D/api/traffic.py:1143-1144; the UI wording at W/routes/connections/+page.svelte:371 is correct).

### TRF-18 (P3): Month boundaries
- Evidence: the month is the UTC calendar month and the KPI does not say so (D/services/bandwidth_tracker.py:133-134; W/routes/bandwidth/+page.svelte:403). The `lte …T23:59:59Z` bound drops records from 23:59:59.001 to .999 on the last day.

### TRF-19 (P3): Page wording claims device scope that the data lacks
- Evidence: "Every session your devices opened" (W/routes/connections/+page.svelte:942) and "Data by device" (1022) cover any `source.ip`, including internet hosts on inbound flows and the router's public address (D/api/traffic.py:1405-1419).

### TRF-20 (P3): `/api/live/rate` reports rows served, not connections
- Evidence: `_record_rate` appends one timestamp per row returned to any client (D/services/live_connections.py:167-191). The figure scales with poll frequency and page size. No page uses it today (W/lib/api/live.ts exposes it), but it is a public daemon endpoint.

### Not established (needs live data, not code)
- The Malcolm mapping of `source.bytes`/`destination.bytes` to `orig_ip_bytes`/`resp_ip_bytes` and of `network.bytes` = their sum. Check one conn doc against its `zeek.conn.*` fields.
- Mirror duplicates. If the switch mirrors more than one port, or both directions of two ports, Zeek counts each packet twice and every byte figure doubles. Nothing in the code detects this. Check for a sudden 2x versus ISP counters, or for `zeek.conn.history` with retransmission flags on clean flows.
- Bridge-mode line rate reads br0 `rx_bytes` (D/services/bridge_capture_adapter.py:185-198). That counts forwarded frames only while br0 is promiscuous; the bridge scripts set promisc on the member NICs. Confirm that br0 `rx_bytes` tracks forwarded traffic on a bridge box.

---

## Part 3: OpenSearch fields queried by this slice

Index: `arkime_sessions3-*` (`OPENSEARCH_NETWORK_INDEX`, D/api/traffic.py:44).

```
@timestamp  D/api/traffic.py:212 (range), D/storage/time_slots.py:63 (date_range), D/api/traffic.py:1775,1779,1780 (sort/min/max), D/services/bandwidth_tracker.py:140,193,282,446,458 (range + painless tz script), D/services/traffic_classifier.py:907, D/services/live_connections.py:275,310,524,566,725,1093
event.provider  D/api/traffic.py:50,1047, D/services/bandwidth_tracker.py:91, D/services/traffic_classifier.py:905, D/services/live_connections.py:464,470
event.dataset  D/api/traffic.py:51,1048, D/services/bandwidth_tracker.py:92, D/services/traffic_classifier.py:906, D/services/live_connections.py:465,471
source.bytes  D/api/traffic.py:280,365,699,1143,1336,1776, D/services/bandwidth_tracker.py:36,106, D/services/traffic_classifier.py:890,1084,1301, D/services/live_connections.py:482,696
destination.bytes  D/api/traffic.py:281,365,700,1144,1336,1777, D/services/bandwidth_tracker.py:37,107, D/services/traffic_classifier.py:891,1083,1300, D/services/live_connections.py:485,698
network.bytes  D/api/traffic.py:1087
source.packets  D/api/traffic.py:282
destination.packets  D/api/traffic.py:283
network.transport  D/api/traffic.py:69,284,537,1145,1380,1431,1658,1782, D/services/live_connections.py:296,541,569,572, D/api/devices.py:1277 (sort)
network.protocol  D/api/traffic.py:72,108,114,540,553, D/api/devices.py:1278 (sort)
zeek.conn.orig_bytes  D/api/traffic.py:70
zeek.conn.resp_bytes  D/api/traffic.py:70
zeek.conn.conn_state  D/api/traffic.py:786, D/api/devices.py:1282 (sort)
length  D/api/devices.py:1279 (sort "duration")
source.ip  D/api/traffic.py:354,1151,1358,1417,1752,1760, D/services/bandwidth_tracker.py:296, D/services/traffic_classifier.py:1097, D/services/live_connections.py:287,532,555,609,707,750, D/services/excluded_ips.py:315,637, D/api/devices.py:1275 (sort)
destination.ip  D/api/traffic.py:422,445,1099,1105,1180,1753,1761, D/services/live_connections.py:288,533,753, D/api/devices.py:1276 (sort)
source.port  D/api/devices.py:1285 (sort tiebreak)
destination.port  D/api/traffic.py:566,571, D/services/live_connections.py:1088, D/api/devices.py:1285 (sort tiebreak), D/services/iot_monitor.py:55 (ENCRYPTED_CONN_FILTER, used by protocols)
destination.as.full  D/api/traffic.py:1107,1365, D/services/traffic_classifier.py:919,946
destination.geo.country_iso_code  D/api/traffic.py:1110,1374, D/services/live_connections.py:137,142,648,663
destination.geo.country_name  D/services/live_connections.py:642,669,711
destination.geo.city_name  D/services/live_connections.py:628,675
destination.geo.location  D/services/live_connections.py:655,690 (_source in top_hits)
source.geo.country_iso_code  D/services/live_connections.py:140
rule.name  D/api/alerts.py:65 (prefix "SURICATA ", alert exclusion used by D/api/traffic.py:1057 and D/services/live_connections.py:481)
suricata.alert.metadata.signature_severity  D/api/alerts.py:73 (same exclusion)
```

Read from `_source` only (not queried, but displayed): `event.start`, `event.end` (D/services/live_connections.py:65), `client.bytes`/`server.bytes` (fallback, W/routes/connections/+page.svelte:473-474), `source.as.*`, `destination.as.number`, `destination.as.organization.name` (D/services/live_connections.py:412-414, 452), `zeek.conn.history`.

Not an OpenSearch field: the device Live bandwidth reads kernel tc counters; the Live line rate reads `/sys/class/net/<iface>/statistics/{rx,tx}_bytes`.
