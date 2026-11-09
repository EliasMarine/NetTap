# NetTap release audit: device identity and per-device attribution

Commit audited: `446845ec` (worktree `.claude/worktrees/release-audit`). Read-only. Production code only; comments/tests/docs were not taken as proof.
Paths below are relative to the repo root. `devices.py` = `daemon/api/devices.py`, `registry` = `daemon/services/device_registry.py`, `fingerprint` = `daemon/services/device_fingerprint.py`, `iot` = `daemon/services/iot_monitor.py`, `scorer` = `daemon/services/iot_trust_scorer.py`, `excl` = `daemon/services/excluded_ips.py`.

Index for every query unless stated: `arkime_sessions3-*` (`OPENSEARCH_NETWORK_INDEX`, devices.py:46). The registry lives in `nettap-devices` (registry:61), keyed by MAC; it has no date in its name, so storage pruning never deletes it (daemon/storage/manager.py:470-530 only prunes dated indices).

How a "device" is keyed (the core answer):
- **Devices table, device detail, Home count:** one row per IPv4 `source.ip` in Zeek `conn` records, filtered to the auto-detected LAN /24s (excl:86-213, :299-315), at least 3 conn records in the window (devices.py:55), minus excluded IPs and addresses ending `.0`/`.255`/starting `224.` (devices.py:200-202). Only connections the address **started** count toward its bytes and connections. MAC, hostname and OS are looked up per IP for the window.
- **Registry ("By type" list, MAC page, "New in 24 h", New banner):** one doc per MAC, built every 300 s from the last hour of the same IP buckets (devices_v2.py:57-58, :223-283). Each IP is filed under its most common `source.mac` that hour. IPs accumulate per MAC until another MAC is seen on the IP.
- **IoT page:** one row per `source.mac` that has a Malcolm `source.oui` matching IoT keywords, over the window, with **no LAN filter** (iot:295-424).
- Timezone: every window is ISO from/to, filtered on `@timestamp` (UTC); charts bucket in UTC fixed intervals (`time_slots`), labels in browser time.

---

## Part 1: Provenance table

