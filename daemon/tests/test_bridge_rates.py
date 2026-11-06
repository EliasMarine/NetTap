"""S12: the bridge's byte rates come from monotonic time between ordered counter samples."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.bridge_health import BridgeHealthMonitor


def _frozen(clock):
    # replace the module's `time`, not time.monotonic itself, which the event loop also reads
    return patch("services.bridge_health.time", SimpleNamespace(monotonic=clock))


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _monitor(
    samples: list[int], clock: FakeClock, read_delays: list[float] | None = None
):
    """A monitor whose rx counter steps through `samples` (tx is twice rx)."""
    monitor = BridgeHealthMonitor()
    calls = iter(range(len(samples)))
    delays = iter(read_delays or [0.0] * len(samples))

    async def read_stats(_iface):
        i = next(calls)
        await asyncio.sleep(next(delays))
        return {
            "rx_bytes": samples[i],
            "tx_bytes": samples[i] * 2,
            "rx_packets": 1,
            "tx_packets": 1,
        }

    async def no(*_a):
        return False

    async def up():
        return "up"

    monitor._read_interface_stats = read_stats
    monitor._check_bridge_state = up
    monitor._check_carrier = lambda _i: up()
    monitor._check_watchdog = no
    monitor._check_bypass_file = lambda: False
    return monitor


def test_first_sample_has_no_rate():
    clock = FakeClock()
    with _frozen(clock):
        result = asyncio.run(_monitor([5_000], clock).check_health())
    assert result["rx_bytes_per_sec"] is None
    assert result["tx_bytes_per_sec"] is None


def test_irregular_intervals_divide_by_the_real_elapsed_time():
    clock = FakeClock()
    monitor = _monitor([0, 30_000, 33_000], clock)
    with _frozen(clock):
        asyncio.run(monitor.check_health())
        clock.now += 30.0
        first = asyncio.run(monitor.check_health())
        clock.now += 3.0
        second = asyncio.run(monitor.check_health())
    # 30,000 bytes over 30 s, then 3,000 over 3 s: 1,000 B/s both times, never 30,000 or 3,000
    assert first["rx_bytes_per_sec"] == pytest.approx(1_000)
    assert second["rx_bytes_per_sec"] == pytest.approx(1_000)
    assert second["tx_bytes_per_sec"] == pytest.approx(2_000)


def test_a_counter_reset_has_no_rate():
    clock = FakeClock()
    monitor = _monitor([90_000, 1_000], clock)
    with _frozen(clock):
        asyncio.run(monitor.check_health())
        clock.now += 30.0
        result = asyncio.run(monitor.check_health())
    assert result["rx_bytes_per_sec"] is None


def test_overlapping_callers_take_ordered_samples():
    clock = FakeClock()
    # the first caller's read is slow; unordered, the second caller's newer sample would land
    # first and the first caller's older one would then look like a counter reset
    monitor = _monitor([0, 10_000, 20_000], clock, read_delays=[0.0, 0.02, 0.0])
    with _frozen(clock):

        async def run():
            await monitor.check_health()
            clock.now += 10.0
            return await asyncio.gather(monitor.check_health(), monitor.check_health())

        a, b = asyncio.run(run())
    assert a["rx_bytes_per_sec"] == pytest.approx(1_000)
    # same fake instant for the second sample: no interval, so no rate rather than a guess
    assert b["rx_bytes_per_sec"] is None
