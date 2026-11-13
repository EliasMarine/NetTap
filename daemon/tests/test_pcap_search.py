"""
Tests for the PcapSearchService.

Covers: BPF filter validation, file listing, preview extraction,
search, and download.
"""

import asyncio
import os
import time
from datetime import datetime, timezone

import pytest

import services.pcap_search as pcap_search_mod
from services import packet_search as ps
from decimal import Decimal

from services.capture_index import Selection, StillIndexing
from services.container_exec import ReaderBusy
from services.packet_manifest import PacketError
from services.pcap_search import PcapSearchService
from tests.fake_pcap_download import FakeIndex, FakeTshark, capture, failed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pcap_dir(tmp_path):
    """Create a temp PCAP directory with sample files."""
    pcap1 = tmp_path / "capture_001.pcap"
    pcap1.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 100)  # pcap magic + data

    pcap2 = tmp_path / "capture_002.pcapng"
    pcap2.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\x00" * 200)  # pcapng magic + data

    # Non-pcap file (should be ignored)
    txt = tmp_path / "readme.txt"
    txt.write_text("not a pcap")

    # Subdirectory with a pcap
    subdir = tmp_path / "2026-03"
    subdir.mkdir()
    pcap3 = subdir / "sub_capture.pcap"
    pcap3.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 50)

    return tmp_path


@pytest.fixture
def service(pcap_dir):
    """Return a PcapSearchService with temp PCAP directory."""
    return PcapSearchService(pcap_dir=str(pcap_dir))


# ---------------------------------------------------------------------------
# BPF filter validation
# ---------------------------------------------------------------------------


class TestBpfValidation:
    def test_valid_filter(self, service):
        """Standard BPF filters should be valid."""
        assert service.validate_bpf_filter("tcp port 80")[0] is True
        assert service.validate_bpf_filter("host 192.168.1.1")[0] is True
        assert service.validate_bpf_filter("udp and port 53")[0] is True

    def test_empty_filter(self, service):
        """Empty filter should be invalid."""
        valid, err = service.validate_bpf_filter("")
        assert valid is False
        assert "Empty" in err

    def test_none_filter(self, service):
        """None filter should be invalid."""
        valid, err = service.validate_bpf_filter(None)
        assert valid is False

    def test_forbidden_characters(self, service):
        """; ` and $ are rejected; | and & are allowed.

        Filters are Wireshark display filters, which use || and && for OR/AND.
        They reach tshark as a single argv element via create_subprocess_exec
        (no shell) -- see TestFilterArgvBoundary for the guarantee itself.
        """
        valid, err = service.validate_bpf_filter("tcp; rm -rf /")
        assert valid is False
        assert "forbidden" in err.lower()

        valid, err = service.validate_bpf_filter("tcp `whoami`")
        assert valid is False

        valid, err = service.validate_bpf_filter("ip.src == $(id)")
        assert valid is False

        assert service.validate_bpf_filter("tcp || udp")[0] is True
        assert service.validate_bpf_filter("tcp && !dns")[0] is True

    def test_too_long_filter(self, service):
        """Excessively long filters should be rejected."""
        valid, err = service.validate_bpf_filter("a" * 1001)
        assert valid is False
        assert "too long" in err.lower()


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------


class TestGetAvailablePcaps:
    def test_lists_pcap_files(self, service, pcap_dir):
        """Should find all PCAP files recursively."""
        files = service.get_available_pcaps()
        assert len(files) == 3

        names = {f["name"] for f in files}
        assert "capture_001.pcap" in names
        assert "capture_002.pcapng" in names
        assert "sub_capture.pcap" in names

    def test_excludes_non_pcap(self, service):
        """Should not include non-PCAP files."""
        files = service.get_available_pcaps()
        names = {f["name"] for f in files}
        assert "readme.txt" not in names

    def test_includes_metadata(self, service):
        """Each file entry should have required metadata."""
        files = service.get_available_pcaps()
        for f in files:
            assert "file" in f
            assert "name" in f
            assert "size_bytes" in f
            assert "modified" in f
            assert f["size_bytes"] > 0

    def test_nonexistent_directory(self, tmp_path):
        """Should return empty list for nonexistent directory."""
        svc = PcapSearchService(pcap_dir=str(tmp_path / "nonexistent"))
        assert svc.get_available_pcaps() == []

    def test_sorted_by_modification_time(self, service):
        """Files should be sorted by modification time, newest first."""
        files = service.get_available_pcaps()
        times = [f["modified"] for f in files]
        assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# Search (mocked tshark)
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_invalid_filter_raises(self, service):
        """Should raise ValueError for an invalid display filter."""
        with pytest.raises(ValueError, match="Invalid display filter"):
            await service.search("")

    @pytest.mark.asyncio
    async def test_no_pcaps_returns_empty(self, tmp_path):
        """Should return empty when no PCAP files exist."""
        svc = PcapSearchService(pcap_dir=str(tmp_path / "empty"))
        result = await svc.search("tcp port 80")
        assert result == []


