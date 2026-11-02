# 2026-11-01 — Dashboard data accuracy audit (G11)

**Status:** In progress. Batch 1 code is done and unit-tested; the device run is next.
**Branch:** `fix/dashboard-data-accuracy`, off `fix/index-template-pattern`.
**Linear:** to be created when the batch lands.

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
| 1 | ✅ | Devices | MAC, hostname-based category and manufacturer are empty for every device | `device_fingerprint.get_mac_for_ip` reads `_source["source.mac"]`, but `_source` is nested (`{"source": {"mac": …}}`) | Read the nested value (it may be a list) |
| 2 | ✅ | Home | "Devices: 3", when there are ~47 LAN devices | `/api/devices/count` counts unique DHCP-assigned IPs, and a mirrored uplink sees almost no DHCP | Count with the same query and threshold as the devices list, so both always agree |
| 3 | ✅ | Devices | List shows 27; quiet devices (phones, IoT) are hidden | `_MIN_CONNECTIONS = 20` per range | Lower it to a small noise floor (3) |
| 4 | ✅ | DNS | About half the "queries" and nearly all "NXDOMAIN" are `pcap-monitor`, which is NetTap's own check | DNS analytics don't apply the log search's `pcap-monitor` exclusion | One shared DNS noise exclusion, used by DNS analytics and log search |
| 5 | ✅ | DNS, Logs, Connections | Totals stop at 10,000 | OpenSearch only counts exactly to 10,000 unless asked | `track_total_hits: true` where a total is shown |
| 6 | ✅ | DNS | Average resolution time wrong (663 ms; real average over answered queries is much higher, median 0.2 s) | `avg` with `"missing": 0` counts unanswered queries as 0 ms | Average only queries that have a response time; consider showing the median |
| 7 | ✅ | Infrastructure | Logstash panels fail (502 "unreachable") | Daemon calls `http://logstash:9600`; on host networking Docker names don't resolve, and 9600 isn't published | Publish `127.0.0.1:9600` on logstash and set `LOGSTASH_API_URL=http://127.0.0.1:9600` for the daemon |
| 8 | ✅ | System, Tools | CyberChef status takes 5 s and can't reach the container | Same as #7: `http://nettap-cyberchef:8443` | Publish CyberChef on loopback and point `CYBERCHEF_URL` at it |
| 9 | ✅ | System | "Uptime" is the daemon's (minutes), not the machine's | `uptime` is measured from daemon start | Report host uptime from `/proc/uptime`, and keep daemon uptime as its own field |
| 10 | ✅ | Infrastructure | Cluster health "yellow" on a healthy single-node box | ISM history index `.opendistro-ism-managed-index-history-*` asks for 1 replica | Daemon sets `plugins.index_state_management.history.number_of_replicas: 0` and fixes existing history indices |
| 11 | ✅ | Any "since" or first-seen value | A record dated 1970-01-01 (index `arkime_sessions3-700101`) | zeekctl writes `conn-summary.*.log` at each hourly rotation; Filebeat ships it as an unknown log type with timestamp 0. **It recurs every hour** | Stop shipping `conn-summary*` files; then the stray index can be deleted |
| 12 | ✅ | Risk scores (home and compliance) | `/api/risk/scores` returns 502 | `extended_stats` on `_doc_count`, which OpenSearch refuses (since Sprint 3) | Compute the connection stats from the terms buckets |
| 13 | ✅ | Home, Bandwidth | This month's usage (1.00 GB) and 24 h total (1.08 GB) disagree, although all data is from today | Two causes. (a) Bandwidth summed `client/server.bytes`: Zeek `orig_bytes`, payload only, about 7% lower. The summary summed `source/destination.bytes`: `orig_ip_bytes`, on the wire. (b) Only bandwidth excluded NetTap's own IP | Every byte total (summary, time series, bandwidth, top talkers, top destinations, MAC correlator) sums `source/destination.bytes` with the same exclusion. A guard test blocks `client/server.bytes` sums |

### Batch 2: needs real rework

| # | Status | Page | Problem | Cause | Fix |
|---|---|---|---|---|---|
| 14 | ⬜ | Certificates | Shows TLS sessions, not certificates: subject, issuer and dates are empty, so expiry and self-signed checks can never fire; "total 1000" is a fetch cap | `cert_monitor` reads `zeek.ssl.*`; Zeek 8 keeps certificate details in `x509.log` | Rebuild on `event.dataset: x509` (dedupe by fingerprint), joined to SSL sessions for server names |
| 15 | ⬜ | IoT | IoT device list empty while the fleet summary says 7 devices | Different sources for the two | Make the list and summary use one device set |
| 16 | ⬜ | Devices, Changelog | Device registry (`nettap-devices` index) and changelog are empty | Nothing populates them in mirror mode (to investigate) | Find the writer and fix it |
| 17 | 🔧 | All | Browser pass: labels, charts, on-screen consistency | Owner is logged in; the home page is done, and the rest follows after the batch 1 deploy | Check every page |
| 18 | ⬜ | Home | Device Overview grid says "No devices detected yet" while the Devices card shows a count | To investigate after batch 1 (the grid may read the empty registry, #16) | |
| 19 | ⬜ | Home | Alerts card shows 2.2K (16 high, 336 medium, 1,853 low), but the Alert Summary panel says "394 total" | Two different queries or time ranges | One alert count source for both |
| 20 | ⬜ | Home | Application layer: "UNKNOWN 6.2K" is the largest slice | Sessions without `network.protocol` are bucketed as unknown | Label by port/service fallback, or leave unknown out of the chart |
| 21 | ⬜ | Devices | Device list is slow (one lookup per device) | Per-device MAC/hostname lookups (N+1) | Batch the lookups |
| 22 | ⬜ | Tools | CyberChef page and TShark analysis untested end to end | Part of the goal | Exercise both in the browser on the G11 |
| 23 | ⬜ | PCAP | Capture, list, download and analyse a PCAP from the app | Part of the goal | Exercise in the browser on the G11 |

## Verified correct
- **Traffic totals** matched OpenSearch, apart from a few seconds of lag. After #13 the summary leaves out NetTap's own traffic, so it sits slightly below a raw OpenSearch count.
- **Alert severity mapping** is correct (1/2/3 map to high, medium and low).
- **The alerts page leaves out Suricata engine events** (`SURICATA ` prefix) on purpose, which is why it's lower than the raw 2,554.
- **Hardware and capture stats:** storage, SMART, capture interface stats and top talkers look right.

## Log
- 2026-11-01: audit done; tracking doc created; batch 1 started.
- 2026-11-01: batch 1 code done, with tests for each fix. The full daemon suite passes (2,388 tests) and ruff is clean. Three agents did the work: devices (#1-#3), risk (#12) and DNS/totals/bandwidth (#4-#6, #13); I did #7-#11.
  - The per-device DNS list also leaves out `pcap-monitor` now.
  - Deploy: `bash /home/nettap/NetTap/scripts/remote/deploy-data-accuracy-batch1.sh`. It recreates the daemon, zeek-live, logstash and cyberchef, and deletes the 1970 index (owner approved).
- **Not changed yet:** `/api/logs/stats` and `/api/logs/timeline` still count `pcap-monitor` records. `nl_search` "large transfers" still filters on `client.bytes`. The web UI doesn't show `median_resolution_ms` yet. Pages past 10,000 results still can't be opened (an OpenSearch paging limit).
