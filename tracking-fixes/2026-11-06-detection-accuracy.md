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

G11, 2026-11-07 06:14–06:27 UTC, branch rebased on main 50e6f2f (after #196), `bash scripts/remote/deploy-detection-slice1.sh`: **verified, every check ✓.**

- 7-day window 2026-10-31T06:14Z → 2026-11-07T06:14Z: before, the API counted 708,872 alerts; after, **4,104 counted + 704,768 activity = 708,872**, each equal to a raw OpenSearch query.
- .44: 8 ET Informational "Bandwidth Sharing Tool" SIDs suppressed (Mysterium, Traffmonetizer, EarnApp, Grass; DNS and TLS SNI): 2067455, 2067457, 2067460, 2067462, 2067467, 2067469, 2067472, 2067474. Suricata: "Threshold config parsed: 8 rule(s) found"; 53,492 rules loaded, 0 failed. Fixtures passed before (with the candidate file) and after (live config): activity-stun, suppress-44, keep-2013075-44.
- Live: 0 alerts from the suppressed SIDs from .44 in the 5 minutes after the engine started (225 alerts indexed overall; before, these SIDs fired ~11 a minute from .44).
- Pages: /api/alerts, categories, top-signatures, smart summary, risk scores, devices count, IoT fleet summary all 200; activity list 704,768; `activity=yes` 400; 2,133 of 3,530 smart groups are activity, all level 5. No daemon errors since the restart.
- Rules baseline for slice 2 saved on the device at `~/nettap-rules-baseline/rules`. Replay runs kept under `~/nettap-replay/` (~46 MB each; prune later).
- Rollback of the suppression: write an empty `/etc/nettap/suricata-threshold.config` and recreate suricata-live.

## Slice 2: more free sources, optional ET Pro code, one rules lock (branch `feature/detection-slice2`)

Status: merged as PR #206 (`c548f865`) and verified on the G11 (below). The G11 is back on `main`.

### Changes

- **Sources** (`docker/docker-compose.yml`, suricata-live): `SURICATA_UPDATE_ENABLE_SOURCES: "et/open,abuse.ch/sslbl-blacklist,echap/stalkerware,ipfire/dbl"`. `SURICATA_DISABLE_SIDS` adds the IPFire allowlist `re:msg:"IPFire DBL \[(?!Malware\]|Phishing\])`, so every update (startup, nightly, manual) keeps only IPFire's Malware and Phishing categories (4 rules each: DNS, HTTP, QUIC, TLS). `SURICATA_UPDATE_ETOPEN` removed (OLD CODE): 26.10.0 doesn't read it, and upstream would add ET Open beside ET Pro.
- **One update path** (`config/suricata/nettap-rules-update.sh`, mounted ro): `start` runs as root in the entrypoint wrapper after the capture env loader. It wipes `/var/lib/suricata/update/sources/*.yaml`, records the start-time source list (600, PUID; `docker exec` doesn't get the loader's env), and installs a shim at Malcolm's `suricata-update-rules.sh` (Malcolm's kept as `malcolm-suricata-update-rules.sh`). Startup, the nightly cron and "Update now" all run `update`:
  1. Take the flock on the `nettap-rules-state` volume.
  2. Recover an unfinished attempt (marker), then run Malcolm's updater (its options, `--fail`).
  3. Wait until the engine's reload time moves and it reports 0 failed rules.
  4. Publish a verified `gen-*` last-good copy (atomic symlink swap; keep 2).
  5. On a failure, restore the last good copy and reload it (blocking, retried while a reload is in progress).
  6. Write `update-status.json` (`active`/`prepared`/`failed`/`interrupted`, a reason with any ET Pro code redacted, last success, last activation).

  TERM/INT kill Malcolm's process group and roll back.
- **Lock users:**
  - The daemon (`services/rules_lock.py`, fcntl) holds it while it restarts suricata-live for a capture-mode change (240 s wait, then "try again") and while it saves or clears the ET Pro code (60 s).
  - Deploy scripts take it from the host with a holder container (`scripts/remote/rules-lock.sh`: live image, PUID, no network, all caps dropped, `flock -w 900`, sleeps ≤ 30 min, `docker rm -f` releases). The device's sudo allows docker only, so `sudo flock` isn't possible.
  - `verify-detection.sh` takes the snapshot holding it; with no lock yet, it keeps the 23:50–00:30 refusal.
