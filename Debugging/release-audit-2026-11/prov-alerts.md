# NetTap release audit: alerts, severity, detections, threat and risk scores

Repo: `.claude/worktrees/release-audit` at `446845ec`. Production code only. Paths are relative to the repo root.
`AI` = `daemon/services/alert_intelligence.py`, `AF` = `daemon/services/alert_findings.py`, `AA` = `daemon/api/alerts.py`.

Scope note: Home (`web/src/routes/+page.svelte`) has **no threat score**. It shows the Alerts KPI, the "Alert summary" card (severity gauge + top smart-alert groups) and nothing else from this slice. The threat score appears on `/threats` (KPI) and `/alerts` ("Threat summary" ring).

Common query base ("counted alerts"): index `arkime_sessions3-*` (`OPENSEARCH_NETWORK_INDEX`), `@timestamp` in [from, to] (`strict_date_optional_time`, ISO from the browser, UTC), `event.provider:suricata`, `event.dataset:alert`, must_not `rule.name` prefix `"SURICATA "` and must_not `suricata.alert.metadata.signature_severity ∈ {Informational, Unknown}` (AA:59-80, AA:154-179). Default window 24 h (AA:40, AA:91-121).

---

## Part 1. Provenance table

| Item | UI location | Producer & source fields | Index / fields queried | Query (filters/agg/size/window/tz) | Backend calc | Frontend format & units | Refresh/freshness | Class | Absent/stale/error behaviour |
|---|---|---|---|---|---|---|---|---|---|
| Alerts KPI total | Home KPI "Alerts" (+page.svelte:711-721); sidebar badge; Alerts page tiles | Suricata EVE alert docs (Malcolm Logstash) | `arkime_sessions3-*`: `@timestamp`, `event.provider`, `event.dataset`, `rule.name`, `suricata.alert.metadata.signature_severity`, `suricata.alert.severity` | counted base; `size:0`, `track_total_hits:true`, terms `suricata.alert.severity` size 10; window = shared snapshot rounded to the minute (alertSnapshot.ts `snapshotWindow`) | `hits.total.value` (AA:754-838). **Not passed through `checked()`**: a timed-out or partly failed reply is accepted (AA:798) | `formatNumber` compact; trend vs previous equal window (`trendPercent`, home.ts:69-79), up = bad | Home 30 s auto (+page.svelte:238-246); shared store per window (alertSnapshot.ts) | Suricata rule match | Error: last good value + stale note (+page.svelte:487-493, alertSnapshot.ts catch). Partial shard failure: silently lower (ALR-11). No data: 0 |
| Alerts KPI sub "N high, N med, N low" | Home KPI sub (+page.svelte:487-493) | `suricata.alert.severity` (classtype priority 1/2/3) | same | terms agg | 1→high, 2→medium, 3→low, other→`severity_N` key (AA:811-827) | `fmt()` | same | Suricata priority (not threat) | as above. Label never says "Suricata priority" (ALR-5) |
| Severity gauge | Home "Alert summary" (+page.svelte:822-830); Alerts "Alerts by severity" (alerts/+page.svelte:1368-1388) | same | same | same | `severityBuckets`: info = total − (h+m+l) (lib/utils/severity.ts:37-47) | SeverityGauge high/medium/low/info | same | Suricata priority | Error: stale note or error card |
| "N to review · M not counted" | Home Alert summary sub (+page.svelte:610-618) | Smart summary | counted base + activity partition (`signature_severity ∈ {Informational,Unknown}`) | full composite of (rule.name, source.ip, destination.ip), page 1,000, cap 500,000 groups (AI:1312-1361) | `total_events` = Σ `counted_events`; `informational_events` = Σ all group counts − counted (AI:1785-1810) | compact numbers | 30 s | NetTap reclassification | Summary failed: clause hidden (+page.svelte:610). Suppressed alerts vanish from both figures (ALR-9) |
| Top alert groups (pill, category, ×N, signature) | Home Alert summary (+page.svelte:831-859) | Suricata alert; NetTap `reclassify_severity`, `categorize_alert` | counted base, composite on `rule.name`,`source.ip`,`destination.ip`; top_hits `_source` `alert, rule, suricata.alert, suricata.severity, destination.port` (AI:1316-1322); findings query (AF:106-140) and Zeek conn spans (AF:143-232) | all groups computed, `limit=10` applied after sort `(severity, -count)` (AA:2096-2147, AI:1701) | group severity = reclassified base (AI:1602-1608); reputation groups = min finding severity (AI:1620-1632); category = substring match (AI:773-780) | `SeverityPill smartLevel` 1 critical…4 low (severity.ts:27-32); `×count` | 30 s | NetTap reclassification of Suricata matches | Error: "Couldn't load the alert summary" (+page.svelte:854-856). Empty & loaded: **"No actionable alerts detected."** (+page.svelte:858) even when Suricata is not producing alerts (ALR-1) |
| Alert list rows (time, severity, signature, src, dst, proto, category, Acknowledged) | Alerts page "All alerts", category page list | EVE alert doc | counted (or activity) base + filters; sort on mapped field (AA:413-438) | `size ≤200`, `from` paging to 10,000 window, `track_total_hits` (AA:441-751) | `_normalize_alert_source` merges `alert.*`/`rule.*`/`suricata.alert.*` (AA:254-345); severity default **3 (low)** if missing (AA:348-374); enrichment text (alert_enrichment.py) | `suricataLevel` 1 high/2 medium/3 low/else info (severity.ts:22-24); local time | on load/refresh | Suricata match | 502 on OpenSearch/QueryFailed → error card. Missing severity reads "Low" here but "Info" in counts (ALR-15) |
| Activity count "N informational events not counted" | Alerts page (alerts/+page.svelte:1389-1393) | ET `signature_severity` Informational/Unknown | activity base (AA:154-179) | `/api/alerts/count?activity=true` | same as count (unchecked) | `fmt` | page refresh | ET metadata | Failed: keeps last |
| Timeline (high/medium/low/info per slot) | Alerts page "Alert timeline" | Suricata priority | counted base | `time_slots` date_range, UTC epoch-aligned slots; terms severity size 5 (AA:950-1040) | info = slot doc_count − h − m − l | local labels | page refresh | Suricata priority | OpenSearch error → 502. **Reply unchecked** (AA:1016) |
| Top signatures | Alerts page | `rule.name`, primary `suricata.alert.severity` | counted base | composite page 5,000, cap 50,000, checked (`what=`) (AA:1063-1224) | sort by count; `complete`/`examined` returned | partial note shown | page refresh | Suricata match | QueryFailed → 502; cap disclosed |
| Top source / destination IPs | Alerts page | `source.ip` / `destination.ip` | counted base | as above (AA:1227-1321) | | links to address/device page | page refresh | Suricata match | as above |
| Alert categories (count, trend, sub-cats) | Alerts page "Alert categories" (alerts/+page.svelte:1564-1580); `/alerts/[category]` | NetTap substring categories over `rule.name` | counted base; per-signature terms severity + `time_slots` sparkline | `_every_signature` composite, page 100, cap 500,000, **unchecked, cap only logged** (AA:1330-1349, AA:1445-1670) | `categorize_alert` substring (AI:773-780); trend second half vs first half ×1.5 | BarList | page refresh | NetTap heuristic over Suricata names | Error → card. Reputation hits counted under "Malware & C2" (ALR-7) |
| Threat score + level | Threats KPI (threats/+page.svelte:505-522); Alerts "Threat summary" ring (alerts/+page.svelte:1536-1562) | Smart summary | as smart groups + baseline file | full window | Part 2 formula (AI:1754-1901, 1904-1935) | `value/100`, SeverityPill level; "How the score is worked out" text (lib/api/alerts.ts:500-501) | Threats: on load/range change; Alerts: page refresh | NetTap heuristic | Request error → error card, never 0 (threats/+page.svelte:487-498; alerts/+page.svelte:1540; alerts.ts throws). **Empty data (Suricata dead) → 0 / "No threat level"** (ALR-1) |
| Baseline note "N× above/vs baseline" | Threats KPI note (threats/+page.svelte:512) | `nettap-baselines.json` in daemon `/tmp` (tmpfs) | none (file) | ≥6 earlier hourly snapshots, same window length, last 7 d (AI:1160-1229) | deviation = rate / max(avg_rate, 1/window) | "1.0× vs baseline" | written once per clock hour on live network-wide requests | NetTap heuristic | <6 points: shows "1× vs baseline" though no baseline exists (ALR-13). Reset on every daemon restart (ALR-9) |
| Alert groups KPI, "N alert events need attention" | Threats KPI + brief (threats/+page.svelte:191-199, 523-528) | Smart summary `total_groups`, `total_events`, `informational_events` | as above | | groups with severity < 5 (AI:1784) | compact | on load | NetTap reclassification | 0 groups → **"No actionable threats detected."** (threats:195) |
| Category stack bar | Threats "Threat brief" | `categories[*].events` | | | Σ counted_events per substring category (AI:1812-1827) | StackBar | on load | heuristic | hidden when empty |
| Kill chains | Threats KPI + "Active kill chains" (threats:529, 610-650) | Smart groups `with_times`, per finding instants | as findings | per device: stages 1–4 from category, strictly increasing, ≤24 h steps, ≥2 stages, ≥1 own-traffic step; reputation and severity-5 excluded; attempts only stages 1–2 (AF:532-645) | `assessment` "…possible active intrusion." (AF:636-641) | chips "Stage N · Detected/Not seen" | on load | NetTap behavioural correlation of Suricata matches | Empty → "No active kill chains". Depends on substring categories (ALR-7) and Zeek attribution (ALR-10) |
| Beaconing | Threats KPI + card (threats:530-537, 690-760) | Zeek conn | `event.provider:zeek`, `event.dataset:conn`, must_not dest in NOT_INTERNET_CIDRS / ports 53,67,68,123,137,138,1900,5353,5355 (threat_detection.py:471-565) | candidate pairs (src,dst,port) ≥10 conns (multi_terms size 50,000 or paged); 10 s slots per pair | ≥10 slots, mean Δ > 5 s, CV < 0.15 (threat_detection.py:333-366); confidence = CV band 50/35/20 + count band 30/20/10 + 20 if near a common interval (144-166); ≥10 scheduled hosts → "many_hosts", not a suspect (393-420) | table, "Confidence N%" Meter (threats:465) | background snapshot 15 min (24 h/7 d), 60 min (30 d); "checked HH:MM"; stale/failed/pending states (beacon_snapshots.py) | NetTap behavioural heuristic | Failed → "—"/error; pending → "checking…"; partial cap → notice. **Live-path replies unchecked** (threat_detection.py:257, 397, 411) |
| DNS anomalies | Threats "DNS anomalies" | Zeek dns `zeek.dns.query`, `zeek.dns.rcode_name`, `source.ip` | `event.dataset:dns` minus `DNS_LOOKUP_EXCLUSION` | all names + all sources, unchecked `all_buckets` (threat_detection.py:776-783) | DGA: label entropy > 3.8 and len > 8; tunnel: subdomain > 50 chars; NXDOMAIN: > 50 queries and > 40% NXDOMAIN (708-900) | up to 5 each | on load | heuristic | failed → error card; cap → note |
| Lateral movement | Threats "Lateral movement" | Zeek conn on 13 admin ports between RFC1918 hosts | `source.ip`/`destination.ip` ∈ RFC1918, port list (570-705) | unchecked `all_buckets` (640) | every pair listed; fan-out > 2 → "WARNING: possible lateral movement" | top 8 by fan-out | on load | heuristic | failed → error card |
| Auto-investigations | Threats "Auto-investigations" (threats:782-880) | top 3 smart groups with severity ≤ 2 (investigation.py:338) | Zeek conn: host profile `now-24h`, pair history `now-7d` (investigation.py:57-172) | unchecked searches (87, 151) | `_generate_recommendation` by group severity/category (175-205) | "What to do" box (threats:867) | on load | NetTap heuristic | failure → `failed_checks` chip/notice |
| Threat intel matches | Threats card (threats:540-605) | Suricata reputation-rule alerts only | `rule.name` wildcards `*COMPROMISED*`,`*DROP*`,`*CINS*`,`*Dshield*`; `source.ip`,`destination.ip` (threat_intel.py:57-66, 261-388) | composite page 10,000, unchecked, cap only logged (349-364) | listed endpoint = the one global address of the pair (71-78); merged into cache feed `et_compromised` forever (390-399) | BarList per "feed", label "ET Compromised IPs" | every Threats load (GET with side effect) | Suricata reputation rules re-labelled as threat intel | failed → "Threat intel unavailable"; no date or feed age shown (ALR-12) |
| Address threat-list chip | `/address/[ip]` header (address/[ip]/+page.svelte:527-539) | cache + this window's listing alerts | as above | | `threat_intel()` (api/addresses.py:412-425) | red "On a threat list: ET Compromised IPs" / green "Not on a threat list" | per page load | Suricata reputation rules | None only when alerts unreadable; cache never expires (until daemon restart) (ALR-12) |
| Device risk score + factors | `/devices/[ip]` "Risk score" (devices/[ip]/+page.svelte:842-868); `/compliance` | Smart findings (own traffic only) + Zeek conn history | conn: `source.ip`, `destination.ip`, `source.bytes`, `destination.bytes`, `@timestamp` date_range 7 days + window (api/risk.py:368-432) | checked `all_buckets` (`what=`) | alerts: Σ per distinct own signature 50/25/5/1, cap 50; conn anomaly 10/25 if ≥500 conns and ≥3×/≥5× median day, upload 10/25 if ≥100 MB and ≥3× (25 if ≥1 GB); volume factors only with an own non-reputation high/critical alert; levels 0-24 low, 25-49 medium, 50-74 high, 75+ critical (risk_scoring.py:332-478; api/risk.py:442-480) | Ring /100 + pill + factor bars | page refresh | NetTap heuristic | Failure → error or stale notice, never 0 (devices/[ip]:387-394). 404 when the device opened no connections (api/risk.py:858-862) reads as an error |
| Device smart alerts (assessment, trend arrow) | `/devices/[ip]` "Smart alerts" (devices/[ip]:870-910) | Smart groups `device_ip` | either side = device | | `generate_assessment(..., device_count=1, ...)` (AI:1648-1655, 887-951); `compute_trend` by absolute rate (AI:800-826) | text + Rising/Falling icon | page refresh | heuristic | error → "check failed". Assessment always says "Only this device triggers this alert" (ALR-14) |
| Security posture (6 categories, overall grade, recommendations) | `/compliance` | protocols, alert count, device count, risk scores, investigation stats | `/api/traffic/protocols`, `/api/alerts/count`, `/api/devices/count`, `/api/risk/scores`, `/api/investigations/stats`, all with no window (daemon default 24 h; stats all-time) (compliance/+page.svelte:596-622) | | client-side weights 0.25/0.15×5; empty inputs score 100 (141, 147, 167, 180, 196, 210) | Ring + grade A–F, chips Good/Needs attention/Poor | manual/top-bar refresh | NetTap heuristic | Failed input → "Couldn't compute" (withFailures). **Empty input → 100 / "Excellent"** (ALR-2) |
| In-app alert notifications | Top-bar bell (NotificationBell.svelte) | smart groups | `/api/alerts/smart?limit=50` (24 h) | | per category: notify if worst group severity ≤ 2; "devices affected" = distinct src+dst IPs (routes/api/notifications/from-alerts/+server.ts:7-53) | bell list | on each TopBar mount (NotificationBell.svelte:47-58) | heuristic over Suricata | daemon error → treated as no alerts (from-alerts:8-12). No dedup (ALR-4) |
| Notification routing rules | Settings › Notifications "Routing rules" | NotificationHub rules JSON | none | | `process_event` (notification_hub.py:515-547) has **no caller** | rule list | n/a | config | rules never fire (ALR-4) |
| Suppress / False positive | Alerts list rows, drawer, category page, device page | user action | none | | global (no device) TTL 30 d / permanent FP in `/tmp/nettap-suppress.json` (AI:956-1063); applied only to smart groups/score/risk (AI:1578-1586) | buttons; list reloads unchanged | immediate | user state | lost on daemon restart; no list/undo UI (ALR-9) |
| `/alerts/suricata/[name]` figures | raw Suricata category page | `rule.category`, `rule.name`, IPs, severity | counted base + `rule.category` term | SnapshotSearch PIT, checked, caps disclosed (api/suricata_categories.py) | | "by Suricata severity" (suricata/[name]/+page.svelte:208) | page refresh | Suricata match | correct partial/failure handling |
| `/alerts/[category]` stats | category page KPIs, "Addresses involved" | substring category | counted base | `_every_signature` + `_alerts_by_ip` (unchecked, cap logged) (AA:1673-1937) | sources/targets/addresses incl. internet addresses (label correct: "inside and outside your network") | "Top 20 of N" | page refresh | heuristic | 502 on error |

