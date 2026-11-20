# Plan Review Log: F2 device details store (NET-320)
Started 2026-11-20. MAX_ROUNDS=5. Session dir: .codex-review/2026-11-20-f2-device-details

## Round 1 - Codex

1. **High — A valid backup can be too large to restore.** Plan §2.1 permits 2,000 notes of 1,000 characters. Four-byte Unicode makes that 8,000,000 bytes before JSON overhead. The existing 8 MiB photo allowance adds about 11.2 MB after base64 encoding. Together they exceed the 16 MiB import limit at nginx, the web app, and the daemon. Export can succeed and leave the owner with an unusable backup. **Fix:** Set an aggregate serialized-byte budget for details that reserves room for photos and other sections. Enforce it on update and restore, and round-trip a boundary-size export through the actual HTTP validate/import path. [Photo allowance](<daemon/services/device_custom.py:38>) · [nginx limit](<docker/nginx.conf:219>) · [Web limit](<docker/docker-compose.yml:1079>) · [Daemon limit](<daemon/api/server.py:163>)

2. **High — The proposed write pattern exposes owner names and notes to local readers.** The roadmap requires mode `0600`. The atomic writer defaults to `0644` and explicitly applies that mode before replacing the file. Copying the names-store call as proposed in §2.1 would make the details file readable by other users with access to the directory, regardless of umask. **Fix:** Pass `mode=0o600` on every details commit. Assert the resulting file mode after both an update and a backup restore. [Roadmap state-file rule](<plans/2026-11-18-feature-roadmap.md:70>) · [Atomic writer](<daemon/services/capture_config.py:244>) · [Existing store call](<daemon/services/device_custom.py:288>)

3. **High — The G11 cleanup can erase a real owner edit.** The initial emptiness check and the unconditional `DELETE` in §5 are separate requests. An owner edit or backup restore between them can add details that the exit trap then deletes. Even a fresh read immediately before cleanup leaves that race. **Fix:** Run the mutating smoke test against a disposable data volume and seeded registry. Keep the live G11 check read-only and ship it with #5 as scheduled. [Proposed cleanup](<plans/2026-11-20-f2-device-details.md:123>) · [Roadmap deployment point](<plans/2026-11-18-feature-roadmap.md:389>)

4. **High — A known-damaged destination can produce a partial restore.** Plan §4 deliberately lets preflight pass when the running store already knows it will refuse `restore()`. Other sections can then change, including live retention and a confirmed capture-mode change. Deleting the damaged file as §3.6 suggests also leaves `_problem` latched until the daemon restarts. **Fix:** When `device_details` is present, check destination health before applying any section. Test that a damaged destination leaves a valid sibling section untouched, and document recovery by quarantining the file, restarting, and restoring a known-good backup. [Plan risk](<plans/2026-11-20-f2-device-details.md:84>) · [Latched store health](<daemon/services/device_custom.py:258>) · [Import side effects](<daemon/api/backup.py:76>)

5. **Medium — F2 can save more watches than #5 can honor.** The plan permits `watch_after_min` on all 2,000 entries. The roadmap budgets #5 for at most 50 watched MACs. A backup created before #5 ships could already exceed that limit. **Fix:** Enforce a maximum of 50 entries with a watch value under the update lock and in backup validation. Test the 51st watch, an edit to an existing watch at capacity, and adding a group-only device at capacity. [F2 limits](<plans/2026-11-20-f2-device-details.md:23>) · [Watched-device budget](<plans/2026-11-18-feature-roadmap.md:397>)

6. **Medium — A malformed DELETE target can clear a valid device.** `device_custom.normalize_mac` validates after the registry normalizer has discarded everything beyond the sixth octet. That behavior serves DHCP ingestion, but it makes an overlong editing URL resolve to a real device, contrary to §2.3’s promised 400. Normalizing backup keys can likewise collapse two entries onto one MAC. **Fix:** Validate the complete six-octet identifier at the mutation boundary and require canonical, unique keys in backup maps. Test that a rejected DELETE preserves the target’s details. [Custom normalizer](<daemon/services/device_custom.py:77>) · [Registry truncation](<daemon/services/device_registry.py:157>)

