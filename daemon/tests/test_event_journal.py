"""The event journal: the commit point for notification events (NET-319)."""

import json
import os
import stat
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services.event_journal import EventJournal, event_id

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_append_writes_one_line_with_seq_and_stable_id(tmp_path):
    path = tmp_path / "events.jsonl"
    journal = EventJournal(str(path))
    entry = journal.append(
        "new_device",
        "aa:bb",
        "2026-11-18T10:00:00+00:00",
        {"ip": "10.0.0.5"},
        instance="",
    )
    assert entry["seq"] == 1
    assert entry["id"] == event_id("new_device", "aa:bb", "")
    assert _lines(path) == [entry]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_same_event_twice_is_written_once_even_after_restart(tmp_path):
    path = tmp_path / "events.jsonl"
    journal = EventJournal(str(path))
    assert journal.append("new_device", "aa:bb", "t1", {}, instance="")
    assert journal.append("new_device", "aa:bb", "t2", {}, instance="") is None
    again = EventJournal(str(path))
    assert again.append("new_device", "aa:bb", "t3", {}, instance="") is None
    assert len(_lines(path)) == 1


def test_instance_defaults_to_observed_at(tmp_path):
    journal = EventJournal(str(tmp_path / "e.jsonl"))
    assert journal.append("device_offline", "aa", "t1", {})
    assert journal.append("device_offline", "aa", "t2", {})  # a new transition
    assert journal.append("device_offline", "aa", "t1", {}) is None


def test_seq_continues_after_restart(tmp_path):
    path = tmp_path / "e.jsonl"
    journal = EventJournal(str(path))
    journal.append("new_device", "a", "t", {}, instance="")
    journal.append("new_device", "b", "t", {}, instance="")
    again = EventJournal(str(path))
    assert again.existed_at_start
    assert again.append("new_device", "c", "t", {}, instance="")["seq"] == 3


def test_first_start_is_recognised(tmp_path):
    assert not EventJournal(str(tmp_path / "e.jsonl")).existed_at_start


def test_torn_tail_is_cut_at_load_before_the_next_append(tmp_path):
    path = tmp_path / "e.jsonl"
    EventJournal(str(path)).append("new_device", "a", "t", {}, instance="")
    with open(path, "ab") as f:
        f.write(b'{"seq":2,"id":"x","ty')  # a crash mid-append
    journal = EventJournal(str(path))
    entry = journal.append("new_device", "b", "t", {}, instance="")
    assert entry["seq"] == 2
    assert [e["key"] for e in _lines(path)] == ["a", "b"]


