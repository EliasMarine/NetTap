# 2026-11-07 — Packet analysis, PR 1: the daemon reads windows of the saved captures exactly

**Status:** PR #196. The branch passed every check on the G11 (2026-11-07 05:17 UTC); the review fixes below are deployed with the merge.
- **Linear:** NET-188.
- **Plan:** `.codex-review/2026-11-07-0400-packet-analysis/PLAN.md`. Codex reviewed it for 5 rounds and raised 38 findings, all accepted. The log has the build's measured departures under "Implementation notes".
- **Mockup:** https://claude.ai/artifact/EhF7D2N8ngPrY49DgKTVWP

**Problem**

The TShark page (`/tools/tshark`) asked for a PCAP path and Wireshark syntax, then showed raw JSON. Its daemon side read whole files and gave up silently:
- Max packets went up to 10,000, but the daemon capped at 1,000.
- Validate always failed.
- Nothing said whether a result was complete.

The new page (PR 2) starts from a question: who, what and when. It needs a daemon that answers it from NetTap's saved captures, exactly, and says what it covered.

**What changed**

- **`daemon/services/container_exec.py`:** one supervised runner for every job in `nettap-tshark`.
  - Each job runs under `setsid` in its own process group. A watchdog prints `#nt-deadline`, then sends TERM, then KILL 2 s later. The group is killed again when the job ends.
  - Each stage reports `#nt-status <stage> <code>`.
  - An output cap, a sink failure, a cancel or an overrun kills the group inside the container (`kill -KILL -<pgid>`) before the error propagates.
  - Every input is a positional argument to fixed scripts.
- **`daemon/services/capture_index.py`:** the capture index.
  - It records each file's real first and last packet time from capinfos, plus its packet count and link type.
  - It is persisted to `/opt/nettap/data/packet-index.json` and keyed by size and mtime.
  - A background pass indexes new and changed files, newest first, 8 at a time.
  - A search indexes any file without a current entry itself (at most 8). With more pending it answers 503 "still indexing".
  - A file capinfos can't read is `failed`. It is named by every search, which is then marked incomplete.
  - A cut-short file (partly written last packet) is indexed for its complete packets.
- **`daemon/services/packet_search.py`:** the jobs, and how each ending is judged.
  - **Search:** `mergecap | editcap -A from -B to | tshark -Y filter -T fields | head -n limit+1`. It ends in one of three ways:
    - `eof`: every stage exited 0;
    - `limit`: limit+1 rows came back;
    - `deadline`: the marker was seen.
    - A dead stage gives 502, an out-of-memory kill 507. The result is never partial data presented as whole.
  - **Detail:** PDML plus a frames-only hex dump of one packet. Both are checked against the packet's identity (time, captured length, MD5).
  - **Download:** pcap. Each record is verified before it is sent, and a mismatch aborts the transfer.
  - **Field suggestions:** an awk scan of `tshark -G fields`.
  - **Filter check:** a compile against an empty pcap on stdin.
- **`daemon/services/packet_parse.py`:** the parsing.
  - It parses field rows. A wrong column count is an error, never a skipped row.
  - It parses PDML with caps on size (2 MB), nodes (4,000) and depth (32).
  - Byte marking applies only on the contiguous header chain from eth, and only where the field's value equals the frame's bytes. A packet showing any reassembly is never marked.
  - It parses the hex dump, and verifies the pcap stream record by record.
- **`daemon/services/packet_manifest.py`:** the manifest the page sends back.
  - It is shape-checked (400).
  - Admission checks the manifest's own files on disk now: finished files unchanged, recent files only grown, the budget on actual sizes. A failure is a 409.
- **`daemon/api/packets.py`:** the routes.
  - `GET /api/packets/captures` and `GET /api/packets/capture-file?id=`;
  - `POST /api/packets/search`, `/packet`, `/download` and `/check-filter`;
  - `GET /api/packets/fields?prefix=`.
- **`daemon/api/server.py`, `services/pcap_search.py`, `services/tshark_service.py`:** TShark, PCAP Search and packet analysis share TShark's 2 reader slots. PCAP Search used to have 2 of its own.
- **Web:** `/api/packets/*` timeouts in the catch-all proxy, a streaming download route, and the client `web/src/lib/api/packets.ts`.
- **`scripts/remote/deploy-packet-analysis.sh` + `verify-packet-analysis.py`:** the deploy, then an independent check on real captures:
  - the index against a fresh capinfos;
  - a boundary-spanning search against each file read whole by TShark;
  - the download read back, and one packet's detail;
  - the filter check and a hostile filter;
  - the provisional flag;
  - no leftover jobs.

