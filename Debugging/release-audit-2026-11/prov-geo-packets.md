# Provenance audit: geolocation/ASN and packet search/download

Repo: `.claude/worktrees/release-audit` @ 446845ec. Read-only. All paths are relative to the repo root.
I checked production code only. I did not use tests, docs or comments as evidence. "Suspected" means I could not confirm it from code alone, and the item says what would confirm it.

---

## Part 1: Provenance table

### A. Geolocation, ASN, destinations

| Item | UI location | Producer & source fields | Index / fields queried | Query (filters/agg/size/window/tz) | Backend calc | Frontend format & units | Refresh/freshness | Class | Absent/stale/error behaviour |
|---|---|---|---|---|---|---|---|---|---|
| GeoIP result facts (country, city, coordinates, ASN, organisation, private) | `/geoip/[ip]` result card (`web/src/routes/geoip/[ip]/+page.svelte:130-158`) | **Not MaxMind in the daemon.** `maxminddb` is missing from `daemon/requirements.txt`, so `geoip_service.py:293-307` always falls back. Real order: private check (`:478-484`), then the newest OpenSearch session holding this IP with geo (Malcolm Logstash GeoLite2: `*.geo.country_name/country_iso_code/city_name/location`, `*.as.number/organization.name/full`), then the hardcoded `WELL_KNOWN_IPS` table (`:23-223`), then "Unknown"/"XX" (`:527`) | `arkime_sessions3-*`, hardcoded at `geoip_service.py:389` (ignores `OPENSEARCH_NETWORK_INDEX`) | `size 1`, sort `@timestamp desc`, `should` term `source.ip`/`destination.ip`, filter exists `source.geo.country_name` OR `destination.geo.country_name` (`:353-387`). **No time window** (all retained indices) | Picks the side whose ip matches. Lat/lon from `geo.location` or `geo.latitude/longitude`. ASN parsed from `as.full` "AS123 Org" when number/org are missing (`:396-449`). Result cached in `_os_cache` (2048), **and every result, Unknown included, is cached for the process lifetime by `@lru_cache(4096)`** (`:466`) | Coordinates `toFixed(4)` (about 11 m), linked to Google Maps (`:90,143`). Country code hidden when `XX` (`:136`). Private shows "Yes"/"No (public)" (`:156`). No source, DB date or accuracy shown | On route change / page refresh contract. The daemon side never refreshes (lru_cache) until restart | External enrichment (GeoLite2 via Malcolm), or hardcoded table | OpenSearch exception swallowed at debug (`:462-464`) and returns "Unknown/XX, is_private false" as a normal 200. Web shows "Unknown", "No (public)". A daemon non-2xx makes the page show an error card (`lib/api/geoip.ts:59`) |
| GeoIP map | `/geoip/[ip]` "Map" card (`+page.svelte:171-190`) | Same lat/lon | — | — | — | OpenStreetMap iframe with bbox ±0.5°/±0.3° and a marker, plus a Google Maps button | Same | External tile service | **Blocked by CSP**: nginx sends `frame-src 'self'` on every response (`docker/nginx.conf:162`, no `add_header` in `location /` `:181-208`), so the iframe never loads |
| Address page location line | `/address/[ip]` (`address/[ip]/+page.svelte:624-630`) | `lookupGeoIP` (same as above) | same | same | same | `city, country (CC)`. Shows "(XX)" for unknown, because the code `XX` is truthy (`:625`) | Page load | External enrichment | Same as GeoIP. Unknown reads "Unknown (XX)" |
| Live globe markers/arcs | Live › "Where your traffic goes" (`LiveGlobeCard.svelte`, `Globe.svelte`, `globe/engine.js:202-228`) | Zeek conn docs enriched by Malcolm: `destination.geo.*` | `arkime_sessions3-*` (`NETWORK_INDEX`, `live_connections.py:31`) | Filter `event.provider:zeek`, `event.dataset:conn`, `@timestamp now-5m..now` (`:463-465,522-525`). Optional device/proto/country. `must_not source.ip in excluded_ips`. Aggs: `geo_countries` terms `destination.geo.country_iso_code` **size 30** with sub-aggs country_name/top_city(size 1)/bytes/top_hits location (`:661-694`), plus `geo_destinations` terms `destination.geo.city_name` size 20 (`:626-660`) | One arc per country, placed at **its top city's location** (or the newest doc's location), labelled with the top city, but **count/bytes are the whole country's** (`:994-1016`). Countries without a location are dropped (`:1003-1006`). Server time (`now-5m`) | Marker radius ∝ √count. Tooltip "City, Country · N connections · bytes" (`Globe.svelte:150-153`). Sub "last 5 minutes" (`LiveGlobeCard.svelte:128`) | Live page poll | External enrichment (aggregated) | No client: empty response. OpenSearch error: 502, then error card (`LiveGlobeCard.svelte:215-216`). Conn docs carry the conn **start** time and are written at conn end, so long or open flows are missing from "last 5 minutes" |
| Top destinations list + "N countries" | Globe side list (`LiveGlobeCard.svelte:291-322`) | `geo_arcs` merged per country (`destinationsOf` `:22-35`) | as above | as above | — | Count `en-GB`. Cities = [top city]. "N countries" = arcs (≤30) | poll | Derived from enrichment | "No destinations yet" empty state. Inbound rows are never counted (destination-only agg) |
| Top country stat | Live stat strip (`live/+page.svelte:326`) | `destination.geo.country_name` | same | terms size 1 (`live_connections.py:709-714`), by doc count | — | Name or "—" | poll | Enrichment | "—" |
| Feed row country chip / globe feed "Out to City, Country" | Live feed table (`live/+page.svelte:597,607`), expanded globe feed (`LiveGlobeCard.svelte:181-185`) | `_format_connection`: destination geo, or **source geo** when the destination has no country (`live_connections.py:366-375,441-454`). Rows with no lat/lon then enriched through `GeoIPService.lookup` (`api/live.py:317-367`) | hits `_source` (full doc) | size `min(limit,500)`, sort `@timestamp desc` (`:562-566`) | Enrichment fills `country`/`country_name`/`dest_city`/`dest_asn`/`dest_org`/`geo_ip` from GeoIPService, **including "XX"/"Unknown" for multicast** (`api/live.py:353-367`) | ISO code chip | poll | Enrichment | Unknown public or multicast rows get "XX" |
| Live drawer location | Live drawer "Details" (`LiveConnectionDrawerContent.svelte:155-196`) | `fetch_connection_detail`: newest conn doc for the pair in 24 h (`live_connections.py:1060-1110`), parsed for `geo_ip` (`:1283-1330`). Falls back to `GeoIPService.lookup` when lat/lon are missing (`api/live.py:290-307`) | `destination.geo.*`, `destination.as.*`, `source.geo.*`, `source.as.*` | size 1, `@timestamp now-24h`, ip-pair, optional `destination.port` | — | Coordinates `toFixed(4)`, `AS<n>`, org | On open | Enrichment | Empty strings render "--" |
| Globe packets | Globe flights (`engine.js:233-240`) | Each fresh row's `dest_lat/dest_lon` | — | — | — | Animation to exact coordinates | poll | Enrichment | Rows without lat/lon are skipped |
| Home location | Settings › Network location (`settings/LocationCard.svelte`); globe home point | User input, saved to `/opt/nettap/data/home_location.json` (`services/home_location.py:17-89`) | none | — | Validated, rounded to 4 dp (`:25-53`) | Text inputs; globe home marker | Live page reads it on load | User-entered | Load failure: "Couldn't load your network's location" (`LiveGlobeCard.svelte:266-267`). Corrupt file: treated as unset (logged) |
| "Use my WAN location" | Settings › Network location (`LocationCard.svelte:51-63,130-131`) | **External live lookup**: `GET https://ipinfo.io/json` from the daemon (`api/home_location.py:34-58`). Reveals the WAN IP to ipinfo.io. Disclosed in the UI (`LocationCard.svelte:106`) and on click only | none | 5 s timeout, 16 KiB cap, no redirects | `loc` "lat,lon" plus city/region/country label (`:60-79`). Not saved until Save | Fills the fields | On click | External live lookup | 502 with a plain reason (`:132-150`) |
| Connections top destinations ASN/country | Connections stats (`api/traffic.py:1090-1116,1278-1310`) | `destination.as.full`, `destination.geo.country_iso_code` | `arkime_sessions3-*` | `terms destination.ip in winners`, sub-terms size 1 each, same window as stats | Most frequent ASN/country per IP | — | page | Enrichment | "" when missing |
| Sankey destination owners | Connections Sankey (`api/traffic.py:1343-1385,1523-1566`) | `destination.as.full` (`missing:"Unknown"`), `destination.geo.country_iso_code` | same | terms size=limit, ordered by bytes | "AS123 " prefix stripped | — | page | Enrichment | LAN and unenriched destinations are lumped as "Unknown" |
| GeoIP DB date | System/versions (`services/version_manager.py:545-590`) | mtime of a local mmdb, else the newest bundled Logstash `GeoLite2-City.mmdb` | none | docker exec `ls -t` | — | Date | 10 min cache | Metadata | "unknown". **Not shown on any geo surface** |
| Internet health | No UI consumer (only `lib/api/internet-health.ts`) | ping 8.8.8.8/1.1.1.1/208.67.222.222, DNS google.com/cloudflare.com/example.com (`services/internet_health.py:48-49`) | none | On `POST /api/internet/check` only (`api/health_monitor.py:58-67`) | median | — | on demand | External probe | Status "unknown" when ping can't run |

