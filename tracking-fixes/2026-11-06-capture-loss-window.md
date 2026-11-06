# 2026-11-06 — Capture packet loss over the last hour, not since the counters reset (NET-167)

**Status:** fixed on `fix/capture-loss-window`. The PR is pending. Plan: `plans/2026-11-06-net167-capture-loss-window.md` (Codex approved in 3 rounds).

**Problem**
- Home's "Packets" stage and Infrastructure's "Packet loss" KPI came from the interface counters in sysfs.
- Those counters reset only when the interface is created (boot, driver reload, a re-created bridge).
- So a loss burst days ago kept Home red, and loss happening now was diluted by days of clean traffic.

**Root causes**
- No window: the figure was `drop_rate_pct` over the counters' whole life.
- The formula counted host drops twice. The kernel's `rtnl_link_stats64` already includes them in `rx_packets`, so 100 drops in 1,000 packets read 9.09%, not 10%.
- The managers' sysfs helpers read a failed file as 0, and the stub manager reports zeros, so a broken read could look like "no loss".

**Fix (daemon)**
- `daemon/services/loss_window.py` (new):
  - `read_loss_counters` reads `ifindex`, the three counters, then `ifindex` again. Any failed, garbage or negative read, or a changed ifindex, gives `None`, never 0.
  - `LossWindow` keeps validated readings for up to an hour. It restarts on a new capture interface, a new ifindex, or any single counter going down. Unreadable counters make it `unavailable`.
  - `over()` reports `state` (`ok`, `measuring`, `unavailable`), the window (`seconds`, `arrived`, `lost`, `drop_rate_pct`) and the cumulative figure from the same reading. No rate when nothing arrived; lost > arrived is rejected, never clamped.
- `daemon/api/capture.py`: a sampler started from `cleanup_ctx` adds a reading every 60 s; `/api/capture/stats` adds one more and returns `loss_window`. On shutdown the task is cancelled and awaited.
- `daemon/services/capture_manager.py`: `packet_loss_pct` follows the kernel semantics, `lost / (rx_packets + rx_missed_errors)`, with no clamp. Old version kept as OLD CODE.

**Fix (web)**
- `web/src/lib/api/capture.ts`: validates `loss_window` (missing or malformed reads as unavailable, never 0 loss); one `lossWords` helper words all four cases; `windowWords` rounds minutes down.
- Home `packetsStage` and Infrastructure's KPI use the same helper. Infrastructure shows "unavailable" when the latest refresh failed, rather than the old window. The capture stage keeps bypass and promiscuous-off as failing whatever the loss says.
- The details table shows the validated cumulative count, labelled "Packets lost since the counters reset".

**Tests**
- `daemon/tests/test_loss_window.py` (30 tests): the reader, every window rule, the kernel formula, and the API (the stub's zeros never feed the window; the sampler stops cleanly).
- Fixtures in `test_dhcp_gateway.py` and `test_mirror_manager.py` moved to the kernel semantics; old values kept as OLD CODE.
- Web: validator, wording, Home branches, Infrastructure KPI, stale refresh and stage precedence.

**Device check**
- `bash /home/nettap/NetTap/scripts/remote/deploy-capture-loss-window.sh` rebuilds the daemon and web, checks `measuring` straight after the restart, then after 70 s checks: state ok, 60 to 3,600 s, lost ≤ arrived ≤ the interface's own count, on the capture interface.

**Lessons**
- Read the kernel's counter definitions before building a ratio from them: `rx_packets` already includes `rx_dropped`.
- A failed read must never become a 0 in a health figure. Return "unknown" and say so.
- A cumulative counter answers "since when?" with "since the interface was created". Any health judgement needs a stated window.
