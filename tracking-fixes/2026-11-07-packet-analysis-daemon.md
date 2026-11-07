# 2026-11-07 — Packet analysis, PR 1: the daemon reads windows of the saved captures exactly

**Status:** built and tested on `feature/packet-analysis-redesign`. Gates, PR, merge and the G11 check are pending.
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

**Tests**

- 132 new daemon tests in `test_container_exec.py`, `test_capture_index.py`, `test_packet_parse.py`, `test_packet_manifest.py`, `test_packet_search.py` and `test_packets_api.py`. Two of them need setsid and run on Linux only.
- Full daemon suite: 3,397 passed, 0 failed.

**Lessons**

- **Measure the device before trusting the plan's numbers.** The plan assumed a recent file was rare. On the G11, 24 files can be "recent" at once.
- **Record fixtures from the real binary.** The fragment fixture from planning held a real router MAC address, so it was regenerated from crafted packets before commit.

**Next steps**

Gates, then the PR, merge, and the G11 deploy with `bash scripts/remote/deploy-packet-analysis.sh`. Then PR 2, the page.