| Item | UI location | Producer & source fields | Index / fields queried | Query (filters/agg/size/window/tz) | Backend calc | Frontend format & units | Refresh/freshness | Class | Absent/stale/error behaviour |
|---|---|---|---|---|---|---|---|---|---|
| Total devices | /devices KPI (devices/+page.svelte:693); same rule on Home via /api/devices/count | Zeek conn `source.ip` | `event.provider=zeek`, `event.dataset=conn`, `source.ip` in LAN CIDRs, `@timestamp` | composite paging of every `source.ip` (`all_buckets`, cap 20,000 → 502), `doc_count>=3`, skip .0/.255/224.; excluded IPs `must_not` (devices.py:161-178, :258-295) | `len(buckets)` (devices.py:678) | integer; note = window words | on load, range change, 30 s auto-refresh if on | Observation (count of IPv4 addresses, not devices) | 502 → KPI "—" + "Couldn't load"; incomplete read → 502, never a smaller number (devices.py:252-255). IPv6, low-share subnets and post-NAT LANs silently absent (DEV-1/2/4) |
| Online now | /devices KPI (:701) | conn `@timestamp` (Zeek `ts` = connection **start**) | same as above + `max(@timestamp)` per IP | same read | IPs whose newest conn start ≥ daemon now − 5 min (devices.py:58, :676-683) | integer; "Traffic in the last 5 minutes"; "—" if the custom window ended earlier | same | Heuristic | A device in one long session reads Idle/Offline; conn records only appear when the connection ends (DEV-12) |
| New in 24 h | /devices KPI (:712); Home | registry `first_seen` | `nettap-devices` `first_seen` | `count` range `first_seen >= now−24h` (registry:508-514; devices_v2.py:425-454) | count of MACs first registered since | integer, note "Last 24 hours", sub "First seen by NetTap" | registry pass every 5 min over last 1 h | Heuristic (first registration of a MAC) | 502 → "—". Rotating private MACs re-count; daemon gaps >1 h never backfilled (DEV-13) |
| Top consumer | /devices KPI | list row 0 (bytes desc) | as device list | as device list | first row of bytes-ranked list | `formatBytes` (1000-based) + name | as list | Observation (originated flows, IPv4 only) | "—" when no rows |
| All devices: IP | table col (devices/+page.svelte:580, :614) | `source.ip` bucket key | as Total devices | as above, ranked in Python, top `limit` (≤500) | — | mono text | as list | Observation | — |
| All devices: Name | table col | (1) owner name by MAC (device_custom.json), (2) UniFi alias by MAC, else UniFi client **currently** at this IP, (3) registry discovered name by MAC, else (4) DNS name whose answer was this IP | `dns.ip`, `network.protocol=dns`, `dns.host`, `source.ip`, `source.port`/`destination.port` (5353) (fingerprint:83-123) | `terms dns.host size 10`, window | first name not starting `_` and not a service/reverse name (fingerprint:196-210); registry name overrides (devices.py:851); UniFi (devices.py:879-888); owner name last (devices.py:891) | owner > UniFi (tag) > hostname > "—" (devices/+page.svelte:615-624) | registry names refresh every 5 min; UniFi cache only when the UniFi page is opened (DEV-14) | Heuristic + external enrichment (UniFi) | Lookup failure → no name, logged at debug only (fingerprint:336-338); registry failure → DNS names (devices.py:319-324) |
| All devices: Status | table col | row `last_seen` | — | — | Online if ≥ `online_since`, Idle within 1 h of `as_of`, else Offline (devices/+page.svelte:553-562) | text | as list | Heuristic | "—" when the window ended before the last 5 min |
| All devices: Type | table col (:629-631) | OS hint, hostname, OUI vendor | — | — | `_device_category` substring rules (devices.py:426-509) | icon + label, no confidence | as list | Heuristic | "Unknown" (DEV-7) |
| All devices: OS | table col (:632) | HTTP User-Agent | `http.useragent`, `network.protocol=http`, `source.ip` | `terms http.useragent size 5`, window (fingerprint:178-193) | first regex hit over the 5 commonest UAs (fingerprint:26-41, :231-237) | plain text, "—" if none | as list | Heuristic | none (DEV-8) |
| All devices: Manufacturer | table col (:633) | MAC from DHCP (dead, see DEV-5) else commonest conn `source.mac`; vendor from bundled `oui.txt` (863 lines) else Malcolm `source.oui` learned per 24-bit prefix | `source.mac`, `source.oui`, `dhcp.id` (fingerprint:126-175) | DHCP: newest hit with `dhcp.id`; conn: `terms source.mac size 1` + top_hits | `get_manufacturer` → string, `"Unknown"` on miss (fingerprint:276-307) | plain text | as list | External enrichment (OUI) | "Unknown" (randomized MACs too), not marked as a lookup (DEV-15) |
| All devices: Bandwidth | table col | conn `source.bytes`+`destination.bytes` | `source.bytes`, `destination.bytes` | painless sum per IP, window (devices.py:605-620) | sum over connections the IP **started** | `formatBytes` + bar | as list | Observation (partial: originated, IPv4, by start time) | — (DEV-2/3/12) |
| All devices: Connections | table col | conn doc count | — | per-IP `doc_count` | count of conn records the IP started | compact number | as list | Observation (partial) | — |
| All devices: Alerts | table col | Suricata alerts, source or dest = IP | `event.provider=suricata`, `event.dataset=alert`, `source.ip`, `destination.ip`, noise exclusion | chunks of 10,000 IPs, per-side terms (devices.py:710-793) | sum both sides | compact number | as list | Observation | incomplete/failed → whole list 502 (devices.py:764-774) |
| All devices: Last seen | table col | max conn `@timestamp` | `@timestamp` | per IP max | — | "Nm ago" (browser clock) | as list | Observation (conn start time) | "—" |
| By type list (Device, Address, Maker, Traffic, Connections, Last seen, New chip) | /devices "By type" tab, mirror mode only (devices/+page.svelte:262-268, :741-790) | registry docs; traffic = sum of the IP list's rows for every IP the MAC holds | `nettap-devices` sorted `last_seen desc`, size 200 (registry:484-506) | registry list has no window; traffic from the windowed device list (utils/registry-traffic.ts) | `withTraffic`: sum rows whose IP is in `ips` (registry-traffic.ts); New = `first_seen ≥ now−24h` | name = owner > UniFi alias (never set, DEV-14) > friendly > DHCP > mDNS > hostnames[0] > vendor > MAC; "Maker unknown" | registry every 5 min; list on page load | Heuristic (MAC↔IP mapping) | Registry 502 → error card; traffic "—" when IPs not in list; capped at 200 with no notice (DEV-18) |
| New-device banner | /devices top (NewDeviceBanner.svelte) | registry list (200 newest) | as above | — | `isNewDevice` and newer than localStorage dismissal | up to 3 names | page load | Heuristic | Dismiss also sends a PATCH no route serves (DEV-17) |
| Device hero name/chips | /devices/[ip] (devices/[ip]/+page.svelte:752-764) | owner name, UniFi alias, OS hint, `network.transport` terms | as detail | — | — | h1 = owner > UniFi > IP; OS chip; protocol tags | on load/range/auto | Heuristic | 404 only for non-LAN IPs (devices.py:929-930) |
| Identity facts (IP, MAC, Vendor, Hostname, First seen in range, Last seen) | /devices/[ip] (:788-796) | as list lookups, for this IP over the window | `source.ip`, `source.mac`, `source.oui`, `dns.*`, `@timestamp` | per-IP searches (fingerprint:322-389) | MAC = commonest in window; hostname = registry name else DNS name | mono text; "First seen in range" | per load | Heuristic + OUI enrichment | Lookup errors → "—" silently (DEV-19) |
| Traffic KPI (↓ down / ↑ up) | /devices/[ip] (:814) | conn bytes, `source.ip = IP` only | `source.bytes`, `destination.bytes` | `term source.ip`, conn, window (devices.py:936-1037) | total, orig (= up), resp (= down) | `formatBytes` | per load | Observation (originated only) | page 502 on failure |
| Upload share | (:816) | same | same | same | orig/total → % and label | % + meter | per load | Derived | 0 % when no bytes |
| Connections + unique destinations | (:819) | conn `hits.total`; `destination.ip` terms | `track_total_hits`; `terms destination.ip size 10,000` (exact unless more) | window | count of started connections; unique = bucket count or cardinality | compact number | per load | Observation (originated only) | contradicts "Recent connections" total (DEV-3) |
| Alerts KPI | (:821) | Suricata, either side | as list | `track_total_hits` | count | number | per load | Observation | 502 |
| Bandwidth over time | (:826-837) | conn bytes by `@timestamp` slot | `source.bytes`, `destination.bytes` | `time_slots` 5 m ≤1 d, 1 h ≤7 d, 3 h beyond (devices.py:126-142, :1008-1035) | sum per slot by connection start | area chart, bytes per slot | per load | Observation (start-time binned) | "No traffic in this range" (DEV-12) |
| Traffic categories | (:936-953) | conn bytes per `destination.as.full` mapped by `classify_asn` | `destination.as.full` | `terms size 10,000`, `source.ip`, window (devices.py:1471-1500) | merged per category | bar list | per load | Heuristic (ASN→category) | traffic with no ASN (LAN) omitted, so bars ≠ total |
| Top services | (:955-970) | as above | `destination.as.full` | `terms size 10,000 order bytes` | org name after ASN number, merged, top 10 (devices.py:1063-1083) | bar list | per load | External enrichment (ASN) | empty card |
| Top destinations | (:972-984) | conn `destination.ip` | `terms size 10,000` + bytes sum | window | sorted by bytes in Python, top 20, UI shows 8 | table | per load | Observation (originated) | — |
| DNS activity | (:986-992) | Zeek dns `zeek.dns.query`, `source.ip = IP` | `zeek.dns.query` | `terms size 50 shard_size 10,000`, DNS lookup exclusion (devices.py:1124-1167) | — | top 10 after dropping `_tcp`/`_udp`/`.arpa` | per load | Observation (plaintext DNS only) | DoH/DoT invisible; empty card says "No DNS data." |
| Top ports + Suspicious chip | (:994-1006) | conn `destination.port` | `terms size 20` | window (devices.py:1632-1704) | names from a 26-entry map; suspicious if in {4444,5555,6666,8888,9999,31337,12345,65535} (:1690) | table + warn chip | per load | Heuristic | "Unknown" service |
| Recent connections | (:1009-1040) | conn where source **or** destination = IP | `source.ip`/`destination.ip` should, `network.transport` filter, sort fields | `from`/`size` paging ≤10,000 (devices.py:1385-1455) | `direction` = out if source = IP | DL/UL from the device's side (:641-645) | per load / page | Observation | 502 → error card |
| Rename / picture | DeviceCustomise on IP and MAC pages | local file `device_custom.json` + `device-pictures/` keyed by MAC (services/device_custom.py) | `nettap-devices` get by MAC (must exist for PUT) | — | atomic write, validated (device_custom.py `_commit`) | errors shown in panel; success only on 200 with device (devices-registry.ts `saveDevice`; DeviceCustomise.svelte:112-124) | immediate | Owner data | Save failure correctly shown as failure. IP page saves to the MAC guessed for the window (DEV-5) |
| MAC page identity (MAC, IPs, Manufacturer, Hostnames, First/Last seen, category, New) | /devices/mac/[mac] (:270-299) | registry doc | `nettap-devices` get | — | — | raw category chip; all hostnames ever heard; `formatTime` | registry pass every 5 min | Heuristic | 404 → "Device not found"; other errors → error card |
| MAC page Traffic in/out, Connections, Top destinations, Protocols | (:316-410) | conn where `source.mac` = MAC **or** `source.ip` ∈ registry `ips` (all-time) | `source.mac`, `source.ip`, `event.dataset=conn`, bytes, `network.transport`, `destination.ip` | `track_total_hits`; top dest `size 20 order bytes shard_size 10,000` (registry:516-652) | sums | `formatBytesShort`; note "another device may have used one since" (:335) | per load | Observation (originated; IPv4+IPv6 via MAC) | error card / 404 |
| IoT devices KPI | /iot (iot +page.svelte:708) | MACs with `source.oui` matching keywords | `source.mac`, `source.oui`, `source.ip`, `@timestamp` | composite all MACs, **any dataset, no LAN filter**, excluded IPs (iot:295-424) | keyword substring match (iot:427-452) | integer "Classified devices" | per request (5 calls each rediscover) | Heuristic + OUI enrichment | partial composite only logged (iot:377-378); error → 500 → error card |
| Anomalies KPI | (:715-718) | baselines (never built unless the unused baseline API is called) | — | last 1 h | count for devices with a baseline | "—" + "Not checked: no device has a baseline" | — | Heuristic | honestly labelled |
| Privacy concerns KPI | (:719-720) | per-MAC distinct DNS names in `tracker_domains.txt` (204 lines) | `network.protocol=dns`, `source.mac`, `dns.host` | composite (mac, dns.host) (iot:899-981) | devices with >5 tracker names | integer | per request | Heuristic | device with no DNS seen counts as 0 trackers (DEV-10) |
| Unencrypted KPI | (:721-728) | conn per MAC minus local chatter | `source.mac`, `destination.port`, `network.protocol`, `network.transport`, `destination.ip` | (iot:711-840) | encrypted = port ∈ {443,853,8443,8883} or protocol ∈ {ssl,ssh,quic,…}; devices under 50 % | integer + "N of M measured" | per request | Heuristic | "—" when nothing measured |
| Smart home health ring + pillar rows | (:733-750) | `IoTTrustScorer` over the per-MAC stats | as above + Suricata `suricata.alert.severity` by `source.mac` (iot:842-897), `destination.as.full` cardinality | window | 5 measurable checks (55 pts) scaled to 100; harmonic mean over devices (scorer `score_device`, `compute_fleet_score`) | ring, letter grade, subtitle "Your smart home is healthy." (iot:669-705) | per request | Heuristic score | "Not enough measured" below 50 coverage; but unobserved inputs read as 0 = full marks (DEV-10) |
| Device trust scores table | (:648-651, :783-805) | per-device score | as above | — | as above | grade + score; drawer adds "Measured: from N of 13 checks" (:880) | per request | Heuristic | "— Not enough measured" |
| Findings | (:752-766) | privacy report trackers + protocol audit (category profiles) + hard-coded DNS | `dns.host`, `destination.port`, `destination.ip` | (iot:1520-1640, :2073-2160) | unexpected port per category profile; DNS to non-router resolvers | list; empty state "No findings. All devices look healthy." (:760) | per request | Heuristic | absence of evidence shown as health (DEV-10) |
| Manufacturer profiles | (:806-821) | per OUI vendor | as above | — | harmonic-mean trust, violations by category profile (iot:2774-2900) | bar list | per request | Heuristic | empty card |
| Network isolation (score, pairs, advice) | (:823-845) | IoT `source.mac` → any RFC1918 `destination.ip` | conn, `destination.ip` painless RFC1918 test, ports | composite (mac, dest) (iot:2389-2675) | 100 − 25/15/5 per pair by port risk | "N/100" + grade; "No cross-segment IoT communication detected." | per request | Heuristic | no IoT devices → 100/A (DEV-11) |
| /address/[ip] | redirect target for any non-LAN IP from the device page (devices/[ip]/+page.svelte:472) | conn both directions | `source.*`, `destination.*`, `zeek.ssl.*` | snapshot drilldown (daemon/api/addresses.py:124-160) | to-it / from-it, counted once each | — | per load | Observation | (owned by the drill-down slice; listed for contrast: it counts both directions, the device page does not) |
| API-only (no UI consumer) | `/api/mac/*` (randomized MACs, merges), `/api/lan/*` (ARP, rogue DHCP), `/api/iot/devices`, `/classify`, `/baseline`, `/anomalies`, `/api/devices/baseline*` | — | — | — | — | grep of web/src/**/*.svelte finds no caller | — | — | see DEV-16, DEV-22 |

