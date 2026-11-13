"""PCAP Search's "Download filtered" over HTTP (NET-189): the body streams from the job, and a
failure never reaches the browser as a complete-looking file.

Every test goes through aiohttp's full request lifecycle with the real PcapSearchService; only the
capture index and the job in the tshark container are faked (tests/fake_pcap_download.py). There
is no temp file any more, so F8's leak can't happen (its tests are kept below as OLD CODE); every
test still checks the daemon's temp directory is left empty. The container side (the window cut's
FIFOs) is checked in test_cut_shell.py and test_container_exec.py.
"""

import asyncio
import tempfile

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import api.pcap as pcap_api
import services.pcap_search as pcap_search_mod
from api.error_replies import safe_error_middleware
from api.pcap import register_pcap_routes
from services.pcap_search import PcapSearchService
from tests.fake_pcap_download import FakeIndex, FakeTshark, capture

T = 1_794_502_800  # 2026-11-12T17:00:00Z
URL = "/api/pcap/download?filter=tcp&from=2026-11-12T17:00:00.000Z&to=2026-11-12T17:00:20.000Z"
A = capture(f"mnetsniff-enp4s0_{T - 40}.pcap", f"{T - 40}", f"{T + 4}")
B = capture(f"mnetsniff-enp4s0_{T + 5}.pcap", f"{T + 5}", f"{T + 49}")


@pytest.fixture(autouse=True)
def daemon_tmp(tmp_path, monkeypatch):
    """Where a daemon-side temp file would land: empty after every test, whatever happened
    (F8: leaked downloads filled the daemon's 50 MB /tmp)."""
    out = tmp_path / "tmp"
    out.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(out))
    yield out
    assert sorted(p.name for p in out.iterdir()) == []


@pytest.fixture
def tshark(monkeypatch):
    fake = FakeTshark()
    monkeypatch.setattr(pcap_search_mod, "run_in_tshark", fake)
    return fake


class _DaemonServer(TestServer):
    """The daemon's own runner: web.AppRunner(app) with aiohttp's defaults, which don't cancel
    a handler when its client goes away (TestServer does, which hid NET-189's abandoned job)."""

    async def _make_runner(self, **kwargs):
        kwargs.pop("handler_cancellation", None)
        return web.AppRunner(self.app, **kwargs)


