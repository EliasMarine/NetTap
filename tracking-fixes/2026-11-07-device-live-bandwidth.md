# Live bandwidth per device on its own page (NET-205)

**Date:** 2026-11-07
**Branch:** `feature/device-live-bandwidth`
**Linear:** NET-205
**Status:** Opt-in (off by default) since 2026-11-08. G11 gates run 2026-11-09: accuracy, kernel, lifecycle and off PASS; the CPU cost is measured and stated; capture safety FAILS with eight watches (stated in Settings, accepted because the feature is opt-in).

## Opt-in (2026-11-08)

The CPU gate failed (27.8% of a core for 8 watches at 1 Gbit/s IMIX, bar 5%), so the owner asked for the feature as a setting. Plan: `.codex-review/2026-11-08-live-bandwidth-opt-in/` (Codex APPROVED, round 5).

- **Setting:** `/opt/nettap/data/live_bandwidth.json` (`LIVE_BANDWIDTH_FILE`), written atomically by `services/live_bandwidth_setting.py`. Missing or invalid means off.
- **API:** `GET`/`PUT /api/settings/live-bandwidth`. A PUT saves first, then applies; a failed save is a 500 and nothing changes.
- **Off:** the meter answers `off` without touching tc. Turning off flips a flag at once and a background task removes the filters, retrying a dirty interface every 10 s (30 times), then every 60 s. New watches get 503 while clean-up is pending.
- **Races:** an admission re-checks the switch after the lock, after preparing and after installing, and rolls back what it added.
- **Web:** `web/src/routes/settings/LiveBandwidthCard.svelte` in Settings › Capture, with the measured cost; the device card links to it when off.
- **Clean-up without the daemon:** `scripts/remote/live-bandwidth-cleanup.sh` (`--check` lists only).

## What the owner asked for

"A live bandwidth per device on its own device page. This should be an accurate figure."

Agreed in the approved prompt: download and upload every ~2 s on both device pages (`/devices/<ip>` and `/devices/mac/<MAC>`), within ±5%, with a 5-minute chart. Measured from packets on the capture interface, only while a page is open, shared per device, capped, with no disk writes and no effect on capture. ±5% is proven against a known transfer.

## Why nothing that existed could do it

The traffic charts come from Zeek connection logs in OpenSearch. A connection's bytes are logged when it ends (or every few minutes for long ones), so the charts lag by minutes and can't give a rate for "now".

## What changed

### Daemon

- **`services/live_bandwidth_tc.py` (new):** the tc building blocks, shared with the G11 gate script.
  - Builds one watch's filter lines: 2 for a MAC (`dst_mac` down, `src_mac` up), 4 for an IPv4 address (`dst_ip`/`src_ip`, plain and 802.1Q).
  - Every line uses `skip_hw`, `action continue` and a cookie (`NETTAPBM` + slot + generation).
  - Six shared prefs (49152–49157), with one handle per watch.
  - Parses `tc -s -j filter show`, finds foreign filters, reads the qdiscs and `ethtool -k` offloads.
  - One deadline-bound runner kills and reaps its child process on a timeout, error or cancellation (the NET-203 pattern).
- **`services/live_bandwidth.py` (new):** `LiveBandwidthMeter`.
  - **Mirror mode only.** Bridge and DHCP gateway give a plain reason.
  - **Each poll is a keepalive.** The first poll starts a watch, viewers share it, and it stops 15 s after the last poll. At most 8 watches.
  - **One lock** covers installs, removals and sampling; a keepalive for a running watch never waits on it.
  - **Admission bounds.** A 6 s overall deadline, a 1.5 s lock wait and at most one waiter; anything else gets 503.
  - **A supervised sampler** ticks every 2 s on the monotonic clock and keeps 150 ticks (5 minutes).
  - **Invalid ticks carry a reason:** a late read, a slow read (over 2% of the interval), a counter reset, a missing counter or one from another generation, a foreign rule, capture settings changing, or a failed read. The headline goes blank when the latest reading is over 5 s old.
  - **Watch removal.** A watch is marked retiring before any await, so a keepalive that races its removal starts a fresh watch instead of reviving a dying one.
  - **Unremovable filters are parked.** A slot whose filters can't be removed is set aside, and the next tick retries.
  - **Startup and shutdown clean-up** delete every NetTap-cookie filter on every interface. It runs after the real capture manager is installed (`main.py`) and on `on_cleanup`.
  - **Host sysfs.** Interfaces are read from `HOST_SYS_NET` (`/host/sys/class/net`), like every other daemon sysfs reader.
