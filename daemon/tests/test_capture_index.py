"""The capture index: which files hold a window's packets (NET-188)."""

import asyncio
import json
import os
from decimal import Decimal

import pytest

from services import capture_index as ci
from services.capture_index import (
    CaptureIndex,
    IndexEntry,
    StillIndexing,
    epoch_iso,
    parse_capinfos,
    parse_capinfos_batch,
    scan_captures,
)
from services.container_exec import ExecResult

HEADER = "File name\tFile encapsulation\tNumber of packets\tStart time\tEnd time"


def table(path, first, last, packets=10, encap="ether"):
    return f"{HEADER}\n{path}\t{encap}\t{packets}\t{first}\t{last}"


class TestParseCapinfos:
    def test_normal(self):
        e = parse_capinfos(table("/pcap/a.pcap", "100.5", "130.25"), 0, 9, 1)
        assert (e.state, e.first, e.last, e.packets, e.encapsulation) == (
            "indexed",
            "100.5",
            "130.25",
            10,
            "ether",
        )

    def test_cut_short_keeps_its_complete_packets(self):
        text = (
            'capinfos: An error occurred after reading 677 packets from "/pcap/a.pcap".\n'
            'capinfos: The file "/pcap/a.pcap" appears to have been cut short in the '
            "middle of a packet.\n  (will continue anyway, checksums might be incorrect)\n"
            + table("/pcap/a.pcap", "1794025874.991223", "1794025875.010428", 677)
        )
        e = parse_capinfos(text, 1, 9, 1)
        assert e.state == "indexed" and e.cut_short and e.packets == 677

    def test_unreadable_file_fails_with_capinfos_message(self):
        e = parse_capinfos(
            'capinfos: The file "/pcap/a.pcap" isn\'t a capture file in a format '
            "TShark understands.",
            2,
            9,
            1,
        )
        assert e.state == "failed" and "isn't a capture file" in e.error

    def test_empty_file_has_no_times(self):
        e = parse_capinfos(table("/pcap/a.pcap", "n/a", "n/a", 0), 0, 24, 1)
        assert e.state == "indexed" and e.first is None
        assert not e.overlaps(Decimal(0), Decimal(10**12))

    def test_tab_in_file_name(self):
        e = parse_capinfos(table("/pcap/a\tb.pcap", "1", "2"), 0, 9, 1)
        assert (e.first, e.last) == ("1", "2")

    def test_batch_split(self):
        out = (
            "#nt-file 0\n" + table("/pcap/a", "1", "2") + "\n#nt-rc 0\n"
            "#nt-file 1\ncapinfos: broken\n#nt-rc 2\n"
            "#nt-file 2\n"  # the batch was stopped here
        )
        parsed = parse_capinfos_batch(out)
        assert set(parsed) == {0, 1} and parsed[1] == (2, "capinfos: broken")


class TestOverlap:
    e = IndexEntry(1, 1, "indexed", "100", "200", 5, "ether")

    @pytest.mark.parametrize(
        ("start", "end", "hit"),
        [
            ("50", "100", False),  # `to` is exclusive
            ("50", "100.000001", True),
            ("200", "300", True),  # exactly at the last packet
            ("200.000001", "300", False),
            ("120", "130", True),  # inside one file
        ],
    )
    def test_bounds(self, start, end, hit):
        assert self.e.overlaps(Decimal(start), Decimal(end)) is hit

    def test_failed_never_overlaps(self):
        failed = IndexEntry(1, 1, "failed", error="x")
        assert not failed.overlaps(Decimal(0), Decimal(10**12))


def test_scan_skips_links_and_other_files(tmp_path):
    (tmp_path / "a.pcap").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.PCAPNG").write_bytes(b"xy")
    (tmp_path / "notes.txt").write_text("no")
    os.symlink(tmp_path / "a.pcap", tmp_path / "link.pcap")
    ids = sorted(f.id for f in scan_captures(str(tmp_path)))
    assert ids == ["a.pcap", "sub/b.PCAPNG"]


def test_epoch_iso_keeps_microseconds():
    assert epoch_iso("1700000000.000001") == "2023-11-14T22:13:20.000001Z"


# --- select(): with capinfos replaced by a table per file name -----------------


@pytest.fixture
def capinfos(monkeypatch):
    """{file name: (rc, output)}; files missing from it are left unread."""
    answers: dict[str, tuple[int, str]] = {}
    calls: list[list[str]] = []

    async def fake_run(job, args, **_kw):
        calls.append(list(args))
        out = []
        for i, path in enumerate(args):
            name = path.rsplit("/", 1)[-1]
            if name in answers:
                rc, text = answers[name]
                out.append(f"#nt-file {i}\n{text}\n#nt-rc {rc}")
        return ExecResult("\n".join(out).encode() + b"\n", "", {}, 0, False, 1, 0.1)

    monkeypatch.setattr(ci, "run_in_tshark", fake_run)
    monkeypatch.setattr(ci, "TIME_FLOOR", 0)  # these tests use tiny epoch times
    return answers, calls