---

## Part 2: Findings

### DEV-1 · P1 · Post-NAT captures (the "Inline bridge" mode) cannot attribute anything to devices, and no page says so
Evidence:
- The setup wizard's Inline bridge mode puts NetTap "between your modem and router. Sees all WAN traffic." (web/src/routes/setup/+page.svelte:970; go-live/+page.svelte:370, :430). On that link every LAN device is behind the router's NAT.
- LAN detection only counts RFC1918 **sources** talking to non-RFC1918 destinations (excl:86-213, painless at :112-125, `_is_rfc1918` at :186). With a public WAN address none qualify, so it falls back to all of RFC1918 (excl:315) and the device list is empty. With double NAT (ISP gateway in router mode, WAN = 192.168.x.x) the router's WAN address becomes the only "device".
- Empty state: "No devices seen yet. Devices appear once they make a few connections through the monitored link." (devices/+page.svelte:864). By type: "All devices lists every device NetTap sees in this capture mode." (:757).
- IoT discovery has no LAN filter (iot:315-321): on the WAN link, `source.mac` is the router's WAN MAC (or the ISP gateway's). A TP-Link, Google or Amazon router matches the IoT keywords (iot:117-158) and is scored as one IoT "device" using the whole household's traffic.

Failure scenario: a user follows the go-live steps (modem → NetTap → router). Devices stays at "No devices seen yet" forever, or shows "1 devices seen on the network": the router, typed from its OUI, with every byte in the house. The IoT page grades the router as a smart-home device. Nothing explains that per-device visibility needs a capture point on the LAN side.
Affected UI: /devices (all KPIs, both tabs), /devices/[ip], /iot, Home device card, New in 24 h.

