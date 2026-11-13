"""Packet analysis service (NET-188): how each job's ending is classified.

The jobs' outputs are the ones recorded on the G11 (tests/fixtures/packets); the
container is replaced by a fake that returns them.
"""

import asyncio
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from services import packet_search as ps
from services.capture_index import CaptureIndex, IndexEntry
from services.container_exec import ExecResult
from services.packet_manifest import PacketError
from services.packet_parse import ALL_FIELDS

FIX = Path(__file__).parent / "fixtures" / "packets"
ALL_ZERO = {"mergecap": 0, "editcap": 0, "tshark": 0, "head": 0}


def result(stdout=b"", statuses=None, stderr="", deadline=False):
    return ExecResult(stdout, stderr, statuses or {}, 0, deadline, 42, 0.5)


def rows_text(n_rows: int) -> bytes:
    lines = []
    for i in range(1, n_rows + 1):
        cols = [str(i), f"1700000000.{i:06d}", "60", "60", f"{i:032x}"]
        cols += [""] * (len(ALL_FIELDS) - 7) + ["TCP", f"row {i}"]
        lines.append("\t".join(cols))
    return ("\n".join(lines) + "\n").encode() if lines else b""


class FakeContainer:
    """Answers each job; records the arguments it was given."""

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []
        self.check = result(statuses={"tshark": 0})
        self.search = result((FIX / "search_all.out").read_bytes(), ALL_ZERO)
        self.detail = result(
            (FIX / "detail_1.out").read_bytes(),
            {f"{s}{i}": 0 for s in ("mergecap", "editcap", "tshark") for i in (1, 2)},
        )
        self.download = (FIX / "download_125.out").read_bytes()
        self.download_statuses = {"mergecap": 0, "editcap": 0, "tshark": 0}
        self.fields = result(
            (FIX / "fields_tls.out").read_bytes(), {"tshark": 0, "awk": 0}
        )

    async def run(self, job, args, *, deadline_s, max_stdout, sink=None, **_kw):
        self.calls.append((job, list(args)))
        if job == ps.CHECK_JOB:
            return self.check
        if job == ps.SEARCH_JOB:
            return self.search
        if job == ps.DETAIL_JOB:
            return self.detail
        if job == ps.FIELDS_JOB:
            return self.fields
        if job == ps.DOWNLOAD_JOB:
            for i in range(0, len(self.download), 50):
                await sink(self.download[i : i + 50])
            return result(b"", self.download_statuses)
        raise AssertionError("unknown job")


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = FakeContainer()
    monkeypatch.setattr(ps, "run_in_tshark", fake.run)
    (tmp_path / "a.pcap").write_bytes(b"x" * 575)
    os.utime(tmp_path / "a.pcap", (1000, 1000))
    slot = asyncio.Semaphore(2)
    index = CaptureIndex(str(tmp_path), str(tmp_path / "idx.json"), slot)
    st = (tmp_path / "a.pcap").stat()
    index._entries["a.pcap"] = IndexEntry(
        st.st_size,
        st.st_mtime_ns,
        "indexed",
        "1700000000.000001",
        "1700000001.000001",
        6,
        "ether",
    )

    async def version():
        return "TShark (Wireshark) 4.0.17"

    svc = ps.PacketSearchService(str(tmp_path), index, slot, version)
    return svc, fake, tmp_path, index


BODY = {"filter": "", "from": "1700000000", "to": "1700000002", "limit": 100}


@pytest.mark.asyncio
async def test_whole_window_read_is_complete(env):
    svc, fake, *_ = env
    out = await svc.search(BODY)
    assert (out["termination"], out["complete"], out["provisional"]) == (
        "eof",
        True,
        False,
    )
    assert len(out["rows"]) == 6 and out["filter"] == "frame"
    assert out["manifest"]["files"] == [
        {
            "id": "a.pcap",
            "size": 575,
            "mtime_ns": out["manifest"]["files"][0]["mtime_ns"],
            "recent": False,
        }
    ]
    assert [f["n"] for f in out["manifest"]["frames"]] == [1, 2, 3, 4, 5, 6]
    assert out["window"]["effective"] == {
        "from": "1700000000.000000000",
        "to": "1700000002.000000000",
    }
    job, args = fake.calls[-1]
    assert args[:4] == ["1700000000.000000000", "1700000002.000000000", "frame", "101"]
    assert args[4:] == ["/pcap/a.pcap"]