7. **Medium — The proposed row funnel has early exits.** `owner_fields()` returns immediately when a MAC has no name, icon, or photo. That is a normal case for a device with F2 details. The IP-device and traffic handlers also bypass presentation entirely when the custom store is absent, so changing only the `with_names` fallback cannot deliver the uniform shape promised in §2.2. **Fix:** Merge details independently of the names-store lookup and use the same empty row fields in both handler fallbacks. Test a details-only MAC through registry, device, and traffic HTTP responses. [Names-store early return](<daemon/services/device_custom.py:392>) · [Device fallback](<daemon/api/devices.py:903>) · [Traffic fallback](<daemon/api/traffic.py:1096>)

8. **Medium — The detail response misses one page and can mix two revisions.** The IP page reads `/api/devices/{ip}`, whose handler uses the row presenter. Adding notes only to the MAC registry endpoint leaves the IP page without them, despite #9 requiring both pages. On the MAC path, taking group and owner from `row_fields()` and then fetching notes separately can return old group/new notes after one atomic multi-field update. The shared mutation helper also hardcodes `app["device_custom"]`; changing its error message alone does not wire in the details store. **Fix:** Use one four-field snapshot for both detail handlers and the details mutation reply. Have update/clear return their committed snapshot, and explicitly select the target store in the mutation helper. Test both detail URLs, an unresolved IP-to-MAC lookup, and a concurrent update during response assembly. [IP page read](<web/src/routes/devices/[ip]/+page.svelte:444>) · [IP response](<daemon/api/devices.py:2188>) · [Mutation helper](<daemon/api/device_custom.py:46>) · [Both-page requirement](<plans/2026-11-18-feature-roadmap.md:585>)

9. **Medium — Copying the loader can defeat damage containment.** The reference loader checks `os.path.exists()` before opening. A path that cannot be inspected can appear absent, allowing an apparently healthy empty export that clears details when restored elsewhere. Its parse handler also misses `RecursionError`, which can let a damaged document abort daemon startup. **Fix:** Open directly and treat only `FileNotFoundError` as an empty store. Bound the read, classify permission and parse-depth failures as unavailable, and cold-start test that names still serve while details export fails. [Reference loader](<daemon/services/device_custom.py:213>) · [Proposed startup wiring](<plans/2026-11-20-f2-device-details.md:65>)

10. **Medium — Multiline notes change the persistent schema against the roadmap.** F2 prohibits control and format characters. Plan §§2.1 and 3.4 explicitly persist LF, a control character, and §5 makes that behavior a release test. A later reader following the roadmap could reject a backup produced by F2. **Fix:** Reject CR and LF consistently on PUT, load, and restore. Check for forbidden controls before trimming so a control-only input cannot silently clear an existing value. Update the smoke fixture accordingly. [Roadmap text contract](<plans/2026-11-18-feature-roadmap.md:379>) · [Proposed exception](<plans/2026-11-20-f2-device-details.md:25>)

11. **Medium — The promised backup failure reason never reaches the owner.** The export handler returns an unmarked exception-derived 500. Production middleware replaces its text, and the web client independently discards the response body and reports only `Export failed: 500`. A store-level test would pass while §3.6’s recovery guidance remained invisible. **Fix:** Map details-store unavailability to a fixed, user-safe `public_json` message, keep the path and exception in the daemon log, and surface that message in the web client. Test with the production middleware enabled. [Export handler](<daemon/api/backup.py:39>) · [Error middleware](<daemon/api/error_replies.py:63>) · [Web client](<web/src/lib/api/backup.ts:45>)

12. **Medium — Backup preview runs the new validation on the request loop.** `/api/backup/import` offloads validation, but `/api/backup/validate` calls it synchronously. Plan §2.4 adds normalization and character checks over as many as two million note characters. A normal restore preview can therefore stall unrelated daemon requests, including health checks. **Fix:** Run preview validation through `run_blocking` as import already does, and stop collecting diagnostics once the five promised reasons are available. [Import preflight](<daemon/api/backup.py:62>) · [Preview handler](<daemon/api/backup.py:242>)

VERDICT: REVISE

### Claude response

All 12 findings taken; the change for each is in the plan, §9.

- **Taken in full:** 1 (1 MiB details budget), 2 (mode 0600), 3 (the live check is read-only; the round trip runs isolated), 4 (a damaged destination refuses the import), 5 (50 watches), 6 (strict MACs, canonical backup keys), 8 (one snapshot for both device page reads; update returns it; _apply takes the store), 9 (open directly; bounded read; RecursionError is damage), 10 (notes are one line; controls refused before trimming), 11 (fixed 503 message; the web client shows it), 12 (preview off the loop; at most 5 reasons).
- **Taken in part:** 7. Details merge before owner_fields' early returns, and the with_names fallback gains the keys. The api/devices.py and api/traffic.py fallbacks run only without a device_custom store, which create_app always builds, so they are stated as test-only and left unchanged rather than given code.
- **New risks:** two budgets (50 watches, 1 MiB) that #5 and #9 must respect. The export error is now a fixed message, so the owner learns a file is damaged but not which one; the daemon log names it.

