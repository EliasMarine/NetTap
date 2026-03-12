"""
NetTap Live Connections API Routes

Registers endpoints for real-time connection monitoring.

Endpoints:
    GET /api/live/connections  Snapshot of active connections
    GET /api/live/rate         Current connection rate
"""

import logging

from aiohttp import web

from services.live_connections import LiveConnectionTracker
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.live")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_live_connections(request: web.Request) -> web.Response:
    """GET /api/live/connections?device=&proto=&country=&limit=100

    Returns a snapshot of recent active connections from the tracker.
    """
    tracker: LiveConnectionTracker = request.app["live_tracker"]

    device = request.query.get("device", "").strip() or None
    proto = request.query.get("proto", "").strip() or None
    country = request.query.get("country", "").strip() or None
    limit_str = request.query.get("limit", "100")
    try:
        limit = max(1, min(int(limit_str), 1000))
    except (ValueError, TypeError):
        limit = 100

    # Fetch fresh data from OpenSearch and update cache
    connections = tracker.fetch_from_opensearch(
        device=device,
        proto=proto,
        country=country,
        limit=limit,
    )

    return web.json_response({
        "connections": connections,
        "count": len(connections),
        "filters": {
            "device": device,
            "proto": proto,
            "country": country,
        },
    })


async def handle_live_rate(request: web.Request) -> web.Response:
    """GET /api/live/rate

    Returns current connection rate (connections/sec over last 60s).
    """
    tracker: LiveConnectionTracker = request.app["live_tracker"]
    rate = tracker.get_connection_rate()
    return web.json_response(rate)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_live_routes(
    app: web.Application,
    tracker: LiveConnectionTracker,
) -> None:
    """Register live connection API routes on the aiohttp application."""
    app["live_tracker"] = tracker

    app.router.add_get("/api/live/connections", handle_live_connections)
    app.router.add_get("/api/live/rate", handle_live_rate)

    logger.info("Live connections API routes registered (2 endpoints)")