@pytest.mark.asyncio
async def test_limit_row_means_more_exist(env):
    svc, fake, *_ = env
    fake.search = result(
        rows_text(101), {"head": 0, "tshark": 2, "editcap": 141, "mergecap": 141}
    )
    out = await svc.search(BODY)
    assert (
        out["termination"] == "limit"
        and not out["complete"]
        and len(out["rows"]) == 100
    )


@pytest.mark.asyncio
async def test_deadline_without_a_match(env):
    svc, fake, *_ = env
    fake.search = result(b"", {}, "Terminated", deadline=True)
    out = await svc.search(BODY)
    assert out["termination"] == "deadline" and not out["complete"]
    assert "before finding a match; matches may still exist" in out["message"]


@pytest.mark.asyncio
async def test_deadline_after_one_match_keeps_it(env):
    svc, fake, *_ = env
    fake.search = result(rows_text(1) + b"2\t17000", {}, deadline=True)
    out = await svc.search(BODY)
    assert len(out["rows"]) == 1 and out["termination"] == "deadline"
    assert "more may exist" in out["message"]


@pytest.mark.asyncio
async def test_out_of_memory_is_507(env):
    svc, fake, *_ = env
    fake.search = result(rows_text(2), {"tshark": 137, "head": 0})
    with pytest.raises(PacketError) as err:
        await svc.search(BODY)
    assert err.value.status == 507


@pytest.mark.asyncio
async def test_a_stage_that_failed_is_502_never_partial_data(env):
    svc, fake, *_ = env
    fake.search = result(
        rows_text(2), {**ALL_ZERO, "editcap": 2}, "editcap: can't read"
    )
    with pytest.raises(PacketError) as err:
        await svc.search(BODY)
    assert err.value.status == 502 and "editcap" in err.value.detail


@pytest.mark.asyncio
async def test_silent_death_is_502(env):
    svc, fake, *_ = env
    fake.search = result(rows_text(2), {})
    with pytest.raises(PacketError) as err:
        await svc.search(BODY)
    assert err.value.status == 502


def flag_cut_short(index):
    index._entries["a.pcap"] = replace(index._entries["a.pcap"], cut_short=True)


@pytest.mark.asyncio
async def test_a_file_that_may_end_mid_packet_goes_through_editcap(env):
    """TShark 4.0.17's mergecap stops merging EVERY file at a partly written packet
    (exit 2; on the G11 a crashed file hid all of the next file's packets), so such
    a file reaches mergecap through editcap (_CUT), whose stage must report."""
    svc, fake, tmp_path, index = env
    await svc.search(BODY)
    assert fake.calls[-1][1][4:] == ["/pcap/a.pcap"]  # finished and whole: direct
    flag_cut_short(index)
    fake.search = result(
        (FIX / "search_all.out").read_bytes(), {**ALL_ZERO, "pre-0": 0}
    )
    assert (await svc.search(BODY))["termination"] == "eof"
    assert fake.calls[-1][1][4:] == ["cut:/pcap/a.pcap"]
    damaged = 'editcap: The file "/pcap/a.pcap" appears to be damaged or corrupt.'
    for statuses, stderr in (
        (ALL_ZERO, ""),  # the editcap in front never reported
        ({**ALL_ZERO, "pre-0": 1}, ""),
        ({**ALL_ZERO, "pre-0": 0, "mergecap": 2}, ""),  # no cut reaches mergecap now
        ({**ALL_ZERO, "pre-0": 0}, damaged),  # editcap 4.0.17 exits 0 even so
    ):
        fake.search = result(rows_text(1), statuses, stderr)
        with pytest.raises(PacketError) as err:
            await svc.search(BODY)
        assert err.value.status == 502


