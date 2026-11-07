"""Packet analysis routes (NET-188): status codes, file containment, aborted downloads."""

import asyncio
import os

import pytest
from aiohttp import ClientPayloadError, web
from aiohttp.test_utils import TestClient, TestServer

from api.packets import (
    handle_capture_file,
    handle_captures,
    handle_download,
    handle_search,
)
from services.capture_index import CaptureIndex
from services.packet_manifest import PacketError
from services.packet_search import PacketSearchService


class StubService(PacketSearchService):
    def __init__(self, root):
        super().__init__(
            root,
            CaptureIndex(root, os.path.join(root, "i.json"), asyncio.Semaphore(2)),
            asyncio.Semaphore(2),
            lambda: None,
        )
        self.fail_after = None

    async def search(self, body):
        raise PacketError(400, "That time hasn't happened yet.")

    def prepare_download(self, body_manifest):
        if body_manifest == "mixed":
            raise PacketError(422, "Download isn't available for this search.")
        from services.packet_manifest import parse_manifest

        return parse_manifest(body_manifest)

    async def download(self, manifest, write):
        await write(b"\xd4\xc3\xb2\xa1" + b"\0" * 60)
        await write(b"\0" * 1000)
        if self.fail_after:
            raise PacketError(409, "changed")
        return 1


async def client_for(root):
    app = web.Application()
    app["packet_search"] = StubService(str(root))
    for method, path, handler in (
        ("GET", "/captures", handle_captures),
        ("GET", "/file", handle_capture_file),
        ("POST", "/search", handle_search),
        ("POST", "/download", handle_download),
    ):
        app.router.add_route(method, path, handler)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, app["packet_search"]


MANIFEST = {
    "from": "1700000000",
    "to": "1700000002",
    "files": [{"id": "a.pcap", "size": 1, "mtime_ns": "1"}],
    "frames": [{"n": 1, "t": "1700000000.000001", "cap_len": 54, "md5": "a" * 32}],
}


@pytest.mark.asyncio
async def test_captures_lists_limits(tmp_path):
    client, _ = await client_for(tmp_path)
    try:
        body = await (await client.get("/captures")).json()
        assert body["limits"]["max_window_seconds"] == 1800 and body["count"] == 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_capture_file_containment(tmp_path):
    (tmp_path / "a.pcap").write_bytes(b"pcapdata")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "b.pcap").write_bytes(b"other")
    os.symlink(tmp_path / "a.pcap", tmp_path / "link.pcap")
    os.symlink(tmp_path / "outside", tmp_path / "dirlink")  # a symlink mid-id
    (tmp_path / "folder.pcap").mkdir()
    client, _ = await client_for(tmp_path)
    try:
        ok = await client.get("/file", params={"id": "a.pcap"})
        assert ok.status == 200 and await ok.read() == b"pcapdata"
        assert "attachment" in ok.headers["Content-Disposition"]
        assert (
            await client.get("/file", params={"id": "../etc/passwd.pcap"})
        ).status == 400
        assert (await client.get("/file", params={"id": "link.pcap"})).status == 404
        assert (await client.get("/file", params={"id": "gone.pcap"})).status == 404
        for refused in ("dirlink/b.pcap", "folder.pcap"):
            assert (await client.get("/file", params={"id": refused})).status == 404
        assert (
            await client.get("/file", params={"id": "outside/b.pcap"})
        ).status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_errors_are_json_with_their_status(tmp_path):
    client, _ = await client_for(tmp_path)
    try:
        resp = await client.post("/search", json={})
        assert resp.status == 400
        assert (await resp.json())["error"] == "That time hasn't happened yet."
        bad = await client.post("/search", data="not json")
        assert bad.status == 400
        mixed = await client.post("/download", json={"manifest": "mixed"})
        assert (
            mixed.status == 422 and "isn't available" in (await mixed.json())["error"]
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_download_completes(tmp_path):
    client, _ = await client_for(tmp_path)
    try:
        resp = await client.post("/download", json={"manifest": MANIFEST})
        assert resp.status == 200 and len(await resp.read()) == 1064
        assert resp.headers["Content-Disposition"].endswith(
            'nettap-packets-20231114T221320Z.pcap"'
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_download_failure_after_bytes_is_an_aborted_transfer(tmp_path):
    client, svc = await client_for(tmp_path)
    svc.fail_after = True
    try:
        resp = await client.post("/download", json={"manifest": MANIFEST})
        assert resp.status == 200  # headers already went out
        with pytest.raises(ClientPayloadError):
            await resp.read()
    finally:
        await client.close()
