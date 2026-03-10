"""
NetTap PCAP Search API Routes

Registers endpoints for PCAP file listing, search, preview, and download.

Endpoints:
    GET /api/pcap/files      List available PCAPs
    GET /api/pcap/search     Search PCAPs by BPF filter
    GET /api/pcap/preview    Preview packets from a PCAP
    GET /api/pcap/download   Download filtered PCAP
"""

import logging
import os

from aiohttp import web

from services.pcap_search import PcapSearchService

logger = logging.getLogger("nettap.api.pcap")


async def handle_pcap_files(request: web.Request) -> web.Response:
    """GET /api/pcap/files?from=&to= — List available PCAP files."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    from_ts = request.query.get("from")
    to_ts = request.query.get("to")

    try:
        files = pcap_service.get_available_pcaps(from_ts, to_ts)
    except Exception as exc:
        logger.error("Error listing PCAP files: %s", exc)
        return web.json_response(
            {"error": f"Failed to list PCAP files: {exc}"}, status=500
        )

    return web.json_response({
        "count": len(files),
        "files": files,
    })


async def handle_pcap_search(request: web.Request) -> web.Response:
    """GET /api/pcap/search?filter=&from=&to= — Search PCAPs by BPF filter."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    bpf_filter = request.query.get("filter", "").strip()
    from_ts = request.query.get("from")
    to_ts = request.query.get("to")

    if not bpf_filter:
        return web.json_response(
            {"error": "filter parameter is required"}, status=400
        )

    try:
        results = await pcap_service.search(bpf_filter, from_ts, to_ts)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.error("Error searching PCAPs: %s", exc)
        return web.json_response(
            {"error": f"PCAP search failed: {exc}"}, status=500
        )

    return web.json_response({
        "filter": bpf_filter,
        "count": len(results),
        "results": results,
    })


async def handle_pcap_preview(request: web.Request) -> web.Response:
    """GET /api/pcap/preview?file=&filter=&limit= — Preview packets."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    pcap_file = request.query.get("file", "").strip()
    bpf_filter = request.query.get("filter", "").strip() or None
    limit_str = request.query.get("limit", "100")

    if not pcap_file:
        return web.json_response(
            {"error": "file parameter is required"}, status=400
        )

    try:
        limit = max(1, min(int(limit_str), 1000))
    except (ValueError, TypeError):
        limit = 100

    try:
        packets = await pcap_service.preview(pcap_file, bpf_filter, limit)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except FileNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:
        logger.error("Error previewing PCAP: %s", exc)
        return web.json_response(
            {"error": f"PCAP preview failed: {exc}"}, status=500
        )

    return web.json_response({
        "file": pcap_file,
        "filter": bpf_filter,
        "count": len(packets),
        "packets": packets,
    })


async def handle_pcap_download_file(request: web.Request) -> web.Response:
    """GET /api/pcap/download-file?file= — Download a single PCAP file."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    pcap_file = request.query.get("file", "").strip()
    if not pcap_file:
        return web.json_response(
            {"error": "file parameter is required"}, status=400
        )

    # Security: ensure file is within pcap directory
    pcap_path = os.path.abspath(pcap_file)
    pcap_dir = os.path.abspath(str(pcap_service._pcap_dir))
    if not pcap_path.startswith(pcap_dir):
        return web.json_response(
            {"error": "File must be within the PCAP directory"}, status=400
        )

    if not os.path.exists(pcap_path):
        return web.json_response(
            {"error": "PCAP file not found"}, status=404
        )

    filename = os.path.basename(pcap_path)
    return web.FileResponse(
        pcap_path,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/vnd.tcpdump.pcap",
        },
    )


async def handle_pcap_download(request: web.Request) -> web.Response:
    """GET /api/pcap/download?filter=&from=&to= — Download filtered PCAP."""
    pcap_service: PcapSearchService = request.app["pcap_search"]

    bpf_filter = request.query.get("filter", "").strip()
    from_ts = request.query.get("from")
    to_ts = request.query.get("to")

    if not bpf_filter:
        return web.json_response(
            {"error": "filter parameter is required"}, status=400
        )

    try:
        tmp_path = await pcap_service.download_filtered(
            bpf_filter, from_ts, to_ts
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.error("Error downloading filtered PCAP: %s", exc)
        return web.json_response(
            {"error": f"PCAP download failed: {exc}"}, status=500
        )

    if tmp_path is None:
        return web.json_response(
            {"error": "No matching PCAP data found"}, status=404
        )

    try:
        response = web.FileResponse(
            tmp_path,
            headers={
                "Content-Disposition": "attachment; filename=nettap_filtered.pcap",
                "Content-Type": "application/vnd.tcpdump.pcap",
            },
        )
        # Schedule cleanup after response is sent
        response._tmp_path = tmp_path  # type: ignore[attr-defined]
        return response
    except Exception as exc:
        # Clean up temp file on error
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        logger.error("Error sending PCAP download: %s", exc)
        return web.json_response(
            {"error": f"Failed to send PCAP: {exc}"}, status=500
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_pcap_routes(
    app: web.Application, pcap_service: PcapSearchService
) -> None:
    """Register PCAP search API routes."""
    app["pcap_search"] = pcap_service

    app.router.add_get("/api/pcap/files", handle_pcap_files)
    app.router.add_get("/api/pcap/search", handle_pcap_search)
    app.router.add_get("/api/pcap/preview", handle_pcap_preview)
    app.router.add_get("/api/pcap/download", handle_pcap_download)
    app.router.add_get("/api/pcap/download-file", handle_pcap_download_file)

    logger.info("PCAP search API routes registered (5 endpoints)")
