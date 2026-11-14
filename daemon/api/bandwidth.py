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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web
from opensearchpy import OpenSearchException

from api.error_replies import public_json
from api.devices import _accounted_devices, _ip_order
from api.offload import in_thread
from api.time_range import parse_time_range, slot_interval
from services.bandwidth_tracker import (
    MAX_MONTHLY_CAP_BYTES,
    BandwidthTracker,
    internet_bytes,
)
from storage.snapshot_search import QueryFailed

logger = logging.getLogger("nettap.api.bandwidth")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """'from'/'to' as ISO timestamps, defaulting to the last 30 days; unreadable is a 400."""
    # OLD CODE START — 2026-11-02: an unreadable from/to (e.g. now-5m) silently became the
    # default window, so the Infrastructure page divided 24 h of events by 5 min
    # """Extract 'from' and 'to' query parameters as ISO timestamps.
    #
    # Defaults to the last 30 days if not provided.
    # """
    # now = datetime.now(timezone.utc)
    # default_from = (now - timedelta(days=30)).isoformat()
    # default_to = now.isoformat()
    #
    # raw_from = request.query.get("from", "")
    # raw_to = request.query.get("to", "")
    #
    # if raw_from:
    #     try:
    #         datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_from = ""
    # if raw_to:
    #     try:
    #         datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_to = ""
    #
    # return (raw_from or default_from, raw_to or default_to)
    # OLD CODE END
    return parse_time_range(request, timedelta(days=30))


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@in_thread
def handle_monthly(request: web.Request) -> web.Response:
    """GET /api/bandwidth/monthly?year=&month=

    Returns monthly usage totals and projection.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    excluded_ips_list = request.app.get("excluded_ips", [])

    now = datetime.now(timezone.utc)
    year_str = request.query.get("year", str(now.year))
    month_str = request.query.get("month", str(now.month))

    try:
        year = int(year_str)
        month = max(1, min(12, int(month_str)))
    except (ValueError, TypeError):
        year = now.year
        month = now.month

    try:
        # OLD CODE: usage = tracker.get_monthly_usage(year, month, excluded_ips=excluded_ips_list) (NET-226)
        usage = tracker.get_monthly_usage(
            year,
            month,
            excluded_ips=excluded_ips_list,
            lan_filter=request.app.get("lan_filter"),
        )
        # OLD CODE: projection = tracker.get_projected_monthly(year, month, excluded_ips=excluded_ips_list) (NET-226 follow-up)
        projection = tracker.get_projected_monthly(
            year, month, excluded_ips=excluded_ips_list, usage=usage
        )
    except QueryFailed as exc:
        return _incomplete("bandwidth/monthly", exc)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in bandwidth/monthly: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    return web.json_response(
        {
            **usage,
            "projection": projection,
        }
    )


@in_thread
def handle_daily(request: web.Request) -> web.Response:
    """GET /api/bandwidth/daily?from=&to=

    Returns daily usage totals for a date range.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    from_ts, to_ts = _parse_time_range(request)
    # NET-275: 1 d slots over ~27 years were over MAX_SLOTS and time_slots raised, a 500
    slot_interval(request, from_ts, to_ts, {"1d"}, "1d")
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        # OLD CODE: daily = tracker.get_daily_usage(from_ts, to_ts, excluded_ips=excluded_ips_list) (NET-226)
        daily = tracker.get_daily_usage(
            from_ts,
            to_ts,
            excluded_ips=excluded_ips_list,
            lan_filter=request.app.get("lan_filter"),
        )
    except QueryFailed as exc:
        return _incomplete("bandwidth/daily", exc)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in bandwidth/daily: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "interval": "1d",  # UTC days, as get_daily_usage slots them (NET-249)
            "daily": daily,
        }
    )


def _incomplete(where: str, exc: QueryFailed) -> web.Response:
    """The 502 for a search that answered only in part, never a smaller figure."""
    logger.error("Incomplete search in %s: %s", where, exc)
    return public_json({"error": "The bandwidth search was incomplete"}, status=502)


def _device_usage(accounted: list[dict], limit: int) -> list[dict]:
    """The `limit` devices with most traffic, each with its share of all devices' traffic.

    A connection between two of your devices counts for both, so the shares add up to 100
    over devices, not over the network total (NET-226).
    """
    everything = sum(d["total_bytes"] for d in accounted)
    ranked = sorted(accounted, key=lambda d: (-d["total_bytes"], _ip_order(d["key"])))
    fields = (
        "total_bytes",
        "upload_bytes",
        "download_bytes",
        "connection_count",
        "ipv6_left_out",
        "ipv6_left_out_reason",
    )
    return [
        {
            "ip": d["key"],
            **{k: d[k] for k in fields},
            "percent_of_total": round(d["total_bytes"] / everything * 100, 1)
            if everything
            else 0,
        }
        for d in ranked[:limit]
    ]


