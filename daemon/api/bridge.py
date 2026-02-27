"""
NetTap Bridge Health Monitor API Routes

Registers bridge health monitoring endpoints with the aiohttp application.
Provides current health status, history, statistics, and bypass mode
control for the Linux bridge inline tap.
"""

import logging

from aiohttp import web

from services.bridge_health import BridgeHealthMonitor

logger = logging.getLogger("nettap.api.bridge")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_bridge_health(request: web.Request) -> web.Response:
    """GET /api/bridge/health

    Return the current bridge health status by running a health check.
    """
    monitor: BridgeHealthMonitor = request.app["bridge_health"]
    try:
        result = await monitor.check_health()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error checking bridge health")
        return web.json_response(
            {"error": f"Bridge health check failed: {exc}"},
            status=500,
        )


async def handle_bridge_history(request: web.Request) -> web.Response:
    """GET /api/bridge/history?limit=100

    Return bridge health check history (newest first).
    Optional 'limit' query param (default 100).
    """
    monitor: BridgeHealthMonitor = request.app["bridge_health"]

    limit = 100
    raw_limit = request.query.get("limit", "")
    if raw_limit:
        try:
            limit = max(1, int(raw_limit))
        except (ValueError, TypeError):
            pass

    try:
        history = await monitor.get_history(limit=limit)
        return web.json_response({"history": history, "count": len(history)})
    except Exception as exc:
        logger.exception("Error fetching bridge history")
        return web.json_response(
            {"error": f"Failed to fetch bridge history: {exc}"},
            status=500,
        )


async def handle_bridge_stats(request: web.Request) -> web.Response:
    """GET /api/bridge/stats

    Return computed statistics over the bridge health check history.
    """
    monitor: BridgeHealthMonitor = request.app["bridge_health"]
    try:
        stats = await monitor.get_statistics()
        return web.json_response(stats)
    except Exception as exc:
        logger.exception("Error fetching bridge statistics")
        return web.json_response(
            {"error": f"Failed to fetch bridge statistics: {exc}"},
            status=500,
        )


async def handle_bypass_enable(request: web.Request) -> web.Response:
    """POST /api/bridge/bypass/enable

    Activate bypass mode. Traffic will flow directly between WAN and LAN
    without inspection.
    """
    monitor: BridgeHealthMonitor = request.app["bridge_health"]
    try:
        result = await monitor.trigger_bypass()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error enabling bypass mode")
        return web.json_response(
            {"error": f"Failed to enable bypass mode: {exc}"},
            status=500,
        )


async def handle_bypass_disable(request: web.Request) -> web.Response:
    """POST /api/bridge/bypass/disable

    Deactivate bypass mode. Traffic inspection will resume.
    """
    monitor: BridgeHealthMonitor = request.app["bridge_health"]
    try:
        result = await monitor.disable_bypass()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error disabling bypass mode")
        return web.json_response(
            {"error": f"Failed to disable bypass mode: {exc}"},
            status=500,
        )


async def handle_bypass_status(request: web.Request) -> web.Response:
    """GET /api/bridge/bypass/status

    Return the current bypass mode status.
    """
    monitor: BridgeHealthMonitor = request.app["bridge_health"]
    return web.json_response(
        {
            "bypass_active": monitor._bypass_active,
        }
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_bridge_routes(
    app: web.Application, bridge_health_monitor: BridgeHealthMonitor
) -> None:
    """Register all bridge health monitor API routes on the given aiohttp application."""
    app["bridge_health"] = bridge_health_monitor
    app.router.add_get("/api/bridge/health", handle_bridge_health)
    app.router.add_get("/api/bridge/history", handle_bridge_history)
    app.router.add_get("/api/bridge/stats", handle_bridge_stats)
    app.router.add_post("/api/bridge/bypass/enable", handle_bypass_enable)
    app.router.add_post("/api/bridge/bypass/disable", handle_bypass_disable)
    app.router.add_get("/api/bridge/bypass/status", handle_bypass_status)
    logger.info("Bridge health monitor API routes registered (6 endpoints)")
