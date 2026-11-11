# NetTap release audit — November 2026

> Audit question: can a user trust what NetTap displays about their network, and understand what it cannot observe or establish?
>
> Revision audited: `446845ec` (main). Runtime: the home trial box (GMKtec G11, Realtek NICs, Ubuntu 24.04, mirror/SPAN). Audit date: 2026-11-08/09 (device clock UTC).
> All network identifiers are redacted: addresses are written as 192.0.2.x / 2001:db8::, MACs as 00:00:5e:00:53:xx, names as device-A.
> Security findings are summarised by class here; exploitation detail for open items is kept in the Linear issues, not in this public file.

**Status: complete (2026-11-09).** All P0/P1 findings are fixed in PR #236 (`fix/release-audit-2026-11`, merged to `main` with the owner's approval):
- wave 1, F1–F8;
- wave 2, the six P1 blockers and the P2 list (section 6.2);
- wave 3, the device checks and the reload 502 they found (section 6.3).

The owner approved the four device steps, and all were run on the G11 on 2026-11-09:
- the TShark and nginx recreate;
- failure injection;
- a benign IDS trigger;
- the rendered UI.

The G11 runs the PR head `a7623897` (the tree `main` received). The smoke test gives 29 PASS / 0 FAIL / 0 WARN.

---

## 1. Verdict

**`main` before PR #236 (`446845ec`) was NOT READY.** It had every finding, including a 502 on every logged-in page reload (A17).

**With PR #236 merged and deployed: READY WITH LIMITATIONS.** Scope: the GMKtec G11 (Realtek NICs, Ubuntu 24.04), mirror/SPAN of the router's LAN side. The four owner steps all passed on the G11 (section 6.3):
1. The TShark and nginx recreate: TShark has no network and runs as nobody, and CyberChef needs a login (C16).
2. Failure injection (C12, C18):
   - a stopped Suricata was reported in 1 s and a stopped Zeek in 22 s, and each recovered on its own;
   - an OpenSearch restart kept its auth (Chain 21 confirmed) and ingestion resumed.
