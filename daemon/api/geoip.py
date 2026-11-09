"""
NetTap GeoIP API Routes

Registers GeoIP lookup endpoints with the aiohttp application.
These endpoints answer from Malcolm's GeoLite2 enrichment stored with the traffic in
OpenSearch (a local MaxMind file only if one is installed), with RFC1918 detection and a
built-in well-known IP list as fallbacks. Each answer names its source (NET-237).
"""

import ipaddress
import logging

from aiohttp import web

from api.error_replies import public_json
from api.offload import in_thread
from services.geoip_service import GeoIPService, GeoLookupFailed

logger = logging.getLogger("nettap.api.geoip")

# NET-237 (GEO-4): a failed lookup is an error the page shows, never "Unknown"
LOOKUP_FAILED = {
    "error": "Couldn't look up this address: the traffic database didn't answer. Try again in a minute."
}


def _plain_ip(raw: str) -> bool:
    """An address without a zone id: ipaddress accepts "fe80::1%<anything>", newlines included,
    and the zone id then reached the log (security review L3)."""
    try:
        return getattr(ipaddress.ip_address(raw), "scope_id", None) is None
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@in_thread
def handle_geoip_lookup(request: web.Request) -> web.Response:
    """GET /api/geoip/{ip}

    Look up GeoIP data for a single IP address.
    Returns 400 for invalid IP format.
    """
    raw_ip = request.match_info["ip"]

    # OLD CODE START — L3: a zone id ("fe80::1%<text>") passed, newlines included
    # try:
    #     ipaddress.ip_address(raw_ip)
    # except ValueError:
    #     return web.json_response({"error": f"Invalid IP address: {raw_ip}"}, status=400)
    # OLD CODE END
    if not _plain_ip(raw_ip):
        return web.json_response({"error": f"Invalid IP address: {raw_ip}"}, status=400)

    geoip: GeoIPService = request.app["geoip"]
    # OLD CODE: result = geoip.lookup(raw_ip) (NET-237: a failed query answered 200 "Unknown")
    try:
        result = geoip.lookup(raw_ip)
    except GeoLookupFailed:
        return public_json(LOOKUP_FAILED, status=502)
    return web.json_response(result.to_dict())


@in_thread
def handle_geoip_batch(request: web.Request) -> web.Response:
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
        # OLD CODE START — L3: a zone id passed
        # try:
        #     ipaddress.ip_address(ip_str)
        #     ip_list.append(ip_str)
        # except ValueError:
        #     invalid.append(ip_str)
        # OLD CODE END
        (ip_list if _plain_ip(ip_str) else invalid).append(ip_str)

    if not ip_list:
        return web.json_response(
            {"error": "No valid IP addresses provided", "invalid": invalid},
            status=400,
        )

    geoip: GeoIPService = request.app["geoip"]
    # OLD CODE: results = geoip.lookup_batch(ip_list) (NET-237: failures read as "Unknown")
    try:
        results = geoip.lookup_batch(ip_list)
    except GeoLookupFailed:
        return public_json(LOOKUP_FAILED, status=502)

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
