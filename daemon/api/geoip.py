"""
NetTap GeoIP API Routes

Registers GeoIP lookup endpoints with the aiohttp application.
These endpoints provide IP-to-location resolution using MaxMind GeoLite2
(when available) with fallback to RFC1918 detection and a built-in
well-known IP database.
"""

import ipaddress
import logging

from aiohttp import web

from services.geoip_service import GeoIPService

logger = logging.getLogger("nettap.api.geoip")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_geoip_lookup(request: web.Request) -> web.Response:
    """GET /api/geoip/{ip}

    Look up GeoIP data for a single IP address.
    Returns 400 for invalid IP format.
    """
    raw_ip = request.match_info["ip"]

    # Validate IP format
    try:
        ipaddress.ip_address(raw_ip)
    except ValueError:
        return web.json_response({"error": f"Invalid IP address: {raw_ip}"}, status=400)

    geoip: GeoIPService = request.app["geoip"]
    result = geoip.lookup(raw_ip)
    return web.json_response(result.to_dict())


async def handle_geoip_batch(request: web.Request) -> web.Response:
    """GET /api/geoip/batch?ips=1.1.1.1,8.8.8.8

    Look up GeoIP data for multiple comma-separated IP addresses.
    Caps at 50 IPs. Returns 400 if the 'ips' parameter is missing
    or contains no valid entries.
    """
    raw_ips = request.query.get("ips", "").strip()
    if not raw_ips:
        return web.json_response(
            {"error": "Missing required query parameter: ips"}, status=400
        )

    # Split and validate
    ip_list: list[str] = []
    invalid: list[str] = []
    for ip_str in raw_ips.split(","):
        ip_str = ip_str.strip()
        if not ip_str:
            continue
        try:
            ipaddress.ip_address(ip_str)
            ip_list.append(ip_str)
        except ValueError:
            invalid.append(ip_str)

    if not ip_list:
        return web.json_response(
            {"error": "No valid IP addresses provided", "invalid": invalid},
            status=400,
        )

    geoip: GeoIPService = request.app["geoip"]
    results = geoip.lookup_batch(ip_list)

    response: dict = {"results": results}
    if invalid:
        response["invalid"] = invalid

    return web.json_response(response)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_geoip_routes(app: web.Application, geoip_service: GeoIPService) -> None:
    """Register all GeoIP API routes on the given aiohttp application."""
    app["geoip"] = geoip_service
    # Register /batch BEFORE /{ip} to avoid route conflict
    app.router.add_get("/api/geoip/batch", handle_geoip_batch)
    app.router.add_get("/api/geoip/{ip}", handle_geoip_lookup)
    logger.info("GeoIP API routes registered (2 endpoints)")