---

## Part 2. Threat score formula as implemented

Entry: `get_smart_alert_summary` (AI:1754-1901). Callers: `/api/alerts/smart/summary` (AA:2150-2179) and `/api/threats/report` → `generate_threat_report` (investigation.py:278).

1. **Groups.** `get_smart_alerts(..., include_info=True, limit=None, with_times=True)` (AI:1774-1784). Counted partition: base query above (AI:1386-1434). Groups = composite (rule.name, source.ip, destination.ip) (AI:1436-1484). Dropped: `ENGINE_NOISE_SIGNATURES` (AI:81-93, 1542), suppressed/false-positive signatures (AI:1578-1586). Scored set `alerts` = groups with `severity < 5` (AI:1784).
2. **Base severity** `reclassify_severity` (AI:722-740): name starts with `ET INFO|ET HUNTING|ET TOR|ET P2P|ET GAMES|ET CHAT` → 5; else ET `signature_severity` Critical/Major/Minor → 1/2/3 (AI:676-686); else first matching prefix in `SEVERITY_OVERRIDES` (AI:43-79, e.g. ET MALWARE 1, ET SCAN 3, ET POLICY 4, `GPL` 5, `SURICATA` 5); else Suricata priority 1→2, 2→3, other→4. Activity partition → 5 (AI:1606-1607).
3. **Findings** (AF:443-504): each alert-minute with a LAN party (`lan_cidrs`, IPv4 RFC 1918 or detected /24s) is charged to one device by `charge` (AF:412-440); `own` = the device opened the connection per Zeek `conn` history, or (no record / unknown opener) the alert is older than `SETTLE_MS` = 10 min (AF:51, 469-476).
4. **Finding severity** `finding_severity` (AF:507-517): non-reputation → base; reputation (`ET DROP|DSHIELD|CINS|COMPROMISED|TOR|3CORESEC`, AF:24-31) → `max(base, 3)` if own, else 5.
5. **Points** `_finding_points` (AI:1915-1935), weights `W = {1:10, 2:5, 3:2, 4:0.5, 5:0}` (AI:1904):
   - per finding f with severity < 5: key (signature, f.device), w = W[f.severity]; if not own, w = min(w, 0.5) (AF:35);
   - if group `unattributed > 0` and not (reputation and has findings): key (signature, source_ip, destination_ip), w = W[group severity] (no attempt cap). `unattributed` = group count − Σ found counts (AI:1634): IPv6, non-LAN subnets, inline-bridge (post-NAT) traffic, LAN↔LAN client-target alerts with unknown opener;
   - each key keeps its max w; `raw = Σ w`.