@pytest.mark.asyncio
async def test_windows_before_2000_are_refused(env):
    """The index leaves out records stamped before 2000 (a crash's zeroed tail), so
    a search there could only answer "complete, nothing found"."""
    svc, *_ = env
    with pytest.raises(PacketError) as err:
        await svc.search({**BODY, "from": "0", "to": "600"})
    assert err.value.status == 400


@pytest.mark.asyncio
async def test_a_file_still_being_written_goes_through_editcap(env):
    svc, fake, tmp_path, index = env
    os.utime(tmp_path / "a.pcap")  # written just now
    index._entries["a.pcap"] = replace(
        index._entries["a.pcap"], mtime_ns=(tmp_path / "a.pcap").stat().st_mtime_ns
    )
    fake.search = result(
        (FIX / "search_all.out").read_bytes(), {**ALL_ZERO, "pre-0": 0}
    )
    await svc.search(BODY)
    assert fake.calls[-1][1][4:] == ["cut:/pcap/a.pcap"]


@pytest.mark.asyncio
async def test_detail_and_download_send_a_cut_short_file_through_editcap(env):
    svc, fake, _, index = env
    flag_cut_short(index)
    fake.search = result(
        (FIX / "search_all.out").read_bytes(), {**ALL_ZERO, "pre-0": 0}
    )
    m = await manifest_of(svc)
    with pytest.raises(PacketError):  # neither pass's editcap reported
        await svc.packet({"manifest": m, "frame": 1})
    fake.detail = result(
        fake.detail.stdout, {**fake.detail.statuses, "pre1-0": 0, "pre2-0": 0}
    )
    assert (await svc.packet({"manifest": m, "frame": 1}))["cap_len"] == 54
    assert fake.calls[-1][1][3:] == ["cut:/pcap/a.pcap"]

    async def write(_chunk):
        pass

    dm = svc.prepare_download(_download_manifest(m))
    with pytest.raises(PacketError):
        await svc.download(dm, write)
    fake.download_statuses = {**fake.download_statuses, "pre-0": 0}
    assert await svc.download(dm, write) == 3
    assert fake.calls[-1][1][4:] == ["cut:/pcap/a.pcap"]


@pytest.mark.asyncio
async def test_hostile_filter_is_one_argument(env):
    svc, fake, *_ = env
    await svc.search({**BODY, "filter": 'x"; rm -rf / #'})
    check, search = fake.calls
    assert check[1] == ['x"; rm -rf / #'] and search[1][2] == 'x"; rm -rf / #'


@pytest.mark.asyncio
async def test_refused_filter_is_400_with_tsharks_words(env):
    svc, fake, *_ = env
    fake.check = result(
        b"", {"tshark": 2}, "tshark: Unexpected end of filter expression."
    )
    with pytest.raises(PacketError) as err:
        await svc.search({**BODY, "filter": "tcp.port =="})
    assert err.value.status == 400 and err.value.message.startswith(
        "tshark: Unexpected"
    )
    assert len(fake.calls) == 1  # never searched


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("over", "words"),
    [
        ({"filter": "a\nb"}, "line breaks"),
        ({"limit": 50}, "100, 250 or 1000"),
        ({"limit": 100.0}, "100, 250 or 1000"),
        ({"from": "1700000002", "to": "1700000002"}, "end after"),
        ({"to": "1700001801"}, "30 minutes"),
        ({"from": "now"}, "epoch"),
    ],
)
async def test_bad_requests(env, over, words):
    svc, *_ = env
    with pytest.raises(PacketError) as err:
        await svc.search({**BODY, **over})
    assert err.value.status == 400 and words in err.value.message


@pytest.mark.asyncio
async def test_future_window_and_clamped_end(env):
    svc, *_ = env
    now = int(time.time())
    with pytest.raises(PacketError) as err:
        await svc.search({**BODY, "from": str(now + 60), "to": str(now + 120)})
    assert "hasn't happened yet" in err.value.message
    out = await svc.search({**BODY, "from": str(now - 10), "to": str(now + 100)})
    assert out["window"]["requested"]["to"] == f"{now + 100}.000000000"
    assert int(out["window"]["effective"]["to"].split(".")[0]) <= now + 1
    assert out["provisional"] is True and out["rows"] == []