**Measured on the G11 (TShark 4.0.17) while building**

- **Rotation is fast.** Capture files rotate every 5 to 25 s under load: 272 files started in one 30-minute stretch.
- **Cut-short files still read.** On a cut-short file, capinfos exits 1 and mergecap exits 2, with "cut short in the middle of a packet". All complete packets are still read.
- **Set syntax.** `frame.number in {…}` needs commas; with spaces TShark refuses it.
- **Escaping.** `-E escape` doesn't exist in 4.0.17, but tabs inside values are escaped anyway.
- **Expert info.** `_ws.expert.message` / `.severity` / `.group` give TShark's own "noticed" items per packet.
- **The real job scripts.** Every one ran through the real supervisor against a synthetic capture with documentation addresses. Those outputs are the test fixtures.
  - A filter of `x"; rm -rf / #` arrived as one argument.
  - A job that traps TERM was killed at the deadline.
  - `/proc` was clean afterwards.

**Found by the first G11 run and the PR reviews (fixed before merge)**

- **A crash leaves a zero-filled tail, and capinfos called it 1970.** `mnetsniff-enp4s0_1794019107.pcap` had 94,208 real packets (02:38:27 to 02:42:22 UTC on 2026-11-07), then 74 records of time 0 and length 0. ext4 had saved the file's size but not its last blocks. capinfos reported the first packet as 1970-01-01, so:
  - the summary's oldest packet read 1970;
  - the file counted as overlapping every window before 02:42 that day;
  - its packet count included the junk records.
  
  Searches never returned the junk as rows, because `editcap -A` drops it. The fix: when capinfos reports anything before 2000, the index reads that file again through `editcap -A 946684800 | capinfos -` and logs how many records it left out. The index format is now version 2, so the G11 re-indexes every file once after deploy. The verifier now checks each cut-short file against TShark reading it whole, and checks that the oldest packet is after 2000.
- **A crashed file hid every later file's packets (Python review, critical).** TShark 4.0.17's mergecap stops merging all files at the first partly written packet. It exits 2 and prints only the cut-short line, which the daemon accepted as clean. On the G11, the crashed file plus the next one (which starts at 02:53, after the reboot) gave 94,282 packets: the crashed file's alone. All 77,870 of the next file's were missing. A search across the outage returned 322 SYN rows marked complete; the truth is 339.
  - **Fix:** every file that may end in a partly written packet goes to mergecap through `editcap` and a FIFO. That is a file the index flagged as cut short, a recent file that may still be written, or one whose index entry is for another version of the file. editcap stops at the cut and exits 0, and each one reports its own stage. mergecap's exit 2 is a real failure again.
  - **Measured on the G11:** 339 rows, equal to each file read whole (322 + 17). Every stage reported 0, and no FIFO was left.
  - **Verifier:** it now also searches across every cut-short file's end into the next file, against the files read whole.
- **A stuck cleanup could hold a reader slot for ever (Python review, high).** After a cap, a failed sink or a cancel, the cleanup stopped reading the pipes. A job still writing filled them, and on Python 3.12 `Process.wait()` returns only once the pipes close, so the cleanup never ended. Two such events took both shared slots, and TShark, PCAP Search and packet analysis all answered 503 until the daemon restarted. The cleanup now reads both pipes to the end and limits its waits. The test fails without the reads.
- **One slow file stopped every search (Python review, medium).** A file capinfos couldn't read within the batch's 30 s stayed pending, so every search answered "still indexing", and the background pass spun on it. Each file now has its own 25 s limit (GNU `timeout`). A file over it is recorded as failed and named by every search.
- **Smaller ones (Python review, low).**
  - A search waiting behind the background pass no longer reads files that pass just indexed.
  - The index prunes deleted files from a scan taken when it saves, not from a caller's older one.
  - A failed save stays marked unsaved, so the shutdown flush retries it.
  - The TShark version lookup can't hold up a finished answer (2 s, then "unknown").
  - A bad time in TShark's own output is a 502 with a reason, not a 500.