6. `threat_score = min(100, int(raw))` (AI:1836) — truncation: a lone 0.5 attempt scores 0.
7. `threat_level = _score_level(score)`: ≥75 critical, ≥50 high, ≥25 medium, ≥1 low, else none (AI:1907-1912, 1849).
8. **Baseline bonus** (network-wide only): `update_baseline(record=live)` (AI:1863-1871; live = window ends within 15 min of now, AI:1074-1085). rate = total_events / window_hours; anomalous if ≥6 earlier hourly snapshots of the same window length in the last 7 d exist and rate / max(avg_rate, 1/window) > 2.0 (AI:1167-1229). If anomalous and score < 75: score = min(100, score + 15), level re-banded (AI:1875-1883). File `$NETTAP_DATA_DIR/nettap-baselines.json`, default `/tmp` (AI:1067-1069) = tmpfs in the daemon container.
9. **Cap**: level lowered to the ceiling of the worst group severity (1 critical, 2 high, 3 medium, 4 low) (AI:1887, 1298-1305).
10. **Zero case**: no group with severity < 5 → `{threat_score: 0, threat_level: "none", …}` (AI:1796-1808). Query failure raises → HTTP 500 (AA:2173-2175); web throws (lib/api/alerts.ts) and both pages show an error card.

Reproducibility: inputs (findings, own/attempt split, unattributed keys, baseline history, suppress list) are not shown in the UI, so the score cannot be recomputed from what the user sees. User-facing text: lib/api/alerts.ts:500-501.