### DEV-2 · P1 · Device figures are IPv4-only; IPv6 traffic is silently missing
Evidence: the LAN filter is CIDR terms on `source.ip` with IPv4 /8, /16, /24 only. Its docstring says "matches IPv4 only" (excl:299-315, `_parse_manual_subnets` accepts `IPv4Network` only). `lan_check` says "(IPv4 only, as every device filter applies it)" (daemon/api/drilldown_runner.py:65-75). The device detail matches `term source.ip = <IPv4>` (devices.py:943). The MAC page instead matches `source.mac` (registry:531-537), so it **does** include the device's IPv6 flows.
Failure scenario: on a dual-stack ISP (Comcast, many EU ISPs), YouTube, Netflix, Google and Meta traffic largely runs over IPv6. A phone's Bandwidth, Connections, Top destinations, Upload share and the Top consumer KPI omit all of it. The same device shows a larger total on /devices/mac/[mac] than on /devices/[ip]. An IPv6 LAN address opened from anywhere is redirected to /address as if it were an internet host (devices/[ip]/+page.svelte:472). No UI text says "IPv4 only".
Affected UI: /devices table and KPIs, /devices/[ip] KPIs/charts/tables, By type traffic, Home device count.

### DEV-3 · P1 · Per-device bytes and connections count only connections the device started; the same page lists both directions
Evidence: list aggs and every detail agg filter `source.ip = device` (devices.py:605-620, :943, :1477, :1638). "Connections" = `hits.total` of those records (devices.py:1049-1051). "Recent connections" on the same page queries source **or** destination (devices.py:1393-1399) and is titled "Sessions to or from this device" (devices/[ip]/+page.svelte:1009). The MAC page (registry:531-537) and IoT stats (iot:739) are source-side too. The address page counts both directions (daemon/api/addresses.py:1-10, :124-160).
Failure scenario: a NAS or Plex server streams 200 GB to the TV and to remote viewers. Those connections are opened *to* the server, so its Traffic KPI shows only its own update checks (a few MB), and its "Connections" KPI is far below the "N total" chip on Recent connections a scroll lower. The router (DNS/DHCP server for the LAN), IP cameras pulled by an NVR, game consoles taking inbound P2P, and printers are understated the same way. "↓ down / ↑ up" (:814) implies the device's full traffic.
Affected UI: /devices Bandwidth/Connections/Top consumer, /devices/[ip] Traffic, Upload share, Connections, Bandwidth chart, Top destinations, Top services, Categories, Ports; By type traffic; /devices/mac/[mac].

### DEV-4 · P2 · LAN auto-detection silently drops quiet subnets and some valid hosts
Evidence: LAN = RFC1918 /24s whose share of outbound conn records is ≥1 % (excl:81, :207-213), re-detected hourly (daemon/main.py:301-328). Device list, count and registry all use it (devices.py:161-178; devices_v2.py:247-254). Addresses ending `.0` or `.255` are dropped whatever the prefix (devices.py:200-202).
Failure scenario: a /24 IoT or guest VLAN that makes under 1 % of conn records is not "LAN". Its devices vanish from Devices, Home, the registry and "New in 24 h". Opening one of them redirects to /address as an internet host (devices.py:929-930; devices/[ip]/+page.svelte:472). They can reappear or vanish hourly as shares move. With `LAN_SUBNETS=10.0.0.0/16`, a host at 10.0.1.255 or 10.0.2.0 is never listed. No page shows which subnets count as LAN.
Affected UI: /devices, Home, /devices/[ip] (redirect), New in 24 h.

