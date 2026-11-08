# Live bandwidth per device on its own page (NET-205)

**Date:** 2026-11-07
**Branch:** `feature/device-live-bandwidth`
**Linear:** NET-205
**Status:** Built and tested locally. The G11 release gate and accuracy gate are next.

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

Results: _pending._

## Accuracy gate

`scripts/remote/live_bandwidth_reference.py` is an AF_PACKET reader in the daemon container.

- **What it reads:** frames to or from the dev Mac's MAC, with kernel receive timestamps (`SO_TIMESTAMPNS`) converted to the meter's monotonic clock, summed as frame length − 14 into 1 ms bins.
- **When a run is void:** when the reference socket drops frames, or the wall clock moves more than 2 ms.
- **Pass, per direction:** at least 95% valid ticks in the transfer's middle span, at least 15 consecutive eligible windows, and every eligible window within ±5%.
- **Transfers:** a sustained Cloudflare download and upload from the dev Mac.

Results: _pending._

## Known limits

- **Capture safety isn't verified by engine telemetry.** Suricata's stats are disabled and Zeek writes no stats or capture-loss log. Follow-up issue: enable Suricata `stats` and compare `capture.kernel_drops` with the meter off and on.
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
- **Back-to-back mutations of the same size can hit a stale `.pyc`.** The file's mtime and size match, so Python reuses old bytecode. Run mutation checks with `PYTHONDONTWRITEBYTECODE=1`.
