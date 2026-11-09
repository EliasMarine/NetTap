"""NET-205: the accuracy gate's reference (scripts/remote/live_bandwidth_reference.py)."""

import importlib.util
import json
import socket
import struct
from pathlib import Path

import pytest

from services.live_bandwidth_tc import cookie_for

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


# ---------------------------------------------------------------------------- flow accounting

DEV = bytes.fromhex("bc89c1e18ad6")
ROUTER = bytes.fromhex("020000000001")
DEV_IP, CF_IP = socket.inet_aton("192.168.1.20"), socket.inet_aton("104.16.0.1")
MSS = 1448  # payload of a full frame: 14 + 20 + 32 + 1448 = 1514 bytes, 1500 at the meter's layer


def _frame(down: bool, seq: int, payload: int, port=50000, far=(CF_IP, 443), proto=6):
    """The headers of a frame to (down) or from the dev Mac, and its length on the wire."""
    ends = [(DEV_IP, port), far]
    (src, sport), (dst, dport) = ends[::-1] if down else ends
    eth = (DEV + ROUTER if down else ROUTER + DEV) + b"\x08\x00"
    ip = struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, 52 + payload, 0, 0x4000, 64, proto, 0, src, dst
    )
    tcp = struct.pack(
        "!HHIIBB", sport, dport, seq % (1 << 32), 0, 8 << 4, 0x10
    ) + bytes(26)
    return eth + ip + tcp, max(66 + payload, 60)


def _download(acc, segments=1000, seq=1000, payload=MSS, at=100.0):
    """A clean download: every other data segment gets an ACK back."""
    for n in range(segments):
        acc.add(*_frame(True, seq + n * payload, payload), at + n / 1000)
        if n % 2:
            acc.add(*_frame(False, 1, 0), at + n / 1000)


def _stats(acc, direction="down"):
    return acc.flow_stats(acc.curl_flow(direction))[direction]


class TestFlowAccounting:
    def test_a_clean_flow_measures_its_header_share_and_passes(self):
        acc = ref.Accounting(DEV)
        _download(acc)
        stats = _stats(acc)
        assert (
            stats["flow_l3"] == 1000 * 1500
            and stats["flow_payload_unique"] == 1000 * MSS
        )
        assert (
            stats["dup_bytes"] == stats["partial_overlaps"] == stats["unrelated"] == 0
        )
        assert (stats["first_data"], stats["last_data"]) == (100.0, 100.999)
        verdict = ref.judge_average(1000 * 1500, 1000 * MSS, stats)
        assert verdict["header_share"] == pytest.approx(1500 / MSS - 1)
        assert verdict["verdict"] == "PASS" and verdict["error"] == pytest.approx(0)

    def test_a_meter_six_percent_over_fails(self):
        acc = ref.Accounting(DEV)
        _download(acc)
        verdict = ref.judge_average(int(1000 * 1500 * 1.06), 1000 * MSS, _stats(acc))
        assert verdict["verdict"] == "FAIL" and verdict["error"] == pytest.approx(0.06)

    def test_other_traffic_is_unrelated_and_over_one_percent_voids_the_run(self):
        small, big = ref.Accounting(DEV), ref.Accounting(DEV)
        for acc, bursts in ((small, 5), (big, 20)):  # 0.5 % and 2 % of the flow
            _download(acc)
            # a web page on port 80 and a UDP frame mid-transfer
            for n in range(bursts):
                acc.add(*_frame(True, n * MSS, MSS, port=50001, far=(CF_IP, 80)), 100.5)
            acc.add(*_frame(True, 0, MSS, proto=17), 100.5)
        stats = _stats(small)
        assert stats["unrelated"] == 6 * 1500
        assert (
            ref.judge_average(1000 * 1500 + 6 * 1500, 1000 * MSS, stats)["verdict"]
            == "PASS"
        )
        verdict = ref.judge_average(1000 * 1500 + 21 * 1500, 1000 * MSS, _stats(big))
        assert verdict["verdict"] == "VOID" and "other traffic" in verdict["reasons"][0]

    def test_retransmitted_download_segments_count_as_duplicates(self):
        acc = ref.Accounting(DEV)
        _download(acc)
        # the server resends ten segments; nothing on the Mac's side says so
        for n in range(10):
            acc.add(*_frame(True, 1000 + n * MSS, MSS), 101.0)
        stats = _stats(acc)
        assert (
            stats["dup_bytes"] == 10 * 1500
            and stats["flow_payload_unique"] == 1000 * MSS
        )
        verdict = ref.judge_average(1010 * 1500, 1000 * MSS, stats)
        assert verdict["header_share"] == pytest.approx(1500 / MSS - 1)
        assert verdict["verdict"] == "PASS" and verdict["error"] == pytest.approx(0)
        acc_over = ref.Accounting(DEV)
        _download(acc_over, segments=100)
        for n in range(3):  # 3 % resent
            acc_over.add(*_frame(True, 1000 + n * MSS, MSS), 101.0)
        assert (
            ref.judge_average(103 * 1500, 100 * MSS, _stats(acc_over))["verdict"]
            == "VOID"
        )

    def test_the_sequence_number_wraps(self):
        acc = ref.Accounting(DEV)
        _download(acc, seq=(1 << 32) - 10 * MSS)
        stats = _stats(acc)
        assert stats["flow_payload_unique"] == 1000 * MSS
        assert stats["dup_bytes"] == stats["partial_overlaps"] == 0
        acc = ref.Accounting(DEV)
        acc.add(*_frame(True, (1 << 32) - 500, MSS), 100.0)  # straddles the wrap
        acc.add(*_frame(True, 0, 948), 100.1)  # its tail resent from sequence 0
        stats = _stats(acc)
        assert stats["flow_payload_unique"] == MSS and stats["dup_bytes"] == 1000
        assert stats["partial_overlaps"] == 0

    def test_a_partly_overlapping_segment_voids_the_run(self):
        acc = ref.Accounting(DEV)
        acc.add(*_frame(True, 0, 1000), 100.0)
        acc.add(*_frame(True, 500, 1000), 100.1)
        stats = _stats(acc)
        assert stats["partial_overlaps"] == 1 and stats["flow_payload_unique"] == 1500
        verdict = ref.judge_average(stats["flow_l3"], 1500, stats)
        assert (
            verdict["verdict"] == "VOID"
            and "partly overlapped" in verdict["reasons"][0]
        )

    def test_the_curl_flow_is_the_https_flow_with_most_bytes_that_way(self):
        acc = ref.Accounting(DEV)
        _download(acc, segments=10)
        for n in range(20):  # a bigger upload on another flow
            acc.add(*_frame(False, n * MSS, MSS, port=50002), 100.0)
        for n in range(50):
            acc.add(*_frame(True, n * MSS, MSS, port=50003, far=(CF_IP, 8443)), 100.0)
        down = acc.flow_stats(acc.curl_flow("down"))
        assert down["flow"] == "tcp 192.168.1.20:50000 <-> 104.16.0.1:443"
        assert down["down"]["unrelated"] == 50 * 1500
        assert acc.curl_flow("up")[1] == 50002

    def test_no_data_in_the_flow_is_void(self):
        stats = {"flow_l3": 52, "flow_payload_unique": 0, "dup_bytes": 0, "unrelated": 0,
                 "partial_overlaps": 0}  # fmt: skip
        assert ref.judge_average(52, 0, stats)["verdict"] == "VOID"


