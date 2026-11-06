"""NET-167: capture loss over a recent window, from validated counter readings."""

import asyncio
import builtins
import os

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api.capture import register_capture_routes, sample_loss
from services.capture_manager import packet_loss_pct
from services.loss_window import Counters, LossWindow, read_loss_counters


def _sysfs(
    root, iface="br0", ifindex=7, rx_packets=1000, rx_dropped=10, rx_missed_errors=5
):
    stats = root / iface / "statistics"
    stats.mkdir(parents=True, exist_ok=True)
    (root / iface / "ifindex").write_text(f"{ifindex}\n")
    for name, value in (
        ("rx_packets", rx_packets),
        ("rx_dropped", rx_dropped),
        ("rx_missed_errors", rx_missed_errors),
    ):
        (stats / name).write_text(f"{value}\n")


def C(rx_packets, rx_dropped=0, rx_missed_errors=0, ifindex=7):
    return Counters(ifindex, rx_packets, rx_dropped, rx_missed_errors)


# ---------------------------------------------------------------------------
# The reader: a failed read is never a 0
# ---------------------------------------------------------------------------


def test_reads_the_counters(tmp_path):
    _sysfs(tmp_path)
    assert read_loss_counters(str(tmp_path), "br0") == Counters(7, 1000, 10, 5)


@pytest.mark.parametrize(
    "broken",
    [
        "ifindex",
        "statistics/rx_packets",
        "statistics/rx_dropped",
        "statistics/rx_missed_errors",
    ],
)
@pytest.mark.parametrize("how", ["missing", "garbage", "negative"])
def test_any_unreadable_file_is_none(tmp_path, broken, how):
    _sysfs(tmp_path)
    path = tmp_path / "br0" / broken
    if how == "missing":
        path.unlink()
    else:
        path.write_text("n/a\n" if how == "garbage" else "-1\n")
    assert read_loss_counters(str(tmp_path), "br0") is None


def test_an_interface_replaced_mid_read_is_none(tmp_path, monkeypatch):
    _sysfs(tmp_path)
    ifindex = str(tmp_path / "br0" / "ifindex")
    real_open = builtins.open
    reads = []

    def swapping_open(path, *args, **kwargs):
        # the second ifindex read sees the re-created interface
        if os.fspath(path) == ifindex:
            reads.append(path)
            if len(reads) == 2:
                (tmp_path / "br0" / "ifindex").write_text("8\n")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", swapping_open)
    assert read_loss_counters(str(tmp_path), "br0") is None


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def test_window_between_two_readings():
    w = LossWindow()
    w.add(0, "br0", C(1000, 10, 0))
    w.add(600, "br0", C(11000, 110, 0))
    out = w.over()
    assert out["state"] == "ok"
    assert out["interface"] == "br0"
    # 10,000 arrived, 100 of them dropped by the host: 1 %, not 100 / 10,100
    assert out["window"] == {
        "seconds": 600,
        "arrived": 10000,
        "lost": 100,
        "drop_rate_pct": 1.0,
    }
    assert out["cumulative"] == {"arrived": 11000, "lost": 110, "drop_rate_pct": 1.0}


def test_missed_packets_count_in_both_arrived_and_lost():
    w = LossWindow()
    w.add(0, "eth1", C(0))
    w.add(120, "eth1", C(950, 0, 50))
    assert w.over()["window"] == {
        "seconds": 120,
        "arrived": 1000,
        "lost": 50,
        "drop_rate_pct": 5.0,
    }


def test_one_reading_or_under_a_minute_is_measuring():
    w = LossWindow()
    assert w.over() == {
        "state": "measuring",
        "interface": None,
        "window": None,
        "cumulative": None,
    }
    w.add(0, "br0", C(1000))
    assert w.over()["state"] == "measuring"
    assert w.over()["cumulative"] == {"arrived": 1000, "lost": 0, "drop_rate_pct": 0.0}
    w.add(59, "br0", C(2000))
    assert w.over()["state"] == "measuring"


def test_a_masked_decrease_restarts_instead_of_1100_percent():
    # (1000, 100, 0) -> (900, 210, 0): both totals grew, but rx_packets went down
    w = LossWindow()
    w.add(0, "br0", C(1000, 100, 0))
    w.add(600, "br0", C(900, 210, 0))
    assert w.over()["state"] == "measuring"
    w.add(1200, "br0", C(1900, 220, 0))
    assert w.over()["window"] == {
        "seconds": 600,
        "arrived": 1000,
        "lost": 10,
        "drop_rate_pct": 1.0,
    }


def test_a_recreated_interface_restarts_even_with_grown_counters():
    w = LossWindow()
    w.add(0, "br0", C(1000, 0, 0, ifindex=7))
    w.add(600, "br0", C(50000, 5000, 0, ifindex=9))
    assert w.over()["state"] == "measuring"


def test_a_new_capture_interface_restarts():
    w = LossWindow()
    w.add(0, "br0", C(1000))
    # OLD CODE: w.add(600, "enp4s0", C(50000, ifindex=3)) (the new ifindex alone restarted it)
    w.add(600, "enp4s0", C(50000))  # same ifindex: only the name differs
    assert w.over()["state"] == "measuring"
    assert w.over()["interface"] == "enp4s0"


def test_unreadable_then_two_new_readings_to_recover():
    w = LossWindow()
    w.add(0, "br0", C(1000))
    w.add(60, "br0", None)
    assert w.over() == {
        "state": "unavailable",
        "interface": "br0",
        "window": None,
        "cumulative": None,
    }
    w.add(120, "br0", C(3000))
    assert w.over()["state"] == "measuring"
    w.add(180, "br0", C(4000, 10))
    assert w.over()["window"]["seconds"] == 60