### B. Packet search and download

| Item | UI location | Producer & source fields | Index / fields queried | Query (filters/agg/size/window/tz) | Backend calc | Frontend format & units | Refresh/freshness | Class | Absent/stale/error behaviour |
|---|---|---|---|---|---|---|---|---|---|
| Packets kept | `/packets` StartKpis (`StartKpis.svelte:28-61`) | `capinfos -a -e …` per file in nettap-tshark (`capture_index.py:67-76`). Oldest `first` among **indexed** files (`:463-468`) | — (PCAP on `pcap-data`, netsniff-ng is the only writer: `docker-compose.yml:676-681`) | Background index every 10 s, 8 files per batch (`capture_index.py:397-433`) | now − oldest packet | "N days, back to HH:MM …". Sub "The oldest files go first when space runs low" (`:40`) | page refresh | Direct observation (file metadata) | No indexed file: "—" and "No capture file has been indexed yet". Missing dir: same as empty (scan yields nothing) |
| Capture files / bytes on disk | `/packets` KPI | `scan_captures` (`capture_index.py:153-174`) | — | — | count, Σsize | `formatBytes` decimal | refresh | Observation | — |
| Capture rotation text | `/packets` KPI | capture status `maxFileSizeMB` | — | — | — | `formatBytes(maxFileSizeMB × 1024²)`, decimal units (`StartKpis.svelte:47`). 256 shows as "268.4 MB" | refresh | Config | — |
| Packet search rows | `/packets` results table (`PacketTable.svelte`, `ResultsView.svelte`) | TShark 4.0.17 fields `IDENTITY_FIELDS + DETAIL_FIELDS + _ws.col.*` (`packet_parse.py:14-48`) over a window cut with mergecap\|editcap (`packet_search.py:89-119`) | Files chosen by capinfos first/last overlap (`capture_index.py:125-129,372-395`). No OpenSearch | Window ≤30 min, epoch ns (UTC), `to` clamped to now (`packet_search.py:291-307`). Limit ∈ {100,250,1000}. Reads limit+1 rows to detect "more". 40 s job / 48 s request. ≤64 files / 3 GB (`packet_manifest.py:20-24`) | `termination` = limit / eof / deadline. `complete` = eof and no unreadable file. `provisional` if within 2 min (`:390-454`) | Browser local time (`packets-view.ts:29-47`). Bytes `B` | On search | Direct observation | No file overlaps: "No saved capture holds packets from this window." (`:417-424`). Deadline, limit and unreadable files are each stated (`ResultsView.svelte:76-87`, `ResultQuestion.svelte:115-140`). Errors: typed problem card (busy/changed/memory/refused) |
| Packet detail | `/packets` PacketDrawer | PDML + hex of frame n in the same window, re-verified by time/cap_len/MD5 (`packet_search.py:496-549`) | — | same window | 409 "changed" on mismatch | Tree + hex | on select | Observation | 409/502/504/507 messages |
| Download these packets | `/packets` DownloadForm (form POST, `DownloadForm.svelte`) → `routes/api/packets/download/+server.ts` → `api/packets.py:152-188` | `tshark -Y "frame.number in {…}" -F nsecpcap -w -` over the same window (`packet_search.py:129-134`). Every record verified (`PcapVerifier`) | — | 70 MB cap, single link type required (`:553-569`) | Stream. A mismatch aborts the connection without EOF (`api/packets.py:146-186`) | File `nettap-packets-<UTC>.pcap` | on click | Observation | 409 if files were pruned or changed, 422 for mixed link types |
| Saved captures list + file download | `/packets` SavedCaptures; `GET /api/packets/capture-file?id=` (`api/packets.py:77-106`) | index summary | — | — | realpath + equality check (symlinks refused) | size, modified | refresh | Observation | 404 "no longer exists" |
| PCAP Search file list + KPIs | `/pcap` (`routes/pcap/+page.svelte:367-373,689-706`) | `get_available_pcaps`: **filtered by file mtime** (`pcap_search.py:126-171`) | — | `from`/`to` = browser clock now − range .. now (`pcap/+page.svelte:290-295`) | sort mtime desc | `formatBytes` decimal | refresh | Observation | Missing dir: `[]`, so "No PCAP files in this time range" |
| PCAP Search results ("Matching" per file) | `/pcap` Search results | `tshark -r <file> -Y <filter> -T fields -e frame.number`, whole file (`pcap_search.py:331-415`) | — | Files by mtime. **No packet-time filter.** 300 s per file. One global job (`:238-278`) | count of lines | `matching_packets` per file | poll every SEARCH_POLL_MS | Observation | timed_out/failed counted and shown (`pcap/+page.svelte:798-815`) |
| PCAP preview | `/pcap` Preview | `tshark -c limit` or `… -Y | head` (`pcap_search.py:430-579`) | — | first 100 of the file, 45 s | — | text fields | on click | Observation | timeout notice (`:866`). Refused filter: 400 |
| Download filtered | `/pcap` "Download filtered" → `GET /api/pcap/download?filter=&from=&to=` (`api/pcap.py:176-218`) | mergecap of **all files in the mtime range** into `/tmp/nettap_merged.pcap` (tshark tmpfs 100 MB), then `tshark -Y -w -` whole output into daemon memory, written to the daemon `/tmp` (tmpfs 50 MB) (`pcap_search.py:598-748`) | — | 150 s each step | — | `nettap_filtered.pcap` | on click | Observation | See PKT-1. Never cleaned up |
| Download file | `/pcap` row Download → `GET /api/pcap/download-file?file=` (`api/pcap.py:136-173`) | file | — | — | realpath prefix + sep | — | — | Observation | 400/404 |
| Connections drawer "TShark" tab | Connections drawer (`ConnectionDrawerContent.svelte:238-336`; `routes/connections/+page.svelte:192`) | `/api/tshark/pcaps` (mtime list, `tshark_service.py:717-744`) + `/api/tshark/analyze` (`tshark_service.py:513-598`) | — | Filter = ip pair + dst port (`tshark-filter.ts:38-61`), **no time bound**. Files sorted by \|mtime − conn ts\|, up to 5 tried, first with any match wins (`tshark-analyze.ts:34-39,71-127`). 15 s match scan + 30 s run | first 100 matches | JSON packets | on tab open | Observation, possibly not this connection | "No matching packets found after searching 5 PCAP files". Scan timeout dropped |
| `/tools/tshark` | redirect 308 to `/packets` (`routes/tools/tshark/+page.ts`) | — | — | — | — | — | — | — | — |

