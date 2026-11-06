"""
NetTap Capture Mode API Routes

Provides mode-agnostic capture endpoints that work with both bridge and
mirror capture modes. The active CaptureManager implementation is stored
on the app at ``request.app["capture_manager"]``.

Endpoints:
    GET /api/capture/mode       — current capture mode
    GET /api/capture/health     — health status from CaptureManager
    GET /api/capture/stats      — drop counters, throughput, loss over the last hour
    GET /api/capture/interface  — active capture interface name
"""

import asyncio
import contextlib
import logging
import time
from typing import AsyncIterator

from aiohttp import web

from services.loss_window import (
    SAMPLE_INTERVAL_S,
    SYS_NET,
    LossWindow,
    read_loss_counters,
)

logger = logging.getLogger("nettap.api.capture")


def _get_capture_manager(request: web.Request):
    """Retrieve the CaptureManager from the app."""
    cm = request.app.get("capture_manager")
    if cm is None:
        raise web.HTTPServiceUnavailable(text="Capture manager not initialized")
    return cm


async def handle_capture_mode(request: web.Request) -> web.Response:
    """GET /api/capture/mode — Return the current capture mode."""
    cm = _get_capture_manager(request)
    return web.json_response(
        {
            "mode": cm.mode.value,
            "interface": cm.get_capture_interface(),
        }
    )


async def handle_capture_health(request: web.Request) -> web.Response:
    """GET /api/capture/health — Return capture health status."""
    cm = _get_capture_manager(request)
    try:
        health = await cm.get_health()
        return web.json_response(health.to_dict())
    except Exception as exc:
        logger.error("Capture health check failed: %s", exc)
        return web.json_response({"error": f"Health check failed: {exc}"}, status=500)


async def handle_capture_stats(request: web.Request) -> web.Response:
    """GET /api/capture/stats — Return capture interface statistics."""
    cm = _get_capture_manager(request)
    try:
        stats = await cm.get_stats()
        # OLD CODE START — NET-167: cumulative counters only
        # return web.json_response(stats.to_dict())
        # OLD CODE END
        sample_loss(request.app)
        return web.json_response(
            {**stats.to_dict(), "loss_window": request.app["loss_window"].over()}
        )
    except Exception as exc:
        logger.error("Capture stats failed: %s", exc)
        return web.json_response(
            {"error": f"Stats retrieval failed: {exc}"}, status=500
        )


def sample_loss(app: web.Application) -> None:
    """One validated reading of the capture interface's loss counters (NET-167).

    No await inside: the background sampler and a request can't interleave between reading
    the clock, reading sysfs and recording the sample.
    """
    cm = app.get("capture_manager")
    if cm is None:
        return
    iface = cm.get_capture_interface() or ""
    counters = read_loss_counters(app["loss_sys_net"], iface) if iface else None
    app["loss_window"].add(time.monotonic(), iface, counters)


async def _loss_sampler(app: web.Application) -> AsyncIterator[None]:
    """A reading every minute, so the window covers the last hour whether or not a page is open."""

    async def run() -> None:
        while True:
            try:
                sample_loss(app)
            except Exception:
                logger.exception("Loss window sample failed")
            await asyncio.sleep(SAMPLE_INTERVAL_S)

    task = asyncio.create_task(run(), name="loss-window-sampler")
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def handle_capture_interface(request: web.Request) -> web.Response:
    """GET /api/capture/interface — Return the active capture interface name."""
    cm = _get_capture_manager(request)
    return web.json_response(
        {
            "interface": cm.get_capture_interface(),
        }
    )


def register_capture_routes(app: web.Application) -> None:
    """Register capture mode API routes on the aiohttp application."""
    app["loss_window"] = LossWindow()
    app.setdefault("loss_sys_net", SYS_NET)
    app.cleanup_ctx.append(_loss_sampler)
    app.router.add_get("/api/capture/mode", handle_capture_mode)
    app.router.add_get("/api/capture/health", handle_capture_health)
    app.router.add_get("/api/capture/stats", handle_capture_stats)
    app.router.add_get("/api/capture/interface", handle_capture_interface)
    logger.info("Capture API routes registered (4 endpoints)")
