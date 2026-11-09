# NET-237: data-layer honesty (release audit B-e, B-f, B-g, P3)

**Branch:** `fix/net-237-data-honesty` (from `fix/release-audit-2026-11` at e3391970)
**Status:** fixed locally, all suites green; not yet deployed to the G11
**Plan gate:** Codex APPROVED after 3 rounds. **Over-engineering gate:** ponytail-review, one finding fixed.

## B-f — partial OpenSearch replies (TRF-3, ALR-11, DNS-4)

- **Problem.** The audit listed ~40 routes that never check `_shards.failed` or `timed_out`.
- **Root cause.** The routes don't need to: every one searches through `storage._client`, an `ExactTermsOpenSearch`, which has raised `PartialResultsError` on failed shards since 9394dbea (the audit missed it). Three gaps were left in that client: `timed_out: true` (OpenSearch answers from the shards that finished), an msearch with one failed search (`{"error": …}` read as "no hits"), and `count()` (no check).
- **Fix.** `_partial()` in `daemon/storage/exact_terms.py` checks all three; `search`, `msearch` and a new `count` override raise on it. DNS analytics, its `all_buckets` scans included, runs on the same client, so `services/dns_analytics.py` is untouched.
- **Decision.** A partial reply stays an error (502, and the page's error or stale state), not a "may be incomplete" flag. A flag would put a number known to be low on screen.

## B-e — Live "Right now" can't show long connections (TRF-1)

- **Problem.** A 45-minute stream never appeared on the Live page, during or after.
- **Root cause.** Zeek writes a conn record when a connection closes, stamped with its start. The window filtered `@timestamp` (the start) to the last 5 minutes.
- **Fix.** The window and the feed's order use `event.end` (it equals `lastPacket` on every conn record). Rows carry `ended_at`. The feed's column is "Ended", the globe's list shows end times, and the drawer shows Started and Ended. The copy says "Bandwidth is live · the rest counts connections that ended in the last 5 minutes", with a note that an open stream shows up once it ends.
- **Measured on the G11.** The start window held 2,632 connections, the longest 128 s. The end window held 2,716, the longest 1,819 s. Both queries took 3 ms.
- **Decision.** Interim `conn_long.log` records aren't used. Malcolm's defaults write them at 10 min, 30 min, 1 h, 12 h, 24 h and 3 d, with no repeat, so they could only show a long connection just after a checkpoint, and their cumulative bytes would double-count against the final record. To make them useful, set `ZEEK_LONG_CONN_DURATIONS=300` and `ZEEK_LONG_CONN_REPEAT_LAST_DURATION=true` on the Zeek container. That is a follow-up, not done here.

## B-g — GeoIP (GEO-2, GEO-3, GEO-4) and the P3 anycast table

- **GEO-2.** GeoLite2 gives a city or country centre with no accuracy radius.
  - `geoEstimate()` in `web/src/lib/api/geoip.ts` shows a city centre to one decimal, as "city estimate, accuracy unknown".
  - A country-only answer, or an anycast address, gets no coordinates and no map.
  - The map has no marker, and the Maps link searches the place name.
- **GEO-3.** Answers now carry `source` (`traffic`, `maxmind`, `builtin`, `private` or `none`) and `seen_at`.
  - The GeoIP page names the source in plain words. For a stored answer, it says the database version used then isn't recorded.
  - It shows the installed GeoLite2 file date from `/api/system/versions` as what is installed now.
  - No `maxminddb`: Malcolm's stored fields cover country, city, coordinates and ASN.
- **GEO-4.**
  - **Root cause.** `lookup()` was `lru_cache`d, and `_lookup_opensearch` swallowed errors at debug level. A failed query became "Unknown / public" until restart.
  - **Fix.** A failure now raises `GeoLookupFailed` and isn't cached; the routes answer 502. A miss is remembered for 5 minutes.
  - The query also had a bug: the address and its geo could match opposite sides of a session. The two are now tied to the same side.
- **P3 anycast.** Addresses in `ANYCAST_IPS` (public DNS resolvers, CDN anycast) get no city or point from any source, and say "Anycast: location varies". This covers the GeoIP and Address pages, Live rows, the detail, and both Live fallbacks.

## P3 — 1970 documents

- **Finding.** The 17 docs in `arkime_sessions3-700101` have no IP, MAC or bytes.
- **Why nothing is thrown off.**
  - Every session query has a time range or an IP or MAC term.
  - The `min @timestamp` aggregations sit under IP or MAC filters.
  - F2's freshness check uses `event.ingested`.
  - Retention reads the index as dated 1970-01-01 and would prune it first, which is harmless.
- **Change.** None.

## P3 — docs drift

- `CONTRIBUTING.md`: Ubuntu 22.04 or 24.04.
- `README.md` already matches the compose pins (Malcolm 26.10.0) and the code.
- "Alert-triggered PCAP" survives only in untracked files.

## Files

- **Daemon:** `storage/exact_terms.py`, `services/live_connections.py`, `services/geoip_service.py`, `api/geoip.py`, `api/live.py`, plus tests.
- **Web:**
  - `lib/api/{geoip,live}.ts`
  - `routes/geoip/[ip]`, `routes/address/[ip]`, `routes/live`
  - `components/live/LiveGlobeCard.svelte`, `components/drawer/content/LiveConnectionDrawerContent.svelte`
  - visual fixtures `geoip.ts`, `live.ts`
- **Docs:** `CONTRIBUTING.md`

## Tests (each failed on the old code)

- **Daemon** (`test_exact_terms.py`, `test_live_connections.py`, `test_geoip_service.py`, `test_geoip_api.py`):
  - `timed_out`, msearch error and count each raise; DNS paths raise.
  - The window and sort use `event.end`; rows carry `ended_at`.
  - Anycast is stripped on rows, the detail and both fallbacks; a failed fallback leaves the detail as it was.
  - An error isn't cached; a miss expires; the query ties each side to its own geo; source and `seen_at` are set; the API answers 502.
- **Web:**
  - `geoEstimate`.
  - GeoIP page: source and installed database, a failed version read, country-only, anycast, 502, and a slow version scan.
  - Address page anycast; Live copy; end-time order in the feed and the globe list; drawer anycast, precision and times.

## Lessons

- Before fixing "N routes don't check X", look at the shared client the routes call. The guard may already be there, one layer down.
- A cache in front of a lookup that can fail must cache answers, not outcomes.
- Zeek's conn `@timestamp` is the start, and the record exists only after the end. Any "now" view must filter on `event.end`.
