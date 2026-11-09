# NetTap UI honesty audit: release-audit worktree @ 446845ec

Question asked: does the UI communicate uncertainty and failure honestly?
Scope: production paths in web/src (tests, fixtures and mocks excluded) and daemon/api + daemon/services (tests excluded). Everything was read statically; nothing was run. File paths are relative to the worktree root. `OLD CODE` blocks are dead code and were ignored.
Method: the lead swept the whole codebase with greps and scanners for every except/catch/!res.ok fallback, the cross-cutting files, the daemon, and the tools, PCAP, Packets and lookup pages. Three forked slices then read each page with its components, API client, proxy and daemon handler (A = security pages, B = device and traffic pages, C = system, settings, setup, Go Live and the shell). The lead spot-checked the high-severity claims (A-1, C-1, C-4, C-5 and its own).

## Verdict

The codebase was clearly hardened against "failure renders as zero/healthy" (the #96, NET-158 and S5 passes):
- The daemon returns 502 on OpenSearch errors, with a `checked()`/QueryFailed guard for partial shards. No daemon handler converts an exception into a 200 empty payload.
- Most API clients now throw.
- Every data page except the flow and action pages registers `registerPageRefresh` with a load guard.
- Most cards separate loading, empty and error.

There is no mock or random data on any data path.

The remaining dishonesty falls into five groups:
1. **Features that report success without doing the work.** This covers the notification preference save, the test notification, the routing rules, the scheduled alert notifications (never sent), Suppress and False positive (lost on restart), and the report generator.
2. **"Nothing measured" scored as good.** Compliance gives A/100; the IoT isolation score is 100/A; DNS average is 0.0 ms; Live bandwidth reads 0 B/s.
3. **No sensor-liveness signal.** With Suricata, Zeek or Logstash stopped, Home, Alerts, Threats and System show "No alerts" and "Healthy".
4. **Setup and Go Live overstatements.** These are the mock disk figures, the "Daemon · Running" check, the unconditional "monitoring all traffic" banner, and the stale bypass state.
5. **Stale data that looks current.** The top bar shows no chip on a fully failed refresh; the "Live" chip shows over frozen data; UniFi's cache is served as current; reverse DNS is labelled "looked up now".

### Design-system claim ("every data card shows CardState for loading, empty and error; every loader uses registerPageRefresh with a load guard")
**Mostly true, with exceptions:**
- **CardState is missing or bypassed** on:
  - Infrastructure: the KPIs and the Zeek/Suricata cards show "--" for loading and error alike.
  - The shell alert badge: hidden on failure, the same as for zero.
  - Recipe cards on system/cyberchef and tools/cyberchef: failure reads as empty or hidden.
  - Setup storage step: mock data is shown as real.
  - The MAC device page: loading renders as empty.
  - Settings: the notification preferences and API-key forms.
- **registerPageRefresh is absent** on setup, go-live and settings/backup (flow or action pages; go-live polls on its own), and on the tools action pages.
- **Loaders that report 'ok' despite failures:**
  - Threats returns 'ok' when checks inside the report failed (HON-27).
  - tools/cyberchef returns 'ok' when recipes fail.
- **The contract has no stale or disabled state.** CardState only knows loading, empty and error. Stale data is handled ad hoc: page notices and `loadFailed(what, true)` on most pages, nothing on the cards listed in HON-35. The TopBar never flags a fully failed refresh (HON-11).

## Findings

Severity: P0 = compromise or data loss; P1 = materially wrong information or a silent failure the user would act on; P2 = misleading presentation; P3 = minor.
CONFIRMED = the path was followed from the backend or failure to what renders. SUSPECTED = not fully traced.
No P0 found.

### P1

**HON-1 · P1 · CONFIRMED (no check exists) · Nothing tells "no alerts / healthy" apart from "the sensors or ingestion stopped"** (slice A-3 + C-9)
- Evidence:
  - The aggregate health covers only storage readable, SMART and OpenSearch reachable (daemon/api/server.py:546-618, `_aggregate_health`).
  - Home's pipeline has four stages: capture link, packet loss, system and OpenSearch (web/src/routes/home.ts:119-170). There is no Zeek, Suricata or Logstash stage, and no "newest event ingested" age anywhere in daemon/api or daemon/services.
  - A full disk past the emergency line and stopped capture don't affect "Healthy" either.
- User sees, with Suricata or its Logstash pipeline stopped:
  - Home: Alerts KPI "0", an empty gauge, "No actionable alerts detected." (web/src/routes/+page.svelte:857-858), and all pipeline stages green;
  - Alerts: zero tiles and "No alerts" (alerts/+page.svelte:1463-1464);
  - Threats: "No actionable threats detected." (threats/+page.svelte:195);
  - System: "NetTap · Healthy" (system/+page.svelte:208-216, :290-297);
  - Compliance: alert score 100.
- Pages: Home, Alerts, Threats, System, Compliance.

**HON-2 · P1 · CONFIRMED · Saving notification preferences does nothing, but says "saved successfully"** (C-1)
- web/src/routes/api/notifications/config/+server.ts:37-48 (POST) discards the body (`const _body = …`) and returns `{success: true, message: 'Configuration received. Set environment variables…'}`.
- web/src/routes/settings/+page.svelte:705-735 checks only `res.ok` and shows "Notification settings saved successfully.". The `message` is ignored.
- GET rebuilds the form from environment variables (lib/server/notifications.ts:84-117), so a reload undoes every change.
- User sees: a green "saved" for a webhook URL, email address and threshold that are never used.
- Page: /settings (Notifications).

**HON-3 · P1 · CONFIRMED · "Send test notification" always reports success** (C-2)
- routes/api/notifications/test/+server.ts returns `success: true` whenever `sendNotification` resolves. In lib/server/notifications.ts (~259-335):
  - `sendEmail` swallows every error with a console.error;
  - `sendWebhook` catches network errors (:271) and never checks `res.ok`;
  - with no channel configured, it still resolves.
- settings/+page.svelte:739-757 shows "Test notification sent successfully."
- User sees: confirmation that SMTP or the webhook works, when nothing was delivered.
- Page: /settings.

**HON-4 · P1 · CONFIRMED · Alert notifications go out only while a browser has the app open, and a daemon failure reads as "0 alerts"** (C-3, lead L-14)
- The only producer is GET /api/notifications/from-alerts. Its only caller is lib/components/NotificationBell.svelte:40-50, which runs when the shell mounts. There is no server-side schedule.
- routes/api/notifications/from-alerts/+server.ts:8-14: `res.json().catch(() => ({alerts: []}))` and `data.alerts || []`. The daemon's 502 `{error}` becomes `{notifications_created: 0}` with 200, and the bell's caller swallows errors.
- Settings copy promises "Which alerts reach you · by email and webhook" (settings/+page.svelte:956, :976).
- SUSPECTED: there is no de-duplication, so every app load re-sends a notification for each critical or high category.
- User sees: an empty bell and no email while critical alerts occur.
- Pages: shell bell, /settings.

**HON-5 · P1 · CONFIRMED · Notification routing rules never fire** (C-4)
- daemon/services/notification_hub.py:515 `process_event()` has no caller (grep across daemon/), so channels are only reached by `test()` (:152-162).
- settings/notifications/+page.svelte still offers rules for New device, Alert, Anomaly, Storage, SMART, Capture and System events (:108-116) and confirms "Routing rule created." (:237).
- The delivery-log empty state says "Each notification NetTap sends … appears here" (:500-501).
- User sees: configured rules and a working Test, then silence on real events.
- Page: /settings/notifications.

**HON-6 · P1 · CONFIRMED · Suppress and False positive are written to a tmpfs and are lost on every restart; save failures still return 200** (A-1)
- daemon/services/alert_intelligence.py:956-958: the path is `NETTAP_DATA_DIR` or `/tmp`. Baselines (:1068) and the threat-intel cache (services/threat_intel.py:25) use the same fallback.
- `NETTAP_DATA_DIR` is set nowhere. The daemon container (`nettap-storage-daemon`, docker/docker-compose.yml:826) mounts `/tmp` as a 50 MB tmpfs (:883), while its persistent volume is /opt/nettap/data (:892).
- `save_suppress_list` swallows exceptions (:970-981). daemon/api/alerts.py:2196-2224 returns 200 "suppressed" / "marked_false_positive" regardless.
- An unreadable file loads as empty, and the next save overwrites it (:960-967).
- User sees: after any redeploy (`--force-recreate`), every suppression and "permanent" false positive is gone, and the threat score and Home summary count them again. There was no success feedback in the first place (HON-30).
- Pages: Alerts, Alerts/[category], Home, Threats.

**HON-7 · P1 · CONFIRMED (code path) · Security posture scores "nothing measured" as 100 / grade A / "Excellent"** (A-2)
- web/src/routes/compliance/+page.svelte gives each category 100 when it has nothing to measure:
  - :141 encryption, :147 DNS, :167 network, :180 and :184 patch, :196 alerts, :210 monitoring;
  - the overall is A/100 (:227-228).
- Copy: "Excellent security posture. Your network follows best practices across all categories." (:688), "looks excellent" (:556), and "No alerts detected — your network looks clean" (:369).
- Failed requests are handled (:406-421); empty results are not.
- User sees: on a fresh install, or with ingestion broken but OpenSearch answering zero counts, a green A ring and "6 of 6 Good".
- Page: /compliance.

**HON-8 · P1 · CONFIRMED · The setup wizard's Storage step shows fabricated disk figures as real** (lead L-1)
- routes/api/setup/storage/+server.ts:104-127 answers 200 with a hardcoded StorageStatus (1000 GB total, 44.3 used, 955.7 free, 4.4 %, 1.2 GB/day, `source: 'mock'`) whenever `daemonJSON('/api/storage/status')` errs. That covers the daemon being down, and the daemon being up while `storage.get_status()` raises (lib/server/daemon.ts:144-146).
- routes/setup/+page.svelte:480-497 `fetchStorage()` never checks `source === 'mock'`, though :407 and settings/+page.svelte:175 do.
- Rendered at :1283-1300: "4.4% used · 44.3 GB used · 955.7 GB free · 1000.0 GB total · Estimated retention capacity: N days at about 1.2 GB a day". The estimate is from :186-192, which also defaults `estimated_daily_gb || 1.2`.
- With only the storage read failing, the retention save (storage +server.ts POST :139-200, honest) succeeds against numbers that were never measured.
- Page: /setup (Storage).

**HON-9 · P1 · CONFIRMED · Go Live always says "NetTap is monitoring your network. All traffic between your modem and router is analysed for threats and anomalies."** (lead L-2)
- routes/go-live/+page.svelte:428-431 is unconditional in phase 3, which only means br0 exists and both carriers are up (:89-97).
- It shows beside "Bypass mode is on … without inspection" (:421-426), while bridge health fails (:131-135, :439-448), and without any Zeek, Suricata or OpenSearch check.
- User sees: a green "monitoring all traffic" banner at the moment of going live, possibly with nothing inspected.
- Page: /go-live.

**HON-10 · P1 · CONFIRMED · Setup verification says "NetTap daemon · Running" with the daemon down** (C-5)
- routes/setup/+page.svelte:606-611 passes on `fetch('/api/health').ok`.
- routes/api/health/+server.ts always returns 200 `status: 'healthy'` for the web process. A down daemon appears only in the nested `daemon.status: 'unreachable'`, which the requirements step reads (:381) but this step doesn't.
- User sees: a green tick on the last wizard screen.
- Page: /setup.

### P2

**HON-11 · P2 · CONFIRMED · The top bar does not mark a fully failed refresh** (lead L-3)
- lib/components/shell/TopBar.svelte:246-250 shows "Some data failed to refresh" only for `status === 'partial'`. For `'failed'`, it keeps "Updated N min ago" from the last good load (shell/topbar.ts:86-94; stores/pageRefresh.ts:96-101).
- "Can't reach NetTap" (:243-245) covers only an unreachable web/daemon, not OpenSearch failing behind a live daemon.
- User sees: the same header whether the last refresh worked or failed. On the cards in HON-35 the old figures then look current.
- Pages: all.

**HON-12 · P2 · CONFIRMED · The Threats brief says "no … threat intel matches" when the intel request failed** (A-4)
- threats/+page.svelte:211-222: `intelFailed` (:395) is never added to `failed`, and `tiTotal` falls back to 0. The text is "No kill chains, beaconing or threat intel matches."
- Meanwhile the intel card beside it shows an error (:560, :597-598).
- Page: /threats.

**HON-13 · P2 · CONFIRMED · Grade A and green checks for LAN traffic NetTap cannot see** (A-5)
- daemon/services/iot_monitor.py:2406-2412 returns segmentation 100/"A" when no IoT device is known.
- iot/+page.svelte:826-833: "100/100", grade A, and "No cross-segment IoT communication detected." with a check icon.
- threats/+page.svelte:771-776: "No lateral movement detected."
- In bridge, uplink-mirror and DHCP-gateway modes, LAN-to-LAN traffic is switched behind the router and never crosses NetTap. No card says so.
- Compliance "Network segmentation" (:163-172, :447-455) is really "100, less 10 per device not baselined".
- Pages: /iot, /threats, /compliance.

**HON-14 · P2 · CONFIRMED · Compliance category names claim more than they measure** (A-6)
- "Patch currency" (compliance/+page.svelte:458-466) counts http, ftp, telnet, pop3 and imap connections (:175-191), not patches or TLS versions.
- "DNS security" counts only DoT (:436-444). DoH users score "Poor".
- "current period" is never defined; the page uses the daemon's 24 h default (:600-604).
- "Monitoring coverage" means "has a risk score" (:487).
- Page: /compliance.

**HON-15 · P2 · CONFIRMED · Daemon-generated alert text states compromise as fact and orders isolation** (A-7, lead L-6)
- daemon/services/alert_enrichment.py:
  - :28 "Trojan horse communication detected: …";
  - :29 "Exploit attempt detected";
  - :33 "Web server attack detected";
  - :40 "Attack response or successful compromise indicator";
  - :132 "This is a critical threat. Malware with high severity often indicates active infection with data theft or ransomware capabilities." (the UI labels Suricata sev 1 "High", :125);
  - :137 "…suggests the device is compromised and under remote control.";
  - :63 "Immediately isolate the device…".
- daemon/services/investigation.py:181-182: "IMMEDIATE: Isolate the source host from the network." for every severity ≤1 alert, even when the source is an internet host (an inbound attempt).
- This text is added to every raw alert (daemon/api/alerts.py:732, :890). It is shown as alert row titles (routes/alerts/alert-view.ts `alertTitle`), in the drawer (AlertDrawerContent.svelte:169-190, AlertDetail.svelte:47, :90, AlertDetailPanel.svelte:177-196), and under Threats › Auto-investigations › "What to do" (threats/+page.svelte:867).
- The curated per-SID text (daemon/data/suricata_descriptions.json) is correctly hedged ("may be infected"). The prefix fallback, which covers most alerts, is not.
- Pages: Alerts, Alerts/[category], Threats.

**HON-16 · P2 · CONFIRMED · Live "Bandwidth" reads 0 B/s when it can't measure** (B-1)
- daemon/api/live.py:46-63 `ThroughputSampler.rate()` returns 0.0 (not None) when both counter reads are 0. Then :207-217 overwrites the conn-derived bandwidth with it.
- Zero counters come from:
  - CaptureManagerStub.get_stats (daemon/services/capture_mode_stub.py:92-94), which is kept for good when capture setup fails (daemon/main.py:564-579);
  - unreadable sysfs counters (bridge_capture_adapter.py:243-253, mirror_manager.py:608-615).
- User sees: "Bandwidth 0 B/s" (live/+page.svelte:322) beside a busy connection feed.
- Page: /live.

**HON-17 · P2 · CONFIRMED · The Live page keeps saying "Live" over frozen data** (B-2)
- live/+page.svelte:631 `<LiveChip {paused}>`. LiveChip.svelte:6-7 has no failed state.
- On a failed poll the page keeps the old `dashboard` (:445-450), the globe keeps animating old arcs, and the subtitle still says "refreshing every 3 s" (:627). Only one page banner (:641-643) says otherwise.
- LiveBandwidthCard is the correct model: it shows Live only while fresh, plus "last measured N s ago".
- Page: /live.

**HON-18 · P2 · CONFIRMED · Device OS and type are shown as fact from weak heuristics** (B-3)
- OS comes from one plaintext-HTTP User-Agent regex (daemon/services/device_fingerprint.py:26-35, :368-389).
- Type comes from hostname substrings (daemon/api/devices.py:426-500; "cameron-pc" → IoT).
- Shown unhedged in the "OS" and "Type" columns (devices/+page.svelte:585-586, :630-632), the hero chip (devices/[ip]/+page.svelte:760) and the category chip (devices/mac/[mac]/+page.svelte:274).
- Pages: /devices, /devices/[ip], /devices/mac/[mac].

**HON-19 · P2 · CONFIRMED · DNS "Average resolution 0.0 ms" when nothing was measured** (B-4)
- daemon/services/dns_analytics.py:569-570 `round((avg_rtt or 0) * 1000, 2)`, rendered at dns/+page.svelte:679-686.
- This happens with zero records or one-way capture.
- Page: /dns.

**HON-20 · P2 · CONFIRMED · Infrastructure shows "Healthy · Promiscuous" for bridge capture without checking** (C-6)
- infrastructure/+page.svelte:976-978 returns ok whenever bypass is off. `captureHealth.promisc_enabled` (:435) is read only for mirror and gateway modes (:970-974).
- Page: /infrastructure.

**HON-21 · P2 · CONFIRMED · After a reload, the DHCP gateway page drops the IPv6 "some traffic skips NetTap" warning; the gateway banner is unconditional** (C-7)
- lib/components/golive/DhcpGoLive.svelte:85-95 skips the preflight when the gateway is already on. The warning is gated on `preflight?.ipv6_router_advertisements` (:511-518).
- "NetTap is now your network's gateway" (:442-446) shows even when the DHCP server chip reads "Stopped" (:465-469).
- Page: /go-live (DHCP mode).

**HON-22 · P2 · CONFIRMED · A crashed capture manager shows as "Capture not set up"** (C-8)
- daemon/main.py:564-579 keeps the stub, whose `not_configured` status (capture_mode_stub.py:76-86) maps to the grey "Capture not set up" in lib/components/shell/status.ts:40-41. The stub's issue text is never shown.
- Pages: shell, Home pipeline.

**HON-23 · P2 · CONFIRMED · Backup claims to export "every NetTap setting"** (C-10)
- Copy at settings/backup/+page.svelte:143-146. daemon/services/config_backup.py:79-133 leaves out Suricata rule sources, the ET Pro code and owner rules, UniFi, home location, the live-bandwidth opt-in, the env notification settings and API keys.
- The export reports "Configuration exported successfully".
- Page: /settings/backup.

**HON-24 · P2 · CONFIRMED · Go Live keeps the old bridge status after a failed refresh, and the bypass button acts on it** (C-11)
- go-live/+page.svelte:128-136 keeps `health` on failure. The chip (:436-438) shows the old word beside the error (:447-449).
- The bypass button (:509-520) chooses enable or disable from the stale `health.bypass_active`, against its own "#96: no bypass toggle while the bridge state is unknown" comment.
- Page: /go-live.

**HON-25 · P2 · CONFIRMED (daemon) / SUSPECTED (UI timing) · UniFi lists: stale cache served as current, poll failures as 200** (lead L-4)
- daemon/services/unifi_integration.py:518-533 `_cached_poll` swallows the exception and returns the old cache, or `[]` before the first success. The handler `except`s in daemon/api/devices_v2.py:618-679 never fire, and the lists carry no age (`cache_age_seconds` is on /status only, clients only: :857-858).
- infrastructure/+page.svelte:505-515 marks a list failed only on rejection, which never happens here. The `last_error` banner (:1646-1648) comes from /status, which is read before the lists (:483-498), so it lands at the earliest on the next 30 s cycle.
- Until then: device and port states up to 5-10 min old shown as current, or empty tables.
- Page: /infrastructure.

**HON-26 · P2 · CONFIRMED · The report generator returns fabricated "compliant, low risk" reports** (lead L-5)
- daemon/services/report_generator.py:311-410: every section is a placeholder. Compliance `overall_score: 100` with three "pass" checks ("Rules are current"…), risk "low", 0 alerts, 0 devices.
- Served by POST /api/reports/generate/{id} (daemon/api/reports.py:155-193), proxied at routes/api/reports/generate/[id]/+server.ts and wrapped by lib/api/reports.ts:129.
- No page uses it, so this is API-only today. Return 501 or delete it before publishing the API.

### P3

**HON-27 · P3 · CONFIRMED** (A-8) threats/+page.svelte:402 `outcome([reportRes, tiRes])` returns 'ok' when the report carries `failed_checks`. The top bar shows "Updated just now" with no chip.

**HON-28 · P3 · CONFIRMED** (A-9, L-9) IoT wording:
- iot/+page.svelte:760 "No findings. All devices look healthy." Only the privacy and protocol checks feed it.
- :978-981 "Compliant · All protocols within expected parameters." also covers devices with too little traffic to judge (`compliant: len(findings) == 0` in iot_monitor).

**HON-29 · P3 · CONFIRMED** (A-10) alerts/+page.svelte:1463-1464: "Alerts will appear here once Suricata is running…" shows even when a filter is active.

**HON-30 · P3 · CONFIRMED** (A-11) Suppress and False positive give no feedback, and the raw row stays (alerts/+page.svelte:1117-1126; suppression filters smart alerts only, alert_intelligence.py:1578-1583).

**HON-31 · P3 · CONFIRMED** (A-12) alerts/+page.svelte:841 / :1390-1393: the "N informational events" line keeps the old window's count after a failed refresh, with no marker.

**HON-32 · P3 · SUSPECTED** (A-13) The Home Alerts KPI window can lag the traffic KPIs after the tab was hidden (lib/stores/alertSnapshot.ts:63, +page.svelte:169, +layout.svelte:117).

**HON-33 · P3 · CONFIRMED** (A-14) The compliance KPIs "N of 6" silently leave out uncomputed categories (compliance/+page.svelte:727-753).

**HON-34 · P3 · SUSPECTED** (A-15) A corrupt ack file loads as `{}` and the next ack overwrites every earlier one (daemon/api/alerts.py:383-389, :913-926).

**HON-35 · P3 · CONFIRMED** (B-5) Old data kept after a failed refresh with no card marker:
- the devices Top consumer KPI (devices/+page.svelte:718-726);
- the MAC page hero, top destinations, protocols and connections KPI (devices/mac/[mac]/+page.svelte:109-118, :266-302, :327-333, :359-390);
- the bandwidth per-device table (bandwidth/+page.svelte:481-495);
- traffic/[category] share of network, plus trend arrows against an old previous window (:470-475);
- connections protocols and top sources/destinations (connections/+page.svelte:999-1068);
- the devices/[ip] "Online" chip, from a non-reactive Date.now() in $derived (:232-233).

**HON-36 · P3 · CONFIRMED** (B-6) MAC page:
- On a range change, loading shows "No destinations…" (devices/mac/[mac]/+page.svelte:95, :360-389).
- The Bandwidth, DNS and Alerts cards never render, because DeviceRegistry.get_device_traffic (daemon/services/device_registry.py:625-636) returns none of those keys. A device's alerts are invisible on its MAC page.

**HON-37 · P3 · CONFIRMED** (B-7) "looked up now" (address/[ip]/+page.svelte:608) can be cached reverse DNS (up to 1 h) or WHOIS (up to 24 h) (daemon/api/lookup.py:26-29, :134, :167). The lookup pages also don't mark cached answers.

**HON-38 · P3 · CONFIRMED** (B-8) A missing GeoIP database, a MaxMind error or an OpenSearch error becomes "Unknown"/"XX" (daemon/services/geoip_service.py:462-464, :506, :526; geoip/[ip]/+page.svelte:133-139).

**HON-39 · P3 · CONFIRMED** (B-9) A green check, "Not on a threat list", shows even with 0 indicators cached (address/[ip]/+page.svelte:533-539; daemon/api/addresses.py:412-425).

**HON-40 · P3 · CONFIRMED** (B-10) Monthly projection and cap file:
- The projection divides by calendar days since the 1st (daemon/services/bandwidth_tracker.py:369-381).
- A corrupt cap file silently resets the cap to 0 (:57-65), and the over-cap warning disappears.

**HON-41 · P3 · CONFIRMED** (B-11) A quiet device's 404 from the risk endpoint shows as "Couldn't load the risk score: the request failed." (daemon/api/risk.py:918; lib/api/devices.ts:402-409; devices/[ip]/+page.svelte:863-864).

**HON-42 · P3 · CONFIRMED** (B-12, L-8) Copy that slightly overclaims:
- "Every session your devices opened" (connections/+page.svelte:942);
- "+N new" for a device-count delta (traffic/[category]/+page.svelte:242);
- "No NXDOMAIN errors detected. That's a good sign." (dns/+page.svelte:785);
- "Every device shows up in NetTap under its own address" (lib/components/setup/DhcpGatewayStep.svelte:54). Static-IP and IPv6 devices bypass the gateway; the caveat comes later, at DhcpGoLive.svelte:516.

**HON-43 · P3 · CONFIRMED** (B-13) NewDeviceBanner hides itself regardless of the `acknowledgeDevice()` result (lib/components/NewDeviceBanner.svelte:54-64; lib/api/devices-registry.ts:216-230).

**HON-44 · P3 · CONFIRMED** (C-12) Infrastructure pipeline stages:
- The Zeek and Suricata rates keep their last value with stages green after a failure (infrastructure/+page.svelte:467-468, :982-985).
- Logstash reads "ok · Processing" whenever its stats are readable (:1010-1012).
- The pipelines and templates sections vanish on failure (lib/api/infrastructure.ts:209-282).

**HON-45 · P3 · CONFIRMED** (C-13) "Ruleset: ET Open" is hardcoded (infrastructure/+page.svelte:1487), though ET Pro and own rules exist since NET-191.

**HON-46 · P3 · CONFIRMED** (C-14) A failed API-key status load looks like "not configured" (settings/+page.svelte:323-336, :933-935).

**HON-47 · P3 · CONFIRMED** (C-15) "Cleanup complete … (N errors)" is shown as success (settings/+page.svelte:851-855).

**HON-48 · P3 · CONFIRMED** (C-16) Notification bell:
- Mark-read is optimistic and its result ignored (NotificationBell.svelte:90-108).
- The unread badge keeps its old number after a failed poll.

**HON-49 · P3 · CONFIRMED** (C-17) The sidebar alert badge renders nothing for both a failure and zero (routes/+layout.svelte:124-127; Sidebar.svelte:54).

**HON-50 · P3 · CONFIRMED** (C-18, L-12) CyberChef:
- `getRecipes` returns `{recipes: []}` on non-2xx (lib/api/cyberchef.ts:56-66). system/cyberchef shows "No quick recipes" (:199-200), and tools/cyberchef hides the card and returns 'ok' (:53-64).
- A daemon-side status-check failure (daemon/services/cyberchef_service.py:124-131) renders as "CyberChef isn't running".

**HON-51 · P3 · CONFIRMED** (C-19) Changelog:
- The 7-day default window is never stated (daemon/services/changelog.py:117-121; changelog/+page.svelte:231, :262-268).
- A failed `log_event` silently drops the event (:93-95).

**HON-52 · P3 · CONFIRMED** (C-20) After a failed refresh, the System OpenSearch card body says "Connected" from old data while its chip says "Unknown" (system/+page.svelte:323-350).

**HON-53 · P3 · CONFIRMED** (C-21) routes/api/health/+server.ts hardcodes `version: '0.3.0'` and `status: 'healthy'` (see HON-10).

**HON-54 · P3 · CONFIRMED** (L-7) The DNS heuristics name one malicious cause and no benign one:
- daemon/services/threat_detection.py:851 "suggests DNS tunneling" for long subdomains (CDN and telemetry hashes match);
- :886-890 "consistent with DGA domain bruteforcing" for a high NXDOMAIN ratio (Chrome's random-name probes and misconfigured devices match).
- The beacon text (:370-374) already names benign causes.
- Page: /threats.

**HON-55 · P3 · CONFIRMED** (L-10) A missing severity defaults to 3 = low (daemon/api/devices.py:1595, services/alert_intelligence.py:1559, services/alert_enrichment.py:223) instead of unknown.

**HON-56 · P3 · CONFIRMED** (L-11) A missing or corrupt OUI database becomes `{}` (daemon/services/mac_lookup_service.py:80-87), and an OpenSearch fallback failure becomes None (:63-68). Both read as "Unknown vendor" (tools/mac-lookup/+page.svelte:98; tools/ipv6/+page.svelte:93).

**HON-57 · P3 · CONFIRMED** (L-12) Dead API clients still turn non-2xx into empty results:
- lib/api/lan-security.ts:45-80, mac-correlation.ts:123-199, detection-packs.ts:33-131;
- suricata-rules.ts:166-233 (getRuleSources/getRuleStats, used only in OLD CODE at settings/suricata-rules/+page.svelte:315);
- system.ts:192-197 (getIndices), bridge.ts:108-118 (getBridgeHistory), reports.ts:35-135;
- live: changelog.ts:70-80 (`getEventTypes`; the filter list empties silently).
- Any future consumer inherits "failure = nothing". Make them throw, or delete them.

**HON-58 · P3 · CONFIRMED** (L-13) A real-looking public IP ships as a placeholder: settings/+page.svelte:1425 `placeholder="e.g. 203.0.113.10 (owner IP, redacted)"`, also daemon/api/settings.py:243, routes/api/settings/excluded-ips/+server.ts:18 and tests. This is consumer ISP space, likely the owner's WAN address. Use RFC 5737 203.0.113.x.

### Checked and found honest (no finding)
- **Random and demo data:** there is no Math.random or `random` on a data path. The only uses are notification IDs (lib/server/notifications.ts:287) and the globe's visual jitter (charts/globe/engine.js:42). There is no demo or sample mode.
- **NIC mock:** the mock in routes/api/setup/nics/+server.ts:72-78 is rejected by the wizard (setup/+page.svelte:334, :440).
- **Capture stub:** daemon/services/capture_mode_stub.py is reachable (api/server.py:1278-1283) but reports `not_configured` with an explicit issue. Its no-op setup/teardown are not routed. The problems are its zero stats (HON-16) and its label after a crash (HON-22).
- **Daemon handlers:** a scan of every except block in daemon/api found none returning 200 with an empty payload. OpenSearch errors return 502, partial shards raise QueryFailed (e.g. api/traffic.py:290-596), and /api/system/health is tri-state (api/server.py:553-614, scope aside: HON-1).
- **Lower layers:** hub channel senders check HTTP status (services/notification_hub.py:~354-456), and the hub Test needs `success === true` (lib/api/notification-hub.ts:115-126). Device rename and picture, device-page suppress, acknowledge, the retention save (outcome_unknown), capture toggles, excluded IPs, UniFi test, live-bandwidth opt-in, updates ("Not checked" / "Unknown", never "Up to date"), Suricata rules, logs, investigations, PCAP, Packets and the Tools pages all show failures.
- **Dead code:** threat_intel.py:226-228 "confirmed malicious infrastructure" has no caller of `enrich_alerts`.
- **Wording:** no "decrypt" claims in UI copy. "secure", "safe" and "protected" appear only as protocol names, cookie flags or update copy (system/updates/+page.svelte:709, harmless).

### Slice ID to HON ID map (the state-table notes below cite slice IDs)
| Slice ID | HON | | Slice ID | HON | | Slice ID | HON | | Lead | HON |
|---|---|---|---|---|---|---|---|---|---|---|
| A-1 | 6 | | B-1 | 16 | | C-1 | 2 | | L-1 | 8 |
| A-2 | 7 | | B-2 | 17 | | C-2 | 3 | | L-2 | 9 |
| A-3 | 1 | | B-3 | 18 | | C-3 | 4 | | L-3 | 11 |
| A-4 | 12 | | B-4 | 19 | | C-4 | 5 | | L-4 | 25 |
| A-5 | 13 | | B-5 | 35 | | C-5 | 10 | | L-5 | 26 |
| A-6 | 14 | | B-6 | 36 | | C-6 | 20 | | L-6 | 15 |
| A-7 | 15 | | B-7 | 37 | | C-7 | 21 | | L-7 | 54 |
| A-8 | 27 | | B-8 | 38 | | C-8 | 22 | | L-8 | 42 |
| A-9 | 28 | | B-9 | 39 | | C-9 | 1 | | L-9 | 28 |
| A-10 | 29 | | B-10 | 40 | | C-10 | 23 | | L-10 | 55 |
| A-11 | 30 | | B-11 | 41 | | C-11 | 24 | | L-11 | 56 |
| A-12 | 31 | | B-12 | 42 | | C-12 | 44 | | L-12 | 57, 50 |
| A-13 | 32 | | B-13 | 43 | | C-13 | 45 | | L-13 | 58 |
| A-14 | 33 | | | | | C-14 | 46 | | L-14 | 4 |
| A-15 | 34 | | | | | C-15..C-21 | 47..53 | | | |

## Per-page state table (every route in web/src/routes/**/+page.svelte)

Legend: Y = handled separately and honestly. N = missing. "conflated: X" = what is shown instead. "Note" or "page notice" = data kept, with a stale notice. n/a = not applicable.
Columns: Loading / Empty (no observed activity) / Error (failed query) / Stale (behaviour after a failed refresh, or cached data without age) / Disabled (feature off, not configured, not checked).

### Slice A: Home, Alerts, Threats, Compliance, IoT, Certificates

| Page | Card | Loading | Empty | Error | Stale | Disabled | Notes |
|---|---|---|---|---|---|---|---|
| Home | Bandwidth KPI | Y ("Loading…", —) | Y (0 B + "No traffic data yet" notice) | Y (sub: couldn't load) | Y (stale sub text) | N | no ingest-freshness check (A-3) |
| Home | Connections KPI | Y | Y (notice) | Y | Y | N | |
| Home | Alerts KPI | Y | conflated: 0 when Suricata is down | Y | Y (snapshot stale text) | N | A-3, A-13 |
| Home | Devices KPI + "new today" chip | Y | Y | Y (KPI); chip: conflated, failure hides the chip like 0 | Y | n/a | |
| Home | Bandwidth over time | Y | Y | Y | Y (staleNote) | N | |
| Home | Network protocols | Y | Y | Y | Y | N | |
| Home | Traffic categories | Y | Y | Y | Y | N | |
| Home | Top devices | Y | Y | Y | Y | N | |
| Home | Alert summary (gauge) | Y | conflated: empty gauge when Suricata is down | Y | Y | N | |
| Home | Alert summary (groups) | blank while loading | Y "No actionable alerts detected." | Y (cleared, message) | n/a (cleared) | N | A-3 |
| Home | Capture pipeline | Y ("Checking") | n/a | Y (Unknown + reason) | partial: "at the last refresh", no time | Y (Not configured) | no Zeek/Suricata/Logstash stage |
| Alerts | Alerts by severity | Y | conflated: zeros when the sensor is down | Y | Y (stale notice) | N | A-3 |
| Alerts | Alert list | Y | Y (copy blames Suricata even when filtered, A-10) | Y | n/a (cleared) | N | |
| Alerts | Alert timeline | Y | Y | Y | error replaces old data | N | |
| Alerts | Threat summary | Y | Y | Y | error replaces | N | |
| Alerts | Alert categories | Y | Y | Y | error replaces | N | |
| Alerts | Top signatures | Y | Y | Y | error replaces | N | partial-scan note Y |
| Alerts | Top affected devices / sources | Y | Y | Y | error replaces | N | partial note Y |
| Alerts | Informational line | n/a | hidden at 0 | hidden only before the first success | N: kept old, no marker (A-12) | n/a | |
| Alerts | Row/drawer actions | n/a | n/a | Y (errors shown) | n/a | n/a | success invisible; persistence lost on restart (A-1, A-11) |
| Alerts/[category] | Page body (KPIs, severity, sub-categories, addresses, signatures) | Y | Y (page-level) | Y (page-level) | n/a (cleared) | N | one request feeds all |
| Alerts/[category] | Alert volume over time | Y | Y | Y | n/a (cleared) | N | |
| Alerts/[category] | Recent alerts | Y | Y | Y | n/a | N | |
| Alerts/suricata/[name] | Every card | Y | Y | Y | Y (stale notice) | n/a | partial-list notices Y |
| Threats | Whole report (KPIs, brief) | Y | Y | Y | n/a (cleared) | N | brief conflates intel failure (A-4) |
| Threats | Threat intel matches | Y | Y | Y | n/a | N | |
| Threats | Kill chains | Y (page) | Y | Y (page) | n/a | N | |
| Threats | Beaconing | Y (pending) | Y | Y | Y ("Last checked …") | Y (partial-scan note) | |
| Threats | DNS anomalies | Y (page) | Y | Y | n/a | Y (incomplete note) | |
| Threats | Lateral movement | Y (page) | conflated: "No lateral movement detected" for traffic it can't see (A-5) | Y | n/a | N | |
| Threats | Auto-investigations | Y (page) | Y | Y (also partial) | n/a | N | advice wording (A-7) |
| Threats | Loader result | | | returns 'ok' with failed checks (A-8) | | | |
| Compliance | KPIs Good/Attention/Poor | Y (—) | conflated: no data reads Good | conflated: uncomputed silently left out (A-14) | per-input failure nulls the score | N | |
| Compliance | Score by category (radar) | Y | conflated: no data = 100 (A-2) | Y (fewer than 3 computed) / note | Y (failed input means no score) | N | |
| Compliance | Overall posture | Y | conflated: no data = A/100 "Excellent" (A-2) | Y | Y | N | |
| Compliance | Category cards | Y | conflated: score 100 + "No … data yet" finding | Y ("Couldn't compute") | Y | N | labels (A-6) |
| IoT | Page (fleet) | Y | Y ("No IoT devices…") | Y (page error) | n/a (cleared) | n/a | |
| IoT | KPIs: anomalies / unencrypted | Y (page) | Y | Y (page) | n/a | Y ("Not checked" / "Not measured") | |
| IoT | Smart home health | Y | Y ("Not enough measured") | Y (page) | n/a | Y | |
| IoT | Findings | Y (page) | Y, but "All devices look healthy" (A-9) | Y (both or one check failed) | n/a | N | |
| IoT | Device trust scores | Y (page) | Y | Y (page) | n/a | Y (per-row "Not enough measured") | |
| IoT | Manufacturer profiles | Y (page) | Y | Y | n/a | Y | |
| IoT | Network isolation | Y (page) | conflated: 100/A + check for unobservable traffic (A-5) | Y | n/a | N | |
| IoT | Drawer tabs | Y | Y | Y | n/a | partial: Protocol "Compliant" (A-9) | |
| Certificates | KPIs | Y (—) | Y | Y (—) | Y (stale notice with time) | n/a | |
| Certificates | Needs a look | Y | Y (careful scoped copy) | Y | Y | Y ("Not checked" when validation is off) | |
| Certificates | Your devices' certificates | Y | Y | Y | Y | Y | |
| Certificates | All certificates | Y | Y | Y | Y | Y | truncation notice Y |

Refresh contract: every slice page calls `registerPageRefresh` and checks `guard.current(g)` (Home `+page.svelte:163-214`, Alerts `:767-871` plus `listGuard`, Category `:392-427`, Suricata `:55-88`, Threats `:382-405`, Compliance `:595-671`, IoT `:188-212` plus `drawerGuard`, Certificates `:88-149`). The only loader that understates a failure is Threats (A-8).

### Slice B: device and traffic pages

| Page | Card | Loading | Empty | Error | Stale | Disabled | Notes |
|---|---|---|---|---|---|---|---|
| devices | KPI Total devices | Y (—) | Y | Y (sub) | Y (sub) | n/a | |
| devices | KPI Online now | Y | Y | Y | Y | Y (custom window ended) | |
| devices | KPI New in 24 h | Y | Y | Y | Y | n/a | |
| devices | KPI Top consumer | Y (—) | Y (—) | conflated: shows — with no reason | N: kept old data, no marker | n/a | B-5 |
| devices | By type | Y | Y | Y (capture mode / registry) | Y (amber note) | Y (not mirror mode, explained) | Type and OS unhedged (B-3) |
| devices | All devices table | Y | Y (+ filter-empty) | Y | Y (page subtitle) | n/a | "OS" and "Type" columns (B-3) |
| devices/[ip] | Hero / identity | Y | Y (not found) | Y | Y (amber notice) | n/a | OS chip unhedged (B-3); "Online" chip goes stale (B-5) |
| devices/[ip] | KPIs (traffic, upload share, connections, alerts) | Y (hidden until device) | Y | Y (hero error) | Y (page notice) | n/a | |
| devices/[ip] | Live bandwidth | Y | Y (measuring) | Y (400/503/other) | Y (last measured N s ago) | Y (off / unsupported) | Model card |
| devices/[ip] | Bandwidth over time | Y | Y | Y (via hero) | Y (page notice) | n/a | |
| devices/[ip] | Risk score | Y | conflated: no data shows error | Y | Y | n/a | B-11 |
| devices/[ip] | Smart alerts | Y | Y | Y (chip "check failed") | Y (cleared on failure) | n/a | |
| devices/[ip] | Traffic categories | Y | Y | Y | Y | n/a | |
| devices/[ip] | Top services / Top destinations / DNS activity | Y | Y | Y (via hero) | Y (page notice) | n/a | |
| devices/[ip] | Top ports | Y | Y | Y | Y | n/a | |
| devices/[ip] | Recent connections | Y | Y | Y | Y (cleared) | n/a | |
| devices/mac/[mac] | Hero | Y | Y (not found) | Y | N: kept old device, no marker | n/a | Category chip unhedged |
| devices/mac/[mac] | KPI Traffic | Y (—) | Y | Y | Y | n/a | |
| devices/mac/[mac] | KPI Connections | Y (—) | Y | conflated: — with no reason | N | n/a | |
| devices/mac/[mac] | Live bandwidth | Y | Y | Y | Y | Y | |
| devices/mac/[mac] | Top destinations / Protocols | conflated: loading shows empty on range change | Y | Y (first load only) | N | n/a | B-6 |
| devices/mac/[mac] | Bandwidth / DNS / Alerts | never rendered | never rendered | never rendered | — | — | Daemon lacks these fields (B-6) |
| address/[ip] | Threat-list chip | n/a | Y | Y ("Not checked") | Y | n/a | Green check overstates (B-9) |
| address/[ip] | KPIs | Y (—) | Y | Y (page notice) | Y (page notice) | n/a | Byte figures say "Not measured" / "at least" |
| address/[ip] | Connections over time | Y | Y | Y | Y | n/a | |
| address/[ip] | Who it is | Y | Y (None) | Y (couldn't look it up) | N: cached rDNS/WHOIS shown as "looked up now" | Y (click to look up) | B-7 |
| address/[ip] | Devices / Ports / TLS names | Y | Y | Y | Y | n/a | Partial-list notices |
| address/[ip] | Connections table | Y | Y | Y | Y (cleared) | n/a | Capped at 10k, said so |
| domain/[name] | All KPIs and cards | Y | Y | Y | Y (page notice) | n/a | "Too many to count" handled |
| geoip/[ip] | Result | Y | n/a | Y (HTTP only) | n/a | conflated: missing DB shows "Unknown" | B-8 |
| geoip/[ip] | Map | Y (hidden) | Y (hidden) | Y (hidden) | n/a | n/a | Loads openstreetmap.org (outside scope) |
| traffic/[category] | Empty / error wrapper | Y | Y | Y | Y (page notice) | n/a | |
| traffic/[category] | KPIs bytes / devices / connections + trend | Y | Y | Y | Y (page notice); trend may use old prev window | n/a | "+N new" wording (B-12) |
| traffic/[category] | KPI Share of network | Y (—) | Y | conflated: — with no reason | N | n/a | B-5 |
| traffic/[category] | Bandwidth over time | Y | Y | Y | Y | n/a | |
| traffic/[category] | Top services / Per-device | Y | Y | Y (wrapper) | Y (page notice) | n/a | |
| connections | Summary strip | Y | Y | Y | Y | n/a | |
| connections | Session volume | Y | Y | Y | Y | n/a | |
| connections | Protocols / Top sources / Top destinations | Y | Y | Y | N in card (Summary card has the note) | n/a | B-5 |
| connections | Network flow | Y | Y | Y | Y | n/a | |
| connections | Sessions table | Y | Y | Y | Y (cleared, "—" total) | n/a | "Every session" copy (B-12) |
| dns | KPIs | Y (—) | Y | Y (page notice) | Y | n/a | Avg resolution 0.0 ms when unmeasured (B-4) |
| dns | Timeline / Most looked-up / Domains / Query types / NXDOMAIN | Y | Y | Y | Y (in-card) | n/a | Shared `section` helper |
| dns | DNS by device | Y | Y | Y | Y (cleared) | Y (no device chosen) | |
| dns | Suspicious patterns | Y | Y (check icon + scope sentence) | Y | Y (error replaces) | n/a | |
| bandwidth | Month KPIs | Y | Y | Y | Y (page notice) | Y (no cap → no meter) | Corrupt cap file silent; projection (B-10) |
| bandwidth | Daily usage | Y | Y | Y | Y | n/a | |
| bandwidth | Top consumers | Y | Y | Y | Y | n/a | |
| bandwidth | Per-device breakdown | Y | Y | Y | N | n/a | B-5 |
| bandwidth | Heatmap | Y | partial (pale grid, aria only) | Y | Y | n/a | |
| live | Right now strip | Y | Y | Y | page notice only; chip says Live (N) | n/a | 0 B/s from the stub (B-1, B-2) |
| live | Globe | Y | Y | Y (first load) | N: keeps animating old arcs | Y (home location failed / unset) | B-2 |
| live | Top talkers / Protocols | Y | Y | Y (incl. filtered) | page notice only | n/a | |
| live | Live connections feed | Y | Y | Y | page notice only | n/a | |

### Refresh contract / load guard
- All 11 pages call `registerPageRefresh` and check a guard (`guard.current(g)`, or `seq` for side lookups) before writing state.
- No loader returns `'ok'` after a failed request that feeds visible data:
  - live returns `'partial'` when the filtered side request fails, and `'failed'` on its catch;
  - connections uses a local `outcome()` that includes the table.
- Device-name lookups (`getRegistryDevices`) on address, domain and connections are left out of the outcome on purpose. When they fail, rows fall back to IP addresses, which is honest.
- Actions outside the contract keep their own guards: the connections table filters (`tableGuard`), the DNS device lookup (`deviceLookupSeq`), and the device and address connection pagers (`connGuard`).

### Slice C: system, settings, setup, Go Live, changelog, investigations, logs, shell

| Page | Card | Loading | Empty | Error | Stale | Disabled | Notes |
|---|---|---|---|---|---|---|---|
| system | System health (Pipeline) | Y (Checking…) | n/a | Y (unknown · Request failed) | Y (drops to unknown) | Y (SMART null → unknown) | "Healthy" scope is too narrow (C-9) |
| system | System overview | Y | n/a | Y | Note | n/a | |
| system | OpenSearch | Y | n/a | Y | N (body says "Connected", chip says "Unknown") | n/a | C-20 |
| system | Bridge and failover (BridgeStatus) | Y | n/a | Y | Note | Y (bridge mode only; mode failure → error) | polls every 15 s |
| system | Storage | Y | Y | Y | Note | n/a | |
| system | Drive health | Y | n/a | Y | Note | Y (healthy null → "Unknown") | |
| system | Services (TShark/CyberChef) | Y | n/a | Y | Y | n/a | |
| system/updates | Versions table | Y | Y | Y | Y | Y ("Not checked", "Unknown") | |
| system/updates | Updates banner and panel | Y | n/a | Y | n/a | Y (applies_with) | |
| system/updates | History | Y | Y | Y | n/a | n/a | |
| system/cyberchef | Status | Y | n/a | Y | Note | Conflated: a daemon-side check failure shows "isn't running" | C-18 |
| system/cyberchef | Quick recipes | N | Conflated: failure shows "No quick recipes" | N | Note | n/a | C-18 |
| infrastructure | KPIs (Disk used, Indices, Packet loss, Latency) | N (shows "--") | n/a | Conflated: "--" | Note (banner) | Y (latency "Not measured") | |
| infrastructure | Capture pipeline | Y (unknown) | n/a | Y (No reading) | N: stages keep the last value as ok | n/a | C-6, C-12 |
| infrastructure | Bridge / capture port | Y | n/a | Y | Note | Y (mode switch) | |
| infrastructure | Packet capture | Y | n/a | Y | Y ("Couldn't refresh the loss figures") | n/a | |
| infrastructure | Zeek / Suricata | N | n/a | Conflated: "--" | N (silent last value) | n/a | C-12, C-13 |
| infrastructure | Filebeat / Logstash | Y | n/a | Y | Note | n/a | pipelines table hides on failure |
| infrastructure | OpenSearch cluster | Y | Y (no indices) | Y | Note | n/a | templates hide on failure |
| infrastructure | UniFi (status, devices, networks, WiFi, posture, WAN, VPN) | Y | Y | Y | Note | Y (not configured) | |
| settings | Notification preferences | N | n/a | Y (load failure disables save) | n/a | n/a | save is a no-op shown as success (C-1); test always succeeds (C-2) |
| settings | Retention health | Y | n/a | Y | Note | n/a | "Never (daemon starting…)" when prune is null |
| settings | Data retention policy | Y | n/a | Y (save disabled) | n/a | n/a | save outcome is honest |
| settings | Manual data cleanup | Y | n/a | Y | n/a | n/a | errors shown in green (C-15) |
| settings | PCAP capture | Y | n/a | Y (changes off) | N (read once) | Y (disabled vs stopped vs unknown) | |
| settings | API keys | Y | n/a | Conflated: failure looks like "not configured" | n/a | n/a | C-14 |
| settings | Excluded IPs | Y | Y | Y (changes off) | n/a | n/a | |
| settings | UniFi controller | Y | n/a | Y | N (read once) | Y (not configured) | |
| settings | Live bandwidth (component) | Y | n/a | Y | Y (follow-failed note) | Y (off by default) | |
| settings | About | N | n/a | Conflated: "Unknown" | n/a | n/a | |
| settings/backup | Export / Import | n/a | n/a | Y | n/a | n/a | "every setting" overclaims (C-10); no registerPageRefresh (action page) |
| settings/notifications | Channels | Y | Y | Y | Note ("—" counts) | n/a | rules never fire (C-4) |
| settings/notifications | Routing rules | Y | Y | Y | Note | n/a | C-4 |
| settings/notifications | Recent deliveries | Y | Y | Y | Note | n/a | |
| settings/suricata-rules | Rules Suricata runs / Rule sources / Schedule / ET Pro / Own rules | Y | Y | Y | Y | Y (owner rules unmounted, ET Pro off) | |
| setup | Requirements | Y | n/a | Y ("couldn't check") | n/a | n/a | no registerPageRefresh (wizard) |
| setup | Interfaces | Y | n/a | Y (mock → error) | n/a | n/a | |
| setup | Storage | Y | n/a | N: mock shown as real (lead's finding) | n/a | n/a | |
| setup | Verification | Y (checking) | n/a | Conflated: daemon down shows "Running" | n/a | Y (warn = couldn't check) | C-5 |
| go-live | Readiness / Wiring | Y | n/a | Y | n/a | Y (DHCP mode → DhcpGoLive) | no registerPageRefresh; polls on its own |
| go-live | Bridge health | Y | n/a | Y (notice) | N: old chip and bypass button kept | Y (bypass notice) | lead's finding for :428-431; C-11 |
| go-live (DhcpGoLive) | Gateway status / leases | Y | Y | Y | Note (pollError), but chips are stale | Y | C-7 |
| changelog | Events | Y | Y | Y | Y (cleared on failure) | n/a | 7-day window unstated (C-19) |
| investigations | KPIs / list / drawer | Y | Y | Y | Y ("—", never 0) | n/a | |
| logs | KPIs + 5 sections + log table | Y | Y | Y | Y (stale notes) | n/a | |
| shell | Capture chip | Y (Checking mode…) | n/a | Y ("Capture status unknown") | Y | Conflated: crashed capture shows "not set up" | C-8 |
| shell | Storage foot | Y | n/a | Y (hidden) | Y | n/a | |
| shell | Alert badge | N | Conflated: failure looks like 0 | N | n/a | n/a | C-17 |
| shell | TopBar Updated / Refresh | n/a | n/a | partial → chip; failed → no chip (lead's finding) | Y ("Updated N min ago") | n/a | |
| shell | Notification bell | Y | Y | Y (in the dropdown) | Note (in the dropdown); the badge stays stale | n/a | C-3, C-16 |

### Refresh contract
- `registerPageRefresh` is missing on setup, go-live and settings/backup. These are flow or action pages, and go-live polls on its own.
- The settings loader returns an outcome only for the storage-status and About reads (`routes/settings/+page.svelte:679-686`). The forms load once, outside the contract, as documented.
- The changelog loader returns 'ok' when the event-types request fails, which is acceptable: that list only fills the filter.
- No loader in this slice returns 'ok' after a failed request that feeds visible data.

### Lead: PCAP, Packets, Lookups, Tools, Login

| Page | Card | Loading | Empty | Error | Stale | Disabled | Notes |
|---|---|---|---|---|---|---|---|
| /pcap | KPIs (files, total captured) | Y ('…'/skeleton) | Y | Y ('—' via filesUnknown) | N/A | N/A | |
| /pcap | Capture chip and switch | Y | N/A | Y (unknown, switch disabled) | conflated: a failed re-read keeps the last chip state (pcap/+page.svelte:376-379) | Y (Stopped) | |
| /pcap | Capture timeline / Available files | Y | Y | Y | N | N/A | cleared on failure (:372) |
| /pcap | Search results / preview | Y | Y (two empty texts: unreadable files vs none) | Y | N/A | N/A | |
| /packets | Start KPIs | Y ('…') | N/A | Y ('—' + "Couldn't load") | N | Y (capture Off/Unknown) | StartKpis.svelte:34-83 |
| /packets | Saved captures | Y | Y | Y | N | N/A | |
| /packets | Results | Y (elapsed timer) | Y | Y | N/A | N/A | |
| /lookup/dns/[ip], /lookup/whois/[ip] | Result | Y | Y (no record vs timeout) | Y | conflated: cached answers (api/lookup.py TTL cache) not marked as cached | N/A | |
| /lookup/dns, /lookup/whois | input only | N/A | Y | N/A | N/A | N/A | no backend |
| /tools/ping | Ping/traceroute | Y | N/A | Y | N/A | N/A | no RTT on 100 % loss |
| /tools/dns-recon | Records | Y | Y | Y (per-type errors joined) | N/A | N/A | |
| /tools/ssl-cert | Cert | Y | Y | Y | N/A | N/A | |
| /tools/mac-lookup | Vendor | Y | Y | conflated: missing OUI DB or failed fallback shows "Unknown vendor" (L-11) | N/A | N/A | |
| /tools/cyberchef | Status | Y | N/A | Y | N | Y (not running) | |
| /tools/cyberchef | Quick recipes | N | N | conflated: failure hides the card, loader returns 'ok' | N/A | N/A | L-12 |
| /tools/ipv6 | MAC maker | Y | Y | conflated as L-11 | N/A | N/A | address analysis is client-side |
| /tools, /tools/base64, /tools/subnet-calc, /tools/port-reference | none (client-side) | N/A | N/A | N/A | N/A | N/A | |
| /tools/tshark | redirect to /packets | N/A | | | | | |
| /login | form | N/A | N/A | Y | N/A | N/A | not a data page |