---

## Part 2: Findings

### GEO-1: P2: The GeoIP page map never loads: blocked by the site's own CSP
- Evidence: `web/src/routes/geoip/[ip]/+page.svelte:171-181` embeds `https://www.openstreetmap.org/export/embed.html…`. `docker/nginx.conf:162` sets `Content-Security-Policy … frame-src 'self'` at server level. `location /` (`:181-208`) has no `add_header`, so it inherits the header. The web container is only reachable through nginx (`docker-compose.yml` nettap-web `expose: 3000`, ports commented out).
- Scenario: open `/geoip/8.8.8.8`. The "Map · OpenStreetMap · centred on the coordinates" card renders an empty, refused frame. The browser console logs a CSP violation. The card still advertises a map and coordinates.
- Side effect, a good one: no automatic third-party request. If someone "fixes" the CSP, every public-IP lookup would send coordinates to openstreetmap.org without disclosure.
- Affected UI: GeoIP lookup page.

### GEO-2: P2: Precision overstated: city-centroid estimates shown as 11 m coordinates with a map pin
- Evidence: page subtitle "Where an IP address is, and the network that owns it." (`geoip/[ip]/+page.svelte:109`). Coordinates use `toFixed(4)` and link to Google Maps (`:90,142-145,185-186`), with a map marker (`:180`). The Live drawer does the same (`LiveConnectionDrawerContent.svelte:101-103,194`). The backend never reads or returns an accuracy radius (`geoip_service.py:413-420`, `live_connections.py:408-410`). GeoLite2 has no exact location.
- Scenario: a US IP that GeoLite2 knows only at country level gets the country default point (for the US, a field in Kansas). The page shows `37.7510, -97.8220`, with "Open in Google Maps" pointing at a farm, and the globe flies packets there. A user reads a mobile or CDN IP as being "in" a specific town.
- Affected UI: GeoIP page, Address page, Live drawer, globe.