# ---------------------------------------------------------------------------
# Preview (mocked tshark)
# ---------------------------------------------------------------------------


class TestPreview:
    @pytest.mark.asyncio
    async def test_file_outside_pcap_dir_rejected(self, service):
        """Should reject files outside the PCAP directory."""
        with pytest.raises(ValueError, match="within the configured"):
            await service.preview("/etc/passwd")

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, service, pcap_dir):
        """Should raise FileNotFoundError for missing files."""
        fake_path = str(pcap_dir / "nonexistent.pcap")
        with pytest.raises(FileNotFoundError):
            await service.preview(fake_path)

    @pytest.mark.asyncio
    async def test_invalid_bpf_filter_rejected(self, service, pcap_dir):
        """Should reject an invalid display filter in preview."""
        pcap_file = str(pcap_dir / "capture_001.pcap")
        with pytest.raises(ValueError, match="Invalid display filter"):
            await service.preview(pcap_file, bpf_filter="tcp; evil")


# ---------------------------------------------------------------------------
# Download (mocked tshark + mergecap)
# ---------------------------------------------------------------------------


# OLD CODE START — NET-189: the download streams from the capture index; see
# TestStreamedDownload below
# class TestDownload:
#     @pytest.mark.asyncio
#     async def test_invalid_filter_raises(self, service):
#         """Should raise ValueError for an invalid display filter."""
#         with pytest.raises(ValueError, match="Invalid display filter"):
#             await service.download_filtered("")
#
#     @pytest.mark.asyncio
#     async def test_no_pcaps_returns_none(self, tmp_path):
#         """Should return None when no PCAP files exist."""
#         svc = PcapSearchService(pcap_dir=str(tmp_path / "empty"))
#         result = await svc.download_filtered("tcp port 80")
#         assert result is None
# OLD CODE END


# ---------------------------------------------------------------------------
# Filter argv boundary (mocked subprocess)
# ---------------------------------------------------------------------------

_DISPLAY_FILTER = "ip.src == 10.0.0.1 || (tcp.port == 443 && !dns)"


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return b"1\n2\n", b""


@pytest.fixture
def recorded_argv(monkeypatch):
    """Record every create_subprocess_exec argv; fail if a shell is ever used."""
    calls = []

    async def fake_exec(*argv, **kwargs):
        calls.append(list(argv))
        return _FakeProc()

    async def no_shell(*args, **kwargs):
        raise AssertionError("create_subprocess_shell must never be used")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", no_shell)
    return calls


def _assert_filter_is_one_arg(calls):
    tshark_calls = [argv for argv in calls if "tshark" in argv]
    assert tshark_calls, "expected at least one tshark invocation"
    for argv in tshark_calls:
        assert argv[argv.index("-Y") + 1] == _DISPLAY_FILTER


class TestFilterArgvBoundary:
    @pytest.mark.asyncio
    async def test_search_passes_filter_as_single_arg(self, service, recorded_argv):
        await service.search(_DISPLAY_FILTER)
        _assert_filter_is_one_arg(recorded_argv)

    @pytest.mark.asyncio
    async def test_preview_passes_filter_as_single_arg(
        self, service, pcap_dir, recorded_argv
    ):
        await service.preview(
            str(pcap_dir / "capture_001.pcap"), bpf_filter=_DISPLAY_FILTER
        )
        # filtered preview runs `sh -c <constant script> sh <file> <filter> <limit>`
        (argv,) = recorded_argv
        assert argv[-2] == _DISPLAY_FILTER
        assert _DISPLAY_FILTER not in argv[argv.index("-c") + 1]

    # OLD CODE START — NET-189: the download's filter is a job argument now
    # (TestStreamedDownload.test_the_job_gets_the_window_filter_and_files_as_arguments)
    # @pytest.mark.asyncio
    # async def test_download_passes_filter_as_single_arg(self, service, recorded_argv):
    #     path = await service.download_filtered(_DISPLAY_FILTER)
    #     try:
    #         _assert_filter_is_one_arg(recorded_argv)
    #     finally:
    #         if path:
    #             os.unlink(path)
    # OLD CODE END


def _assert_every_exec_is_bounded(calls):
    """Each docker exec into the tshark container runs under coreutils timeout, so a
    daemon-side timeout can't leave tshark/mergecap running (G11, 2026-11-02)."""
    execs = [argv for argv in calls if argv[:2] == ["docker", "exec"]]
    assert execs, "expected at least one docker exec"
    for argv in execs:
        assert argv[3:6] == ["timeout", "-k", "5"], argv
        assert int(argv[6]) > 0


