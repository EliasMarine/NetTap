"""F8: "Download filtered" never leaves its temp file behind on the daemon's 50 MB /tmp tmpfs.

Every test goes through aiohttp's full request lifecycle with the real PcapSearchService; only
the docker exec into the tshark container is faked. aiohttp runs each request (the handler,
then prepare() sending the file) in a task of its own; a middleware records it, and the
assertions wait for it to end, so they run after the request is over, not after a sleep.
"""

import asyncio
import errno
import tempfile
import threading
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api.pcap import register_pcap_routes
from services.pcap_search import PcapSearchService

URL = "/api/pcap/download?filter=dns"


class _Proc:
    def __init__(self, out: bytes):
        self._out, self.returncode = out, 0

    async def communicate(self):
        return self._out, b""


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """The service's temp files land here, so a leak is a file left in this directory."""
    out = tmp_path / "tmp"
    out.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(out))
    return out


@pytest.fixture
def tshark_output(monkeypatch):
    """The filtered PCAP the faked tshark writes to stdout; tests replace .data."""
    state = type("S", (), {"data": b"\xd4\xc3\xb2\xa1" + b"\0" * 4096})()

    async def fake_exec(*argv, **kwargs):
        return _Proc(state.data if "tshark" in argv else b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return state


async def _client(tmp_path) -> tuple[TestClient, list[asyncio.Task]]:
    pcaps = tmp_path / "pcap"
    pcaps.mkdir()
    (pcaps / "capture_001.pcap").write_bytes(b"\xd4\xc3\xb2\xa1" + b"\0" * 100)
    requests: list[asyncio.Task] = []

    @web.middleware
    async def record(request, handler):
        requests.append(asyncio.current_task())
        return await handler(request)

    app = web.Application(middlewares=[record])
    register_pcap_routes(app, PcapSearchService(pcap_dir=str(pcaps)))
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, requests


async def _over(requests: list[asyncio.Task]) -> None:
    assert requests, "the request never reached the server"
    _, pending = await asyncio.wait(requests, timeout=10)
    assert not pending, "the request is still running"


def _left(tmp_dir: Path) -> list[str]:
    return sorted(p.name for p in tmp_dir.iterdir())


@pytest.mark.asyncio
async def test_file_is_gone_after_a_normal_download(tmp_path, tmp_dir, tshark_output):
    client, requests = await _client(tmp_path)
    try:
        resp = await client.get(URL)
        assert resp.status == 200
        assert await resp.read() == tshark_output.data
        await _over(requests)
        assert _left(tmp_dir) == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_file_is_gone_after_the_client_disconnects_mid_send(
    tmp_path, tmp_dir, tshark_output
):
    tshark_output.data = b"\xd4\xc3\xb2\xa1" + b"\0" * (32 * 1024 * 1024)
    client, requests = await _client(tmp_path)
    try:
        resp = await client.get(URL)
        assert resp.status == 200
        assert len(await resp.content.read(1024)) > 0
        resp.close()  # drop the connection with most of the 32 MB unsent
        await _over(requests)
        assert _left(tmp_dir) == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_failed_write_leaves_no_file(
    tmp_path, tmp_dir, tshark_output, monkeypatch
):
    client, requests = await _client(tmp_path)
    real_write = Path.write_bytes

    def disk_full(self, data):
        real_write(self, data[:1000])  # part of it lands, then the tmpfs fills
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", disk_full)
    try:
        resp = await client.get(URL)
        assert resp.status == 500
        await _over(requests)
        assert _left(tmp_dir) == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_cancelling_during_the_write_leaves_no_file(
    tmp_path, tmp_dir, tshark_output, monkeypatch
):
    # TestServer cancels the request when the client goes away (the daemon's server cancels it
    # at shutdown instead): the same CancelledError either way
    client, requests = await _client(tmp_path)
    reached, release, finished = threading.Event(), threading.Event(), threading.Event()
    real_write = Path.write_bytes

    def held_write(self, data):
        reached.set()
        release.wait(10)  # held just before the worker opens the path
        try:
            return real_write(self, data)
        finally:
            finished.set()

    monkeypatch.setattr(Path, "write_bytes", held_write)
    loop = asyncio.get_running_loop()
    try:
        download = asyncio.ensure_future(client.get(URL))
        assert await loop.run_in_executor(None, reached.wait, 10)
        download.cancel()  # the client goes away, so the server cancels the request
        with pytest.raises(asyncio.CancelledError):
            await download
        (request,) = requests
        while not request.cancelling():
            await asyncio.sleep(0)  # until the server has cancelled the request
        # one more turn: the request's wakeup is queued ahead of ours, so the CancelledError
        # has reached the service's await before the worker may write
        await asyncio.sleep(0)
        release.set()
        assert await loop.run_in_executor(None, finished.wait, 10)
        await _over(requests)
        assert _left(tmp_dir) == []
    finally:
        release.set()
        await client.close()
