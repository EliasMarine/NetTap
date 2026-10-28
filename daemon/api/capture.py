"""
NetTap Capture Mode API Routes

Provides mode-agnostic capture endpoints that work with both bridge and
mirror capture modes. The active CaptureManager implementation is stored
on the app at ``request.app["capture_manager"]``.

Endpoints:
    GET /api/capture/mode       — current capture mode
    GET /api/capture/health     — health status from CaptureManager
    GET /api/capture/stats      — drop counters, throughput
    GET /api/capture/interface  — active capture interface name
"""

import logging

from aiohttp import web

logger = logging.getLogger("nettap.api.capture")


def _get_capture_manager(request: web.Request):
    """Retrieve the CaptureManager from the app."""
    cm = request.app.get("capture_manager")
    if cm is None:
        raise web.HTTPServiceUnavailable(
            text="Capture manager not initialized"
        )
    return cm


async def handle_capture_mode(request: web.Request) -> web.Response:
    """GET /api/capture/mode — Return the current capture mode."""
    cm = _get_capture_manager(request)
    return web.json_response({
        "mode": cm.mode.value,
        "interface": cm.get_capture_interface(),
    })


async def handle_capture_health(request: web.Request) -> web.Response:
    """GET /api/capture/health — Return capture health status."""
    cm = _get_capture_manager(request)
    try:
        health = await cm.get_health()
        return web.json_response(health.to_dict())
    except Exception as exc:
        logger.error("Capture health check failed: %s", exc)
        return web.json_response(
            {"error": f"Health check failed: {exc}"}, status=500
        )


async def handle_capture_stats(request: web.Request) -> web.Response:
    """GET /api/capture/stats — Return capture interface statistics."""
    cm = _get_capture_manager(request)
    try:
        stats = await cm.get_stats()
        return web.json_response(stats.to_dict())
    except Exception as exc:
        logger.error("Capture stats failed: %s", exc)
        return web.json_response(
            {"error": f"Stats retrieval failed: {exc}"}, status=500
        )


async def handle_capture_interface(request: web.Request) -> web.Response:
    """GET /api/capture/interface — Return the active capture interface name."""
    cm = _get_capture_manager(request)
    return web.json_response({
        "interface": cm.get_capture_interface(),
    })


def register_capture_routes(app: web.Application) -> None:
    """Register capture mode API routes on the aiohttp application."""
    app.router.add_get("/api/capture/mode", handle_capture_mode)
    app.router.add_get("/api/capture/health", handle_capture_health)
    app.router.add_get("/api/capture/stats", handle_capture_stats)
    app.router.add_get("/api/capture/interface", handle_capture_interface)
    logger.info("Capture API routes registered (4 endpoints)")