class TestNoOrphanedTshark:
    @pytest.mark.asyncio
    async def test_search_is_bounded(self, service, recorded_argv):
        await service.search(_DISPLAY_FILTER)
        _assert_every_exec_is_bounded(recorded_argv)

    @pytest.mark.asyncio
    async def test_preview_is_bounded(self, service, pcap_dir, recorded_argv):
        await service.preview(str(pcap_dir / "capture_001.pcap"))
        _assert_every_exec_is_bounded(recorded_argv)

    # OLD CODE START — NET-189: the download runs under run_in_tshark's supervisor and
    # watchdog (test_container_exec.py), with one deadline for the request
    # @pytest.mark.asyncio
    # async def test_merge_and_filter_download_are_bounded(self, service, recorded_argv):
    #     path = await service.download_filtered(_DISPLAY_FILTER)
    #     try:
    #         # two files in the fixture: mergecap, then the filter pass
    #         assert any("mergecap" in argv for argv in recorded_argv)
    #         _assert_every_exec_is_bounded([a for a in recorded_argv if "rm" not in a])
    #     finally:
    #         if path:
    #             os.unlink(path)
    # OLD CODE END


class _Proc:
    def __init__(self, out=b"1\n2\n", rc=0):
        self._out, self.returncode = out, rc

    async def communicate(self):
        return self._out, b""


@pytest.fixture
def fake_tshark(monkeypatch):
    """create_subprocess_exec stub; set .result = (stdout, returncode)."""
    state = type("S", (), {"result": (b"1\n2\n", 0), "calls": []})()

    async def fake_exec(*argv, **kwargs):
        state.calls.append(list(argv))
        return _Proc(*state.result)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return state


class TestBackgroundSearch:
    """A search over many large files runs as a job the page polls (G11, 2026-11-02)."""

    @pytest.mark.asyncio
    async def test_first_call_starts_job_and_returns_at_once(
        self, service, fake_tshark
    ):
        first = await service.search_progress("dns")
        assert first["files_total"] == 3
        assert first["files_checked"] == 0
        assert first["complete"] is False
        await service._search_task
        done = await service.search_progress("dns")
        assert done["complete"] is True
        assert done["files_checked"] == 3
        assert done["count"] == 3
        assert {r["matching_packets"] for r in done["results"]} == {2}

    @pytest.mark.asyncio
    async def test_progress_reports_sizes_and_time_for_the_estimate(
        self, service, fake_tshark
    ):
        # #137: the page estimates what's left from this box's own pace, not an assumed rate
        first = await service.search_progress("dns")
        sizes = sum(p["size_bytes"] for p in service.get_available_pcaps())
        assert first["bytes_total"] == sizes > 0
        assert first["bytes_checked"] == 0
        assert first["seconds_elapsed"] >= 0
        await service._search_task
        done = await service.search_progress("dns")
        assert done["bytes_checked"] == done["bytes_total"]
        assert (
            done["seconds_elapsed"]
            == (await service.search_progress("dns"))["seconds_elapsed"]
        )

    @pytest.mark.asyncio
    async def test_same_params_poll_the_same_job(self, service, fake_tshark):
        await service.search_progress("dns")
        task = service._search_task
        await service.search_progress("dns")
        assert service._search_task is task
        await task

    @pytest.mark.asyncio
    async def test_new_params_replace_the_job(self, service, fake_tshark):
        await service.search_progress("dns")
        old = service._search_task
        await service.search_progress("http")
        assert service._search_task is not old
        await asyncio.sleep(0)
        assert old.cancelled() or old.done()
        await service._search_task
        assert (await service.search_progress("http"))["complete"] is True

    @pytest.mark.asyncio
    async def test_out_of_memory_is_reported_as_such_not_as_a_timeout(
        self, service, fake_tshark
    ):
        # #137: the kernel's KILL (137) before timeout's deadline: a 787 MB file in a 1 GiB container
        fake_tshark.result = (b"", 137)
        await service.search_progress("dns")
        await service._search_task
        done = await service.search_progress("dns")
        assert done["timed_out"] == 0
        assert done["failed"] == 3
        assert done["error"].startswith("tshark ran out of memory reading ")
        assert done["error"].endswith(" MB)")

    @pytest.mark.asyncio
    async def test_kill_at_timeouts_deadline_is_still_a_timeout(
        self, service, fake_tshark, monkeypatch
    ):
        # timeout -k 5 sends KILL 5 s after its deadline: that 137 is a timeout
        clock = iter(range(0, 100_000, 400))
        monkeypatch.setattr(pcap_search_mod.time, "monotonic", lambda: next(clock))
        fake_tshark.result = (b"", 137)
        await service.search_progress("dns")
        await service._search_task
        done = await service.search_progress("dns")
        assert (done["timed_out"], done["failed"]) == (3, 0)

    @pytest.mark.asyncio
    async def test_timed_out_files_are_reported_not_counted_as_no_match(
        self, service, fake_tshark
    ):
        fake_tshark.result = (b"", 124)
        await service.search_progress("dns")
        await service._search_task
        done = await service.search_progress("dns")
        assert done["timed_out"] == 3
        assert done["count"] == 0
        assert done["complete"] is True

    @pytest.mark.asyncio
    async def test_cut_short_file_keeps_its_matches(self, service, fake_tshark):
        fake_tshark.result = (b"7\n9\n", 2)  # file still being written
        assert await service._count_matching_packets("/x.pcap", "dns") == 2

    @pytest.mark.asyncio
    async def test_invalid_filter_raises(self, service):
        with pytest.raises(ValueError, match="Invalid display filter"):
            await service.search_progress("")

    @pytest.mark.asyncio
    async def test_no_files_is_complete_at_once(self, tmp_path):
        svc = PcapSearchService(pcap_dir=str(tmp_path / "empty"))
        result = await svc.search_progress("dns")
        assert result["complete"] is True
        assert result["files_total"] == 0