- **`api/live_bandwidth.py` (new):** `GET /api/live-bandwidth?mac=` or `?ip=`.
  - Exactly one key.
  - The MAC is normalised to lower case; multicast, broadcast and all-zero MACs are refused.
  - The IP must be IPv4 and on the LAN: in the detected subnets, or else RFC1918.
  - Errors: 400 for a bad key, 503 when busy, 500 when tc fails. Registered in `api/server.py`.

### Web

- **`LiveBandwidthCard.svelte` (new), on both device pages.** It sits after the KPI row on the IP page and after the KPI cards on the MAC page. The IP page counts by its IP and the MAC page by its MAC.
  - **Polling is local to the card.** The next poll starts 2 s after the last one settles, aborts on unmount, pauses while the tab is hidden, and drops a late reply for an old key.
  - **Display:** two big figures from a fresh, valid reading only (a valid 0 shows as "0 bit/s"); otherwise the reason and "last measured N s ago".
  - **States:** loading, measuring, busy with Retry, unsupported with the daemon's reason, and error.
  - **Info line:** what's counted and on which interface, plus a GRO warning when GRO is on.
- **`AreaChart` gains an opt-in `gaps` prop** (with `finiteRuns()` in `geometry.ts`), so a missing tick is a gap, not a line across it. Every existing chart is unchanged.
- **Also new:** `formatBitRate()` (decimal: kbit/s, Mbit/s, Gbit/s, as NET-166), the `getLiveBandwidth()` client and a visual fixture.

## Accuracy: what the figure is

- **The layer is the Ethernet payload:** the IP packet, plus padding for packets under 46 bytes. The 802.1Q tag isn't counted.
- **What the MAC page counts:** everything the device sends, plus unicast addressed to it. Broadcast and multicast it receives aren't counted.
- **Traffic the mirror can't see** (device to device on the same switch) isn't counted.
- **GRO on the capture NIC** would make rates read about 3% low. The API reports it and the card says so.

## Tests

- **Daemon: 76 new tests.** All 4,028 daemon tests pass.
  - `test_live_bandwidth_tc.py`: filter lines, cookie, the real G11 dump fixture, the runner's kill-and-reap.
  - `test_live_bandwidth.py`: against an in-memory tc (`tests/live_bandwidth_fake.py`), with a hand-driven clock:
    - admission, sharing, the cap, the single waiter and the lock-wait cap;
    - the admission deadline, the capture lock, rollback and parked slots;
    - unsupported modes and interfaces, foreign rules;
    - rate maths, every invalid-sample reason, headline freshness and the ring;
    - idle stop, the retiring race, reconcile, shutdown and the sampler supervisor.
  - `test_live_bandwidth_api.py`: validation and the 400/503/500 mapping.
  - `test_live_bandwidth_reference.py`: the accuracy reference's windowing by kernel timestamp, the gate rules, and its socket filter run through a small BPF interpreter.
- **Mutation checks:** 13 guards broken one at a time; the tests caught every real one.
  - The guards: `continue`, owned-only delete, the reaper's retiring mark, the cap, generation matching, the single waiter, the timing budget, freshness, the foreign check at admission, slot parking, the identity check after install, and the startup gate.
  - The one that survived was reconcile's own owned-only filter. It duplicated `_delete`'s filter, so it was removed; `_delete` now returns the count.
- **Web.** All 4,106 web tests pass, svelte-check has 0 errors, and the colour gate is clean.
  - New: `LiveBandwidthCard.test.ts`, `live-bandwidth.test.ts`, `bitrate.test.ts`, `AreaChart` gap tests, and both device pages render the card with the right key.