---

## Part 3. Findings

### ALR-1 · P1 · Silent Suricata or ingestion failure reads as "no threats", score 0 and "network looks clean"
- Evidence: zero groups → score 0 / level none (AI:1796-1808); Threats headline "No actionable threats detected." and "No kill chains, beaconing or threat intel matches." (threats/+page.svelte:195, 222); Home "No actionable alerts detected." (+page.svelte:858); Compliance "No alerts detected — your network looks clean" and "Excellent security posture…" (compliance/+page.svelte:369, 556, 688). System health checks storage, SMART and OpenSearch reachability only (daemon/api/server.py:529-579); the Home pipeline covers capture, packets, system, OpenSearch (home.ts:119-170). Nothing checks Suricata liveness, rule load, or the age of the newest `event.provider:suricata` document. A search on a missing `arkime_sessions3-*` pattern returns 0 hits, not an error.
- Failure: Suricata crashes, fails to load rules, or filebeat/Logstash stops shipping eve.json while Zeek keeps running. Every alert page shows zero, threat score 0 "No threat level", Compliance grade can reach A, for as long as the outage lasts.
- Affected UI: Home Alerts KPI and Alert summary, /alerts, /threats, /compliance, sidebar badge.

### ALR-2 · P1 · Security posture page scores missing data as 100 and claims "excellent"
- Evidence: Encryption 100 when nothing eligible (compliance/+page.svelte:141); DNS 100 with no DNS (147); Network 100 with 0 devices (167); Patch 100 with no services (180); Alerts 100 with 0 alerts (196); Monitoring 100 with 0 devices (210); summary "Excellent security posture. Your network follows best practices across all categories." (688); recommendation "posture looks excellent" (556); "your network looks clean" (369). "Network segmentation" (447) and "Monitoring coverage" both use `scoredDevices = min(riskScores.length, totalDevices)` (161), and `/api/risk/scores` scores every LAN device it sees (api/risk.py:537-565), so both are ~100 by construction and measure nothing about segmentation. "Patch currency" (458) is the share of http/ftp/telnet/pop3/imap connections, not patching. "Alert response" is 0 whenever any alert exists and no investigation was opened (201). Inputs use different windows (24 h default vs all-time investigation stats) and no window is shown.
- Failure: fresh install, capture down, or a quiet day: grade A, "Good" chips, "follows best practices". Failed requests are handled correctly (`withFailures`), empty data is not.
- Affected UI: /compliance (KPI chips, radar, overall ring, recommendations).