### DEV-5 · P2 · One IP is shown as one device with one MAC, name and picture, even when the address changed hands in the window
Evidence: the device page keys on IP. MAC = the newest DHCP record carrying `dhcp.id` (fingerprint:126-141). The registry's own comment says Malcolm never fills that for Zeek DHCP (registry:800-802), so in practice it is the *commonest* `source.mac` for the IP over the window (fingerprint:144-175). Hostname, owner name, picture and UniFi alias are all hung on that MAC (devices.py:1226-1267). The rename panel on the IP page saves to `device.mac` (devices/[ip]/+page.svelte:144-160). If no UniFi alias is found for the MAC, the code falls back to whichever UniFi client **currently** has that IP (devices.py:883-886; unifi_integration.py:595-612). Only the MAC page carries a disclaimer (devices/mac/[mac]/+page.svelte:335).
Failure scenario: over "Last 30 days", 192.168.1.50 was a guest's phone for 20 days and the owner's laptop for 10. The IP page shows one device with the phone's MAC, vendor and owner-given name, summing both devices' traffic. Renaming it "Laptop" renames the guest phone's MAC. The UniFi tag can show the name of today's holder on traffic from last week.
Affected UI: /devices table (Name, Manufacturer, Type), /devices/[ip] hero and facts, the rename panel.

### DEV-6 · P2 · Registry device names come from mDNS service labels, other devices' names and SSDP user-agent tokens
Evidence: mDNS enrichment takes the **first** `.local` entry in a DNS record's `dns.host` list and keeps the label before the first dot (registry:994-1008). `_airplay._tcp.local` becomes `_airplay`. A query the device *sent* for `Brother-HL.local` names the sender `Brother-HL`. The router's mDNS reflector gets whichever host it last reflected. The SSDP enricher names a device after the first token of its HTTP UA: `Microsoft-Windows/10.0 UPnP/1.0` → "Microsoft Windows", `Linux/4.9 UPnP` → "Linux" (registry:1086-1093). Each pass replaces `enrichment_sources[source]` with the newest record (registry:204-209), so names flip. The fallback is `hostnames[0]`, the alphabetically first of every name ever heard (registry:728-730). The device list puts the registry name ahead of the DNS name (devices.py:851). Its cleanup only removes names containing `._tcp.` and similar (devices.py:855-860), so `_airplay` survives and feeds classification (devices.py:868).
Failure scenario: a laptop with no DHCP hostname shows as "Brother-HL" after printing (and is then typed Infrastructure by the "brother" hint, devices.py:452), or as "_companion-link". The MAC page lists every junk name under Hostnames (devices/mac/[mac]/+page.svelte:293).
Affected UI: /devices Name and Type, By type list, MAC page, New banner names.

### DEV-7 · P2 · Device type is a substring guess shown as fact, and the registry cannot hold "media"
Evidence: with no OS hint (the usual case, see DEV-8), the IoT hostname hints run **before** the phone and computer hints: "ring", "nest", "hue", "smart", "cam", "switch", "plug", "sensor" (devices.py:435-462, :482-505). "hp-" means printer (:452, :499). The registry's `VALID_CATEGORIES` lacks "media" (registry:66). New docs and `set_category` refuse it (registry:240-242, :277-280), so `_categorize_unknown` can never store it (devices_v2.py:217-218). A stored category is never revised once it is not "unknown" (registry:189-195).
Failure scenario: "Camerons-iPhone" and "Ernests-MacBook-Pro" are typed IoT. An "HP-ENVY" laptop is typed Infrastructure. Sonos, Roku, Apple TV and consoles show as Media in All devices but sit in **Unknown** in By type, whose "Media" group (devices/device-types.ts:10-17) can never fill. Type is shown with an icon and no "guessed" marker (devices/+page.svelte:629-631; MAC page :274).
Affected UI: /devices Type column and filter pills, By type groups, MAC page category chip, Home grid.

### DEV-8 · P2 · OS comes only from plaintext HTTP user agents, and some patterns can never match
Evidence: the only source is `http.useragent` on `network.protocol=http` (fingerprint:178-193). The first match wins over the 5 commonest UAs, and "Linux" is tested before "SmartTV|Tizen|webOS" (fingerprint:26-41, :231-237). Tizen and webOS UAs contain "Linux", so TVs read "Linux" → Computer. Xbox UAs contain "Windows NT 10.0" → "Windows 10/11" → Computer. JA3/JA4 is not used (fingerprint:384-387). The OS is shown as a bare chip or column (devices/[ip]/+page.svelte:760; devices/+page.svelte:632).
Failure scenario: most modern devices make no plaintext HTTP, so OS is blank. When it is set, it may come from an app or library UA rather than the OS, and smart TVs and consoles are labelled Linux/Windows computers, with nothing saying this is a guess.
Affected UI: /devices OS and Type, /devices/[ip] hero chip.

### DEV-9 · P2 · IoT discovery counts phones and laptops as IoT: "ring" matches "Manufacturing"
Evidence: `_is_iot_oui` substring-matches keywords including "ring", "nest", "echo", "arlo", "tp-link", "amazon" (iot:117-158, :427-452). "manufactu**ring**" and "enginee**ring**" contain "ring", so "Murata Manufacturing Co., Ltd." (the Wi-Fi module in many phones and laptops) is IoT. The protocol audit then files it as a doorbell, because "ring" maps to the doorbell profile (iot:2052, :2110). TP-Link routers, APs and USB adapters are IoT. There is no LAN filter (iot:315-321). MACs without a Malcolm OUI, i.e. randomized ones, are never considered (iot:319).
Failure scenario: a Samsung phone with a Murata NIC appears on /iot with a trust grade, and findings like "Uses port 5228 which is not expected for a video doorbell". IoT devices whose NIC vendor is a generic module maker (AzureWave, Realtek, Hon Hai) are missed.
Affected UI: /iot every card (device count, fleet score, table, findings, manufacturer profiles, isolation).