### GEO-3: P2: The source and age of a geo answer are never shown; part of the answer is a hardcoded table
- Evidence: the documented MaxMind path is dead. `maxminddb` is not in `daemon/requirements.txt`, and `Dockerfile.daemon:40-41` installs only that file, so `geoip_service.py:293-305` logs "not installed" and `_db_available` stays false. `api/geoip.py:5-7` still claims MaxMind. Real answers come from (a) the newest Malcolm-enriched session, whatever DB version enriched it then (`:353-389`), (b) `WELL_KNOWN_IPS` (`:23-223`), which states cities for anycast services (8.8.8.8 "Mountain View", 1.1.1.1 "San Francisco", 9.9.9.9 "Berkeley") as fact (`:514-524`), or (c) Unknown. `GeoIPResult.to_dict()` (`:251-263`) has no `source`, `as_of` or DB-date field. The GeoLite DB date exists only in `version_manager.py:545-590`.
- Scenario: a user checks where 1.1.1.1 is before Malcolm has seen it. The page states "San Francisco, United States, AS13335", taken from a hand-typed table. That anycast answer is wrong for nearly everyone, and nothing marks it as a guess.
- Affected UI: GeoIP page, Address page, Live enrichment.

### GEO-4: P2: A failed lookup becomes a permanent "Unknown / public" answer
- Evidence: `@lru_cache(maxsize=4096)` on `GeoIPService.lookup` (`geoip_service.py:466`) caches every return, including `GeoIPResult(ip)` = "Unknown"/"XX"/`is_private=False` (`:527`). That fallback is reached when the OpenSearch query **raised** (swallowed at `logger.debug`, `:462-464`) or found no geo session yet (`:391-392`). There is no TTL, so it lasts until the daemon restarts. The handler returns 200 (`api/geoip.py:41-43`). This brings back the #96 error-as-value pattern that `web/src/lib/api/geoip.ts:44-59` removed on the client.
- Scenario: OpenSearch restarts (or auth breaks, Chain 11) while a user opens `/geoip/203.0.113.7`. The page shows "Country Unknown · Private address No (public)" with no error. After OpenSearch recovers, the same IP still shows Unknown for days. The Address page shows "Unknown (XX)" (`address/[ip]/+page.svelte:625`).
- Affected UI: GeoIP page, Address page, Live drawer fallback (`api/live.py:299`), Live enrichment (`:349`).