### ALR-3 · P1 (suspected for bridge mode; confirmed for IPv6) · With no RFC 1918 party, the NET-209 attribution does not apply and the score falls back to the old inflated rules
- Evidence: findings exist only for alerts with a LAN party (`terms source.ip/destination.ip: lan_cidrs`, AF:117-125); the LAN rule is IPv4 RFC 1918 only (services/excluded_ips.py:86-131, 286; api/drilldown_runner.py:78-80). Groups with no findings are scored per (signature, source, destination) at full weight with no attempt cap (AI:1932-1934); reputation groups with no LAN party stay at medium = 2 points each (AI:1627-1632). Default deployment is `CAPTURE_MODE: bridge` (docker/docker-compose.yml:963) between modem and router, where IPv4 traffic is post-NAT: router WAN address ↔ internet only. `listed_endpoint` also returns None for two global endpoints (threat_intel.py:71-78), so Threat intel matches stay empty. The user text says "An attempt from the internet against a device adds at most 0.5, and blocklist hits your devices did not start are not counted" (lib/api/alerts.ts:500-501), which is false for these groups.
- Failure: an inline-bridge box sees all unsolicited internet traffic before the router's firewall (ET DROP/CINS/DShield/SCAN against the WAN IP). Each new scanner address adds 2–10 points; score pins at 100 with level up to high/critical, while kill chains, device risk and threat-intel matches show nothing (no LAN device). The same happens on any IPv6 traffic in mirror mode (documented limitation, not shown in the UI).
- Confirm: on a bridge-mode box, call `/api/alerts/smart?include_info=false&limit=1000` and count groups with empty `findings` and `unattributed > 0`.
- Affected UI: /threats score, level, headline; /alerts Threat summary; Threat intel card.

### ALR-4 · P1 · Alert notifications: routing rules never fire; the only path is browser-triggered, duplicated, and hides daemon errors
- Evidence: `NotificationHub.process_event` (daemon/services/notification_hub.py:515-547) has no caller anywhere in `daemon/` or `web/`. Settings › Notifications offers "Routing rules … Rules send each kind of event to the channels you pick" (web/src/routes/settings/notifications/+page.svelte:395-461). The real path is `NotificationBell` calling `/api/notifications/from-alerts` on every mount (web/src/lib/components/NotificationBell.svelte:47-58) → `sendNotification` per category with no dedup (routes/api/notifications/from-alerts/+server.ts:33-50; web/src/lib/server/notifications.ts:294-343). A daemon 500 parses to `{error}` → `alerts` undefined → `[]` → "0 created" (from-alerts:8-12). "N device(s) affected" adds internet source and destination addresses (26-27). Severity uses group severity, which is not lowered for attempts (ALR-6). In-app store path `/var/lib/nettap` is on a read-only root FS in the web container (docker-compose.yml:1008-1018; notifications.ts:83, writeStore swallows errors), so notifications are memory-only.
- Failure: a user creates "Alert, critical → Discord". A real C2 alert at 03:00 sends nothing. Next morning each tab opened re-sends the same 24 h of categories to email/webhook (env-configured) and the bell.
- Affected UI: Settings › Notifications, bell, email/webhook.

### ALR-5 · P2 · Two severity scales sit side by side, unlabelled; NetTap's reclassification is never shown
- Evidence: Home Alert summary gauge = Suricata classtype priority (1 high/2 medium/3 low) (+page.svelte:825; AA:811-827); group pills in the same card = NetTap reclassified scale with "critical" (+page.svelte:847; AI:722-740). Alerts KPI sub "N high, N med, N low" (+page.svelte:492) and "Alerts by severity" (alerts/+page.svelte:1368) never say "Suricata priority". Smart groups do not return the original Suricata severity, and no screen shows "Suricata: high → NetTap: low". THREAT-SCORING rule 2 (and the code order) treat priority as not a measure of maliciousness, yet it is the headline split.
- Failure: an `ET POLICY` rule with classtype policy-violation (priority 1) shows "High" in the gauge, the KPI and the alert list, and "Low" in the group below it. An ET Major rule with priority 3 shows "Low" in the gauge and "High" in the group.
- Affected UI: Home, /alerts, alert list, drawer, compliance "high-severity alert(s)".
- Not a defect: no inverted mapping was found. Suricata 1 = most severe everywhere (severity.ts:22-24, AA:425-438 sort inversion, AA:1395-1421 `min`, AI:740).