### DEV-10 · P2 · The IoT trust score is a narrow heuristic presented as a health verdict; unobserved inputs score as perfect
Evidence:
- Behaviour checks, telemetry and firmware are always `None` (iot:1092-1108). So only trackers (10), third-party orgs (10), encryption (15), protocol violations (10) and alerts (10) can count, scaled to 100 (scorer `score_device`).
- Missing per-device stats default to **0** rather than unavailable: `third_party_orgs` (iot:1016), `tracker_domain_count` (iot:1019), `alert_count`, `dest_ports`. A device whose DNS NetTap never saw (DoH, DoT, Android Private DNS, or DNS sent past the capture point) gets full tracker and third-party points. The privacy report sets encryption to 1.0 when nothing qualifies (iot:1570).
- `protocol_violations` = every distinct destination port outside the **default** profile [80, 443, 53, 123, 5353, 1900], −3 each (iot:282-289, :486, :1030-1034). That penalises MQTT-TLS 8883 (also counted as "encrypted"), Google 5228, Apple 5223 and Cast 8009. Suspected: also each ephemeral port of a unicast SSDP reply logged as a new connection. Confirm with a Zeek conn record whose orig port is 1900. Meanwhile the Findings protocol audit and Manufacturer profiles use **category** profiles (iot:2110-2130, :2850-2858), so one device can be "compliant" in Findings yet lose all 10 protocol points in its score.
- "Third-party orgs" = approximate cardinality of destination ASNs (iot:786-790), so CDN use (Akamai, Cloudflare, AWS) lowers privacy.
- The UI shows "Your smart home is healthy." (iot:681-690) or "No findings. All devices look healthy." (iot +page.svelte:760). Coverage ("from N of 13 checks") appears only inside the drawer (:880).

Failure scenario: a camera that tunnels its DNS over HTTPS and talks only to 443 earns an A and "healthy". A well-behaved MQTT-over-TLS sensor gets a D for "protocol violations".
Affected UI: /iot hero ring and subtitle, Privacy concerns, device trust table, manufacturer profiles.

### DEV-11 · P2 · Network isolation reports "A" with nothing measured, and "well-isolated" from traffic it cannot see
Evidence: with no IoT devices it returns score 100, grade A (iot:2405-2413), shown as "100/100 A" (iot +page.svelte:827). Without observed pairs it says "Your IoT devices are well-isolated from internal hosts." (iot:2643) and "No cross-segment IoT communication detected." (:833). But a SPAN of the router uplink never carries same-switch LAN traffic. Any RFC1918 destination counts as an internal host, the router and NAS included (iot:2437-2453), and the recommendation calls them "workstations". IoT-to-IoT pairs are excluded only by each device's **newest** IP from any record type (iot:404-407, :2611), which can be an IPv6 link-local or 0.0.0.0 DHCP record, so IoT-to-IoT traffic can be flagged.
Failure scenario: a flat home network where the IoT plug can reach the laptop over the switch shows "A, well isolated". A Sonos reading the NAS over SMB (445) is flagged "critical" for "reaching your workstations".
Affected UI: /iot Network isolation card.

### DEV-12 · P2 · Bytes are filed by connection start time; open connections are missing; "Online"/"Last seen" use start times
Evidence: every window filter and chart slot is on `@timestamp` (devices.py:145-158, :1008-1035). For Zeek conn that is the connection's **start**, and the record only exists once the connection ends. Online = newest start within 5 minutes (devices.py:58, :676-683). The detail page's status and "Last seen" use the same value (devices/[ip]/+page.svelte:232-233).
Failure scenario: a 3-hour VPN session or a 20 GB download shows as one spike at its start, counted wholly in the window where it began, and is absent while still running. A laptop on a 2-hour video call with no other connections reads "Idle"/"Offline" during the call. The chart subtitle "Bytes per interval" implies transfer time.
Affected UI: /devices Online now, Status, Last seen, Bandwidth; /devices/[ip] chart, KPIs, status chip.

### DEV-13 · P2 · "New device" is the first registration of a MAC in a rolling 1-hour pass
Evidence: the registry refreshes every 300 s over only the last hour (devices_v2.py:57-58, :239-241) with no backfill after downtime. `first_seen` = `seen_at` = the **newest** record in that first hour (devices_v2.py:157; registry:247). The count is over `first_seen` (registry:508-514). The DHCP, mDNS and SSDP enrichers register any MAC without the device list's LAN and threshold rules (devices_v2.py:263-267; registry:778-1108), although ARP enrichment was dropped for exactly that reason (devices_v2.py:263-264).
Failure scenario: phones and PCs with rotating private MACs, or Windows "random hardware address, change daily", count as new each rotation and leave orphan registry entries. A device that came and went while the daemon was down for over an hour is never registered or announced. A fresh install reports every device as new. MACs seen only in mDNS or SSDP count as "New in 24 h" but never appear in the All devices table. `first_seen` can be up to an hour late (changelog "device_joined" too).
Affected UI: /devices New in 24 h KPI, New chip, New banner, Home, Changelog.

### DEV-14 · P2 · UniFi names are stale or missing, and appear on some pages only
Evidence: nothing polls UniFi clients in the background. `poll_clients` runs only from the UniFi test and clients endpoints (devices_v2.py:591, :624). `get_device_alias` and `get_client_name_by_ip` read `_cache_clients` whatever its age (unifi_integration.py:567-612). No code registers a "unifi" enrichment, so the registry's top name priority (registry:707-711) is dead.
Failure scenario: after a daemon restart, All devices loses every UniFi name until someone opens the UniFi integration page. After that the names never refresh, and with the IP fallback (DEV-5) an old client's name stays on a reassigned IP. By type, the MAC page, the banner and /iot never show the UniFi name that All devices shows for the same device.
Affected UI: /devices Name (UniFi tag), /devices/[ip] h1, By type, MAC page.

