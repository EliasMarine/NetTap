"""Packet analysis API (NET-188).

GET  /api/packets/captures          saved capture files with their packet times
GET  /api/packets/capture-file?id=  one capture file
POST /api/packets/search            {filter, from, to, limit}
POST /api/packets/packet            {manifest, frame}
POST /api/packets/download          {manifest}: the search's packets as pcap
GET  /api/packets/fields?prefix=    field-name suggestions
POST /api/packets/check-filter      {filter}
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import stat
from datetime import UTC, datetime

from aiohttp import web

from services.capture_index import CaptureIndex
from services.packet_manifest import (
    MAX_BYTES,
    MAX_FILES,
    MAX_WINDOW_NS,
    PacketError,
    valid_file_id,
)
from services.packet_search import LIMITS, PacketSearchService

logger = logging.getLogger("nettap.api.packets")


def _error(exc: PacketError) -> web.Response:
    body = {"error": exc.message}
    if exc.detail:
        body["detail"] = exc.detail
    if exc.status >= 500:
        logger.warning(
            "packet request failed (%d): %s %s",
            exc.status,
            exc.message,
            exc.detail or "",
        )
    return web.json_response(body, status=exc.status)


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise PacketError(400, "The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise PacketError(400, "The request body must be a JSON object.")
    return body


def _service(request: web.Request) -> PacketSearchService:
    return request.app["packet_search"]


async def handle_captures(request: web.Request) -> web.Response:
    svc = _service(request)
    summary = await asyncio.to_thread(svc.index.summary)
    summary["limits"] = {
        "max_window_seconds": MAX_WINDOW_NS // 1_000_000_000,
        "max_files": MAX_FILES,
        "max_bytes": MAX_BYTES,
        "rows": list(LIMITS),
    }
    return web.json_response(summary)


async def handle_capture_file(request: web.Request) -> web.StreamResponse:
    svc = _service(request)
    file_id = request.query.get("id", "")
    if not valid_file_id(file_id):
        return web.json_response({"error": "Name a capture file."}, status=400)
    path = os.path.join(svc.root, file_id)
    real_root = os.path.realpath(svc.root)
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        return web.json_response(
            {"error": "That capture file no longer exists."}, status=404
        )
    if (
        os.path.islink(path)
        or not stat.S_ISREG(st.st_mode)
        or not os.path.realpath(path).startswith(real_root + os.sep)
    ):
        return web.json_response(
            {"error": "That capture file no longer exists."}, status=404
        )
    name = os.path.basename(file_id).replace('"', "")
    return web.FileResponse(
        path,
        headers={
            "Content-Type": "application/vnd.tcpdump.pcap",
            "Content-Disposition": f'attachment; filename="{name}"',
        },
    )


async def handle_search(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            await _service(request).search(await _json_body(request))
        )
    except PacketError as exc:
        return _error(exc)


async def handle_packet(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            await _service(request).packet(await _json_body(request))
        )
    except PacketError as exc:
        return _error(exc)


async def handle_fields(request: web.Request) -> web.Response:
    try:
        return web.json_response(
            await _service(request).fields(request.query.get("prefix", ""))
        )
    except PacketError as exc:
        return _error(exc)


async def handle_check_filter(request: web.Request) -> web.Response:
    try:
        body = await _json_body(request)
        return web.json_response(
            await _service(request).check_filter(body.get("filter"))
        )
    except PacketError as exc:
        return _error(exc)


def _abort(request: web.Request) -> None:
    """End the connection without the closing chunk, so the client sees a failure."""
    if request.transport is not None:
        request.transport.abort()


async def handle_download(request: web.Request) -> web.StreamResponse:
    svc = _service(request)
    try:
        manifest = svc.prepare_download((await _json_body(request)).get("manifest"))
    except PacketError as exc:
        return _error(exc)
    stamp = datetime.fromtimestamp(int(manifest.start.split(".")[0]), UTC)
    resp = web.StreamResponse(
        headers={
            "Content-Type": "application/vnd.tcpdump.pcap",
            "Content-Disposition": (
                f'attachment; filename="nettap-packets-{stamp:%Y%m%dT%H%M%SZ}.pcap"'
            ),
        }
    )

    async def write(chunk: bytes) -> None:
        if not resp.prepared:
            await resp.prepare(request)
        await resp.write(chunk)

    try:
        await svc.download(manifest, write)
    except PacketError as exc:
        if not resp.prepared:
            return _error(exc)
        logger.warning(
            "download stopped part-way: %s %s", exc.message, exc.detail or ""
        )
        _abort(request)
        return resp
    except ConnectionError:
        logger.info("download cancelled by the client")
        _abort(request)
        return resp
    await resp.write_eof()
    return resp


def register_packet_routes(
    app: web.Application, service: PacketSearchService, index: CaptureIndex
) -> None:
    app["packet_search"] = service

    async def _indexer(_app: web.Application):
        task = asyncio.create_task(index.run_forever(), name="capture-index")
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app.cleanup_ctx.append(_indexer)
    app.router.add_get("/api/packets/captures", handle_captures)
    app.router.add_get("/api/packets/capture-file", handle_capture_file)
    app.router.add_post("/api/packets/search", handle_search)
    app.router.add_post("/api/packets/packet", handle_packet)
    app.router.add_post("/api/packets/download", handle_download)
    app.router.add_get("/api/packets/fields", handle_fields)
    app.router.add_post("/api/packets/check-filter", handle_check_filter)
    logger.info("Packet analysis routes registered (7 endpoints)")