3. A benign IDS trigger (C8): Suricata matched in under a second and the alert was indexed 11.3 s after the packet. That is just over the 10 s goal (H5, NET-243). Fixed 2026-11-11 (PR #247): median 2.0 s, max 6.5 s.
4. The rendered UI: a stopped sensor shows on Home. Checking the UI found the reload 502 (A17); it is fixed and verified.

**What holds up.** These reconcile exactly, or within protocol overhead, against independent sums of the source records on the G11:
- traffic totals (4,570,892,146 B = 4,570,892,146 B for 17:00–18:00 UTC after the wave-2 deploy);
- per-device connections from both sides, IPv6 by MAC included (device-A: 4,578 = 3,053 started + 1,432 answered + 93 IPv6);
- DNS lookups;
- Suricata alert counts and severities;
- certificate sessions;
- controlled downloads of known size.

**What the branch makes honest.** Every "no alerts" message names the pipeline state, and health reports stale data and stopped sensors. Partial or capped searches are errors, not low figures. Saves, tests and restores say what really happened. Guesses (device type, OS, GeoIP city) are labelled as guesses, with their source. Each capture mode says what it can't see.

**Limitations a release would carry:**
- Inline bridge and DHCP gateway were never run on hardware; their limits are stated in the product, not measured.
- Global IPv6 was not observed (the test network has ULA and link-local only).
- ~~The threat score's suppressions and baseline aren't shown (C9, NET-239).~~ Fixed 2026-11-11 (PR #247): the score's method now says how many findings suppressions left out and whether the +15 applied.
- ~~A capped detection view fails as "incomplete" rather than showing what it read (NET-238).~~ Fixed 2026-11-11 (PR #247): DNS and threat-intel detections show what they read and say where the scan stopped; totals stay fail-closed.
- ~~With a sensor stopped, Alerts still lists older alerts without saying the IDS isn't running; only Home's Capture pipeline card and System say so (NET-242).~~ Fixed 2026-11-11 (PR #247): Alerts and Threats say so at the top of the page.
- ~~Alert delivery measured 11.3 s from packet to index in one sample, over the 10 s goal (NET-243).~~ Fixed 2026-11-11 (PR #247): Filebeat flushes after 2 s, not 10 s; on the G11, 1,019 alerts had a median of 2.0 s and a max of 6.5 s from packet to index.
- The daemon stays host-root-equivalent, as accepted in `SECURITY.md`.
- The owner's public IP is still in git history (F7 fixed HEAD only).

### Release criteria

Each result is for PR #236 (head `a7623897`) unless it says otherwise. `main` before the merge (`446845ec`) fails C3–C5, C8–C11, C13–C17 and C19, as found.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| C1 | Test suites: no new failures vs baseline | **PASS** | Daemon 4,630 passed / 4 skipped / 0 failed (baseline 4,243). Vitest 4,514 passed (baseline 4,303). svelte-check 0 errors. Colour gate, e2e types, ruff and shellcheck clean. bats 277/277. Playwright visual 295 passed (50 skipped by design). CI on PR #236: every job passes, Lint Web included; CodeQL flags two test files that write dummy secrets (alerts #19, #20; owner to triage) |
| C2 | Deployed system identified and traceable | **PASS** | G11 at `a7623897` on `fix/release-audit-2026-11`, clean checkout (smoke test step 1); `main` received the same tree |
| C3 | Connection counts and traffic totals reconcile with source | **PASS** | Two device runs equal to the independent Zeek sum: 13:00–14:00 UTC (1,436,217,196 B) and 17:00–18:00 UTC (4,570,892,146 B). `main` FAIL (R1: interim records summed) |
| C4 | Upload/download direction and bandwidth correct, with units | **UNVERIFIED** | Upload is now what the LAN device sent on either side (B-d), with tests. On the device only totals were reconciled, not the upload/download split. 1,000-based units shown |
| C5 | Device identity and attribution correct for the mode, uncertainty shown | **PASS** | Both sides and IPv6 by MAC reconcile on the G11 (device-A 4,578 = 3,053 + 1,432 + 93). Answer-only devices are listed. Type and OS are shown as guesses with their basis. Global IPv6 not observed |
| C6 | DNS activity reconciles | **PASS** | R6: 5,477 = 5,477 lookups. The median lookup time is shown (smoke test). The page says encrypted DNS is invisible |
| C7 | TLS/certificate data reconciles | **PASS** | R14: 1,416 = 1,416 sessions with a chain |
| C8 | Suricata alerts and severity faithful, worded as rule matches | **PASS** (~~latency goal missed by 1.3 s, NET-243~~ met 2026-11-11, PR #247: p90 4.3 s, max 6.5 s) | Counts exact (R7). Credential-exposure rules ET rates Informational are counted (B-i). Generated text is worded as rule matches (B-j). End to end on the G11 (R15): a LAN request carrying `uid=0(root)` matched ET 2100498 at 19:59:36.27, was indexed at 19:59:47.57 (11.3 s), and the daemon serves it under Activity because ET rates it Informational |
| C9 | Risk/threat scores reproducible from inputs, presented as heuristics | **PASS** (was FAIL P2; fixed 2026-11-11, PR #247) | Deterministic, method shown, inputs persist across restarts (F4). ~~Suppressions and baseline aren't shown (NET-239)~~: the method now gives the suppressed-findings count and whether the busier-window +15 applied, and says when the baseline is still learning |
| C10 | GeoIP/ASN/vendor shown as enrichment, with fitting precision | **PASS** | Answers give their source and age, city-level precision, and anycast with no pin (smoke test on the G11) |
| C11 | Packet search/download right and access-controlled | **PASS** | Daemon 401 without token, web 401 without session (smoke test). The filtered download's temp file is removed (F8) |
| C12 | Capture health reflects a stopped capture and packet loss | **PASS** | NIC loss exact (R11). Failure injection on the G11 (`failure-injection-release.sh`): Suricata stopped → `sensor_stopped` and status "problem" in 1 s; Zeek stopped → the same in 22 s (Zeek takes ~10 s to exit); each back to "fresh" with nobody's help |
| C13 | Storage/retention accurate; current/protected data never deleted | **PASS** (disk full UNVERIFIED) | Disk use counted like `df` (29.6%). Growth is measured, ILM retries, capture resumes after a disk-full pause (tests; smoke test on the G11). Today's index and the newest PCAP are kept (tests). A real disk-full run needs an isolated stack |
| C14 | Every data card distinguishes loading, empty, error, stale, disabled, healthy | **PASS** | Pipeline state beside every "no alerts" (NET-228), partial replies are errors, the Live chip says "Not updating". Checked in local renders and in the visual suite's empty and error modes. Rendered on the G11: Home, Live and Alerts load and show live figures; with Suricata stopped, Home's Capture pipeline card reads "System: Reports a problem" and "Data: Suricata stopped" |
| C15 | No mock, random or hardcoded-success data in production paths | **PASS** | Notifications, Compliance and the Setup storage step fixed (F3, F5, A16); the storage route's dead mock branches removed |
| C16 | No unauthenticated data access, default credentials or committed secrets; privileged surfaces justified | **PASS** | First admin and Go Live need the setup code (A13). Public health carries no hardware detail (F6). On the G11 after the recreate: TShark has no network and runs as nobody (capinfos still reads the newest capture), CyberChef answers 302 to the login (smoke test step 9). Accepted risks are listed in `SECURITY.md`. The owner IP remains in git history |
| C17 | Each capture mode's limits stated in product and docs | **PASS** | Bridge mode says what a post-NAT capture can't show; setup labels each mode by what was tested on hardware (NET-225) |
| C18 | Failures surface in the UI and services recover | **PASS** (~~Alerts gap, NET-242~~ fixed 2026-11-11, PR #247; reboot not run) | G11: each stopped sensor was reported and recovered (C12). An OpenSearch restart turned health to "problem" and came back healthy. Auth survived the restart (cluster green through the service curlrc, Chain 21 confirmed), and ingestion was fresh 2 s after OpenSearch was healthy. The smoke test then passed. Home shows a stopped sensor. Alerts with older alerts listed does not (P2, NET-242). The public web `/api/health` stays "healthy" while OpenSearch restarts: it is a liveness check only (P3). An appliance reboot was not run |
| C19 | No unresolved P0/P1 findings | **PASS** in PR #236; FAIL on `main` before it | No P0. B1–B6 fixed (section 8). A17, the reload 502 found on the device, is fixed and verified (NET-241) |

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
| R15 | Suricata alert end to end (2026-11-09, PR head) | One HTTP request from a LAN client to example.com (IANA-reserved) carrying `uid=0(root)` in a header, sent 19:59:36 UTC; Suricata's own eve.json has the alert at 19:59:36.274 | one alert for ET 2100498, Informational | OpenSearch: one document, `event.ingested` 19:59:47.572; `/api/alerts?activity=true` lists it (severity 2, Informational); the counted list leaves it out (NET-191) | Activity list | PASS; packet to index 11.3 s, over the 10 s goal (NET-243) |

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
| A5 | External notifications don't work in a Docker install and routing rules never fire | env names differ between loader (`NOTIFY_*`), `.env.example` and compose (which forwards none); `notification_hub.process_event` has no caller; alert notifications only fire while a browser has the app open | code | Notifications | **Fixed (wave 2, NET-224)** |
| A6 | Alert suppressions, false-positive marks, baselines and the threat-intel cache are kept in tmpfs and lost on every daemon restart | `NETTAP_DATA_DIR` unset on the G11; `/tmp` is tmpfs | live | Alerts, threat score | **Fixed (F4, NET-233)** |
| A7 | Security posture scores "nothing measured" as 100, grade A, "Excellent" | `compliance/+page.svelte:141-228` | code | Compliance | **Fixed (F5, NET-234)** |
| A8 | PCAP Search "Download filtered" leaves its temp file on a 50 MB tmpfs; downloads fail once it fills | `api/pcap.py:210-211` (`_tmp_path` never read) | code | PCAP Search | **Fixed (F8, NET-236)** |
| A9 | Backup/restore says "Import successful" but skips retention and capture mode | `config_backup.py:39-44` reads `retention_config.json`/`capture_config.json`; the daemon uses `retention.json` and `capture-mode.conf` | code | Settings › Backup | **Fixed (wave 2, NET-227)** |
| A10 | Inline bridge (post-NAT): Devices shows only the router, DNS says devices "made no DNS queries", threat score charges internet noise at full weight; empty states promise devices will appear | DEV-1, DNS-1, ALR-3 | agent; not testable here | bridge mode (advertised) | **Fixed in copy (wave 2, NET-225)**; no bench run |
| A11 | Device totals count only connections the device started; servers (NAS, media server) and responders are understated, unlabelled | live: 111 connections to this Mac omitted; `devices.py:605-620` | live | Devices, Top devices | **Fixed (wave 2, NET-226)**, reconciled live |
| A12 | Device views are IPv4-only; IPv6 traffic of dual-stack devices is missing while the MAC page includes it | `excluded_ips.py:299-315` | agent | Devices | **Fixed (wave 2, NET-226)** |
| A13 | First host to reach a fresh install can create the admin account (no setup code) | `hooks.server.ts`, `setup/+page.server.ts` | agent (security) | install/first run | **Fixed (wave 2, NET-229)** |
| A14 | TShark runs as root, parses attacker-crafted packets, and shares a Docker network with services that trust identity headers | NT-02 | live (confirmed on the G11) | container isolation | **Fixed in compose (wave 2, NET-229)**; needs the TShark recreate |
| A15 | ILM policy failure at startup is never retried and Settings still shows "Policy synced" | STO-2 | agent | retention | **Fixed (wave 2, NET-237)** |
| A16 | Setup Storage step shows invented disk figures when the daemon is down | HON-8/STO-8 | agent | setup | **Fixed (wave 2, NET-237)** |
| A17 | A full reload of any large page while logged in is a 502 Bad Gateway. Client-side navigation still works, which hid it | SvelteKit's `Link` preload header is 4.3–4.8 KB on Home, Alerts, Live and Connections (also on `main`); nginx's default 4 KB `proxy_buffer_size` logged "upstream sent too big header" | live | Home, Alerts, Live, Connections, Logs, IoT on reload | **Fixed (wave 3, NET-241)**, verified on the G11 |

### P2 — misleading presentation, edge cases, recoverable reliability defects (selected)

| ID | Finding | Verified | Outcome |
|---|---|---|---|
| B-a | Unauthenticated `/api/health` returns drive model/serial, storage and SMART | live | **Fixed (F6, NET-235)** |
| B-b | Setup's final check says "NetTap daemon · Running" when the daemon is down (`/api/health` is always 200) | code | **Fixed (F6, NET-235)** |
| B-c | The owner's real public IP is committed as a placeholder (Settings, comments, tests; also in history) | live | **Fixed in HEAD (F7)**; history unchanged |
| B-d | Upload/download = connection originator, so inbound flows (port forwards, P2P, servers) read backwards (TRF-4) | live (semantics) | **Fixed (wave 2, NET-226)** |
| B-e | Live page "Right now" can't show long-running connections (records exist only after they end) (TRF-1) | code | **Fixed (wave 2, NET-237)** |
| B-f | Partial-shard OpenSearch replies shown as complete totals (TRF-3, ALR-11) | agent | **Fixed (wave 2, NET-237)** |
| B-g | GeoIP: city centres shown to ~11 m with a map pin; no database age/source; daemon can't open MaxMind (`maxminddb` missing); query errors cached as "Unknown" (GEO-2/3/4) | agent + live (anycast without country) | **Fixed (wave 2, NET-237)** |
| B-h | Device type/OS are substring guesses shown as fact (DEV-7/8/9); IoT trust and isolation grades claim health from unseen inputs (DEV-10/11) | agent | **Fixed (wave 2, NET-226, NET-237)** |
| B-i | Severity-1 Suricata rules tagged "Informational"/"Unknown" by ET are moved out of the alert count (cleartext Basic-Auth password, `.htpasswd` access) without saying so on the page | live | **Fixed (wave 2, NET-228)** |
| B-j | Alert/explanation text states compromise as fact ("IMMEDIATE: Isolate", "Only this device triggers this alert") (HON-15, ALR-6, ALR-14) | agent | **Fixed (wave 2, NET-228)** |
| B-k | DNS pages don't say DoH/DoT is invisible; mean RTT shown, median hidden (DNS-1/3) | agent | **Fixed (wave 2, NET-225)** |
| B-l | Capture can stay stopped after a disk-full event (stop 95%, delete to <90%, resume <85%) (STO-1) | code | **Fixed (wave 2, NET-237)** |
| B-m | Retention estimate uses a fixed 1.2 GB/day (actual 1.7–2.8 GB indices + ~63 GB PCAP/day on the G11) | live | **Fixed (wave 2, NET-237)** |
| B-n | Setup wizard: "Inline bridge — sees all WAN traffic" omits that devices become indistinguishable; DHCP gateway "Recommended" though untested on hardware | code | **Fixed (wave 2, NET-225)** |
| B-o | Daemon on 0.0.0.0:8880 (token-protected), daemon is host-root-equivalent (docker.sock, SYS_ADMIN, writable systemd dir), capture containers root with NET_ADMIN; images pinned by tag not digest; CyberChef served without login | live + agent | **Partly fixed (NET-229)**: TShark isolated, CyberChef behind the login; the rest accepted in `SECURITY.md` |
| B-p | Error replies include internal exception text (OpenSearch URLs, connection errors) | local | **Fixed (wave 2, NET-229, NET-237)** |
| B-q | With a sensor stopped, Alerts lists the window's older alerts and never says the IDS isn't running; only Home's Capture pipeline card and System do, and the sidebar capture chip stays green | live | **Fixed (NET-242, PR #247)**: Alerts and Threats show "Data pipeline now: Suricata stopped" at the top; G11 health read `sensor_stopped` within 20 s of a stop (2026-11-11). The sidebar chip is unchanged |
| B-r | Alert delivery: 11.3 s from packet to index in one sample, over the 10 s goal (H5) | live | **Fixed (NET-243, PR #247)**: cause was Filebeat's 10 s memory-queue flush timeout; set to 2 s. G11 after: median 2.0 s, p90 4.3 s, max 6.5 s, none over 10 s (before: 22.5% over) |

### P3 (selected)

Docs drift (component versions, "alert-triggered PCAP"); 17 documents with 1970 timestamps in `arkime_sessions3-700101`; Live page keeps its "Live" badge while every request fails; GeoLite fallback table names fixed cities for anycast services; shellcheck's 26 pre-existing warnings; the public web `/api/health` says "healthy" while OpenSearch restarts (it is a liveness check; `/api/system/health` reports the problem).

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

### 6.2 Wave 2: the six blockers and the P2 list (2026-11-09)

The same branch, in about 110 further commits. Each area was fixed in its own worktree, reviewed (Codex plan gate for the larger areas, ponytail, then a security, TypeScript and Python review of the combined branch and a delta round on its fixes), and cherry-picked in. Every new test failed on the code before its fix.

| Area | Findings | What changed | Linear |
|---|---|---|---|
| Notifications | A5 (B1) | The daemon sends alert notifications itself: a dispatcher polls new Suricata alerts every minute, routes them by the rules, and keeps its state across restarts, so no browser needs to be open. One set of env names, forwarded by compose and copied by the installer. Settings save through the daemon, secrets are never returned, every send has a deadline and records why it failed (SMTP deadline covers greeting and QUIT; Telegram gets plain text; each service gets text within its limit). Each channel gets at most 100 alert messages a day, failed sends don't count, and the last one says so first. A restore goes through the running hub, validated; a restored channel that sends somewhere new comes back off. In-app notifications persist and repeat a batch at most once a day; a daemon error passes its status on | NET-224 |
| Inline bridge honesty | A10 (B2), B-k, B-n | Devices, Threats, IoT, the device risk score and Go Live say what a post-NAT capture can't show (one router address, no per-device DNS, no smart-home grades). Setup labels each mode by what was tested on hardware. DNS shows the median lookup time and says encrypted DNS (DoH/DoT) is invisible; its suspicious-pattern thresholds scale with the window. The capture-mode store keeps "unknown" as unknown and retries | NET-225 |
| Device accounting | A11, A12 (B3), B-d, B-h | Device figures count both sides of a connection; upload is what the device sent on either side. IPv6 folds into the device whose MAC it carries (a router's MAC keeps only link-local). Devices that only answer are listed. Network totals add LAN-side upload, download and local bytes, so inbound flows no longer read as upload. Type and OS read as guesses with their basis. The monthly cap leaves out local traffic. Figures that still count only started connections say so | NET-226 |
| Backup and restore | A9 (B4) | Backup and restore use the files the daemon really reads, without secrets. A backup that fails validation restores nothing. The page says what was restored, skipped (and why) and failed, and asks before restoring a different capture mode. Excluded IPs keep NetTap's own; a setup re-run keeps the PCAP rotation size; a restored bandwidth cap is bounded | NET-227 |
| Alerts honesty | A2 rest (B5), B-i, B-j | Every "no alerts" message shows the data pipeline's state beside it, as do the device page and the sidebar badge (which now shows a failed count instead of hiding it). Generated text, kill chains and blocklist hits are worded as rule matches with their source, never "confirmed malicious". Credential-exposure rules that ET rates Informational or Unknown are counted. Trends compare two equal, settled windows, or say they can't | NET-228 |
| First run and containers | A13, A14 (B6), B-o, B-p | Creating the first admin, and Go Live, need a one-time setup code that the installer prints (about 59 bits, single use, constant-time compare, file mode 600). The right code always works; after 50 wrong codes, further wrong ones get a 429, so no LAN host can lock setup. TShark has no network and runs as nobody; CyberChef needs a NetTap session (both take effect only once those containers are recreated, see section 9). Deliberate 5xx replies are marked public at the source, with an AST guard in the tests, and other 5xx replies carry only safe fields. The installer's firewall lets nettap-web reach the daemon. `SECURITY.md` lists the accepted risks with reasons | NET-229 |
| Data-layer honesty | A15, A16, B-e, B-f, B-g, B-h, B-l, B-m, P3 | ILM retries with backoff and Settings says why it is out of sync. Capture resumes after a disk-full pause, and the chip says it is paused. Disk use is counted like `df`. Retention estimates come from measured growth, or "No estimate yet". Partial, timed-out and capped replies are errors, not low figures. The live window counts connections by when they ended, and says so. GeoIP answers give their source and age, city-level precision, mark anycast, never cache an error, and show an offline map where the CSP blocks the frame. IoT grades only what was observed. The Live chip says "Not updating" while polls fail. CONTRIBUTING lists Ubuntu 22.04 or 24.04 | NET-237 |

**Measured on the G11 (read-only, against the running stack).** For one hour, device-A (a server behind a port forward):
- both-sides query: 5,075 connections and 2,193,024 B, equal to independent sums;
- deployed API: 720 connections and 168,900 B.

Query costs:
- device list in OpenSearch: 24 h 0.40 → 0.53 s, 7 d 1.9 → 2.2 s;
- Home's 7 and 30 day series: about 0.5 → 1.4–1.9 s;
- the answer-only device search: 130–210 ms;
- the PCAP growth scan: 44–48 ms for 3,620 files, now shared between polls for 10 minutes.

Other effects:
- df-style disk use reads 29.6% where NetTap showed 28.4%;
- counting the credential-exposure rules adds 13 alerts over 30 days.

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

**On the device:** see section 6.3.

<!-- OLD TEXT START — before the device runs
**Verified on the device: none yet.** The read-only smoke test on `main` gives 16 PASS / 2 FAIL / 1 WARN. The fails are F1 and F6; the warning is F2's missing pipeline check.

After deploying the branch, all three should pass:
    bash scripts/remote/deploy-release-audit.sh
OLD TEXT END -->

### 6.3 Wave 3: the device checks (2026-11-09, owner-approved)

The G11 runs the PR head. Each step had the owner's approval, and none touched the network path.

| Step | Result |
|---|---|
| TShark and nginx recreate (`deploy-release-audit-isolation.sh`) | `nginx -t` and the compose file valid. capinfos opens the newest capture as uid 65534. Smoke test 28/28 |
| Failure injection (`failure-injection-release.sh`) | <ul><li>Suricata stopped: `sensor_stopped` and "problem" in 1 s; fresh 27 s after the restart.</li><li>Zeek stopped: the same in 22 s; fresh again.</li><li>OpenSearch restart: health "problem" during it, docker health back in about 70 s, cluster green through the service curlrc (auth intact, Chain 21), pipeline fresh 2 s later.</li><li>Smoke test after it all: 28/28.</li></ul> |
| Rendered UI | <ul><li>The first full reload while logged in was a **502** (A17). nginx: "upstream sent too big header". Fixed by `proxy_buffer_size 16k` and `proxy_buffers 8 16k` (`edfdd9a9`, NET-241); the bats test fails on the old config.</li><li>After the fix, full reloads of Home and Live render.</li><li>With Suricata stopped for 76 s: Home's Capture pipeline card read "Data: Suricata stopped". Alerts said nothing (B-q, NET-242).</li></ul> |
| Benign IDS trigger | <ul><li>The planned `testmynids.org` request never left the LAN: its DNS filter answers `0.0.0.0` for that name, and the audit doesn't bypass the owner's filter.</li><li>The same signature went in a request header to example.com (IANA-reserved) instead (R15). The alert was indexed in 11.3 s (B-r, NET-243).</li></ul> |
| Final smoke test (with the nginx log check) | **29 PASS / 0 FAIL / 0 WARN** |

Not run: an appliance reboot, stopping Logstash or Filebeat, a disk-full run.

---

## 7. Capture-mode capability and limitations

Tested = observed on the G11 in this audit. Code = traced in code and unit tests only; no hardware run.

| Feature | Mirror / SPAN (tested, G11, LAN-side mirror) | Inline bridge (code only) | DHCP gateway (code only; README: "Not yet tested on real hardware") |
|---|---|---|---|
| Sees internet traffic of LAN devices | Yes, if the mirrored port carries it (router uplink here) | Yes, all WAN traffic | Yes, for devices that took a NetTap lease |
| Per-device attribution | Yes (pre-NAT addresses + MACs) | **No**: post-NAT, every device is the router's IP. On the branch, Devices, DNS, IoT, Threats and the risk score say so (NET-225); `main` implies per-device views (DEV-1, DNS-1, ALR-3) | Yes, by NetTap-issued address |
| Device-to-device (LAN↔LAN) | Only flows that cross the mirrored port; switch-local traffic is invisible | No | No (bypasses NetTap) |
| Static-IP clients | Yes if their traffic crosses the mirror | As router IP | **Bypass NetTap** |
| IPv6 | Captured; on the branch device views add IPv6 by MAC (NET-226); `main` is IPv4-only (DEV-2) | Post-NAT/prefix only | **Bypasses NetTap** when the router sends RAs (Go Live warns) |
| Asymmetric routing | Depends on mirror config (one direction missing → `missed_bytes`, half-flows) | n/a (single path) | n/a |
| Capture loss visibility | NIC counters only (0.005% observed) | br0 counters (virtual) — physical-port drops not counted (HLT-2) | NIC counters |
| Encrypted content | Not decrypted (metadata only; TLS 1.3 hides certificates — stated) | same | same |
| Effect if NetTap fails | None on the network | Kernel bridge keeps forwarding (stated) | Devices lose internet when leases expire (Go Live warns) |
| Wording in setup wizard | "See traffic per device on the LAN" — fair | `main` omits that devices become indistinguishable; the branch says so and that the mode is untested on hardware (NET-225) | `main` says "Recommended" though untested; the branch labels it by what was tested (NET-225) |

---

## 8. Remaining release blockers

Parent issue NET-223. Each blocker was an unresolved P1 on `446845ec`. All six are fixed on the branch (section 6.2). What still stands between the branch and a release is in the last column and in section 9.

| # | Blocker | Linear | What was required | On the branch |
|---|---|---|---|---|
| B1 | External notifications can't be configured in a Docker install; routing rules never fire; alert notifications need an open browser | NET-224 | One config contract and server-side dispatch | **Fixed.** No channel is configured on the G11, so no real send was made; a send to a real channel is UNVERIFIED |
| B2 | Inline bridge (post-NAT): device, DNS and threat views claim what NetTap can't see | NET-225 | Mode-aware copy and empty states; wizard states the NAT limit; a bench run | **Fixed in copy and tests.** The bench run is still UNVERIFIED |
| B3 | Device totals omit responder traffic and all IPv6 | NET-226 | Count both sides, add IPv6 | **Fixed**, reconciled on the G11 (5,075 = 5,075). Global IPv6 is UNVERIFIED (ULA only here) |
| B4 | Backup/restore reports success but skips retention and capture mode | NET-227 | Back up the real files; report what was restored | **Fixed.** A restore on the device was not run (it rewrites live settings) |
| B5 | Alerts/Threats/Compliance say "no threats" / "clean" without the pipeline check beside them | NET-228 | Pipeline state with every "no alerts"; "no rule matched" wording | **Fixed** |
| B6 | First host on a fresh install can claim the admin account; TShark not network-isolated | NET-229 | One-time setup code; `network_mode: none` for TShark | **Fixed**, verified on the G11 after the recreate (smoke test step 9) |
| B7 | A full reload of a large page while logged in is a 502 (found on the device in wave 3) | NET-241 | Header buffer that fits SvelteKit's `Link` header | **Fixed**, verified on the G11 (reloads render; smoke test step 7) |

Also required by the existing gate in `RELEASE-VERIFICATION.md`, still open: hardware checks H2–H4, H6 and H7 (H5 now passes on the G11: p90 4.3 s after NET-243), release notes, and the version bump.

---

## 9. UNVERIFIED areas

| Area | Why unverified | What would resolve it |
|---|---|---|
| ~~Rendered live UI on the G11~~ | **Resolved 2026-11-09:** the owner accepted the certificate and signed in. Home, Live and Alerts render; a stopped sensor shows on Home (section 6.3). The check found A17, now fixed | — |
| Inline bridge and DHCP gateway on hardware | No bench; G11 runs mirror mode on the live home network | Isolated two-NIC bench (modem → NetTap → router) per mode |
| IPv6 internet traffic | Test network has only ULA/link-local IPv6 | A network with global IPv6, or an IPv6 PCAP fixture replayed into an isolated stack |
| ~~A benign IDS trigger end to end~~ | **Resolved 2026-11-09** (R15): alert end to end, 11.3 s packet to index; the 10 s goal is NET-243 | — |
| ~~Failure injection: Suricata, Zeek, OpenSearch restart, role mapping surviving a restart~~ | **Resolved 2026-11-09** (section 6.3) | — |
| Stopping Logstash or Filebeat, an appliance reboot, the role mapping surviving a container *recreate* | Not run in the approved window (a reboot takes the whole box down; a recreate of OpenSearch resets its filesystem) | An owner-approved reboot, then `bash scripts/remote/smoke-test-release.sh` |
| Disk full / near full | Must not be done on the live box; no isolated stack with a small disk | Isolated VM with a small data disk |
| Malcolm update failure and rollback | Disruptive | Isolated stack |
| ~~Index retention (today's index protected)~~ | Resolved 2026-11-09: manual cleanup and PCAP pruning already had tests; `test_prune_emergency_never_deletes_todays_index` now pins the emergency prune | — |
| 500 Mbps zero-loss, <1 ms added latency (bridge) | No bench | iperf3 through a bridge bench (H3) |
| Fixes F1–F8 on the device | **Resolved 2026-11-09:** deployed with the owner's approval; smoke test 19 PASS / 0 FAIL / 0 WARN; F4 migration ran inside the container (baselines moved, present after the recreate) | — |
| Wave-2 fixes on the device | **Resolved 2026-11-09:** `fa2c2984` deployed (web UI and daemon), smoke test 26 PASS / 2 FAIL / 0 WARN; the daemon log has no errors, and no notification channel is configured, so nothing was sent | — |
| ~~TShark isolation and CyberChef's login on the device (NET-229)~~ | **Resolved 2026-11-09:** recreated with the owner's approval; smoke test 28/28, then 29/29 with the nginx fix | — |
| A real notification send (NET-224) | No channel is configured on the G11; the owner's addresses and credentials aren't the audit's to enter | Owner sets up one channel in Settings › Notifications and presses Test |
| A backup restore on the device (NET-227) | A restore rewrites live settings | Isolated stack, or the owner restores a backup taken just before |
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
| 7 | Web API refuses requests without a session; public `/api/health` carries no hardware detail; nginx never cut off a page's headers (NET-241) | any fails |
| 8 | Disk use (info); storage status | capture paused for disk, ILM out of sync, or no growth estimate |
| 9 | Blocker fixes: notification settings carry no secret; DNS median; alert trend values; no setup code once an admin exists; TShark has no network and runs as nobody; CyberChef needs a login; GeoIP marks anycast and names its source | any check fails |
| 10 | Device-A's connections counted from both sides (started + answered + IPv6 by MAC) against independent sums | totals differ |

Results:
- `main` (`446845ec`), 2026-11-09, steps 1–8: 16 PASS, 2 FAIL (step 6, and the hardware detail in step 7), 1 WARN (step 5 pipeline).
- Branch at `e3391970` (wave 1): 19 PASS.
- Branch at `fa2c2984` (wave 2): 26 PASS, 2 FAIL. Both FAILs are in step 9 and clear once TShark and nginx are recreated.
- After the recreate (`fc42d424`): 28 PASS, also after the failure injection.
- PR head `a7623897` (wave 3, with the nginx check): **29 PASS / 0 FAIL / 0 WARN**.

Before tagging a release, also run:
- the Dev suites: daemon pytest, vitest, svelte-check, `npm run check:colors`, `npm run test:visual`, bats;
- a full reload of Home while logged in (the smoke test's own web checks are unauthenticated);
- a benign IDS trigger from a LAN client: a request whose header carries `uid=0(root)` to any HTTP site (ET 2100498, listed under Activity), checking the alert is indexed in under 10 s (H5). A DNS filter may block `testmynids.org`.