### ALR-6 · P2 · Attempts keep full severity everywhere except the score, so pages disagree and advice targets the attacker
- Evidence: non-reputation group severity = base severity (AI:1602-1608, 1663); findings' `own` is only used inside the score (AI:1928) and device risk. The web never reads `own_traffic`, `findings`, `reputation` or `counted_events` (no reference under web/src outside tests). Auto-investigation picks groups with severity ≤ 2 (investigation.py:338) and says "IMMEDIATE: Isolate the source host from the network." (182) and, for malware_c2, "Check for malware on the source device" (188). For inbound attempts the source is the internet attacker; for many `ET MALWARE … response` rules the source is the internet server. Score truncation `int(raw)` (AI:1836) turns a lone 0.5 into 0 / "none" (AI:1849).
- Failure: a scanner sends a log4j exploit to a port-forwarded server and gets a 405. Home shows a "Critical · Exploit Attempt" pill, the bell raises a "critical" notification, Auto-investigations says to isolate the source host, while the Threats KPI reads 0/100 "No threat level" beside "1 alert events need attention".
- Affected UI: Home Alert summary, /threats KPIs and Auto-investigations, bell, device page smart alerts.

### ALR-7 · P2 · Substring categories mislabel alerts and feed kill chains
- Evidence: `categorize_alert` matches any pattern anywhere in the upper-cased name, first category wins (AI:773-780). Patterns include "DROP" (AI:204), "C2" (199), "RCE" (251), "TOR" (267), "SSN" (151), "DOS". So "ET POLICY Dropbox …" → Malware & C2; "…SOURCE/RESOURCE/FORCE…" → Exploit Attempt (exploit is checked before policy); "…EC2…" → Malware & C2. Category drives the kill-chain stage (`KILL_CHAIN_STAGES` AI:658-663 via AF:532-552), the assessment text (AI:897-922) and the recommendation (investigation.py:186-192). Reputation hits (DROP, CINS, DSHIELD, COMPROMISED, AI:202-206) are counted as "Malware & C2" in the Alerts page category card from raw counts (AA:1575-1580), against rule 8 (a reputation hit is not evidence).
- Failure: a laptop syncing Dropbox (own traffic, counted unless ET rates it Informational) after an inbound ET SCAN attempt against it within 24 h → "2-stage chain … possible active intrusion". Inbound blocklist background makes "Malware & C2" the largest category on /alerts.
- Confirm (suspected part): query counted alerts with `rule.name:*Dropbox*` or names containing SOURCE/EC2 and check `categorize_alert`.
- Affected UI: Home chips and pills, /alerts categories, /alerts/[category], /threats kill chains and brief.

### ALR-8 · P2 · Whole GPL family (and similar prefixes) silently demoted to "not counted"
- Evidence: `SEVERITY_OVERRIDES["GPL"] = 5` (AI:78), applied when a rule carries no ET `signature_severity` (AI:734-739); most GPL rules in ET Open have none. Severity 5 is dropped from smart groups, the score, kill chains and device risk (AI:1643-1644, 1784), but still counted in the raw Alerts KPI ("high" if priority 1/2). THREAT-SCORING lists only ET INFO/HUNTING/TOR/P2P/GAMES/CHAT and SURICATA as context.
- Failure: "GPL ATTACK_RESPONSE id check returned root" (a post-exploitation indicator) on a LAN server never reaches the threat score, Home groups, or the device's risk; it only adds to "M not counted".
- Affected UI: /threats, /alerts Threat summary, Home groups, device risk.

### ALR-9 · P2 · Suppressions, false positives, baselines and the threat-intel cache live in tmpfs; suppression is global, invisible and not undoable
- Evidence: paths default to `/tmp` when `NETTAP_DATA_DIR` is unset (AI:956-958, 1067-1069; threat_intel.py:24-26). The daemon sets no `NETTAP_DATA_DIR` (docker-compose.yml daemon `environment`, Dockerfile.daemon has no ENV) and runs `read_only: true` with `/tmp:size=50M` tmpfs (docker-compose.yml:881-883). Suppress/FP buttons send no device (alerts/+page.svelte:1128-1136), so they are global; FP has no TTL (AI:1014-1027). There is no GET/DELETE route for the list (AA:2227-2256). The raw list ignores suppression, so the row stays after the click. Suppressed alerts disappear from both "to review" and "not counted" (AI:1792), so Home figures no longer add up to the KPI. A failed save is logged and the API still answers "suppressed" (AI:971-982; AA:2200).
- Failure: the owner marks a noisy rule false positive; after the next daemon restart or deploy it is back and the score jumps with no explanation. The baseline restarts empty, so the +15 bonus is impossible for 6 h and the "7-day" average is limited to uptime. A global FP on one device hides that signature on every other device too.
- Affected UI: /alerts, category page, device page, /threats score.

### ALR-10 · P2 · Missing Zeek records turn inbound attempts into "the device's own traffic"
- Evidence: an inbound alert whose conn record is missing or of unknown opener is charged as own once older than 10 min (AF:44-51, 469-476). Own findings score at full weight (AI:1925-1929), feed device risk (api/risk.py:442-480: 50 points per critical signature, "corroborated" enables volume factors) and anchor kill chains (AF:541-552, 599). No screen states the attribution basis.
- Failure: Zeek stops, lags more than 10 min, or drops records (the G11 NIC already drops frames under load). Every inbound exploit attempt older than 10 min is scored as a compromise (10 instead of 0.5), the target server's risk becomes high/critical, and inbound scan + exploit attempts can form a "possible active intrusion" chain.
- Affected UI: /threats score and kill chains, device risk, /compliance.

### ALR-11 · P2 · Several alert and detection queries accept partial OpenSearch replies as complete
- Evidence: no `checked()` / `what=` on: alert count (AA:798), timeline (AA:1016), category timeline (AA:2028), `_every_signature` (AA:1338-1342), `_alerts_by_ip` (AA:1406-1414), beaconing candidates and slots (threat_detection.py:257, 397, 411), lateral movement (640), DNS anomalies (776-783), threat-intel scan (threat_intel.py:349-364), auto-investigation profiles (investigation.py:87, 151), LAN anomaly scans. Compare with the smart summary, which raises (AI:1350-1361), and `snapshot_search.checked` (daemon/storage/snapshot_search.py:65-84).
- Failure: one red or timed-out shard among the daily `arkime_sessions3-*` indices. The Alerts KPI, sidebar badge and compliance read a lower total, categories lose signatures, "No beaconing/lateral movement/DNS anomalies detected" can appear, all with no warning, while the threat summary errors. Caps (500,000 signatures, TI pairs) are only logged.
- Affected UI: Home Alerts KPI, sidebar, /alerts tiles, timeline and categories, /threats cards, /compliance.