- **"Update now"** runs the shim as `suricata` (`docker exec -u suricata …`) and reports the status record. 200 = active/prepared, 202 = still running after 270 s, 500 = failed (the record's reason).
- **Live status** adds `enabled_sources` (names only, from `source:` lines), `etpro_rules` (active SIDs 2800000–2899999), `engine` (`ruleset-stats`, `ruleset-reload-time`; null when Suricata doesn't answer) and `update` (the record; `prepared` reads `active` once the engine loaded later; `stale` after 48 h without success; `recovery_pending`).
- **ET Pro code** (`services/etpro.py`, `POST/GET/DELETE /api/suricata/rules/commercial`):
  - The code must be `^[A-Za-z0-9]{16,64}$`.
  - Preflight: a one-byte GET (`Range: bytes=0-0`, redirects followed, body not read) of `https://rules.emergingthreatspro.com/<code>/suricata-<suricata-offline -V>/etpro.rules.tar.gz` (10 s). Anything but 200 or 206 is a plain 400 or 502 and changes nothing.
  - Save holding the rules lock: `/etc/nettap/suricata.env` (600, atomic), then `docker restart` suricata-live. A failed restart puts the previous file back.
  - The reply is 202, and a background watch records the activation: engine reload after the restart, rules loaded/failed, ET Pro SIDs, sources, update state.
  - GET answers `{configured, active, last_update_ok, applying, activation}` and never the code. Logs carry the preflight result and the activation outcome, never the code.
  - The capture env loader turns `et/open` into `et/pro|secret-code=…`. It ignores an invalid code with a message that doesn't echo it.
  - Clear deletes the file and restarts; the wipe at start drops the stored ET Pro source.
  - The old Snort Subscriber/ET Pro "commercial" methods and handlers are retired as OLD CODE.
- **Web** (teammate web-etpro):
  - Settings › Suricata rules shows a status line for the last update, worst news first, and the real enabled sources with friendly names.
  - An ET Pro card replaces the commercial form: Saved / In use / Last update, save, and remove with a confirm step. It polls every 15 s while applying.
  - "Update now" reads 202 as still running.
  - The proxies allow 290 s and pass status codes through. So do the DHCP gateway enable/disable and setup save proxies (were 60 s), because a Suricata restart there can wait 240 s for the lock.
  - The main Settings page's unconnected "Emerging Threats Pro key" field is retired (OLD CODE). A link to Settings › Suricata rules replaces it, and the daemon no longer accepts `SURICATA_ET_PRO_KEY` as an API key.
- **Device scripts:**
  - `gate-detection-slice2.sh`:
    - Stages the new update path in a throwaway container: live image, network on, 1 GiB, 1 CPU, the source list and disable.conf lines from the pulled compose file, a fresh data dir.
    - Then `check-staged`: allowlist, datasets resolved, owner SID range.
    - Then fixtures on the staged rules (0 failed; the IPFire/Echap fixtures pass).
    - Then own traffic, live vs staged, with the SID difference.
  - `deploy-detection-slice2.sh`: gate first, then build, the daemon and web, and a recreate of suricata-live holding the lock. Then it checks the sources, allowlist, shim, startup update, last-good, engine, live status, memory and capture, the fixtures on live, "Update now" and the daemon log.
  - `check-etpro-canary.sh` and `check-rules-update-safety.sh`: see the device run order below.
  - `rollback-detection-slice2.sh`.
  - Shared helpers in `rules-checks.sh`, including the canary and safety scripts' common preflight.
- **Replay tool** (`verify_detection.py`):
  - Fixtures drawn from the ruleset replayed: IPFire Malware/Phishing hits from each category's dataset; the owner's DoH name `dns.quad9.net` must fire no disabled IPFire category; an Echap stalkerware hit.
  - New commands: `check-staged` (the gate's checks) and `diff-sids` (own traffic, live vs staged).

### Tests

- Daemon: 3,687 passed, 4 skipped. New:
  - `test_etpro.py` (32): regex, the one-byte GET preflight, 200/206 accepted, 403/500/unreachable/timeout refused, 600 file, restart under the lock, failed restart restores, busy at once while an update runs, ≤ 60 s lock wait, activation and honest status, code never in replies or logs.
  - `test_rules_lock.py` (9).
  - `test_rules_update_status.py` (18).
  - `test_rules_contract.py` (5): each reply's exact keys against the web's TypeScript interfaces. It found "Update now"'s record without `stale`, now fixed.
  - `test_verify_detection_rules.py` (13).
  - `test_settings_api.py`: +1, the retired key is never written.
- Bats:
  - `test_rules_update.bats` (22; 18 need Linux): 22/22 in `ghcr.io/idaholab/malcolm/suricata:26.10.0` with a 256 KiB tmpfs for the disk-full case. Each of 5 mutants (no redaction, no gen.tmp cleanup, no trap, no wipe, no atomic swap) fails a test.
  - Capture env loader: +4.
  - `test_verify_detection.bats`: rewritten, 5 tests, for the lock.
  - Compose: +1 for the sources, allowlist, mounts and state volume. Two existing compose tests were adapted (the rules start step after the loader; the single-quoted value).
  - macOS total: 196, 0 failed, 18 skipped.
- Web: Vitest 3,798 passed (`suricata-rules-etpro.test.ts` 20 new; the DHCP and setup proxy tests now expect 290 s). svelte-check 0 errors; its 2 warnings were already there. `check:colors` and `check:e2e` clean. Visual 276 passed; the 49 skipped are the reduced-motion project.
- shellcheck clean on every changed script (the loader as `sh`). ruff 0.17.3 check and format clean on every touched daemon file.
- Local rehearsal of the gate's staged update with the real image (non-root, 1 CPU, fresh data dir): 64 s, status `prepared`, last-good published. The staged rules:
  - 65,377 active rules of 81,409;
  - IPFire Malware 4 and Phishing 4, nothing else;
  - 2 datasets (17.5 MiB);
  - 994 Echap rules and 10,957 SSLBL rules;
  - no owner-range SID.

### Deviations from the plan

- **Host-side lock: a holder container instead of `sudo flock`.** The device's sudo allows docker only.
- **Daemon lock waits:**
  - Capture-mode restarts wait 240 s, not 900 s, so the answer comes back inside HTTP time limits.
  - An ET Pro save or clear waits 60 s, and answers 409 at once while "Update now" runs in the daemon. The worst case is 210 s, under the web's 290 s.
- **ET Pro save:**
  - The lock is taken before the file is written, not after, so a running update never sees half a change.
  - The reply is 202 once the restart is issued. Readiness is followed in the background: GET adds `applying` and `activation`. The restart plus the startup update can take minutes.
  - The request body is `{code}`.
- **Persisted start-time source list.** `docker exec` doesn't get the loader's ET Pro swap.
- **Lock file opened read-only.** The daemon (root) may have created it.
- **When a rollback reloads:** only when files were actually restored, or on interrupt or recovery. A failed download that wrote nothing needs no reload.
- **Malcolm's `grep -v` quirk is not handled.** An empty output would fail the pipeline, but on 26.10.0 the three "conf file does not exist" warnings always print.
- **DoH negative fixture:** a query for `dns.quad9.net` must fire no disabled IPFire category SID.
- **"Update now" answers 202** when the update is still running after 270 s.
- **Live status additions moved into slice 2:** engine facts and the status record (the plan had them in slice 3 step 1). The deploy checks and the Settings status line need them. The source toggles' retirement stays in slice 3.
- **Overlap check:** a holder lock and a daemon flock probe stand in for "a custom-rule save", which is slice 3.
- **Recreate while an update is queued:** an update waiting for the lock in the old container stops with it. It has written nothing, because the marker comes after the lock. The new container's startup update is the one that "runs after the new container is up".
- **The gate stages the free sources only.** An ET Pro code is never passed on a `docker run` command line. "suricata -T: 0 failed" is covered by suricata-update's own `-T` plus the replay's "N loaded, 0 failed".
- **First-deploy refusal window: 23:00–00:30 UTC**, because the gate runs before the recreate.
- **`NETTAP_REPLAY_ROOT`** is a test override for `verify-detection.sh`.
- **ET Pro preflight is a one-byte GET, not a HEAD.** suricata-update downloads with GET. A signed redirect can allow GET only and refuse HEAD, which would turn away a good code. 206 counts as accepted.
- **DHCP gateway and setup save proxies wait 290 s (were 60 s).** Their Suricata restart can wait 240 s for the rules lock.

### Pre-commit review

- /deep-review: no findings. Root writing through a link Malcolm's user could plant in `/run/nettap-rules` was judged post-compromise only, and hardened anyway (`start` removes links, creates the lock file with O_EXCL, writes the sources file through a fresh temp file). A bats test plants the links.
- /ponytail-review: no must-fix. Fixed: the safety script's "no update cut off" check could never fail (it now reads the new container's log for the recovery line); the DHCP and setup proxies' 60 s timeouts; a redundant `except`; the duplicated preflight; the HEAD preflight.

### Reviews (round 2)

Three reviews of `6abb4a81`: a security engineer, a correctness reviewer for the daemon and shell, and a TypeScript reviewer. None found anything critical. Every fix below has a test that fails on the code before it (checked by running the new tests against `6abb4a81`).

Confirmed read-only on the G11: `/var/lib/suricata` is an anonymous image volume owned by `suricata` (only `rules/` is the named volume), and supercronic runs as `suricata`. Chain 27 is corrected.

**Security**
- **M1.** The daemon (root) opened `rules.lock` and `update-status.json` on the volume Malcolm's user owns. A planted link was followed (`O_CREAT` created its target), a FIFO blocked the event loop, and `/dev/zero` gave an endless read.
  - Fix: `rules_lock.open_regular` opens with `O_NOFOLLOW | O_NONBLOCK` and refuses anything that isn't a regular file. The status record is read through it, with a 64 KiB cap.
  - pytest: link, FIFO and oversized file, for both files.
- **L1.** `start` checked only the last path part for a link.
  - Fix: it now refuses, before wiping or writing anything, when a parent of the sources dir or the sources file isn't a real directory (`cd -P` differs from the literal path). No `suricata` process runs during `start`, so there is no race.
  - bats: a linked parent.
- **L2.** Malcolm's updater had no time limit, so a stalled download held the lock.
  - Fix: `setsid timeout -k 30 ${NETTAP_RULES_UPDATE_MAX:-900}`. A timeout is a failed update and the last good rules are restored.
  - The deploy and the rollback now recreate suricata-live anyway when the lock wait runs out. The stopped update leaves its marker, so the next start restores the last good rules first.
  - bats: the time limit.
- **L3.** `update` now refuses to run as root, pointing to `docker exec -u suricata`.
  - Image bats now run as uid 1000.
  - bats: a faked `id -u` of 0.
- **L4.** `failure_reason` now strips control characters.
- **I1.** The ET Pro code is checked with `re.fullmatch`, so `code\n` is refused.
  - pytest: the trailing newline.
- **I4 (canary script):**
  - It searches after canary A, after canary B and after the clear. Every stage covers the docker logs, `/run/nettap-rules`, suricata-live's `/tmp`, `/etc/suricata` and `/var/log/suricata`, and the API answers. After the clear, `/etc/nettap` and `/var/lib/suricata/update` are searched too.
  - A failed search or `docker logs` counts as a failure ("?").
  - In the wrapper, Malcolm's output is redacted by a process substitution before it reaches `$OUT`. A SIGKILLed run leaves no code in `/tmp`.
  - bats: the output file is checked while the update runs and again after a SIGKILL.
- **I5.** At startup, the daemon removes a `SURICATA_ET_PRO_KEY` saved before the field was retired from `/opt/nettap/data/.env`. It logs the key name only.
  - pytest.
- **I3, follow-up, not changed now.** `/etc/nettap/suricata.env` is root-only (600), but root in any other container that mounts `/etc/nettap` can read it. Narrow those mounts, or move the code to a dedicated volume that only the daemon and suricata-live mount.

**Correctness**
1. **The first run could wedge for ever.** With no last good copy, every rollback failed, so the marker stayed and every later run stopped at "recovering".
   - Fix: a missing, dangling or empty last good copy is "nothing to restore" (`restore` returns 3). The rollback succeeds without touching the files or the engine, so the marker clears. A generation without a non-empty `suricata.rules` never empties the live rules.
   - Status reasons now say which happened.
   - bats: a first run that fails, then succeeds; a dangling last good link.
2. **Rollback didn't return to ET Open.**
   - Fix: with the lock held and before the recreate, Step 4 removes `sources/*.yaml` and `nettap-enable-sources` as `suricata`.
   - The ET Pro and "code cleared" checks use `test ! -e`, so they fail when the daemon container is down. `enabled_sources` fails when it can't ask.
   - Deviation: the old compose file names no source, and suricata-update then uses ET Open without writing a source file. So "none named" stays accepted, but only when suricata-update answered and the rules file holds ET rules (new check "ET Open rules"). "Exactly `et/open`" would fail on every correct rollback.
3. **Partial source set.**
   - Fix: after a successful update, the wrapper compares the configured sources with the enabled source files and records `missing_sources` in the status record. There is no rollback.
   - The daemon passes the field through (a list of names, `[]` by default).
   - The web type and the contract test include it. The Settings status line shows it amber: "The last update worked, but these sources weren't enabled: …".
   - Deviation: the wrapper reads the source files' `source:` lines (what the daemon's live status reads) rather than calling `suricata-update list-enabled-sources`. Same answer, no extra process.
   - bats: a source that fails to enable.
4. **Small fixes:**
   - The Suricata `docker restart` under the rules lock now has a 120 s limit (pytest).
   - A second ET Pro save or clear cancels the first readiness watch (pytest).
5. **Test gaps:**
   - **TERM with the engine running** (bats). The test found a real bug: a bare `return` in `reload_blocking`, called from the TERM trap, returned the status from before the trap (143). So every interrupted update with Suricata running recorded "engine not confirmed" and kept the marker. It now returns `$?`.
   - `test_rules_lock.py` asserts the real 240 s default. The no-op monkeypatch is gone.
   - The disk-full test runs in the image bats (256 KiB tmpfs, mode 1777); it skips only outside Linux.

**Web**
- **H1.** The 15 s ET Pro poll uses `refresh.runIfIdle()`.
- **M2.** One `busy` flag turns off Update now, Save code and Remove code. Behaviour change: "Update rules now" is off while an ET Pro change applies.
- **M3.** A save or remove failure shows in the card as `notice is-error` with `role="alert"`, until the next attempt.
- **M4.** The field error has `role="alert"`.
- **L5.** A save resets `confirmingRemove`.
- **L6.** The status is read again after a failure as well.
- **L7.** The green "active" line also needs `etpro.active`.
- **L8.** A test checks the real `RULE_UPDATE_TIMEOUT_MS`.
- **L9.** `error` is used only when it is a string.
- 12 new page tests, plus the API test and the constant test.

**Reviews (round 2, gates)**

- **/deep-review** (delta `6abb4a81..c0afbd75`): no findings. Its record is in the security review.
- **/ponytail-review**: one must-fix and four small findings, all fixed.
  - **Must-fix:** Malcolm's startup `timeout 300s` sends TERM to the whole process group, so it also killed the `sed` redactor with its output still buffered, and the stopped run printed nothing. The redactor now ignores TERM and INT and drains once `on_signal` has killed the updater's group. A bats test runs `timeout 1 bash … update` (as docker_entrypoint.sh does) and requires the updater's line in the output. It fails on `c0afbd75`.
  - **Lock message:** the deploy and rollback "couldn't take the rules lock" message now covers both causes: the lock was busy for 15 minutes, or the holder container didn't start.
  - **Restart timeout:** `capture_control` uses etpro's `RESTART_TIMEOUT_S`; its own constant is kept as OLD CODE. `proc.kill()` ignores `ProcessLookupError`, with a pytest.
  - **Test cleanup:** the duplicate `statusReads` helper is gone. The 240 s and 290 s constant tests stay, each with a comment saying it pins the daemon-to-proxy timing contract.
  - **Leftovers:** the dead `mkdir -p` in `start` is removed. The legacy key cleanup now logs the key name it removed.
- **Tests after the gate fixes:**
  - daemon 3,700 passed, 4 skipped
  - Vitest 3,813 passed; svelte-check 0 errors
  - bats on macOS: 205 tests, 0 failed, 25 skipped
  - image `test_rules_update.bats` as uid 1000: 31/31
  - shellcheck and ruff clean

**Tests after round 2**

| Suite | Result |
|---|---|
| Daemon pytest | 3,699 passed, 4 skipped |
| Vitest | 3,813 passed |
| svelte-check | 0 errors |
| `check:colors`, `check:e2e`, `vite build` | clean |
| Visual | 276 passed, 49 skipped (the reduced-motion project) |
| bats on macOS | 204 tests, 0 failed, 24 skipped (they need Linux) |
| `test_rules_update.bats` in the Malcolm 26.10.0 image, as uid 1000 | 30/30, 0 skipped |
| shellcheck, ruff 0.17.3 | clean |

### Device run order (owner)

1. `bash /home/nettap/NetTap/scripts/remote/deploy-detection-slice2.sh`: gate first; if it fails, nothing is built or restarted.
2. `bash /home/nettap/NetTap/scripts/remote/check-etpro-canary.sh`: three Suricata restarts.
3. `bash /home/nettap/NetTap/scripts/remote/check-rules-update-safety.sh`: four downloads and one recreate.

Rollback: `bash /home/nettap/NetTap/scripts/remote/rollback-detection-slice2.sh`. It removes the ET Pro code first, then goes back to `main` (or a given commit) and recreates suricata-live. `~/nettap-rules-baseline` is kept.

### Not verifiable without the device

- Proofpoint's real answer to a bad code.
- The startup update's time against Malcolm's 300 s limit on the G11.
- Memory and RSS with the IPFire datasets.
- `docker compose config --format json` on the device's Compose version.
- `dump-counters` field names for capture drops.
- Whether Malcolm's crontab still points at the shim path after a restart.
- The holder-container lock on the real volume. It was proved with Docker Desktop.

### G11 run (2026-11-07, branch `feature/detection-slice2` @ `bde17614`)

All three scripts passed, run in order with nettap-23 told first. The G11 stays on the branch until the PR merges.

**`deploy-detection-slice2.sh`:**
- **The gate:** the staged update took 109 s.
  - The staged rules load 65,451 rules with 0 failed. The live rules before held 53,492.
  - All 7 fixtures pass.
  - The G11's own traffic gives the same 427 alerts and 7 SIDs on the live and staged rules ("SIDs only with the new rules: 0").
- **The recreate (14:00:31 UTC):**
  - The startup update finished at 14:01:08, 37 s, well inside Malcolm's 300 s limit.
  - The engine started at 14:04:07.
  - Enabled sources: `abuse.ch/sslbl-blacklist,echap/stalkerware,et/open,ipfire/dbl`.
  - The IPFire allowlist and the shim are in place, a last good generation was kept, 65,451 rules loaded and 0 failed.
- **The replay against the live rules:** the IPFire Malware and Phishing fixtures, the IPFire disabled-DoH fixture and the Echap stalkerware fixture all pass.
- **"Update now"** through the daemon was active within 47 s.
- **Errors:** none in the daemon log.
- **Memory:** suricata-live used about 0.9–1.0 GiB, and the host had 2.4–2.7 GiB available.
- **Capture:** enp4s0, 0 dropped.
  - The deploy's own capture line printed nothing. Malcolm's `suricata.yaml` has `stats: enabled: no`, so `dump-counters` answers "stats are disabled in the config".
  - Fixed in `9d87ba69` to use `iface-stat`. Checked on the G11: "6515 packets, 0 dropped on enp4s0".

**`check-etpro-canary.sh`:**
- Canary A and canary B were each saved as root 600. Each update was refused with Proofpoint's real answer, `HTTP Error 404: Not Found`, and logged with `<code>` in place of the code.
- After each one, the previous rules stayed loaded (same rules hash, 65,451 loaded, 0 failed), and Settings showed "configured true, active false".
- After the clear, the sources were back to the four free ones.
- No canary appeared at any stage in:
  - the docker logs of suricata-live or the daemon;
  - `/run/nettap-rules`, `/tmp`, `/etc/suricata` or `/var/log/suricata`;
  - any of the 6 daemon API answers;
  - (after the clear) `/etc/nettap` and `/var/lib/suricata/update`.

**`check-rules-update-safety.sh`:**
- An unreachable source and a source with a broken rule each failed and kept the previous rules, and neither left the marker behind.
- A lock taker waited out "Update now".
- A recreate during manual updates cut no update off.

**Answers to "Not verifiable without the device":**
- Proofpoint answers a bad code with HTTP 404.
- The startup update takes 37 s on the G11.
- Malcolm's crontab still runs `/usr/local/bin/suricata-update-rules.sh`, which is the shim, after the restarts.
- The holder-container lock works on the real volume (safety check B).
- Capture drops come from `iface-stat`, not `dump-counters`.

## Slice 3: Settings matches the device; own rules (branch `feature/detection-slice3`)

Status: built and tested locally, pushed, no PR yet. Not on the device.

### Changes

- **Own rules volume** (`docker/docker-compose.yml`):
  - `suricata-custom-rules` is rw in the daemon at `/var/lib/nettap-suricata-custom` and ro in suricata-live at `/opt/suricata/rules/custom`.
  - Malcolm 26.10.0 sets `SURICATA_CUSTOM_RULES_DIR=/opt/suricata/rules`. `suricata_config_populate.py` adds `glob(CUSTOM_RULES_DIR/**/*.rules)` to `rule-files` at every start, as absolute paths.
  - The volume holds only `owner.rules` and `owner.rules.prev`.
  - The daemon creates an empty `owner.rules` (0644) at start, and suricata-live waits for the daemon to be healthy, so Malcolm lists the file.
  - `nettap-rules-staging` is rw in the daemon at `/var/lib/nettap-rules-staging` and never mounted in suricata-live.
  - The `update-sources.yaml` mount on suricata-live is retired (OLD CODE). The file stays for the legacy source endpoints.
- **Validator** (`daemon/services/owner_rules_validator.py`):
  - Each non-blank line is a `#` comment or one rule whose action is exactly `alert`.
  - The options are split on `;` by a quote- and backslash-aware parser, so a `;` or a keyword inside `msg`/`content` text is just text.
  - Refused keywords: `lua`, `luajit`, `luaxform`, `config`, `bypass`, `dataset`, `datarep`, `filestore`.
  - Exactly one `sid`, from 1000000 to 1999999, unique across the file.
  - At most 2,000 rules and 256 KB of UTF-8 text. Empty content is allowed and clears the rules.
- **Save** (`daemon/services/owner_rules.py`). It holds the daemon's rule-operation lock and the slice 2 rules lock from start to end (30 s wait, then 409):
  1. Remove staging dirs older than 1 h.
  2. `docker inspect` suricata-live and the daemon: image, PUID/PGID, the live rules volume's name, and the staging volume's host path.
  3. Snapshot into `nettap-rules-staging/<uuid>/`: `docker cp` of `/etc/suricata` and `/opt/suricata/include-configs`, plus `custom/owner.rules` = the candidate.
  4. Refuse (409) if the snapshot's `suricata.yaml` doesn't list `/opt/suricata/rules/custom/owner.rules`. That means suricata-live started before the volume existed, and a reload would never read the file.
  5. Suricata's test: `docker run --rm` of the live image with `-T -v`, no network, 1 GiB, 1 CPU, the live UID/GID, all caps dropped except the three its binary's file caps need, and no-new-privileges.
     - Mounts, all ro: the snapshot at the live paths, the live rules volume, the candidate at the custom dir, and the threshold file when it is a regular file.
     - It must exit 0 and print "0 rules failed" within 180 s.
     - `docker rm -f` always runs afterwards, so a timeout or a cancel leaves no container behind.
  6. Write `owner.rules.prev` (the previous rules), then `owner.rules`. Each write goes through `.owner.rules.tmp-<uuid>` (O_EXCL, O_NOFOLLOW, fsync, 0644) and `os.replace`.
  7. A blocking `reload-rules` (120 s) must answer OK, and `ruleset-stats` must show 0 failed.
  8. On any failure in 7, put the previous rules back, reload again, and answer 502 ("… The previous rules were put back.", or that Suricata didn't confirm it).
  9. The staging dir is removed in `finally`.
  - Logs carry counts and results only, never rule text. An unexpected error logs its type only.
- **API** (`daemon/api/suricata_rules.py`):
  - `GET /api/suricata/rules/custom` → `{content, rule_count, max_rules, max_bytes}`.
  - `POST …/custom/check` → 200 `{ok, rule_count}` or 400 `{error, errors: [{line, message}]}`. It runs NetTap's checks only and saves nothing.
  - `POST …/custom` → 200 `{saved, rule_count, engine: {loaded, failed}}`. Otherwise:
    - 400: NetTap's checks, or no text.
    - 409: busy, or Suricata not set up for own rules.
    - 422: Suricata refused; `errors` carries each failing line and Suricata's reason.
    - 502: not loaded, previous rules put back; or suricata-live couldn't be inspected or copied.
    - 500: test timeout, or anything unexpected.
  - The old handlers that wrote the unwired `config/suricata/custom.rules` are retired as OLD CODE. `SuricataRuleManager.add_custom_rules/get_custom_rules` stay, unrouted.
- **Live status:** `owner_rules` counts the `alert` lines in suricata-live's `owner.rules`, or is null when that file isn't there (suricata-live not recreated with the mount).
- **Web** (teammate web-slice3):
  - Settings › Suricata rules retires the unwired source toggles and schedule picker as OLD CODE. It shows the engine facts: loaded/failed, last reload, own rule count, and the update record, with "downloaded" (file) kept apart from "active" (engine).
  - A "Your own rules" card (`OwnerRulesCard.svelte`): a monospace editor with loading, empty, error, validating and saving states; **Check rules** and **Save and load**; each refusal shown on its line.
  - Save and load is off while `owner_rules` is null. The page's `busy` covers a save, so **Update now** and the ET Pro buttons wait for it (it holds the same lock).
  - The limit text comes from the GET, so it follows the daemon's constants.
  - Proxies: GET with the default timeout, the save with 290 s, and a new `custom/check` route.
- **Device scripts:**
  - `deploy-detection-slice3.sh`:
    - Gate 1, before anything is built: slice 2 is live, Suricata runs cleanly, and `SURICATA_CUSTOM_RULES_DIR` is `/opt/suricata/rules`.
    - Then it builds and recreates the daemon and web.
    - Gate 2, before suricata-live is touched: `owner.rules` and the staging dir exist in the daemon, the GET answers, and `/check` accepts an alert rule and refuses a drop rule.
    - Then it recreates suricata-live holding the rules lock.
    - Then it verifies: `rule-files` lists `owner.rules`, the custom mount is read-only, no `update-sources.yaml` or staging mount, the engine shows 0 failed, the live `owner_rules` equals the saved count, and the update is active. Last, the daemon log.
  - `check-owner-rules.sh` runs the plan's G11 sequence through the daemon API. It refuses if own rules exist and clears the test rule on exit.
    1. Save the self-test rule: owner count 1, and the engine loads exactly one rule more, 0 failed.
    2. Replay: the fixture fires.
    3. Restart suricata-live holding the lock: still listed, still 1, 0 failed.
    4. Clear: the engine loads exactly one rule fewer, which proves the restarted engine had loaded it.
    5. Replay: the fixture is absent.
  - `verify-detection.sh --owner-rule present|absent` adds the dedicated `owner-selftest` fixture PCAP (a DNS query for `nettap-selftest.invalid` from 192.168.1.50). The expectation goes to `verify_detection.py` as `NETTAP_OWNER_FIXTURE`; without the option the fixture isn't built.
  - `deploy-detection-slice2.sh` now pulls `main`.

### Tests

- Daemon: 3,796 passed, 4 skipped (macOS). New:
  - `test_owner_rules_validator.py` (52): every plan fixture (pass, drop, reject, config inside an alert, bypass, each Lua keyword, quoted `;` in content/msg, duplicate sid, out-of-range sid), broken quotes and parentheses, 256 KB just under and just over, UTF-8 bytes, 2,000 and 2,001 rules.
  - `test_owner_rules.py` (31): success; Suricata's refusal (422, line numbers, nothing changed, no reload); exit 0 without "0 rules failed"; a reload failure and failed rules after the reload restore the previous rules; an unconfirmed put-back; docker failing at the reload still puts the previous rules back; a timeout and a cancel each remove the container and release both locks; the yaml guard; an interrupted save leaves no extra `*.rules` and no temp file; busy lock; concurrent saves run one after the other; empty content; staging never under the custom dir (constructor refuses, and the custom dir holds only the old file during the test); the runner's box; the threshold mount; prepare and stale cleanup; logs never carry rule text.
  - `test_rules_contract.py` +6: GET, check and save keys against `OwnerRules`, `OwnerRuleError` and `OwnerRulesSaveResult`; `owner_rules` in the live status.
  - `test_suricata_rules.py` +1, and the Linux script test reads a real `owner.rules`. `test_verify_detection_rules.py` +4.
  - The touched daemon tests pass in `python:3.12-slim` on Linux: 143, none skipped.
- Bats: `test_compose_validation.bats` +1, `test_verify_detection.bats` +1, `test_check_owner_rules.bats` (3, new) and `test_deploy_detection_slice3.bats` (2, new). macOS total: 212, 0 failed.
- Web: Vitest 3,865 passed. New: `OwnerRulesCard.test.ts` (21: each state, typing kept through a new file, Check rules ok/400/failed, Save and load 200/empty/400/422/409/502/failed/in progress) and `suricata-rules-owner.test.ts` (16: engine figures, retired controls gone, how the page feeds the card, one change at a time across cards). svelte-check 0 errors (its 2 warnings were already there). `check:colors` and `check:e2e` clean. Visual 276 passed; the 49 skipped are the reduced-motion project.
- The page is 836 lines, over the 800 cap. About 257 are comments, mostly kept OLD CODE; the owner rules card is its own component (coordinator: no other split).
- With the real image (`ghcr.io/idaholab/malcolm/suricata:26.10.0`, local Docker):
  - `OwnerRules._snapshot` and `_test` ran against a container of the live image, with `rule-files` set as Malcolm sets it. A good rule passed, a rule with an unknown keyword was refused on line 2 with Suricata's reason, and empty content passed.
  - The `owner-selftest` PCAP replayed against the self-test rule fired sid 1999999 from 192.168.1.50.
- shellcheck clean on every new or changed script. ruff 0.17.3 check and format clean on `daemon/`.

### Deviations from the plan

- **256 KB of text, not 1 MB** (coordinator, 2026-11-07). A save must pass adapter-node's `BODY_SIZE_LIMIT` (512K), nginx's `client_max_body_size` (1m) and aiohttp's `client_max_size` (1 MiB), and JSON escaping grows rule text by about a third. No body limit was raised. The 2,000-rule cap stays, and whichever is hit first wins. One constant (`MAX_BYTES`); the web shows the daemon's numbers and messages.
- **The live rules volume is mounted read-only in the test container, not copied into the snapshot.** The rules lock is held, so no update changes it, and a save doesn't copy ~50 MB.
- **Lock wait 30 s, reload limit 120 s.** On the G11 a 65k-rule load takes ~20 s at 1 CPU and reloads took 24–53 s, so a save takes about a minute. Only stacked worst cases outlast the web's 290 s; the daemon then still finishes and the live status shows the outcome.
- **The yaml guard** (409) is an addition: `reload-rules` re-reads only the files listed at start.
- **`/check` is an addition** for the editor's validating state. It runs NetTap's checks only.
- **The `-T` runner adds `--set detect.sgh-mpm-caching=no`**, as the replay runner does: the Hyperscan cache dir isn't mounted there.
- **"Restore `.prev`"** writes the previous bytes back to `owner.rules` (the same bytes as `owner.rules.prev`) and reloads.
- **The live status counts own rules from the file** in suricata-live. The engine reports totals only, so "loaded" is shown by the reload's 0 failed and, on the G11, by `check-owner-rules.sh`'s one-more/one-fewer count.
- **Engine facts and the update record were built in slice 2** (recorded there). Slice 3 adds the own rule count and the page.
- **Rollback is a redeploy**, not a script: suricata-live recreated without the mount has no own rules.

### Device run order (owner)

1. `bash /home/nettap/NetTap/scripts/remote/deploy-detection-slice3.sh` (BRANCH `feature/detection-slice3` until the PR merges). Two gates; it stops before suricata-live is touched if either fails.
2. `bash /home/nettap/NetTap/scripts/remote/check-owner-rules.sh`. It saves a test rule, replays, restarts suricata-live once, clears the rule and replays again. It refuses if there are own rules already.

Rollback: set `BRANCH="main"` (or the previous commit) in the deploy script and redeploy. Back up `owner.rules` before removing the `suricata-custom-rules` volume.

### Not verifiable without the device

- `docker cp` of `/etc/suricata` from the running suricata-live. Checked against a created container of the same image.
- Malcolm's start with the custom dir mounted read-only inside its anonymous `/opt/suricata/rules` volume (PUSER_CHOWN can't chown it).
- The `-T` and reload times with the G11's rules, and the test container's memory.
- The engine's one-more/one-fewer counts after a save, a restart and a clear.
