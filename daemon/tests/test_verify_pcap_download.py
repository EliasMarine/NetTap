"""NET-189: the device check for PCAP Search's download (scripts/remote/verify_pcap_download.py)."""

import importlib.util
from decimal import Decimal
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "remote"
    / "verify_pcap_download.py"
)
_spec = importlib.util.spec_from_file_location("verify_pcap_download", _PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def _row(name, first, last, packets=100_000, state="indexed"):
    return {
        "name": name,
        "first": first,
        "last": last,
        "packets": packets,
        "state": state,
    }


def test_bounds_are_sent_as_the_browser_sends_them():
    # new Date(...).toISOString(): whole milliseconds and Z, which the daemon reads as UTC
    assert check.iso(Decimal("1794502800.1239")) == "2026-11-12T17:00:00.123Z"
    assert check.iso(Decimal(1794502800)) == "2026-11-12T17:00:00.000Z"


def test_the_window_straddles_the_start_of_the_second_newest_file():
    rows = [
        _row("c", "1000.5", "1040.0"),  # newest, may still be written
        _row("b", "960.25", "1000.4"),
        _row("a", "920.0", "960.2"),
        _row("x", "0", "0", state="failed"),
    ]
    start, end, b_first, over = check.pick_window(rows)
    assert (start, end, b_first) == (
        Decimal("958.25"),
        Decimal("962.25"),
        Decimal("960.25"),
    )
    assert [r["name"] for r in over] == ["b", "a"]


def test_a_pair_over_the_budget_is_skipped_for_an_older_one():
    rows = [
        _row("d", "1040", "1080"),
        _row("c", "1000", "1040", packets=300_000),
        _row("b", "960", "1000", packets=200_000),
        _row("a", "920", "960", packets=50_000),
    ]
    _, _, b_first, over = check.pick_window(rows)
    assert b_first == Decimal(960) and [r["name"] for r in over] == ["b", "a"]
    assert check.pick_window(rows[:2]) is None  # no neighbour: no window


def test_capinfos_table_is_read_by_position():
    text = (
        'Running as user "root"\n'
        "File name\tFile encapsulation\tNumber of packets\tStart time\tEnd time\n"
        "-\tEthernet\t1234\t1794502790.250000000\t1794502809.990000000\n"
    )
    assert check.parse_capinfos(text) == (
        1234,
        Decimal("1794502790.250000000"),
        Decimal("1794502809.990000000"),
    )
    assert check.parse_capinfos("capinfos: The file isn't a capture file\n") is None


def test_a_busy_reader_is_waited_out(monkeypatch):
    # the busy check's download may still be stopping when the next one starts
    replies = iter(
        [
            type("R", (), {"status": s, "read": lambda self, n=0: b"busy"})()
            for s in (503, 503, 200)
        ]
    )
    monkeypatch.setattr(check, "request", lambda path: next(replies))
    monkeypatch.setattr(check, "BUSY_WAIT_S", 0)
    assert check.request_when_free("/api/pcap/download").status == 200
