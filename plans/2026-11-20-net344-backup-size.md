# Plan: every downloadable backup restores (NET-344)

_Round 6 revision by Claude, 2026-11-20 (Codex rounds 1–6: 12, 9, 8, 7, 7 and 8 findings; see §9–§14). Codex did not approve within the six-round cap; §14 lists what is taken and what is rejected, with reasons._

**Linear:** NET-344 (High, M1 v1.0 must-have) · **Blocks:** F2 device details (NET-320), whose PR stays a draft until this merges and its restore test passes on `main` · **Branch:** `fix/backup-size` from `origin/main` 07e1c1cd

## 1. Goal

Any backup NetTap offers as a successful download must restore: the exact bytes the owner saves pass `POST /api/backup/validate` and `POST /api/backup/import` through nginx, the web app and the daemon. The import must also accept every section the validation accepted. Today that's not guaranteed:

- **Re-encoding:** the web app re-encodes the JSON both ways.
  - On the way out, its proxy parses JSON replies and re-serialises them (`web/src/routes/api/[...path]/+server.ts:174-177`), and `downloadConfigFile` pretty-prints them (`web/src/lib/api/backup.ts:58-61`).
  - On the way in, Settings parses the file and re-serialises it (`backup.ts:79`, `:98`).
- **No caps:** acknowledgements, suppressions and excluded IPs have none, so an export can pass the 16 MiB restore limit, and the owner finds out at restore.
- **Validate and import disagree:** validation checks a few sections, while the import checks every section as it applies them. So a backup can validate, then have a section refused after earlier sections have applied. Examples are a legacy excluded-IP CIDR (`excluded_ips.py:645`) and a suppression `reason: null`.

## 2. Approach

### 2.1 One serialisation, kept byte for byte