### GEO-5: P2: Globe city markers label a city but count the whole country
- Evidence: `live_connections.py:994-1016` builds one arc per `geo_countries` bucket with `"city": c_city` (the top city) and `"count": bucket.doc_count`, `"bytes"` for the **country**. `engine.js:202-216` turns each arc into a city marker. The tooltip renders `"${city}, ${country}" · N connections` (`Globe.svelte:150-153`). The side list shows the country count with that one city underneath (`LiveGlobeCard.svelte:26-31,309`).
- Scenario: 1,200 US connections in 5 minutes, 300 of them to Ashburn. Hovering the marker says "Ashburn, United States · 1,200 connections". All US traffic appears to terminate in Ashburn.
- Affected UI: Live globe and flat map (DotMap hotspots `LiveGlobeCard.svelte:125`).

### GEO-6: P3: The country breakdown is destination-only and capped at 30, while the filter is not destination-only
- Evidence: `geo_countries` terms `destination.geo.country_iso_code` size 30 (`live_connections.py:661-664`). `top_country` uses `destination.geo.country_name` (`:709-714`). Rows placed at their source (inbound) via `_format_connection` (`:366-375`) are never counted. Clicking a country applies `country_filter` = destination OR (source when the destination has none) (`:130-150`), so the feed shows inbound rows the count left out. "N countries" = arcs (≤30, minus those with no location, `:1003-1006`). The 5-minute window is on conn-start `@timestamp` (`:524`), so long or open flows are absent.
- Scenario: inbound scans from 40 countries do not change the Top destinations numbers. Choosing "CN" shows inbound CN rows that its count of 0 did not include.

