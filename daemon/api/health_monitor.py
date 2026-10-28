"""
NetTap Internet Health Monitor API Routes

Registers internet health check endpoints with the aiohttp application.
Provides current status, history, statistics, and on-demand health checks.
"""

import logging

from aiohttp import web

from services.internet_health import InternetHealthMonitor

logger = logging.getLogger("nettap.api.health_monitor")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_health_status(request: web.Request) -> web.Response:
    """GET /api/internet/health

    Return the most recent internet health check result.
    """
    monitor: InternetHealthMonitor = request.app["internet_health"]
    return web.json_response(monitor.get_current_status())


async def handle_health_history(request: web.Request) -> web.Response:
    """GET /api/internet/history?limit=288

    Return internet health check history (newest first).
    Optional 'limit' query param (default 288 = 24h at 5min intervals).
    """
    monitor: InternetHealthMonitor = request.app["internet_health"]

    limit = 288
    raw_limit = request.query.get("limit", "")
    if raw_limit:
        try:
            limit = max(1, int(raw_limit))
        except (ValueError, TypeError):
            pass

    history = monitor.get_history(limit=limit)
    return web.json_response({"history": history, "count": len(history)})


async def handle_health_stats(request: web.Request) -> web.Response:
    """GET /api/internet/stats

    Return computed statistics over the health check history window.
    """
    monitor: InternetHealthMonitor = request.app["internet_health"]
    return web.json_response(monitor.get_statistics())


async def handle_health_check(request: web.Request) -> web.Response:
    """POST /api/internet/check

    Trigger an immediate health check cycle and return the result.
    """
    monitor: InternetHealthMonitor = request.app["internet_health"]
    check = await monitor.run_check()
    return web.json_response(check.to_dict())


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_health_monitor_routes(
    app: web.Application, monitor: InternetHealthMonitor
) -> None:
    """Register all internet health monitor API routes."""
    app["internet_health"] = monitor
    app.router.add_get("/api/internet/health", handle_health_status)
    app.router.add_get("/api/internet/history", handle_health_history)
    app.router.add_get("/api/internet/stats", handle_health_stats)
    app.router.add_post("/api/internet/check", handle_health_check)
    logger.info("Internet health monitor API routes registered (4 endpoints)")