@in_thread
def handle_devices(request: web.Request) -> web.Response:
    """GET /api/bandwidth/devices?from=&to=&limit=50

    Returns per-device bandwidth breakdown.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    from_ts, to_ts = _parse_time_range(request)
    # OLD CODE: excluded_ips_list = request.app.get("excluded_ips", []) (NET-226: the device list's accounting applies them)

    limit_str = request.query.get("limit", "50")
    try:
        limit = max(1, min(200, int(limit_str)))
    except (ValueError, TypeError):
        limit = 50

    # OLD CODE START — NET-226: the sources with most bytes in the connections they started, so
    # a server's answered traffic and every device's IPv6 were missing; the device list's
    # accounting now
    # try:
    #     devices = tracker.get_per_device_usage(
    #         from_ts,
    #         to_ts,
    #         limit=limit,
    #         excluded_ips=excluded_ips_list,
    #         # same LAN rule as the device list, so both pages show the same devices
    #         lan_filter=request.app.get("lan_filter"),
    #     )
    # except OpenSearchException as exc:
    #     logger.error("OpenSearch error in bandwidth/devices: %s", exc)
    #     return web.json_response(
    #         {"error": f"OpenSearch query failed: {exc}"}, status=502
    #     )
    # OLD CODE END
    try:
        accounted = _accounted_devices(
            tracker._client,
            request.app,
            from_ts,
            to_ts,
            "bandwidth devices",
        )
    except QueryFailed as exc:
        return _incomplete("bandwidth/devices", exc)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in bandwidth/devices: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )
    devices = _device_usage(accounted, limit)

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "devices": devices,
        }
    )


@in_thread
def handle_heatmap(request: web.Request) -> web.Response:
    """GET /api/bandwidth/heatmap?from=&to=&tz=

    Returns a 7x24 hour-of-day x day-of-week bandwidth matrix, in the viewer's IANA
    time zone `tz` (default UTC).
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    from_ts, to_ts = _parse_time_range(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    tz = request.query.get("tz") or "UTC"
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return web.json_response({"error": f"Unknown time zone: {tz}"}, status=400)

    try:
        matrix = tracker.get_hourly_heatmap(
            from_ts, to_ts, excluded_ips=excluded_ips_list, tz=tz
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in bandwidth/heatmap: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    return web.json_response(
        {
            "from": from_ts,
            "to": to_ts,
            "tz": tz,
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "hours": list(range(24)),
            "matrix": matrix,
        }
    )


@in_thread
def handle_cap(request: web.Request) -> web.Response:
    """GET /api/bandwidth/cap

    Returns configured bandwidth cap and current usage percentage.
    """
    tracker: BandwidthTracker = request.app["bandwidth_tracker"]
    cap = tracker.get_cap()
    excluded_ips_list = request.app.get("excluded_ips", [])

    # Get current month usage for percentage
    now = datetime.now(timezone.utc)
    try:
        # OLD CODE: usage = tracker.get_monthly_usage(now.year, now.month, excluded_ips=excluded_ips_list)
        usage = tracker.get_monthly_usage(
            now.year,
            now.month,
            excluded_ips=excluded_ips_list,
            lan_filter=request.app.get("lan_filter"),
        )
    except QueryFailed as exc:
        return _incomplete("bandwidth/cap", exc)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in bandwidth/cap: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    # OLD CODE START — NET-226 follow-up: traffic between your own devices counted against the cap
    # cap["current_usage_bytes"] = usage["total_bytes"]
    # if cap["monthly_cap_bytes"] > 0:
    #     cap["usage_percent"] = round(
    #         usage["total_bytes"] / cap["monthly_cap_bytes"] * 100, 1
    #     )
    # OLD CODE END
    cap["current_usage_bytes"] = internet_bytes(usage)
    if cap["monthly_cap_bytes"] > 0:
        cap["usage_percent"] = round(
            cap["current_usage_bytes"] / cap["monthly_cap_bytes"] * 100, 1
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
        # OLD CODE: cap_bytes = int(float(cap_gb) * (1024**3)) (NET-166: the GB typed was GiB)
        # shortcut: a cap saved before NET-166 keeps its bytes, so it reads about 7% higher (1,000 GiB
        # shows as 1,073.7 GB); no page sets a cap yet, so convert stored caps if one ships first
        # int() cut 4.1 GB to 4,099,999,999 bytes (float error), and Infinity raised OverflowError
        # (a 500); a negative cap is saved as 0 (off), so the reply says 0 too
        # OLD CODE: cap_bytes = int(float(cap_gb) * 1e9)
        # OLD CODE: except (ValueError, TypeError):
        cap_bytes = max(0, round(float(cap_gb) * 1e9))
    except (ValueError, TypeError, OverflowError):
        return web.json_response(
            {"error": "'monthly_cap_gb' must be a number"}, status=400
        )

    # D5: the loader ignores a cap over 1 PB, so saving one would turn it off at the next start
    if cap_bytes > MAX_MONTHLY_CAP_BYTES:
        return web.json_response(
            {"error": "'monthly_cap_gb' must be at most 1,000,000 GB (1 PB)"},
            status=400,
        )
    tracker.save_cap(cap_bytes)

    return web.json_response(
        {
            "result": "saved",
            # OLD CODE: "monthly_cap_gb": round(cap_bytes / (1024**3), 1), (NET-166)
            "monthly_cap_gb": round(cap_bytes / 1e9, 1),
            "monthly_cap_bytes": cap_bytes,
        }
    )


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
