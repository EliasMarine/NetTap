"""
NetTap Device Baseline API Routes

Registers device baseline management endpoints with the aiohttp application.
These endpoints allow viewing/modifying the known-device baseline and checking
for new (previously unseen) devices on the network.
"""

import logging

from aiohttp import web

from services.device_baseline import DeviceBaseline

logger = logging.getLogger("nettap.api.baseline")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_get_baseline(request: web.Request) -> web.Response:
    """GET /api/devices/baseline

    Returns the current known-device baseline.
    """
    baseline: DeviceBaseline = request.app["device_baseline"]
    devices = baseline.get_baseline()

    return web.json_response({
        "count": baseline.get_baseline_count(),
        "devices": devices,
    })


async def handle_check_baseline(request: web.Request) -> web.Response:
    """GET /api/devices/baseline/check

    Check for new devices by comparing currently-seen devices against the
    baseline. Requires that a recent device list is available in the app
    context (populated by the device inventory module or passed as query).

    For simplicity, this endpoint accepts a JSON body with a 'devices' list
    via POST, or reads from app context if available.
    """
    baseline: DeviceBaseline = request.app["device_baseline"]

    # Try to get current devices from app context (set by device scan cycle)
    current_devices = request.app.get("current_devices", [])

    alerts = baseline.check_devices(current_devices)

    return web.json_response({
        "baseline_count": baseline.get_baseline_count(),
        "new_device_count": len(alerts),
        "alerts": alerts,
    })


async def handle_check_baseline_post(request: web.Request) -> web.Response:
    """POST /api/devices/baseline/check

    Check for new devices by comparing a provided device list against the
    baseline. Accepts JSON body: {"devices": [{"mac": "...", "ip": "...", ...}]}
    """
    baseline: DeviceBaseline = request.app["device_baseline"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"}, status=400
        )

    current_devices = body.get("devices", [])
    if not isinstance(current_devices, list):
        return web.json_response(
            {"error": "'devices' must be a list"}, status=400
        )

    alerts = baseline.check_devices(current_devices)

    return web.json_response({
        "baseline_count": baseline.get_baseline_count(),
        "new_device_count": len(alerts),
        "alerts": alerts,
    })


async def handle_add_to_baseline(request: web.Request) -> web.Response:
    """POST /api/devices/baseline/add

    Add a device to the known-device baseline.
    Accepts JSON body: {"mac": "AA:BB:CC:DD:EE:FF", "ip": "...", ...}
    """
    baseline: DeviceBaseline = request.app["device_baseline"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"}, status=400
        )

    mac = body.get("mac", "")
    if not mac or not isinstance(mac, str):
        return web.json_response(
            {"error": "Missing or invalid 'mac' field"}, status=400
        )

    device_info = {
        k: v for k, v in body.items() if k != "mac"
    }

    baseline.add_to_baseline(mac, device_info)

    return web.json_response({
        "result": "added",
        "mac": mac.strip().upper(),
        "baseline_count": baseline.get_baseline_count(),
    })


async def handle_remove_from_baseline(request: web.Request) -> web.Response:
    """DELETE /api/devices/baseline/{mac}

    Remove a device from the known-device baseline by MAC address.
    """
    mac = request.match_info["mac"]
    baseline: DeviceBaseline = request.app["device_baseline"]

    if baseline.remove_from_baseline(mac):
        return web.json_response({
            "result": "removed",
            "mac": mac.strip().upper(),
            "baseline_count": baseline.get_baseline_count(),
        })
    else:
        return web.json_response(
            {"error": f"Device {mac} not found in baseline"}, status=404
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_baseline_routes(
    app: web.Application,
    device_baseline: DeviceBaseline,
) -> None:
    """Register all device baseline API routes on the given aiohttp application."""
    app["device_baseline"] = device_baseline
    app.router.add_get("/api/devices/baseline", handle_get_baseline)
    app.router.add_get("/api/devices/baseline/check", handle_check_baseline)
    app.router.add_post("/api/devices/baseline/check", handle_check_baseline_post)
    app.router.add_post("/api/devices/baseline/add", handle_add_to_baseline)
    app.router.add_delete("/api/devices/baseline/{mac}", handle_remove_from_baseline)
    logger.info("Device baseline API routes registered (5 endpoints)")
