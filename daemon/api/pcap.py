"""
NetTap PCAP Search API Routes

Registers endpoints for PCAP file listing, search, preview, and download.

Endpoints:
    GET /api/pcap/files      List available PCAPs
    GET /api/pcap/search     Search PCAPs by BPF filter
    GET /api/pcap/preview    Preview packets from a PCAP
    GET /api/pcap/download   Download filtered PCAP
"""

import asyncio
import logging
import os
from collections.abc import Awaitable
from typing import TypeVar

from aiohttp import web

# OLD CODE START — NET-189: the download streams; no temp file to delete
# from aiohttp.abc import AbstractStreamWriter
# OLD CODE END
from api.error_replies import public_json
from api.offload import in_thread
from api.packets import _abort
from api.time_range import iso_param
from services.capture_index import StillIndexing
from services.container_exec import ReaderBusy
from services.packet_manifest import PacketError
from services.pcap_search import PcapSearchService

logger = logging.getLogger("nettap.api.pcap")


# OLD CODE START — NET-189: the download streams; no temp file to delete
# class _TempFileResponse(web.FileResponse):
#     """Sends a temp file, then deletes it, however the send ends (F8: the daemon's /tmp is a
#     50 MB tmpfs, so every leaked download shrank it until downloads failed)."""
#
#     async def prepare(self, request: web.BaseRequest) -> AbstractStreamWriter | None:
#         try:
#             return await super().prepare(request)
#         finally:
#             self._path.unlink(missing_ok=True)
# OLD CODE END


@in_thread
def handle_pcap_files(request: web.Request) -> web.Response:
    """GET /api/pcap/files?from=&to= — List available PCAP files."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    # OLD CODE START — an unreadable bound was dropped downstream, so a bad from searched every file
    # from_ts = request.query.get("from")
    # to_ts = request.query.get("to")
    # OLD CODE END
    from_ts = iso_param(request, "from")
    to_ts = iso_param(request, "to")

    try:
        files = pcap_service.get_available_pcaps(from_ts, to_ts)
    except Exception as exc:
        logger.error("Error listing PCAP files: %s", exc)
        return web.json_response(
            {"error": f"Failed to list PCAP files: {exc}"}, status=500
        )

    return web.json_response(
        {
            "count": len(files),
            "files": files,
        }
    )


async def handle_pcap_search(request: web.Request) -> web.Response:
    """GET /api/pcap/search?filter=&from=&to= — Search PCAPs by BPF filter."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    bpf_filter = request.query.get("filter", "").strip()
    # OLD CODE START — an unreadable bound was dropped downstream, so a bad from searched every file
    # from_ts = request.query.get("from")
    # to_ts = request.query.get("to")
    # OLD CODE END
    from_ts = iso_param(request, "from")
    to_ts = iso_param(request, "to")

    if not bpf_filter:
        return web.json_response({"error": "filter parameter is required"}, status=400)

    # OLD CODE START — 2026-11-02: one blocking request read every file in the range
    # (~45 s per 240 MB); the web proxy gave up after 10 s
    # try:
    #     results = await pcap_service.search(bpf_filter, from_ts, to_ts)
    # except ValueError as exc:
    #     return web.json_response({"error": str(exc)}, status=400)
    # except Exception as exc:
    #     logger.error("Error searching PCAPs: %s", exc)
    #     return web.json_response({"error": f"PCAP search failed: {exc}"}, status=500)
    #
    # return web.json_response(
    #     {
    #         "filter": bpf_filter,
    #         "count": len(results),
    #         "results": results,
    #     }
    # )
    # OLD CODE END
    try:
        progress = await pcap_service.search_progress(bpf_filter, from_ts, to_ts)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.error("Error searching PCAPs: %s", exc)
        return web.json_response({"error": f"PCAP search failed: {exc}"}, status=500)

    return web.json_response(progress)