## Round 2 - Codex

1. **High — A successful write can make the store unreadable on restart.** §2.1 caps the serialized devices map at 1 MiB and the file at 1 MiB + 64 KiB, but leaves the encoding and indentation unspecified. I measured a valid 2,000-device fixture at **1,048,001 bytes** as a compact map and **1,118,037 bytes** using the reference store’s indented file format. The latter exceeds the **1,114,112-byte** loader ceiling. **Fix:** Define one UTF-8 encoding for the versioned file, check the exact bytes that will be written, and use the same limit when loading. Test that a boundary-size commit survives reopening the store and can still be exported. [Plan §2.1](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:21>) · [Reference writer](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/services/device_custom.py:288>)

2. **High — The 1 MiB quota still cannot guarantee that a full backup is restorable.** §9 #1 substitutes an arithmetic test for the requested HTTP round trip. Alert acknowledgements are exported in full and have no aggregate cap. A backup with 11.2 MB of encoded photos and 5 MB of acknowledgements can fit under 16 MiB, then cross the limit when a valid 1 MB details section is added. **Fix:** Check the complete serialized backup against the restore limit before reporting export success. Return an actionable error for an oversized export. Exercise both a near-limit success and an over-limit refusal through the real HTTP path, including reposting the successful export to validate and import. [Acknowledgement export](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/services/config_backup.py:269>) · [Acknowledgement writer](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/api/alerts.py:979>) · [Restore limit](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/docker/nginx.conf:219>)

3. **High — `strict_mac` still accepts malformed DELETE targets.** A trailing `:` or `:ZZ` contributes no hex digits. The proposed comparison therefore passes, and the registry normalizer discards the extra component. The shared `_run` also normalizes the route parameter before calling `_apply`, so validation there would already be too late. **Fix:** Select the details parser in `_run` and match the entire original route parameter against the supported six-octet grammar. Test both suffixes and assert that the existing entry survives each rejected DELETE. [Plan MAC rule](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:29>) · [Shared parser](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/api/device_custom.py:65>) · [Registry truncation](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/services/device_registry.py:157>)

4. **Medium — The IP page can return a MAC that the new write API rejects.** Its fingerprint lookup returns the observed DHCP address, and the IP response exposes that value as `device.mac`. The repo has a regression case for a real eight-octet DHCP address filed under a six-octet registry key. A client using the IP page’s MAC for a details PUT would receive 400 for a device editable from the registry page. **Fix:** Resolve the canonical registry MAC for the IP detail response and use it as the edit target. For an unusable observed MAC, return empty details while preserving the traffic measurements. Test the existing eight-octet fixture across both reads and a PUT using the returned target. [IP response](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/api/devices.py:2142>) · [IP page edit target](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/web/src/routes/devices/[ip]/+page.svelte:175>) · [DHCP regression case](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/tests/test_device_registry_refresh.py:817>)

5. **Medium — The deployment leaves the accepted web error fix out of the running system.** §2.4 changes `exportConfig`, but §5 rebuilds only the daemon. The web client is compiled into a separate image, so G11 can pass while the owner still sees only `Export failed: 503`. The proposed Vitest filter also skips the existing backup-client test file. **Fix:** Include the web image in the scheduled #5 deployment, verify both running image IDs, and run the backup-client tests as part of the release check. [Deployment steps](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:145>) · [Web image build](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/docker/Dockerfile.web:36>) · [Client tests](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/web/src/lib/api/backup.test.ts:46>)

6. **Medium — First use can fail when the configured data directory does not exist.** The reference store creates the parent as a side effect of creating its photo directory. The proposed photo-free `_commit` goes straight to `write_file_atomic`, whose `mkstemp` requires an existing parent. The store can therefore start healthy and fail its first PUT or restore with a storage error. **Fix:** Create the parent on the first actual commit. Test first PUT and first restore against an uncreated root, then reopen each store and verify its contents. [Reference commit](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/services/device_custom.py:283>) · [Atomic writer](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/services/capture_config.py:249>)

