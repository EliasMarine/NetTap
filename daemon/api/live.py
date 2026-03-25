"""
NetTap Live Connections API Routes

Registers endpoints for real-time connection monitoring.

Endpoints:
    GET /api/live/connections         Snapshot of active connections
    GET /api/live/rate                Current connection rate
    GET /api/live/dashboard           Consolidated dashboard payload (connections + aggs + alerts)
    GET /api/live/connection/detail   Detail for a specific src→dst pair (geo, alerts, history)
"""

import asyncio
import logging

from aiohttp import web

from services.live_connections import LiveConnectionTracker

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


async def handle_live_dashboard(request: web.Request) -> web.Response:
    """GET /api/live/dashboard?device=&proto=&country=&limit=100

    Returns the consolidated live dashboard payload: connections with
    geo/ASN fields, stats ribbon data, protocol distribution, top talkers,
    and geo arcs for map visualization. Alert cross-referencing flags
    connections involved in Suricata alerts.

    GeoIP fallback: connections missing lat/lon are enriched via the
    GeoIPService (MaxMind / well-known IPs / OpenSearch lookup).
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

    # Run the synchronous OpenSearch queries in a thread executor to avoid
    # blocking the event loop (matches server.py pattern).
    loop = asyncio.get_running_loop()
    try:
        dashboard = await loop.run_in_executor(
            None,
            lambda: tracker.fetch_dashboard_data(
                device=device, proto=proto, country=country, limit=limit,
            ),
        )
    except Exception as exc:
        logger.error("Error fetching live dashboard data: %s", exc)
        return web.json_response(
            {"error": f"Dashboard query failed: {exc}"}, status=502
        )

    # GeoIP fallback enrichment: fill in missing lat/lon for connections
    # that OpenSearch didn't have geo data for.
    geoip = request.app.get("geoip")
    if geoip:
        _enrich_connections_geoip(dashboard.get("connections", []), geoip)

    return web.json_response(dashboard)


async def handle_live_connection_detail(request: web.Request) -> web.Response:
    """GET /api/live/connection/detail?src=&dst=&port=

    Returns detailed information for a specific source→destination pair:
    - geo: Full GeoIP + ASN info for the destination
    - alerts: Related Suricata alerts (last 24h)
    - history: Connection timeline with byte volumes (last 24h)
    """
    tracker: LiveConnectionTracker = request.app["live_tracker"]

    src = request.query.get("src", "").strip()
    dst = request.query.get("dst", "").strip()
    port_str = request.query.get("port", "").strip()

    if not src or not dst:
        return web.json_response(
            {"error": "Both 'src' and 'dst' query parameters are required"},
            status=400,
        )

    dst_port: int | None = None
    if port_str:
        try:
            dst_port = int(port_str)
        except (ValueError, TypeError):
            pass

    # Run queries in thread executor
    loop = asyncio.get_running_loop()
    try:
        detail = await loop.run_in_executor(
            None,
            lambda: tracker.fetch_connection_detail(
                src_ip=src, dst_ip=dst, dst_port=dst_port,
            ),
        )
    except Exception as exc:
        logger.error("Error fetching connection detail: %s", exc)
        return web.json_response(
            {"error": f"Detail query failed: {exc}"}, status=502
        )

    # GeoIP fallback: if OpenSearch had no geo data for the destination
    geo = detail.get("geo", {})
    if geo and not geo.get("lat") and not geo.get("lon"):
        geoip = request.app.get("geoip")
        if geoip:
            target_ip = geo.get("ip") or dst
            result = geoip.lookup(target_ip)
            if result and not result.is_private:
                geo["country"] = result.country or geo.get("country", "")
                geo["country_code"] = result.country_code or geo.get("country_code", "")
                geo["city"] = result.city or geo.get("city", "")
                geo["lat"] = result.latitude
                geo["lon"] = result.longitude
                geo["asn"] = result.asn or geo.get("asn")
                geo["organization"] = result.organization or geo.get("organization", "")

    return web.json_response(detail)


# ---------------------------------------------------------------------------
# GeoIP fallback helper
# ---------------------------------------------------------------------------


def _enrich_connections_geoip(connections: list[dict], geoip) -> None:
    """Enrich connections that are missing geo coordinates via GeoIPService.

    Modifies connection dicts in-place. Only enriches connections where
    dest_lat/dest_lon are None (OpenSearch had no geo data).
    """
    for conn in connections:
        if conn.get("dest_lat") is not None and conn.get("dest_lon") is not None:
            continue

        dest_ip = conn.get("dest_ip", "")
        if not dest_ip:
            continue

        try:
            result = geoip.lookup(dest_ip)
        except Exception:
            continue

        if result and not result.is_private:
            if result.latitude is not None and result.longitude is not None:
                conn["dest_lat"] = result.latitude
                conn["dest_lon"] = result.longitude
            if result.city and not conn.get("dest_city"):
                conn["dest_city"] = result.city
            if result.country_code and not conn.get("country"):
                conn["country"] = result.country_code
            if result.country and not conn.get("country_name"):
                conn["country_name"] = result.country
            if result.asn and not conn.get("dest_asn"):
                conn["dest_asn"] = result.asn
            if result.organization and not conn.get("dest_org"):
                conn["dest_org"] = result.organization


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
    app.router.add_get("/api/live/dashboard", handle_live_dashboard)
    app.router.add_get("/api/live/connection/detail", handle_live_connection_detail)

    logger.info("Live connections API routes registered (4 endpoints)")