- **Second round (the Python reviewer re-checked the fix against TShark 4.0.17 built from `docker/Dockerfile.tshark`).**
  - **The fix hid damaged files (medium).** editcap 4.0.17 exits 0 on every read error, not only a cut-short tail. A damaged record in a `cut:` file silently ended that file's packets. Now editcap's messages must all be the exact cut-short text, or the read is a failure. The same check covers the pre-2000 re-read.
  - **capinfos escaped the kills (low).** Plain `timeout` moves its child into a new process group, out of reach of the group kill. It is now `timeout --foreground`.
  - **Windows before 2000 (low).** These now get a 400: the index leaves those records out, so the answer could only be "complete, nothing found".
  - **New test.** `daemon/tests/test_cut_shell.py` runs the real `cut()` shell wherever Wireshark's tools are installed.
- **CI.** It was green on main before this PR. The "red baseline" in `.claude/rules/git-workflow.md` is out of date. PR #196 broke it four ways:
  - **CodeQL, 3 high `py/path-injection` alerts on the capture-file route.** The route was safe in practice, but it touched the raw joined path before checking it. It now resolves the path first, checks containment and that the result equals the plain join (no symlink anywhere), and only then uses the checked path.
  - **The web build (Trivy and Integration Tests).** `export const DOWNLOAD_HEADERS_TIMEOUT_MS` in `+server.ts`: SvelteKit refuses any non-handler export from an endpoint, and only `vite build` checks that. Moved to `limits.ts`.
  - **Lint Python.** The two fixture generator scripts.
- **The deploy script hid a failed build.** On the second G11 deploy the web build failed. The script then recreated the web container from the old image and still reported every check passed, because the checks talk to the daemon. A failed build now stops the deploy with a ✗.
- **A filter could forge the job's control lines (security review, low).** When TShark refuses a filter, it echoes the filter with `\x0a` turned into a real line break. On 4.0.17 a filter printed bare `#nt-status tshark 0` and `#nt-pgid 1` lines. Line order made this harmless, but now every run gets a random tag. The job receives the tag as `$NT`, and only `#nt-<tag> …` lines count as control lines.
- **Input checks.** The checks for window times, MD5 and the field prefix used `\d` and `$`, which accept non-ASCII digits and a trailing newline. A 12-digit time made the download route's file name fail with a 500. A manifest size of `"²"` passed `isdigit()` and then failed in `int()`, another 500. All of these are 400s now: ASCII digits, `\Z`, at most 11 digits.
- **Web.**
  - The download route has its own 60 s limit on the daemon's headers. It no longer depends on the browser's request signal.
  - A 200 that isn't JSON (a sign-in page) becomes a readable error.
  - Field suggestions and the filter check have a 25 s proxy timeout.

**Tests**

- 132 new daemon tests in `test_container_exec.py`, `test_capture_index.py`, `test_packet_parse.py`, `test_packet_manifest.py`, `test_packet_search.py` and `test_packets_api.py`. Two of them need setsid and run on Linux only.
- Full daemon suite: 3,417 passed, 0 failed (after the review fixes). Web: 3,446 passed.

**Lessons**

- **Run `npm run build` before pushing web changes.** svelte-check and vitest pass on an endpoint that the production build refuses.
- **A deploy script must fail on a failed build.** Otherwise it ships the old image and its checks still pass.
- **editcap's exit code says nothing about read errors.** Only its message does.
- **A tool's exit code can mean "I stopped early" in one version and "I skipped it" in another.** mergecap 4.6.9 merges past a cut-short file; 4.0.17 stops. Measure multi-file behaviour on the device's version, with a real crashed file, not one file at a time.
- **Check the index's own summary against reality, not only a random sample.** The random check of 3 files passed while the summary said 1970; one crashed file in 1,480 is what a power cut leaves.

- **Measure the device before trusting the plan's numbers.** The plan assumed a recent file was rare. On the G11, 24 files can be "recent" at once.
- **Record fixtures from the real binary.** The fragment fixture from planning held a real router MAC address, so it was regenerated from crafted packets before commit.

**Next steps**

Gates, then the PR, merge, and the G11 deploy with `bash scripts/remote/deploy-packet-analysis.sh`. Then PR 2, the page.