### DEV-15 · P3 · Vendor lookups are not presented as lookups; randomized MACs read "Unknown"
Evidence: `get_manufacturer` returns the string "Unknown" on a miss (fingerprint:276-307), while the registry uses null ("Maker unknown"). Malcolm vendors are learned per 24-bit prefix (fingerprint:309-313; mac_lookup_service.py:46-71 prefix search), which mislabels IEEE MA-M/MA-S sub-blocks that share a 24-bit prefix. The vendor is the NIC maker (Espressif, Murata), not the product. Randomized MACs are flagged only inside the open customise panel (DeviceCustomise.svelte:63-64, :197-199).
Affected UI: /devices Manufacturer and Type, /devices/[ip] Vendor, MAC page.

### DEV-16 · P3 · Randomized-MAC correlation and merge are API-only and have no effect
Evidence: no Svelte page calls `web/src/lib/api/mac-correlation.ts`. `get_active_merges` has no caller (daemon/services/mac_correlator.py:662), so a merge changes nothing. `_save_merge_history` logs a failure and the merge still returns success (mac_correlator.py:157-165, :623-640). Similarity uses `dns.question.name` and `tls.ja3` (mac_correlator.py:59-61). Other code says Malcolm does not provide JA3 (fingerprint:384-387) and uses `zeek.dns.query` for DNS names (devices.py:1140). Suspected consequence: those terms are always empty, so the best possible similarity is 0.25 + 0.15 = 0.40, below the 0.50 threshold (mac_correlator.py:36, :583), and suggestions are always empty. Confirm with an `exists` count on both fields. `is_randomized_mac` also flags VM and Docker MACs (52:54:00, 02:42:…) (mac_correlator.py:113-123).

### DEV-17 · P3 · The "dismiss new devices" acknowledgement goes to a route that doesn't exist
Evidence: `acknowledgeDevice` sends `PATCH /api/devices/registry/{mac}` (web/src/lib/api/devices-registry.ts:216-230). The daemon has no PATCH route (devices_v2.py:785-789), and the SvelteKit routes have none either (`api/devices/[ip]/+server.ts` GET only; `api/[...path]/+server.ts` exports GET/POST/PUT/DELETE). Every call gets a 405, ignored. The dismissal itself works through localStorage.

### DEV-18 · P3 · The registry is never pruned; maintenance and lists see only the newest 1,000/200 entries
Evidence: `get_all_devices(limit=1000)` in `correct_last_seen`, `drop_reassigned_ips`, `merge_long_macs`, `enrich_with_oui`, `enrich_with_ja3` (registry:307, :358, :385, :1120, :1162) and `_categorize_unknown` (devices_v2.py:204). The list endpoint returns no total (devices_v2.py:369-375). By type asks for 200 (devices/+page.svelte:266) and shows no "showing 200 of N". IPs added by the DHCP enricher after `drop_reassigned_ips` stay on two MACs until the next pass, and `withTraffic` then counts the IP on both cards (web/src/lib/utils/registry-traffic.ts).

### DEV-19 · P3 · Silent degradations in the lookups
Evidence: `lookup_many` treats a per-search `_msearch` error as "no data" (fingerprint:431-440). The `get_*` fallbacks catch every exception at debug level (fingerprint:336-338, :354-366, :381-382). A registry failure falls back to DNS names with only a warning (devices.py:319-324). An incomplete IoT discovery only logs (iot:377-378). A failed registry refresh leaves New in 24 h and By type stale with no UI sign (daemon/main.py:357-360).
Failure scenario: an OpenSearch hiccup mid-request shows devices with no MAC, vendor, hostname or OS, instead of an error.

### DEV-20 · P3 · "Suspicious" port chip is a fixed list with no explanation
Evidence: ports {4444, 5555, 6666, 8888, 9999, 31337, 12345, 65535} are flagged and 8888/9999 are named "Unknown" (devices.py:1661-1690; devices/[ip]/+page.svelte serviceCell). 5555 is common for Android ADB and some media apps, and 8888 for dev servers and proxies.

### DEV-21 · P3 (suspected) · On aiohttp 3.9.x the device route shadows the registry and baseline routes
Evidence: `requirements.txt` allows `aiohttp>=3.9.0`. `/api/devices/{ip}` is registered first (daemon/api/server.py:1116). `/api/devices/baseline` (server.py:1145) and `/api/devices/registry` (server.py:1307) come later. aiohttp 3.9 resolves routes linearly, so the dynamic route would take "registry" and "baseline" as IPs and answer 404 "not on your network" (devices.py:929-930). 3.10+ checks plain paths first. Confirm with `pip show aiohttp` in the daemon image, then raise the lower bound.

### DEV-22 · P3 · LAN security checks (ARP spoofing, rogue DHCP) have no UI, and rogue DHCP over-alerts
Evidence: no Svelte consumer of `web/src/lib/api/lan-security.ts`. Any device seen sending from UDP 67 counts as a DHCP server and a second one is "critical" (daemon/services/lan_anomaly_detector.py:185-357), so DHCP relays and mesh nodes that relay would alarm. The ARP checks honestly report "not checked" when no ARP is logged (daemon/api/lan_security.py:23-33).

### DEV-23 · P3 (suspected) · Inter-VLAN flows may be double-counted on a mirrored trunk
Evidence: on the G11-style uplink mirror, a routed LAN-to-LAN flow crosses the mirrored port twice with the same 5-tuple. Whether Zeek's per-connection bytes double depends on whether Malcolm maps `source.bytes` to `orig_bytes` (sequence-based, not doubled) or `orig_ip_bytes` (packet-based, doubled). The mapping is not in this repo. Confirm by copying a known-size file between VLANs and comparing the source device's Bandwidth.

No P0 found in this slice: no data-loss path in names and pictures (atomic writes, validated store, failures surfaced: services/device_custom.py `_commit`; daemon/api/device_custom.py `_run`), and no hardcoded, mock or random data in production code paths.