7. **Medium — The revised text rule still admits line breaks and values outside strict UTF-8.** Internal U+2028 LINE SEPARATOR and U+2029 PARAGRAPH SEPARATOR survive NFC, trimming, and the `Cc`/`Cf` filter. JSON can also carry an escaped lone surrogate, which passes those checks but cannot be encoded as strict UTF-8 for the byte budget. **Fix:** Reject line separators, paragraph separators, and surrogate code points in the shared update/load/restore validator. Add tests for each and retain a positive case for an ordinary four-byte character. [Text and byte contracts](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:26>)

VERDICT: REVISE

### Claude response

All 7 findings taken; the change for each is in the plan, §10.

- **1:** one compact UTF-8 file format; the budget is the exact file bytes and also the loader limit.
- **2:** handle_export refuses an over-limit backup with a fixed 413, tested through the real HTTP app at the edge and past it.
- **3:** strict_mac full-matches the raw grammar, chosen in _run.
- **4:** the IP read keys details by _mac_key and returns registry_mac as the edit target; the eight-octet fixture is tested.
- **5:** the deploy rebuilds both images and checks both IDs; backup.test.ts is in the suite.
- **6:** _commit creates the data directory.
- **7:** Cs, Zl and Zp are refused as well.

**New risk:** the export size check refuses a backup that some owners can make today (many photos plus years of acknowledgements). That is intended: such a backup would fail on restore. The message says what to remove.

## Round 3 - Codex

1. **High — The size check measures the daemon response, but the owner downloads a different file.** The web client pretty-prints the JSON before saving it. Using the encoded lengths of 32 permitted photos and 43,000 acknowledgement records, I measured **15,486,769 bytes** as compact JSON and **16,992,618 bytes** in the download format. The latter exceeds 16 MiB. Settings compacts the file again on upload, but an administrator posting the downloaded file directly to `/api/backup/import` gets a size refusal. The §10 test reposts the daemon response and misses this case. **Fix:** Produce compact UTF-8 once, preserve those bytes through the proxy and browser download, and test the downloaded file verbatim against both validate and import. [Plan §2.4](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:74>) · [Download and upload serialization](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/web/src/lib/api/backup.ts:58>)

2. **Medium — The 64 KiB reserve rejects backups that fit.** A serialized body of 16 MiB minus 32 KiB is below the configured restore limit, yet §2.4 returns 413 and tells the owner to remove data. This contradicts the latest Claude response’s rationale that the refused backups would fail on restore. **Fix:** Compare the final byte count with the receiver’s actual cutoff. Test the largest accepted body and the first refused body through HTTP. [Proposed cutoff](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:74>) · [Daemon limit](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/api/server.py:163>) · [nginx limit](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/docker/nginx.conf:219>)

3. **Medium — The new 413 can leave the owner without a usable recovery instruction.** The message says to remove pictures or old acknowledgements. On an appliance with no pictures and a large acknowledgement history, Alerts supports marking an alert acknowledged and provides no pruning action. Suppressions can also account for the excess. **Fix:** Identify the largest contributing section in the error and document a tested recovery procedure that archives its contents before pruning. Cover an acknowledgement-only oversized backup. [Acknowledgement routes](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/api/alerts.py:2401>) · [Exported alert sections](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/services/config_backup.py:269>)

4. **Medium — The live G11 check fails on an outcome the revised API explicitly permits.** §5 unconditionally requires the live export to contain `device_details`. A healthy appliance returning the intended size-limit 413 cannot meet that condition, so a correct deployment fails verification. **Fix:** On live data, verify the section on 200, report the specific size-limit 413 as an operational finding, and fail on other export errors. Keep section presence and round-trip success mandatory in the isolated fixture. [Live and isolated checks](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:154>)

VERDICT: REVISE

### Claude response

All 4 findings are about the export size check I added in round 2. Each shows that a correct check is a backup-wide feature, not part of F2. A correct check needs three things: it must measure the downloaded, pretty-printed file; it must compare against the real cutoff; and it must tell the owner which section to shrink, with an acknowledgement prune that does not exist yet.

- **The overflow is not F2's.** It exists today without F2, from uncapped alert acknowledgements.
- **Change:** I removed the export check from F2 and opened NET-344 (`fix: a config backup can be too large to restore`) with your four findings as its requirements.
- **F2 now bounds its own share more tightly:** a 512 KiB file budget (was 1 MiB), and a test that a full details store adds under 768 KiB to a backup as the browser saves it.
- **Rejected:** keeping a size guard in F2. A partial guard either refuses backups that restore fine or misses ones that don't, as rounds 2 and 3 showed. NET-344 owns it.
- **Finding 4** no longer applies: there is no 413 in F2, so the live check stands.

