# Plan: F2, device details store (NET-320)

_Codex APPROVED in round 6, 2026-11-20 (rounds 1–5: 12, 7, 4, 1 and 1 findings; see §9–§13)_

_Update after NET-344 merged (#342, 2026-11-20): the 768 KiB "as the browser saves it" bound and the pre-deploy headroom check are superseded. NET-344's `fit` measures the real compact file, and the deploy checks use its classifier. F2's share of a backup is its compact map, at most 512 KiB. The tracking doc's "Rebase" section has the details._

**Linear:** NET-320 · **Roadmap:** `plans/2026-11-18-feature-roadmap.md` §F2, decision D2 · **Depends on:** nothing · **Used by:** #5 watched devices (NET-331), #9 groups/owners/notes
**Branch:** `feature/f2-device-details` from `origin/main` 07e1c1cd

## 1. Goal

A per-device store for facts the owner adds that NetTap can't discover: how long a device may be gone before it counts as offline (`watch_after_min`, for #5), and a `group`, an `owner` and `notes` (for #9). Nothing the owner sees changes in this slice; it gives #5 and #9 a safe place to keep their settings, an API to set them, and a backup section.

Why a new file and not `device_custom.json`: `_validated` (`daemon/services/device_custom.py:157-179`) refuses any entry key outside `{name, icon, photo}` and marks the whole store unreadable. New keys there would make a rolled-back daemon refuse the file and serve no names or pictures at all until it was fixed by hand.

## 2. Approach

### 2.1 Store (`daemon/services/device_details.py`, new)

- **File:** `<NETTAP_DATA_DIR>/device_details.json`, `{"version": 1, "devices": {MAC: {"watch_after_min"?, "group"?, "owner"?, "notes"?}}}`. MACs are normalised with `device_custom.normalize_mac`. An entry is never empty: clearing its last field removes it.
- **Class `DeviceDetailsStore(root=None)`,** the `DeviceCustomStore` pattern without photos:
  - `threading.Lock`;
  - **One file format** (r2 #1): `json.dumps({"version": 1, "devices": …}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)`, encoded as strict UTF-8. The size budget is checked on exactly these bytes, and the loader uses the same limit, so a write that fits always reopens.
  - `_load()` opens the file directly; only `FileNotFoundError` means an empty store (no `os.path.exists` check, which reports a path it can't inspect as absent: r1 #9). It reads at most `DETAILS_MAX_BYTES + 1` bytes; a longer file is damaged. Then `_validated()` refuses anything that isn't stored clean.
  - **Damaged:** any other `OSError`, `ValueError` (JSON included), `RecursionError` or an over-long file sets `_problem` and logs one error naming the path. The store then serves nothing and refuses every write and export with `StoreUnavailable` (the class from `device_custom`). `_problem` stays until the daemon restarts; recovery is to move the file aside, restart, and restore a known-good backup (§7);
  - `_commit(devices)` creates the data directory if it is missing (`os.makedirs(root, exist_ok=True)`, r2 #6: `write_file_atomic`'s `mkstemp` needs the parent, and only the photo path creates it today). It then calls `write_file_atomic(path, text, mode=0o600)`: names, owners and notes are the owner's own words, and the roadmap's state-file rule is 0600 (r1 #2). Then the in-memory swap. An OSError leaves both as they were.
- **Limits** (`DEVICES_MAX = 2000`, as `device_custom`):
  - `watch_after_min`: an int (not a bool) in `{15, 30, 60, 240, 1440}`, on at most `WATCH_MAX = 50` devices, the budget #5 is planned for (roadmap #5). A 51st watch is a 400; changing an existing watch at 50 is fine (r1 #5).
  - `group` up to 32 characters, `owner` up to 64, `notes` up to 1,000. Each is NFC-normalised. Characters in the Unicode categories Cc (control), Cf (format), Cs (surrogate), Zl (line separator, U+2028) and Zp (paragraph separator, U+2029) are refused *before* trimming (r1 #10, r2 #7). So `"\n"` is a 400 and never clears a field, notes are one line like the rest, and an escaped lone surrogate can't reach the UTF-8 byte budget. Then trimmed. An ordinary four-byte character (an emoji) is allowed.
  - A text value that is empty after trimming means "clear", the same as `null`.
  - **Size budget:** the file's exact bytes (the format above) stay within `DETAILS_MAX_BYTES = 512 KiB`, checked on every update and restore. Without it, 2,000 four-byte-character notes alone would be 8 MB. A full store adds under 768 KiB to a backup **as the browser saves it** (the web client pretty-prints the download, `web/src/lib/api/backup.ts:58`), and a test pins that bound. Whether a whole backup fits the 16 MiB restore limit is a backup-wide question F2 does not settle: see §3 decision 9 and NET-344.
- **MACs** (r1 #6, r2 #3): `device_custom.normalize_mac` keeps the first six octets of a longer string (a DHCP need), so on its own `…:FF:00`, `…:FF:` or `…:FF:ZZ` would edit device `…:FF`. Details use `strict_mac(raw)`, which matches the **whole** raw string against six hex pairs joined by one consistent separator, `:` or `-` (`[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}`, full match, ASCII), and returns it upper-cased with colons. Anything else is a ValueError. Backup keys must already be canonical (`AA:BB:…` upper case), so two keys can never collapse onto one device.
- **`update(mac, changes)`:** `changes` is an object with at least one of the four keys and nothing else. `null` clears a field. Every field, the watch count and the size budget are checked under the lock before anything is written, so a bad change writes nothing. One commit. A change that leaves the store as it was writes nothing. **Returns the committed four-field snapshot** (r1 #8).
- **`clear(mac)`:** removes the entry; nothing to remove writes nothing. Returns the (empty) snapshot.
- **Reads:**
  - `get(mac)` returns a copy of all four fields, each `None` when unset; one read under the lock, so the fields always come from one revision;
  - `row_fields(mac)` returns `{group, owner, watch_after_min}` (no notes) and never raises: a non-MAC or a damaged store gives all `None`.
- **Backup:**
  - `export()` returns `{MAC: entry}` and raises `StoreUnavailable` on a damaged store, as `DeviceCustomStore.export` does, so a backup is never silently incomplete;
  - `problems(section)` is a pure validator for the preflight. It returns up to 5 reasons and stops there (r1 #12), and it checks canonical keys, fields, the watch count and the size budget;
  - `restore(section)` replaces the whole set in one commit after the same checks.

### 2.2 Rows and the device page

- **Rows:** `DeviceCustomStore.owner_fields` (`device_custom.py:381`) feeds every row shape: `DeviceRegistry.with_names` (`device_registry.py:962`) and `DeviceCustomStore.present` (`device_custom.py:406`, used by `api/devices.py:908` and `api/traffic.py:1096`).
  - `DeviceCustomStore.__init__` takes an optional `details: DeviceDetailsStore | None`.
  - `owner_fields` adds `group`, `owner` and `watch_after_min` from `details.row_fields(mac)`, all `None` without a details store. The details are merged **before** its early returns (a non-MAC, or a MAC with no name or picture), so a device with only details still shows them (r1 #7).
  - The no-store fallback in `with_names` (`device_registry.py:965-968`) gains the same three keys. The other two fallbacks (`api/devices.py:908`, `api/traffic.py:1096`) run only when the app has no `device_custom`, which `create_app` always builds; they stay as they are, and the plan says so rather than adding code for a test-only path.
  - A test sends a details-only MAC through the registry list, `GET /api/devices/{ip}` and the traffic breakdown.
- **Notes stay on the device pages, from one snapshot** (r1 #8): both device page reads, `GET /api/devices/registry/{mac}` (`api/devices_v2.py:408`, the MAC page) and `GET /api/devices/{ip}` (`api/devices.py:2188`, the IP page), take one `details.get(mac)` and set `group`, `owner`, `watch_after_min` and `notes` from it, over the row fields.
  - **The IP page's MAC** (r2 #4): its `device.mac` is the address the fingerprint observed, which can be an eight-octet DHCP chaddr filed under a six-octet registry key (`tests/test_device_registry_refresh.py:817`). The IP read keys details by the registry's own form (`_mac_key(mac)`, the same rule the registry files devices under) and adds `registry_mac`, the canonical MAC a client must use to edit them. No usable MAC means `registry_mac: null` and the four fields `None`; the traffic figures are unaffected. List, search and traffic rows never carry notes, so a 1,000-character note isn't repeated 2,000 times in a list reply.

### 2.3 API (in `daemon/api/device_custom.py`, beside the name and picture routes)

- **`PUT /api/devices/registry/{mac}/details`:** body is a partial object (§2.1). The device must be in the registry, as for a name. Replies `{"device": …}`: the registry row with the four fields from the snapshot `update` returned, so the reply is exactly what was committed.
- **`DELETE /api/devices/registry/{mac}/details`:** works for any valid MAC, so an owner can tidy up after a device has gone. Same reply. Both routes parse the raw route parameter with `strict_mac`, chosen in `_run` (which today normalises before `_apply` runs, so a check inside `_apply` would be too late; r2 #3). An over-long or malformed MAC is a 400 and changes nothing.
- **The shared helper:** `_apply` (`api/device_custom.py:46`) gets `request.app["device_custom"]` today. It takes the change as a function of the request's app, so the details routes act on `app["device_details"]` and fold the returned snapshot into the reply.
- **Errors, through the existing `_run`:**
  - a bad MAC, body or field is a 400 with the plain-English reason;
  - an unknown device is a 404;
  - a damaged details file is a 503, "Device details can't be saved: their file is unreadable." (`_run` gains the message as a parameter; names and pictures keep theirs);
  - an OpenSearch error is a 502;
  - a storage failure is a 500.
- **Auth:** the daemon token middleware covers these routes like every other. The web app gets no route in this slice (no UI).

### 2.4 Backup (`daemon/services/config_backup.py`)

- **Section:** a new `device_details` section in `_VALID_SECTIONS`.
- **Export:** `{MAC: entry}` from `export()`. A damaged details file fails the export, as a damaged picture does today (`config_backup.py:252-255`).
  - **The owner sees why** (r1 #11). Today `handle_export` (`api/backup.py:35-45`) answers a 500 built from the exception, which the production error middleware replaces, and `exportConfig` (`web/src/lib/api/backup.ts:45`) shows only "Export failed: 500". Now `StoreUnavailable` becomes a fixed `public_json` 503: "A device settings file is unreadable, so the backup would be incomplete. The daemon log names the file." The path and exception go to the log. `exportConfig` shows the reply's `error` when there is one, with a Vitest test.
- **Preflight:** in `validate_import`, when the section is present:
  - any `problems()` set `is_valid = False` with up to 5 reasons;
  - a damaged details store on this box sets `is_valid = False` with "Device details on this NetTap are unreadable; fix that before restoring them." (r1 #4: otherwise other sections, a confirmed capture-mode change included, would apply before the details restore failed).
  - Either refuses the whole import before anything applies (`api/backup.py` returns 400), as for quiet hours (NET-330).
- **Preview off the loop** (r1 #12): `handle_validate` (`api/backup.py:242`) calls `validate_import` on the request loop. It goes through `run_blocking`, as `handle_import` already does.
- **Backup size is NET-344, not F2** (r2 #2, r3 #1–#4): alert acknowledgements are exported in full with no cap (`config_backup.py:269`), so a backup can pass the 16 MiB restore limit today, with or without F2. A correct guard has to measure the file as downloaded, compare it with the real cutoff, and tell the owner which section to shrink, with a way to prune acknowledgements that doesn't exist yet. That is its own slice, NET-344. F2 only keeps its own addition small and bounded (§2.1).
- **Restore:**
  - A present section replaces the details set: devices absent from it lose their details, which matches names and pictures.
  - An absent section, from a backup made before F2, leaves the current details alone (the NET-200 rule), with no note.
  - A failure goes in `errors` like the device custom block (`config_backup.py:486-495`).
- **Web:** `BackupTab.svelte` `SECTION_LABELS` gains `device_details: 'Device details'`, so the restore list shows a word and not the key. This is the only web change.

### 2.5 Wiring (`daemon/api/server.py`)

- `device_details = DeviceDetailsStore()` is created before `DeviceCustomStore(details=device_details)` (`server.py:1386`).
- It is stored as `app["device_details"]` and passed to `ConfigBackup(device_details=…)` (`server.py:1568`).

## 3. Key decisions and tradeoffs

_Decisions 3, 4 and 6 changed in round 1; the earlier wording is in §9._

1. **Rows get details through `owner_fields`, by passing the details store into `DeviceCustomStore`.** This gives one funnel and no change at the five call sites. The cost is that the two stores are coupled at presentation only, and a details failure can never affect names (`row_fields` never raises).
2. **Notes only on the device page's read,** not in lists. That keeps list replies small and keeps free text out of the many places rows go (CSV export, search).
3. **An empty text value clears,** the same as `null`, so a future form that empties a field just works. The alternative was refusing `""` with a 400.
4. **Notes are one line, like the other fields** (r1 #10). The roadmap's "no control or format characters" holds everywhere, checked before trimming. #9 can revisit line breaks with its UI, as a schema change of its own.
5. **The backup preflight refuses a bad section before anything applies,** like quiet hours. Names and pictures still validate inside `restore()`, after earlier sections have applied, and this slice doesn't change that.
6. **A damaged details file blocks backups,** as a damaged picture does (NET-200: "Raises rather than hand back an incomplete one"). The owner now sees a fixed reason (§2.4). Recovery means moving the file aside and restarting, because the damage flag is latched (§7).
8. **Two new budgets:** 50 watches and 512 KiB of details. Both are enforced on writes and restores, so F2 can't store more than #5 can act on, and its share of a backup stays small.
9. **The backup-wide size guard is split out to NET-344** (r3). The overflow exists before F2 (uncapped acknowledgements), and a real fix needs a download-format measure, a section-naming message and an acknowledgement prune. Bolting a half version onto F2 produced three new findings in round 3. F2's worst case adds under 768 KiB as downloaded.
   - **Merge order** (r4, r5): F2 can still push a backup that was just under the limit over it (Codex measured 32 full photos plus 46,000 acknowledgements plus 480 notes). Gating only tags or one deploy script is not enough: every other deploy script pulls `main`, nettap.dev installs from `main`, and acknowledgements keep growing after a one-off headroom check. So **NET-344 merges to `main` first**. F2 is built and reviewed on its branch, and its PR stays a draft that does not merge, and no F2 build touches live data, until NET-344 has merged and its before-and-after restore test passes on `main`. F2 is then rebased onto that `main` and its full suite re-run before merge.
   - With NET-344 in place, a backup that F2 pushes over the limit is refused at export with NET-344's message, not discovered at restore. The G11 headroom step (§5) stays as a cheap extra check on the one live device.
7. **No web route, page or field;** #5 and #9 bring those.

## 4. Risks and open questions

- **Row shape:** three new keys in every registry, device and traffic row. Additive, but tests that compare whole rows or `owner_fields` exactly need the keys. The web types gain them as optional when #5 and #9 use them.
- **Rollback:** an older daemon never reads `device_details.json`, ignores the `device_details` backup section with "Unknown section … will be skipped", and keeps serving names and pictures. A test loads `DeviceCustomStore` beside a `device_details.json` to prove the files are independent.
- **Restoring a backup on a box where the details file is damaged:** the preflight refuses the whole import (§2.4). `restore()` still raises `StoreUnavailable` if the file is damaged between the preflight and the restore; that error goes into `errors` like the device custom block.
- **Open:** should `watch_after_min` exist for a device with no `ips`? It doesn't matter here; #5 decides what watching means.

## 5. Verification

- **`daemon/tests/test_device_details.py` (new):**
  - every limit and its boundary (32/33, 64/65, 1,000/1,001 characters, each watch value, `0`, `True`, `"30"`);
  - Cc and Cf refused before trimming, including a bidi override, `\x00`, and `"\n"` alone (refused, not a clear), in notes too;
  - NFC;
  - the 50-watch budget: a 51st refused, an existing watch changed at 50, a group-only device added at 50;
  - the 512 KiB budget at its boundary, on update and on restore;
  - `strict_mac`: `AA:BB:CC:DD:EE:FF:00`, `AA:BB:CC:DD:EE:FF:`, `AA:BB:CC:DD:EE:FF:ZZ` and mixed separators refused, and each DELETE leaves `AA:BB:CC:DD:EE:FF`'s details alone; non-canonical or colliding backup keys refused;
  - U+2028, U+2029 and a lone surrogate refused; a four-byte emoji allowed and counted as 4 bytes;
  - a boundary-size commit (exactly `DETAILS_MAX_BYTES`) reopens healthy and exports; one byte over is refused;
  - first PUT and first restore against a data directory that doesn't exist yet both succeed and reopen;
  - the file is mode 0600 after an update and after a restore;
  - load: a directory or unreadable path, deeply nested JSON (`RecursionError`), and an over-long file each leave the store damaged, never empty; names still serve on a cold start beside a damaged details file;
  - empty and `null` clear; the last field cleared removes the entry;
  - unknown keys and an empty body refused;
  - a bad field changes nothing;
  - a no-op writes nothing (mtime unchanged);
  - `DEVICES_MAX`;
  - a damaged file: writes and export raise, `row_fields` gives `None`s, nothing else breaks;
  - a write failure (`write_file_atomic` raising OSError) leaves memory and file as they were;
  - concurrent updates from threads keep both fields.
- **Rollback:** `DeviceCustomStore` loads and serves names with a `device_details.json` beside it, and its sweep doesn't touch it.
- **Rows:**
  - `with_names` and `present` carry the three keys, with and without a details store, and never notes;
  - a details-only MAC (no name or picture) shows its details;
  - the eight-octet DHCP fixture: the IP read shows the details filed under the six-octet registry MAC, and its `registry_mac` works as a PUT target;
  - `GET /api/devices/registry/{mac}` and `GET /api/devices/{ip}` carry all four from one snapshot; an IP with no MAC gives `None`s;
  - existing exact-shape tests are updated.
- **API** (aiohttp test client, mocked registry):
  - PUT for a known device;
  - 404 for an unknown one;
  - DELETE for an unknown device;
  - 400 cases with their messages;
  - 503 on a damaged file;
  - 500 on a write failure;
  - the reply carries the committed snapshot, notes included.
- **Backup:**
  - export → restore round trip;
  - a bad section refuses the whole import with nothing applied, driven through the import handler with a valid `bandwidth_cap` beside it, as the quiet hours test does;
  - an old backup without the section leaves details alone;
  - a present section replaces the set;
  - a damaged destination refuses the import, with a valid `bandwidth_cap` beside it left untouched;
  - export with a damaged file is a 503 with the fixed message, through the production error middleware;
  - `POST /api/backup/validate` runs the check off the loop (patched `run_blocking` sees the call);
  - a full details store, written into a backup and serialised as the browser saves it (`json.dumps(indent=2, ensure_ascii=False)`, matching `JSON.stringify(x, null, 2)`), adds under 768 KiB.
- **Web:** a BackupTab label test; `exportConfig` shows the daemon's `error`.
- **All suites:** `cd daemon && python -m pytest`, `uvx ruff@0.17.3 check daemon/ && uvx ruff@0.17.3 format --check daemon/`, `cd web && npx vitest run src/routes/settings src/lib/api/backup.test.ts && npx svelte-check` (the backup client's own tests included, r2 #5).
- **G11** (`scripts/remote/deploy-device-details.sh`), with **no write to live data** (r1 #3: a check-then-DELETE on the live store could erase an edit made between them):
  - **headroom first, before anything is rebuilt** (r4): export the live backup, re-serialise it compactly as Settings uploads it (`backup.ts:93`, inside the daemon container), and stop with no change unless that size plus 768 KiB is at most `MAX_REQUEST_BYTES`. The script prints the size and the headroom;
  - rebuild and recreate the daemon **and the web app** (r2 #5: `exportConfig` changes, and the web client is its own image); stop if either recreation fails; each running image ID must equal its built one;
  - live, read-only: the registry list rows carry `group`, `owner` and `watch_after_min`; the device page read carries `notes`; a backup export has a `device_details` section; the log has no device details error;
  - isolated: `verify_device_details.py` runs in a throwaway copy of that image (`--network none`, no mounts, a temp data dir) and exercises the store and backup functions end to end: update, the snapshot, the budgets, `strict_mac`, mode 0600, export → restore, and a damaged file. It prints `DEVICE-DETAILS-OK` only after the last check;
  - memory, logs and status.

## 6. Rollback and migration safety

- **Rollback is safe by construction:** the old daemon never reads `device_details.json`, so names and pictures are unaffected.
- **No migration:** the file starts absent, which is an empty store.
- **Undo:** revert the PR. The file stays on the volume, unread; delete it by hand if wanted.

## 7. Observability

- **Errors:** one error log line when the file is unreadable, naming the path and reason. Writes are refused with a plain-English reason; exports and imports with fixed messages (§2.4).
- **Recovery** (stated in the log line): move `device_details.json` aside, restart the daemon, then restore a known-good backup or set the details again.
- **No new metric.** The deploy script's round trip is the check on the box.

## 8. Out of scope

- Any UI: #5 adds the watch setting, and #9 adds group, owner and notes, with their pages and filters.
- Acting on `watch_after_min`: #5.
- Searching by group or owner: #9.
- Moving names and pictures into the new file.

## 9. Round 1 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | 2,000 × 1,000 four-byte notes plus photos overflow the 16 MiB import | 1 MiB details budget on update and restore; a 16 MiB arithmetic test (§2.1, §5) |
| 2 | `write_file_atomic` defaults to 0644 | `mode=0o600`, asserted after update and restore |
| 3 | The live check-then-DELETE could erase an owner edit | Live check read-only; the round trip runs isolated in a throwaway container |
| 4 | A damaged destination let other sections apply first | The preflight refuses the import when the store is damaged; recovery steps documented |
| 5 | 2,000 watches, #5 budgets 50 | `WATCH_MAX = 50` on update, preflight and restore |
| 6 | `normalize_mac` truncates past six octets | `strict_mac` for the routes; canonical backup keys |
| 7 | `owner_fields` returns early for a MAC with no name or picture | Details merged before the early returns; the store-less fallbacks stated as test-only |
| 8 | The IP page lacked notes; separate reads could mix revisions; `_apply` hard-codes the custom store | One `get()` snapshot for both device page reads; `update` returns its snapshot; `_apply` takes the store |
| 9 | `os.path.exists` and an uncaught `RecursionError` in the loader | Open directly, only `FileNotFoundError` is empty; bounded read; `RecursionError` is damage |
| 10 | Line breaks in notes break the roadmap's no-control rule | One line; controls refused before trimming |
| 11 | The export reason never reaches the owner | Fixed `public_json` 503; `exportConfig` shows the daemon's `error` |
| 12 | `/api/backup/validate` validates on the loop | `run_blocking`; `problems()` stops at 5 reasons |

Earlier wording: decision 3 is unchanged. Decision 4 was "Notes may hold line breaks; nothing else may". Decision 6 said the owner "sees the reason and can delete the file".

## 10. Round 2 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | An indented file at the budget is over the loader's ceiling | One compact UTF-8 format; the budget is the file's exact bytes and the loader's limit; a boundary reopen test |
| 2 | Uncapped alert acknowledgements can still push a backup past 16 MiB | `handle_export` refuses a backup over the restore limit with a fixed 413; HTTP round trip at the edge and past it |
| 3 | `…:FF:` and `…:FF:ZZ` pass a hex-digit comparison | `strict_mac` full-matches the raw string's grammar; the details routes parse with it in `_run` |
| 4 | The IP page's MAC can be an eight-octet chaddr the write API refuses | Details keyed by `_mac_key`; `registry_mac` returned as the edit target; the eight-octet fixture tested |
| 5 | The web fix isn't deployed by a daemon-only rebuild | Rebuild both images, check both IDs; run `backup.test.ts` |
| 6 | First write fails when the data directory doesn't exist | `_commit` creates it; first PUT and first restore tested |
| 7 | U+2028/U+2029 and lone surrogates pass Cc/Cf | Cs, Zl and Zp refused too; a four-byte emoji stays allowed |

## 11. Round 3 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | The export check measured the daemon reply, not the pretty-printed download | The export size check is removed from F2. The backup-wide guard is NET-344, which must measure the downloaded form |
| 2 | The 64 KiB reserve refuses backups that fit | Gone with the check (NET-344: compare with the real cutoff) |
| 3 | The 413 gave no usable recovery when acknowledgements are the bulk | Gone with the check (NET-344: name the largest section, add an acknowledgement prune) |
| 4 | The live G11 check would fail on the intended 413 | No 413 in F2, so the live export check stands as written |

F2's own share is now smaller: 512 KiB for the file, and under 768 KiB as downloaded, with a test.

## 12. Round 4 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | F2 alone can push a near-limit backup over 16 MiB, and the owner finds out at restore | NET-344 is a release gate for F2 (no tag ships F2 before it). The G11 deploy measures the live backup first and refuses to roll out without room for F2's 768 KiB |

## 13. Round 5 changes (Codex)

| # | Finding | Change |
|---|---------|--------|
| 1 | A tag gate and one script's headroom check still let F2 reach live data (other deploy scripts, nettap.dev installs from `main`), and acknowledgements grow after the check | NET-344 merges to `main` before F2. The F2 PR stays a draft, and no F2 build touches live data, until NET-344's before-and-after restore test passes on `main`; then rebase and re-run the suite |