**Encoder** (`config_backup.encode(obj)`): `json.JSONEncoder(separators=(",", ":"), ensure_ascii=False, allow_nan=False)`.
- Its output chunks pass through one rule: any surrogate code point is replaced by its `\uXXXX` escape. In a Python `str` every surrogate is a lone one, because a valid pair is a single code point.
- The result then encodes as strict UTF-8.
- The rule acts per character, so a section's encoded size never depends on what else is in the file (Codex r2 #2).
- `allow_nan=False`: a non-finite number fails the export with a fixed message naming the section (r1 #2).

**Daemon export** (`daemon/api/backup.py` `handle_export`):
- The config is built off the loop, then fitted (§2.3).
- It answers `web.Response(body=…, content_type="application/json")`, with `Content-Disposition: attachment; filename="nettap-config-<YYYY-MM-DD>.json"` (the owner's date) and `Cache-Control: no-store`.

**Web proxy** (`+server.ts`): a branch placed before the JSON path passes a 200 from `GET /api/backup/export` through unchanged.
- It streams `res.body` and forwards `Content-Type`, `Content-Disposition` and `Cache-Control`. Error replies still take the JSON path.
- `/api/backup/export` joins `SLOW_PATH_TIMEOUT_MS` at 60 s (r1 #6, #7).

**Web download** (`downloadConfigFile`):
- It fetches the export itself. When the reply isn't OK, it throws the reply's `error`, falling back to `Export failed: <status>`.
- When it is OK, it saves `await res.blob()` unchanged under the daemon's filename.
- It returns `{leftOut}`, from `JSON.parse(await blob.text()).metadata.acknowledgements_left_out` (0 when absent). The old parse-and-pretty-print path stays as `OLD CODE`.

**Web upload** (`readConfigFile`, `validateConfig`, `importConfig`, `BackupTab.svelte`):
- The body for validate and import is chosen once per selection:
  - the file's own text, when its UTF-8 size is under the cutoff;
  - otherwise `JSON.stringify(data)`, compacted once, if that fits. This keeps today's oversized pretty-printed files restorable (r1 #1);
  - otherwise a local refusal naming the size.
- Both posts send that string unchanged.
- Each selection gets a generation number, and Remove or a new selection bumps it. Only current-generation results are kept, and Apply sends only the body whose validation finished for the current selection (r1 #5).

### 2.2 The cutoff and the restore routes

- **The real cutoff:**
  - aiohttp refuses a body whose length is `>= client_max_size` (`aiohttp/web_request.py:675-678`);
  - nginx (`16m`) and adapter-node (`BODY_SIZE_LIMIT: "16M"`, `>`) accept exactly 16 MiB.
  - So a body restores when `len(body) < 16 MiB`. `RESTORE_LIMIT_BYTES` in `config_backup.py` names it.
- **A limits test pins all four:** `MAX_REQUEST_BYTES`, the nginx backup location, compose's `BODY_SIZE_LIMIT`, and the constant.
- **413 on both routes:** `handle_validate` and `handle_import` catch `web.HTTPRequestEntityTooLarge` before their general `except`, and answer a `public_json` 413: "This file is over the 16 MB restore limit." (r1 #8)
- **nginx timeout:** the backup location gets `proxy_read_timeout 300s`, which covers the web app's 290 s import budget (r1 #11).

### 2.3 Fitting: trim the oldest acknowledgements, refuse for owner settings (r3 #1, #2, #3)

_Round 2's "leave out whole sections" is withdrawn (see §11): a whole-section omission threw away acknowledgements that fit, and leaving out owner settings broke the restorable-backup promise when the source box is gone._

`fit(config) -> (body, left_out)`:

1. **Normalise display text only** (r2 #8, r4 #6). On the export copy, a suppression `reason` that isn't a string becomes text: `None` becomes `""`, and any other value becomes `str(value)`. That covers a numeric reason the old API stored unchanged. A reason is shown to the owner but never matched, so this changes no behaviour.
   - Every API that writes suppressions stores an integer `signature_id` (`int(sig_id)`, `api/alerts.py:2345`, `:2365`) and zone-aware times (`alert_intelligence.py:1077-1080`, `:1105`). So after this step, the importer's suppression check cannot fail on data the API wrote.
   - Nothing else is normalised. Excluded IPs are exported exactly as stored (r4 #1). A legacy range is refused at export by name (step 6), never silently dropped. Live Connections and Top Destinations apply ranges (`live_connections.py:604`, `traffic.py:520`), so only the owner can decide to remove one.
2. **Measure without building the body.** Each section's encoded size comes from streaming `encode` through `iterencode` and summing UTF-8 lengths. Each acknowledgement entry's size, `"id":{…}`, is measured the same way. The surrogate rule is per character, so sizes add up exactly (r2 #2).
3. **Trim the oldest acknowledgements.** If the total isn't under `RESTORE_LIMIT_BYTES`, keep the largest newest-first prefix of acknowledgements whose exact total fits. The total counts:
   - the kept entries;
   - exactly `max(n − 1, 0)` commas;
   - `"acknowledgements_left_out":<total − n>` in the metadata, digits included.
   - **The order** (r4 #3) is by the UTC instant of `acknowledged_at`, newest first. A missing, unparsable or zone-less time counts as oldest. Equal instants order by alert ID ascending. The sort key is `(instant or −∞, then alert ID)`. It never compares strings, which mis-order mixed offsets such as `+01:00` against `Z`.
   - A test proves maximality: the chosen prefix fits, and adding the next-oldest entry reaches the cutoff.
4. **Refuse for owner settings, never omit them.** Every other section is mandatory, names and pictures included (always together, r3 #3). If the backup with zero acknowledgements still doesn't fit, the export answers a fixed `public_json` 413, which names the largest section and its encoded size. For example: "This backup would be 17.4 MB, over the 16 MB restore limit. The largest part is excluded IPs (9.1 MB)." Then advice for the section:
   - **excluded IPs:** not reachable once capped at 10,000 entries (§2.5), which is at most about 0.4 MB;
   - **alert suppressions:** "NetTap can't remove suppressions yet (NET-346)." See §3 decision 6 for why this case stays a refusal;
   - **device pictures:** remove some pictures;
   - **notification rules:** remove some in Settings › Notifications (`DELETE /api/notifications/rules/{id}`);
   - **anything else:** "the daemon log lists each part's size".
   - One WARNING log line gives every section's size.
5. **Encode the final body once.** Assert its length equals the computed total and is under the limit.
6. **Check before offering the file:** the fitted config goes through the shared preflight (§2.4). If a section fails, the export answers a fixed `public_json` 422 and no file is offered. The reply carries a stable `code` (r6 #6):
   - **`legacy_excluded_ips`:** the excluded-IP list holds something an older NetTap allowed and this one can't restore: a range, or more than 10,000 entries. "Excluded IPs: 10.0.0.0/8 is a range. NetTap no longer keeps ranges, so it can't restore this one. Remove it in Settings › Network, then export again. Live Connections and Top Destinations stop hiding that range once it's removed." The over-the-cap version says how many to remove.
   - **`invalid_section`:** anything else, which is data no API writes, such as a hand-edited file. The log names the section, the entry and the file.
   - The deploy gates treat only `legacy_excluded_ips` as an expected finding. `invalid_section` always fails a gate.
7. **The note at download** (only when acknowledgements were trimmed): "Backup saved. It leaves out the N oldest alert acknowledgements to stay under the 16 MB restore limit; after a restore those alerts show as not acknowledged."
8. **One export at a time, and none queued** (r4 #7, r5 #7): while an export is building, another export gets an immediate `public_json` 503 with `Retry-After: 30`: "A backup is already being made. Try again in a moment." A flag set and cleared around the build in `try/finally` decides this; it never waits on a lock. A request whose client has gone can't start a build later, because nothing is queued. The web proxy forwards `Retry-After` on that 503 (r6 #7).

### 2.4 One preflight, shared by validate, import and export (r2 #1, r3 #4, #5)

- **Shared checks:** `section_errors(sections) -> dict[section, reasons]` holds the side-effect-free content check of every restorable section that `import_config` checks today. That is capture, retention, notification channels, rules and quiet hours, names and pictures (the `DeviceCustomStore` restore checks as a dry run), excluded IPs, bandwidth cap, home location, acknowledgements and suppressions.
- **The guarantee, precisely** (r3 #4): a content-validation failure applies zero changes. Operational failures after the preflight keep today's accurate reporting in `applied`, `skipped` and `errors`, for example a section file that fails to write, or a capture restart that fails after its config was saved. A restore is not claimed to be atomic.
- **Run once, off the loop** (r3 #5):
  - `handle_validate` runs the preflight through `run_blocking`;
  - `handle_import` runs it once through `run_blocking` and passes the result into `import_config`, which applies nothing when it has errors and doesn't validate again.
  - A populated near-limit validation (32 photos plus a large excluded-IP list) is checked while the event loop keeps answering `/api/health`.
- **The `acknowledgements_left_out` metadata** is validated (r2 #9):
  - absent means 0;
  - otherwise it must be a non-negative integer, not a bool;
  - a positive value requires an acknowledgement map in `sections`.
  - A malformed value is an ordinary validation error.
  - When positive, validation warns: "This backup leaves out N alert acknowledgements. Restoring replaces this NetTap's acknowledgements with the M it carries."
- **Suppression reasons:** the restore predicate accepts a string or `None`, because older backups carry `null`. The suppress API stores `str(reason or "")` from now on.
- **Excluded IPs:** every entry must be a single IP (`parse_single_ip`), the same rule as the Settings PUT, and the list holds at most `EXCLUDED_IPS_MAX` (10,000) after duplicates are removed (§2.5). The import writes the deduplicated list with the atomic writer (`write_file_atomic`), as the suppression file already does, instead of `Path.write_text`. A failed write then leaves the old file whole (r5 #6).

### 2.5 A cap of 10,000 excluded IPs (r6 #1, #3, #5)

_Round 5's 16 MiB Settings save is withdrawn. A list that large breaks the live views (OpenSearch refuses more than 65,536 terms in one clause, `devices.py:147`), renders 100,000 rows in Settings, and makes the save slow (r6 #1, #3, #5)._

- **`EXCLUDED_IPS_MAX = 10_000`** in `services/excluded_ips.py`:
  - **Settings PUT:** refuses a longer list: "Up to 10,000 excluded IPs. Remove some first."
  - **Restore:** the preflight refuses a longer list by name.
  - **Export:** a stored list over the cap gives the `legacy_excluded_ips` 422.
- **Why 10,000:**
  - it is well under the 65,536-term limit;
  - at most about 0.4 MB, so it never makes a backup too big, and Settings' 1 MiB save always fits it;
  - the Settings PUT for 10,000 IPv6 addresses is 177,079 bytes, and parsing it took 30 ms (measured);
  - a home network excludes a handful.
- **Duplicates** (r6 #3): `load_excluded_ips` removes duplicates in order, as the Settings PUT already does (`settings.py:283`). The import does the same. A list restored with two spellings of one address can then never give Settings two rows with the same key.
- **Atomic writes** (r5 #6): `save_excluded_ips` and the backup import use `write_file_atomic`. The `OLD CODE` blocks keep the old writers.
- **No nginx change for Settings:** its 1 MiB location stays.
- **Tests:**
  - the 10,001st entry is refused by the PUT and by the restore;
  - a stored list of 10,001 gives the `legacy_excluded_ips` 422; after the owner saves 10,000, the export answers 200;
  - a stored legacy range gives the same code, and after removal, a 200;
  - duplicate spellings restore as one entry;
  - an injected write failure leaves the old file and the reloaded list intact, for both writers.

## 3. Key decisions and tradeoffs

1. **Preserve the bytes, don't predict them,** so the measured size is the restored size. The one exception is the compaction fallback for an old oversized file, which measures the exact string it sends.
2. **Trim acknowledgements one by one; never omit an owner setting.** A backup that can't fit even without acknowledgements is refused, with the largest part named and sized. Every part that can grow has a UI to shrink it or a cap, except suppressions (decision 6).
3. **Only display text is normalised; behaviour is never changed silently.** A reason that isn't a string becomes text, because reasons are never matched. A legacy range changes what two live views show, so the export refuses it by name and the owner removes it. Restoring ranges was tried in round 4 and dropped: it needed a new predicate, a schema gate for rollback, and a second restore rule.
4. **One preflight, run once, off the loop.** A content failure applies nothing; operational failures are reported as they are today.
5. **The proof is per hop, plus a live check through nginx:** each hop is tested as the identity on the bytes, and the G11 check goes through authenticated nginx after nginx is recreated.
6. **A suppression-dominated backup stays a refusal, tracked as NET-346.** There is no list or removal action for suppressions today; building one (route, UI, tests) is its own slice.
   - **The exposure, in bytes** (r6 #8): with the largest picture set (32 pictures, about 11.2 MB as base64) and everything else at realistic sizes, about 4.5 MB is left for suppressions.
   - **Through the Alerts UI,** each entry is about 150 bytes plus its reason. `suppress_rule` keeps one entry per signature per scope (`alert_intelligence.py:1084-1090`), and the UI sends no reason. That is about 30,000 entries.
   - **The API and restores** don't limit a reason's length, so a few entries with very long reasons can use the space faster. Only a hand-written request or file does that, and the 413 fixture covers it.
   - **The refusal loses nothing,** since the box keeps every setting; only a full backup can't be made until NET-346.
   - **A related bug** found while reading this code is NET-345: an expired suppression blocks suppressing the same alert again.
7. **Concurrent Settings tabs are out of scope** (r6 #4). Every Settings tab saves its whole object, so two tabs open at once can overwrite each other. That is today's behaviour for every tab, and NET-344 doesn't change the excluded-IP save path. Moving the repair into Settings (round 5) is withdrawn, so no new path inherits it.

## 4. Risks and open questions

- **Old backup files** restore if they fit as files, or once compacted. Ones with legacy-invalid sections are refused by validation with a reason, before anything applies.
- **A content failure now applies nothing.** That changes one existing behaviour: a backup with one bad section used to apply the rest. Tests that relied on partial applies for content errors are updated, and the validation message names the bad section. Operational failures still report per section (§2.4).
- **Scripts reading the export** still get JSON:
  - `verify-device-names.py:97` parses the text;
  - `full-stack-test.sh:399` checks only the status.
- **F2 rebase requirements** (r1 #4, r2 #6, r3 #1, r4 #4, r5 #1). These are also written in F2's tracking doc (`tracking-fixes/2026-11-20-f2-device-details.md`, "Rebase requirements"):
  - **The live checks in `deploy-device-details.sh` differ by stage:**
    - **before the deploy,** the running NET-344 build has no `device_details`, so a valid 200 (printing `acknowledgements_left_out`) passes;
    - **after the recreate,** a 200 must carry `device_details`;
    - at both stages, the size 413 and the `legacy_excluded_ips` 422 are findings, not failures. An `invalid_section` 422, for example on `device_details`, fails, and so does any other answer.
    - **The classifier** is a standard-library-only script, `scripts/remote/classify_backup_export.py` (r6 #2). It imports nothing from the daemon. The deploy script pipes it into whichever daemon image is running, so it works on the NET-344 image before F2 exists. Its test runs it in a fresh interpreter with the daemon off `sys.path`, against a pre-F2 200, a post-F2 200, a 413, a `legacy_excluded_ips` 422 and an `invalid_section` 422.
  - **Shared checks:** `device_details` joins `section_errors`.
  - **Serialisation test:** rewritten against `fit` with ASCII and emoji notes.
  - **Release fixture:** 32 photos, 46,000 acknowledgements and 480 notes. It must give a 200 whose `acknowledgements_left_out` equals the expected count. The kept acknowledgement IDs must equal an independently computed newest set. Names, pictures and notes must be intact after import.
- **Rollback** (r3 #8):
  - New files are plain JSON, with suppression reasons already text.
  - If the code is reverted, old Settings re-stringifies a file it reads, which can push a near-limit file over the limit (`1e-05` becomes `0.00001`). The recovery is to post the saved bytes directly to the daemon on the box, which the tracking doc will document with the exact command (the token read inside the container, never printed). It uses the same `request.json()` path the old daemon has.
  - A test posts the `limit − 1` numeric fixture as raw bytes to validate and import and checks both accept it.

## 5. Verification

- **Encoder:** a lone surrogate is escaped while emoji elsewhere stay raw UTF-8; each section's measured size equals its share of the final body; `NaN` is refused with the section named.
- **`fit`:**
  - under the limit: nothing trimmed;
  - a body of exactly `limit − 1` bytes is kept whole;
  - one of exactly `limit` bytes trims the oldest acknowledgement;
  - maximality: the prefix fits, and adding the next-oldest entry reaches the cutoff;
  - count digits are handled at 9→10 and 99→100;
  - ordering: a fixture with mixed offsets (string order ≠ instant order), a zone-less time and a tie keeps exactly the IDs written by hand in the test (r4 #3);
  - a lone surrogate in a kept or dropped entry, with emoji elsewhere, still matches the computed total;
  - an excluded-IP-dominated and a notification-rule-dominated case each give the 413 with the right section named;
  - a legacy range gives the `legacy_excluded_ips` 422, and the box's file is unchanged;
  - a stored numeric suppression reason exports as text, and the export validates (r4 #6);
  - a suppression-dominated case gives the 413 that names NET-346, once with many short entries and once with a few very long reasons (r6 #8);
  - **memory** (r4 #7): two concurrent HTTP exports of a 32 MiB acknowledgement file in mixed ASCII and emoji text, measured from the file read through the response:
    - the second gets the immediate 503 with `Retry-After` while the first builds, under the production runner (`handler_cancellation` off, as `test_pcap_download_cleanup.py:51` sets up). A client that disconnects never causes a later build (r5 #7);
    - each finishes within 10 s;
    - `fit`'s own extra workspace (traced around `fit` alone) stays under 2 × the cutoff;
    - the whole-path peak is reported, and the G11 verifier prints it beside VmRSS before and after.
- **Preflight:**
  - every section's bad cases match today's import checks;
  - an invalid section beside a valid bandwidth cap gives `is_valid: false` and zero writes on import;
  - a valid bandwidth cap followed by a failed capture restart reports and persists exactly what happened (r3 #4);
  - the preflight runs once per import, off the loop, and `/api/health` answers during a populated near-limit validation.
- **HTTP** (aiohttp app with `client_max_size=MAX_REQUEST_BYTES`, the real routes and `safe_error_middleware`):
  - the before-and-after fixture is downloaded and posted as is to validate and import, into a different destination. The destination then has the names, the pictures and exactly the kept acknowledgement IDs (r3 #3);
  - the cutoff: valid JSON padded to `limit − 1` is accepted, `limit` gets the plain-English 413, and malformed JSON gets 400;
  - malformed `acknowledgements_left_out` values each give a validation error, not a 500;
  - the rollback fixture is posted as raw bytes.
- **Web:**
  - the proxy passthrough keeps the bytes and the three headers, and an export 503 keeps `Retry-After` (r6 #7);
  - the blob is saved unchanged;
  - the upload body is chosen as in §2.1;
  - selections completing out of order never apply under the wrong name;
  - the note and the warning render.
- **Suites:**
  - daemon `pytest`;
  - `uvx ruff@0.17.3 check daemon/ && uvx ruff@0.17.3 format --check daemon/`;
  - `cd web && npx vitest run && npx svelte-check`;
  - `npm run check:colors`;
  - visual tests for Settings › Backup;
  - `shellcheck` on the new deploy script.
- **G11** (`scripts/remote/deploy-backup-size.sh`), with no write to live data:
  - rebuild and recreate the daemon and web images, and check both image IDs;
  - **nginx:** before anything is rebuilt, test the checked-out config in a one-off container on a fresh mount: `docker compose run --rm --no-deps --entrypoint nginx nettap-nginx -t`, as `deploy-data-accuracy-batch16.sh` step 2 does (r4 #5). Then recreate the nginx container rather than reloading it: a checkout can replace the bind-mounted file's inode, `tracking-fixes/2026-11-12-installer-go-live-uninstall.md:52`, and `deploy-device-names-pictures.sh:53` does the same. Then `nginx -T` must show `client_max_body_size 16m` and `proxy_read_timeout 300s` on the backup location, (r3 #6);
  - **through authenticated nginx** (a 60-second session signed inside nettap-web, as `deploy-chart-drilldown-slice1.sh` step 10 does; never printed):
    - `GET https://localhost/api/backup/export` answers 200 under the limit, and its bytes, posted back unchanged, give `is_valid` from validate. The size 413 and the `legacy_excluded_ips` 422 are reported as findings, and the padded-document checks below still run. Any other answer fails, `invalid_section` included (r6 #6);
    - a valid `{"metadata":…,"sections":{}}` document padded with whitespace to exactly `limit − 1` bytes is accepted by validate, and by import with `applied: []`, so nothing is written;
    - the same document at `limit` bytes gets 413;
    - the size and `acknowledgements_left_out` are printed;
  - **isolated:** `verify_backup_size.py` runs in a throwaway copy of the daemon image. It runs the before-and-after fixture through `fit`, the preflight and `import_config` into temp paths, checking the kept acknowledgement IDs and the restored names and pictures, and prints `BACKUP-SIZE-OK`;
  - memory, logs and status.

## 6. Rollback and migration safety

- **Revert the PR.** See §4 for files near the limit.
- **No data migration.** Nothing stored on the box changes. The excluded-IP cap only refuses new saves and restores, and a stored list over it is reported at export.

## 7. Observability

- **Logs:** an INFO line when acknowledgements are trimmed, with sizes. A WARNING line with every section's size on a size refusal. An ERROR line naming the section and entry on a content refusal.
- **What the owner sees:** the note at download, the warning at restore, and the fixed 413, 422 or 503 messages.

## 8. Out of scope

- Pruning acknowledgements on the box.
- A list and removal action for suppressions (NET-346), and the expired-suppression bug (NET-345).
- Caps beyond the excluded-IP cap (§2.5). A size refusal names the part to shrink.
- Conflict detection between Settings tabs (decision 7).
- Compressing backups.

## 9. Round 1 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | Raw upload strands old oversized pretty files | The file's text if it fits, else one compaction, else a local refusal |
| 2 | Size check ≠ content restores | `allow_nan=False`; shared checks (widened in round 2) |
| 3 | No end-to-end restore through the deployed path | Per-hop identity tests; the live check through nginx (round 2) |
| 4 | F2's gates conflict | UTF-8 output; F2 rebase requirements (§4) |
| 5 | A/B selection race | Generation numbers |
| 6 | Fitter memory and time | Streaming size measurement (round 2) |
| 7 | Octet-stream drops `no-store` | `application/json` with a passthrough branch |
| 8 | The 413 swallowed as 400 | Explicit handling on both routes |
| 9 | No warning at restore | A validated `acknowledgements_left_out` warning (rounds 2–3) |
| 10 | No removal action for suppressions | Superseded in round 2: sections are left out, so no caps are needed |
| 11 | nginx 60 s timeout | `proxy_read_timeout 300s` |
| 12 | Rollback near the limit | Documented |

## 10. Round 2 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | Shared checks covered two sections | `section_errors` covers every restorable section; validate, import and export share it; a content failure applies nothing (round 3 wording); legacy CIDR fixture |
| 2 | Per-entry fitting not exact | Gone: whole sections, a per-character surrogate escape, maximality test |
| 3 | Suppression caps over budget and can lock Alerts | Caps removed (kept). Whole-section omission superseded in round 3 by a 413 |
| 4 | First encode materialises the history | Sizes measured by streaming `iterencode`; one final encode under the limit; concurrent mixed-text resource test |
| 5 | The G11 check bypasses nginx and the web app | Authenticated nginx probe, `nginx -T`, `limit − 1` and `limit` posts with an empty sections document |
| 6 | F2's post-deploy check expects 200 with details | `device_details` is never left out; the size 413 is reported as a finding (round 3) |
| 7 | Excluded-IP recovery needs a PUT larger than 1 MiB | Superseded in round 3: ranges are left out of the export copy; size is a 413 |
| 8 | `reason: null` breaks rollback | Normalised to `""` in the export copy |
| 9 | The warning reads unvalidated metadata | Metadata validated before the warning (now `acknowledgements_left_out`, round 3) |

## 11. Round 3 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | Whole-section omission drops acknowledgements that fit | Back to a newest-first prefix, now exact: the per-character surrogate rule makes sizes additive; `max(n − 1, 0)` commas; count digits; maximality test; F2 fixture checks the kept IDs |
| 2 | Dropping owner settings breaks the promise; the 500 is reachable (notification rules) | Owner settings are mandatory; a fixed 413 names the largest section and its size; excluded-IP and rule-dominated tests; live probes recognise the 413 |
| 3 | Pictures left out makes names skip on restore | Names and pictures are always both present (both mandatory); round trip to a fresh destination checks the restored names and pictures |
| 4 | "All or nothing" overclaims | Guarantee stated: a content failure applies nothing; operational failures reported as today; capture-restart test |
| 5 | Preflight on the loop and run twice | `run_blocking` in both handlers; import consumes one preflight result; responsiveness test |
| 6 | nginx reload can keep the old file | `nginx -t`, then recreate the container, then `nginx -T` and the probes |
| 7 | Legacy CIDR repair can't fit Settings' 1 MiB PUT | The export copy leaves out entries that aren't single IPs (ignored at runtime, `excluded_ips.py:645`); counted in the note; the box's file is untouched; no manual repair |
| 8 | Rollback can't recover a saved near-limit file | Documented direct-byte restore on the box (token inside the container); raw-byte post test at `limit − 1` |

## 12. Round 4 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | Dropping CIDRs changes the live views | Withdrawn. Excluded IPs are exported as stored, and the restore accepts single IPs and IP networks verbatim; a subnet fixture covers both views |
| 2 | The 413 leaves two recovery gaps (an excluded-IP list over 1 MiB; suppressions) | Section repair (§2.5): archive the section with `backup-section.sh`, edit it, restore it alone through Settings › Backup; tested with a 1.5 MiB list and reduced suppressions, and a re-export answers 200 |
| 3 | The ack tests can keep the wrong records | Ordered by UTC instant; zone-less or unparsable times count as oldest; ties by ID ascending; expected IDs written by hand in a mixed-offset fixture |
| 4 | F2's handoff describes the withdrawn design | F2's tracking doc synced with §4 (committed on the F2 branch) |
| 5 | `nginx -t` in the old container tests the old file | A one-off container on a fresh mount before anything is rebuilt, then recreate, `nginx -T` and the probes |
| 6 | A stored numeric reason blocks every export | Reasons that aren't strings become text in the export copy; upgrade test; the content refusal points to the section repair and no longer claims to be unreachable |
| 7 | The memory test starts after the file parse | Measured from the file read through the response for two concurrent HTTP exports; exports serialised by a lock; `fit`'s workspace bounded separately |

## 13. Round 5 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | F2's pre-deploy check needs `device_details` before F2 exists | The stages differ: before the deploy, a valid NET-344 200; after, `device_details` is required. One tested classifier; both documents synced |
| 2 | The network predicate accepts `true` and scoped IPv6 | Gone: ranges are no longer restored. The restore keeps `parse_single_ip`; a legacy range is a named 422 at export |
| 3 | A CIDR backup half-applies on the old importer | Gone with #2: a new export never carries a range |
| 4 | The repair archive can't always undo | Gone: the section repair is withdrawn. Settings can save any list a backup can carry (nginx `16m` location) |
| 5 | An offline repair can erase later changes | Gone with #4: every edit goes through the live Settings save |
| 6 | A failed large write can empty the excluded list | `write_file_atomic` for the backup import and the Settings save; injected-failure tests |
| 7 | The lock queues abandoned exports | An immediate 503 with `Retry-After` while one builds; nothing waits; production-runner test |

Also: the suppression-dominated 413 is a deliberate refusal, tracked as NET-346 (decision 6). NET-345 records the expired-suppression bug found on the way.

## 14. Round 6 changes (Codex), and where the review ended

Codex returned REVISE in round 6, the owner's cap. Taken:

| # | Finding | Change |
|---|---------|--------|
| 1 | A 16 MiB Settings list breaks the live views (over 65,536 terms) | The 16 MiB save is withdrawn; excluded IPs are capped at 10,000 for the Settings save and the restore (§2.5) |
| 2 | F2's classifier imports F2-only code | A standard-library-only `classify_backup_export.py`, run in a fresh interpreter in its test |
| 3 | Duplicates and huge lists crash or swamp Settings | Duplicates removed on load and on import; the cap keeps the list renderable |
| 5 | A large PUT blocks the event loop | Not reachable at the cap: 10,000 IPv6 is 177 KB and parses in 30 ms; the 1 MiB location is unchanged |
| 6 | The two gates treat the 422 differently | Stable codes: `legacy_excluded_ips` is a finding in both gates, `invalid_section` fails |
| 7 | The proxy drops `Retry-After` | Forwarded on the export 503; tested in the proxy |
| 8 | The suppression estimate has no byte basis | Decision 6 restated in bytes; long-reason fixture |

Rejected: **#4, a lost update between Settings tabs.** Every Settings tab saves its whole object; that is pre-existing, and NET-344 no longer adds a path that inherits it (decision 7).
