"""
NetTap IoT Monitor API Routes

Registers IoT device monitoring endpoints with the aiohttp application.
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web

from services.iot_monitor import IoTMonitor
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.iot")

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


async def handle_iot_devices(request: web.Request) -> web.Response:
    """GET /api/iot/devices"""
    iot: IoTMonitor = request.app["iot_monitor"]
    devices = iot.get_iot_devices()
    return web.json_response({"devices": devices, "count": len(devices)})


async def handle_device_baseline(request: web.Request) -> web.Response:
    """GET /api/iot/devices/{mac}/baseline"""
    mac = request.match_info["mac"]
    iot: IoTMonitor = request.app["iot_monitor"]

    baseline = iot.get_device_baseline(mac)
    if baseline is None:
        # Try to build one
        try:
            baseline = iot.build_baseline(mac)
        except Exception as exc:
            logger.error("Failed to build baseline for %s: %s", mac, exc)
            return web.json_response(
                {"error": f"Failed to build baseline: {exc}"}, status=500
            )

    return web.json_response({"mac": mac, "baseline": baseline})


async def handle_iot_anomalies(request: web.Request) -> web.Response:
    """GET /api/iot/anomalies?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    iot: IoTMonitor = request.app["iot_monitor"]

    try:
        anomalies = iot.get_anomalies(from_ts, to_ts)
    except Exception as exc:
        logger.error("IoT anomaly detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "anomalies": anomalies,
        "count": len(anomalies),
    })


async def handle_classify_device(request: web.Request) -> web.Response:
    """POST /api/iot/devices/{mac}/classify"""
    mac = request.match_info["mac"]
    iot: IoTMonitor = request.app["iot_monitor"]

    try:
        body = await request.json()
    except Exception:
        body = {}

    is_iot = iot.classify_as_iot(mac, body)

    return web.json_response({
        "mac": mac,
        "is_iot": is_iot,
        "message": f"Device {mac} {'classified as IoT' if is_iot else 'not classified as IoT'}",
    })


def register_iot_routes(app: web.Application, storage: StorageManager) -> None:
    """Register IoT monitoring API routes."""
    iot_monitor = IoTMonitor(client=storage._client)
    app["iot_monitor"] = iot_monitor

    app.router.add_get("/api/iot/devices", handle_iot_devices)
    app.router.add_get("/api/iot/devices/{mac}/baseline", handle_device_baseline)
    app.router.add_get("/api/iot/anomalies", handle_iot_anomalies)
    app.router.add_post("/api/iot/devices/{mac}/classify", handle_classify_device)
    logger.info("IoT monitoring API routes registered (4 endpoints)")
