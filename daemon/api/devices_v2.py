"""
NetTap Device Registry API Routes (v2)

Provides REST endpoints for the DeviceRegistry service and UniFi
integration. These endpoints operate on the MAC-keyed ``nettap-devices``
index, separate from the original IP-based device inventory in devices.py.

Endpoints:
    GET  /api/devices/registry              — list all discovered devices
    GET  /api/devices/registry/{mac}        — single device detail
    GET  /api/devices/registry/{mac}/traffic — traffic for one device
    GET  /api/devices/registry/search       — search devices
    POST /api/integrations/unifi/configure  — set UniFi credentials
    GET  /api/integrations/unifi/status     — connection status
    POST /api/integrations/unifi/test       — test connectivity
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web

from services.device_registry import DeviceRegistry
from services.unifi_integration import UnifiIntegration

logger = logging.getLogger("nettap.api.devices_v2")

_DEFAULT_RANGE_HOURS = 24


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Extract 'from' and 'to' query parameters as ISO timestamps."""
    now = datetime.now(timezone.utc)
    default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
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


def _parse_int_param(request: web.Request, name: str, default: int) -> int:
    """Parse an integer query parameter with a fallback default."""
    raw = request.query.get(name, "")
    if raw:
        try:
            return max(1, int(raw))
        except (ValueError, TypeError):
            pass
    return default


def _get_registry(request: web.Request) -> DeviceRegistry:
    """Retrieve the DeviceRegistry from the app."""
    registry = request.app.get("device_registry")
    if registry is None:
        raise web.HTTPServiceUnavailable(
            text="Device registry not initialized"
        )
    return registry


def _get_unifi(request: web.Request) -> UnifiIntegration:
    """Retrieve the UnifiIntegration from the app."""
    unifi = request.app.get("unifi_integration")
    if unifi is None:
        raise web.HTTPServiceUnavailable(
            text="UniFi integration not initialized"
        )
    return unifi


# ---------------------------------------------------------------------------
# Device registry handlers
# ---------------------------------------------------------------------------


async def handle_registry_list(request: web.Request) -> web.Response:
    """GET /api/devices/registry?limit=100&offset=0"""
    registry = _get_registry(request)
    limit = min(_parse_int_param(request, "limit", 100), 500)
    offset = _parse_int_param(request, "offset", 0) - 1  # Convert 1-based to 0-based
    offset = max(0, offset)

    devices = registry.get_all_devices(limit=limit, offset=offset)

    # Add display_name to each device
    for device in devices:
        device["display_name"] = registry.get_display_name(device)

    return web.json_response({
        "devices": devices,
        "count": len(devices),
        "limit": limit,
        "offset": offset,
    })


async def handle_registry_detail(request: web.Request) -> web.Response:
    """GET /api/devices/registry/{mac}"""
    registry = _get_registry(request)
    mac = request.match_info["mac"]

    device = registry.get_device(mac)
    if device is None:
        return web.json_response(
            {"error": f"Device not found: {mac}"}, status=404
        )

    device["display_name"] = registry.get_display_name(device)
    return web.json_response({"device": device})


async def handle_registry_traffic(request: web.Request) -> web.Response:
    """GET /api/devices/registry/{mac}/traffic?from=&to="""
    registry = _get_registry(request)
    mac = request.match_info["mac"]
    from_ts, to_ts = _parse_time_range(request)

    device = registry.get_device(mac)
    if device is None:
        return web.json_response(
            {"error": f"Device not found: {mac}"}, status=404
        )

    traffic = registry.get_device_traffic(mac, from_ts, to_ts)
    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "traffic": traffic,
    })


async def handle_registry_search(request: web.Request) -> web.Response:
    """GET /api/devices/registry/search?q="""
    registry = _get_registry(request)
    query_str = request.query.get("q", "").strip()

    if not query_str:
        return web.json_response(
            {"error": "Query parameter 'q' is required"}, status=400
        )

    devices = registry.search_devices(query_str)
    for device in devices:
        device["display_name"] = registry.get_display_name(device)

    return web.json_response({
        "query": query_str,
        "devices": devices,
        "count": len(devices),
    })


# ---------------------------------------------------------------------------
# UniFi integration handlers
# ---------------------------------------------------------------------------


async def handle_unifi_configure(request: web.Request) -> web.Response:
    """POST /api/integrations/unifi/configure

    Body: {"controller_url": "...", "username": "...", "password": "...", "site": "default"}
    """
    unifi = _get_unifi(request)

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"}, status=400
        )

    controller_url = body.get("controller_url")
    username = body.get("username")
    password = body.get("password")
    site = body.get("site", "default")

    if not controller_url or not username or not password:
        return web.json_response(
            {"error": "controller_url, username, and password are required"},
            status=400,
        )

    unifi.configure(controller_url, username, password, site)
    return web.json_response({
        "status": "configured",
        "controller_url": controller_url,
    })


async def handle_unifi_status(request: web.Request) -> web.Response:
    """GET /api/integrations/unifi/status"""
    unifi = _get_unifi(request)
    return web.json_response(unifi.get_status())


async def handle_unifi_test(request: web.Request) -> web.Response:
    """POST /api/integrations/unifi/test"""
    unifi = _get_unifi(request)

    if not unifi.is_configured:
        return web.json_response(
            {"success": False, "error": "UniFi integration not configured"},
            status=400,
        )

    success = await unifi.test_connection()
    return web.json_response({
        "success": success,
        "status": unifi.get_status(),
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_devices_v2_routes(
    app: web.Application,
    device_registry: DeviceRegistry,
    unifi_integration: UnifiIntegration,
) -> None:
    """Register device registry and UniFi integration routes."""
    app["device_registry"] = device_registry
    app["unifi_integration"] = unifi_integration

    # Device registry endpoints
    # Note: search must be registered BEFORE {mac} to avoid routing conflicts
    app.router.add_get("/api/devices/registry/search", handle_registry_search)
    app.router.add_get("/api/devices/registry", handle_registry_list)
    app.router.add_get("/api/devices/registry/{mac}", handle_registry_detail)
    app.router.add_get(
        "/api/devices/registry/{mac}/traffic", handle_registry_traffic
    )

    # UniFi integration endpoints
    app.router.add_post(
        "/api/integrations/unifi/configure", handle_unifi_configure
    )
    app.router.add_get("/api/integrations/unifi/status", handle_unifi_status)
    app.router.add_post("/api/integrations/unifi/test", handle_unifi_test)

    logger.info("Device Registry v2 + UniFi routes registered (7 endpoints)")