## G11 release gate

`scripts/remote/deploy-device-live-bandwidth.sh` runs, inside the daemon container:

- **`verify_live_bandwidth.py kernel`:** exact counts on a throwaway veth pair. 802.1Q frames counted without the tag, a 38-byte packet counted as 46, multicast in upload only, other hosts never. Six watches share the stages; a neighbour's delete under traffic; a reused slot.
- **`verify_live_bandwidth.py bench`:** the CPU cost per frame for no `clsact`, an empty one and 8 watches. Frames: minimum size, IMIX and full size. The release check is IMIX at 1 Gbit/s ≤ 5% of one core.
  - The sender is pinned to one CPU and that CPU's system + irq + softirq time is counted. veth delivers in the sender's softirq, while all-CPU accounting would be swamped by the capture stack's own load. (The plan said all CPUs.)
- **`verify_live_bandwidth.py lifecycle`:** start, ticks advance, filters present, gone 20 s after the last poll, the 9th device gets 503, and no qdisc or filter NetTap doesn't own changes. `/api/health` must stay under 1 s.

Results (G11, 2026-11-09, branch at `37d047f7`):

- **kernel:** 14/14 PASS.
- **bench** (7 interleaved paired rounds; median extra CPU per frame over no `clsact`, as a share of one core at 1 Gbit/s, [quartiles]):

  | Frames | One MAC watch | One IP watch | Eight watches |
  |---|---|---|---|
  | Full size | 6.7% [6.2–7.2] | 7.9% [6.9–8.5] | 13.8% [11.8–15.4] |
  | IMIX | 28.8% [24.6–32.1] | 39.3% [27.8–53.4] | 83.8% [45.5–95.3] |
  | Minimum size | 141% [115–232], unstable | 217% [202–326] | 357% [335–421] |

  Not pass/fail any more (owner ruling); the Settings card states it. The bench's own `/api/health` check failed: 1.50 s worst while it flooded a veth pair at line rate.
- **lifecycle:** 8/8 PASS, `/api/health` 0.42 s worst.
- **off:** 11/11 PASS. Turning off answered in 0.01 s, and 16 filters (eight watches) were gone in 0.5 s.
- **capture safety: FAIL (reproducible), accepted.** Run 1 was void (Cloudflare refused the load downloads). Runs 2 and 3 used two range downloads (OVH + Hetzner, ~330 Mbit/s). `rx_missed_errors` growth per pair (off, eight): run 2 `[(0,38),(0,76),(0,0)]`, run 3 `[(0,56),(0,91),(0,0)]`. The script printed INCONCLUSIVE (one 0/0 pair each), but eight watches missed frames in 4 of 6 arms and off in none. The plan says this blocks the release; it ships because the feature is off by default and the Settings card says so. See `Debugging/BRIDGE-ARCHITECTURE.md` §17.

## Accuracy gate

`scripts/remote/live_bandwidth_reference.py` is an AF_PACKET reader in the daemon container.

- **What it reads:** frames to or from the dev Mac's MAC, with kernel receive timestamps (`SO_TIMESTAMPNS`) converted to the meter's monotonic clock, summed as frame length − 14 into 1 ms bins.
- **When a run is void:** when the reference socket drops frames, or the wall clock moves more than 2 ms.
- **Pass, per direction:** at least 95% valid ticks in the transfer's middle span, at least 15 consecutive eligible windows, and every eligible window within ±5%.
- **Transfers:** a sustained download and upload from the dev Mac.

Results (G11, 2026-11-09): **PASS both ways.** No reference drops, no clock step, GRO off.

| | Download | Upload |
|---|---|---|
| Transfer | 500 MB from OVH (`proof.ovh.net`, 10 MiB/s cap) | 300 MB to Cloudflare `__up` (5 MiB/s cap) |
| Window check | 22 windows, worst 0.12%, mean 0.00% | 25 windows, worst 0.63%, mean 0.03% |
| Average check | +0.27% vs expected (header share 3.6%, 0 dup bytes) | +0.07% (header share 3.8%, 2.6 kB dup) |
| Span check | byte-exact (520,890,231) | byte-exact (312,024,701) |

