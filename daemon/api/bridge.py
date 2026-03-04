"""
NetTap Bridge Health Monitor API Routes

Registers bridge health monitoring endpoints with the aiohttp application.
Provides current health status, history, statistics, and bypass mode
control for the Linux bridge inline tap.
"""

import logging

from aiohttp import web

from services.bridge_health import BridgeHealthMonitor
from services.bridge_manager import BridgeManager

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
# Bridge management handlers (create, teardown, readiness)
# ---------------------------------------------------------------------------


async def handle_bridge_create(request: web.Request) -> web.Response:
    """POST /api/setup/bridge

    Create the Linux bridge with the specified WAN and LAN interfaces.
    Expects JSON body: {"wan_interface": "...", "lan_interface": "..."}
    """
    manager: BridgeManager | None = request.app.get("bridge_manager")
    if manager is None:
        return web.json_response(
            {"error": "Bridge manager not available"},
            status=503,
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"},
            status=400,
        )

    wan = body.get("wan_interface", "")
    lan = body.get("lan_interface", "")
    if not wan or not lan:
        return web.json_response(
            {"error": "wan_interface and lan_interface are required"},
            status=400,
        )

    try:
        result = await manager.create_bridge(wan=wan, lan=lan)
        status = 200 if result.get("created") else 400
        return web.json_response(result, status=status)
    except Exception as exc:
        logger.exception("Error creating bridge")
        return web.json_response(
            {"error": f"Bridge creation failed: {exc}"},
            status=500,
        )


async def handle_bridge_teardown(request: web.Request) -> web.Response:
    """POST /api/bridge/teardown

    Tear down the Linux bridge and release member interfaces.
    """
    manager: BridgeManager | None = request.app.get("bridge_manager")
    if manager is None:
        return web.json_response(
            {"error": "Bridge manager not available"},
            status=503,
        )

    try:
        result = await manager.teardown_bridge()
        status = 200 if result.get("torn_down") else 400
        return web.json_response(result, status=status)
    except Exception as exc:
        logger.exception("Error tearing down bridge")
        return web.json_response(
            {"error": f"Bridge teardown failed: {exc}"},
            status=500,
        )


async def handle_bridge_readiness(request: web.Request) -> web.Response:
    """GET /api/bridge/readiness

    Return bridge readiness status with detailed checks.
    """
    manager: BridgeManager | None = request.app.get("bridge_manager")
    if manager is None:
        return web.json_response(
            {"error": "Bridge manager not available"},
            status=503,
        )

    try:
        result = await manager.check_readiness()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error checking bridge readiness")
        return web.json_response(
            {"error": f"Bridge readiness check failed: {exc}"},
            status=500,
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_bridge_routes(
    app: web.Application,
    bridge_health_monitor: BridgeHealthMonitor,
    bridge_manager: BridgeManager | None = None,
) -> None:
    """Register all bridge API routes on the given aiohttp application."""
    app["bridge_health"] = bridge_health_monitor
    app.router.add_get("/api/bridge/health", handle_bridge_health)
    app.router.add_get("/api/bridge/history", handle_bridge_history)
    app.router.add_get("/api/bridge/stats", handle_bridge_stats)
    app.router.add_post("/api/bridge/bypass/enable", handle_bypass_enable)
    app.router.add_post("/api/bridge/bypass/disable", handle_bypass_disable)
    app.router.add_get("/api/bridge/bypass/status", handle_bypass_status)

    # Bridge management routes (require BridgeManager)
    if bridge_manager is not None:
        app["bridge_manager"] = bridge_manager
    app.router.add_post("/api/setup/bridge", handle_bridge_create)
    app.router.add_post("/api/bridge/teardown", handle_bridge_teardown)
    app.router.add_get("/api/bridge/readiness", handle_bridge_readiness)

    logger.info("Bridge API routes registered (9 endpoints)")
