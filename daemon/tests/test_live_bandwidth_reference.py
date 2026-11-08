"""NET-205: the accuracy gate's reference (scripts/remote/live_bandwidth_reference.py)."""

import importlib.util
import struct
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "remote"
    / "live_bandwidth_reference.py"
)
_spec = importlib.util.spec_from_file_location("live_bandwidth_reference", _PATH)
ref = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ref)

OFFSET = 1_700_000_000.0  # CLOCK_REALTIME - CLOCK_MONOTONIC
MBIT10 = 10e6


def _transfer(start=100.0, end=160.0, bytes_per_ms=1250) -> "ref.Bins":
    """A steady 10 Mbit/s download between start and end (CLOCK_MONOTONIC seconds)."""
    bins = ref.Bins(OFFSET)
    for ms in range(int(start * 1000), int(end * 1000)):
        bins.add(OFFSET + ms / 1000 + 0.0002, bytes_per_ms, "down")
    return bins


def _samples(rate=MBIT10, missed=(), off=None, ticks=31):
    samples = []
    for k in range(ticks):
        mono = 100.0005 + 2 * k
        if k in missed:
            samples.append({"tick": k, "mono": None, "down_bps": None, "up_bps": None})
            continue
        down = off[1] if off and off[0] == k else rate
        samples.append({"tick": k, "mono": mono, "down_bps": down, "up_bps": 0.0})
    return samples


class TestBins:
    def test_a_frame_is_placed_by_its_kernel_timestamp_not_when_it_was_read(self):
        bins = ref.Bins(OFFSET)
        # received 0.5 ms before the tick, read by Python 10 ms after it
        bins.add(OFFSET + 1.9995, 1500, "down")
        assert bins.between("down", 0.0, 1.9999) == 1500
        assert bins.between("down", 1.9999, 4.0) == 0

    def test_span_is_where_the_direction_ran_at_one_megabit_or_more(self):
        bins = _transfer(100.0, 160.0)
        bins.add(OFFSET + 50.0, 10, "down")  # a trickle long before stays out
        assert bins.span("down") == (100.0, 160.0)
        assert bins.span("up") is None


class TestEvaluate:
    def test_a_meter_two_percent_high_passes(self):
        result = ref.evaluate(_transfer(), _samples(rate=MBIT10 * 1.02), "down")
        assert result["pass"] is True, result["checks"]
        assert result["span"] == [103.0, 157.0]
        assert result["longest_run"] == result["eligible_windows"] >= 15
        assert abs(result["worst_error"] - 0.02) < 0.002

    def test_one_window_six_percent_off_fails(self):
        result = ref.evaluate(_transfer(), _samples(off=(10, MBIT10 * 1.06)), "down")
        assert result["checks"]["every_window"] is False and result["pass"] is False

    def test_a_missed_tick_counts_against_the_share_and_breaks_the_run(self):
        result = ref.evaluate(_transfer(), _samples(missed=(15,)), "down")
        assert result["ticks_inside"] == 27 and result["valid_share"] == round(
            26 / 27, 4
        )
        assert result["longest_run"] < 15
        assert result["checks"]["longest_run"] is False

    def test_no_transfer_is_a_fail_with_the_reason(self):
        result = ref.evaluate(ref.Bins(OFFSET), _samples(), "up")
        assert result == {"pass": False, "why": "no up transfer seen"}


def _bpf_accepts(program: bytes, frame: bytes) -> bool:
    """A tiny classic-BPF interpreter for the four opcodes the filter uses."""
    code = [
        struct.unpack("HBBI", program[i : i + 8]) for i in range(0, len(program), 8)
    ]
    acc, pc = 0, 0
    while True:
        op, jt, jf, k = code[pc]
        if op == 0x20:
            acc = struct.unpack("!I", frame[k : k + 4])[0]
        elif op == 0x28:
            acc = struct.unpack("!H", frame[k : k + 2])[0]
        elif op == 0x15:
            pc += jt if acc == k else jf
        elif op == 0x06:
            return k != 0
        pc += 1


def test_the_socket_filter_keeps_only_frames_to_or_from_the_mac():
    mac = bytes.fromhex("bc89c1e18ad6")
    other = bytes.fromhex("02000000000a")
    near = bytes.fromhex("bc89c1e18ad7")  # same first two bytes
    near_hi = bytes.fromhex("bc8ac1e18ad6")  # same last four bytes
    program = ref.ether_host_filter(mac)
    tail = b"\x08\x00" + bytes(46)
    assert _bpf_accepts(program, mac + other + tail)
    assert _bpf_accepts(program, other + mac + tail)
    for dst, src in [(other, other), (near, near_hi), (near_hi, near)]:
        assert not _bpf_accepts(program, dst + src + tail)