### ALR-12 · P2 · "Threat intel" is re-labelled Suricata reputation hits: no real feeds, undated, never expires, and "Not on a threat list" implies a check that did not happen
- Evidence: `TI_FEEDS` names Abuse.ch Feodo, Abuse.ch SSLBL, DShield (threat_intel.py:48-53) but nothing downloads them (module docstring "Future: scheduled feed downloader"). The only populated set is `et_compromised` labelled "ET Compromised IPs", filled from DROP, CINS, DShield and COMPROMISED alerts (57-68, 390-399), so a Spamhaus DROP hit is shown as "ET Compromised IPs". Entries never expire (no TTL; only lost when tmpfs resets, ALR-9); `updated_at` is written (158) but never shown. `*Dshield*` is a case-sensitive wildcard against `ET DSHIELD …` names (63) (suspected miss; confirm the `rule.name` mapping has no lowercase normalizer). Address page: red "On a threat list: ET Compromised IPs" with no date, green check "Not on a threat list" when the address is simply absent from local alerts (address/[ip]/+page.svelte:527-539; api/addresses.py:412-425).
- Failure: an address that hit a DROP rule weeks ago still shows "On a threat list" today; an address on Feodo that no ET rule fired on shows a green "Not on a threat list".
- Affected UI: /threats Threat intel card, /address/[ip] header.

### ALR-13 · P3 · Score saturates, is not reproducible from the screen, and shows "1× vs baseline" with no baseline
- Evidence: the sum is not normalised to the window and caps at 100 (AI:1836), so 7 d and 30 d windows pin at 100 on an ordinary network. Findings, own/attempt split and baseline history are not displayed (Part 2). With fewer than 6 earlier snapshots, deviation stays 1.0 (AI:1216-1221) and the KPI note reads "1× vs baseline" (threats/+page.svelte:512). Labelled "Higher is riskier", not as a heuristic.
- Affected UI: /threats KPI, /alerts ring.

### ALR-14 · P2 · Generated text states compromise or targeting as fact
- Evidence: alert drawer text (via alert-view.ts:17-29): "Trojan horse communication detected" (alert_enrichment.py:28), "Web server attack detected" (33), "Traffic from known malicious source … Block this IP" for ET DROP (43, 106), "Known threat signature matched" for GPL (44), "suggests the device is compromised and under remote control" (137) and "often indicates active infection" (132), keyed on Suricata priority. Device page smart-alert assessment always passes `device_count=1` (AI:1653) → "Only this device triggers this alert — may be targeted." (AI:926) for every group; "Credential abuse detected." / "Sensitive data exposure detected." from substring categories (AI:901-911); "Frequency is increasing rapidly" from an absolute rate > 20/h, not a trend (AI:800-826, 935). The curated SID file mostly hedges ("may be infected").
- Failure: an ET DROP hit on a reply to the user's own connection tells them to block the address and "investigate any devices that communicated with it"; every smart alert on a device page claims the device was singled out.
- Affected UI: alert drawer (/alerts, category page), /devices/[ip] smart alerts.

### ALR-15 · P3 · Severity-less alerts read "Low" in the list but "Info" in the counts
- Evidence: `_extract_severity` returns 3 when no field holds an int (AA:348-374); counts and tiles put missing severity under info (AA:811-827; severity.ts:37-47).
- Affected UI: alert list, drawer, enrichment risk note (uses that 3).

### ALR-16 · P3 · Detection heuristics shown with probability-like confidence
- Evidence: beacon "Confidence N%" is a points sum (CV band + count band + "common interval") (threat_detection.py:144-166), drawn as a Meter (threats/+page.svelte:465). Lateral movement lists every RFC 1918 SSH/SMB/RDP/DB connection under the title "Lateral movement" (570-705). DNS: "consistent with DGA domain bruteforcing" from > 40% NXDOMAIN (878-890). The beacon assessment text itself is well hedged (360-365).
- Affected UI: /threats Beaconing, DNS anomalies, Lateral movement.

