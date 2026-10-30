# Code Review Fix Tracker (review of 2026-10-30)

**Progress:** <!--P-->8 / 273 fixed<!--/P--> · CRITICAL <!--CRITICAL-->2/6<!--/CRITICAL--> · HIGH <!--HIGH-->1/37<!--/HIGH--> · MEDIUM <!--MEDIUM-->0/121<!--/MEDIUM--> · LOW <!--LOW-->5/109<!--/LOW-->

**Findings:** `docs/reviews/2026-10-30-code-review.md` ([PR #146](https://github.com/EliasMarine/NetTap/pull/146)). The detail and recommended fix for each ID are there.  
**Linear:** NET-112 (umbrella).  
**Branch:** `fix/code-review-batch-1`, stacked on `phase-4/dhcp-gateway-mode` (PR #145).

## How this works

- Each fix is one commit that names the finding ID(s) in its subject. That same commit ticks the row here and adds a line to the fix log.
- Each fix also gets a Linear sub-issue under NET-112, marked Done with a link to the commit.
- To find the change for an ID, search the history: `git log --grep=CR-001`.
- **Fixed** means the code changed and the tests pass. Device checks are listed in the fix log once you confirm them on the NetTap box.
- The six findings fixed on the DHCP branch are already ticked.

## Batch 1: fix first

Item 8 of the review's fix-first table says CR-018; that is a typo for CR-017. CR-018 belongs to the PCAP group and is listed there.

- [x] <!--B:MS-001-->MS-001: OpenSearch role mapping wiped on every start (root cause of Chain 11)
- [x] <!--B:CR-003-->CR-003: OpenSearch Dashboards open to the LAN with all_access
- [ ] <!--B:CR-021-->CR-021: Arkime viewer on :8005 with a forgeable admin token
- [ ] <!--B:CR-022-->CR-022: Grafana without NetTap login, anonymous viewer, admin/nettap
- [ ] <!--B:CR-002-->CR-002: Emergency prune deletes every OpenSearch index
- [ ] <!--B:CR-001-->CR-001: PCAP cleanup never deletes anything
- [ ] <!--B:CR-018-->CR-018: Capture stop flag at 95% has no effect
- [ ] <!--B:CR-020-->CR-020: Two full-PCAP writers fill the disk
- [ ] <!--B:MS-002-->MS-002: Full-time PCAP has no retention
- [ ] <!--B:CR-004-->CR-004: Wizard 'Verify' builds the live bridge
- [ ] <!--B:CR-025-->CR-025: nettap.service runs compose down on stop
- [ ] <!--B:CR-034-->CR-034: Login has no effective rate limit
- [ ] <!--B:CR-017-->CR-017: Generated ISM policies never manage a real index
- [ ] <!--B:CR-038-->CR-038: Static ISM policy matches no real index
- [ ] <!--B:LD-001-->LD-001: Daemon boot units are never enabled

## Fix log

| Date | ID(s) | What changed | Tests |
|------|-------|--------------|-------|
| 2026-10-30 | CR-007, CR-165, CR-166, CR-167, CR-212, CR-247 | Fixed as part of DHCP gateway mode (PR #145) | pytest 2315, vitest 1942 |
| 2026-10-30 | MS-001 (NET-113) | opensearch gets Malcolm's 8 ROLE_* vars, so its own startup builds and pushes the full role mapping; deploy-malcolm.sh waits for that push instead of overwriting it; fix-opensearch.sh writes the minimal mapping only on an old container. Device check pending (Chain 21) | bats: 2 new deploy + 1 new compose test, fail without the fix |
| 2026-10-30 | CR-003 | NET-114: /dashboards/ needs a NetTap login (nginx auth_request to /api/auth/me); nginx sets X-Forwarded-User/Roles from the session and drops the client's. Still open: direct container access to dashboards:5601 and OpenSearch :9200 with spoofed headers | vitest +2, bats +3 (new test_nginx_conf.bats), fail without the fix |
<!--LOG-->

## All findings

### CRITICAL (6)

| Done | ID | Area | Location | Finding | Status |
|------|----|------|----------|---------|--------|
| ☐ | CR-001 | daemon-core | `daemon/storage/manager.py:108` | PCAP cleanup never deletes anything: wrong path, read-only mount, top-level glob only | Open |
| ☐ | CR-002 | daemon-core | `daemon/storage/manager.py:462` | Emergency prune deletes every OpenSearch index, today's live index included, and repeats every cycle | Open |
| ✅ | CR-003 | malcolm-stack, scripts-infra, security-crosscut | `docker/nginx.conf:187` | OpenSearch Dashboards is published on :443 with no authentication and all_access backend credentials | Fixed (batch 1) |
| ☐ | CR-004 | contracts-integration, daemon-api-A, daemon-services-A, web-pages-A, web-server | `web/src/routes/setup/+page.svelte:368 (+4)` | Wizard 'Verify Configuration' creates the live bridge, and reports success only when creation failed | Open |
| ✅ | MS-001 | malcolm-stack | `docker/docker-compose.yml:98` | OpenSearch lacks ROLE_ADMIN, so every container start wipes the role mapping and pushes the empty one | Fixed (batch 1) |
| ☐ | MS-002 | malcolm-stack | `docker/docker-compose.yml:694` | Full-time PCAP capture has no retention; emergency prune then deletes all OpenSearch data | Open |

### HIGH (37)

| Done | ID | Area | Location | Finding | Status |
|------|----|------|----------|---------|--------|
| ☐ | CR-005 | daemon-api-A | `daemon/api/alerts.py:51` | Suricata decoder-noise filter never matches anything | Open |
| ☐ | CR-006 | daemon-api-A | `daemon/api/alerts.py:404` | Synchronous OpenSearch calls block the daemon's event loop | Open |
| ✅ | CR-007 | contracts-integration, daemon-api-B, daemon-services-A, web-pages-A, web-server | `daemon/api/setup.py:24 (+3)` | Setup wizard's capture mode and NIC choice never reach the daemon or the capture containers | Fixed (PR #145) |
| ☐ | CR-008 | daemon-api-A, daemon-services-C | `daemon/services/alert_intelligence.py:889 (+1)` | Alert suppressions, false-positive marks, baselines and the TI cache are written to tmpfs /tmp and lost on every restart | Open |
| ☐ | CR-009 | daemon-api-A, daemon-services-C | `daemon/services/alert_intelligence.py:1181` | Smart Alerts silently drop alert groups past the first 200 composite buckets | Open |
| ☐ | CR-010 | daemon-api-A, daemon-services-A | `daemon/services/bridge_health.py:317 (+1)` | Bypass enable reports success but does not stop inspection | Open |
| ☐ | CR-011 | daemon-services-A | `daemon/services/bridge_manager.py:154` | create_bridge has no management-NIC guard, no name validation and no rollback on partial failure | Open |
| ☐ | CR-012 | contracts-integration, daemon-api-A, daemon-services-A, web-pages-A | `daemon/services/config_backup.py:39 (+3)` | Backup and restore read and write config files that the services never use | Open |
| ☐ | CR-013 | daemon-services-B | `daemon/services/device_fingerprint.py:186` | get_mac_for_ip reads a flat 'source.mac' key that OpenSearch never returns, so every device has no MAC | Open |
| ☐ | CR-014 | daemon-services-B | `daemon/services/device_registry.py:395` | The nettap-devices registry is never populated: no production code calls register_device or any enrich_* method | Open |
| ☐ | CR-015 | daemon-services-C | `daemon/services/notification_hub.py:473` | Routing rules never fire: process_event has no caller | Open |
| ☐ | CR-016 | daemon-services-C | `daemon/services/threat_detection.py:143` | Beaconing detection checks only 300 pairs and can exceed max_buckets, then silently returns no beacons | Open |
| ☐ | CR-017 | daemon-core | `daemon/storage/ilm_generator.py:109` | Generated ISM policies never manage a real index, so age-based retention never runs | Open |
| ☐ | CR-018 | daemon-core | `daemon/storage/manager.py:109` | Writing the capture stop flag at 95% has no effect | Open |
| ☐ | CR-019 | gap-pass, malcolm-stack | `docker/docker-compose.yml:290` | Filebeat mounts the Zeek and Suricata log volumes read-only, so their logs are never pruned | Open |
| ☐ | CR-020 | gap-pass | `docker/docker-compose.yml:509` | Two full-PCAP writers fill the disk; Arkime keeps it at 85-90% and the daemon's 'stop capture' flag is never read | Open |
| ☐ | CR-021 | gap-pass | `docker/docker-compose.yml:513` | Arkime viewer runs on host port 8005, and its admin S2S token can be forged with the public fallback secret | Open |
| ☐ | CR-022 | malcolm-stack, scripts-infra, security-crosscut | `docker/docker-compose.yml:824` | Grafana is reachable without NetTap login, with anonymous viewer and default admin password 'nettap' | Open |
| ☐ | CR-023 | scripts-infra | `scripts/bridge/setup-bridge.sh:403` | --dry-run --persist writes the real netplan bridge, NetworkManager and sysctl configs | Open |
| ☐ | CR-024 | malcolm-stack, scripts-infra | `scripts/install/deploy-malcolm.sh:601` | (( applied++ )) under set -e kills the installer at the first ISM policy | Open |
| ☐ | CR-025 | scripts-infra | `scripts/install/install.sh:397` | nettap.service ExecStop runs 'docker compose down', so every reboot recreates OpenSearch and breaks auth | Open |
| ☐ | CR-026 | gap-pass, scripts-infra | `scripts/install/setup-firewall.sh:225` | Documented firewall hardening blocks nettap-web from reaching the daemon | Open |
| ☐ | CR-027 | contracts-integration, web-components | `web/src/lib/api/bridge.ts:37 (+1)` | The System page bypass control reads `active` but the daemon sends `bypass_active`, so bypass cannot be turned off there | Open |
| ☐ | CR-028 | contracts-integration, web-components | `web/src/lib/components/NotificationBell.svelte:50 (+1)` | Each page load re-sends alert notifications to email and webhook | Open |
| ☐ | CR-029 | web-pages-B | `web/src/routes/alerts/+page.svelte:986` | Alerts page says "No Alerts" when the daemon or OpenSearch fails | Open |
| ☐ | CR-030 | web-server | `web/src/routes/api/[...path]/+server.ts:35` | PCAP downloads through the catch-all proxy are cut off after 10 s in total | Open |
| ☐ | CR-031 | web-pages-A, web-server | `web/src/routes/api/notifications/config/+server.ts:43 (+1)` | Saving notification settings reports success but discards everything | Open |
| ☐ | CR-032 | web-pages-C | `web/src/routes/compliance/+page.svelte:431` | Security Posture shows grade A / 100% 'excellent' when its data fails to load | Open |
| ☐ | CR-033 | web-pages-A | `web/src/routes/go-live/+page.svelte:45` | Go Live falls back to eth0/eth1, and the wizard never stores the real NIC names on success | Open |
| ☐ | CR-034 | security-crosscut, web-pages-A, web-server | `web/src/routes/login/+page.server.ts:7` | Login form action has no rate limit; the only limiter is unused and keyed on nginx's IP | Open |
| ☐ | CR-035 | web-pages-B | `web/src/routes/system/updates/+page.svelte:282` | Apply Updates shows "Update Complete" after the 10 s proxy timeout while the update is still running | Open |
| ☐ | CR-036 | web-pages-C | `web/src/routes/threats/+page.svelte:145` | Threats page shows a clean 'no threats' report when the threat analysis fails | Open |
| ☐ | CR-038 | malcolm-stack, scripts-infra | `config/opensearch/ilm-policy.json:92 (+1)` | ISM policies match no real index and use rollover without an alias, so tiered retention never applies | Open |
| ☐ | LD-001 | lead (DHCP design recon) | `daemon/services/bridge_manager.py:635 (+1)` | Boot units written by the daemon are never enabled: the wants/ symlinks point at the container path | Open |
| ☐ | MS-003 | malcolm-stack | `docker/docker-compose.yml:473` | A disabled packet-capture setting is turned back on at every boot | Open |
| ☐ | MS-004 | malcolm-stack | `docker/docker-compose.yml:518` | arkime-live has no curlrc mount, so it hangs forever and never captures or initialises the DB | Open |
| ☐ | MS-005 | malcolm-stack | `scripts/install/deploy-malcolm.sh:521` | malcolm_template is pushed with a literal REPLACER index pattern, so it never applies | Open |

### MEDIUM (121)

| Done | ID | Area | Location | Finding | Status |
|------|----|------|----------|---------|--------|
| ☐ | CR-037 | malcolm-stack, scripts-infra | `config/grafana/provisioning/datasources/datasource.yaml:6` | Provisioned Grafana datasources and dashboards cannot return data | Open |
| ☐ | CR-039 | daemon-api-A | `daemon/api/alerts.py:342` | Category alert list and category detail/timeline disagree on membership | Open |
| ☐ | CR-040 | daemon-api-A | `daemon/api/bandwidth.py:68` | ISP data-cap totals drop traffic from excluded IPs | Open |
| ☐ | CR-041 | daemon-api-A | `daemon/api/devices.py:345` | Device list makes 3–4 sequential blocking queries per device | Open |
| ☐ | CR-042 | daemon-api-A | `daemon/api/devices.py:509` | Device detail connection and alert counts stop at 10,000 | Open |
| ☐ | CR-043 | daemon-api-B | `daemon/api/live.py:124` | Live dashboard GeoIP fallback makes one synchronous OpenSearch search per connection on the event loop | Open |
| ☐ | CR-044 | daemon-api-B | `daemon/api/logstash.py:16` | Host-networked daemon calls Docker-DNS names (logstash, nettap-cyberchef) that do not resolve on the host | Open |
| ☐ | CR-045 | daemon-api-B, daemon-services-A, security-crosscut | `daemon/api/pcap.py:170` | Filtered PCAP download leaks its temp file into the daemon's 50 MB /tmp tmpfs | Open |
| ☐ | CR-046 | daemon-api-B | `daemon/api/risk.py:185` | Many handlers call the synchronous OpenSearch client directly on the event loop | Open |
| ☐ | CR-047 | daemon-api-B | `daemon/api/risk.py:381` | The same device gets different risk scores on the list and on its detail page | Open |
| ☐ | CR-048 | contracts-integration | `daemon/api/server.py:211` | Synchronous OpenSearch calls block the daemon's event loop | Open |
| ☐ | CR-049 | daemon-services-A | `daemon/api/server.py:919` | CyberChef status and recipe URLs use a Docker DNS name the host-networked daemon cannot resolve | Open |
| ☐ | CR-050 | daemon-api-B | `daemon/api/server.py:1120` | Suricata rule-sources path is one directory short, so the rules page shows no sources | Open |
| ☐ | CR-051 | daemon-api-B | `daemon/api/settings.py:33` | Settings > API Keys saves values that no component reads, but reports them as configured | Open |
| ☐ | CR-052 | daemon-api-B | `daemon/api/setup.py:156` | Wizard storage settings: a failed retention save is swallowed and the response is still 'ok' | Open |
| ☐ | CR-053 | daemon-core | `daemon/main.py:277` | smart_loop runs blocking subprocess calls on the event loop for up to 90 s | Open |
| ☐ | CR-054 | daemon-services-C | `daemon/services/alert_intelligence.py:722` | categorize_alert's bare substring match misfiles common benign signatures as Malware & C2 or Tor | Open |
| ☐ | CR-055 | daemon-services-C | `daemon/services/alert_intelligence.py:935` | After a suppression expires, suppressing the same signature again does nothing but reports success | Open |
| ☐ | CR-056 | daemon-services-C | `daemon/services/alert_intelligence.py:1028` | Alert 'baseline' mixes every request's time range and device, which triggers spurious +15 threat-score boosts | Open |
| ☐ | CR-057 | daemon-api-A | `daemon/services/alert_intelligence.py:1225` | OpenSearch failures come back as 200 with empty results | Open |
| ☐ | CR-058 | daemon-api-A | `daemon/services/bandwidth_tracker.py:83` | Bandwidth totals use client.bytes/server.bytes; the rest of the UI uses source/destination.bytes | Open |
| ☐ | CR-059 | daemon-services-B | `daemon/services/bandwidth_tracker.py:250` | Per-device bandwidth picks the top N by connection count, not bytes, so 'Top consumers' and '% of Total' are wrong | Open |
| ☐ | CR-060 | daemon-api-A, daemon-services-A | `daemon/services/bridge_manager.py:119` | Reconfiguring an existing br0 leaves old member ports attached | Open |
| ☐ | CR-061 | daemon-services-A | `daemon/services/bridge_manager.py:262` | teardown_bridge leaves netplan/systemd/sysctl persistence, so the bridge returns on reboot | Open |
| ☐ | CR-062 | daemon-services-C | `daemon/services/cert_monitor.py:69` | Certificate and DNS analytics still hide excluded IPs | Open |
| ☐ | CR-063 | daemon-services-C | `daemon/services/cert_monitor.py:80` | Certificate stats and detections cover only the latest 1,000 SSL events and count connections as certificates | Open |
| ☐ | CR-064 | daemon-services-A | `daemon/services/config_backup.py:174` | Config import writes section content unvalidated: a bad bandwidth_cap crash-loops the daemon; running services never reload | Open |
| ☐ | CR-065 | daemon-services-B | `daemon/services/device_fingerprint.py:27` | OS patterns are ordered generic-first and use labels the category mapper doesn't recognize, so consoles, TVs and Windows PCs are misclassif… | Open |
| ☐ | CR-066 | daemon-services-C | `daemon/services/dns_analytics.py:388` | DNS page tunneling and long-name checks only look at the top 200 most-queried domains | Open |
| ☐ | CR-067 | daemon-services-C | `daemon/services/dns_analytics.py:442` | DNS 'total queries' hero stat is capped at 10,000 | Open |
| ☐ | CR-068 | daemon-services-B | `daemon/services/excluded_ips.py:97` | LAN subnet auto-detection runs once at startup with an unbounded, scripted full-index scan on the event loop, and never re-runs | Open |
| ☐ | CR-069 | daemon-services-C | `daemon/services/geoip_service.py:461` | GeoIP lookup caches 'Unknown' and OpenSearch failures forever, and runs sync OpenSearch searches on the event loop | Open |
| ☐ | CR-070 | daemon-api-A | `daemon/services/investigation_store.py:111` | A torn JSON write wipes all investigations and alert acks | Open |
| ☐ | CR-071 | daemon-services-B | `daemon/services/iot_monitor.py:258` | IoT device entries are frozen at first discovery (ip, last_seen), which misattributes isolation pairs after DHCP churn | Open |
| ☐ | CR-072 | daemon-services-B | `daemon/services/iot_monitor.py:310` | IoT OUI classification uses bare substring matching, so 'ring' matches 'Manufacturing' and 'Engineering' | Open |
| ☐ | CR-073 | daemon-services-B | `daemon/services/iot_monitor.py:562` | Encryption ratio counts all DNS/NTP/mDNS/SSDP sessions as unencrypted, inflating 'unencrypted' findings and lowering every IoT grade | Open |
| ☐ | CR-074 | daemon-services-B | `daemon/services/lan_anomaly_detector.py:58` | ARP-spoofing and IP-conflict detection query an 'arp' Zeek dataset the deployed stack never produces, so both always report all clear; the… | Open |
| ☐ | CR-075 | daemon-services-B | `daemon/services/lan_anomaly_detector.py:157` | Rogue-DHCP detection groups by source.ip (the DHCP client), so normal clients are flagged as critical rogue DHCP servers | Open |
| ☐ | CR-076 | daemon-services-A | `daemon/services/mirror_manager.py:115` | Mirror setup flushes IPs on the configured NIC at every daemon start with no management guard | Open |
| ☐ | CR-077 | daemon-api-B, daemon-services-C | `daemon/services/notification_hub.py:273` | Email channel test runs blocking smtplib with no timeout on the daemon event loop | Open |
| ☐ | CR-078 | daemon-api-B | `daemon/services/pcap_search.py:160` | PCAP search runs tshark over every file sequentially with no overall limit and holds a shared semaphore slot | Open |
| ☐ | CR-079 | daemon-api-B, daemon-services-A | `daemon/services/pcap_search.py:367` | Filtered download merges into a fixed shared path in a 100 MB tmpfs and reports failures as 'no matching data' | Open |
| ☐ | CR-080 | daemon-services-C | `daemon/services/ssl_cert_service.py:156` | Unauthenticated SSL-cert tool lets any LAN client probe arbitrary host:port from the appliance and leaks openssl processes | Open |
| ☐ | CR-081 | daemon-services-C | `daemon/services/suricata_rules.py:21` | Suricata rules manager points at paths that don't exist or are read-only in the container | Open |
| ☐ | CR-082 | daemon-services-C | `daemon/services/threat_detection.py:252` | Lateral movement keeps only the first 300 triples, so internet scanners crowd out LAN pairs | Open |
| ☐ | CR-083 | daemon-services-C | `daemon/services/threat_detection.py:353` | DGA/tunnel detection only looks at the 500 most-queried names, so it can't see the low-count names those threats produce | Open |
| ☐ | CR-084 | daemon-services-C | `daemon/services/traffic_classifier.py:873` | Category drill-downs use different matching from the category totals, so numbers disagree and traffic is counted twice | Open |
| ☐ | CR-085 | daemon-services-A | `daemon/services/tshark_service.py:299` | TShark timeouts kill only the docker CLI, leaving tshark running; the output cap is not enforced | Open |
| ☐ | CR-086 | daemon-services-B | `daemon/services/unifi_integration.py:610` | UniFi client cache is only filled by an explicit Test/clients call and never refreshed, so aliases vanish after restart or go stale and get… | Open |
| ☐ | CR-087 | daemon-services-A | `daemon/services/update_executor.py:340` | Update executor cannot run in the shipped daemon container; every update fails | Open |
| ☐ | CR-088 | daemon-api-B | `daemon/services/update_executor.py:343` | System update apply and rollback cannot work inside the deployed daemon container | Open |
| ☐ | CR-089 | daemon-core | `daemon/storage/manager.py:90` | Tier prefixes put all Malcolm network data in 'cold', so the 80% prune applies cold_days (30) to Zeek and Suricata | Open |
| ☐ | CR-090 | daemon-core | `daemon/storage/manager.py:213` | Disk usage math ignores ext4 reserved blocks, so every threshold triggers about 5 points late | Open |
| ☐ | CR-091 | gap-pass, malcolm-stack | `docker/docker-compose.yml:362` | nettap.zeek is mounted at a path Zeek never reads, and fixing the path would stop Zeek from starting | Open |
| ☐ | CR-092 | gap-pass | `docker/docker-compose.yml:413` | The Suricata rule-source settings are never used; the web UI toggles do nothing | Open |
| ☐ | CR-093 | scripts-infra | `docker/nginx.conf:80` | Static upstreams for optional services take the whole UI down when one of them is not running | Open |
| ☐ | CR-094 | scripts-infra | `scripts/bridge/bypass-mode.sh:39` | Bypass mode targets compose project 'nettap', but the stack runs as project 'docker', so capture is never stopped | Open |
| ☐ | CR-095 | scripts-infra | `scripts/bridge/setup-bridge.sh:388` | IPv6 sysctl failure triggers the ERR rollback, which also tears down a pre-existing working bridge | Open |
| ☐ | CR-096 | scripts-infra | `scripts/bridge/setup-bridge.sh:418` | Persisted br0 netplan leaves IPv6 link-local on, so networkd re-enables IPv6 on the 'invisible' bridge after reboot | Open |
| ☐ | CR-097 | scripts-infra | `scripts/generate-secrets.sh:28` | generate-secrets.sh writes to /opt/nettap/.env, which nothing reads, while docs say secrets are auto-generated | Open |
| ☐ | CR-098 | gap-pass | `scripts/install/install.sh:459` | No default install firewalls the host-network listeners (Arkime viewer :8005, daemon :8880) | Open |
| ☐ | CR-099 | scripts-infra | `scripts/install/preflight.sh:284` | Current internet/SSH NIC can be assigned to the bridge, and install.sh bridges it before pulling images | Open |
| ☐ | CR-100 | web-server | `web/src/hooks.server.ts:21` | /api/tools/* and /api/lookup/* are public, so anyone who can reach the UI can make the appliance probe the network | Open |
| ☐ | CR-101 | web-server | `web/src/hooks.server.ts:116` | State-changing POSTs without a Content-Type bypass SvelteKit's CSRF origin check | Open |
| ☐ | CR-102 | web-server | `web/src/hooks.server.ts:117` | Unauthenticated /api/* requests get a 302 to an HTML page instead of a 401 | Open |
| ☐ | CR-103 | contracts-integration | `web/src/lib/api/risk.ts:25` | The Compliance page crashes because risk scores come back as `devices`, not `scores` | Open |
| ☐ | CR-104 | contracts-integration | `web/src/lib/api/updates.ts:65` | The Updates page expects version, history and status shapes the daemon does not send | Open |
| ☐ | CR-105 | web-components | `web/src/lib/components/HorizontalBarList.svelte:113` | IP context menu nested inside link or button rows also triggers the row | Open |
| ☐ | CR-106 | web-components | `web/src/lib/components/IPAddress.svelte:150` | 'Filter connections from/to this IP' sends params the Connections page ignores | Open |
| ☐ | CR-107 | web-components | `web/src/lib/components/drawer/content/AlertDrawerContent.svelte:251` | Related Events table reads dotted keys from nested _source, so columns show '--' | Open |
| ☐ | CR-108 | web-components | `web/src/lib/components/drawer/content/ConnectionDrawerContent.svelte:199` | 'Threat Context' shows the source device's recent alerts, not this connection's | Open |
| ☐ | CR-109 | web-components | `web/src/lib/components/drawer/content/InvestigationDrawerContent.svelte:59` | Investigation note is cleared before the save finishes and lost if it fails | Open |
| ☐ | CR-110 | web-components | `web/src/lib/components/tshark/AnalysisPanel.svelte:404` | Hex Dump pane is never given data | Open |
| ☐ | CR-111 | web-components | `web/src/lib/components/tshark/FilterInput.svelte:62` | TShark filter 'Validate' button always reports the filter as invalid | Open |
| ☐ | CR-112 | contracts-integration | `web/src/lib/server/daemon.ts:52` | The 10s proxy timeout is shorter than daemon operations that legitimately run longer | Open |
| ☐ | CR-113 | web-server | `web/src/lib/server/notifications.ts:83` | In-app notifications are written to a read-only path and silently lost on every restart | Open |
| ☐ | CR-114 | web-pages-A | `web/src/routes/+layout.svelte:17` | Capture mode loads once per app session, fails on /login or /setup, and never retries after login | Open |
| ☐ | CR-115 | web-pages-A | `web/src/routes/+layout.svelte:188` | Topbar always shows a green 'Online' status | Open |
| ☐ | CR-116 | web-pages-A | `web/src/routes/+page.svelte:137` | Dashboard ignores the device and protocol filters and keeps '(24h)' labels for any time range | Open |
| ☐ | CR-117 | web-pages-A | `web/src/routes/+page.svelte:196` | Dashboard never shows 'daemon unreachable'; when the daemon is down it claims 'the daemon is running' and shows zero traffic | Open |
| ☐ | CR-118 | web-pages-B | `web/src/routes/alerts/+page.svelte:146` | "Critical" stat card is always 0: it reads category key 'malware-c2' but the daemon sends 'malware_c2' | Open |
| ☐ | CR-119 | web-pages-B | `web/src/routes/alerts/+page.svelte:210` | The "Info" severity pill shows all alerts | Open |
| ☐ | CR-120 | web-pages-B | `web/src/routes/alerts/+page.svelte:399` | Stale responses overwrite newer filter results (alerts, category, IoT, logs) | Open |
| ☐ | CR-121 | web-pages-B | `web/src/routes/alerts/[category]/+page.svelte:305` | The sub-category filter only shows a "Filtered: X" banner; no data is filtered | Open |
| ☐ | CR-122 | web-server | `web/src/routes/api/notifications/from-alerts/+server.ts:41` | Every full page load re-creates notifications (and resends email/webhook) for the same alerts | Open |
| ☐ | CR-123 | web-server | `web/src/routes/api/setup/nics/+server.ts:73` | Setup NIC and storage routes hide daemon errors behind fake data | Open |
| ☐ | CR-124 | web-server | `web/src/routes/api/suricata/rules/update/+server.ts:10` | Long-running daemon operations are proxied with the 10 s default timeout | Open |
| ☐ | CR-125 | web-pages-C | `web/src/routes/certificates/+page.svelte:86` | Certificates page hides MITM issuer-change warnings when the daemon fails | Open |
| ☐ | CR-126 | web-pages-C | `web/src/routes/connections/+page.svelte:320` | Auto-refresh snaps the table back to the page it started on; responses can arrive out of order | Open |
| ☐ | CR-127 | web-pages-C | `web/src/routes/connections/+page.svelte:332` | State filter is applied client-side per page; 'Has Alerts' does nothing | Open |
| ☐ | CR-128 | web-pages-C | `web/src/routes/connections/+page.svelte:424` | Connections ignores the src_ip / dst_ip / filter URL params that other pages link with | Open |
| ☐ | CR-129 | web-pages-C | `web/src/routes/connections/+page.svelte:653` | IPv6 or CIDR in the IP filter breaks the query and shows 'No Connections' | Open |
| ☐ | CR-130 | web-pages-B | `web/src/routes/devices/+page.svelte:77` | Device pages show "no devices", a fake zero-traffic device, or "not found in registry" when the daemon fails | Open |
| ☐ | CR-131 | web-pages-B | `web/src/routes/devices/[ip]/+page.svelte:317` | The connections protocol filter applies only to the current 25-row page, while totals and pagination ignore it | Open |
| ☐ | CR-132 | web-pages-C | `web/src/routes/dns/+page.svelte:579` | DNS page shows 'No NXDOMAIN errors… That's a good sign' and 'No suspicious DNS patterns' when the daemon fails | Open |
| ☐ | CR-133 | web-pages-A | `web/src/routes/go-live/+page.svelte:76` | A transient daemon failure sends live monitoring back to Phase 1 and offers 'Create Bridge' on a running bridge | Open |
| ☐ | CR-134 | web-pages-A | `web/src/routes/go-live/+page.svelte:360` | Phase 3 always says 'Your network is being monitored', and bypass toggle failures are silent | Open |
| ☐ | CR-135 | web-pages-B | `web/src/routes/infrastructure/+page.svelte:169` | Zeek evt/s is overstated 288x and Suricata alerts/s is always 0 | Open |
| ☐ | CR-136 | web-pages-C | `web/src/routes/investigations/+page.svelte:57` | Investigation drawer never refreshes: added notes and status changes do not appear | Open |
| ☐ | CR-137 | web-pages-C | `web/src/routes/investigations/+page.svelte:220` | Create investigation and add note clear the user's input even when the save failed | Open |
| ☐ | CR-138 | web-pages-B | `web/src/routes/iot/+page.svelte:855` | Failed IoT checks are shown as "no cross-segment communication", "all devices look healthy" and "all protocols within expected parameters" | Open |
| ☐ | CR-139 | web-pages-C | `web/src/routes/live/+page.svelte:134` | Live monitor state defects (no in-flight guard, blanking on failed poll, drawer race, highlight id, 'other' filter) | Open |
| ☐ | CR-140 | security-crosscut, web-pages-B | `web/src/routes/logs/+page.svelte:520 (+1)` | CSV export allows formula injection from attacker-controlled log fields | Open |
| ☐ | CR-141 | web-pages-C | `web/src/routes/pcap/+page.svelte:366` | Capture toggle shows ON when capture status is unknown or the container is stopped; clicking it disables capture | Open |
| ☐ | CR-142 | web-pages-A | `web/src/routes/settings/+page.svelte:225` | A failed excluded-IPs load leaves an empty list, and Save then wipes the saved exclusions | Open |
| ☐ | CR-143 | web-pages-A | `web/src/routes/settings/suricata-rules/+page.svelte:72` | A transient load failure blanks the custom-rules editor, and saving wipes the existing custom rules | Open |
| ☐ | CR-144 | contracts-integration, web-pages-A | `web/src/routes/setup/+page.svelte:614` | Wizard UniFi settings are dropped unless the user clicks 'Test' | Open |
| ☐ | CR-145 | web-pages-A | `web/src/routes/setup/+page.svelte:644` | The form-success $effect re-saves the config and yanks the user to Verification on every later edit | Open |
| ☐ | CR-146 | web-pages-A | `web/src/routes/setup/+page.svelte:647` | A failed config save is hidden: the wizard advances to Verification and can't be re-run | Open |
| ☐ | CR-147 | contracts-integration | `web/src/routes/setup/+page.svelte:647` | A failed /api/setup/configure is never shown to the user | Open |
| ☐ | CR-148 | web-pages-B | `web/src/routes/system/+page.svelte:49` | System page shows "0.0% used" storage and an OpenSearch bootstrap hint when the daemon is unreachable | Open |
| ☐ | CR-149 | web-pages-B | `web/src/routes/system/cyberchef/+page.svelte:49` | Apply Recipe loads the Docker-internal URL http://nettap-cyberchef:8443 into the iframe | Open |
| ☐ | CR-150 | web-pages-B | `web/src/routes/system/updates/+page.svelte:214` | Update History and What's New never render: the client expects an array, the daemon sends {history, count} | Open |
| ☐ | CR-151 | web-pages-B | `web/src/routes/system/updates/+page.svelte:226` | A failed "Check for Updates" reports every component as Up to Date and "Last checked: Just now" | Open |
| ☐ | CR-152 | web-pages-C | `web/src/routes/traffic/[category]/+page.svelte:236` | Category auto-refresh blanks the whole page every 30s and destroys the search input | Open |
| ☐ | CR-153 | web-pages-C | `web/src/routes/traffic/[category]/+page.svelte:373` | Several pages show 'no data' empty states instead of an error when the daemon fails | Open |
| ☐ | CR-198 | gap-pass, malcolm-stack | `docker/docker-compose.yml:412` | config/suricata/nettap.yaml is never included by Malcolm's generated suricata.yaml | Open |
| ☐ | MS-006 | malcolm-stack | `daemon/services/update_executor.py:129` | UI component updates use the wrong compose service names, a missing compose file, and recreate OpenSearch | Open |
| ☐ | MS-007 | malcolm-stack | `docker/docker-compose.yml:294` | Filebeat registry volume is mounted at a path Filebeat doesn't use, so logs re-ship after every recreate | Open |
| ☐ | MS-008 | malcolm-stack | `docker/docker-compose.yml:346` | PCAP_PROCESSOR flags left on in live containers cause a DNS storm for 'pcap-monitor' | Open |
| ☐ | MS-009 | malcolm-stack | `docker/docker-compose.yml:363` | Packet capture can't start unless the daemon, and therefore OpenSearch, is healthy | Open |

### LOW (109)

| Done | ID | Area | Location | Finding | Status |
|------|----|------|----------|---------|--------|
| ☐ | CR-154 | scripts-infra | `.github/workflows/integration.yml:76` | The 'release gate' integration workflow runs no integration tests, and releases do not depend on CI | Open |
| ☐ | CR-155 | daemon-api-A | `daemon/api/baseline.py:78` | JSON bodies that are not objects crash handlers with a 500 | Open |
| ☐ | CR-156 | daemon-api-A | `daemon/api/capture_control.py:220` | PUT /api/capture/settings reports a restart but the new rotate size never applies | Open |
| ☐ | CR-157 | daemon-api-A | `daemon/api/detection_packs.py:65` | Installing or enabling a detection pack has no effect on Suricata | Open |
| ☐ | CR-158 | daemon-api-A | `daemon/api/dns.py:46` | Bad numeric parameters cause 500s or unbounded query sizes | Open |
| ☐ | CR-159 | daemon-api-B | `daemon/api/logs.py:545` | Unguarded int() and unbounded numeric query params turn bad input into 500s or expensive queries | Open |
| ☐ | CR-160 | daemon-api-B | `daemon/api/notifications_hub.py:24` | Notification channel listing returns SMTP passwords and bot tokens in clear text | Open |
| ☐ | CR-161 | daemon-api-B | `daemon/api/pcap.py:121` | PCAP download and preview path checks use unanchored prefixes and follow symlinks | Open |
| ☐ | CR-162 | daemon-services-C | `daemon/api/server.py:329` | Changelog is never fed network events, and its only writer passes metadata as the description | Open |
| ☐ | CR-163 | daemon-api-B | `daemon/api/server.py:498` | POST /api/ilm/apply reapplies static default policies without OpenSearch auth and reports success | Open |
| ☐ | CR-164 | daemon-api-B | `daemon/api/server.py:983` | Appliance management IP is re-added to the exclusion list on every daemon start | Open |
| ✅ | CR-165 | daemon-api-B | `daemon/api/setup.py:40` | Setup configure writes unvalidated interface names and storage values raw into config/.env files | Fixed (PR #145) |
| ✅ | CR-166 | contracts-integration, security-crosscut | `daemon/api/setup.py:70 (+1)` | /api/setup/configure writes unvalidated interface names and storage values into .env and capture-mode.conf | Fixed (PR #145) |
| ✅ | CR-167 | daemon-core | `daemon/main.py:474` | Unguarded capture setup runs before the storage and SMART loops; any exception exits the daemon | Fixed (PR #145) |
| ☐ | CR-168 | daemon-services-A | `daemon/main.py:497` | Two BridgeHealthMonitor instances: /api/bridge/history and stats never see the 30s bridge_loop samples | Open |
| ☐ | CR-169 | daemon-core | `daemon/pyproject.toml:5` | pyproject dependencies differ from requirements.txt | Open |
| ☐ | CR-170 | daemon-services-B | `daemon/services/bandwidth_tracker.py:401` | Bandwidth heatmap, daily and monthly buckets are computed in UTC with no time zone | Open |
| ☐ | CR-171 | daemon-services-A | `daemon/services/bridge_manager.py:530` | WAN/LAN chosen by alphabetical order of bridge members: readiness tells users to move the wrong cable | Open |
| ☐ | CR-172 | daemon-services-A | `daemon/services/bridge_manager.py:567` | Daemon netplan overwrites setup-bridge.sh's version and drops `optional: true` and mode 0600 | Open |
| ☐ | CR-173 | daemon-services-B | `daemon/services/device_baseline.py:74` | State JSON files are truncated before being rewritten, so a full disk or power loss wipes them (baseline, excluded IPs, UniFi key, merges,… | Open |
| ☐ | CR-174 | daemon-services-B | `daemon/services/device_baseline.py:127` | Baseline MAC normalization only upper-cases, so dash- and colon-form MACs never match | Open |
| ☐ | CR-175 | daemon-services-C | `daemon/services/investigation_store.py:111` | Non-atomic JSON saves plus a lenient load can wipe all investigations after a crash or power cut | Open |
| ☐ | CR-176 | daemon-services-C | `daemon/services/investigation_store.py:202` | A rejected update is still partly applied in memory | Open |
| ☐ | CR-177 | daemon-services-B | `daemon/services/iot_monitor.py:1158` | IoT anomalies ignore the requested from/to range and always cover only the last hour | Open |
| ☐ | CR-178 | daemon-services-B | `daemon/services/live_connections.py:385` | Live dashboard builds its excluded-IP must_not from raw stored entries and skips build_excluded_ips_filter validation | Open |
| ☐ | CR-179 | daemon-services-B | `daemon/services/mac_correlator.py:423` | suggest_merges makes R x K blocking OpenSearch queries on the event loop and refetches known-MAC fingerprints for every randomized MAC | Open |
| ☐ | CR-180 | daemon-services-B | `daemon/services/mac_correlator.py:505` | Recorded MAC merges are never applied anywhere | Open |
| ☐ | CR-181 | daemon-services-C | `daemon/services/nl_search.py:212` | Natural-language 'alerts' searches never restrict results to Suricata alerts | Open |
| ☐ | CR-182 | daemon-services-C | `daemon/services/notification_hub.py:124` | Notification channel list returns stored secrets unredacted | Open |
| ☐ | CR-183 | security-crosscut | `daemon/services/pcap_search.py:244` | PCAP path guards in preview and TShark analyze do not collapse '..' | Open |
| ☐ | CR-184 | daemon-services-C | `daemon/services/report_generator.py:311` | Generated reports contain hardcoded placeholder data (0 alerts, compliance 100% pass, risk low) | Open |
| ☐ | CR-185 | daemon-services-C | `daemon/services/risk_scoring.py:225` | Risk scoring gives every normal home device risk points for ordinary behavior | Open |
| ☐ | CR-186 | daemon-services-C | `daemon/services/threat_intel.py:174` | TI bootstrap records the victim (destination) IPs of inbound blocklist alerts as 'compromised' indicators | Open |
| ☐ | CR-187 | daemon-services-A | `daemon/services/tshark_service.py:112` | Absolute PCAP paths are checked lexically, so '..' segments escape the PCAP dir | Open |
| ☐ | CR-188 | daemon-api-B | `daemon/services/tshark_service.py:292` | TShark JSON output over 5 MB is cut mid-document and returned as zero packets with no error | Open |
| ☐ | CR-189 | daemon-services-A | `daemon/services/update_checker.py:446` | Update checks to GitHub and Docker Hub disable TLS verification | Open |
| ☐ | CR-190 | daemon-services-A | `daemon/services/update_executor.py:744` | Docker rollback ignores the saved image ID and reports success; error text is saved as the image ID | Open |
| ☐ | CR-191 | daemon-services-A | `daemon/services/version_manager.py:102` | Version inventory name collisions overwrite zeek/suricata/opensearch with 'unknown' | Open |
| ☐ | CR-192 | daemon-core | `daemon/smart/monitor.py:680` | SATA wear and TBW parsing only fits Samsung-style attributes | Open |
| ☐ | CR-193 | daemon-core | `daemon/storage/manager.py:105` | Fixed critical (95%) and resume (85%) thresholds override user settings | Open |
| ☐ | CR-194 | daemon-core | `daemon/storage/manager.py:410` | The 80% safeguard deletes nothing when all data is within retention, so the real threshold is 90% | Open |
| ☐ | CR-195 | daemon-core | `daemon/storage/manager.py:809` | Startup ILM check is marked done even when every policy fails, and is never retried | Open |
| ☐ | CR-196 | daemon-core | `daemon/storage/manager.py:1418` | estimated_daily_gb is hardcoded to 1.2 and drives the wizard's capacity estimate | Open |
| ☐ | CR-197 | daemon-core | `daemon/storage/retention_config.py:171` | retention.json is loaded without validate_config; a non-integer env value crashes the daemon | Open |
| ☐ | CR-199 | scripts-infra | `docker/docker-compose.yml:847` | Unpinned edge proxy image and a Grafana plugin fetched at runtime | Open |
| ☐ | CR-200 | scripts-infra | `scripts/bridge/setup-bridge.sh:507` | mask_to_cidr is undefined, so the persisted management IP is always /24 | Open |
| ☐ | CR-201 | scripts-infra | `scripts/generate-cert.sh:113` | Run without sudo (as its usage shows), the nginx key ends up unreadable by nettap-nginx | Open |
| ☐ | CR-202 | scripts-infra | `scripts/install/activate-bridge.sh:171` | OpenSearch readiness probe has no credentials, so it always fails after a 5-minute wait | Open |
| ☐ | CR-203 | scripts-infra | `scripts/install/install.sh:238` | Installer forces public Quad9 resolvers for all container DNS | Open |
| ☐ | CR-204 | security-crosscut | `scripts/install/setup-firewall.sh:200` | The 'mgmt only' ufw rules don't apply to Docker-published 443/80, and the firewall script is never run by install | Open |
| ☐ | CR-205 | scripts-infra | `scripts/install/validate-hardware.sh:256` | Standalone hardware validation aborts at the first warning | Open |
| ☐ | CR-206 | scripts-infra | `scripts/remote/full-stack-test.sh:146` | The release 'full stack test' checks out and redeploys an old branch | Open |
| ☐ | CR-207 | scripts-infra | `scripts/verify-release.sh:497` | Release verification says 'release is ready' when every check was skipped | Open |
| ☐ | CR-208 | security-crosscut | `web/src/hooks.server.ts:21` | Unauthenticated /api/tools lets any LAN host run ping/traceroute/openssl/dig from the appliance with no concurrency limit | Open |
| ☐ | CR-209 | contracts-integration | `web/src/lib/api/bridge.ts:222` | Go Live replaces the daemon's bridge-creation errors with 'HTTP 400' | Open |
| ☐ | CR-210 | contracts-integration | `web/src/lib/api/devices-registry.ts:107` | Acknowledging a new device uses PATCH, which neither the proxy nor the daemon routes | Open |
| ☐ | CR-211 | web-components | `web/src/lib/components/Breadcrumb.svelte:110` | 'GeoIP' breadcrumb links to /geoip, which has no page | Open |
| ✅ | CR-212 | web-components | `web/src/lib/components/CaptureHealthPanel.svelte:59` | Capture panels assume only 'bridge' or 'mirror' modes | Fixed (PR #145) |
| ☐ | CR-213 | web-components | `web/src/lib/components/DetailDrawer.svelte:38` | Escape on an IP context menu inside a drawer also closes the drawer | Open |
| ☐ | CR-214 | web-components | `web/src/lib/components/DetailDrawer.svelte:61` | Drawers have no dialog semantics or focus management | Open |
| ☐ | CR-215 | web-components | `web/src/lib/components/IPAddress.svelte:182` | IP address is role=button with a tab stop but does nothing on Enter or Space | Open |
| ☐ | CR-216 | web-components | `web/src/lib/components/NotificationBell.svelte:106` | Clicking an already-read notification lowers the unread badge | Open |
| ☐ | CR-217 | web-components | `web/src/lib/components/charts/DonutChart.svelte:98` | Clickable donut segments are mouse-only | Open |
| ☐ | CR-218 | web-components | `web/src/lib/components/drawer/content/ConnectionDrawerContent.svelte:438` | Alert severity labels differ from the rest of the UI | Open |
| ☐ | CR-219 | web-components | `web/src/lib/components/drawer/content/InvestigationDrawerContent.svelte:151` | Linked-alert links use an ignored ?id= param and unencoded values | Open |
| ☐ | CR-220 | web-components | `web/src/lib/components/live/GeoMap.svelte:77` | Live map loads tiles from Carto's CDN, against the 'no cloud dependency' constraint | Open |
| ☐ | CR-221 | web-components | `web/src/lib/components/live/LiveConnectionTable.svelte:97` | Direction guessed from destination port mislabels outbound traffic as 'Inbound' | Open |
| ☐ | CR-222 | web-components | `web/src/lib/components/live/LiveConnectionTable.svelte:120` | IPs sort as text; sort headers and rows are mouse-only | Open |
| ☐ | CR-223 | web-components | `web/src/lib/components/live/LiveConnectionTable.svelte:189` | Selected-row highlight never matches the open drawer | Open |
| ☐ | CR-224 | web-components | `web/src/lib/components/tshark/FilterInput.svelte:23` | Prop-sync effect refills the filter whenever the user clears it | Open |
| ☐ | CR-225 | web-components | `web/src/lib/components/tshark/PacketTable.svelte:159` | Hardcoded colors and font sizes break the planned light theme | Open |
| ☐ | CR-226 | web-pages-A | `web/src/routes/+page.svelte:220` | Overlapping dashboard fetches: an older response can overwrite newer filtered data | Open |
| ☐ | CR-227 | web-pages-A | `web/src/routes/+page.svelte:252` | Hardcoded colors, font sizes and page max-widths in the layout, dashboard and Go Live | Open |
| ☐ | CR-228 | web-pages-A | `web/src/routes/+page.svelte:869` | Smart-alert rows are role=button and focusable but don't respond to the keyboard | Open |
| ☐ | CR-229 | web-pages-B | `web/src/routes/alerts/+page.svelte:150` | Column sort on server-paginated alert tables sorts only the 50 (or 25) rows on the current page | Open |
| ☐ | CR-230 | web-pages-B | `web/src/routes/alerts/+page.svelte:510` | Acknowledge Alert fails silently | Open |
| ☐ | CR-231 | web-server | `web/src/routes/api/health/+server.ts:17` | Unauthenticated /api/health returns the daemon's full system health | Open |
| ☐ | CR-232 | contracts-integration | `web/src/routes/api/search/+server.ts:18` | Natural-language search POSTs to a daemon route that accepts only GET with ?q= | Open |
| ☐ | CR-233 | contracts-integration | `web/src/routes/api/setup/storage/+server.ts:105` | The wizard's storage GET falls back to fake disk numbers and passes the disk check | Open |
| ☐ | CR-234 | web-server | `web/src/routes/api/suricata/rules/sources/[id]/enable/+server.ts:10` | Path params interpolated into daemon paths without encoding | Open |
| ☐ | CR-235 | web-pages-C | `web/src/routes/bandwidth/+page.svelte:70` | Hardcoded rgba palette values instead of CSS variables | Open |
| ☐ | CR-236 | web-pages-C | `web/src/routes/certificates/+page.svelte:243` | Mouse-only rows and sort headers; modal Escape handler can never fire | Open |
| ☐ | CR-237 | web-pages-C | `web/src/routes/changelog/+page.svelte:42` | $effect tracks the filter state, so every filter change fetches twice | Open |
| ☐ | CR-238 | web-pages-C | `web/src/routes/connections/+page.svelte:121` | captureMode store subscription is never unsubscribed | Open |
| ☐ | CR-239 | web-pages-B | `web/src/routes/devices/[ip]/+page.svelte:348` | Device detail time-range pills (24h/7d/30d) are inert | Open |
| ☐ | CR-240 | web-pages-B | `web/src/routes/devices/[ip]/+page.svelte:605` | Many tables are unsortable or sort IPs as strings, against the "ALL tables MUST be sortable" rule | Open |
| ☐ | CR-241 | web-pages-C | `web/src/routes/dns/+page.svelte:263` | Per-device DNS panel keeps the old time range's results after the range changes | Open |
| ☐ | CR-242 | web-pages-C | `web/src/routes/dns/+page.svelte:547` | Tables with unsortable columns (design rule: all tables sortable) | Open |
| ☐ | CR-243 | web-pages-C | `web/src/routes/geoip/[ip]/+page.svelte:84` | Route param is decoded twice; a '%' in the input throws URIError and crashes the page | Open |
| ☐ | CR-244 | web-pages-C | `web/src/routes/geoip/[ip]/+page.svelte:222` | Embedded OpenStreetMap iframe is always blocked by the app's CSP | Open |
| ☐ | CR-245 | web-pages-B | `web/src/routes/infrastructure/+page.svelte:259` | Index table sorts sizes as strings ("950mb" > "1.2gb") | Open |
| ☐ | CR-246 | web-pages-B | `web/src/routes/infrastructure/+page.svelte:559` | Clickable elements are mouse-only (div, tr and th with onclick) | Open |
| ✅ | CR-247 | web-pages-B | `web/src/routes/infrastructure/+page.svelte:777` | Infrastructure page shows bridge/br0 for every mode except an explicit 'mirror' | Fixed (PR #145) |
| ☐ | CR-248 | web-pages-B | `web/src/routes/iot/+page.svelte:167` | IoT drawer can show the previous device's communication map and timeline | Open |
| ☐ | CR-249 | web-pages-C | `web/src/routes/live/+page.svelte:401` | 'Filter by Country' on a connection with no country leaves a filter on that shows nothing | Open |
| ☐ | CR-250 | web-server | `web/src/routes/login/+page.server.ts:19` | Login returns 500 when the user store is damaged | Open |
| ☐ | CR-251 | web-pages-B | `web/src/routes/logs/+page.svelte:538` | Auto-refresh discards rows loaded with "Load More" and resets device connection paging | Open |
| ☐ | CR-252 | web-pages-B | `web/src/routes/logs/+page.svelte:1123` | Hardcoded white text and px/rem sizes break theming | Open |
| ☐ | CR-253 | web-pages-C | `web/src/routes/pcap/+page.svelte:241` | Packet preview can show another file's packets, filtered by unsaved filter text | Open |
| ☐ | CR-254 | web-pages-C | `web/src/routes/pcap/+page.svelte:748` | Hardcoded text colors (#000/#fff/#ef4444) break the planned light theme | Open |
| ☐ | CR-255 | web-pages-A | `web/src/routes/settings/suricata-rules/+page.svelte:121` | Changing the update schedule reports success even when the save failed | Open |
| ☐ | CR-256 | web-pages-A | `web/src/routes/settings/suricata-rules/+page.svelte:231` | Tables are not sortable (Suricata rule sources, DNS Recon records, Ping replies, Traceroute hops) | Open |
| ☐ | CR-257 | web-server | `web/src/routes/setup/+page.server.ts:109` | Setup paths return raw internal error text to unauthenticated first-run clients | Open |
| ☐ | CR-258 | web-pages-A | `web/src/routes/setup/+page.svelte:316` | The 'Docker is running' requirement always passes, and the disk check passes on error | Open |
| ☐ | CR-259 | contracts-integration, web-pages-A | `web/src/routes/setup/+page.svelte:1432` | The wizard's Self-Traffic Exclusion field is editable but never saved | Open |
| ☐ | CR-260 | web-pages-C | `web/src/routes/traffic/[category]/+page.svelte:186` | 'Updated just now' / 'Last scan just now' never changes | Open |
| ☐ | MS-010 | malcolm-stack | `docker/docker-compose.yml:161` | dashboards-helper lacks opensearch.env vars and mounts its volume at an unused path | Open |
| ☐ | MS-011 | malcolm-stack | `docker/docker-compose.yml:336` | Capture entrypoints recursively chown growing data volumes on every start | Open |
| ☐ | MS-012 | malcolm-stack | `scripts/install/malcolm-config.sh:342` | Image tag is hardcoded in docker/.env, so upgrades via malcolm-versions.conf silently don't apply | Open |