### GEO-7: P3: Multicast and CGNAT addresses are treated as public "Unknown"
- Evidence: `is_private` (`geoip_service.py:317-328`) checks private, loopback, link-local and reserved, but not multicast or 100.64/10. In Python, `224.0.0.251.is_private` and `100.64.0.1.is_private` are False. `_enrich_connections_geoip` (`api/live.py:340-367`) then sets `country="XX"`, `country_name="Unknown"` and `geo_ip` on mDNS/SSDP rows (direction "local"). The feed shows an "XX" chip (`live/+page.svelte:597,607`). "Filter by country" (`:808`) then sends `XX`, which matches nothing.
- Scenario: every mDNS/SSDP row in the Live feed carries country "XX". A CGNAT ISP hop on the GeoIP page reads "Private address: No (public)".

### GEO-8: P3: Third-party contact audit (mostly clean)
- No automatic external geo lookup was found. The ipinfo.io WAN lookup is on click only and disclosed (`LocationCard.svelte:104-107`, `api/home_location.py:31-58`).
- The Google Maps button and link send coordinates to Google when clicked, without disclosure (`geoip/[ip]/+page.svelte:90,143,186`).
- `InternetHealthMonitor` pings Google, Cloudflare and OpenDNS and resolves google.com/cloudflare.com (`internet_health.py:48-49`), but only on `POST /api/internet/check` (`api/health_monitor.py:58-67`), and no page calls it.
- Live enrichment runs one OpenSearch query per uncached IP inside the poll (`api/live.py:325-351`, up to 500 rows): an N+1 on a cold cache.
- The index is hardcoded at `geoip_service.py:389`.

### PKT-1: P1: PCAP Search "Download filtered" leaks temp files into a 50 MB RAM tmpfs and fails for normal sizes
- Evidence: `download_filtered` creates `NamedTemporaryFile(delete=False)` in the daemon `/tmp` (`pcap_search.py:631-635`) and writes the **whole** filtered output there (`:721`) after holding all of it in memory (`:701-703`). The handler "schedules cleanup" by setting `response._tmp_path` (`api/pcap.py:210-211`), and nothing reads that attribute (grep finds only that line). The daemon `/tmp` is `tmpfs size=50M` on a `read_only` container (`docker-compose.yml:881-883`). Multi-file ranges merge into a fixed `/tmp/nettap_merged.pcap` (`pcap_search.py:638,647-654`) inside nettap-tshark, whose `/tmp` is `tmpfs size=100M` (`docker-compose.yml:1166-1168`). Two concurrent downloads (2 reader slots) share that one path.
- Scenario: "Last 24 h", filter `dns`, with several 256 MB netsniff files. mergecap runs out of space and the user gets "PCAP download failed: mergecap failed: …". A one-file download whose output exceeds ~50 MB fails with ENOSPC (500). A few small successful downloads stay in RAM for good. Once they total 50 MB, every later filtered download fails until the daemon restarts, and other daemon `/tmp` writers fail too, for example the bypass state file (`bridge_health.py:38,698-704`, failures only debug-logged). That knock-on is suspected: confirm by filling `/tmp` and toggling bypass.
- Also: the output covers whole files, not the chosen range (see PKT-3).
- Affected UI: `/pcap` "Download filtered" (`pcap/+page.svelte:511-515,760-761`).