def test_unreadable_middle_line_is_skipped(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text(
        '{"seq":1,"id":"a","type":"new_device","key":"a","recorded_at":"x","data":{}}\n'
        "not json\n"
        '{"seq":2,"id":"b","type":"new_device","key":"b","recorded_at":"x","data":{}}\n'
    )
    journal = EventJournal(str(path))
    assert [e["seq"] for e in journal.after(0, 10)] == [1, 2]
    assert journal.last_seq == 2


def test_failed_write_leaves_the_file_as_it_was(tmp_path):
    path = tmp_path / "e.jsonl"
    journal = EventJournal(str(path))
    journal.append("new_device", "a", "t", {}, instance="")
    before = path.read_bytes()
    real_write = os.write

    def half_then_fail(fd, data):
        real_write(fd, bytes(data[:10]))
        raise OSError(28, "No space left on device")

    with patch("services.event_journal.os.write", side_effect=half_then_fail):
        with pytest.raises(OSError):
            journal.append("new_device", "b", "t", {}, instance="")
    assert path.read_bytes() == before
    # nothing was recorded, so the retry writes it with the next seq
    assert journal.append("new_device", "b", "t", {}, instance="")["seq"] == 2
    assert [e["key"] for e in _lines(path)] == ["a", "b"]


def test_after_serves_the_window_and_pages_older_backlog_from_disk(tmp_path):
    path = tmp_path / "e.jsonl"
    journal = EventJournal(str(path), window=100)
    for i in range(1500):
        journal.append("new_device", f"m{i}", "t", {}, instance="")
    assert [e["seq"] for e in journal.after(1450, 10)] == list(range(1451, 1461))
    # 1,500 unread with only 100 in memory: read from the file, nothing skipped
    page = journal.after(0, 200)
    assert [e["seq"] for e in page] == list(range(1, 201))
    assert journal.after(1500, 10) == []


# NET-339: `types` overrides a line's type by seq (default new_device)
def _old_and_new(
    path, ages_days: list[int], types: dict[int, str] | None = None
) -> None:
    lines = []
    for i, age in enumerate(ages_days, start=1):
        at = (NOW - timedelta(days=age)).isoformat()
        lines.append(
            json.dumps(
                {
                    "seq": i,
                    "id": f"id{i}",
                    "type": (types or {}).get(i, "new_device"),
                    "key": f"k{i}",
                    "recorded_at": at,
                    "data": {},
                }
            )
        )
    path.write_text("\n".join(lines) + "\n")


def test_compaction_drops_old_lines_but_keeps_unread_and_newest(tmp_path):
    path = tmp_path / "e.jsonl"
    _old_and_new(path, [200, 150, 130, 10, 5])
    journal = EventJournal(str(path))
    # the dispatcher has taken up to seq 1: seqs 2 and 3 are old but unread
    assert journal.compact(NOW, keep_from_seq=1) == 1
    assert [e["seq"] for e in _lines(path)] == [2, 3, 4, 5]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_compaction_never_loses_the_seq_high_water_mark(tmp_path):
    path = tmp_path / "e.jsonl"
    _old_and_new(path, [300, 250, 200])
    journal = EventJournal(str(path))
    journal.compact(NOW, keep_from_seq=3)  # all taken and all old
    assert [e["seq"] for e in _lines(path)] == [3]
    again = EventJournal(str(path))
    assert again.append("new_device", "new", "t", {}, instance="")["seq"] == 4
    assert [e["seq"] for e in again.after(3, 10)] == [4]


def test_compaction_caps_lines(tmp_path):
    path = tmp_path / "e.jsonl"
    _old_and_new(path, [1] * 10)
    journal = EventJournal(str(path), max_lines=4)
    journal.compact(NOW, keep_from_seq=10)
    assert [e["seq"] for e in _lines(path)] == [7, 8, 9, 10]


def test_compaction_keeps_recent_data_cap_lines_past_the_line_cap(tmp_path):
    """NET-339: a data cap line is the once-a-month record, so only its age drops it."""
    path = tmp_path / "e.jsonl"
    # 63 days is past CAP_KEEP but inside KEEP_DAYS: the line cap alone decides it
    _old_and_new(
        path,
        [200, 63, 61, 30, 30, 1, 1, 1, 1, 1],
        types={1: "data_cap", 2: "data_cap", 3: "data_cap", 4: "data_cap"},
    )
    journal = EventJournal(str(path), max_lines=3)
    journal.compact(NOW, keep_from_seq=10)
    # 3 and 4 outlive the 3-line cap; 1 and 2 are too old; the other old lines go as before
    assert [e["seq"] for e in _lines(path)] == [3, 4, 8, 9, 10]


def test_compaction_without_a_saved_cursor_keeps_everything(tmp_path):
    path = tmp_path / "e.jsonl"
    _old_and_new(path, [300, 200])
    assert EventJournal(str(path)).compact(NOW, keep_from_seq=None) == 0
    assert len(_lines(path)) == 2


def test_compaction_racing_appends_loses_nothing(tmp_path):
    path = tmp_path / "e.jsonl"
    _old_and_new(path, [300] * 50)
    journal = EventJournal(str(path))
    errors: list[BaseException] = []

    def writer(prefix: str) -> None:
        try:
            for i in range(100):
                journal.append("new_device", f"{prefix}{i}", "t", {}, instance="")
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    def compactor() -> None:
        try:
            for _ in range(30):
                journal.compact(datetime.now(timezone.utc), keep_from_seq=50)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(p,)) for p in "ab"]
    threads.append(threading.Thread(target=compactor))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    keys = {e["key"] for e in _lines(path)}
    assert {f"a{i}" for i in range(100)} <= keys
    assert {f"b{i}" for i in range(100)} <= keys
    seqs = [e["seq"] for e in _lines(path)]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))


