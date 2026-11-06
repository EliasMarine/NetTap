# Plan: capture packet loss over the last hour, not since the counters reset (NET-167)
_Round 3 - APPROVED by Codex (round 3); two consistency edits applied after approval_

## Goal

Home and Infrastructure judge capture health from `drop_rate_pct`, a ratio of cumulative interface counters (`rx_packets`, `rx_dropped`, `rx_missed_errors` from sysfs) that reset only when the interface is created (boot, driver reload, bridge re-creation). A loss burst days ago keeps Home's "Packets" stage red (`drop_rate_pct > 0.1` → failing, `web/src/routes/home.ts` `packetsStage`), and loss happening now is diluted. Goal: report loss over a stated recent window (up to the last 60 minutes, always with its real length), judge health from that, and keep the cumulative figure only as a labelled secondary.

Load: one household, one daemon process (`daemon/main.py`), on a mini PC.

**Counter source, stated as the code has it (Codex 5):** the window reads the same interface `get_capture_interface()` names — `br0` itself in bridge mode (`bridge_capture_adapter.py:185` reads `br0/statistics`, not the member NICs), the capture NIC in mirror mode, the LAN NIC in DHCP-gateway mode. Member-NIC coverage for the bridge is out of scope and the UI keeps naming the interface it measured.

## Approach

1. **One validated counter reader — `daemon/services/loss_window.py` (new).**
   - `read_loss_counters(sys_net: str, iface: str) -> Counters | None` reads `ifindex`, then `statistics/rx_packets`, `statistics/rx_dropped`, `statistics/rx_missed_errors`, then `ifindex` again; returns `None` if any read is missing, unreadable or not a non-negative integer, or if the two `ifindex` reads differ (the interface was replaced mid-read — Codex r2-3). It never substitutes 0. `sys_net` is the same `HOST_SYS_NET` default (`/host/sys/class/net`) the managers use.
   - Reading sysfs directly (instead of calling `cm.get_stats()`) means the stub (`capture_mode_stub.py:92`, zeros) and the managers' read-0-on-error helpers (`bridge_capture_adapter.py:243`, `mirror_manager.py:609`, `dhcp_gateway_host.py:259`) can never feed the window (Codex 1, 2). Those managers are unchanged.
2. **`LossWindow` (same module, pure, no I/O).**
   - Samples are `(at, iface, ifindex, rx_packets, rx_dropped, rx_missed_errors)` with `at = time.monotonic()` (Codex 3: raw components kept).
   - `add(at, iface, counters | None)`:
     - `None` (unreadable) clears every sample and records state `unavailable`; recovery needs two fresh valid samples (Codex 2).
     - A different `iface` or `ifindex` from the newest sample clears earlier samples (capture mode change, stub → real manager on another interface, or the interface re-created — a new ifindex even when the counters have already grown past their old values) (Codex 1, 3).
     - Any single component lower than in the newest sample clears earlier samples (reset or wrap) (Codex 3).
     - Samples with `at < newest.at - 3600` are dropped (Codex 4: no boundary sample kept).
   - `over() -> {"state": "ok"|"measuring"|"unavailable", "window": {...} | None}`: with at least two samples spanning ≥ 60 s, compares the **oldest sample inside the last 3,600 s** with the newest:
     - `arrived = Δrx_packets + Δrx_missed_errors`, `lost = Δrx_dropped + Δrx_missed_errors` (Codex 6, kernel `rtnl_link_stats64`: `rx_packets` already includes packets the host dropped, `rx_missed_errors` are packets the device dropped before the host saw them, so they are not in `rx_packets`).
     - If `lost > arrived` (inconsistent counters) the window is rejected: state `unavailable`, logged (Codex 3).
     - `drop_rate_pct = lost / arrived * 100` when `arrived > 0`, else `None` (not 0.0) (Codex 7).
     - Returns `{"seconds": span, "arrived", "lost", "drop_rate_pct"}`.
   - Fewer than two valid samples or a span under 60 s → state `measuring`, window `None`.