async def handle_pcap_preview(request: web.Request) -> web.Response:
    """GET /api/pcap/preview?file=&filter=&limit= — Preview packets."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    pcap_file = request.query.get("file", "").strip()
    bpf_filter = request.query.get("filter", "").strip() or None
    limit_str = request.query.get("limit", "100")

    if not pcap_file:
        return web.json_response({"error": "file parameter is required"}, status=400)

    try:
        limit = max(1, min(int(limit_str), 1000))
    except (ValueError, TypeError):
        limit = 100

    try:
        result = await pcap_service.preview_with_status(pcap_file, bpf_filter, limit)
        packets = result["packets"]
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except FileNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:
        logger.error("Error previewing PCAP: %s", exc)
        return web.json_response({"error": f"PCAP preview failed: {exc}"}, status=500)

    return web.json_response(
        {
            "file": pcap_file,
            "filter": bpf_filter,
            "count": len(packets),
            "packets": packets,
            # ran out of time before the end of the file: fewer matches is not "none"
            "timed_out": result["timed_out"],
        }
    )


async def handle_pcap_download_file(request: web.Request) -> web.Response:
    """GET /api/pcap/download-file?file= — Download a single PCAP file."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    pcap_file = request.query.get("file", "").strip()
    if not pcap_file:
        return web.json_response({"error": "file parameter is required"}, status=400)

    # Security: ensure file is within pcap directory
    # OLD CODE START — sound (contains() resolves symlinks), but CodeQL can't see a guard in
    # another function, and abspath left a symlink in the directory pointing elsewhere
    # pcap_path = os.path.abspath(pcap_file)
    # OLD CODE END
    # OLD CODE START — string prefix: ".." was resolved, but "/opt/nettap/pcap-old/..." passed
    # pcap_dir = os.path.abspath(str(pcap_service._pcap_dir))
    # if not pcap_path.startswith(pcap_dir):
    # OLD CODE END
    # OLD CODE START — same check, inline below so the served path is the checked one
    # if not pcap_service.contains(pcap_path):
    # OLD CODE END
    pcap_root = os.path.realpath(str(pcap_service._pcap_dir))
    pcap_path = os.path.realpath(pcap_file)
    if not pcap_path.startswith(pcap_root + os.sep):
        return web.json_response(
            {"error": "File must be within the PCAP directory"}, status=400
        )

    if not os.path.exists(pcap_path):
        return web.json_response({"error": "PCAP file not found"}, status=404)

    filename = os.path.basename(pcap_path)
    return web.FileResponse(
        pcap_path,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/vnd.tcpdump.pcap",
        },
    )


# OLD CODE START — NET-189: the service wrote a temp file (mergecap failed past one file)
# async def handle_pcap_download(request: web.Request) -> web.Response:
#     """GET /api/pcap/download?filter=&from=&to= — Download filtered PCAP."""
#     pcap_service: PcapSearchService = request.app["pcap_search"]
#
#     bpf_filter = request.query.get("filter", "").strip()
#     # OLD CODE START — an unreadable bound was dropped downstream, so a bad from searched every file
#     # from_ts = request.query.get("from")
#     # to_ts = request.query.get("to")
#     # OLD CODE END
#     from_ts = iso_param(request, "from")
#     to_ts = iso_param(request, "to")
#
#     if not bpf_filter:
#         return web.json_response({"error": "filter parameter is required"}, status=400)
#
#     try:
#         tmp_path = await pcap_service.download_filtered(bpf_filter, from_ts, to_ts)
#     except ValueError as exc:
#         return web.json_response({"error": str(exc)}, status=400)
#     except Exception as exc:
#         logger.error("Error downloading filtered PCAP: %s", exc)
#         return web.json_response({"error": f"PCAP download failed: {exc}"}, status=500)
#
#     if tmp_path is None:
#         return web.json_response({"error": "No matching PCAP data found"}, status=404)
#
#     try:
#         # OLD CODE START — F8: nothing read _tmp_path, so every download leaked its temp file
#         # response = web.FileResponse(
#         #     tmp_path,
#         #     headers={
#         #         "Content-Disposition": "attachment; filename=nettap_filtered.pcap",
#         #         "Content-Type": "application/vnd.tcpdump.pcap",
#         #     },
#         # )
#         # # Schedule cleanup after response is sent
#         # response._tmp_path = tmp_path  # type: ignore[attr-defined]
#         # return response
#         # OLD CODE END
#         # aiohttp calls prepare() once, in finish_response; it deletes the file afterwards
#         return _TempFileResponse(
#             tmp_path,
#             headers={
#                 "Content-Disposition": "attachment; filename=nettap_filtered.pcap",
#                 "Content-Type": "application/vnd.tcpdump.pcap",
#             },
#         )
#     except Exception as exc:
#         # Clean up temp file on error
#         if os.path.exists(tmp_path):
#             os.unlink(tmp_path)
#         logger.error("Error sending PCAP download: %s", exc)
#         return web.json_response({"error": f"Failed to send PCAP: {exc}"}, status=500)
# OLD CODE END


