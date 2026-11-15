# Update API checks component names before using them, 2026-11-14

**Linear:** NET-291
**Branch:** `fix/update-component-names-net291`
**Status:** done. PR #293 merged (`032d306f`); verified on the G11 with `deploy-update-names-net291.sh` (every check passed: an existing and a missing rollback path get the same 404, a non-object body, 17 names, an unknown name and `null` each get 400, update history unchanged).

## Problem

The security review of PR #291 (NET-288) found two LOW issues that were already on main:

- `UpdateExecutor.rollback()` joined the requested name onto the backup folder and checked that the
  path exists before it checked the name. `{"component": "../../../etc/x"}` answered "Rollback not
  supported" when the path existed and "No backup available" when it didn't: a file-existence oracle
  for any path in the (root) daemon container. Nothing was written.
- `POST /api/system/updates/apply` took any list of strings. `_apply_batch` makes one result per name
  and the last 50 batches are kept in history. A junk batch ends at once, so the 409 never blocks the
  next, and the 16 MiB body limit was the only bound.

## Root cause

Neither entry point checked its input against the supported names. Both checks existed only as a
fall-through (`else: not supported`, `Unsupported component`) after the name had already been used.

## Fix

- `update_executor.py`: `ROLLBACK_COMPONENTS` (`suricata-rules`, `geoip-db`), `APPLY_COMPONENTS`
  (`malcolm`, `suricata-rules`, `geoip-db`, plus the Malcolm row names `_not_applicable_reason`
  already answers, taken from the same constants) and `MAX_APPLY_COMPONENTS = 16`.
  `rollback()` refuses any other name, with one reply, before the `os.path.join`. The Malcolm answer
  stays first.
- `api/updates.py`: apply returns 400 for a body that is not an object, more than 16 names, a
  non-string name, or a name outside `APPLY_COMPONENTS`, all before `start_update`, so nothing is
  queued or recorded. Rollback returns 400 for a body that is not an object (`null`, `[]`, `5` were a
  logged 500).
- `rollback()` keeps explicit branches (Python review, MEDIUM): `if suricata-rules`, `elif geoip-db`, and an
  `else` that answers "not supported". A bare `else` for geoip-db would restore a third name added to
  `ROLLBACK_COMPONENTS` against the GeoIP path. New test patches the list to three names and checks
  `_rollback_files` is not called (it was, with the GeoIP path, before).
- `_create_backup`: the docker `image_id.txt` branch is retired as OLD CODE (no caller since NET-288).
  The replaced `elif`/`else` lines in `rollback()` are OLD CODE too.
- Chosen: an allow-list plus the cap, not the cap alone. A cap alone still keeps 16 attacker-sized
  strings in each of 50 history entries; only an allow-list bounds each name.
- What the page sends: `malcolm`, `suricata-rules` and `geoip-db` only (the rows with no
  `applies_with`; "Update all" and the per-row Update button both filter on it).
- Web proxies (security review LOW-1, same bug one layer up): `routes/api/system/updates/{apply,rollback}/+server.ts`
  threw a TypeError on the JSON body `null` (`body.components`, `body.component`) and answered 500.
  Each guard now starts with `!body || typeof body !== 'object' ||`; the replaced line is an OLD CODE
  comment. (First thought not worth doing, because the daemon already answers 400; done anyway, since
  it is the same class of bug.)
- Not done: the rollback refusal still echoes `component` in its reply (security review LOW-2, cosmetic).

## Tests

- New, each seen failing first: rollback gives one answer for a name whose path exists and one whose
  path doesn't (traversal, absolute, plain unknown); `ROLLBACK_COMPONENTS`; `_create_backup("zeek")`
  makes no docker call and no `image_id.txt`; apply refuses `["zeek"] * 17`, unknown and long names,
  a valid-plus-unknown mix, and bodies `null`, `[]`, `5`, `"malcolm"`, leaving history, live results and
  current update untouched; rollback refuses the same non-object bodies.
- Web (Vitest, `apply/server.test.ts` and `rollback/server.test.ts` beside each proxy): bodies `null`,
  `[]`, `5`, a string, `{}` and (rollback) a non-string or empty `component` get the proxy's own 400 and
  never reach the daemon; a valid body is forwarded. Only the `null` cases failed before the fix
  (`TypeError: Cannot read properties of null`); the rest guard the existing checks.
- Guards that passed before: `["zeek"] * 16` and the page's names and Malcolm rows still reach
  `start_update`; a non-string `component` is a 400.
- Checker-driven: the real `check_updates()` with every Malcolm container, a stale rules file, a stale
  GeoIP file, a newer NetTap release and an OS row. The rows with no `applies_with` are exactly
  `malcolm`, `suricata-rules`, `geoip-db` and all are in `APPLY_COMPONENTS` (checked by mutation: remove
  `geoip-db` and it fails).
- Full daemon pytest: 5043 passed, 5 skipped, 0 failed. `ruff format --check daemon/` and `ruff check`
  clean.
- Full Vitest 397 files, 5284 tests passed; `svelte-check` 0 errors.
- Plan: `/codex-review` approved in 2 rounds.

## Next

- Client names still reach exception log lines in `api/updates.py` (`%s` of the name); unchanged.
- A new updatable component needs one line in `APPLY_COMPONENTS`; the checker-driven test fails until
  the allow-list has it (it does not check that the executor has a branch for it).
- After deploy: a `POST /api/system/updates/apply` with `{"components": ["../x"]}` answers 400, and
  `POST .../rollback` with `{"component": "../../../etc/x"}` answers 404 "Rollback not supported for
  this component." whether or not the path exists.

## Lessons

Check input against the supported list before it is used for anything (a path, a history entry), not
in the fall-through branch after. A cap on a list bounds the count, not the size of each item.