### PKT-2: P2: PCAP Search has one global search job, so concurrent searches cancel each other
- Evidence: `search_progress` keeps a single `_search_job`. A request whose `(filter, from, to)` differs cancels and replaces it (`pcap_search.py:238-278`). The page polls repeatedly with its own key (`pcap/+page.svelte:426-446`).
- Scenario: two tabs, or two people, search different filters. Each poll restarts the other's job at file 0. Neither ever reaches `complete`, and both spinners run forever.

### PKT-3: P2: PCAP Search filters time by file mtime, and counts and downloads cover whole files
- Evidence: the file list uses `st_mtime` against from/to (`pcap_search.py:150-157`). The count is every match in the file, with no time filter (`:343-361`). The filtered download merges whole files (`:623-628`). `to` comes from the browser clock at click time (`pcap/+page.svelte:290-295,420`).
- Scenario: range "last 1 h". The first file started 3 h ago but was last written 50 min ago. Its "Matching" count and the download include 2 h of packets outside the range.
- Suspected: the file being written has `mtime` at or after the request time, so it is dropped as `modified > to_dt` (`:156`) and the newest minutes are silently not searched. It is certain when the browser clock lags the appliance. Confirm by generating a DNS query, then searching `dns` over "1 h" within a minute.

### PKT-4: P2: The Connections drawer "TShark" tab can show packets from a different connection or time
- Evidence: the filter is the IP pair plus destination port, with no time bound (`web/src/lib/utils/tshark-filter.ts:38-61`). Files are ordered by |file mtime − connection time| (`tshark-analyze.ts:34-39`), and the first file with **any** match wins (`:85-97`). mtime is the file's *last* write, so the file that ended minutes before the connection is often tried first. A scan timeout (`tshark_service.py:507-511`, `truncated`) with zero packets is treated as "no match" and skipped (`tshark-analyze.ts:94`).
- Scenario: a DNS connection to 192.168.1.1:53 at 10:00. The file covering 09:30-09:58 is closest by mtime, has many matches, and its first 100 DNS packets (from 09:30) are shown as this connection's packets. If the 10:00 PCAP was pruned, the message "No matching packets found after searching 5 PCAP files" does not say the capture for that time is gone.
- Affected UI: Connections drawer › TShark.

### PKT-5: P3: The TShark analyze path check can be escaped with ".." in absolute paths
- Evidence: for absolute `pcap_path`, `validate_pcap_path` uses lexical `PurePosixPath.relative_to` (`tshark_service.py:189-211`) and checks ".." only for relative paths (`:202`). `/opt/nettap/pcap/../../../x/y.pcap` passes if the same path exists in the daemon, and tshark then reads `/x/y.pcap` inside nettap-tshark.
- Impact is low: login required, read-only container, and the file must end in .pcap/.pcapng/.cap.
- The other file paths are sound: `api/packets.py:85-98`, `api/pcap.py:156-161`, `pcap_search.py:99-106,452`, `packet_manifest.py:83-92,150-179`.
- Command injection: none found. Packet jobs are fixed scripts with positional args (`container_exec.py:37-49,230-246`, `packet_search.py:111-146`). PCAP and TShark calls use exec argv (`pcap_search.py:343-361,503-514`, `tshark_service.py:283-344`).

### PKT-6: P3: Retention and absence messages are incomplete
- Evidence: the KPI says "The oldest files go first when space runs low" (`StartKpis.svelte:40`), but PCAP is also deleted after `cold_days` whatever the free space (`storage/manager.py:776-799`). Pruning globs `*.pcap` only (`manager.py:753`), while index, search and list accept `.pcapng`/`.cap` (`capture_index.py:36`), so those files are never pruned and hold "Packets kept" back. "No saved capture holds packets from this window." (`packet_search.py:423`) reads the same for "pruned", "capture was off" and "before the first capture". When `sel.files` is empty but some files are unreadable, the same sentence appears alongside the "couldn't be read" list. netsniff ring drops are not surfaced anywhere: `loss_window.py` measures NIC counters, not writer drops.
- A missing capture directory reads as empty, not as an error (`pcap_search.py:136-138`, `capture_index.py:153-174`).

