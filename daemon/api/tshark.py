"""
NetTap TShark API Routes

Registers TShark-related endpoints with the aiohttp application.
These endpoints provide on-demand packet analysis via the containerized TShark service.
"""

import asyncio
import logging
from aiohttp import web

from services.tshark_service import (
    TSharkService,
    TSharkRequest,
    TSharkValidationError,
)

logger = logging.getLogger("nettap.api.tshark")


async def handle_tshark_analyze(request: web.Request) -> web.Response:
    """POST /api/tshark/analyze -- Run TShark analysis on a PCAP file."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    tshark: TSharkService = request.app["tshark"]

    try:
        req = TSharkRequest(
            pcap_path=body.get("pcap_path", ""),
            display_filter=body.get("display_filter", ""),
            max_packets=int(body.get("max_packets", 100)),
            output_format=body.get("output_format", "json"),
            fields=body.get("fields", []),
        )
        result = await tshark.analyze(req)
        return web.json_response(result.to_dict())
    except TSharkValidationError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as exc:
        logger.exception("TShark analysis failed")
        return web.json_response(
            {"error": f"Analysis failed: {exc}"}, status=500
        )


async def handle_tshark_protocols(request: web.Request) -> web.Response:
    """GET /api/tshark/protocols -- List supported protocol dissectors."""
    tshark: TSharkService = request.app["tshark"]
    try:
        protocols = await tshark.get_protocols()
        return web.json_response({"protocols": protocols, "count": len(protocols)})
    except Exception as exc:
        logger.exception("Failed to get protocols")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_tshark_fields(request: web.Request) -> web.Response:
    """GET /api/tshark/fields?protocol=http -- List display filter fields."""
    protocol = request.query.get("protocol", "")
    tshark: TSharkService = request.app["tshark"]
    try:
        fields = await tshark.get_fields(protocol)
        return web.json_response({"fields": fields, "count": len(fields)})
    except Exception as exc:
        logger.exception("Failed to get fields")
        return web.json_response({"error": str(exc)}, status=500)


async def handle_tshark_status(request: web.Request) -> web.Response:
    """GET /api/tshark/status -- TShark container status."""
    tshark: TSharkService = request.app["tshark"]
    try:
        status = await tshark.is_available()
        return web.json_response(status)
    except Exception as exc:
        logger.exception("Failed to check TShark status")
        return web.json_response({"error": str(exc)}, status=500)


def register_tshark_routes(app: web.Application, tshark: TSharkService) -> None:
    """Register all TShark API routes on the given aiohttp application.

    Also stores the TSharkService instance in the app dict.
    """
    app["tshark"] = tshark
    app.router.add_post("/api/tshark/analyze", handle_tshark_analyze)
    app.router.add_get("/api/tshark/protocols", handle_tshark_protocols)
    app.router.add_get("/api/tshark/fields", handle_tshark_fields)
    app.router.add_get("/api/tshark/status", handle_tshark_status)
    logger.info("TShark API routes registered (4 endpoints)")
