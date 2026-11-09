"""NET-205: the capture-safety verdict of the G11 gate (scripts/remote/verify_live_bandwidth.py)."""

import importlib.util
from pathlib import Path

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