class TestFilteredPreview:
    @pytest.mark.asyncio
    async def test_filtered_preview_stops_after_limit_matches_not_packets(
        self, service, pcap_dir, fake_tshark
    ):
        fake_tshark.result = (b"5|t|1.1.1.1|2.2.2.2|eth:ip:udp:dns|80|query\n", 0)
        packets = await service.preview(
            str(pcap_dir / "capture_001.pcap"), bpf_filter="dns", limit=50
        )
        assert packets[0]["frame_number"] == "5"
        (argv,) = fake_tshark.calls
        assert argv[3:6] == ["timeout", "-k", "5"]  # timeout kills the whole pipeline
        assert argv[7:9] == ["sh", "-c"]
        assert argv[-3:] == ["/pcap/capture_001.pcap", "dns", "50"]
        assert '| head -n "$3"' in argv[9]
        assert (
            "tshark -l -r" in argv[9]
        )  # #78: flushed lines let tshark stop when head quits
        assert "-c" not in argv[10:]

    # #141: ip.src was blank for IPv6/ARP and frame.protocols' last entry read "DATA"
    @pytest.mark.asyncio
    async def test_both_previews_use_wiresharks_columns(
        self, service, pcap_dir, fake_tshark
    ):
        fake_tshark.result = (b"1|t|fe80::1|ff02::fb|MDNS|90|Standard query\n", 0)
        await service.preview(str(pcap_dir / "capture_001.pcap"), bpf_filter="mdns")
        packets = await service.preview(str(pcap_dir / "capture_001.pcap"))
        assert len(fake_tshark.calls) == 2  # filtered, then unfiltered
        for argv in fake_tshark.calls:
            text = " ".join(argv)
            for column in ("_ws.col.Source", "_ws.col.Destination", "_ws.col.Protocol"):
                assert column in text
            assert "frame.protocols" not in text and "ip.src" not in text
        assert packets[0]["source"] == "fe80::1"
        assert packets[0]["protocol"] == "MDNS"

    @pytest.mark.asyncio
    async def test_unfiltered_preview_still_uses_packet_count(
        self, service, pcap_dir, fake_tshark
    ):
        fake_tshark.result = (b"", 0)
        await service.preview(str(pcap_dir / "capture_001.pcap"), limit=100)
        (argv,) = fake_tshark.calls
        assert argv[argv.index("-c") + 1] == "100"


@pytest.mark.asyncio
async def test_search_reads_run_at_lowest_priority(service, fake_tshark):
    """A background search must not starve previews of the container's 0.5 CPU."""
    await service.search_progress("dns")
    await service._search_task
    for argv in fake_tshark.calls:
        assert argv[7:10] == ["nice", "-n", "19"], argv


class TestPreviewTimedOut:
    """A busy 3.5 GB file can hold no match in the part 0.5 CPU reads (G11, #52)."""

    @pytest.mark.asyncio
    async def test_timeout_is_reported_with_partial_matches(
        self, service, pcap_dir, fake_tshark
    ):
        fake_tshark.result = (b"5|t|a|b|eth:ip:udp:dns|80|q\n", 124)
        result = await service.preview_with_status(
            str(pcap_dir / "capture_001.pcap"), bpf_filter="dns"
        )
        assert result["timed_out"] is True
        assert len(result["packets"]) == 1

    @pytest.mark.asyncio
    async def test_timeout_with_no_matches(self, service, pcap_dir, fake_tshark):
        fake_tshark.result = (b"", 124)
        result = await service.preview_with_status(
            str(pcap_dir / "capture_001.pcap"), bpf_filter="dns"
        )
        assert result == {"packets": [], "timed_out": True}

    @pytest.mark.asyncio
    async def test_normal_preview_is_not_timed_out(
        self, service, pcap_dir, fake_tshark
    ):
        fake_tshark.result = (b"1|t|a|b|eth:ip:tcp|60|x\n", 0)
        result = await service.preview_with_status(str(pcap_dir / "capture_001.pcap"))
        assert result["timed_out"] is False