@pytest.mark.asyncio
async def test_failed_files_make_any_search_incomplete(env):
    svc, fake, tmp, index = env
    (tmp / "broken.pcap").write_bytes(b"zz")
    st = (tmp / "broken.pcap").stat()
    index._entries["broken.pcap"] = IndexEntry(
        st.st_size, st.st_mtime_ns, "failed", error="bad"
    )
    index._failed_at["broken.pcap"] = (
        time.monotonic()
    )  # failed just now, not yet retried
    out = await svc.search(BODY)
    assert out["termination"] == "eof" and out["complete"] is False
    assert [s["id"] for s in out["skipped_files"]] == ["broken.pcap"]


@pytest.mark.asyncio
async def test_window_with_no_capture(env):
    svc, fake, *_ = env
    out = await svc.search({**BODY, "from": "1600000000", "to": "1600000010"})
    assert (
        out["rows"] == [] and out["complete"] and "No saved capture" in out["message"]
    )
    assert [c[0] for c in fake.calls] == [ps.CHECK_JOB]


@pytest.mark.asyncio
async def test_too_many_files_is_400(env, monkeypatch):
    svc, *_ = env
    monkeypatch.setattr(ps, "MAX_FILES", 0)
    with pytest.raises(PacketError) as err:
        await svc.search(BODY)
    assert err.value.status == 400 and "pick a shorter window" in err.value.message


@pytest.mark.asyncio
async def test_busy_reader_is_503(env, monkeypatch):
    svc, fake, *_ = env
    monkeypatch.setattr(ps, "SLOT_WAIT_SECONDS", 0.05)
    for _ in range(2):
        await svc._slot.acquire()
    with pytest.raises(PacketError) as err:
        await svc.search(BODY)
    assert err.value.status == 503


# --- detail ------------------------------------------------------------------


async def manifest_of(svc):
    return (await svc.search(BODY))["manifest"]


@pytest.mark.asyncio
async def test_detail_matches_the_search(env):
    svc, *_ = env
    out = await svc.packet({"manifest": await manifest_of(svc), "frame": 1})
    assert out["marking"] == "headers" and out["cap_len"] == 54
    assert out["bytes_hex"].startswith("020000000002")


@pytest.mark.asyncio
async def test_detail_of_a_changed_packet_is_409(env):
    svc, *_ = env
    m = await manifest_of(svc)
    m["frames"][0]["md5"] = "0" * 32
    with pytest.raises(PacketError) as err:
        await svc.packet({"manifest": m, "frame": 1})
    assert err.value.status == 409


@pytest.mark.asyncio
async def test_detail_when_frame_numbers_shifted(env):
    svc, fake, *_ = env
    m = await manifest_of(svc)
    fake.detail = result(
        (FIX / "detail_5.out").read_bytes(), fake.detail.statuses
    )  # a late packet moved frame 5 into slot 1
    with pytest.raises(PacketError) as err:
        await svc.packet({"manifest": m, "frame": 1})
    assert err.value.status == 409


@pytest.mark.asyncio
async def test_detail_when_the_window_holds_fewer_packets(env):
    svc, fake, *_ = env
    m = await manifest_of(svc)
    fake.detail = result(
        b'<pdml version="0">\n</pdml>\n#nt-hex\n', fake.detail.statuses
    )
    with pytest.raises(PacketError) as err:
        await svc.packet({"manifest": m, "frame": 1})
    assert err.value.status == 409


@pytest.mark.asyncio
async def test_detail_after_the_file_changed(env):
    svc, fake, tmp, _ = env
    m = await manifest_of(svc)
    (tmp / "a.pcap").write_bytes(b"y" * 600)
    with pytest.raises(PacketError) as err:
        await svc.packet({"manifest": m, "frame": 1})
    assert err.value.status == 409 and fake.calls[-1][0] == ps.SEARCH_JOB


# --- download ----------------------------------------------------------------


