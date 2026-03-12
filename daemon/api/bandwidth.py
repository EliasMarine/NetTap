"""
NetTap Bandwidth API Routes

Registers endpoints for bandwidth monitoring, data cap tracking,
and usage analytics.

Endpoints:
    GET  /api/bandwidth/monthly    Monthly usage + projection
    GET  /api/bandwidth/daily      Daily usage totals
    GET  /api/bandwidth/devices    Per-device bandwidth breakdown
    GET  /api/bandwidth/heatmap    Hour x day-of-week matrix
    GET  /api/bandwidth/cap        Configured cap + usage %
    PUT  /api/settings/bandwidth-cap  Set monthly bandwidth cap
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web

from services.bandwidth_tracker import BandwidthTracker

logger = logging.getLogger("nettap.api.bandwidth")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Extract 'from' and 'to' query parameters as ISO timestamps.

    Defaults to the last 30 days if not provided.
    """
    now = datetime.now(timezone.utc)
    default_from = (now - timedelta(days=30)).isoformat()
    default_to = now.isoformat()

    raw_from = request.query.get("from", "")
    raw_to = request.query.get("to", "")

    if raw_from:
        try:
            datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_from = ""
    if raw_to:
        try:
            datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw_to = ""

    return (raw_from or default_from, raw_to or default_to)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_monthly(request: web.Request) -> web.Response:
    """GET /api/bandwidth/monthly?year=&month=

    Returns monthly usage totals and projection.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]

    now = datetime.now(timezone.utc)
    year_str = request.query.get("year", str(now.year))
    month_str = request.query.get("month", str(now.month))

    try:
        year = int(year_str)
        month = max(1, min(12, int(month_str)))
    except (ValueError, TypeError):
        year = now.year
        month = now.month

    usage = tracker.get_monthly_usage(year, month)
    projection = tracker.get_projected_monthly(year, month)

    return web.json_response({
        **usage,
        "projection": projection,
    })


async def handle_daily(request: web.Request) -> web.Response:
    """GET /api/bandwidth/daily?from=&to=

    Returns daily usage totals for a date range.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    from_ts, to_ts = _parse_time_range(request)

    daily = tracker.get_daily_usage(from_ts, to_ts)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "daily": daily,
    })


async def handle_devices(request: web.Request) -> web.Response:
    """GET /api/bandwidth/devices?from=&to=&limit=50

    Returns per-device bandwidth breakdown.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    from_ts, to_ts = _parse_time_range(request)

    limit_str = request.query.get("limit", "50")
    try:
        limit = max(1, min(200, int(limit_str)))
    except (ValueError, TypeError):
        limit = 50

    devices = tracker.get_per_device_usage(from_ts, to_ts, limit=limit)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "devices": devices,
    })


async def handle_heatmap(request: web.Request) -> web.Response:
    """GET /api/bandwidth/heatmap?from=&to=

    Returns a 7x24 hour-of-day x day-of-week bandwidth matrix.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    from_ts, to_ts = _parse_time_range(request)

    matrix = tracker.get_hourly_heatmap(from_ts, to_ts)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "hours": list(range(24)),
        "matrix": matrix,
    })


async def handle_cap(request: web.Request) -> web.Response:
    """GET /api/bandwidth/cap

    Returns configured bandwidth cap and current usage percentage.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    cap = tracker.get_cap()

    # Get current month usage for percentage
    now = datetime.now(timezone.utc)
    usage = tracker.get_monthly_usage(now.year, now.month)

    cap["current_usage_bytes"] = usage["total_bytes"]
    if cap["monthly_cap_bytes"] > 0:
        cap["usage_percent"] = round(
            usage["total_bytes"] / cap["monthly_cap_bytes"] * 100, 1
        )
    else:
        cap["usage_percent"] = 0

    return web.json_response(cap)


async def handle_set_cap(request: web.Request) -> web.Response:
    """PUT /api/settings/bandwidth-cap

    Set the monthly bandwidth cap.
    Body: { "monthly_cap_gb": 1200 }
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)

    cap_gb = body.get("monthly_cap_gb")
    if cap_gb is None:
        return web.json_response(
            {"error": "Missing 'monthly_cap_gb' field"}, status=400
        )

    try:
        cap_bytes = int(float(cap_gb) * (1024**3))
    except (ValueError, TypeError):
        return web.json_response(
            {"error": "'monthly_cap_gb' must be a number"}, status=400
        )

    tracker.save_cap(cap_bytes)

    return web.json_response({
        "result": "saved",
        "monthly_cap_gb": round(cap_bytes / (1024**3), 1),
        "monthly_cap_bytes": cap_bytes,
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_bandwidth_routes(
    app: web.Application,
    tracker: BandwidthTracker,
) -> None:
    """Register bandwidth API routes on the aiohttp application."""
    app["bandwidth_tracker"] = tracker

    app.router.add_get("/api/bandwidth/monthly", handle_monthly)
    app.router.add_get("/api/bandwidth/daily", handle_daily)
    app.router.add_get("/api/bandwidth/devices", handle_devices)
    app.router.add_get("/api/bandwidth/heatmap", handle_heatmap)
    app.router.add_get("/api/bandwidth/cap", handle_cap)
    app.router.add_put("/api/settings/bandwidth-cap", handle_set_cap)

    logger.info("Bandwidth API routes registered (6 endpoints)")