### ALR-17 · P3 · Detection packs API is a metadata mock
- Evidence: hardcoded packs with fixed rule counts and versions (daemon/services/detection_packs.py `BUILTIN_PACK_DEFS`); class docstring "not implemented in v1 -- only metadata management"; `enable_pack` docstring "rules will be loaded by Suricata" but nothing is written for Suricata; `check_updates` always `[]`. Reachable through `/api/detection-packs/*` proxies (web/src/routes/api/detection-packs/**), though no page imports `$api/detection-packs`.
- Affected UI: none today; any client of the API.

### ALR-18 · P3 · Kill-chain wording outruns the evidence
- Evidence: KPI sub "Devices moving through attack stages" and title "Active kill chains" (threats/+page.svelte:529, 610) for chains that can be built from inbound attempts plus one own-traffic alert whose stage comes from a substring match (ALR-7) or a missing Zeek record (ALR-10). The assessment says "possible" (AF:636-641); the KPI and title do not.
- Affected UI: /threats.

Positive checks (no finding):
- Threat score on request failure: daemon 500 (AA:2173-2175) → client throws (lib/api/alerts.ts getSmartAlertSummary) → error card on /threats (threats/+page.svelte:487-498) and /alerts (alerts/+page.svelte:1540). Never shows 0 on error.
- Smart summary pages are checked and raise at the cap (AI:1325-1361); findings and conn spans raise when incomplete (AF:141-142, 209-210).
- Device risk never shows 0/low on failure (devices/[ip]/+page.svelte:387-394, 863-865).
- Beacon snapshot shows "checked HH:MM", stale and failed states (threats/+page.svelte:109-129, 700-706; beacon_snapshots.py:68-95).
- `/alerts/suricata/[name]` uses a checked point-in-time snapshot and discloses caps.

---

## Part 4. OpenSearch fields queried (index `arkime_sessions3-*`)

```
@timestamp                                   daemon/api/alerts.py:138-150 (range), :414,:431,:436 (sort), :1743 (max)
@timestamp                                   daemon/services/alert_intelligence.py:1384-1391 (range), :1475-1476 (min/max), :1480 (top_hits sort), :1248 (now-24h)
@timestamp                                   daemon/services/alert_findings.py:136 (date_histogram 1m), :163-170 (range)
@timestamp                                   daemon/services/threat_detection.py:235, :323 (10 s histogram), :486 (range), :646-647
@timestamp                                   daemon/services/threat_intel.py:274
@timestamp                                   daemon/services/investigation.py:66, :115, :132-133
@timestamp                                   daemon/api/risk.py:362 (date_range), :841
event.provider                               daemon/api/alerts.py:50
event.provider                               daemon/services/alert_intelligence.py:1393, :1249
event.provider                               daemon/services/alert_findings.py:172
event.provider                               daemon/services/threat_detection.py:487
event.provider                               daemon/services/threat_intel.py:275
event.provider                               daemon/services/investigation.py:68
event.provider                               daemon/api/risk.py:382, :849
event.dataset                                daemon/api/alerts.py:51
event.dataset                                daemon/services/alert_intelligence.py:1394
event.dataset                                daemon/services/alert_findings.py:173
event.dataset                                daemon/services/threat_detection.py:488, :723
event.dataset                                daemon/services/threat_intel.py:276
event.dataset                                daemon/services/investigation.py:69
event.dataset                                daemon/api/risk.py:383, :850
rule.name                                    daemon/api/alerts.py:65 (prefix "SURICATA "), :417 (sort), :533 (term), :1189 (composite), :1337 (composite), :1354-1356 (terms / not exists)
rule.name                                    daemon/services/alert_intelligence.py:1431, :1451 (composite), :1511
rule.name                                    daemon/services/alert_findings.py:129
rule.name                                    daemon/services/threat_intel.py:60-63 (wildcards)
rule.name                                    daemon/api/suricata_categories.py:96
rule.category                                daemon/api/alerts.py:217 (term), :421 (sort)
rule.category                                daemon/api/suricata_categories.py:127
suricata.alert.severity                      daemon/api/alerts.py:193, :199, :415, :793, :1002, :1182, :1411, :1510, :1738
suricata.alert.metadata.signature_severity   daemon/api/alerts.py:71-75
suricata.flow_id                             daemon/services/alert_findings.py:134
source.ip                                    daemon/api/alerts.py:543, :553, :1410, :418 (sort)
source.ip                                    daemon/services/alert_intelligence.py:1402, :1459, :1247
source.ip                                    daemon/services/alert_findings.py:121, :130, :180
source.ip                                    daemon/services/threat_detection.py:74, :81, :217, :276, :592, :783
source.ip                                    daemon/services/threat_intel.py:354
source.ip                                    daemon/services/investigation.py:67, :116
source.ip                                    daemon/api/risk.py:385, :387, :415, :848
destination.ip                               daemon/api/alerts.py:544, :555, :1410, :419 (sort)
destination.ip                               daemon/services/alert_intelligence.py:1403, :1467
destination.ip                               daemon/services/alert_findings.py:122, :131, :181
destination.ip                               daemon/services/threat_detection.py:75, :82, :218, :277, :548, :593
destination.ip                               daemon/services/threat_intel.py:355
destination.ip                               daemon/services/investigation.py:75, :117
destination.ip                               daemon/api/risk.py:392, :394, :398, :415
destination.port                             daemon/api/alerts.py:419 (sort)
destination.port                             daemon/services/threat_detection.py:76, :83, :219, :549, :580
destination.port                             daemon/services/investigation.py:77
network.transport                            daemon/api/alerts.py:420 (sort)
network.transport                            daemon/services/alert_findings.py:187
network.transport                            daemon/services/investigation.py:76
network.community_id                         daemon/services/alert_findings.py:132, :174, :179
event.start                                  daemon/services/alert_findings.py:182
event.end                                    daemon/services/alert_findings.py:183
zeek.conn.history                            daemon/services/alert_findings.py:184
zeek.conn.orig_bytes                         daemon/services/alert_findings.py:192
zeek.conn.resp_bytes                         daemon/services/alert_findings.py:197
zeek.http.user_agent                         daemon/services/alert_intelligence.py:1254
zeek.dns.query                               daemon/services/threat_detection.py:777, :785
zeek.dns.rcode_name                          daemon/services/threat_detection.py:786
source.bytes                                 daemon/services/investigation.py:74, :127
source.bytes                                 daemon/api/risk.py:401
destination.bytes                            daemon/services/investigation.py:127
destination.bytes                            daemon/api/risk.py:405
source.mac                                   daemon/services/lan_anomaly_detector.py:54-55
_id (ids query)                              daemon/api/alerts.py:857
_source read (not filtered): alert, rule, suricata.alert (incl. metadata.signature_severity, metadata.attack_target), suricata.severity, destination.port   daemon/services/alert_intelligence.py:1316-1322, :1596-1605, :1735-1747
```