# --- F5 (NET-331, round 4 #9): an unreadable journal is unavailable, never empty -------------


def _unreadable(path) -> None:
    """Reading the journal now fails with IsADirectoryError, an OSError that isn't "missing"."""
    path.rename(path.with_suffix(".bak"))
    path.mkdir()


def _readable_again(path) -> None:
    path.rmdir()
    path.with_suffix(".bak").rename(path)


def test_an_unreadable_journal_is_unavailable_until_its_load_works(tmp_path):
    path = tmp_path / "e.jsonl"
    first = EventJournal(str(path))
    for key in "abc":
        first.append("new_device", key, "t", {}, instance="")
    _unreadable(path)
    journal = EventJournal(str(path))
    assert not journal.available
    with pytest.raises(OSError):
        journal.append("device_offline", "AA", "t", {}, instance="down|t")
    with pytest.raises(OSError):
        journal.after(0, 10)
    assert journal.reload() is False
    _readable_again(path)
    # the append loads it first: seq 4 after the existing three, never 1 over them
    assert (
        journal.append("device_offline", "AA", "t", {}, instance="down|t")["seq"] == 4
    )
    assert journal.available
    assert journal.append("new_device", "a", "t", {}, instance="") is None  # ids known
    assert [e["seq"] for e in journal.after(0, 10)] == [1, 2, 3, 4]
    assert [e["seq"] for e in _lines(path)] == [1, 2, 3, 4]


def test_reload_recovers_an_unreadable_journal_without_an_append(tmp_path):
    path = tmp_path / "e.jsonl"
    EventJournal(str(path)).append("new_device", "a", "t", {}, instance="")
    _unreadable(path)
    journal = EventJournal(str(path))
    assert (journal.available, journal.last_seq) == (False, 0)
    _readable_again(path)
    assert journal.reload() is True
    assert journal.last_seq == 1
    assert [e["key"] for e in journal.after(0, 10)] == ["a"]
    assert journal.reload() is True  # a no-op once loaded


def test_a_torn_tail_that_cannot_be_cut_leaves_it_unavailable(tmp_path):
    path = tmp_path / "e.jsonl"
    EventJournal(str(path)).append("new_device", "a", "t", {}, instance="")
    with open(path, "ab") as f:
        f.write(b'{"seq":2,"id":"x","ty')
    denied = PermissionError(13, "Permission denied")
    with patch("services.event_journal.open", side_effect=denied, create=True):
        journal = EventJournal(str(path))  # no crash at start-up
    assert not journal.available
    # once the file can be cut, the next append does it and continues the numbering
    assert journal.append("new_device", "b", "t", {}, instance="")["seq"] == 2
    assert [e["key"] for e in _lines(path)] == ["a", "b"]


def test_an_unreadable_journal_logs_one_error_not_one_per_retry(tmp_path, caplog):
    path = tmp_path / "e.jsonl"
    EventJournal(str(path)).append("new_device", "a", "t", {}, instance="")
    _unreadable(path)
    with caplog.at_level("DEBUG", logger="nettap.services.event_journal"):
        journal = EventJournal(str(path))
        assert journal.reload() is False  # a dispatcher poll's retry
        with pytest.raises(OSError):
            journal.append(
                "new_device", "b", "t", {}, instance=""
            )  # a producer's retry
    levels = [r.levelname for r in caplog.records if "unreadable" in r.getMessage()]
    assert levels == ["ERROR", "DEBUG", "DEBUG"]