3. **The cumulative figure comes from the same validated snapshot (Codex r2-2).**
   - `over()` also returns `"cumulative": {"arrived", "lost", "drop_rate_pct"} | None` from the newest valid sample (its absolute counters, same `arrived`/`lost` definitions). `None` when the newest read was unavailable; `drop_rate_pct` is `None` when `arrived == 0` or `lost > arrived` (no clamp, no made-up 100%).
   - The web shows the cumulative figure only from this block, never from the managers' `rx_*`/`drop_rate_pct` fields (which can be read-0-on-error or stub zeros). Those fields stay in the payload unchanged for compatibility.
   - `packet_loss_pct` (`services/capture_manager.py:57`, feeding the managers' `drop_rate_pct`) moves to the same kernel semantics, `lost / (rx_packets + rx_missed_errors)`, with no clamp, so the payload never carries two formulas; old line kept as OLD CODE; S9 tests updated with their old expectations kept as OLD CODE.
4. **Sampling — `daemon/api/capture.py`.**
   - `register_capture_routes` sets `app["loss_window"] = LossWindow()` and appends an `app.cleanup_ctx` that starts one task: every 60 s, `sample(app)` = read `app["capture_manager"].get_capture_interface()` fresh, `read_loss_counters`, `window.add(...)`. Exceptions are logged and the loop continues. On cleanup the task is cancelled **and awaited** (aiohttp background-task pattern).
   - `handle_capture_stats` calls the same `sample(app)` (so the newest point is current), then returns `stats.to_dict()` plus `"loss_window": window.over()`.
   - `sample()` is synchronous between reading the clock, reading sysfs and appending (no `await` inside), so the sampler and a request can't interleave; a comment states that invariant.
   - Logging: info when the window restarts (with the reason: new interface, new ifindex, counter decrease); warning when counters are unreadable (at most once per state change, not every tick).
5. **Web contract — `web/src/lib/api/capture.ts`.** `CaptureStatsResponse.loss_window: { state: 'ok' | 'measuring' | 'unavailable'; window: { seconds: number; arrived: number; lost: number; drop_rate_pct: number | null } | null; cumulative: { arrived: number; lost: number; drop_rate_pct: number | null } | null }` (both blocks validated), validated where the response is parsed; a missing or malformed `loss_window` reads as `{ state: 'unavailable', window: null }`, never as 0 loss. `windowWords(seconds)` → "last 58 min" (minutes, rounded down, so it never overstates).
6. **Home `packetsStage` (`web/src/routes/home.ts`).**
   - `ok` with `arrived > 0`: status `failing` if `drop_rate_pct > 0.1` else `ok`; detail "0.42% lost in the last 58 min · 1,234 packets" or "No packets lost in the last 58 min · 98,765 received".
   - `ok` with `arrived == 0`: status `unknown`, "No packets in the last 58 min".
   - `measuring`: status `unknown`, "Measuring recent loss…".
   - `unavailable`: status `unknown`, "Loss counters unavailable".
   - The card subtitle stops saying "cumulative"; it says packets cover up to the last 60 minutes on `<interface>`.
7. **Infrastructure (`web/src/routes/infrastructure/+page.svelte`).**
   - The "Packet loss" KPI uses the same four branches as Home through one shared helper (`lossWords(loss_window)` in `capture.ts`), so zero arrivals never shows a percentage on either page (Codex 7).
   - **Stale responses (Codex r2-1):** Infrastructure's `settle()` keeps the last good value on failure (line ~94, used for `captureStats` at ~420). When the latest capture-stats request failed, the loss window reads as `unavailable` ("Couldn't refresh the loss figures"), not the old "last 58 min"; the rest of the page's keep-last-good behaviour is unchanged. Home already clears `captureStats` on failure (`+page.svelte:170`).
   - **Capture stage precedence (Codex r2-4):** the strip's `captureStage()` (~924) keeps its own status: bypass active, promiscuous off, or no health reading stay `failing`/`unknown` whatever the loss window says. Only the loss detail text comes from the shared helper; a loss over 0.1 % can turn an otherwise ok stage `failing`, never the reverse.
   - The details table shows the validated cumulative count, labelled "Packets lost since the counters reset" (title `LOSS_SCOPE`), or "Unavailable".
8. OLD CODE blocks for every replaced line.

## Key decisions & tradeoffs

- **In-process ring, not OpenSearch or disk:** a restart loses the window and the pages say "Measuring…" for a minute. Persisting buys little for a recent figure and adds SSD writes.
- **Read sysfs directly in one validated reader** instead of fixing three managers' read helpers: every loss figure the UI shows (window and cumulative) comes from it, and the managers' other fields keep their behaviour.
- **60 s sampler plus a sample per request,** so "last 60 min" doesn't depend on someone having a page open.
- **Oldest sample inside the hour, never one outside it;** the span is reported as measured and labelled in whole minutes rounded down.
- **ifindex + interface name + per-component decrease** detect resets; a reset restarts the window rather than computing a cross-reset delta.

## Risks / open questions

- An interface re-created and refilled past its old counts within one 60 s tick keeps the same name; its new ifindex catches it.
- `HOST_SYS_NET` must be mounted in the daemon container as the managers already rely on it.
- Driver variance: a driver that does *not* include host drops in `rx_packets` would make the rate slightly high (lost/arrived with arrived missing those drops). The kernel documents the inclusion; `lost > arrived` is rejected (rate `None`), never clamped.

## Verification plan

- `daemon/tests/test_loss_window.py` (with a tmp sysfs tree): valid read; each of the four files missing/garbage → `None`; window over two samples (exact Δ and rate); under 60 s → measuring; one sample → measuring; a masked decrease `(1000,100,0)→(900,210,0)` clears and restarts (no 1100%); a new ifindex with grown counters clears; an interface change clears; unreadable → unavailable, then recovery needs two new valid samples; a two-hour sampling gap → the old sample is dropped and the window is `measuring` (never a two-hour delta); an expired loss burst no longer counts after an hour; zero arrivals → `drop_rate_pct` None; `lost > arrived` → unavailable.
- `packet_loss_pct` tests updated to the kernel semantics (100 drops already in 1,000 rx_packets → 10%; lost > arrived is not clamped).
- Reader: the `ifindex` changes between the before and after reads → `None` (deterministic: the test swaps the file between reads via an injected opener or a tmp tree it rewrites).
- Cumulative block: unreadable newest read → `None`; `rx_packets=100, rx_dropped=150` → rate `None`, not 100 %; a stub manager naming an interface that exists → real counters in both blocks, never the stub's zeros.
- API: `create_app()` builds without starting the task (sync construction); a full `AppRunner` setup/cleanup starts and then cancels and awaits it; `/api/capture/stats` includes `loss_window` (`measuring` on the first call; `ok` after two samples ≥ 60 s apart with an injected clock and tmp sysfs); a stub manager whose interface doesn't exist in sysfs gives `unavailable`, never zeros.
- Web: `home.test.ts` for the four branches; `capture.test.ts` for the validator, `windowWords` and `lossWords`; the Infrastructure page test for the KPI, zero arrivals, the "since the counters reset" label, a good reading → failed refresh (shows unavailable, not the old window) → recovery, and bypass / promiscuous-off each paired with a healthy window (the stage stays failing). Every new test fails without its change.
- All suites: daemon pytest, ruff, vitest, svelte-check, colours, e2e, visual (fixtures for `/api/capture/stats` gain `loss_window`).
- Device (Codex 8), in the deploy script after the daemon restarts: wait 70 s, read `/api/capture/stats` → `loss_window.state == "ok"`, `60 ≤ seconds ≤ 3600`, every count ≥ 0, `lost ≤ arrived`, `arrived ≤ rx_packets + rx_missed_errors` (cumulative), and the interface named matches the capture interface. No comparison against two of the script's own reads.

## Rollback / migration safety

Additive field. Rolling back the daemon leaves `loss_window` absent, which the new web reads as `unavailable` (status unknown) — degraded but honest. The `packet_loss_pct` change moves the cumulative figure by at most the double-counted share (tiny at real loss rates). No stored data.

## Observability

Info on every window restart with its reason; a warning when the counters become unreadable and an info when they recover; the API exposes the state so the UI says "Measuring…" or "Loss counters unavailable".

## Out of scope

- Per-member loss for the bridge's two NICs.
- Historical loss charts.
- NET-166 (storage units) and NET-163 (inline-mode threat matching).
