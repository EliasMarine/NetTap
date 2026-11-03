# 2026-11-01 — malcolm_template never applied: guessed field types, rejected Zeek records, .keyword queries

**Status:** Fixed and verified on the G11; PR pending.
**Linear:** NET-128.
**Branch:** `fix/index-template-pattern`, off `fix/zeek-rdrand-urandom`.
**Chain:** DEPLOYMENT-ISSUES.md Chain 24 (supersedes Chain 13's root cause).

## What changed
- **Installer:** `scripts/install/deploy-malcolm.sh` (`bootstrap_index_templates`) fills in `MALCOLM_NETWORK_INDEX_PATTERN_REPLACER` with `arkime_sessions3-*` (or `$MALCOLM_NETWORK_INDEX_PATTERN`) before it pushes `malcolm_template`. The old push is kept as an OLD CODE comment.
- **`scripts/remote/fix-index-template.sh` (new):**
  - pushes the corrected template from inside dashboards-helper;
  - `--delete-today` also drops today's wrongly mapped index;
  - then checks field types, Zeek conn records and the traffic summary.
- **Daemon:** `.keyword` is dropped from field names on every non-comment line in `daemon/api` and `daemon/services` (197 lines, 20 files, Painless scripts included).
- **Log sort:** `api/logs.py` no longer adds `.keyword` to sort fields, and strips it if an old client sends it. The old logic is kept as an OLD CODE comment.
- **Web:** the alert drawer's related-logs query (`AlertDrawerContent.svelte`) uses `source.ip` / `destination.ip`.
- **Tests:**
  - new `daemon/tests/test_query_field_names.py` guards against `.keyword` field names;
  - new sort test in `test_logs_api.py`;
  - new bats test in `test_deploy_malcolm.bats`;
  - updated expectations in `test_live_connections.py`, `test_alerts_api.py`, `test_dns_analytics.py` and `AlertDrawerContent.test.ts`.
- **`scripts/remote/deploy-malcolm-field-names.sh` (new):** rebuilds the daemon and web, then checks the traffic, devices and top-talkers APIs.

## Root cause
- **The template matched no index.** The installer pushed the raw template file, so `index_patterns` stayed `["MALCOLM_NETWORK_INDEX_PATTERN_REPLACER"]`.
- **Each daily `arkime_sessions3-*` index guessed its types** from its first records:
  - `event.id` became `long`, so every Zeek record, whose `event.id` is a text uid, got HTTP 400;
  - IPs and keywords became `text` + `.keyword`.
- **Chain 13 took that for Malcolm's mapping** and added `.keyword` to every query. That's why the devices page stayed empty once the real template applied.

## Steps / solution
1. Grouped the Logstash 400s by reason. All of them were `event.id` of type long, on Zeek records.
2. Read the live template (pattern is the placeholder) and Malcolm's `shared-object-creation.sh` (it fills placeholders in before pushing).
3. Pushed the corrected template on the G11, and deleted today's index with the owner's OK.
4. Checked every `.keyword` field the daemon uses against the new mapping. All are keyword, ip or long, and none needs the suffix. `dns.question.name` and `event_type` don't exist in either mapping.
5. Ran the LAN-filter Painless script against the new index: `doc['source.ip'].value` works on the ip field (5,086 LAN conn records).
6. Renamed mechanically, skipping comment lines so OLD CODE blocks stay verbatim. Fixed the one place where `.keyword` was string logic by hand (`logs.py` sort).

## Files touched
- `scripts/install/deploy-malcolm.sh`, `scripts/remote/fix-index-template.sh` (new), `scripts/remote/deploy-malcolm-field-names.sh` (new)
- `daemon/api/{alerts,traffic,logs,risk,devices}.py`
- `daemon/services/{traffic_classifier,iot_monitor,mac_correlator,changelog,threat_intel,bandwidth_tracker,lan_anomaly_detector,threat_detection,excluded_ips,investigation,device_fingerprint,alert_intelligence,device_registry,live_connections,dns_analytics}.py`
- `daemon/tests/test_query_field_names.py` (new), `test_logs_api.py`, `test_live_connections.py`, `test_alerts_api.py`, `test_dns_analytics.py`
- `web/src/lib/components/drawer/content/AlertDrawerContent.svelte` and its `.test.ts`
- `tests/scripts/test_deploy_malcolm.bats`
- `Debugging/DEPLOYMENT-ISSUES.md`, `Debugging/BRIDGE-ARCHITECTURE.md`

## Test results
- pytest: 2354 passed. ruff 0.17.3 check and format are clean.
- The guard test's negative control flags 9 lines in the pre-fix `devices.py`.
- vitest `AlertDrawerContent.test.ts`: 32/32.
- bats `test_deploy_malcolm.bats`: 36/36.
- shellcheck is clean on all three scripts.
- **G11:**
  - template pattern is `arkime_sessions3-*`;
  - the new index has `source.ip=ip` and `event.id=keyword`;
  - 0 Logstash rejections after the delete;
  - Zeek records indexed: conn 448, dns 373, ssl 120, http 21 and files 32 in the first minutes;
  - traffic summary: 205 connections.
  - after `deploy-malcolm-field-names.sh`: traffic summary 6,185 connections, 18 devices, 5 top talkers, top protocol `udp`, 0 daemon errors, 0 Logstash rejections.

## Lessons
- **Read the live template** (`GET _index_template/malcolm_template`) before "fixing" aggregation errors in queries.
- **A Malcolm `*_REPLACER` token must be filled in** by anything NetTap pushes itself.

## Next steps
- **Other boxes (for example the N100):** run `fix-index-template.sh`, then `deploy-malcolm-field-names.sh`. Older dynamically mapped daily indices will fail aggregations until they age out or are deleted.
- **Stray index:** `arkime_sessions3-700101` (1 record with a 1970 timestamp, from before the fix) has an empty mapping and can be deleted.
- **`network.transport.keyword` was used for `top_protocol`.** Now that it's `network.transport`, check the traffic summary shows a protocol instead of "unknown".