### PKT-7: P3: TShark analyze turns large JSON into an error instead of truncating
- Evidence: stdout is cut at 5 MB (`tshark_service.py:372-374`), then `json.loads` fails and raises (`:400-405`), giving 500 "Analysis failed: TShark output could not be parsed". The drawer asks for 100 packets, so this is rare in the UI.

### PKT-8: P3: The rotation size is shown with a different unit than the setting
- `StartKpis.svelte:47` shows `formatBytes(maxFileSizeMB × 1024²)` in decimal units. A Settings value of "256 MB" (`settings/+page.svelte:437-476`) appears as "A new file every 268.4 MB".

---

## Part 3: OpenSearch fields queried (this slice)

Index everywhere: `arkime_sessions3-*` (hardcoded at `daemon/services/geoip_service.py:389`, otherwise `NETWORK_INDEX` at `daemon/services/live_connections.py:31`).

```
@timestamp                              daemon/services/geoip_service.py:355
source.ip                               daemon/services/geoip_service.py:359
destination.ip                          daemon/services/geoip_service.py:360
source.geo.country_name                 daemon/services/geoip_service.py:367
destination.geo.country_name            daemon/services/geoip_service.py:370
source.ip (_source)                     daemon/services/geoip_service.py:380
destination.ip (_source)                daemon/services/geoip_service.py:381
source.geo.* (_source)                  daemon/services/geoip_service.py:382
destination.geo.* (_source)             daemon/services/geoip_service.py:383
source.as.* (_source)                   daemon/services/geoip_service.py:384
destination.as.* (_source)              daemon/services/geoip_service.py:385
*.geo.location / latitude / longitude   daemon/services/geoip_service.py:413-420 (read)
*.as.number / organization(.name) / full daemon/services/geoip_service.py:423-427 (read)
*.geo.country_iso_code / city_name      daemon/services/geoip_service.py:443-444 (read)
destination.geo.country_iso_code        daemon/services/live_connections.py:137
source.geo.country_iso_code             daemon/services/live_connections.py:140
destination.geo.country_iso_code (exists) daemon/services/live_connections.py:142
event.provider                          daemon/services/live_connections.py:464 (zeek), :470 (suricata)
event.dataset                           daemon/services/live_connections.py:465 (conn), :471 (alert)
source.bytes / destination.bytes (painless) daemon/services/live_connections.py:485-488
@timestamp                              daemon/services/live_connections.py:524, 566, 656, 691, 725
source.ip                               daemon/services/live_connections.py:532, 555, 609, 707
destination.ip                          daemon/services/live_connections.py:533
network.transport                       daemon/services/live_connections.py:541, 569, 572
destination.geo.city_name               daemon/services/live_connections.py:628, 675
destination.geo.country_name            daemon/services/live_connections.py:642, 669, 711
destination.geo.country_iso_code        daemon/services/live_connections.py:648, 663
destination.geo.location (top_hits)     daemon/services/live_connections.py:655, 690
source.bytes                            daemon/services/live_connections.py:696
destination.bytes                       daemon/services/live_connections.py:698
source.ip / destination.ip (painless)   daemon/services/live_connections.py:750-754
source.ip / destination.ip (pair)       daemon/services/live_connections.py:1070-1079
destination.port                        daemon/services/live_connections.py:1088
@timestamp                              daemon/services/live_connections.py:1093, 1102, 1117, 1128, 1146
destination.ip, destination.geo.*, destination.as.*, source.ip, source.geo.*, source.as.*, @timestamp (_source)  daemon/services/live_connections.py:1103-1110
rule.name, rule.category, suricata.alert.signature/severity/category, alert.signature/severity/category, suricata.severity (_source) daemon/services/live_connections.py:1129-1140
source.geo.*, destination.geo.*, *.as.*, network.transport, network.protocol, source.port, destination.port, event.start, event.end, length (read from hit _source) daemon/services/live_connections.py:60-67, 366-375, 408-454
destination.ip (terms)                  daemon/api/traffic.py:1099, 1105
destination.as.full                     daemon/api/traffic.py:1107, 1365
destination.geo.country_iso_code        daemon/api/traffic.py:1110, 1374
source.ip (terms)                       daemon/api/traffic.py:1358
```

Packet search, PCAP Search and TShark query no OpenSearch fields. They read PCAP files from the `pcap-data` volume (`/opt/nettap/pcap` in the daemon, `/pcap` in nettap-tshark).