def _download_manifest(m):
    return {**m, "frames": [f for f in m["frames"] if f["n"] in (1, 2, 5)]}


@pytest.mark.asyncio
async def test_download_streams_only_verified_records(env):
    svc, fake, *_ = env
    m = svc.prepare_download(_download_manifest(await manifest_of(svc)))
    sent = []

    async def write(chunk):
        sent.append(chunk)

    assert await svc.download(m, write) == 3
    assert b"".join(sent) == fake.download
    job, args = fake.calls[-1]
    assert args[2:4] == ["5", "1,2,5"]


@pytest.mark.asyncio
async def test_download_mismatch_stops_mid_stream(env):
    svc, fake, *_ = env
    m = svc.prepare_download(_download_manifest(await manifest_of(svc)))
    bad = bytearray(fake.download)
    bad[-1] ^= 1  # the last packet's bytes changed
    fake.download = bytes(bad)
    sent = []

    async def write(chunk):
        sent.append(chunk)

    with pytest.raises(PacketError) as err:
        await svc.download(m, write)
    assert err.value.status == 409
    assert len(b"".join(sent)) < len(bad)  # the changed record was never sent


@pytest.mark.asyncio
async def test_download_with_a_failed_reader_is_an_error(env):
    svc, fake, *_ = env
    m = svc.prepare_download(_download_manifest(await manifest_of(svc)))
    fake.download_statuses = {"mergecap": 0, "editcap": 0, "tshark": 2}

    async def write(_chunk):
        pass

    with pytest.raises(PacketError) as err:
        await svc.download(m, write)
    assert err.value.status == 502


@pytest.mark.asyncio
async def test_download_refuses_mixed_link_types(env):
    svc, fake, tmp, index = env
    m = await manifest_of(svc)
    (tmp / "b.pcap").write_bytes(b"q")
    st = (tmp / "b.pcap").stat()
    index._entries["b.pcap"] = IndexEntry(
        st.st_size, st.st_mtime_ns, "indexed", "1", "2", 1, "linux-sll"
    )
    m["files"].append(
        {"id": "b.pcap", "size": st.st_size, "mtime_ns": str(st.st_mtime_ns)}
    )
    with pytest.raises(PacketError) as err:
        svc.prepare_download(m)
    assert err.value.status == 422 and "ether, linux-sll" in err.value.message


# --- fields and filter check ----------------------------------------------------


@pytest.mark.asyncio
async def test_fields_more_only_when_there_are_more(env):
    svc, fake, *_ = env
    out = await svc.fields("tls.handshake.ext")  # 21 rows came back: one past the list
    assert len(out["fields"]) == 20 and out["more"] is True
    assert out["fields"][0]["field"] == "tls.handshake.extensions_length"
    assert fake.calls[-1][1] == ["tls.handshake.ext", "21"]
    twenty = b"".join(fake.fields.stdout.splitlines(keepends=True)[:20])
    fake.fields = result(twenty, {"tshark": 0, "awk": 0})  # exactly 20 exist
    out = await svc.fields("tls.handshake.ext")
    assert len(out["fields"]) == 20 and out["more"] is False


@pytest.mark.asyncio
async def test_fields_failure_is_not_an_empty_list(env):
    svc, fake, *_ = env
    fake.fields = result(
        b"F\tdns.flags.rcode\tReply code\tFT_UINT16\t\n", {"tshark": 2, "awk": 0}
    )
    with pytest.raises(PacketError) as err:
        await svc.fields("dns.flags.rco")
    assert err.value.status == 502


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["ab", "TLS", "a b", "x;y", "a" * 81, "tls\n"])
async def test_fields_prefix_checked(env, prefix):
    svc, *_ = env
    with pytest.raises(PacketError) as err:
        await svc.fields(prefix)
    assert err.value.status == 400


@pytest.mark.asyncio
async def test_check_filter(env):
    svc, fake, *_ = env
    assert (await svc.check_filter("tcp"))["ok"]
    fake.check = result(b"", {}, "", deadline=True)
    with pytest.raises(PacketError) as err:
        await svc.check_filter("tcp")
    assert err.value.status == 504