class TestFailuresAreErrors:
    """#96: a tshark/docker failure is an error, never "no packets" or "no match"."""

    @pytest.mark.asyncio
    async def test_failed_preview_raises(self, service, pcap_dir, fake_tshark):
        fake_tshark.result = (b"", 1)  # e.g. docker: container is not running
        with pytest.raises(RuntimeError):
            await service.preview_with_status(str(pcap_dir / "capture_001.pcap"))

    @pytest.mark.asyncio
    async def test_preview_without_docker_raises(self, service, pcap_dir, monkeypatch):
        async def no_docker(*argv, **kwargs):
            raise FileNotFoundError("docker")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", no_docker)
        with pytest.raises(RuntimeError, match="docker not found"):
            await service.preview_with_status(str(pcap_dir / "capture_001.pcap"))

    @pytest.mark.asyncio
    async def test_failed_count_raises(self, service, fake_tshark):
        fake_tshark.result = (b"", 4)  # tshark: invalid display filter
        with pytest.raises(RuntimeError):
            await service._count_matching_packets("/x.pcap", "dns")

    @pytest.mark.asyncio
    async def test_background_search_reports_unreadable_files(
        self, service, fake_tshark
    ):
        fake_tshark.result = (b"", 4)
        await service.search_progress("dns")
        await service._search_task
        done = await service.search_progress("dns")
        assert done["complete"] is True
        assert done["failed"] == 3
        assert done["error"]
        assert done["count"] == 0

    # OLD CODE START — NET-189: see TestStreamedDownload.test_a_failed_read_is_an_error
    # @pytest.mark.asyncio
    # async def test_failed_download_raises_not_no_match(self, service, fake_tshark):
    #     fake_tshark.result = (b"", 1)
    #     with pytest.raises(RuntimeError):
    #         await service.download_filtered("dns")
    # OLD CODE END


# stderr of TShark 4.0.17 (the debian:bookworm container) refusing a filter, exit code 2
_ROOT_WARNING = b'Running as user "root" and group "root". This could be dangerous.\n'
_BAD_FILTER_STDERR = _ROOT_WARNING + (
    b'tshark: Left side of "==" expression must be a field or function, not ip.srcc.\n'
    b"    ip.srcc == 1\n    ^~~~~~~\n"
)


class TestRefusedFilterInPreview:
    """#96: the preview pipes tshark into head, so a refused filter read as no packets."""

    @pytest.fixture
    def tshark_runs(self, monkeypatch):
        """Pipe run prints nothing (rc 0, head's); then the filter check gets `check`."""
        state = type("S", (), {"check": (0, _ROOT_WARNING), "calls": []})()

        class P:
            def __init__(self, rc, out, err):
                self.returncode, self._out, self._err = rc, out, err

            async def communicate(self):
                return self._out, self._err

        async def fake_exec(*argv, **kwargs):
            state.calls.append(list(argv))
            if "sh" in argv:
                return P(0, b"", _BAD_FILTER_STDERR)
            return P(state.check[0], b"", state.check[1])

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        return state

    @pytest.mark.asyncio
    async def test_refused_filter_raises_tshark_message(
        self, service, pcap_dir, tshark_runs
    ):
        tshark_runs.check = (2, _BAD_FILTER_STDERR)
        with pytest.raises(ValueError, match="not ip.srcc") as exc:
            await service.preview_with_status(
                str(pcap_dir / "capture_001.pcap"), bpf_filter="ip.srcc == 1"
            )
        assert "Running as user" not in str(exc.value)
        check = tshark_runs.calls[1]
        assert check[3:6] == ["timeout", "-k", "5"]
        assert check[7:] == [
            "tshark",
            "-r",
            "/pcap/capture_001.pcap",
            "-Y",
            "ip.srcc == 1",
            "-c",
            "1",
            "-T",
            "fields",
            "-e",
            "frame.number",
        ]

    @pytest.mark.asyncio
    async def test_valid_filter_without_matches_is_empty(
        self, service, pcap_dir, tshark_runs
    ):
        result = await service.preview_with_status(
            str(pcap_dir / "capture_001.pcap"), bpf_filter="udp.port == 7"
        )
        assert result == {"packets": [], "timed_out": False}

    @pytest.mark.asyncio
    async def test_docker_failure_in_check_is_not_a_filter_error(
        self, service, pcap_dir, tshark_runs
    ):
        tshark_runs.check = (
            1,
            b"Error response from daemon: container is not running\n",
        )
        with pytest.raises(RuntimeError, match="not running"):
            await service.preview_with_status(
                str(pcap_dir / "capture_001.pcap"), bpf_filter="dns"
            )