async def _client(tmp_path, index, slots=2) -> TestClient:
    # OLD CODE: app = web.Application() (without the middleware a cut 503 message still passed)
    app = web.Application(middlewares=[safe_error_middleware])  # as in api/server.py
    svc = PcapSearchService(
        pcap_dir=str(tmp_path), semaphore=asyncio.Semaphore(slots), index=index
    )
    register_pcap_routes(app, svc)
    client = TestClient(_DaemonServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_the_body_is_the_jobs_output(tmp_path, tshark):
    client = await _client(tmp_path, FakeIndex([A, B]))
    try:
        resp = await client.get(URL)
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "application/vnd.tcpdump.pcap"
        assert "attachment" in resp.headers["Content-Disposition"]
        assert await resp.read() == b"".join(tshark.chunks)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_failure_before_the_first_byte_is_json(tmp_path, tshark):
    tshark.chunks = []  # the job wrote nothing, then failed
    tshark.statuses = {**tshark.statuses, "tshark": 137}
    client = await _client(tmp_path, FakeIndex([A, B]))
    try:
        resp = await client.get(URL)
        assert resp.status == 500
        assert "out of memory" in (await resp.json())["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_failure_after_the_first_byte_is_a_broken_download(tmp_path, tshark):
    tshark.statuses = {
        **tshark.statuses,
        "mergecap": 2,
    }  # bytes went out, then it failed
    client = await _client(tmp_path, FakeIndex([A, B]))
    try:
        resp = await client.get(URL)
        assert resp.status == 200
        with pytest.raises(aiohttp.ClientPayloadError):
            await resp.read()  # never a clean end the browser would save as complete
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("index", "status", "message"),
    [
        (FakeIndex([]), 404, "No capture file holds packets"),
        (FakeIndex([A], pending=9), 503, "still indexing"),
        (
            FakeIndex([capture("big.pcap", f"{T}", f"{T + 9}", packets=500_000)]),
            400,
            "500,000 packets",
        ),
    ],
)
async def test_answers_before_any_byte(tmp_path, tshark, index, status, message):
    client = await _client(tmp_path, index)
    try:
        resp = await client.get(URL)
        assert resp.status == status
        assert message in (await resp.json())["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_second_download_while_one_runs_is_503(tmp_path, tshark):
    tshark.hold = asyncio.Event()
    client = await _client(tmp_path, FakeIndex([A]))
    try:
        first = asyncio.ensure_future(client.get(URL))
        await tshark.started.wait()
        resp = await client.get(URL)
        assert resp.status == 503
        assert "Another download is running" in (await resp.json())["error"]
        tshark.hold.set()
        assert (await first).status == 200
    finally:
        tshark.hold.set()
        await client.close()


@pytest.mark.asyncio
async def test_busy_reader_slots_are_503(tmp_path, tshark, monkeypatch):
    monkeypatch.setattr(pcap_search_mod, "_DOWNLOAD_SLOT_WAIT_SECONDS", 0.05)
    client = await _client(tmp_path, FakeIndex([A]), slots=0)
    try:
        resp = await client.get(URL)
        assert resp.status == 503
        assert "packet reader is busy" in (await resp.json())["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_the_client_going_away_stops_the_job(tmp_path, tshark, monkeypatch):
    monkeypatch.setattr(pcap_api, "_CLIENT_CHECK_SECONDS", 0.05)
    # the job writes its first chunks, then nothing (a narrow filter over a long window)
    tshark.hold = asyncio.Event()
    client = await _client(tmp_path, FakeIndex([A]))
    try:
        resp = await client.get(URL)
        assert resp.status == 200
        assert await resp.content.read(len(tshark.chunks[0])) == tshark.chunks[0]
        resp.close()  # drop the connection mid-download
        await asyncio.wait_for(tshark.stopped.wait(), 10)
        # the job saw the failure, so run_in_tshark kills its process group in the
        # container (that kill: test_container_exec.py)
        assert tshark.sink_error is not None
    finally:
        tshark.hold.set()
        await client.close()


# OLD CODE START — NET-189: F8's temp-file tests; the download streams, there is no temp file
# """F8: "Download filtered" never leaves its temp file behind on the daemon's 50 MB /tmp tmpfs.
#
# Every test goes through aiohttp's full request lifecycle with the real PcapSearchService; only
# the docker exec into the tshark container is faked. aiohttp runs each request (the handler,
# then prepare() sending the file) in a task of its own; a middleware records it, and the
# assertions wait for it to end, so they run after the request is over, not after a sleep.
# """
#
# import asyncio
# import errno
# import tempfile
# import threading
# from pathlib import Path
#
# import pytest
# from aiohttp import web
# from aiohttp.test_utils import TestClient, TestServer
#
# from api.pcap import register_pcap_routes
# from services.pcap_search import PcapSearchService
#
# URL = "/api/pcap/download?filter=dns"
#
#
# class _Proc:
#     def __init__(self, out: bytes):
#         self._out, self.returncode = out, 0
#
#     async def communicate(self):
#         return self._out, b""
#
#
# @pytest.fixture
# def tmp_dir(tmp_path, monkeypatch):
#     """The service's temp files land here, so a leak is a file left in this directory."""
#     out = tmp_path / "tmp"
#     out.mkdir()
#     monkeypatch.setattr(tempfile, "tempdir", str(out))
#     return out
#
#
# @pytest.fixture
# def tshark_output(monkeypatch):
#     """The filtered PCAP the faked tshark writes to stdout; tests replace .data."""
#     state = type("S", (), {"data": b"\xd4\xc3\xb2\xa1" + b"\0" * 4096})()
#
#     async def fake_exec(*argv, **kwargs):
#         return _Proc(state.data if "tshark" in argv else b"")
#
#     monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
#     return state
#
#
# async def _client(tmp_path) -> tuple[TestClient, list[asyncio.Task]]:
#     pcaps = tmp_path / "pcap"
#     pcaps.mkdir()
#     (pcaps / "capture_001.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + b"\0" * 100)
#     requests: list[asyncio.Task] = []
#
#     @web.middleware
#     async def record(request, handler):
#         requests.append(asyncio.current_task())
#         return await handler(request)
#
#     app = web.Application(middlewares=[record])
#     register_pcap_routes(app, PcapSearchService(pcap_dir=str(pcaps)))
#     client = TestClient(TestServer(app))
#     await client.start_server()
#     return client, requests
#
#
# async def _over(requests: list[asyncio.Task]) -> None:
#     assert requests, "the request never reached the server"
#     _, pending = await asyncio.wait(requests, timeout=10)
#     assert not pending, "the request is still running"
#
#
# def _left(tmp_dir: Path) -> list[str]:
#     return sorted(p.name for p in tmp_dir.iterdir())
#
#
# @pytest.mark.asyncio
# async def test_file_is_gone_after_a_normal_download(tmp_path, tmp_dir, tshark_output):
#     client, requests = await _client(tmp_path)
#     try:
#         resp = await client.get(URL)
#         assert resp.status == 200
#         assert await resp.read() == tshark_output.data
#         await _over(requests)
#         assert _left(tmp_dir) == []
#     finally:
#         await client.close()
#
#
# @pytest.mark.asyncio
# async def test_file_is_gone_after_the_client_disconnects_mid_send(
#     tmp_path, tmp_dir, tshark_output
# ):
#     tshark_output.data = b"\xd4\xc3\xb2\xa1" + b"\0" * (32 * 1024 * 1024)
#     client, requests = await _client(tmp_path)
#     try:
#         resp = await client.get(URL)
#         assert resp.status == 200
#         assert len(await resp.content.read(1024)) > 0
#         resp.close()  # drop the connection with most of the 32 MB unsent
#         await _over(requests)
#         assert _left(tmp_dir) == []
#     finally:
#         await client.close()
#
#
# @pytest.mark.asyncio
# async def test_a_failed_write_leaves_no_file(
#     tmp_path, tmp_dir, tshark_output, monkeypatch
# ):
#     client, requests = await _client(tmp_path)
#     real_write = Path.write_bytes
#
#     def disk_full(self, data):
#         real_write(self, data[:1000])  # part of it lands, then the tmpfs fills
#         raise OSError(errno.ENOSPC, "No space left on device")
#
#     monkeypatch.setattr(Path, "write_bytes", disk_full)
#     try:
#         resp = await client.get(URL)
#         assert resp.status == 500
#         await _over(requests)
#         assert _left(tmp_dir) == []
#     finally:
#         await client.close()
#
#
# @pytest.mark.asyncio
# async def test_cancelling_during_the_write_leaves_no_file(
#     tmp_path, tmp_dir, tshark_output, monkeypatch
# ):
#     # TestServer cancels the request when the client goes away (the daemon's server cancels it
#     # at shutdown instead): the same CancelledError either way
#     client, requests = await _client(tmp_path)
#     reached, release, finished = threading.Event(), threading.Event(), threading.Event()
#     real_write = Path.write_bytes
#
#     def held_write(self, data):
#         reached.set()
#         release.wait(10)  # held just before the worker opens the path
#         try:
#             return real_write(self, data)
#         finally:
#             finished.set()
#
#     monkeypatch.setattr(Path, "write_bytes", held_write)
#     loop = asyncio.get_running_loop()
#     try:
#         download = asyncio.ensure_future(client.get(URL))
#         assert await loop.run_in_executor(None, reached.wait, 10)
#         download.cancel()  # the client goes away, so the server cancels the request
#         with pytest.raises(asyncio.CancelledError):
#             await download
#         (request,) = requests
#         while not request.cancelling():
#             await asyncio.sleep(0)  # until the server has cancelled the request
#         # one more turn: the request's wakeup is queued ahead of ours, so the CancelledError
#         # has reached the service's await before the worker may write
#         await asyncio.sleep(0)
#         release.set()
#         assert await loop.run_in_executor(None, finished.wait, 10)
#         await _over(requests)
#         assert _left(tmp_dir) == []
#     finally:
#         release.set()
#         await client.close()
# OLD CODE END
