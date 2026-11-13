"""NET-205: the capture-safety verdict of the G11 gate (scripts/remote/verify_live_bandwidth.py)."""

import importlib.util
import json
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "remote"
    / "verify_live_bandwidth.py"
)
_spec = importlib.util.spec_from_file_location("verify_live_bandwidth", _PATH)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_capture_safety_passes_only_when_no_eight_watch_arm_drops_more():
    # (off arm growth, eight-watch arm growth) per pair
    assert gate.capture_verdict([(0, 0), (0, 0), (0, 0)]) == "PASS"
    assert gate.capture_verdict([(5, 3), (2, 2), (0, 0)]) == "PASS"
    assert gate.capture_verdict([(0, 1), (2, 9), (0, 4)]) == "FAIL"
    assert gate.capture_verdict([(0, 1), (0, 0), (3, 3)]) == "INCONCLUSIVE"


def test_the_bench_flags_a_spread_wider_than_the_median():
    text, unstable = gate.spread_text([10, 11, 12, 13, 14], 1e6)
    assert text.startswith("+12 ns [") and "= 1.2% [" in text and unstable is False
    assert gate.spread_text([-5, 0, 5, 30, 40], 1e6)[1] is True


# NET-206: Suricata's kernel counters from `suricatasc -c dump-counters`


def _answer(uptime=100, packets=5000, drops=3, ret="OK"):
    message = {
        "uptime": uptime,
        "capture": {"kernel_packets": packets, "kernel_drops": drops},
        "decoder": {"pkts": packets},
    }
    return json.dumps(
        {"message": message, "return": ret}, indent=1
    )  # multi-line, as suricatasc


def test_dump_counters_gives_uptime_packets_and_drops():
    assert gate.parse_counters(_answer()) == (100, 5000, 3)


def test_counters_switched_off_say_what_to_deploy():
    off = '{"message":"stats are disabled in the config","return":"NOK"}'
    with pytest.raises(RuntimeError, match="deploy NET-206"):
        gate.parse_counters(off)


@pytest.mark.parametrize(
    "out",
    [
        json.dumps({"message": {"uptime": 5, "capture": {}}, "return": "OK"}),
        json.dumps(
            {
                "message": {"capture": {"kernel_packets": 1, "kernel_drops": 0}},
                "return": "OK",
            }
        ),
        "Unable to connect to socket",
    ],
)
def test_a_missing_counter_or_garbage_is_an_error(out):
    with pytest.raises(RuntimeError):
        gate.parse_counters(out)


def test_an_arm_counts_suricatas_packets_and_drops():
    assert gate.arm_delta((100, 1000, 2), (171, 61000, 7), 1) == (60000, 5)


@pytest.mark.parametrize(
    "after",
    [
        (12, 900, 0),  # restarted: uptime went down
        (171, 900, 2),  # packets went down
        (171, 61000, 1),  # drops went down
    ],
)
def test_a_suricata_restart_voids_the_arm(after):
    with pytest.raises(RuntimeError, match="restarted during arm 3"):
        gate.arm_delta((100, 1000, 2), after, 3)


def test_an_arm_with_no_packets_has_no_result():
    with pytest.raises(RuntimeError, match="no packets in arm 2"):
        gate.arm_delta((100, 1000, 2), (171, 1000, 2), 2)


def test_suricata_verdict_compares_drop_ratios():
    # arms differ in length, so (off ratio, eight ratio) per pair
    assert gate.capture_verdict([(0.0, 0.0), (1e-4, 5e-5), (0.0, 0.0)]) == "PASS"
    assert gate.capture_verdict([(0.0, 1e-5), (1e-4, 2e-4), (0.0, 1e-6)]) == "FAIL"