class TestContains:
    """The PCAP directory check resolves ".." and symlinks and rejects sibling directories."""

    def test_paths(self, tmp_path):
        root = tmp_path / "pcap"
        root.mkdir()
        (tmp_path / "pcap-old").mkdir()
        (root / "a.pcap").write_bytes(b"")
        (root / "link.pcap").symlink_to(tmp_path / "pcap-old")
        svc = PcapSearchService(pcap_dir=str(root))

        assert svc.contains(str(root / "a.pcap"))
        assert not svc.contains(
            str(tmp_path / "pcap-old" / "x.pcap")
        )  # sibling with the same prefix
        assert not svc.contains(str(root / ".." / ".." / "etc" / "passwd"))
        assert not svc.contains(str(root / "link.pcap"))  # symlink out of the directory

    @pytest.mark.asyncio
    async def test_preview_rejects_dot_dot(self, service, pcap_dir):
        with pytest.raises(ValueError, match="within the configured"):
            await service.preview(str(pcap_dir / ".." / ".." / "etc" / "passwd"))


# ---------------------------------------------------------------------------
# NET-189: listing by span, and the streamed "Download filtered"
# ---------------------------------------------------------------------------

T = 1_794_502_800  # 2026-11-12T17:00:00Z


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _named(tmp_path, name: str, mtime: float):
    path = tmp_path / name
    path.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)
    os.utime(path, (mtime, mtime))
    return path


class TestListingBySpan:
    """The file list and the background search keep a file that can hold the range's packets."""

    def _names(self, tmp_path, start, end):
        svc = PcapSearchService(pcap_dir=str(tmp_path))
        return {f["name"] for f in svc.get_available_pcaps(_iso(start), _iso(end))}

    def test_a_file_that_started_in_the_range_is_listed_though_written_after_it(
        self, tmp_path
    ):
        _named(tmp_path, f"mnetsniff-enp4s0_{T - 40}.pcap", T + 5)  # before B
        _named(tmp_path, f"mnetsniff-enp4s0_{T + 5}.pcap", T + 50)  # B: starts inside
        # the bug: mtime alone left B out of a 20 s window straddling its start
        assert self._names(tmp_path, T - 5, T + 15) == {
            f"mnetsniff-enp4s0_{T - 40}.pcap",
            f"mnetsniff-enp4s0_{T + 5}.pcap",
        }

    def test_packets_up_to_the_writer_lag_before_the_name_count(self, tmp_path):
        _named(tmp_path, f"mnetsniff-enp4s0_{T + 25}.pcap", T + 60)
        assert self._names(tmp_path, T - 10, T - 2)  # 27 s before the name: listed

    def test_a_file_named_well_after_the_range_is_not_listed(self, tmp_path):
        _named(tmp_path, f"mnetsniff-enp4s0_{T + 45}.pcap", T + 80)
        assert self._names(tmp_path, T - 10, T + 10) == set()

    def test_a_name_without_a_start_time_is_listed_when_written_after_from(
        self, tmp_path
    ):
        _named(tmp_path, "renamed.pcap", T + 500)
        _named(tmp_path, "older.pcap", T - 500)
        assert self._names(tmp_path, T, T + 10) == {"renamed.pcap"}

    def test_a_time_without_an_offset_is_utc(self, tmp_path):
        _named(tmp_path, "renamed.pcap", T + 5)
        svc = PcapSearchService(pcap_dir=str(tmp_path))
        naive = datetime.fromtimestamp(T, timezone.utc).replace(tzinfo=None).isoformat()
        assert len(svc.get_available_pcaps(naive, None)) == 1  # was TypeError
        assert pcap_search_mod._parse_iso(naive) == datetime.fromtimestamp(
            T, timezone.utc
        )


@pytest.fixture
def tshark(monkeypatch):
    fake = FakeTshark()
    monkeypatch.setattr(pcap_search_mod, "run_in_tshark", fake)
    return fake


def _svc(tmp_path, index, slots=2):
    return PcapSearchService(
        pcap_dir=str(tmp_path), semaphore=asyncio.Semaphore(slots), index=index
    )


async def _download(svc, filt="tcp", start=T, end=T + 20):
    chunks: list[bytes] = []

    async def write(chunk: bytes) -> None:
        chunks.append(chunk)

    found = await svc.download_filtered(filt, _iso(start), _iso(end), write)
    return found, chunks