def make(tmp_path, name, size=10, mtime=1_000):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    os.utime(p, (mtime, mtime))
    return p


def index_for(tmp_path):
    return CaptureIndex(
        str(tmp_path), str(tmp_path / "index.json"), asyncio.Semaphore(2)
    )


@pytest.mark.asyncio
async def test_failed_files_are_reported_on_every_window(tmp_path, capinfos):
    answers, _ = capinfos
    make(tmp_path, "good.pcap")
    answers["good.pcap"] = (0, table("/pcap/good.pcap", "100", "200"))
    for i in range(4):
        make(tmp_path, f"bad{i}.pcap")
        answers[f"bad{i}.pcap"] = (2, "capinfos: The file isn't a capture file")
    idx = index_for(tmp_path)
    sel = await idx.select(Decimal("150"), Decimal("160"))
    assert [f.id for f, _ in sel.files] == ["good.pcap"]
    assert sorted(f.id for f, _ in sel.failed) == [f"bad{i}.pcap" for i in range(4)]
    # a window nowhere near them still names them: their packet times are unknown
    sel = await idx.select(Decimal("5000"), Decimal("5010"))
    assert sel.files == [] and len(sel.failed) == 4


@pytest.mark.asyncio
async def test_failed_file_with_recent_mtime_still_counts_for_old_windows(
    tmp_path, capinfos
):
    answers, _ = capinfos
    make(tmp_path, "old.pcap", mtime=1_000)
    make(
        tmp_path, "copied-in.pcap", mtime=2_000_000_000
    )  # historical packets, new mtime
    answers["old.pcap"] = (0, table("/pcap/old.pcap", "100", "200"))
    answers["copied-in.pcap"] = (2, "capinfos: unreadable")
    sel = await index_for(tmp_path).select(Decimal("100"), Decimal("110"))
    assert [f.id for f, _ in sel.failed] == ["copied-in.pcap"]


@pytest.mark.asyncio
async def test_clock_jump_inside_a_file_uses_its_real_bounds(tmp_path, capinfos):
    answers, _ = capinfos
    make(tmp_path, "jump.pcap")
    # packets 100, 200, then 130: capinfos reports the earliest and latest
    answers["jump.pcap"] = (0, table("/pcap/jump.pcap", "100", "200"))
    sel = await index_for(tmp_path).select(Decimal("130"), Decimal("131"))
    assert [f.id for f, _ in sel.files] == ["jump.pcap"]


@pytest.mark.asyncio
async def test_clock_rollback_later_file_named_earlier(tmp_path, capinfos):
    answers, _ = capinfos
    make(tmp_path, "cap_2000.pcap", mtime=2_000)
    make(tmp_path, "cap_1000.pcap", mtime=3_000)  # written later, with an earlier clock
    answers["cap_2000.pcap"] = (0, table("/pcap/cap_2000.pcap", "2000", "2100"))
    answers["cap_1000.pcap"] = (0, table("/pcap/cap_1000.pcap", "1000", "1100"))
    sel = await index_for(tmp_path).select(Decimal("1050"), Decimal("1060"))
    assert [f.id for f, _ in sel.files] == ["cap_1000.pcap"]


@pytest.mark.asyncio
async def test_overlapping_files_from_two_interfaces(tmp_path, capinfos):
    answers, _ = capinfos
    for name in ("eth0_1.pcap", "eth1_1.pcap"):
        make(tmp_path, name)
        answers[name] = (0, table(f"/pcap/{name}", "100", "200"))
    sel = await index_for(tmp_path).select(Decimal("150"), Decimal("151"))
    assert [f.id for f, _ in sel.files] == ["eth0_1.pcap", "eth1_1.pcap"]


@pytest.mark.asyncio
async def test_replaced_file_is_indexed_again(tmp_path, capinfos):
    answers, calls = capinfos
    make(tmp_path, "a.pcap", size=10)
    answers["a.pcap"] = (2, "capinfos: broken")
    idx = index_for(tmp_path)
    assert len((await idx.select(Decimal(0), Decimal(1))).failed) == 1
    make(tmp_path, "a.pcap", size=20)
    answers["a.pcap"] = (0, table("/pcap/a.pcap", "0", "5"))
    sel = await idx.select(Decimal(0), Decimal(1))
    assert sel.failed == [] and len(sel.files) == 1 and len(calls) == 2


