"""S9: one packet-loss figure (kernel drops + NIC misses) in every capture mode."""

import asyncio
import os

import pytest

from services.capture_manager import packet_loss_pct
from services.dhcp_gateway_host import read_iface_stats
from services.mirror_manager import MirrorManager


def test_missed_errors_count_as_loss():
    # rx_dropped 0 but the NIC missed 50: not "no drops"
    assert packet_loss_pct(99_950, 0, 50) == pytest.approx(0.05)


def test_a_tiny_loss_never_rounds_to_zero():
    # one packet in a billion; the old rounding to 4 places reported 0.0
    assert packet_loss_pct(1_000_000_000, 0, 1) > 0


def test_no_packets_is_zero_not_an_error():
    assert packet_loss_pct(0, 0, 0) == 0.0


def _counters(path: str) -> int:
    return {"rx_packets": 99_950, "rx_dropped": 0, "rx_missed_errors": 50}.get(
        os.path.basename(path), 0
    )


def test_mirror_mode_counts_missed_errors():
    mgr = MirrorManager(
        interface="enp2s0",
        management_interface="enp3s0",
        netplan_dir="",
        systemd_dir="",
    )
    mgr._read_sysfs_int = _counters
    mgr._read_sysfs_file = lambda path: "2500"
    stats = asyncio.run(mgr.get_stats())
    assert stats.drop_rate_pct == pytest.approx(0.05)


def test_gateway_mode_counts_missed_errors(tmp_path):
    stats_dir = tmp_path / "eth1" / "statistics"
    stats_dir.mkdir(parents=True)
    for name in ("rx_bytes", "tx_bytes", "tx_packets"):
        (stats_dir / name).write_text("0\n")
    (stats_dir / "rx_packets").write_text("99950\n")
    (stats_dir / "rx_dropped").write_text("0\n")
    (stats_dir / "rx_missed_errors").write_text("50\n")
    (tmp_path / "eth1" / "speed").write_text("1000\n")
    stats = read_iface_stats(str(tmp_path), "eth1")
    assert stats.drop_rate_pct == pytest.approx(0.05)
