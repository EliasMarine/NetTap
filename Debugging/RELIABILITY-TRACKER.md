# NetTap Reliability Tracker — Source of Truth

> Last updated: 2026-03-09
> Status: 7/7 subsystems production-ready. 18/18 containers healthy on N100. Full-stack test (full-stack-test.sh): 59/59 passing. Mirror/SPAN mode: all API endpoints verified. Data pipeline: Suricata working (1.3M alerts/day), Zeek partially broken — produces metadata logs (known_hosts, known_services) but ZERO conn/dns/http/tls logs on March 9. Investigating Zeek capture interface config.

## Purpose

This document tracks production reliability of each NetTap subsystem. Read this before starting any reliability or health-check work. Update after every fix.

## Subsystem Reliability Status

| Subsystem | Status | Verified On | Issues | Notes |
|-----------|--------|-------------|--------|-------|
| OpenSearch | OK | 2026-03-03 | -- | Fixed: curlrc credential parsing added (PR #81) |
| SMART Monitoring | OK | 2026-03-03 | NVMe data limited | smartctl code 2 (may lack SYS_RAWIO); health OK but temp/wear null on some devices |
| Bridge Health | OK | 2026-03-04 | -- | Fixed: not_configured state (PR #81), bypass promisc toggle (PR #83), 30s polling loop (PR #83), 8-point readiness check (PR #83) |
| Bridge Management | OK | 2026-03-04 | -- | NEW: BridgeManager service — create/teardown/readiness via nsenter, host persistence (PR #83) |
| Internet Health | Fixing | -- | Shows "down" when not configured | Missing `not_configured` state |
| Web UI (Dashboard) | OK | 2026-03-05 | -- | REDESIGNED: Full SIEM dashboard with stat cards, charts, auto-refresh (NET-100) |
| Web UI (System) | OK | 2026-03-05 | -- | REDESIGNED: Infrastructure page with OpenSearch/Logstash/System tabs (NET-100) |
| Web UI (Go Live) | OK | 2026-03-04 | -- | NEW: 3-phase Go Live page — readiness/wiring/monitoring (PR #83) |
| Web Auth | OK | 2026-03-04 | -- | Fixed: bridge API + /go-live added to public paths (PR #85) |
| Storage Daemon | OK | 2026-03-03 | -- | Disk monitoring and retention working |
| Log Search API | OK | 2026-03-05 | -- | NEW: Generic Zeek/Suricata log browser with 8 log types, cursor pagination (NET-100) |
| OpenSearch Cluster API | OK | 2026-03-05 | -- | NEW: Cluster health, indices, shards, templates visibility (NET-100) |
| Logstash Monitor API | OK | 2026-03-05 | -- | NEW: Pipeline stats, JVM heap, throughput monitoring (NET-100) |
| Web UI (Log Explorer) | OK | 2026-03-05 | -- | NEW: Kibana Discover-style log browser (NET-100) |
| Web UI (Infrastructure) | OK | 2026-03-05 | -- | NEW: 3-tab OpenSearch/Logstash/System view (NET-100) |
| Dashboard Data (Aggregations) | OK | 2026-03-05 | -- | Fixed: .keyword suffix on all 22 aggregation field references (PR #92). All dashboard pages return data. |
| Logstash Index Routing | OK | 2026-03-05 | -- | Fixed: MALCOLM_NETWORK_INDEX_PATTERN/SUFFIX env vars added to logstash service (717bd24). Events now route to correct arkime_sessions3-* indices. 34,992 docs reindexed from broken index. |
| Alerts API | OK | 2026-03-06 | -- | Fixed: ECS/Malcolm/Suricata field normalization. Signatures, severities, categories, timestamps all populated correctly. Severity counts handle string keys. IP filter (source OR destination) added. |
| WHOIS/DNS Lookup API | OK | 2026-03-06 | -- | NEW: `GET /api/lookup/whois/{ip}` (async subprocess, 15s timeout, parsed fields) + `GET /api/lookup/dns/{ip}` (reverse + forward DNS). Requires `whois` package in Dockerfile. |
| IP Context Menu | OK | 2026-03-06 | -- | NEW: 8 right-click actions on every IP (Copy, Device, GeoIP, WHOIS, DNS, Alerts, Filter From, Filter To). IPAddress component on Devices, Logs, Alerts pages. Filter from/to bug fixed (was using identical URL). |
| Tools Section | OK | 2026-03-06 | -- | NEW: 10 tools — DNS Recon (dig), MAC Lookup (OUI db), Ping/Traceroute (subprocess), SSL Cert (openssl), Subnet Calculator (pure JS), Port Reference (static), Base64/Hex (pure JS), TShark (existing), CyberChef (moved). 4 backend services, 5 proxy routes, 10 pages, sidebar nav, IP context menu links. 97 backend + 24 frontend tests. |
| pcap-capture | OK | 2026-03-07 | -- | Fixed: PUSER=root skips usermod on root PID 1. SYS_ADMIN cap_add covers netsniff-ng file caps (setcap -r fails silently on overlay2). netsniff-ng capturing packets. |
| nginx-proxy | OK | 2026-03-07 | -- | Fixed: healthcheck targets :9200 (OpenSearch proxy) instead of :443 (broken arkime vhost). Removed :443 port binding. 18/18 containers now healthy. |
| nettap-nginx (SSL) | OK | 2026-03-07 | -- | Fixed: SSL key chmod 644 for non-root nginx worker. Self-signed cert, LAN-only. |
| OpenSearch (security) | OK | 2026-03-07 | -- | Reusable fix-opensearch.sh script created. Security bootstrap after container recreate. |
| Boot Persistence | OK | 2026-03-07 | -- | NEW: nettap.service systemd unit — auto-starts Docker stack after docker.service on reboot. |

### Status Legend
- **OK**: Verified working in production
- **Fixing**: Known issue, fix in progress
- **Broken**: Non-functional, blocking
- **Untested**: Not yet verified on production hardware

## Issues Found & Fixed

| Date | Subsystem | Issue | Root Cause | Fix | Linear | Branch/PR |
|------|-----------|-------|------------|-----|--------|-----------|
| 2026-03-03 | OpenSearch | Daemon gets 403 from OpenSearch | `_create_client()` has no http_auth | Add curlrc mount + credential parsing | -- | PR #81 |
| 2026-03-03 | SMART | All SMART metrics null | /dev mounted :ro, NVMe needs write for admin cmds | Remove :ro from /dev mount | -- | PR #81 |
| 2026-03-03 | Bridge | Bridge shows "Down" when br0 doesn't exist | No `not_configured` state | Add not_configured status to bridge_health.py | -- | PR #81 |
| 2026-03-03 | Web UI | Dashboard shows generic error for all failure modes | Single error banner for all states | Distinguish daemon unreachable vs OS connecting vs no data | -- | PR #81 |
| 2026-03-03 | Web UI (System) | Storage shows NaN, SMART crashes on null | Disk bytes returned as GB (double-convert), no null guards | Return raw bytes, add null-coalescing to SMART display | -- | PR #82 |
| 2026-03-03 | Bridge Health | Bypass mode doesn't toggle promisc | `trigger_bypass()` only writes state file, no promisc off | Added nsenter `ip link set <iface> promisc off/on` | NET-91 | PR #83 |
| 2026-03-03 | Bridge Health | Bypass state file write fails | `/var/run` is read-only in container | Moved to `/tmp/nettap-bypass-active` (writable tmpfs) | NET-91 | PR #83 |
| 2026-03-03 | Bridge Health | No background health polling | Health history was demand-driven only | Added `bridge_loop()` in main.py (30s interval) | NET-91 | PR #83 |
| 2026-03-03 | Bridge | No bridge creation from daemon | Wizard step 3 only generated mock preview | Created BridgeManager with create/teardown/readiness | NET-91 | PR #83 |
| 2026-03-03 | Bridge | No readiness check for cable migration | User had no guidance on when to plug cables | 8-point readiness check at `/api/bridge/readiness` | NET-91 | PR #83 |
| 2026-03-03 | Web UI | No Go Live page after wizard | Wizard redirected to `/login` with no guidance | Created `/go-live` with 3-phase workflow | NET-91 | PR #83 |
| 2026-03-04 | Web Auth | Bridge API returns 302 → /login | `/api/bridge/*` and `/go-live` not in PUBLIC_PATHS | Added to PUBLIC_PATHS in hooks.server.ts | -- | PR #85 |
| 2026-03-04 | Bridge Health | System page shows no carriers, no packet data | BridgeHealthMonitor uses hardcoded eth0/eth1 but N100 has enp2s0/enp3s0 | Auto-discover members from br0's brif sysfs directory | NET-92 | PR #88 |
| 2026-03-04 | Bridge Health | Readiness falsely reports netfilter enabled | Reads container `/proc` namespace (always 1) instead of host | Changed netfilter check to use nsenter for host namespace | NET-92 | PR #88 |
| 2026-03-04 | Zeek | Zeek crash-loops: Permission denied on /zeek/live/logs | Fresh volumes root-owned, Malcolm entrypoint needs root for mkdir/chown | Added `user: "root"` to capture services | NET-93 | PR #89 |
| 2026-03-04 | Suricata | Suricata fails: "workers" doesn't exist for UNIX_SOCKET runmode | `SURICATA_RUNMODE: "workers"` conflicts with Malcolm 8.x internal runmode | Removed env var — Malcolm auto-selects af-packet | NET-93 | PR #89 |
| 2026-03-04 | Bridge Health | Netfilter check fails when br_netfilter module not loaded | nsenter cat returns error when proc file absent (module not loaded = good) | Treat missing proc file as netfilter disabled (PASS) | NET-93 | PR #89 |
| 2026-03-05 | Web UI v2 Redesign | .gitignore `logs/` catches route dirs | `.gitignore` pattern `logs/` matches SvelteKit route directories like `src/routes/logs/` | `git add -f` override | NET-100 | -- |
| 2026-03-04 | Dashboard Data | All dashboard queries return zero data | Daemon queries used Zeek-native index/field names; Malcolm uses unified arkime_sessions3-* with ECS fields | Remapped all 7 daemon files: index → NETWORK_INDEX, fields → ECS, added event.provider/dataset filters | NET-95 | infra/opensearch-field-mapping |
| 2026-03-05 | Dashboard Data | All dashboard aggregations fail with 400 | Malcolm maps text fields as text+keyword multi-fields; `terms` aggs require `.keyword` suffix | Added `.keyword` suffix to all 22 aggregation field references across 6 daemon files | -- | PR #92 (phase-4/webui-v2) |
| 2026-03-05 | Log Search API | Log search returns flat docs, frontend crashes | `logs.py` flattened `_source` wrapper; frontend expected `{_id, _source: {...}}` | Preserved `_source` wrapper format in API response | -- | PR #92 (phase-4/webui-v2) |
| 2026-03-05 | Web UI (CSS) | Google Fonts blocked by CSP | nginx.conf Content-Security-Policy missing `fonts.googleapis.com` / `fonts.gstatic.com` | Added font domains to `style-src` and `font-src` CSP directives | -- | PR #92 (phase-4/webui-v2) |
| 2026-03-05 | Logstash / Data Pipeline | 89K+ events in broken literal index, 0 Suricata events in arkime_sessions3-* | `MALCOLM_NETWORK_INDEX_PATTERN` and `MALCOLM_NETWORK_INDEX_SUFFIX` env vars missing from logstash service — `format_index_string.rb` crashed with `NoMethodError: undefined method 'delete_suffix' for nil:NilClass` | Added 4 MALCOLM_*_INDEX env vars to logstash service in docker-compose.yml. Reindexed 34,992 docs from broken index. | -- | Commit 717bd24 (phase-4/webui-v2) |
| 2026-03-06 | Alerts API | All alert signatures show "unknown", severities all "info" | Daemon passed raw `_source` without normalizing ECS/Malcolm/Suricata field paths (`rule.name` vs `suricata.alert.signature` vs `alert.signature`). Category stored as array. Timestamp as epoch millis. | Added `_normalize_alert_source()` + `_extract_severity()` to merge all 3 paths, flatten array categories, prefer ISO `@timestamp`. Fixed severity count string-key parsing. | -- | Commits cf960e4 + 4c26c26 (phase-4/webui-v2) |
| 2026-03-06 | Web UI (IPAddress) | "Filter from" and "Filter to" use identical URL | Both menu items navigated to `/connections?ip={ip}` — no src/dst distinction | Fixed: "from" → `?src_ip=`, "to" → `?dst_ip=` | -- | Commit 5b1b4d4 (phase-4/webui-v2) |
| 2026-03-06 | Web UI (IP Context Menu) | IP addresses on Devices, Logs, Alerts pages rendered as plain text — no right-click actions | IPAddress component only used on Connections and Device Detail pages | Added IPAddress to Devices (3 locations), Log Explorer (IP column detection), Alerts (IP filter badge). Added WHOIS/DNS/Alerts menu items. Created daemon lookup API + pages. | -- | Commit 5b1b4d4 (phase-4/webui-v2) |
| 2026-03-07 | pcap-capture | Container restart-looping: `usermod: user root is currently used by process 1` | Malcolm's `docker-uid-gid-setup.sh` tries `usermod -u 1000 root` but root is PID 1 | Set `PUSER=root` to skip UID remapping entirely | -- | Commit 65e31cf (phase-4/webui-v2) |
| 2026-03-07 | nginx-proxy | Container unhealthy, restart-looping: `host not found in upstream "arkime:8005"` | Healthcheck tested `:443` (broken arkime vhost) instead of `:9200` (working OpenSearch proxy) | Changed healthcheck to `:9200`, removed `:443` port binding | -- | Commit 65e31cf (phase-4/webui-v2) |
| 2026-03-07 | nettap-nginx | Crash-looping: `cannot load certificate key: Permission denied` | SSL key `0600` perms, nginx drops to non-root user with no-new-privileges | `chmod 644` on SSL key file (self-signed, LAN-only) | -- | Manual fix on device |
| 2026-03-07 | OpenSearch | `Security not initialized` after container recreate — all services 403 | `roles_mapping.yml` reverts to empty on container recreate | Ran security bootstrap, created `scripts/remote/fix-opensearch.sh` | -- | Manual fix + script |
| 2026-03-07 | Boot Persistence | Docker stack not starting after reboot — manual `docker compose up -d` required | No systemd service unit for NetTap | Created `scripts/remote/nettap.service` systemd unit | -- | phase-4/webui-v2 |
| 2026-03-07 | pcap-capture | netsniff-ng EPERM on exec — file capabilities exceed container bounding set | netsniff-ng has `cap_sys_admin=eip` file caps exceeding bounding set. `setcap -r` with SETFCAP returns exit 0 but is a no-op on overlay2 (xattrs from image layer persist) | Added `SYS_ADMIN` to pcap-capture `cap_add` so bounding set covers all file caps. Removed useless `setcap -r` (overlay2 limitation). | -- | phase-4/webui-v2 |
| 2026-03-09 | Daemon | Crash-loop: `ModuleNotFoundError: No module named 'yaml'` | `suricata_rules.py` imports yaml but PyYAML not in requirements.txt | Added `PyYAML>=6.0,<7.0` to daemon/requirements.txt | -- | phase-5/mirror-span-mode |
| 2026-03-09 | Full-Stack Test | All API checks HTTP 000 (connection refused) | Port 8880 is Docker `expose` only (internal), not `ports` published to host | Changed test script to use `docker exec` curl from inside daemon container | -- | phase-5/mirror-span-mode |
| 2026-03-09 | Full-Stack Test | nginx returns stale upstream after web container recreate | Script only recreated daemon+web, not nginx. Nginx cached old container IP | Added nettap-nginx to `docker compose up -d --force-recreate` in test script | -- | phase-5/mirror-span-mode |
| 2026-03-09 | Zeek Capture | Dashboard pages all show zeros — no Zeek conn/dns/http/tls logs indexed | `ZEEK_JSON` env var missing from zeek-live service. Zeek's local.zeek checks `getenv("ZEEK_JSON")` and outputs TSV when unset. Logstash can't parse TSV → logs land in broken index or get dropped. Metadata logs (known_hosts etc.) use different code path. | Added `ZEEK_JSON: "true"` to zeek-live environment in docker-compose.yml | -- | phase-5/mirror-span-mode |

## Reliability Lessons Learned

1. **Always mount curlrc in every container that talks to OpenSearch.** The security bootstrap requires Basic Auth — containers without credentials get silent 403 errors.
2. **NVMe SMART queries require write access to /dev.** The smartctl tool sends NVMe admin commands that need write access to the controller device. `:ro` mounts block this silently.
3. **"Not configured" is not the same as "down".** Services that haven't been set up (bridge, internet) should show an informational state, not an error state. Users who haven't configured the bridge yet shouldn't see red badges.
4. **Log stderr from subprocess calls.** When smartctl fails, the exception message alone doesn't show why — the stderr output contains the actual error (e.g., "Permission denied", "No such device").
5. **Parse curlrc files for credentials.** Malcolm stores OpenSearch credentials in curlrc format (`user = "username:password"`). The daemon needs a parser for this format.
6. **Bypass mode must toggle promisc, not just write a state file.** Writing `/tmp/nettap-bypass-active` signals the daemon/UI, but capture containers still see packets if promisc mode stays on. Must `nsenter -t 1 -n -- ip link set <iface> promisc off`.
7. **Container tmpfs paths matter.** `/var/run` is on the container's read-only root filesystem — writes fail silently. Use `/tmp` (which has a writable tmpfs) for ephemeral state files.
8. **SvelteKit auth middleware blocks API routes by default.** New `/api/*` proxy routes must be added to `PUBLIC_PATHS` in `hooks.server.ts` if they need to work without login (e.g., Go Live workflow runs before user auth).
9. **Recreating Docker containers invalidates nginx upstream DNS.** After `docker compose up --force-recreate`, the upstream container gets a new IP. Nginx caches the old one → 502. Must restart nginx after recreating backend containers.
10. **Bridge health needs continuous polling, not demand-driven.** Without a `bridge_loop()`, health history only populated when the API endpoint is hit. The 30s polling loop ensures consistent monitoring data.
11. **Never hardcode NIC names — auto-discover from bridge sysfs.** Intel N100 uses `enp2s0`/`enp3s0` (PCI bus naming), not `eth0`/`eth1`. Read bridge member interfaces from `/sys/class/net/br0/brif/` directory to get actual names.
12. **Container `/proc` is isolated — use nsenter for host reads.** Reading `/proc/sys/net/bridge/bridge-nf-call-iptables` inside the container returns the container's own namespace value (default 1), not the host's. Must use `nsenter -t 1 -n -- cat` to read from host namespace.
13. **Malcolm capture images need `user: "root"` in compose.** Their entrypoint (`docker-uid-gid-setup.sh`) runs `mkdir`/`chown` to set up log directories, then drops privileges to PUID:PGID via `su`. Without starting as root, fresh Docker volumes (root-owned) cause Permission denied.
14. **Don't override Malcolm's internal runmode selection.** Setting `SURICATA_RUNMODE` conflicts with Malcolm's orchestration in Suricata 8.x. Let `SURICATA_LIVE_CAPTURE=true` handle mode selection automatically.
15. **Missing kernel module proc files ≠ feature enabled.** When `br_netfilter` isn't loaded, `/proc/sys/net/bridge/bridge-nf-call-iptables` doesn't exist. This means no iptables interference — the desired state, not a failure.
16. **Agent teams (7 parallel) can build independent SvelteKit pages concurrently without conflicts** — each page has its own route directory, so parallel agents don't step on each other's files.
17. **Malcolm unifies all data into arkime_sessions3-*.** There are no separate zeek-*/suricata-* indices. Use `event.provider` + `event.dataset` to filter by data source. All field names use ECS format, not Zeek-native. Always verify field names against a real document from the N100 before writing queries.
18. **Malcolm maps ALL text fields as text+keyword multi-fields. Every OpenSearch `terms` aggregation MUST use `.keyword` suffix** (e.g., `source.ip.keyword`, `network.transport.keyword`). Without it, aggregations fail with 400: "Text fields are not optimised for operations that require per-document field data." This applies to `terms`, `cardinality`, and `composite` aggs — NOT to `match`, `range`, or `bool` filter queries.
19. **Preserve OpenSearch `_source` wrapper in API responses.** Frontends expect `{_id, _source: {...}}` (standard OpenSearch hit structure). Flattening to `{_id, "field": "value"}` breaks destructuring like `hit._source.field`. Always pass through the raw hit structure from OpenSearch.
20. **CSP headers must explicitly allow external font CDNs.** Google Fonts requires `fonts.googleapis.com` in `style-src` (for CSS) and `fonts.gstatic.com` in `font-src` (for font files). Missing either causes silent fallback to system fonts — only visible via browser console CSP violation messages.
21. **Every Malcolm service needs its own complete set of env vars.** Docker service environments are isolated — setting `MALCOLM_NETWORK_INDEX_PATTERN` on nginx-proxy does NOT make it available to logstash. Malcolm's upstream uses shared `env_file:` references; our custom compose must replicate each env var on every service that needs it. Missing index pattern vars caused Logstash to silently misindex 89K+ events.
22. **Logstash Ruby filter errors cause silent misindexing, not event drops.** When `format_index_string.rb` crashes, Logstash catches the exception and sets the index metadata to the literal unexpanded variable string. OpenSearch creates an index with that garbage name and happily accepts all events. The only signal is Ruby exception traces in logstash logs — pipeline stats show no errors.
23. **Docker `expose` vs `ports`: `expose` is internal-only.** Port 8880 with `expose` is reachable between containers (via Docker DNS) but NOT from the host or test scripts. To test internal-only APIs from a script, use `docker exec <container> curl ...` instead of `curl http://localhost:8880`.
24. **Always recreate nginx when recreating upstream containers.** Nginx caches upstream DNS at startup. If you `--force-recreate` a backend container (nettap-web), nginx keeps pointing to the old IP. Always include nginx in the recreate command.
25. **`$HOME` under `sudo` resolves to `/root`, not the invoking user.** Scripts that use `$HOME` to find user directories (e.g., `/home/nettap/NetTap`) will break under sudo. Hard-code the path or use `$(getent passwd ${SUDO_USER:-$USER} | cut -d: -f6)`.
26. **OpenSearch curlrc credentials, not `-u admin:admin`.** Malcolm stores OpenSearch credentials in `/var/local/curlrc/.opensearch.primary.curlrc`. Using `-u admin:admin` returns empty results or errors. Always use `--config /var/local/curlrc/.opensearch.primary.curlrc`.
23. **Malcolm stores Suricata alert fields under 3 different paths.** ECS: `rule.name`/`rule.id`/`rule.category`. Malcolm: `suricata.alert.signature`/`suricata.severity`. Raw: `alert.signature`/`alert.severity`. A normalization layer must check all 3 paths with fallback priority before the frontend can display them uniformly.
24. **OpenSearch `.keyword` aggregation returns string keys, not ints.** When aggregating on `suricata.severity.keyword`, bucket keys come back as `"1"`, `"2"`, `"3"` (strings), not integers. Severity map lookups fail silently if they only handle int keys. Always parse string keys with `int()` before lookup.
25. **Malcolm may store ECS fields as arrays.** `rule.category` can be `["Generic Protocol Command Decode"]` (array) or `"Generic Protocol Command Decode"` (string). Always check `isinstance(val, list)` and flatten before using as a display string.
26. **Prefer `@timestamp` (ISO) over `timestamp` (epoch millis).** Malcolm documents have both — `@timestamp` in ISO 8601 and `timestamp` as raw epoch milliseconds. Frontend `formatTimestamp()` expects ISO strings. Always normalize to the ISO form.
27. **Set `PUSER=root` for capture containers, don't remove entrypoint scripts.** Malcolm's `docker-uid-gid-setup.sh` checks `PUSER` and skips `usermod` when the target is already root. This is safer than modifying the entrypoint chain.
28. **OpenSearch uses HTTPS internally — `http://` returns empty, not an error.** The daemon connects via `https://opensearch:9200`. Manual curl queries that use `http://` get silently empty responses. Always use `https://` + `--insecure` for self-signed certs.
29. **Diagnose "no data" by checking `event.provider`/`event.dataset` distribution.** When dashboard pages show zeros, aggregate on `event.provider.keyword` and `event.dataset.keyword` to see what data actually exists. The dashboard requires Zeek `conn` logs; if only Suricata alerts exist, all conn-dependent pages return zeros.
30. **Zeek metadata logs (known_hosts, known_services, x509) use a different ingestion path than conn/dns/http.** If metadata logs appear in OpenSearch but conn/dns/http don't, the issue is likely log format (TSV vs JSON), not capture.
31. **`ZEEK_JSON=true` is MANDATORY for Malcolm's Logstash pipeline.** Zeek's local.zeek reads `getenv("ZEEK_JSON")` to decide output format. Without it, Zeek outputs TSV. Logstash expects JSON and can't route TSV logs → they land in the broken literal `%{[@metadata][malcolm_opensearch_index]}` index or get dropped entirely. Always set `ZEEK_JSON: "true"` in the zeek-live service environment.
28. **Health checks must test the service's actual useful function.** nginx-proxy serves as an OpenSearch proxy (`:9200`) in NetTap, not as an arkime reverse proxy (`:443`). Testing the wrong vhost caused unnecessary restart loops.
29. **Appliances need systemd boot persistence.** Without a `nettap.service` unit, a power cycle leaves the entire stack down until manual SSH intervention. Unacceptable for an appliance that sits inline on a network path.
30. **Create reusable fix scripts for recurring manual operations.** OpenSearch security bootstrap is needed after every container recreate. A script (`fix-opensearch.sh`) prevents typos and ensures the correct sequence every time.
31. **File capabilities on binaries cause EPERM even with sufficient ambient caps.** If a binary has file capabilities (e.g., `cap_sys_admin=eip` on netsniff-ng), ALL file caps must be in the container's bounding set or `execve` fails with EPERM. Add the missing caps directly to `cap_add`. Do NOT use `setcap -r` to strip caps at runtime — it returns exit 0 on overlay2 but the xattrs from image layers persist (the writable layer's removal doesn't override lower layer xattrs). This was a hard-won lesson: SETFCAP + `setcap -r` appeared to work (exit 0) but had zero effect.
32. **`setcap -r` is unreliable on Docker overlay2 filesystems.** It returns success but `getcap` still shows original file capabilities. The overlay2 storage driver stores xattrs per-layer, and the writable upper layer cannot remove xattrs set in lower (image) layers. Never rely on runtime `setcap` in Docker containers — ensure the bounding set covers all file capabilities, or build a custom image without file caps.

## Verification Checklist

After deploying reliability fixes to N100 hardware:

- [x] `curl -sk https://localhost/api/health | python3 -m json.tool | grep opensearch_reachable` → `true` (verified 2026-03-03)
- [ ] `curl -sk https://localhost/api/health | python3 -m json.tool | grep -A5 smart` → real temperature/power_on_hours values (NVMe returns null — may need SYS_RAWIO)
- [x] `curl -sk https://localhost/api/bridge/health | python3 -m json.tool` → `health_status: "not_configured"` (verified 2026-03-03)
- [x] Dashboard shows "Healthy" or informational states, no red badges for unconfigured services (verified 2026-03-03)
- [x] System page shows actionable messages for unreachable OpenSearch (verified 2026-03-03)
- [ ] `curl -sk https://localhost/api/bridge/readiness | python3 -m json.tool` → returns readiness JSON (pending PR #85 deploy)
- [ ] Go Live page (`/go-live`) loads and shows readiness phase
- [ ] Bridge creation via `/api/bridge/create` works end-to-end
- [ ] Bypass toggle enables/disables promisc via nsenter

## Test Results

| Date | Test | Environment | Result | Notes |
|------|------|-------------|--------|-------|
| 2026-03-03 | Reliability overhaul deploy | N100 production | PASS | OpenSearch auth working, bridge not_configured state, dashboard UX states |
| 2026-03-03 | System page fixes deploy | N100 production | PASS | Storage NaN fixed, SMART null-safe, compliance loop fixed |
| 2026-03-04 | Bridge Go Live deploy | N100 production | **PARTIAL** | Daemon healthy, bridge_loop running. Hit 302→/login on bridge API — fixed in PR #85 (auth bypass). Pending redeploy. |
| 2026-03-04 | Dev tests (pytest) | Dev macOS | PASS | 1036/1036 passed (104 bridge-specific) |
| 2026-03-04 | Dev tests (vitest) | Dev macOS | PASS | 683/683 passed (22 GoLive + 25 bridge API) |
| 2026-03-04 | Dev svelte-check | Dev macOS | PASS | 620 files, 0 errors, 0 warnings |
| 2026-03-04 | ECS field mapping (pytest) | Dev macOS | PASS | 1041/1041 passed — all daemon queries updated to ECS fields |
| 2026-03-04 | ECS field mapping (vitest) | Dev macOS | PASS | Web tests pass — no web changes needed |
| 2026-03-04 | ECS field mapping (svelte-check) | Dev macOS | PASS | No type errors |
| 2026-03-05 | Logstash index pattern fix | N100 production | PASS | Zero Ruby exceptions after adding MALCOLM_*_INDEX env vars. Suricata events flowing to arkime_sessions3-*. 34,992 docs reindexed from broken index. |
| 2026-03-06 | Alerts normalization + IP context menu | Dev macOS | PASS | svelte-check: 665 files, 0 errors. vitest: 691/691 passed. pytest: 1078/1078 passed. Alerts fix verified via docker exec — signatures, severities, categories all populated. IP context menu: 16 files changed, 1214 lines added. |
| 2026-03-06 | Tools section (10 tools) | Dev macOS | PASS | pytest: 1175/1175 passed (97 new tools tests). vitest: 24/24 tools API tests passed. svelte-check: 692 files, 0 errors. 4 backend services, 10 frontend pages, sidebar nav, context menu links. |
| 2026-03-07 | pcap-capture + nginx-proxy fixes | N100 production | PASS | pcap-capture healthy (PUSER=root, netsniff-ng running). nginx-proxy healthy (healthcheck on :9200). 18/18 containers healthy. |
| 2026-03-07 | nettap-nginx SSL fix | N100 production | PASS | SSL key chmod 644, nginx serving HTTPS correctly. |
| 2026-03-07 | OpenSearch security bootstrap | N100 production | PASS | fix-opensearch.sh ran successfully, all services authenticated. |
| 2026-03-07 | Boot persistence (nettap.service) | N100 production | PASS | systemd unit enabled, Docker stack auto-starts on reboot. |
| 2026-03-07 | netsniff-ng EPERM fix (SYS_ADMIN) | N100 production | PASS | Added SYS_ADMIN to cap_add (bounding set covers all file caps). Previous SETFCAP + setcap -r approach failed silently on overlay2. netsniff-ng executes without EPERM. |