def test_never_more_than_an_hour_and_a_burst_expires():
    w = LossWindow()
    w.add(0, "br0", C(0))
    w.add(60, "br0", C(1000, 500))  # a burst in the first minute
    for minute in range(2, 63):
        w.add(minute * 60, "br0", C(1000 + (minute - 1) * 1000, 500))
    out = w.over()
    assert out["window"]["seconds"] <= 3600
    # the burst's minute is older than an hour now: nothing lost in the window
    assert out["window"]["lost"] == 0


def test_a_gap_longer_than_an_hour_is_measuring_not_a_two_hour_delta():
    w = LossWindow()
    w.add(0, "br0", C(0))
    w.add(60, "br0", C(1000))
    w.add(7260, "br0", C(9000))
    assert w.over()["state"] == "measuring"


def test_readings_closer_than_the_gap_are_not_kept():
    # a stats request every 10 ms for 100 s: memory stays bounded, the window stays right
    w = LossWindow()
    w.add(0, "br0", C(0))
    for i in range(1, 10_001):
        w.add(i * 0.01, "br0", C(i * 10, i // 100))
    assert len(w._samples) <= 100 / 5 + 1
    out = w.over()
    assert out["state"] == "ok"
    assert out["window"]["seconds"] >= 95
    assert out["window"]["lost"] <= out["window"]["arrived"]


def test_a_reset_inside_the_gap_still_restarts():
    w = LossWindow()
    w.add(0, "br0", C(1000))
    w.add(60, "br0", C(2000))
    w.add(61, "br0", C(10))  # 1 s later, counters went down
    assert w.over()["state"] == "measuring"


def test_nothing_arrived_has_no_rate():
    w = LossWindow()
    w.add(0, "br0", C(0))
    w.add(300, "br0", C(0))
    assert w.over()["window"] == {
        "seconds": 300,
        "arrived": 0,
        "lost": 0,
        "drop_rate_pct": None,
    }


def test_more_lost_than_arrived_is_unavailable_not_clamped():
    w = LossWindow()
    w.add(0, "br0", C(100, 0))
    w.add(300, "br0", C(100, 150))
    out = w.over()
    assert out["state"] == "unavailable"
    assert out["window"] is None
    assert out["cumulative"] == {"arrived": 100, "lost": 150, "drop_rate_pct": None}


# ---------------------------------------------------------------------------
# The cumulative formula (kernel semantics) and the API
# ---------------------------------------------------------------------------


def test_cumulative_rate_counts_host_drops_once():
    assert packet_loss_pct(1000, 100, 0) == pytest.approx(10.0)
    assert packet_loss_pct(100, 150, 0) == pytest.approx(150.0)  # not clamped


class _Manager:
    def __init__(self, iface):
        self.iface = iface

    def get_capture_interface(self):
        return self.iface

    async def get_stats(self):
        from services.capture_manager import CaptureStats

        return CaptureStats(capture_interface=self.iface)  # the stub's zeros


def _app(tmp_path, iface="br0"):
    app = web.Application()
    app["capture_manager"] = _Manager(iface)
    app["loss_sys_net"] = str(tmp_path)
    register_capture_routes(app)
    return app


def test_the_app_builds_without_starting_the_sampler(tmp_path):
    app = _app(tmp_path)
    assert app["loss_window"].over()["state"] == "measuring"


def test_a_manager_with_zeros_never_feeds_the_window(tmp_path, monkeypatch):
    # the stub reports zeros; the window reads the named interface's real counters
    _sysfs(tmp_path, rx_packets=5000, rx_dropped=5)
    app = _app(tmp_path)
    clock = iter([0.0, 120.0])
    monkeypatch.setattr("api.capture.time.monotonic", lambda: next(clock))
    sample_loss(app)
    _sysfs(tmp_path, rx_packets=6000, rx_dropped=6)
    sample_loss(app)
    out = app["loss_window"].over()
    assert out["window"] == {
        "seconds": 120,
        "arrived": 1000,
        "lost": 1,
        "drop_rate_pct": 0.1,
    }
    assert out["cumulative"]["arrived"] == 6005


def test_a_missing_interface_is_unavailable(tmp_path):
    app = _app(tmp_path, iface="nope0")
    sample_loss(app)
    assert app["loss_window"].over()["state"] == "unavailable"


def test_stats_endpoint_carries_the_window_and_the_sampler_stops_cleanly(tmp_path):
    _sysfs(tmp_path)

    async def run():
        client = TestClient(TestServer(_app(tmp_path)))
        await client.start_server()
        try:
            resp = await client.get("/api/capture/stats")
            body = await resp.json()
            task = next(
                t for t in asyncio.all_tasks() if t.get_name() == "loss-window-sampler"
            )
        finally:
            await client.close()
        # read inside the loop: asyncio.run cancels leftover tasks itself once run() returns
        return body, task.done()

    # OLD CODE: body, task = asyncio.run(run()) … assert task.done() (always true after asyncio.run)
    body, sampler_stopped = asyncio.run(run())
    assert body["loss_window"]["state"] == "measuring"
    assert body["loss_window"]["cumulative"] == {
        "arrived": 1005,
        "lost": 15,
        "drop_rate_pct": pytest.approx(15 / 1005 * 100),
    }
    assert sampler_stopped
