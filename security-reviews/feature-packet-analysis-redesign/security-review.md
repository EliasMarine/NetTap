# Security Review

## Review Metadata

* Review Folder: `feature-packet-analysis-redesign`
* Report Path: `security-reviews/feature-packet-analysis-redesign/security-review.md`
* Base Ref: `origin/main`
* Base Ref Commit Date: `2026-11-06T19:15:08-08:00`
* Inspected Branch or PR: `feature/packet-analysis-redesign` (PR #196)
* Current Commit: `0fdc0c2`
* Review Scope: the review-fix diffs on top of `0fdc0c2`, in three rounds: `d4f604d` (staged at the time), then the staged follow-up (the editcap message check, `timeout --foreground`, the pre-2000 refusal, the capture-file path rework, the web constant move, and the deploy script build check)
* Diff Sources: `git diff --cached`
* Dirty Working Tree Included: `yes` (the staged changes are the whole scope)
* Earlier review: the committed branch (`483c089...0fdc0c2`) was reviewed on 2026-11-07 with no findings. This report replaces it and covers only the fix diff.

## Files Reviewed

- `daemon/services/container_exec.py`: a per-run random tag on the control markers (`$NT`); the supervisor removes `/tmp/nt-<pgid>-*`; the cleanup drains both pipes and bounds its waits.
- `daemon/services/packet_search.py`: the `cut()` shell function, which sends `cut:` files through editcap and FIFOs in `/tmp`; also `job_path`, `_admitted_paths`, `cut_ok(cuts)`, `_tshark_version` and `FIELD_PREFIX \Z`.
- `daemon/services/capture_index.py`: `_FLOOR_JOB` (`editcap -A 946684800 | capinfos -`), `timeout 25` on capinfos, index format v2, and the save and lock fixes.
- `daemon/services/packet_parse.py` and `daemon/services/packet_manifest.py`: ASCII-only, `\Z`-anchored, at most 11-digit epochs; `epoch_ns` raises ParseError; `_int` checks `isascii`.
- `web/src/routes/api/packets/download/+server.ts`: its own 60 s timeout for the daemon's headers.
- `web/src/lib/api/packets.ts`: a non-JSON 200 becomes a PacketApiError.
- `web/src/routes/api/[...path]/+server.ts`: timeout numbers.
- **Follow-up round:**
  - `daemon/api/packets.py` `handle_capture_file`: the path is resolved and checked (containment, plus equality with the plain join, which refuses a symlink anywhere) before any filesystem access, for CodeQL `py/path-injection`;
  - `capture_index.editcap_read_to_end`, used by `cut_ok` and by the pre-2000 re-read;
  - `timeout --foreground`;
  - windows before 2000 get a 400;
  - `web/src/routes/api/packets/download/limits.ts`.
- `scripts/remote/deploy-packet-analysis.sh` and `verify-packet-analysis.py`: operator-run, with no network input.
- Tests: out of scope under hard exclusion 7.

## Coverage Summary

* Changed symbols analyzed: 14
* Inbound callers inspected: 11. Covered: every `run_in_tshark` caller, every `epoch_ns` caller, `cut_ok`, `_save_soon`, `admit`/`_admitted_paths`, and the web download route.
* Outbound callees inspected: 17
* Sinks considered:
  - shell inside the TShark container: `${f#cut:}`, `mkfifo`/`rm` and the glob over `/tmp/nt-$$-…`, `: <> FIFO`, and editcap/mergecap/capinfos arguments;
  - `kill -KILL -<pgid>`, where the pgid now comes only from a tagged line;
  - the stage statuses that decide whether a result is "complete";
  - path containment for manifest file ids;
  - error text returned to clients;
  - auth on `/api/packets/*` (unchanged; re-checked for `capture-file`);
  - a forged `editcap:` line can only add a failure, because every such line must be the exact cut-short text.
* Regression patterns checked: removed sanitizers, weakened types, auth-default flips, visibility changes. None found; the validators got stricter.
* Trusted rule memory: none
* Limitations / unresolved edges:
  - The supervisor's process-group and FIFO behaviour was checked on the G11 (TShark 4.0.17, dash), not statically.
  - Whether a browser disconnect cancels the streamed download in adapter-node is a resource question, not a security one.
  - A symlink swapped in between the realpath check and `FileResponse` would need write access to the capture volume. Only the capture writer has that, so this is excluded as a race with no practical exploit.
* Not covered (by design): DoS/ReDoS, rate limiting, dependency CVEs, generic hardening.
* External analysis consumed: none

## Findings

No high-confidence security vulnerabilities found in the reviewed changes.