- The download source moved from Cloudflare to OVH: Cloudflare's `__down` refuses large and repeated requests (403).
- A first download run was void: the capture-safety load was still running, so other traffic was 190% of the flow. Its window and span checks passed anyway.

## Pre-merge review fixes (PR #234, 2026-11-09)

- **Daemon (Python review):**
  - A slot parked by a failed rollback now starts the sampler. With no other watch, nothing retried it before, and its filters kept counting.
  - An admission no longer moves to a new capture interface while watches still sit on the old one. It gets 503 until the next tick removes them there; before, their filters were stranded.
  - The clean-up task keeps retrying after an unexpected error (it used to end with the interface left dirty), and shutdown still cleans up after such a task died.
  - The sampler sleeps through the injectable `sleep`, so tests can step it.
  - `verify_live_bandwidth.py` records an unreadable dump instead of crashing.
- **Web (TypeScript review):**
  - A lone sample between two gaps draws as a dot.
  - A measuring reply without samples, interval or interface counts as unexpected.
  - Two cases now ask again when the page is back in view: "unsupported" (a capture interface can come back up), and a 401, which no longer polls every 2 s.
  - `data` is `$state.raw`.
  - New tests cover the key-change reset and hiding the tab while a poll is timed.
- **Security review:**
  - An admission removes NetTap filters on the capture interface that no watch owns. Left there, they made every install fail with "File exists" until a restart (LOW-1, the same leak the Python review found).
  - `live-bandwidth-cleanup.sh`'s fallback container runs as root with only `NET_ADMIN` (`--user 0 --cap-drop ALL --security-opt no-new-privileges`). As the image's `nettap` user it had no `NET_ADMIN`, so every delete would have failed (LOW-2). Checked on the G11: old uid 998 without `NET_ADMIN`, new uid 0 with `CapEff 0x1000`.
  - Not taken: the mode allowlist (every current mode is covered) and a missing-handle guard (the kernel never gives handle 0). The GET that starts a watch can be triggered cross-site while the feature is on, bounded to one watch for 15 s; a site-wide `Sec-Fetch-Site` rule would close it.
- **Each new test fails with its fix removed** (mutation-checked).
- **Not taken:**
  - A `main.py` wiring test: the G11 lifecycle gate covers it end to end.
  - A bounded wait after killing tc: a tc stuck in the kernel holds `rtnl` anyway.
  - Keeping focus on the Settings switch while it saves: the same pattern as the PCAP switch, and unverified.

## Known limits

- **Eight watches cost the G11 a few missed frames a minute at ~330 Mbit/s** (see the release gate). A cheaper filter layout (fewer shared stages, 802.1Q stages only when tagged) would lower it; not done.
<!-- OLD CODE START — NET-206: the counters are on now
- **Capture safety isn't verified by engine telemetry.** Suricata's stats are disabled and Zeek writes no stats or capture-loss log. Follow-up issue: enable Suricata `stats` and compare `capture.kernel_drops` with the meter off and on.
OLD CODE END -->
<!-- OLD CODE START — NET-206: the device run is done
- **Engine drops, meter off vs eight watches (NET-206): pending device run.** Suricata's stats are on (`SURICATA_STATS_ENABLED` / `SURICATA_STATS_INTERVAL` on suricata-live in `docker/docker-compose.yml`: enabled, interval 10 s; Malcolm writes no stats logger, so nothing is written or indexed). `capture-safety` reads `capture.kernel_packets` / `capture.kernel_drops` from `suricatasc -c dump-counters` per arm (an arm across a Suricata restart is void), and adds a second verdict on the per-pair drop ratios. Run `bash scripts/remote/measure-capture-loss.sh` with a sustained download on the dev Mac and record the per-arm lines and both verdicts here.
OLD CODE END -->
- **Engine drops, meter off vs eight watches (NET-206): measured on the G11, 2026-11-13.** `measure-capture-loss.sh` on main at 6124586c. Three ABA pairs of 60 s arms on `enp4s0`, with 466–497 Mbit/s received (three range downloads on the dev Mac: Hetzner Ashburn, OVH, Hetzner Nuremberg).

