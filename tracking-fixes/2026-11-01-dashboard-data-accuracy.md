# 2026-11-01 — Dashboard data accuracy audit (G11)

**Status:** In progress.
- **Batches 1–4:** deployed and verified on the G11 (`deploy-data-accuracy-batch{1..4}.sh`, every check ✓).
- **Batch 5 (next):** owner decisions 2026-11-02 — cap PCAP by size (#37) and turn Arkime off (#44).
- **Still open:** #20, #21, #26, #27, #35, #38, #39, the Settings and PCAP Search pages, and a CyberChef browser re-test.
**Branch:** `fix/dashboard-data-accuracy`, off `fix/index-template-pattern`.
**Linear:** NET-129.

## Goal (owner, 2026-11-01)
NetTap works flawlessly, with correct and accurate figures. Every page works and reports factual data. The add-on tools (CyberChef, TShark) work. Packet capture works.

**Definition of done:**
- Every route was opened in the browser, its numbers were checked against direct OpenSearch queries, and the console shows no errors.
- Numbers that appear on more than one page agree with each other (devices, bytes, alerts, DNS).
- CyberChef opens and runs a recipe. TShark analysis runs on a captured PCAP.
- A PCAP can be captured, listed, downloaded and analysed from the app.
- Each fix has a test that fails without it. Each fix is verified on the G11.
**How found:**
- All 121 safe daemon GET endpoints were called on the G11. Downloads, exports, internet or UniFi calls and API keys were skipped.
- Their numbers were compared with direct OpenSearch queries over the last 24 h.
- The page-by-page browser pass is still pending: the browser was stuck on the self-signed certificate warning, and the app needs the owner's login.

## Ground truth at audit time (OpenSearch, last 24 h, 2026-11-02 ~02:26 UTC)
- **Records:** 31,967 in total: 29,413 Zeek and 2,554 Suricata alerts.
- **Zeek connections:** 12,140 records, 421.7 MB, 480,689 packets.
- **Unique sources:** 91 in total, of which 47 are LAN IPs, with 43 LAN MACs.
- **DNS:** 10,794 queries.
  - 5,361 are `pcap-monitor`, Malcolm's internal check, and nearly all of those are NXDOMAIN.
  - Response time: p50 0.2 s, p95 20 s.
- **Suricata severity:** 1 (high) = 5, 2 = 162, 3 = 2,562.
- **x509:** 14 records in 7 days.

## Fixes

Status key: ⬜ todo · 🔧 in progress · ✅ done (code) · 🟢 verified on device

### Batch 1: quick wins

| # | Status | Page | Problem | Cause | Fix |
|---|---|---|---|---|---|
| 1 | 🟢 | Devices | MAC, hostname-based category and manufacturer are empty for every device | `device_fingerprint.get_mac_for_ip` reads `_source["source.mac"]`, but `_source` is nested (`{"source": {"mac": …}}`) | Read the nested value (it may be a list) |
| 2 | 🟢 | Home | "Devices: 3", when there are ~47 LAN devices | `/api/devices/count` counts unique DHCP-assigned IPs, and a mirrored uplink sees almost no DHCP | Count with the same query and threshold as the devices list, so both always agree |
| 3 | 🟢 | Devices | List shows 27; quiet devices (phones, IoT) are hidden | `_MIN_CONNECTIONS = 20` per range | Lower it to a small noise floor (3) |
| 4 | 🟢 | DNS | About half the "queries" and nearly all "NXDOMAIN" are `pcap-monitor`, which is NetTap's own check | DNS analytics don't apply the log search's `pcap-monitor` exclusion | One shared DNS noise exclusion, used by DNS analytics and log search |
| 5 | 🟢 | DNS, Logs, Connections | Totals stop at 10,000 | OpenSearch only counts exactly to 10,000 unless asked | `track_total_hits: true` where a total is shown |
| 6 | 🟢 | DNS | Average resolution time wrong (663 ms; real average over answered queries is much higher, median 0.2 s) | `avg` with `"missing": 0` counts unanswered queries as 0 ms | Average only queries that have a response time; consider showing the median |
| 7 | 🟢 | Infrastructure | Logstash panels fail (502 "unreachable") | Daemon calls `http://logstash:9600`; on host networking Docker names don't resolve, and 9600 isn't published | Publish `127.0.0.1:9600` on logstash and set `LOGSTASH_API_URL=http://127.0.0.1:9600` for the daemon |
| 8 | 🟢 | System, Tools | CyberChef status takes 5 s and can't reach the container | Same as #7: `http://nettap-cyberchef:8443` | Publish CyberChef on loopback and point `CYBERCHEF_URL` at it |
| 9 | 🟢 | System | "Uptime" is the daemon's (minutes), not the machine's | `uptime` is measured from daemon start | Report host uptime from `/proc/uptime`, and keep daemon uptime as its own field |
| 10 | 🟢 | Infrastructure | Cluster health "yellow" on a healthy single-node box | ISM history index `.opendistro-ism-managed-index-history-*` asks for 1 replica | Daemon sets `plugins.index_state_management.history.number_of_replicas: 0` and fixes existing history indices |
| 11 | 🟢 | Any "since" or first-seen value | A record dated 1970-01-01 (index `arkime_sessions3-700101`) | zeekctl writes `conn-summary.*.log` at each hourly rotation; Filebeat ships it as an unknown log type with timestamp 0. **It recurs every hour** | Stop shipping `conn-summary*` files; then the stray index can be deleted |
| 12 | 🟢 | Risk scores (home and compliance) | `/api/risk/scores` returns 502 | `extended_stats` on `_doc_count`, which OpenSearch refuses (since Sprint 3) | Compute the connection stats from the terms buckets |
| 13 | 🟢 | Home, Bandwidth | This month's usage (1.00 GB) and 24 h total (1.08 GB) disagree, although all data is from today | Two causes. (a) Bandwidth summed `client/server.bytes`: Zeek `orig_bytes`, payload only, about 7% lower. The summary summed `source/destination.bytes`: `orig_ip_bytes`, on the wire. (b) Only bandwidth excluded NetTap's own IP | Every byte total (summary, time series, bandwidth, top talkers, top destinations, MAC correlator) sums `source/destination.bytes` with the same exclusion. A guard test blocks `client/server.bytes` sums |

### Batch 2: needs real rework

| # | Status | Page | Problem | Cause | Fix |
|---|---|---|---|---|---|
| 14 | 🟢 | Certificates | Shows TLS sessions, not certificates: subject, issuer and dates are empty, so expiry and self-signed checks can never fire; "total 1000" is a fetch cap | `cert_monitor` reads `zeek.ssl.*`; Zeek 8 keeps certificate details in `x509.log` | Rebuild on `event.dataset: x509` (dedupe by fingerprint), joined to SSL sessions for server names |
| 15 | 🟢 | IoT | IoT device list empty while the fleet summary says 7 devices | Different sources for the two | Make the list and summary use one device set |
| 16 | 🟢 | Devices, Changelog | Device registry (`nettap-devices` index) and changelog are empty | Nothing ever called `register_device()` or the `enrich_*` methods. DHCP enrichment also filtered on `dhcp.id`, which Malcolm never sets, and a list-valued `source.mac` crashed three enrichers | A daemon loop fills the registry from conn traffic (the device list's rules) at startup and every 5 min, then enriches. A device's first write logs `device_joined` |
| 17 | 🔧 | All | Browser pass: labels, charts, on-screen consistency | Owner is logged in; the home page is done, and the rest follows after the batch 1 deploy | Check every page |
| 18 | 🟢 | Home | Device Overview grid says "No devices detected yet" while the Devices card shows a count | The grid reads the empty registry (#16) | Fixed by #16 |
| 19 | 🟢 | Home | Alerts card shows 2.2K (16 high, 336 medium, 1,853 low), but the Alert Summary panel says "394 total" | (a) The summary hides informational alerts (STUN, DoH) and said so nowhere. (b) It counted SURICATA engine events as informational. (c) A composite agg read only the first 200 groups (not hit on today's data: 80 groups) | It now pages every group, drops engine events like the Alerts page does, and returns `informational_events`. The card reads "657 to review · 2.5K informational", which adds up exactly to the Alerts card |
| 20 | ⬜ | Home | Application layer: "UNKNOWN 8.7K" | Accurate: conn records where Zeek identified no protocol. The DNS slice counts every DNS connection, mDNS included | Low priority: label it "Unidentified" |
| 21 | ⬜ | Devices | Device list is slow (one lookup per device) | Per-device MAC/hostname lookups (N+1). Measured 0.24 s for 5 and 1.9 s for 500 | Low priority |
| 22 | 🔧 | Tools | CyberChef page and TShark analysis untested end to end | Part of the goal | Exercise both in the browser on the G11 |
| 23 | ⬜ | PCAP | Capture, list, download and analyse a PCAP from the app | Part of the goal | Exercise in the browser on the G11 |
| 24 | 🟢 | DNS | 76% of dns.log was mDNS/NetBIOS discovery: Top Domains led with `_services._dns-sd._udp.local`, and the average RTT read 2.2 s (real: 47 ms, median 7 ms) | DNS analytics counted local discovery as lookups | Leave out ports 5353/5355/137 when the destination is local (multicast, broadcast, private, link-local). Discovery traffic to an internet host still counts, so tunneling over 5353 is still detected (security review). Log Explorer keeps every record |
| 25 | 🟢 | Home, Devices | "DHCP-leased devices" wording | Devices come from traffic, not DHCP leases | "Devices seen on the network" |
| 26 | ⬜ | Devices | Manufacturer "Unknown" for known prefixes (`bc:24:11` Proxmox, `d0:21:f9` Ubiquiti); category "Unknown" even when the vendor is known (Philips Hue, Ubiquiti) | Small vendor table; category ignores the manufacturer | Fuller OUI data; map vendor to category |
| 27 | ⬜ | Capture | 33–40 "AF-PACKET truncated packet" a day | Offloads are off on `enp4s0`; probably the switch mirrors jumbo frames into a 1500-byte MTU | Low priority: raise the capture NIC MTU if the switch uses jumbo frames |
| 28 | 🟢 | Alerts | Top Signatures led with "SURICATA Ethertype unknown" (2,651) while the total said 2,978; the timeline axis reached 6,019 | Timeline, Top Signatures and Top IPs skipped the engine-event exclusion | Same exclusion as the count |
| 29 | 🟢 | Alerts, Threats | "100 CRITICAL" with 0 critical alerts | The score adds a weight per group, so 48 groups reach 100 | Level capped at the worst alert present (now HIGH); score unchanged |
| 30 | 🟢 | Home | "1.9GB in / 23GB out" for a 23 GB download | `orig_bytes` (usually the LAN device's upload) was labelled "in" | "23GB down / 1.9GB up", matching Top Devices and Bandwidth |
| 31 | 🟢 | Bandwidth | Top consumers led by NetTap itself (6.9 MB); internet hosts in the per-device list; day labels a day early | Top 50 by connection count, no LAN filter, % of those 50 only; UTC buckets printed in local time | LAN filter from the device list, ordered by bytes, % of all LAN traffic; labels in UTC |
| 32 | 🟢 | DNS, all | Thousands of `pcap-monitor` (and `netbox`) lookups an hour from 192.168.1.199 | zeek-live, suricata-live and arkime-live ran Malcolm's offline PCAP processor (image default), which polls a pcap-monitor service NetTap doesn't run. On host networking each retry is a DNS query to the LAN resolver | `*_PCAP_PROCESSOR: "false"` on the live containers (as in Malcolm's own); bats test |
| 33 | 🟢 | Log Explorer | Total Events 127.1K vs "107,320 results" | Stats excluded alerts but not pcap-monitor; search did the opposite | Both leave out alerts and pcap-monitor; the suricata type still shows alerts |
| 34 | 🟢 | IoT | Findings on "port 0/3"; DNS/DHCP to the router flagged as isolation risk; "unencrypted" counts local DNS/mDNS/NTP | ICMP type/code read as ports; no allowance for expected LAN services | Skip ICMP; ignore DNS/DHCP/NTP to the gateway and local discovery in the encryption share |
| 35 | ⬜ | DNS, Threats | Heuristic false positives: `*.plex.direct` flagged as exfiltration, `sentry.servarr.com` as beaconing, figma/datadog/forter as DGA | Entropy/length/frequency rules with no known-good list | Tune thresholds or add a small allowlist |
| 36 | ✅ | Tools | CyberChef never leaves its loading screen | It starts inlined Web Workers from `blob:` URLs; nginx's CSP had no `worker-src`, so it fell back to `script-src` (no `blob:`) | `worker-src 'self' blob:`; bats test; the deploy restarts nginx (single-file bind mount) |
| 37 | 🔧 | PCAP | Full continuous capture: 56 GB in ~6 h, 32 GB in one busy hour (netsniff, 10 min / 4 GB files) | `PCAP_ENABLE_NETSNIFF=true`, no filter; the spec says alert-triggered only. Retention is 30 days or disk pressure, so nothing breaks, but SSD wear is high | **Owner decision** **Owner decision 2026-11-02: cap by size** (keep full capture, limit PCAP to a share of the disk, oldest first) |
| 38 | ⬜ | Infrastructure | The pipeline shows "Bridge not_configured WAN ○ LAN ○" on a mirror-mode box | The first node always shows bridge state | Show the capture mode (mirror port, interface) instead of a bridge in mirror mode |
| 39 | ⬜ | System, Infrastructure | "Indices 5" on System vs "8 indices" on Infrastructure | Different index sets (data only vs all) | Same count, or label which indices are counted |
| 40 | 🟢 | Tools | TShark hex dump panel always empty | The analysis request never asked for raw bytes | JSON analysis sends `include_hex`; the panel reads `frame_raw`; the protocol tree hides `*_raw` fields (`c941f69`) |
| 41 | 🟢 | Tools | TShark Info column shows the protocol stack ("eth:ethertype:ip:tcp") | `-T json` carries no column data | Second `-T fields -e frame.number -e _ws.col.Info` pass, merged by frame number (`5847beb`) |
| 42 | 🟢 | IoT, Devices | ESP device "1% encrypted"; Pi with DNS-over-TLS "36%"; STUN-only device "0%" | IoT/registry queries counted every record for a MAC (162 Suricata alerts + 2 TLS conns); "encrypted" was ports 443/8443/8883 only | Shared `CONN_RECORDS` (Zeek conn only, `excluded_ips.py`); encrypted = TLS port (incl. 853) or Zeek-identified encrypted protocol; STUN left out (`d344345`, `dc9ac7c`) |
| 43 | 🟢 | Certificates | Card read 0 while 85 certificates existed (right after a daemon restart) | OpenSearch 2.x fails a "now" range inside a filter agg ("DateRangeIncludingNowQuery does not implement createWeight"); the service and the web client both turned the error into zeros | Absolute times in the stats aggs; failed query = 503; cards show "—" (`402743e`) |
| 44 | 🔧 | Capture | arkime-live never started: ~58 TLS `unknown_ca` errors a minute against OpenSearch, no Arkime sessions ever indexed | No `./curlrc:/var/local/curlrc:ro` mount, so `opensearch_status.sh` curls without credentials or `--insecure` and loops forever | **Owner decision 2026-11-02: turn it off** (no page uses Arkime; PCAP Search + TShark read netsniff files) |

## Verified correct
- **Traffic totals:** after #13 the summary, bandwidth and devices all sum `source/destination.bytes`. On the G11 the 24 h bytes equal the raw OpenSearch sum of Zeek conn records (26.47 GB).
- **DNS** after #24: 3,4xx lookups, average 51 ms, median 7 ms, matching direct OpenSearch queries (47 ms / 7 ms).
- **Alerts:** "to review" plus "informational" equals the Alerts card total exactly (657 + 2,490 = 3,147).
- **Capture:** `enp4s0` is promiscuous with GRO/LRO/TSO/GSO/VLAN offload off; 0.000% drops.
- **Alert severity mapping** is correct (1/2/3 map to high, medium and low).
- **The alerts page leaves out Suricata engine events** (`SURICATA ` prefix) on purpose, which is why it's lower than the raw 2,554.
- **Hardware and capture stats:** storage, SMART, capture interface stats and top talkers look right.

- **Batch 4 on the G11 (2026-11-02 ~04:10 UTC):** IoT protocol audit has no port-0 or duplicate encryption findings; isolation 100 with no false DNS/DHCP pairs; encryption 192.168.1.174 = 100% (DoT), 192.168.1.149 = N/A (STUN), ESP devices 100%; certificates card = list = OpenSearch distinct x509 (71 → 77 → 85 → 87 as new certs arrive); TShark returns `frame_raw` and real Info text; browser shows the hex dump, Info column, certificate rows and IoT N/A cards.
- **pcap-monitor lookups:** none since ~03:35 UTC (the batch 3 deploy); before that ~650 a minute.

## Log
- 2026-11-01: audit done; tracking doc created; batch 1 started.
- 2026-11-01: batch 1 code done, with tests for each fix. The full daemon suite passes (2,388 tests) and ruff is clean. Three agents did the work: devices (#1-#3), risk (#12) and DNS/totals/bandwidth (#4-#6, #13); I did #7-#11.
  - The per-device DNS list also leaves out `pcap-monitor` now.
  - Deploy: `bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch1.sh`. It recreates the daemon, zeek-live, logstash and cyberchef, and deletes the 1970 index (owner approved).
- **Not changed yet:** `nl_search` "large transfers" still filters on `client.bytes`. The web UI doesn't show `median_resolution_ms` yet. Pages past 10,000 results still can't be opened (an OpenSearch paging limit).
- 2026-11-01: batch 1 deployed with `deploy-data-accuracy-batch1.sh`; every check passed (device count = list = 36, Logstash 200, CyberChef reachable, uptime = host, cluster green, risk 200, 1970 index deleted).
- 2026-11-01: batch 2 (#19, #24, #25) deployed and verified with `deploy-data-accuracy-batch2.sh`. The browser pass found #26–#35.
- 2026-11-01: batch 3 (#16, #18, #31, #32, #33, plus a changelog metadata bug in manual cleanup) runs with `deploy-data-accuracy-batch3.sh`.
- 2026-11-01: batch 3 verified (registry filled, 38 `device_joined`, bandwidth #1 = devices #1 LAN-only, Log Explorer 125,406 = 125,406, processors 0 in all live containers, CSP `worker-src` present).
- 2026-11-02: batch 4 (#14, #34, #40–#43) deployed with `deploy-data-accuracy-batch4.sh`; every check ✓. A commit security review flagged the port-only isolation exclusion; now UDP-only plus multicast/broadcast, pings are a low-risk signal (`4aa478a`).
- 2026-11-02: owner decisions — PCAP: cap by size (#37); Arkime: turn off (#44). Batch 5 implements both.