class TestRanges:
    def test_merges_touching_and_fills_gaps(self):
        ranges = ref.Ranges()
        added = [ranges.add(*r) for r in [(0, 10), (20, 30), (40, 50), (10, 20)]]
        assert added == [0, 0, 0, 0]
        assert (ranges.starts, ranges.ends) == ([0, 40], [30, 50])
        assert ranges.add(5, 45) == 30 and (ranges.starts, ranges.ends) == ([0], [50])


def test_the_span_check_allows_one_percent():
    assert ref.judge_span(1_010_000, 1_000_000)["pass"] is True
    assert ref.judge_span(1_011_000, 1_000_000)["pass"] is False
    assert ref.judge_span(0, 0)["pass"] is True


def _filter(pref, handle, cookie, nbytes, **keys):
    return {"protocol": "all", "pref": pref, "kind": "flower", "chain": 0,
            "options": {"handle": handle, "keys": keys, "actions": [
                {"kind": "gact", "cookie": cookie, "stats": {"bytes": nbytes, "packets": 1}}]}}  # fmt: skip


def test_watch_bytes_reads_the_raw_counters_of_the_macs_own_watch():
    mac, other = "bc:89:c1:e1:8a:d6", "02:4e:54:00:00:01"
    dump = [
        {"protocol": "all", "pref": 49152, "kind": "flower", "chain": 0},
        _filter(49152, 1, cookie_for(0, 3), 111, dst_mac=other),
        _filter(49152, 2, cookie_for(1, 4), 222_000, dst_mac=mac),
        _filter(49153, 1, cookie_for(0, 3), 333, src_mac=other),
        _filter(49153, 2, cookie_for(1, 4), 4_440, src_mac=mac.upper()),
        _filter(49153, 3, "deadbeef", 999, src_mac=mac),  # someone else's filter
    ]
    got = ref.watch_bytes(json.dumps(dump), mac)
    assert (got["down"], got["up"]) == (222_000, 4_440)
    assert got["down_cookie"] == got["up_cookie"] == cookie_for(1, 4)
    with pytest.raises(ValueError, match="no single down counter"):
        ref.watch_bytes(json.dumps(dump[3:]), mac)