@pytest.mark.asyncio
async def test_too_many_unindexed_files_is_busy(tmp_path, capinfos):
    for i in range(ci.INLINE_INDEX_LIMIT + 1):
        make(tmp_path, f"f{i}.pcap")
    with pytest.raises(StillIndexing) as err:
        await index_for(tmp_path).select(Decimal(0), Decimal(1))
    assert err.value.pending == ci.INLINE_INDEX_LIMIT + 1


@pytest.mark.asyncio
async def test_a_file_the_batch_never_reached_is_not_guessed(tmp_path, capinfos):
    make(tmp_path, "a.pcap")  # no answer: capinfos never got to it
    with pytest.raises(StillIndexing):
        await index_for(tmp_path).select(Decimal(0), Decimal(1))


@pytest.mark.asyncio
async def test_index_survives_a_restart_and_drops_deleted_files(tmp_path, capinfos):
    answers, calls = capinfos
    make(tmp_path, "a.pcap")
    make(tmp_path, "b.pcap")
    answers["a.pcap"] = (0, table("/pcap/a.pcap", "1", "2"))
    answers["b.pcap"] = (0, table("/pcap/b.pcap", "3", "4"))
    await index_for(tmp_path).select(Decimal(0), Decimal(1))
    (tmp_path / "b.pcap").unlink()
    again = index_for(tmp_path)
    sel = await again.select(Decimal(0), Decimal(10))
    assert [f.id for f, _ in sel.files] == ["a.pcap"] and len(calls) == 1
    saved = json.loads((tmp_path / "index.json").read_text())
    assert set(saved["entries"]) == {"a.pcap", "b.pcap"}  # pruned on the next save
    await again._index_pass()
    assert set(json.loads((tmp_path / "index.json").read_text())["entries"]) == {
        "a.pcap"
    }


def test_corrupt_index_file_starts_again(tmp_path):
    (tmp_path / "index.json").write_text("{not json")
    assert index_for(tmp_path).entry("a.pcap") is None


def test_capinfos_timeout_fails_the_file_instead_of_leaving_it_pending():
    e = parse_capinfos("", 124, 9, 1)  # GNU timeout stopped it
    assert e.state == "failed"
    assert e.error == f"capinfos took longer than {ci.CAPINFOS_SECONDS} s"
    # --foreground: plain timeout moves capinfos out of the job's process group,
    # where the deadline's and the daemon's group kills can't reach it
    assert 'timeout --foreground "$CAPINFOS_SECONDS" capinfos' in ci._CAPINFOS_JOB


def test_a_failed_save_stays_dirty_for_the_shutdown_flush(tmp_path):
    idx = CaptureIndex(
        str(tmp_path), str(tmp_path / "missing" / "index.json"), asyncio.Semaphore(2)
    )
    idx._dirty = True
    idx._save(set())
    assert idx._dirty


@pytest.mark.asyncio
async def test_a_file_indexed_while_waiting_for_the_lock_is_not_read_again(
    tmp_path, capinfos
):
    answers, calls = capinfos
    make(tmp_path, "a.pcap")
    answers["a.pcap"] = (0, table("/pcap/a.pcap", "1", "2"))
    idx = index_for(tmp_path)
    [f] = scan_captures(str(tmp_path))
    await idx.index_files([f])
    await idx.index_files([f])  # e.g. a search that waited behind the background pass
    assert len(calls) == 1


def test_index_from_an_older_format_starts_again(tmp_path):
    entry = {"size": 10, "mtime_ns": "1", "state": "indexed", "first": "0.000000"}
    (tmp_path / "index.json").write_text(
        json.dumps({"version": 1, "entries": {"a.pcap": entry}})
    )
    assert index_for(tmp_path).entry("a.pcap") is None


CRASHED = (
    'capinfos: The file "/pcap/crash.pcap" appears to have been cut short in the '
    "middle of a packet.\n"
    + table("/pcap/crash.pcap", "0.000000", "1794019342.449881", 94282)
)


def floor_fake(monkeypatch, floor_result):
    """The batch sees a crash's zeroed tail (first packet 1970); the re-read answers."""
    jobs: list[tuple[str, list[str]]] = []

    async def fake_run(job, args, **_kw):
        jobs.append((job, list(args)))
        if job == ci._FLOOR_JOB:
            return floor_result
        out = f"#nt-file 0\n{CRASHED}\n#nt-rc 1\n".encode()
        return ExecResult(out, "", {}, 0, False, 1, 0.1)

    monkeypatch.setattr(ci, "run_in_tshark", fake_run)
    return jobs