---

## Part 3: Fields queried (one per line, file:line)

OpenSearch `arkime_sessions3-*`:
- `@timestamp` devices.py:152, :618, :619, :720, :987, :988, :1178, :1274, :1569, :1777; devices_v2.py:115, :122; device_registry.py:322, :547, :793, :823, :903; device_fingerprint.py:69; iot_monitor.py:201, :317, :364, :368; mac_correlator.py:41-42, :78, :305; lan_anomaly_detector.py:43
- `event.provider` devices.py:170, :740, :944, :1131, :1198, :1402, :1478, :1563, :1639; lan_anomaly_detector.py:103, :376, :480; excluded_ips.py:111
- `event.dataset` devices.py:171, :741, :945, :1132, :1199, :1403, :1479, :1564, :1640; excluded_ips.py:112, :487 (CONN_RECORDS, used by device_registry.py:555, iot_monitor.py:738, lan_anomaly_detector.py:298); lan_anomaly_detector.py:104, :377, :481
- `source.ip` devices.py:277, :734, :758, :943, :1130, :1192, :1275, :1308, :1396, :1477, :1557, :1638; excluded_ips.py:315 (LAN filter), :160, :637 (excluded IPs); device_registry.py:316, :536, :819, :918, :971, :1058; device_fingerprint.py:105, :134, :160, :186; iot_monitor.py:103, :365; lan_anomaly_detector.py:65 (`ip_field`)
- `destination.ip` devices.py:735, :759, :960, :996, :1193, :1276, :1397, :1558; excluded_ips.py:119; device_registry.py:585; iot_monitor.py:43, :72, :188, :1343, :1799, :1992, :2337, :2351, :2443, :2589; mac_correlator.py:54, :60, :337
- `source.mac` devices_v2.py:110, :116; device_registry.py:317, :532-533, :805, :818, :910, :916, :965, :1046; device_fingerprint.py:140, :161, :167, :170; iot_monitor.py:318, :355, :739, :753, :861, :878, :922, :933, :1684, :2225, :2283 (`_counts_by_mac`), :2335, :2437; mac_correlator.py:68 (`_BY_MAC`), :312; mac_lookup_service.py:57; lan_anomaly_detector.py:54-55, :313 (`{side}.mac`)
- `destination.mac` lan_anomaly_detector.py:313 (`{side}.mac`)
- `source.oui` devices_v2.py:116; device_fingerprint.py:140, :170; iot_monitor.py:319, :357; mac_lookup_service.py:58, :62
- `source.bytes` devices.py:609, :615, :953, :958, :979, :1001, :1027, :1033, :1281, :1493; device_registry.py:566, :574, :595; iot_monitor.py:755, :1196, :1346, :1802, :1991; mac_correlator.py:47, :62, :357
- `destination.bytes` devices.py:609, :616, :953, :959, :979, :1001, :1027, :1032, :1280, :1493; device_registry.py:567, :575, :596; iot_monitor.py:1804; mac_correlator.py:48, :63, :359
- `source.packets` mac_correlator.py:361
- `destination.packets` mac_correlator.py:363; lan_anomaly_detector.py:292
- `source.port` devices.py:1285; device_fingerprint.py:110; lan_anomaly_detector.py:300 (`{side}.port`)
- `destination.port` devices.py:1285, :1647; device_registry.py:1051; device_fingerprint.py:109; iot_monitor.py:42, :55, :68, :87, :90, :94, :100, :189, :799, :1344, :1801, :2267, :2336; lan_anomaly_detector.py:300
- `network.transport` devices.py:617, :986, :1277, :1404; device_registry.py:576; iot_monitor.py:41, :67, :84; lan_anomaly_detector.py:299
- `network.protocol` devices.py:1278; device_registry.py:804, :963, :1045; device_fingerprint.py:101, :188; iot_monitor.py:56, :190, :783, :921, :1345, :1683, :1899
- `destination.as.full` devices.py:970, :1488; iot_monitor.py:788
- `destination.geo.country_name` iot_monitor.py:192, :1349
- `destination.geo.country_iso_code` iot_monitor.py:1808
- `dns.host` device_registry.py:964, :972; device_fingerprint.py:122; iot_monitor.py:951, :1712, :1915
- `dns.ip` device_fingerprint.py:100; iot_monitor.py:1900, :1911
- `dns.question.name` mac_correlator.py:59, :331
- `zeek.dns.query` devices.py:1140
- `dhcp.id` device_fingerprint.py:135
- `zeek.dhcp.host_name` device_registry.py:820
- `zeek.dhcp.assigned_ip` device_registry.py:821
- `http.useragent` device_registry.py:1050, :1059; device_fingerprint.py:187, :192
- `http.uri` device_registry.py:1049, :1060
- `tls.ja3` mac_correlator.py:61, :343
- `suricata.alert.severity` iot_monitor.py:860
- `zeek.conn.conn_state` devices.py:1282 (sort only)
- `length` devices.py:1279 (sort only)
- Imported exclusions (fields defined outside this slice): `SURICATA_NOISE_EXCLUSION` (daemon/api/alerts.py) used at devices.py:743, :1201, :1566 and iot_monitor.py:866; `DNS_LOOKUP_EXCLUSION` (daemon/services/dns_analytics.py) used at devices.py:1134; `build_excluded_ips_filter` (excluded_ips.py:613) on `source.ip`

OpenSearch `nettap-devices` (registry):
- `_id` (MAC) device_registry.py:259-262, :434, :466, :477
- `mac` device_registry.py:667
- `ips` device_registry.py:668
- `hostnames` device_registry.py:669
- `manufacturer` device_registry.py:670
- `friendly_name` device_registry.py:671
- `last_seen` device_registry.py:494 (sort)
- `first_seen` device_registry.py:512 (new-device count)
