# Capture containers: zeek-live capabilities, Suricata counters, PCAP Search download (NET-220, NET-206, NET-189)

**Date:** 2026-11-12
**Branch:** `fix/capture-hardening-stats-pcap-download`
**Status:** Implemented and tested locally; pending deploy (`scripts/remote/deploy-capture-hardening.sh`)
**Plan:** Codex plan review, 5 rounds, approved in round 5.

## NET-220: zeek-live keeps only NET_RAW, with a memory limit

### Root cause
- Zeek runs as uid 1000. Its only capture privilege is the file capability on `zeek` and `capstats`: `cap_net_admin,cap_net_raw=eip`. Malcolm's `docker_entrypoint.sh` (root) re-applies that `setcap` at every start, so compose's `cap_add` only set the ceiling.
- Nothing in the image uses NET_ADMIN (`PCAP_IFACE_TWEAK` is read only by pcap-capture) or SYS_NICE.
- No memory limit: peak 1.66 GiB on the G11, with 0.8 GiB of it in swap.

### Evidence (G11, read-only)
- In the zeek-live container, a uid-1000 probe holding only NET_RAW ran Zeek's af_packet sequence (`socket(AF_PACKET)`, TPACKET_V3, RX ring, bind, promisc membership, fanout) and received 20 packets. With no capabilities it got `PermissionError`.
- `no-new-privileges` stops capture: capstats exec'd by uid 1000 captured without it and failed with `socket: Operation not permitted` with it. So it is not set.

### Fix
- `docker/Dockerfile.zeek-live`:
  - edits the entrypoint's two setcap lines to `CAP_NET_RAW+eip`;
  - sets `cap_net_raw=eip` on zeek and capstats;
  - fails the build if the lines change or `getcap` differs.
- `docker/docker-compose.yml` zeek-live: `cap_add: [NET_RAW]` (the old list is kept as OLD CODE), `mem_limit: 3g`, and a comment saying why there is no `no-new-privileges`.
- The image and compose roll back together: a file capability outside the bounding set makes exec fail.

## NET-206: Suricata's engine counters

### Root cause
- Malcolm generates `stats: enabled: no`, so `suricatasc -c dump-counters` answered "stats are disabled in the config".
- An included `stats:` block replaces the earlier one (`suricata --dump-config`: "redefined"), so the whole block has to be restated.

### Fix
- `config/suricata/nettap.yaml` restates the block: `enabled: yes`, `interval: 10`, `decoder-events: no`. No eve stats and no stats.log, so nothing is written to disk or indexed. With no logger, Suricata 8 keeps the counters for the unix socket.
- `scripts/remote/verify_live_bandwidth.py capture-safety`:
  - checks that the counters answer before the first arm;
  - waits one sync (11 s) in each arm before reading;
  - reads `capture.kernel_packets` / `kernel_drops` per arm;
  - voids an arm across a Suricata restart (uptime down or a counter going down) and aborts on an arm with no packets;
  - prints totals and a second verdict on the per-pair drop ratios.
- New `scripts/remote/measure-capture-loss.sh` runs it and tees the output to `~/nettap-capture-loss.log`.

## NET-189: PCAP Search "Download filtered"

### Root cause (reproduced on the G11)
- mergecap wrote the merged window to nettap-tshark's 100 MB `/tmp`. Two ~107 MB files filled it: a 500, with the file left behind.
- Files were picked by mtime. A 20 s window straddling a file's start returned 200 with only one file's packets.
- The output was held in daemon memory and written to its 50 MB `/tmp`.
- A naive ISO time raised TypeError.

### Fix
- `FILTER_DOWNLOAD_JOB` (packet_search.py) is packet analysis's window cut plus `tshark -r - -Y "$filter" -w -`. It runs as one uninterrupted dissection with no `-M` (session resets drop stateful matches).
- `download_filtered` streams the job's output to the response, with files from `CaptureIndex.select` (real packet times). It:
  - refuses before any byte when there is any failed index entry, or more than 400,000 packets, 64 files or 3 GB;
  - lets one download run at a time and holds a bounded reader slot;
  - has a 240 s deadline;
  - checks the filter first (TShark's message comes back as a 400).
- The handler sends JSON errors before the first byte and aborts the connection after it, so the browser shows a failed download, never a short file that looks complete.
- `CaptureIndex.select` walks the files on the route pool. It ran on the request loop, and the download had been off-loop.
- The file list and background search select by span (name epoch − 30 s to mtime). Naive times are UTC.
- PCAP Search has a download-only window ("Download from" / "to"). Empty uses the page range; one end or end ≤ start shows the error notice.

## Files
`docker/Dockerfile.zeek-live`, `docker/docker-compose.yml`, `config/suricata/nettap.yaml`, `daemon/services/{pcap_search,packet_search,capture_index}.py`, `daemon/api/{pcap,server}.py`, `web/src/routes/pcap/+page.svelte`, `scripts/remote/{verify_live_bandwidth.py,verify_pcap_download.py,measure-capture-loss.sh,deploy-capture-hardening.sh}`.
Tests: `tests/scripts/test_compose_validation.bats`, `daemon/tests/{test_pcap_search,test_pcap_download_cleanup,test_cut_shell,test_verify_live_bandwidth,test_verify_pcap_download,test_health_while_blocked}.py`, `daemon/tests/fake_pcap_download.py`, `web/src/routes/pcap/pcap-page.test.ts`, `web/src/routes/api/catchall-proxy.test.ts`.

## Test results
- Daemon pytest: 4703 passed, 4 skipped, 2 failed. The 2 failures are the date-dependent `test_cert_monitor` baseline failures. Before the change: 4661 passed, 2 failed.
- ruff check and format: clean.
- bats compose: 53 ok (was 52).
- Vitest: 4554 passed. svelte-check: 0 errors. Colour gate: clean. `npm run test:visual`: 295 passed, 50 skipped (/pcap in every theme and width).
- shellcheck: clean on the new scripts.
- Real-tool test (local Wireshark 4.6.9): the download job over two files, one cut short, gives exactly the in-window tcp packets of both.

## Lessons
- A capture binary's file capability is where its privilege comes from. Drop it in the image and in `cap_add` together.
- `no-new-privileges` blocks file-capability gains, not only setuid.
- An included Suricata block replaces the earlier one.
- Pick files by packet times, not mtimes, and stream rather than merge into a size-limited tmpfs.

## Next steps
- The lead deploys with `deploy-capture-hardening.sh`, does the manual browser check it prints, then runs `measure-capture-loss.sh` with a sustained download. Record the numbers in BRIDGE-ARCHITECTURE.md §17 and in `2026-11-07-device-live-bandwidth.md`.
- Admission counts whole files' packets: a safe upper bound, but it can refuse a short window at a file boundary at busy times. Counting the window's packets exactly (one cut pass first) is a possible follow-up.
