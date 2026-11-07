# Detection accuracy: count by ET severity, more free sources, ET Pro code, own rules

Linear: NET-191 (slices 2–3 also close NET-130). Branch: `feature/detection-accuracy`.
Plan: reviewed with Codex over 5 rounds (`.codex-review/2026-11-06-detection-accuracy/`, local).

## Why

G11, 7 days to 2026-11-07: 703,581 Suricata rule alerts (engine events already excluded), ~100,000 a day. ET's own `signature_severity` metadata, stored as `suricata.alert.metadata.signature_severity`:

| ET severity | alerts | signatures |
|---|---|---|
| Informational | 658,676 (93.6%) | 133 |
| Unknown | 41,090 | 8 |
| Minor | 2,193 | 37 |
| Major | 1,873 | 263 |

- STUN (video calls) was 53% of all alerts.
- The owner's own DNS over HTTPS to Quad9 (192.168.1.174) was 28,230 alerts filed as "Command and Control": Malcolm writes the MITRE tactic into `rule.category` (`['Misc activity', 'Command and Control']`).
- 192.168.1.44 raised 147,245 alerts for Mysterium Network and Traffmonetizer (bandwidth sharing). The owner runs these on purpose.
- Real detections were present and small in number: Spamhaus DROP, CINS and DShield sources, Next.js CVE-2025-29927 probes and webshell requests against the internet-exposed 192.168.1.24.

Only ET Open was fetched (Malcolm image default `SURICATA_UPDATE_ENABLE_SOURCES=et/open`). The repo's `update-sources.yaml` (7 "enabled" sources), the detection packs and `config/suricata/nettap.yaml` were not wired to anything.

## Owner decisions (2026-11-06)

1. ET Informational (and Unknown) alerts: stored, listed as activity, never counted.
2. 192.168.1.44's bandwidth-sharing alerts: suppress for that device only.
3. Sources: free by default + an optional ET Pro code.
4. Build slices 1–3.

## Slice 1: count by ET severity, Activity view, .44 suppression, replay check

### Changes

- `daemon/api/alerts.py`: `ET_ACTIVITY_CLAUSE` added to the shared exclusion every count uses (Alerts, Home, Devices, Risk, IoT, Addresses, Domains, categories). `alert_query(activity=True)` selects the activity alerts instead; `/api/alerts` and `/api/alerts/count` take `?activity=true` (anything else is a 400), and so does the category discovery inside the list.
- `daemon/api/traffic.py`, `daemon/services/live_connections.py`: their private engine-only copies now use the shared rule.
- `daemon/services/alert_intelligence.py`: smart alerts split counted and activity into separate queries, so a group is never part activity, part counted. Activity groups are level 5, never boosted, add nothing to the threat score and carry `activity: true` for their drill-down link.
- Audited and left alone: `api/logs.py` (raw log search shows everything), `services/threat_intel.py` (DROP/CINS/DShield rules, all Minor or Major).
- Web: proxies forward `activity`; the Alerts page has an Activity filter chip and a "… informational events not counted · Show" line.
- `config/suricata/nettap.yaml` is now an include at `/opt/suricata/include-configs/nettap.yaml` that sets `threshold-file: /etc/nettap/suricata-threshold.config` (device-local; the deploy script writes .44's suppress lines).
- Replay harness `scripts/remote/verify-detection.sh` with deterministic fixture PCAPs.
- Deploy `scripts/remote/deploy-detection-slice1.sh` + checker `scripts/remote/verify_detection_slice1.py`: counts before → .44's SIDs from OpenSearch (ET Informational/Unknown rules named "Bandwidth Sharing Tool", raised by .44, plus those already suppressed while the live rule still is one; never 2013075) → fixtures with the candidate threshold file (stops here if they fail; nothing changed) → rules baseline for slice 2 (`~/nettap-rules-baseline/rules`) → build → install the threshold file (written by the daemon, which mounts `/etc/nettap` rw as root) → recreate daemon, web, suricata-live → threshold parsed with the expected rule count → fixtures on live → counted + activity = every rule alert, each equal to a raw query → pages answer → .44's suppressed SIDs since the engine started = 0.
- Docs: `docs/user-guide/alerts.md` "What counts as an alert".

### Tests

- Daemon: 3,278 passed, 1 skipped (baseline 3,265 passed, 0 failed). New `tests/test_et_activity.py` (13); `test_smart_alert_paging.py` fake client routes the activity query; `tests/test_verify_detection_slice1.py` (2: which of .44's rules are suppressed; 2013075 never).
- G11 before the deploy (14 days, read-only): .44 raised ~147,000 alerts from 5 bandwidth-sharing SIDs (Mysterium/Traffmonetizer/EarnApp DNS and TLS SNI) and ~78,000 from two Go HTTP client UA rules (2024897, 2060251), all ET Informational/Unknown, all with .44 as the source. Only the 5 are suppressed: the Go rules match any Go program on .44, which carries strangers' traffic, so they stay recorded as activity. 2013075 (Major) fired 15 times from .44 and stays.
- ET "Unknown" over 30 days: 2060251 (Go UA, 38,820), GPL P2P BitTorrent (1,993) and ~280 low-volume web probes (ET HUNTING X-Forward-For/X-Client-IP/X-Real-IP set to localhost; GPL WEB_SERVER .htpasswd/.htaccess access). Per the owner's rule (counts use Minor, Major, Critical) they are activity, not counted.

### Pre-merge review (PR #197)

- /deep-review: no findings. /ponytail-review: a re-run after 14 days of suppression would find no SIDs and stop (fixed: carries the existing ones); one-use constant inlined.
- security-engineer: MEDIUM, the replay runner could plant a link in the output folder the host then writes report.txt (and the deploy's threshold file) through; fixed: the runner's only writable mount is a new empty `out/engine/`. LOW, carried SIDs are re-checked against the live rule (still ET Informational/Unknown "Bandwidth Sharing Tool") before they are kept. LOW, the Go UA rules dropped from the suppression.
- typescript-reviewer: MEDIUM, rule links from the activity list (table and drawer) opened the counted list; they keep `activity=true`, and category pages (counted only) aren't linked from it. MEDIUM, the "not counted" line kept the previous window's number while a new window loaded; cleared on a window change, and a failed same-window refresh keeps the last number.
- Python reviewer: the counted/activity partition and every importer of the shared exclusion are correct. Fixed in the checker: read every smart group (activity sorts last), and a timeout fails one check instead of aborting the rest.
- Follow-ups, not in this PR: the smart summary still files "ET INFO" and "GPL" names under informational by name prefix, so a Minor-rated ET INFO rule counts on Alerts but is informational in the summary; Device alerts and a connection's related alerts list counted alerts only; `/api/alerts/count` doesn't report partial shard reads; `deploy-drill-down.sh` (retired) compares with engine-only raw counts.

### Deploy and verification

(filled in after the G11 run)