@pytest.mark.asyncio
async def test_zeroed_tail_after_a_crash_is_left_out(tmp_path, monkeypatch, caplog):
    real = table("-", "1794019107.174686", "1794019342.449881", 94208)
    jobs = floor_fake(
        monkeypatch,
        ExecResult(
            real.encode(),
            CRASHED.splitlines()[0],
            {"editcap": 0, "capinfos": 0},
            0,
            False,
            1,
            0.1,
        ),
    )
    make(tmp_path, "crash.pcap")
    idx = index_for(tmp_path)
    sel = await idx.select(Decimal("1794019100"), Decimal("1794019200"))
    assert [f.id for f, _ in sel.files] == ["crash.pcap"]
    e = idx.entry("crash.pcap")
    assert (e.state, e.first, e.last, e.packets, e.cut_short) == (
        "indexed",
        "1794019107.174686",
        "1794019342.449881",
        94208,
        True,
    )
    assert jobs[1] == (ci._FLOOR_JOB, ["946684800", "/pcap/crash.pcap"])
    assert "left out 74 records stamped before 2000" in caplog.text
    # an older window no longer reads it, and the summary no longer says 1970
    assert (await idx.select(Decimal("1000"), Decimal("2000"))).files == []
    assert idx.summary()["oldest_packet"] == "1794019107.174686"


REAL = table("-", "1794019107.174686", "1794019200.000000", 50000)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stdout", "stderr", "statuses"),
    [
        (b"", "editcap: Can't open", {"editcap": 1, "capinfos": 0}),
        # editcap 4.0.17 exits 0 on a damaged file too; only its message says so
        (
            REAL.encode(),
            'editcap: The file "/pcap/crash.pcap" appears to be damaged or corrupt.',
            {"editcap": 0, "capinfos": 0},
        ),
    ],
)
async def test_failed_reread_marks_the_file_failed(
    tmp_path, monkeypatch, stdout, stderr, statuses
):
    floor_fake(monkeypatch, ExecResult(stdout, stderr, statuses, 0, False, 1, 0.1))
    make(tmp_path, "crash.pcap")
    idx = index_for(tmp_path)
    sel = await idx.select(Decimal("1794019100"), Decimal("1794019200"))
    e = idx.entry("crash.pcap")
    assert e.state == "failed" and "reading past them failed" in e.error
    assert [f.id for f, _ in sel.failed] == ["crash.pcap"]  # every search names it


@pytest.mark.asyncio
async def test_background_pass_leaves_files_being_written(tmp_path, capinfos):
    answers, calls = capinfos
    import time

    make(tmp_path, "old.pcap", mtime=1_000)
    live = make(tmp_path, "live.pcap")
    os.utime(live, None)  # written just now
    answers["old.pcap"] = (0, table("/pcap/old.pcap", "1", "2"))
    await index_for(tmp_path)._index_pass()
    assert calls == [["/pcap/old.pcap"]]
    assert time.time() - live.stat().st_mtime < ci.SETTLE_SECONDS


@pytest.mark.asyncio
async def test_summary_counts(tmp_path, capinfos):
    answers, _ = capinfos
    make(tmp_path, "a.pcap", size=5)
    make(tmp_path, "b.pcap", size=7)
    answers["a.pcap"] = (0, table("/pcap/a.pcap", "100.5", "200"))
    idx = index_for(tmp_path)
    with pytest.raises(StillIndexing):  # b.pcap never answers
        await idx.select(Decimal(0), Decimal(1))
    s = idx.summary()
    assert (s["count"], s["bytes_total"], s["unindexed"], s["oldest_packet"]) == (
        2,
        12,
        1,
        "100.5",
    )
    by_id = {r["id"]: r for r in s["files"]}
    assert by_id["a.pcap"]["first"] == "100.5" and by_id["b.pcap"]["state"] == "pending"


@pytest.mark.asyncio
async def test_saves_are_coalesced_and_flushed_on_shutdown(
    tmp_path, capinfos, monkeypatch
):
    answers, _ = capinfos
    writes = []
    idx = index_for(tmp_path)
    real_save = idx._save
    monkeypatch.setattr(
        idx, "_save", lambda present: (writes.append(1), real_save(present))
    )
    for i in range(3):
        make(tmp_path, f"f{i}.pcap")
        answers[f"f{i}.pcap"] = (0, table(f"/pcap/f{i}.pcap", "1", "2"))
        await idx.select(Decimal(0), Decimal(1))
    assert len(writes) == 1  # the first save, then nothing within SAVE_SECONDS
    monkeypatch.setattr(ci, "POLL_SECONDS", 0)
    task = asyncio.create_task(idx.run_forever())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(writes) == 2
    saved = json.loads((tmp_path / "index.json").read_text())["entries"]
    assert set(saved) == {"f0.pcap", "f1.pcap", "f2.pcap"}