_CLIENT_CHECK_SECONDS = 1.0
_T = TypeVar("_T")


async def _unless_client_leaves(request: web.Request, work: Awaitable[_T]) -> _T:
    """Await `work`, cancelling it once the client has gone (ConnectionResetError).

    The daemon's AppRunner doesn't cancel a handler when its client disconnects, and a narrow
    filter can write nothing for minutes, so no failed write would notice: the download would
    hold the download lock and a reader slot until its deadline (NET-189 review).
    """
    task = asyncio.ensure_future(work)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=_CLIENT_CHECK_SECONDS)
            if done:
                return task.result()
            if request.transport is None or request.transport.is_closing():
                task.cancel()
                await asyncio.wait({task})  # run_in_tshark kills the job's group
                raise ConnectionResetError("the client went away")
    except asyncio.CancelledError:
        task.cancel()
        raise


async def handle_pcap_download(request: web.Request) -> web.StreamResponse:
    """GET /api/pcap/download?filter=&from=&to= — Stream the window's matching packets.

    Errors before the first byte are JSON; after it the connection is aborted, so the
    browser shows a failed download, never a short file that looks complete (NET-189).
    """
    pcap_service: PcapSearchService = request.app["pcap_search"]

    bpf_filter = request.query.get("filter", "").strip()
    from_ts = iso_param(request, "from")
    to_ts = iso_param(request, "to")

    if not bpf_filter:
        return web.json_response({"error": "filter parameter is required"}, status=400)

    resp = web.StreamResponse(
        headers={
            "Content-Disposition": "attachment; filename=nettap_filtered.pcap",
            "Content-Type": "application/vnd.tcpdump.pcap",
        }
    )

    async def write(chunk: bytes) -> None:
        if not resp.prepared:
            await resp.prepare(request)
        await resp.write(chunk)

    try:
        # OLD CODE START — NET-189 review: an abandoned download ran on until its deadline
        # found = await pcap_service.download_filtered(bpf_filter, from_ts, to_ts, write)
        # OLD CODE END
        found = await _unless_client_leaves(
            request, pcap_service.download_filtered(bpf_filter, from_ts, to_ts, write)
        )
    except ConnectionError:
        logger.info("filtered download cancelled by the client")
        _abort(request)
        return resp
    # Written messages (ReaderBusy, StillIndexing, PacketError) go out with public_json: a plain
    # 5xx reply is cut to "Something went wrong" by api/error_replies.py (NET-189 deploy).
    except (ReaderBusy, StillIndexing) as exc:  # both raised before the first byte
        return public_json({"error": str(exc)}, status=503)
    except PacketError as exc:
        if resp.prepared:
            logger.warning("filtered download stopped part-way: %s", exc)
            _abort(request)
            return resp
        return public_json(
            {"error": f"PCAP download failed: {exc.message}"}, status=exc.status
        )
    except Exception as exc:
        if resp.prepared:
            logger.warning("filtered download stopped part-way: %s", exc)
            _abort(request)
            return resp
        if isinstance(exc, ValueError):
            return web.json_response({"error": str(exc)}, status=400)
        # OLD CODE START — NET-189 deploy: cut to "Something went wrong" by the 5xx filter
        # if isinstance(exc, (ReaderBusy, StillIndexing)):
        #     return web.json_response({"error": str(exc)}, status=503)
        # OLD CODE END
        logger.error("Error downloading filtered PCAP: %s", exc)
        return web.json_response({"error": f"PCAP download failed: {exc}"}, status=500)

    if not found:
        return web.json_response(
            {"error": "No capture file holds packets from this window."}, status=404
        )
    if not resp.prepared:  # tshark always writes a header, so this is only a guard
        await resp.prepare(request)
    await resp.write_eof()
    return resp


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_pcap_routes(app: web.Application, pcap_service: PcapSearchService) -> None:
    """Register PCAP search API routes."""
    app["pcap_search"] = pcap_service

    app.router.add_get("/api/pcap/files", handle_pcap_files)
    app.router.add_get("/api/pcap/search", handle_pcap_search)
    app.router.add_get("/api/pcap/preview", handle_pcap_preview)
    app.router.add_get("/api/pcap/download", handle_pcap_download)
    app.router.add_get("/api/pcap/download-file", handle_pcap_download_file)

    logger.info("PCAP search API routes registered (5 endpoints)")