A = capture(f"mnetsniff-enp4s0_{T - 40}.pcap", f"{T - 40}.5", f"{T + 4}.9")
B = capture(f"mnetsniff-enp4s0_{T + 5}.pcap", f"{T + 5}.0", f"{T + 49}.1")


class TestStreamedDownload:
    @pytest.mark.asyncio
    async def test_every_file_holding_the_window_is_read_and_streamed(
        self, tmp_path, tshark
    ):
        found, chunks = await _download(_svc(tmp_path, FakeIndex([A, B])))
        assert found is True
        assert chunks == tshark.chunks  # in order, nothing held back
        (job,) = tshark.jobs(ps.FILTER_DOWNLOAD_JOB)
        assert job["args"][3:] == [A[0].container_path, B[0].container_path]

    @pytest.mark.asyncio
    async def test_files_come_from_packet_times_not_names_or_mtimes(
        self, tmp_path, tshark
    ):
        # its name and mtime say "inside the window", its packets don't
        liar = capture(
            f"x_{T + 5}.pcap", "1600000000", "1600000100", mtime_ns=T * 10**9
        )
        # its name and mtime say "long before", its packets are inside
        renamed = capture("renamed_1600000000.pcap", f"{T + 1}", f"{T + 2}")
        await _download(_svc(tmp_path, FakeIndex([liar, renamed])))
        (job,) = tshark.jobs(ps.FILTER_DOWNLOAD_JOB)
        assert job["args"][3:] == [renamed[0].container_path]

    @pytest.mark.asyncio
    async def test_the_job_gets_the_window_filter_and_files_as_arguments(
        self, tmp_path, tshark
    ):
        crashed = capture("crashed.pcap", f"{T + 1}", f"{T + 2}", cut_short=True)
        recent = capture("recent.pcap", f"{T + 3}", f"{T + 4}", mtime_ns=time.time_ns())
        filt = "ip.src == 10.0.0.1 || (tcp.port == 443 && !dns)"
        svc = _svc(tmp_path, FakeIndex([A, crashed, recent]))
        chunks: list[bytes] = []

        async def write(chunk: bytes) -> None:
            chunks.append(chunk)

        start, end = "2026-11-12T17:00:00.123Z", "2026-11-12T17:00:20.000Z"
        assert await svc.download_filtered(filt, start, end, write)
        (check,) = tshark.jobs(ps.CHECK_JOB)
        (job,) = tshark.jobs(ps.FILTER_DOWNLOAD_JOB)
        assert check["args"] == [filt]
        assert job["args"] == [
            f"{T}.123",
            f"{T + 20}",
            filt,
            A[0].container_path,
            "cut:/pcap/crashed.pcap",  # may end in a partly written packet
            "cut:/pcap/recent.pcap",  # still being written
        ]
        assert filt not in job["job"]  # the script text is constant
        assert " -M" not in ps.FILTER_DOWNLOAD_JOB  # no session reset: exact matches
        assert job["max"] == 2 * 3 * 1_000_000 + 1024 * 1024
        assert 0 < job["deadline_s"] <= 240

    @pytest.mark.asyncio
    async def test_no_file_holding_the_window_is_false_and_reads_nothing(
        self, tmp_path, tshark
    ):
        found, chunks = await _download(
            _svc(tmp_path, FakeIndex([A])), start=T + 100, end=T + 120
        )
        assert (found, chunks, tshark.calls) == (False, [], [])

    @pytest.mark.asyncio
    async def test_without_from_the_window_starts_in_2000(self, tmp_path, tshark):
        index = FakeIndex([A])
        await _svc(tmp_path, index).download_filtered("tcp", None, _iso(T), _noop)
        assert index.asked[0][0] == 946684800

    @pytest.mark.asyncio
    async def test_still_indexing_reads_nothing(self, tmp_path, tshark):
        with pytest.raises(StillIndexing):
            await _download(_svc(tmp_path, FakeIndex([A], pending=12)))
        assert tshark.calls == []

    @pytest.mark.asyncio
    async def test_a_failed_file_refuses_the_download_whatever_its_mtime(
        self, tmp_path, tshark
    ):
        # capinfos couldn't read it, so nobody knows its packet times; an old mtime
        # proves nothing (round 2 ignored such a file)
        for broken in (failed("broken.pcap"), failed("new.pcap", time.time_ns())):
            svc = _svc(tmp_path, FakeIndex([A, B], [broken]))
            with pytest.raises(ValueError, match=f"couldn't read {broken[0].id}, so"):
                await _download(svc)
        assert tshark.calls == []

    @pytest.mark.asyncio
    async def test_many_failed_files_are_named_up_to_five(self, tmp_path, tshark):
        broken = [failed(f"b{i}.pcap") for i in range(7)]
        with pytest.raises(ValueError, match=r"b4\.pcap and 2 more, so"):
            await _download(_svc(tmp_path, FakeIndex([A], broken)))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "files",
        [
            # over the packet budget (TShark's memory follows the packet count)
            [capture("big.pcap", f"{T}", f"{T + 9}", packets=400_001)],
            # 65 tiny files under the packet budget: 65 editcaps and FIFOs
            [
                capture(f"f{i:02}.pcap", f"{T}", f"{T + 9}", packets=10)
                for i in range(65)
            ],
            # over 3 GB under the packet budget
            [
                capture(
                    f"j{i}.pcap", f"{T}", f"{T + 9}", packets=100, size=1_100_000_000
                )
                for i in range(3)
            ],
        ],
    )
    async def test_over_budget_is_refused_before_any_read(
        self, tmp_path, tshark, files
    ):
        with pytest.raises(ValueError, match="One download reads at most 400,000"):
            await _download(_svc(tmp_path, FakeIndex(files)))
        assert tshark.calls == []

    @pytest.mark.asyncio
    async def test_only_the_windows_share_of_each_file_counts(self, tmp_path, tshark):
        # 256 MB files of ~300k packets each: whole, two are over the budget, but a 20 s
        # window across the change reads about 10% of each (NET-189 review)
        a = capture("a.pcap", f"{T - 100}", f"{T + 10}", packets=300_000)
        b = capture("b.pcap", f"{T + 10}", f"{T + 110}", packets=300_000)
        found, _ = await _download(
            _svc(tmp_path, FakeIndex([a, b])), start=T, end=T + 20
        )
        assert found is True
        assert (
            pcap_search_mod._window_packets(
                Selection([a, b], []), Decimal(T), Decimal(T + 20)
            )
            == 27_272 + 30_000
        )  # 10/110 of a, 10/100 of b
        # a file whose packets share one timestamp counts whole
        one = capture("one.pcap", f"{T + 5}", f"{T + 5}", packets=7)
        assert (
            pcap_search_mod._window_packets(
                Selection([one], []), Decimal(T), Decimal(T + 20)
            )
            == 7
        )

    @pytest.mark.asyncio
    async def test_a_refused_filter_is_tsharks_message_before_the_read(
        self, tmp_path, tshark
    ):
        tshark.check = (2, 'tshark: "foo" is neither a field nor a protocol name.')
        with pytest.raises(ValueError, match="neither a field"):
            await _download(_svc(tmp_path, FakeIndex([A])), filt="foo")
        assert tshark.jobs(ps.FILTER_DOWNLOAD_JOB) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("statuses", "deadline", "stderr", "message"),
        [
            ({"tshark": 137}, False, "", "out of memory"),
            ({"tshark": 143}, True, "", "longer than the time allowed"),
            ({"mergecap": 2}, False, "", "Reading the capture files failed"),
            ({}, False, 'editcap: The file "x" appears to be damaged.', "failed"),
        ],
    )
    async def test_a_failed_read_is_an_error(
        self, tmp_path, tshark, statuses, deadline, stderr, message
    ):
        tshark.statuses = {**tshark.statuses, **statuses}
        tshark.deadline, tshark.stderr = deadline, stderr
        with pytest.raises(PacketError, match=message):
            await _download(_svc(tmp_path, FakeIndex([A, B])))

    @pytest.mark.asyncio
    async def test_a_second_download_is_busy_and_takes_no_slot(self, tmp_path, tshark):
        tshark.hold = asyncio.Event()
        svc = _svc(tmp_path, FakeIndex([A]))
        first = asyncio.create_task(_download(svc))
        await tshark.started.wait()
        slots = svc._semaphore._value
        try:
            with pytest.raises(ReaderBusy, match="Another download is running"):
                await _download(svc)
            assert svc._semaphore._value == slots
        finally:
            tshark.hold.set()
        assert (await first)[0] is True

    @pytest.mark.asyncio
    async def test_busy_reader_slots_are_waited_for_briefly(
        self, tmp_path, tshark, monkeypatch
    ):
        monkeypatch.setattr(pcap_search_mod, "_DOWNLOAD_SLOT_WAIT_SECONDS", 0.05)
        with pytest.raises(ReaderBusy):
            await _download(_svc(tmp_path, FakeIndex([A]), slots=0))
        assert tshark.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("filt", "start", "end"), [("", T, T + 1), ("tcp", T, T)])
    async def test_a_bad_filter_or_window_is_refused(
        self, tmp_path, tshark, filt, start, end
    ):
        with pytest.raises(ValueError):
            await _download(_svc(tmp_path, FakeIndex([A])), filt, start, end)
        assert tshark.calls == []


async def _noop(_chunk: bytes) -> None:
    return None
