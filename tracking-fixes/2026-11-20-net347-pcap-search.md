# NET-347 (PR A): PCAP Search refuses a bad filter and says what it covered

**Date:** 2026-11-20 · **Branch:** `fix/pcap-search-reliability` · **Status:** in review

## What changed
- `daemon/services/pcap_search.py`:
  - `check_filter` compiles a display filter in TShark while holding one reader slot.
  - A new search runs that check first, under `_start_lock`, with a 45 s deadline.
  - Replaced jobs are no longer cancelled. They stop before their next file.
  - `_count_lock` keeps background search to one TShark read at a time.
  - `_count_file` streams both pipes, holds the slot until the docker exec ends, and classifies each read with `_classify_read`. The outcomes are `full`, `truncated`, `timed_out` and `failed`.
- `daemon/api/pcap.py`:
  - A refused filter answers 400.
  - Busy or late answers 503 (`public_json`).
  - A check that couldn't run answers 500 with fixed text.
  - New `POST /api/pcap/check-filter`.
- `web/src/lib/api/pcap.ts`: `PcapRequestError` carries the HTTP status. New `checkPcapFilter`.
- `web/src/routes/pcap/+page.svelte`:
  - TShark's refusal shows inline under the field.
  - Results and row previews follow the submitted search.
  - A late preview for an earlier pick is dropped.
  - A coverage line ("Fully searched N of M files…") and "at least N" rows.
  - "Try again" resends the failed search unchanged.
  - Download filtered waits for the filter check.
- `web/src/routes/api/[...path]/+server.ts`: 55 s for `/api/pcap/search` and 25 s for `/api/pcap/check-filter`.
- `scripts/remote/deploy-live-audit-fixes.sh`, `verify_pcap_search.py`, `rollback-live-audit.sh`.

## Root cause
- No filter compile before a job, so `nettapqa_invalid_filter` scanned 318 files and reported "7 files match".
- `task.cancel()` on a new search freed the reader slot while TShark kept running in the container.
- Any nonzero exit with output counted as a full read.
- The fork failures themselves were A0 (zombies), fixed in PR #345.

## Steps / solution
- Plan reviewed by Codex for 5 rounds (`plans/2026-11-20-live-audit-fixes.md`). It hit the round cap without APPROVED.
- Every round 5 point was taken. The job-id protocol from rounds 2 to 4 was dropped for the existing request contract plus locks.

## Test results
- Daemon:
  - `tests/test_pcap_search.py`, `test_pcap_api.py`, `test_verify_pcap_search.py`, `test_error_replies.py` and `test_health_while_blocked.py` pass.
  - Admission, ordering, one-read-at-a-time, real-pipe stderr flood, stuck read and classification precedence are covered.
  - Full suite: 2 failures, both fixed. They were the curated-exception allowlist and the health test's stub.
- Web:
  - Vitest 5961/5961 (plus 13 page tests and 4 client tests).
  - svelte-check 0 errors.
  - Colour gate clean.
  - Mutation check: removing the stale-preview guard fails its test.
- Device: see the deploy output (added after the run).

## Reviews (PR #346)
- `/deep-review`: no findings.
- `/ponytail-review`:
  - Fixed: the file being written no longer reads as missed, and the kill race.
  - Withdrawn: the wrapper still serves `search()`.
- Security-engineer: no issues. Took I-1: the validator now refuses NUL, CR and LF, as packet search does.
- TypeScript reviewer, fixed:
  - "Try again" only shows beside its own error.
  - An empty preview names its own filter.
  - The failure reason shows when the only failed files had matches.
  - The filter check keys on the trimmed text.
  - Teardown drops late previews and checks.
  - Body-shape guard on error replies.
  - Tests for the proxy timeouts.
- TypeScript reviewer, skipped: aborting stale checks. The daemon doesn't cancel on disconnect, so an abort frees no slot.
- Python reviewer, fixed:
  - The host-cap kill drains both pipes (`communicate()`), so it can't hang on a full buffer.
  - stderr keeps its tail.
  - A start that gets the lock with under 20 s left expires at once.
  - `verify_pcap_search.py` retries 503s, and its reference read is bounded inside the container.
  - A test that a refused start releases the lock.
- CI's `check:e2e` (erasableSyntaxOnly) refused a constructor parameter property. Added `npm run check:e2e` to the local gates.

## Lessons
- Cancelling an asyncio wait on `docker exec` does not stop the process in the container.
- After killing a subprocess whose pipes nobody reads, use `communicate()`, not `wait()`: a full pipe buffer keeps `wait()` from returning.
- A count that reads all of stdout can't report what it saw when the read is stopped. Stream it.

## Next steps
Deploy with `bash /home/nettap/NetTap/scripts/remote/deploy-live-audit-fixes.sh` once PR B (NET-348) and PR C (NET-315) are merged.