| Arm | Setting | Mbit/s | NIC `rx_missed_errors` | Suricata packets | Suricata drops |
|---|---|---|---|---|---|
| 1 | off | 466 | 47 | 3,602,582 | 0 |
| 2 | eight watches | 480 | 0 | 3,659,164 | 0 |
| 3 | eight watches | 489 | 223 | 3,774,804 | 0 |
| 4 | off | 497 | 157 | 3,918,551 | 0 |
| 5 | off | 492 | 201 | 3,820,598 | 0 |
| 6 | eight watches | 497 | 230 | 3,803,366 | 0 |

- **NIC verdict: INCONCLUSIVE (mixed).** Per pair (off, eight): `[(47, 0), (157, 223), (201, 230)]`. Totals: off 405, eight 453, so about 12% more with the watches, and one pair goes the other way.
- **Suricata verdict: PASS.** Off: 11,341,731 packets, 0 dropped. Eight watches: 11,237,334 packets, 0 dropped.
- **What it means.**
  - At about 480 Mbit/s the G11's Realtek NIC misses frames with the meter off too. The earlier ~330 Mbit/s runs had 0 with it off. Its ring buffer can't be raised (the daemon logs "Could not set ring buffer to 4096 on enp4s0: Operation not supported").
  - The watches add little or nothing on top of that.
  - Missed frames never reach the kernel, so Suricata's 0 drops say its AF_PACKET ring kept up, not that nothing was lost. The loss is the NIC's, with or without the meter.
- **Live bandwidth stays off by default**, as before. The Settings card's warning still holds.
- **Not verified on the target hardware.** The Intel i226-V wasn't tested (no bench). `skip_hw` keeps the path in software.
- **Not covered:** bridge and DHCP gateway modes, and IPv6 for devices without a known MAC.

## Files

- **Daemon:** `daemon/services/live_bandwidth.py`, `daemon/services/live_bandwidth_tc.py`, `daemon/api/live_bandwidth.py`, `daemon/api/server.py`, `daemon/main.py`.
- **Daemon tests:** `daemon/tests/test_live_bandwidth*.py`, `daemon/tests/live_bandwidth_fake.py`, `daemon/tests/fixtures/tc_filter_show_g11.json`.
- **Web:** `web/src/lib/components/LiveBandwidthCard.svelte`, `web/src/lib/api/live-bandwidth.ts`, `web/src/lib/utils/bitrate.ts`, `web/src/lib/components/ui/charts/AreaChart.svelte`, `web/src/lib/components/ui/charts/geometry.ts`, both device pages, the tests next to each, and `web/e2e/visual/fixtures/live-bandwidth.ts`.
- **Scripts:** `scripts/remote/deploy-device-live-bandwidth.sh`, `scripts/remote/verify_live_bandwidth.py`, `scripts/remote/live_bandwidth_reference.py`.
- **Docs:** `Debugging/BRIDGE-ARCHITECTURE.md` §17.

## Lessons

- **A terminal tc action hides every later filter.** `action pass` ends classification, so with shared stages only the first matching filter would ever count. `continue` is pinned in the code and in the tests.
- **Redundant guards make mutation testing say "missed".** Two filters doing the same job mean breaking one changes nothing. Remove the duplicate.
- **A script that only runs on the device needs one device run before it counts.** `live_bandwidth_reference.py` set an attribute on a socket object, which Python refuses; no unit test opens an AF_PACKET socket, so it first failed on the G11. The kernel copies a BPF program at `setsockopt`, so the line wasn't needed.
- **Finish one load test before starting the next.** A background download outlived its gate and voided the next accuracy run.
- **Back-to-back mutations of the same size can hit a stale `.pyc`.** The file's mtime and size match, so Python reuses old bytecode. Run mutation checks with `PYTHONDONTWRITEBYTECODE=1`.
