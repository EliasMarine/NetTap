# NetTap release audit — November 2026

> Audit question: can a user trust what NetTap displays about their network, and understand what it cannot observe or establish?
>
> Revision audited: `446845ec` (main). Runtime: the home trial box (GMKtec G11, Realtek NICs, Ubuntu 24.04, mirror/SPAN). Audit date: 2026-11-08/09 (device clock UTC).
> All network identifiers are redacted: addresses are written as 192.0.2.x / 2001:db8::, MACs as 00:00:5e:00:53:xx, names as device-A.
> Security findings are summarised by class here; exploitation detail for open items is kept in the Linear issues, not in this public file.

**Status: complete (2026-11-09).** Fixes F1–F8 are on branch `fix/release-audit-2026-11`: not merged, not deployed.

---

## 1. Verdict

**NOT READY.** Scope: the GMKtec G11 (Realtek NICs, Ubuntu 24.04), mirror/SPAN of the router's LAN side, revision `446845ec`.

**What holds up.** Most figures are faithful to what Zeek and Suricata recorded. These reconcile exactly, or within protocol overhead, against independent sums of the source records:
- DNS lookups.
- Suricata alert counts and severities.
- Certificate sessions.
- Per-device traffic the device started.
- Controlled downloads of known size.

**What doesn't.** On the deployed revision a user can't yet trust everything shown:
- Byte and connection totals include interim long-connection records (up to 9% of a day's bytes).
- Health and "no alerts" stay green with a stopped sensor or nothing indexed.
- Three screens report successes that didn't happen.
- Alert suppressions vanish on every restart.

**What the branch fixes.** F1–F8 fix those defects. Each has tests that fail on the old code and pass on the fix. They are not yet deployed or verified on the device.

**Open blockers.** Six P1 blockers remain (NET-224–NET-229):
- notifications;
- the post-NAT inline bridge;
- device totals that leave out answered and IPv6 traffic;
- backup/restore;
- "no threats" shown without the pipeline state;
- the first-run admin claim.

**Not tested.** Inline bridge and DHCP gateway modes never ran on hardware.

### Release criteria

| # | Criterion | Result | Evidence |
|---|---|---|---|
| C1 | Test suites: no new failures vs baseline | **PASS** (branch) | Daemon 4,271 passed / 4 skipped / 0 failed (baseline 4,243 / 4 / 0). Vitest 4,331 passed (baseline 4,303). svelte-check 0 errors. Colour gate clean. Playwright visual 294 passed (50 skipped by design). bats (migration) 6/6 |
| C2 | Deployed system identified and traceable to main | **PASS** | G11 at `446845ec` on `main`, clean checkout, deploy marker matches (§2.2) |
| C3 | Connection counts and traffic totals reconcile with source | **FAIL** (main); fixed on the branch, UNVERIFIED on the device | R1: interim records summed (A1). Smoke test 06–07 UTC: API 1,177,967,041 B vs final records 1,176,382,268 B. F1 + tests on the branch |
| C4 | Upload/download direction and bandwidth correct, with units | **FAIL** | Outbound correct (R2–R4), 1,000-based units shown; inbound flows read backwards because upload = originator (B-d) |
| C5 | Device identity and attribution correct for the mode, uncertainty shown | **FAIL** | Started-by-device traffic exact (R5); answered traffic and IPv6 left out (A11, A12 → NET-226); OS/type guesses without confidence (B-h) |
| C6 | DNS activity reconciles | **PASS** | R6: 5,477 = 5,477 lookups, NXDOMAIN 475 = 476 − 1 from the appliance |
| C7 | TLS/certificate data reconciles | **PASS** | R14: 1,416 = 1,416 sessions with a chain; 1,401 verified, 15 not |
| C8 | Suricata alerts and severity faithful, worded as rule matches | **FAIL** | Counts exact (R7); severity-1 rules tagged Informational hidden from the count (B-i); explanations state compromise as fact (B-j) |
| C9 | Risk/threat scores reproducible from inputs, presented as heuristics | **FAIL** | Deterministic, and the method is shown (R8); inputs not shown; suppressions/baseline were lost on restart (A6, fixed by F4 on the branch) |
| C10 | GeoIP/ASN/vendor shown as enrichment, with fitting precision | **FAIL** | City centres pinned to ~11 m, no source or database age (R9, B-g) |
| C11 | Packet search/download right and access-controlled | **FAIL** (main); leak fixed on the branch | Daemon 401 without token, web 401 without session (smoke test). Filtered download leaked its temp file (A8, fixed by F8) |
| C12 | Capture health reflects a stopped capture and packet loss | **FAIL** (main); UNVERIFIED on the branch | NIC loss exact (R11); stopped Zeek/Suricata/Logstash/Filebeat invisible (A2). F2 adds the check; device failure injection not run |
| C13 | Storage/retention accurate; current/protected data never deleted | **FAIL** | Usage exact (R12). PCAP cap prune keeps the newest file (isolated run). Emergency index prune keeps today's index (new unit test). The retention estimate is wrong: fixed 1.2 GB/day, "30 days" PCAP vs ~7.8 actual (B-m) |
| C14 | Every data card distinguishes loading, empty, error, stale, disabled, healthy | **FAIL** | Loading/empty/error honest with OpenSearch down (local render). Stale data was invisible (A2). F2 adds it to Home/System, confirmed in a local render with the real daemon; the Alerts card still shows a bare 0 (NET-228) |
| C15 | No mock, random or hardcoded-success data in production paths | **FAIL** (main); partly fixed on the branch | Notification save/test (A3/A4) and Compliance's 100-for-nothing (A7) fixed by F3/F5. Setup's storage step still shows invented figures when the daemon is down (A16) |
| C16 | No unauthenticated data access, default credentials or committed secrets; privileged surfaces justified | **FAIL** | First-run admin claimable by any LAN host (A13 → NET-229). Public health exposed the drive serial (fixed by F6). Owner IP in git history (F7 fixes HEAD only). Daemon is host-root-equivalent (B-o) |
| C17 | Each capture mode's limits stated in product and docs | **FAIL** | Bridge mode's NAT limit not stated (A10 → NET-225); DHCP gateway "Recommended" though untested (B-n) |
| C18 | Failures surface in the UI and services recover | **FAIL** (main); UNVERIFIED on the branch | OpenSearch down: honest error states (local render). Dead sensors silent (A2). Device restart/recovery not exercised (needs approval) |
| C19 | No unresolved P0/P1 findings | **FAIL** | No P0. P1 blockers B1–B6 open (NET-224–NET-229) |

---

## 2. System under test

### 2.1 Repository (`446845ec`)

| Item | Value |
|---|---|
| Daemon | Python 3.12 image, aiohttp on :8880, host network; 263 routes |
| Web | SvelteKit (adapter-node) behind nginx 1.30 on :80/:443 |
| Malcolm images | 26.10.0 (pinned by tag, not digest) |
| Test baseline (this Mac) | daemon pytest 4,243 passed / 4 skipped / 0 failed; vitest 4,303 passed (339 files); svelte-check 0 errors / 2 warnings; colour gate clean; shellcheck 26 issues (pre-existing) |
| Docs drift | CLAUDE.md still states Zeek 6.x, Suricata 7.x, OpenSearch 2.x, Ubuntu 22.04, "alert-triggered" PCAP |

### 2.2 Deployed system (G11, observed read-only)

| Item | Observed |
|---|---|
| Deployed commit | `446845ec`, clean checkout on `main`, deploy marker matches |
| OS / kernel | Ubuntu 24.04.5, 6.8.0-147 (target hardware in docs: N100, i226-V, Ubuntu 22.04 — not what was tested) |
| RAM | 11 GiB total; 3.3 GiB swap in use at audit time (memory pressure) |
| Components | Zeek 9.0.1 (custom `nettap/zeek-live:26.10.0`), Suricata 8.0.7, OpenSearch 3.9.0, Malcolm 26.10.0 Logstash/Filebeat |
| Capture mode | mirror on `enp4s0` (promiscuous, no IP), management on `eno1` |
| What the mirror carries | LAN side of the router (pre-NAT): sources are private client addresses, destination MAC is the router |
| Running services | 15 containers; zeek-live, suricata-live, pcap-capture have no Docker healthcheck |
| Not running | Arkime session capture (no `arkime` provider documents); Grafana (off by default) |
| Data volume | ~1.6–3.7 M documents/day in `arkime_sessions3-YYMMDD`; Suricata ~86 k alerts/day (98% ET INFO/activity) |
| PCAP | full capture by netsniff-ng, 100 MiB files, 454 GB over 7.25 days ≈ 63 GB/day; capped at 25% of disk by the daemon (so ~7.8 days kept, not the 30 shown as "cold tier") |
| Malformed events | index `arkime_sessions3-700101` holds 17 documents dated 1970 (Zeek files/dhcp records with a zero timestamp) |
| Ingestion latency | conn record indexed 10–20 s after the connection closed (controlled test) |
| Capture loss (NIC) | 0.005% cumulative (rx_missed_errors 11,554 of 225.7 M) |
| Exposed ports | 22, 80→443 (nginx), 443, 8880 (daemon, all interfaces, token required); OpenSearch 9200, Logstash 9600, CyberChef 8443 on loopback only |

### 2.3 Real data path

```
mirror port → enp4s0 (promisc)
  ├─ zeek-live (host net)  → Zeek logs (conn, conn_long, dns, ssl, x509, http, files, …)
  ├─ suricata-live (host net, af-packet) → eve.json (alerts only)
  └─ pcap-capture (netsniff-ng) → /pcap/*.pcap (pcap-data volume)
Zeek/Suricata logs → Filebeat → Logstash (Malcolm enrichment: GeoLite2 geo/ASN, OUI, community_id, risk tags)
  → OpenSearch index arkime_sessions3-YYMMDD (one index for all Zeek datasets + Suricata alerts)
  → daemon (opensearch-py queries; PCAP via tshark container / packet index)
  → web server routes (/api/** proxies with the daemon token)
  → Svelte pages
```

Field mapping verified on live records (Zeek conn): `source.bytes` = `zeek.conn.orig_ip_bytes` (IP-layer), `destination.bytes` = `resp_ip_bytes`, `client.bytes` = `orig_bytes` (payload), `server.bytes` = `resp_bytes`, `network.bytes` = sum of IP bytes, `totDataBytes` = sum of payload bytes. `@timestamp` = `zeek.ts` = connection **start**; the record is written when the connection **ends**.

---

## 3. Data-provenance matrix

Class: **O** = Zeek protocol observation, **S** = Suricata rule match, **N** = NetTap-generated classification/score/heuristic, **E** = external enrichment. "On failure" is what the page shows when the daemon query fails (verified by rendering the production build against the real daemon with OpenSearch unreachable, 2026-11-09).

| Item (page) | Producer → fields | Query (index, filter, window) | Calculation / units | Class | Freshness | On failure | Known limits |
|---|---|---|---|---|---|---|---|
| Bandwidth, Connections KPIs (Home) | Zeek conn → `source.bytes`/`destination.bytes` (IP bytes), `source.packets`… | `arkime_sessions3-*`, provider zeek, dataset conn, `@timestamp` (start) in window, appliance IP excluded as source | Σ IP bytes, 1,000-based units; count = conn records | O | refresh per page timer; record appears 10–20 s after the connection **ends** | "Couldn't load …: the request failed." | interim long-connection records summed (F1); long connections attributed to start hour; partial shard replies not flagged (TRF-3) |
| Bandwidth over time (Home, Bandwidth) | same | date_histogram on `@timestamp` | bytes per bucket, "Downloaded/Uploaded" = resp/orig | O | same | error card | upload = originator, so inbound flows are reversed (TRF-4) |
| Top devices / Devices list | Zeek conn; MAC/OUI from Malcolm, hostname from DHCP/DNS/mDNS | `source.ip` terms on detected LAN /24s, IPv4 only, ≥3 conns | Σ bytes where device is **source** | O + E (OUI) + N (type/OS) | same | error card | responder traffic omitted (DEV-3); IPv6 omitted (DEV-2); post-NAT bridge shows only the router (DEV-1); OS/type are guesses shown without confidence (DEV-7/8) |
| Device "New" / registry | NetTap hourly pass over conn records | keyed by MAC | first registration | N | hourly | error card | rotating private MACs counted again (DEV-13) |
| DNS stats (DNS) | Zeek dns → `zeek.dns.query`, `rcode_name`, `rtt` | dataset dns, local discovery (mDNS/LLMNR/NetBIOS to local addresses) and `pcap-monitor` excluded | rows = lookups; RTT mean in ms | O | same | error card | DoH/DoT invisible and not stated (DNS-1); mean shown, median hidden (DNS-3) |
| Top domains | Zeek dns | terms `zeek.dns.query` | count, unique clients | O | same | error card | top-N truncation not stated (DNS-8) |
| Certificates | Zeek ssl/x509 → validation status, not_valid_after | dataset ssl/x509 | expiry vs daemon clock | O | same | 503 "Certificate data is unavailable" | TLS 1.3 hides certs (stated on page); "your network" uses fixed RFC 1918 list (TLS-1) |
| Alerts count & list | Suricata eve alert → `rule.name`, `suricata.alert.severity`, ET `signature_severity` | provider suricata; excludes `SURICATA *` engine events and ET Informational/Unknown ("activity") | count by Suricata severity 1/2/3 → high/medium/low | S | same | error card | dead Suricata reads as "no alerts" (F2/ALR-1); sev-1 rules tagged Informational hidden from the count |
| Smart alerts / threat score (Alerts, Threats) | Suricata alerts + Zeek conn (who opened) | groups (rule, src, dst); reclassified severity | weights 10/5/2/0.5, cap 100, +15 busier window, level ≤ worst alert | N on top of S | same | error card (never shows 0 on error) | inputs not shown; suppressions/baseline in tmpfs (F4); post-NAT scoring at full weight (ALR-3) |
| Compliance / security posture | several APIs | — | weighted mean of 6 category scores, grade A–F | N | page load | — | empty inputs score 100 → grade A (F5) |
| GeoIP / globe / destinations | Malcolm GeoLite2 at ingest → `destination.geo.*`, `destination.as.*` | stored fields; daemon fallback table | city name, lat/lon (shown to ~11 m) | E | ingest time | GeoIP query error → shown as "Unknown" (GEO-4) | city-centre estimates shown as pins (GEO-2); DB age not shown (GEO-3) |
| Categories | ASN/name → NetTap classifier | top destinations | category by ASN substring | N | same | error card | Google = Streaming, Cloudflare = Security & VPN (TRF-10) |
| Live monitor | Zeek conn, last 5 min | `@timestamp` ≥ now-5m | — | O | 3 s poll | error cards; "Live" badge stays | records exist only after a connection ends, so long streams never appear "right now" (TRF-1) |
| Packets / PCAP | netsniff-ng files + packet index; tshark | file mtime and packet index | packet rows, downloads | O (raw) | file rotation 100 MiB / 15 min | search states shown (/packets) | ~7.8 days kept under the 25% cap; `/pcap` filtered download leaks temp files (F8/PKT-1) |
| Capture health (Home pipeline, System) | sysfs NIC counters, link, promisc | — | loss % over a window | O (kernel) | 30 s | "Unknown" when the request fails | Zeek/Suricata/Logstash drops and stopped containers not checked (F2/HLT-1/HLT-2) |
| System health | storage, SMART, OpenSearch ping | — | healthy / incomplete / problem | N | page load | "Problem" when OpenSearch is unreachable (verified) | no data-freshness or sensor check (F2) |
| Storage / retention | `shutil.disk_usage`, index list, retention.json | — | %, days per tier | O (host) | 60 s cycle | error row | estimate uses fixed 1.2 GB/day (STO-8); ext4 reserved blocks ignored (STO-3) |

---

## 4. Reconciliation log

Window for live checks: 2026-11-09 04:00–05:00 UTC unless stated. Expected values computed directly from OpenSearch documents (Zeek fields), not through NetTap code.

| # | Area | Source evidence | Expected | API | Displayed | Verdict |
|---|---|---|---|---|---|---|
| R1 | Connections + traffic totals | 38,261 Zeek conn docs (excl. appliance IP); Σ orig_ip_bytes 481,091,743 + resp_ip_bytes 1,581,302,561 | 2,062,394,304 B; 2,652,746 pkts | identical | UNVERIFIED (live UI behind cert interstitial) | PASS for the query; FAIL overall — see F1: interim long-connection records are summed (92 uids with 2–3 docs in this hour; 9.2% of a full day's bytes on 2026-11-08) |
| R2 | Known-size HTTPS download (controlled) | curl body 10,000,000 B | payload ≥ 10,000,000 | server.bytes 10,019,473; destination.bytes (IP) 10,379,841 | — | PASS (difference = TLS/HTTP framing + TCP/IP headers, 0.2% / 3.8%) |
| R3 | Known-size HTTP download (controlled) | curl body 5,242,880 B | payload 5,242,880 + headers | server.bytes 5,243,156 (+276 B headers); IP 5,431,664 | — | PASS |
| R4 | Direction | outbound LAN→internet: orig = LAN client | upload = orig | NetTap "upload" = originator | — | PASS for outbound; FAIL for inbound/responder flows (TRF-4, DEV-3) |
| R5 | Per-device attribution (this Mac) | as source: 3,876 conns, orig 492,531,037 B, resp 107,958,288 B; as destination: 111 conns, 251,154 B | 600,489,325 B if "started by device" | 600,489,325 B | — | PASS for "connections the device started"; responder traffic (111 conns) is omitted and not labelled (DEV-3) |
| R6 | DNS | 21,135 Zeek dns rows; 15,614 mDNS (5353), 41 NetBIOS, 5,480 port 53; 3 port-53 lookups from the appliance (excluded) | 5,477 lookups; 476 NXDOMAIN (1 from appliance) | 5,477; 475 | — | PASS (local discovery excluded by design; documented in code, not on the page) |
| R7 | Suricata alerts + severity | 7,645 Suricata alerts; minus `SURICATA *` engine events and ET `signature_severity` Informational/Unknown | 45 (sev1 2 / sev2 22 / sev3 21) | 45 / 2 / 22 / 21 | — | PASS for the query. Policy finding: severity-1 rules tagged Informational/Unknown by ET (e.g. cleartext Basic-Auth password, `.htpasswd` access) are moved out of the alert count into "activity" |
| R8 | Threat score | 24 h: 26 groups, 92 counted events, 97,733 informational | formula in `alert_intelligence.py:1754-1935` | 41 / medium | — | PARTIAL: deterministic and its method is shown (`THREAT_SCORE_HOW`), but its inputs (findings, suppressions, baseline) are not shown and suppressions/baseline live in tmpfs (F4) |
| R9 | GeoIP | Malcolm GeoLite2 fields on the record (city, postal code, lat/lon) | city-level estimate | daemon cannot open MaxMind itself (`maxminddb` not installed): uses stored session fields or a built-in table | — | FAIL (GEO-2/3): city centres shown to ~11 m with a map pin; no source or database age shown; Cloudflare anycast destinations have no country |
| R10 | PCAP search/download | 3,510 files, newest written 3 min before check | — | `/packets` reports how each search ended (agent-traced); `/pcap` "Download filtered" leaks temp files on a 50 MB tmpfs (PKT-1) | — | FAIL (PKT-1) |
| R11 | Capture health | NIC counters: 225.7 M packets, 11,982 lost | 0.005% loss | identical | — | PASS for NIC counters; FAIL as "capture health": Zeek/Suricata/Logstash state and data freshness are not checked (F2) |
| R12 | Storage/retention | `df`: 552.8 GB of 1,965 GB; OpenSearch indices ~16 GB; PCAP 454 GB | 28.1% | 28.1% | System page "Cold tier (PCAP files) 30 days · or sooner, once PCAP passes its share of the disk" | PASS for usage; retention estimate uses a hardcoded 1.2 GB/day (actual 1.7–2.8 GB/day of indices + 63 GB/day PCAP) |
| R13 | IPv6 | network has only ULA/link-local IPv6; no global IPv6 path | — | — | — | UNVERIFIED (no IPv6 internet on the test network) |
| R14 | TLS / certificates (06:00–07:00 UTC) | Zeek ssl records with a certificate chain, excluded sources removed: 1,416; validation ok 1,401, "unable to get local issuer" 13, "self-signed in chain" 2 | 1,416 sessions | `/api/certificates/overview`: 1,416 sessions, 1,416 with details, 44 certificates, 53 sites, 9 findings | UNVERIFIED (live UI) | PASS for sessions; the certificate count (44) was not independently recounted |

---

## 5. Findings

Verification column: **live** = reproduced on the G11; **local** = reproduced with the production web build and the real daemon on this Mac (OpenSearch unreachable, or a stub OpenSearch that is healthy but receives no data); **code** = traced end to end in code by the lead auditor; **agent** = traced in code by a slice reviewer and spot-checked, not independently reproduced; **suspected** = plausible, not confirmed. The per-slice inventories with every P2/P3 are in `Debugging/release-audit-2026-11/`.

No P0 was found.

### P1 — materially wrong information, broken core function, silent failure

| ID | Finding | Evidence | Verified | Affects | Outcome |
|---|---|---|---|---|---|
| A1 | Long-connection interim records (`conn_long.log`, cumulative) are summed with the final record | 9.2% of 2026-11-08 bytes; one uid counted 317,561 B vs 139,792 B; smoke test hour 05–06 UTC: API 1,918,401,528 B vs final records 1,873,583,831 B | live | every byte/connection figure, device totals, bandwidth, monthly usage, drill-downs | **Fixed (F1, NET-230)** |
| A2 | Health and "no alerts" stay green when Zeek, Suricata, Logstash or Filebeat stop or nothing is indexed | `server.py:529-582` checks storage, SMART, OpenSearch ping only; stub run (healthy OpenSearch, no new documents): 200 OK with 0 alerts and 0 bytes, health not "problem". Home's traffic empty state is honest when the *whole* window is empty ("OpenSearch is connected but no network connections have been logged"), but a window that went stale part-way looks normal and nothing on System or the pipeline flags it | local + code | Home pipeline, System, Alerts, Threats, Compliance | **Fixed (F2, NET-231)** — health now reports stale data and stopped sensors; Alerts/Threats empty states still don't mention it (B5) |
| A3 | Notification settings page says "saved successfully"; the server discards the body | `routes/api/notifications/config/+server.ts` POST | code | Settings › Notifications | **Fixed (F3, NET-232)** |
| A4 | "Send test notification" always reports success | `lib/server/notifications.ts` swallows SMTP errors, ignores `res.ok` | code | Settings | **Fixed (F3, NET-232)** |
| A5 | External notifications don't work in a Docker install and routing rules never fire | env names differ between loader (`NOTIFY_*`), `.env.example` and compose (which forwards none); `notification_hub.process_event` has no caller; alert notifications only fire while a browser has the app open | code | Notifications | **Blocker B1** |
| A6 | Alert suppressions, false-positive marks, baselines and the threat-intel cache are kept in tmpfs and lost on every daemon restart | `NETTAP_DATA_DIR` unset on the G11; `/tmp` is tmpfs | live | Alerts, threat score | **Fixed (F4, NET-233)** |
| A7 | Security posture scores "nothing measured" as 100, grade A, "Excellent" | `compliance/+page.svelte:141-228` | code | Compliance | **Fixed (F5, NET-234)** |
| A8 | PCAP Search "Download filtered" leaves its temp file on a 50 MB tmpfs; downloads fail once it fills | `api/pcap.py:210-211` (`_tmp_path` never read) | code | PCAP Search | **Fixed (F8, NET-236)** |
| A9 | Backup/restore says "Import successful" but skips retention and capture mode | `config_backup.py:39-44` reads `retention_config.json`/`capture_config.json`; the daemon uses `retention.json` and `capture-mode.conf` | code | Settings › Backup | Blocker B4 |
| A10 | Inline bridge (post-NAT): Devices shows only the router, DNS says devices "made no DNS queries", threat score charges internet noise at full weight; empty states promise devices will appear | DEV-1, DNS-1, ALR-3 | agent; not testable here | bridge mode (advertised) | Blocker B2 |
| A11 | Device totals count only connections the device started; servers (NAS, media server) and responders are understated, unlabelled | live: 111 connections to this Mac omitted; `devices.py:605-620` | live | Devices, Top devices | Blocker B3 (label or count both sides) |
| A12 | Device views are IPv4-only; IPv6 traffic of dual-stack devices is missing while the MAC page includes it | `excluded_ips.py:299-315` | agent | Devices | Blocker B3 |
| A13 | First host to reach a fresh install can create the admin account (no setup code) | `hooks.server.ts`, `setup/+page.server.ts` | agent (security) | install/first run | Blocker B6 |
| A14 | TShark runs as root, parses attacker-crafted packets, and shares a Docker network with services that trust identity headers | NT-02 | suspected | container isolation | Blocker B6 (verify on device, then isolate TShark) |
| A15 | ILM policy failure at startup is never retried and Settings still shows "Policy synced" | STO-2 | agent | retention | NET-237 |
| A16 | Setup Storage step shows invented disk figures when the daemon is down | HON-8/STO-8 | agent | setup | NET-237 |

### P2 — misleading presentation, edge cases, recoverable reliability defects (selected)

| ID | Finding | Verified | Outcome |
|---|---|---|---|
| B-a | Unauthenticated `/api/health` returns drive model/serial, storage and SMART | live | **Fixed (F6, NET-235)** |
| B-b | Setup's final check says "NetTap daemon · Running" when the daemon is down (`/api/health` is always 200) | code | **Fixed (F6, NET-235)** |
| B-c | The owner's real public IP is committed as a placeholder (Settings, comments, tests; also in history) | live | **Fixed in HEAD (F7)**; history unchanged |
| B-d | Upload/download = connection originator, so inbound flows (port forwards, P2P, servers) read backwards (TRF-4) | live (semantics) | NET-237 |
| B-e | Live page "Right now" can't show long-running connections (records exist only after they end) (TRF-1) | code | NET-237 |
| B-f | Partial-shard OpenSearch replies shown as complete totals (TRF-3, ALR-11) | agent | NET-237 |
| B-g | GeoIP: city centres shown to ~11 m with a map pin; no database age/source; daemon can't open MaxMind (`maxminddb` missing); query errors cached as "Unknown" (GEO-2/3/4) | agent + live (anycast without country) | NET-237 |
| B-h | Device type/OS are substring guesses shown as fact (DEV-7/8/9); IoT trust and isolation grades claim health from unseen inputs (DEV-10/11) | agent | NET-237 |
| B-i | Severity-1 Suricata rules tagged "Informational"/"Unknown" by ET are moved out of the alert count (cleartext Basic-Auth password, `.htpasswd` access) without saying so on the page | live | NET-237 |
| B-j | Alert/explanation text states compromise as fact ("IMMEDIATE: Isolate", "Only this device triggers this alert") (HON-15, ALR-6, ALR-14) | agent | NET-237 |
| B-k | DNS pages don't say DoH/DoT is invisible; mean RTT shown, median hidden (DNS-1/3) | agent | NET-237 |
| B-l | Capture can stay stopped after a disk-full event (stop 95%, delete to <90%, resume <85%) (STO-1) | code | NET-237 |
| B-m | Retention estimate uses a fixed 1.2 GB/day (actual 1.7–2.8 GB indices + ~63 GB PCAP/day on the G11) | live | NET-237 |
| B-n | Setup wizard: "Inline bridge — sees all WAN traffic" omits that devices become indistinguishable; DHCP gateway "Recommended" though untested on hardware | code | NET-237 |
| B-o | Daemon on 0.0.0.0:8880 (token-protected), daemon is host-root-equivalent (docker.sock, SYS_ADMIN, writable systemd dir), capture containers root with NET_ADMIN; images pinned by tag not digest; CyberChef served without login | live + agent | NET-237 |
| B-p | Error replies include internal exception text (OpenSearch URLs, connection errors) | local | NET-237 |

### P3 (selected)

Docs drift (component versions, "alert-triggered PCAP"); 17 documents with 1970 timestamps in `arkime_sessions3-700101`; Live page keeps its "Live" badge while every request fails; GeoLite fallback table names fixed cities for anycast services; shellcheck's 26 pre-existing warnings.

---

## 6. Fixes made

Branch `fix/release-audit-2026-11`. Each fix has a Linear issue and tests that fail on the old code and pass on the fix. Fail-before was checked by restoring the old code.

| Fix | Finding | What changed | Regression tests | Linear |
|---|---|---|---|---|
| F1 | A1 | `CONN_ACCOUNTING` (`excluded_ips.py`) drops `conn_long.log` interim records from every byte/connection query; live views and alert evidence keep raw records | `test_conn_long_interim.py`, Logs list count test | NET-230 |
| F2 | A2 | `services/pipeline_health.py`: newest `event.ingested` (stale > 15 min, no data after a 10 min grace) + `docker inspect` of the four sensors; `pipeline` in `/api/system/health`; Data stage on Home, "Data and sensors" on System | `test_pipeline_health.py`, health/Home/System tests | NET-231 |
| F3 | A3, A4 | Notification save answers 501 and says nothing was saved; the test reports each channel (200/409/502), counts webhook 4xx/5xx as failures, and names a missing mail library in plain words | route `server.test.ts`, `notifications.test.ts` | NET-232 |
| F4 | A6 | Suppressions, baselines and threat-intel cache default to `/opt/nettap/data`; `migrate-daemon-state.sh` carries existing files across before the recreate (JSON-checked, older copy kept, only a regular root-owned file) | `test_data_dir_persistence.py`, `test_migrate_daemon_state.bats` | NET-233 |
| F5 | A7 | Compliance: "Not measured" for empty categories; grade over measured categories only; zero alerts no longer "looks clean" | `compliance.test.ts` | NET-234 |
| F6 | B-a, B-b | Public `/api/health` returns only the daemon's status; setup's final check reads it | `api/health/server.test.ts`, `setup-wizard.test.ts` | NET-235 |
| F7 | B-c | Owner IP placeholder replaced by 203.0.113.10 in HEAD (history unchanged) | — | NET-235 |
| F8 | A8 | `_TempFileResponse` deletes the filtered PCAP once sent; the service deletes it on a write error or cancel | `test_pcap_download_cleanup.py` (normal, disconnect mid-send, disk full, cancel) | NET-236 |

Also added: `test_prune_emergency_never_deletes_todays_index` (closes the index-retention UNVERIFIED item).

**Review gates (pre-commit).**
- `/deep-review` with four reviewers: no findings.
- `/ponytail-review`: cut the deploy script's copy of the smoke-test checks, and fixed a race in the smoke test's traffic check, which now brackets the API call with two independent sums.
- Two-angle review, security: no HIGH or MEDIUM. Two LOWs fixed: the token now goes to curl on stdin, and the migration refuses links and foreign-owned files.
- Two-angle review, TypeScript: no HIGH. Fixed the zero-alerts wording, the raw nodemailer error and a malformed-sensors guard.
- Two-angle review, Python: no HIGH. One MEDIUM fixed: the pipeline probe now has its own thread, because queue time on the shared route pool read as "couldn't check", and an "unknown" result is cached for 5 s, not 30 s. It confirmed F1 covers every accounting query.

**Verified locally (2026-11-09).** Setup:
- the real daemon at the branch head;
- the production web build;
- an OpenSearch stub with no sensors behind it.

Results:
- `/api/system/health` answers `problem`, pipeline `sensor_stopped`, all four sensors `missing`.
- Home's pipeline shows "Data: Zeek, Suricata, Logstash and Filebeat stopped" and "System: Reports a problem".
- System's "Data and sensors" row says the same.
- Compliance shows "Not measured", not a grade.
- The same render shows the open gap: the Alerts card still reads a bare "0" (NET-228).

**Verified on the device: none yet.** The read-only smoke test on `main` gives 16 PASS / 2 FAIL / 1 WARN. The fails are F1 and F6; the warning is F2's missing pipeline check.

After deploying the branch, all three should pass:
```bash
bash scripts/remote/deploy-release-audit.sh
```

---

## 7. Capture-mode capability and limitations

Tested = observed on the G11 in this audit. Code = traced in code and unit tests only; no hardware run.

| Feature | Mirror / SPAN (tested, G11, LAN-side mirror) | Inline bridge (code only) | DHCP gateway (code only; README: "Not yet tested on real hardware") |
|---|---|---|---|
| Sees internet traffic of LAN devices | Yes, if the mirrored port carries it (router uplink here) | Yes, all WAN traffic | Yes, for devices that took a NetTap lease |
| Per-device attribution | Yes (pre-NAT addresses + MACs) | **No**: post-NAT, every device is the router's IP; Devices, DNS-per-device and threat scoring degrade (DEV-1, DNS-1, ALR-3) | Yes, by NetTap-issued address |
| Device-to-device (LAN↔LAN) | Only flows that cross the mirrored port; switch-local traffic is invisible | No | No (bypasses NetTap) |
| Static-IP clients | Yes if their traffic crosses the mirror | As router IP | **Bypass NetTap** |
| IPv6 | Captured; device views are IPv4-only (DEV-2) | Post-NAT/prefix only | **Bypasses NetTap** when the router sends RAs (Go Live warns) |
| Asymmetric routing | Depends on mirror config (one direction missing → `missed_bytes`, half-flows) | n/a (single path) | n/a |
| Capture loss visibility | NIC counters only (0.005% observed) | br0 counters (virtual) — physical-port drops not counted (HLT-2) | NIC counters |
| Encrypted content | Not decrypted (metadata only; TLS 1.3 hides certificates — stated) | same | same |
| Effect if NetTap fails | None on the network | Kernel bridge keeps forwarding (stated) | Devices lose internet when leases expire (Go Live warns) |
| Wording in setup wizard | "See traffic per device on the LAN" — fair | "Sees all WAN ingress and egress" — omits that devices become indistinguishable (P2) | "Recommended", "Works with any router" — omits untested status and the bypass list until Go Live (P2) |

---

## 8. Remaining release blockers

Parent issue NET-223. Each blocker is an unresolved P1.

| # | Blocker | Linear | What resolves it |
|---|---|---|---|
| B1 | External notifications can't be configured in a Docker install; routing rules never fire; alert notifications need an open browser | NET-224 | One config contract (loader, compose, `.env.example`, page) and server-side dispatch, or remove the feature from v1.0 and say so |
| B2 | Inline bridge (post-NAT): device, DNS and threat views claim what NetTap can't see | NET-225 | Mode-aware copy and empty states; wizard states the NAT limit; a bench run |
| B3 | Device totals omit responder traffic and all IPv6 | NET-226 | Count the LAN party on both sides (and LAN-side direction), add IPv6 to the LAN rule — or label every device figure "connections this device started, IPv4" |
| B4 | Backup/restore reports success but skips retention and capture mode | NET-227 | Back up the real files; apply capture mode on restore; report what was restored |
| B5 | Alerts/Threats/Compliance say "no threats" / "clean" without the new pipeline check beside them | NET-228 | Show pipeline state with every "no alerts"/"clean" message; reword "no alerts" as "no rule matched" |
| B6 | First host on a fresh install can claim the admin account; TShark not network-isolated (suspected) | NET-229 | One-time setup code from the installer; `network_mode: none` for TShark after the on-device check |

Also required by the existing gate in `RELEASE-VERIFICATION.md`, still open: hardware checks H2–H7, CI green, release notes, version bump.

---

## 9. UNVERIFIED areas

| Area | Why unverified | What would resolve it |
|---|---|---|
| Rendered live UI on the G11 | Chrome stops at the appliance's self-signed certificate interstitial; the audit does not click past security warnings | Owner opens `https://<appliance>` in the Claude tab group, accepts the certificate and signs in; then re-run the reconciliation screenshots |
| Inline bridge and DHCP gateway on hardware | No bench; G11 runs mirror mode on the live home network | Isolated two-NIC bench (modem → NetTap → router) per mode |
| IPv6 internet traffic | Test network has only ULA/link-local IPv6 | A network with global IPv6, or an IPv6 PCAP fixture replayed into an isolated stack |
| A benign IDS trigger end to end (alert < 10 s, H5) | Contacting a third-party test endpoint needs owner approval; no isolated Zeek/Suricata stack was run | Owner approves `curl http://testmynids.org/uid/index.html` from a LAN client, or replay a fixture PCAP into an isolated stack |
| Failure injection on the device (stop Suricata/Zeek/Logstash, OpenSearch restart, reboot, MS-001 role mapping surviving recreate) | Disruptive on the live appliance; needs approval | Owner-approved window; run with the F2 build deployed so the new pipeline check is exercised |
| Disk full / near full | Must not be done on the live box; no isolated stack with a small disk | Isolated VM with a small data disk |
| Malcolm update failure and rollback | Disruptive | Isolated stack |
| ~~Index retention (today's index protected)~~ | Resolved 2026-11-09: manual cleanup and PCAP pruning already had tests; `test_prune_emergency_never_deletes_todays_index` now pins the emergency prune | — |
| 500 Mbps zero-loss, <1 ms added latency (bridge) | No bench | iperf3 through a bridge bench (H3) |
| Fixes F1–F8 on the device | Not deployed (needs explicit authorisation) | Owner runs `bash scripts/remote/deploy-release-audit.sh` (it ends with the smoke test) |
| State migration inside the real daemon container | Claude Code's removal safety check blocks running a script with `rm` through `docker exec sh -c`; the logic is covered by bats on macOS `sh` and shellcheck in POSIX mode | The deploy script runs it on the device; its Step 6 confirms every file arrived |
| Certificate count (44) on the Certificates page | Sessions reconciled (R14); distinct server certificates not recounted independently | A first-fingerprint cardinality over the same window |

---

## 10. Pre-release smoke test

`scripts/remote/smoke-test-release.sh` is read-only: no pull, no rebuild, no restart. Run it on the device as the normal user after any deploy:

```bash
bash scripts/remote/smoke-test-release.sh
```

It prints one PASS / FAIL / WARN line per check and exits non-zero on any FAIL. The daemon token is read inside each request and passed to curl on stdin, so it never shows in output or in `ps`.

| Step | Check | Fails when |
|---|---|---|
| 1 | Revision and a clean checkout | local changes (warn) |
| 2 | The nine core containers run (healthy where they have a healthcheck) | any missing or not running |
| 3 | OpenSearch cluster health | not green (yellow warns) |
| 4 | Newest Zeek record's `event.ingested` | older than 15 min, or none in 24 h |
| 5 | Daemon refuses requests without the token; system health; the F2 pipeline state; capture health; packet loss (info) | health not "healthy", pipeline not "fresh", capture not "normal" |
| 6 | Last full hour's traffic total vs an independent sum of Zeek's final conn records (excluded IPs removed), taken before and after the API call | API total outside that range (interim records counted) |
| 7 | Web API refuses requests without a session; public `/api/health` carries no hardware detail | either fails |
| 8 | Disk use (info) | — |

On `main` (`446845ec`), 2026-11-09: 16 PASS, 2 FAIL (step 6, step 7 hardware detail), 1 WARN (step 5 pipeline). With the branch deployed, the expected result is all PASS.

Before tagging a release, also run:
- the Dev suites: daemon pytest, vitest, svelte-check, `npm run check:colors`, `npm run test:visual`, bats;
- a benign IDS trigger from a LAN client, checking the alert appears in under 10 s (H5).