## Round 4 - Codex

**High — F2 can make a previously restorable backup exceed the upload limit.** The 768 KiB download bound holds. The remaining issue in §3 decision 9 is release sequencing. Settings uploads compact JSON, and I measured the following sizes using that serialization. [Decision 9](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:97>) · [Settings import](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/web/src/lib/api/backup.ts:93>)

| Backup fixture | Upload size | Result against the 16 MiB limit |
|---|---:|---|
| 32 maximum-size photos and 46,000 acknowledgements | 16,522,769 bytes | Fits |
| Same backup plus 480 valid device notes | 17,018,628 bytes | Exceeds limit |

The details file is 495,865 bytes, within its 512 KiB quota. F2 alone pushes this backup across the cutoff. Export still succeeds, so the owner discovers the problem at restore time. These are serialization measurements, not an executed HTTP restore. [F2 quota](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:29>) · [Restore limit](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/docker/nginx.conf:219>)

**Fix:** Keep the backup-wide work in NET-344 and make it a prerequisite for F2’s **production rollout**. Use this before-and-after fixture as a release test: any backup offered as a successful download must pass validation and import. F2 implementation can proceed independently.

VERDICT: REVISE

### Claude response

Taken, as you proposed: NET-344 gates F2's production rollout, and implementation goes ahead.

- **Release gate.** NET-344 is now High priority in the M1 v1.0 must-have milestone. Its description has a "Release gate" section: no tagged release ships F2 until NET-344 merges. Your before-and-after fixture is its release test.
- **The G11 rollout** (the only device on `main`) is made safe directly. Before anything is rebuilt, the deploy script exports the live backup, re-serialises it compactly as Settings uploads it, and stops with no change unless that size plus 768 KiB fits in `MAX_REQUEST_BYTES` (plan §5, §3 decision 9).

## Round 5 - Codex

**High — The release gate still permits F2 to reach live data before NET-344.** Decision 9 gates tags, but §5 puts the G11 headroom check in one feature-specific script. The existing names-and-pictures deploy independently pulls `main` and rebuilds the same daemon and web images. It can deploy F2 even after the F2 script refused. The repository also documents an untagged `main` installation path through nettap.dev. [Decision 9](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:98>) · [G11 deploy path](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/scripts/remote/deploy-device-names-pictures.sh:38>) · [Install verification](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/tracking-fixes/2026-11-16-fresh-install-cloud-ubuntu-2204-needrestart.md:12>)

**Impact.** Even when the intended script runs and passes, it measures headroom only at deployment. Subsequent acknowledgements can consume that space while F2 is live. An export can then succeed even though adding `device_details` pushed an otherwise restorable backup above the upload limit. [G11 preflight](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:157>) · [Acknowledgement writes](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/daemon/api/alerts.py:979>)

**Fix.** Make NET-344 and the passing before-and-after restore test prerequisites for merging F2 into `main` or deploying an F2 feature build against live data. Implementation and isolated image tests can proceed on the feature branch.

VERDICT: REVISE

### Claude response

Taken as proposed. NET-344 merges to `main` before F2.

- **F2 waits on the branch.** It is implemented and reviewed on its branch with isolated image tests, and its PR stays a draft. It does not merge, and no F2 build runs against live data, until NET-344 has merged and its before-and-after restore test passes on `main`.
- **Then F2 merges.** It is rebased onto that `main`, and the full suite is re-run before merge.
- **Headroom check.** The G11 headroom step stays as an extra check on the one live device; it is no longer the safeguard.

The owner allowed a sixth Codex round ("Run a six round if necessary"), so this goes to round 6.

## Round 6 - Codex

The final revision closes the rollout finding. Decision 9 and §13 require NET-344 to merge and its before-and-after restore test to pass on `main` before F2 can merge or run against live data. That covers untagged installs, other deploy scripts, and direct feature-branch deployments. F2 must then rebase onto that tested `main` and rerun its full suite before merge. I found no remaining material issue in the plan. [Decision 9](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.md:98>) · [Latest review response](</Volumes/ExtraStrg_RAID1/Mega Sync/Coding Projects/NetTap/.claude/worktrees/f2/plans/2026-11-20-f2-device-details.review-log.md:126>)

VERDICT: APPROVED

## Result

APPROVED in round 6 of 6. The owner allowed six rounds, and their standing instruction is "implement when you have approval". Findings by round: 12, 7, 4, 1, 1, then 0. The work is split out to NET-344, which merges first.
