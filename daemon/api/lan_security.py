"""
NetTap LAN Security API Routes

Registers LAN anomaly detection endpoints with the aiohttp application.
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from services.lan_anomaly_detector import LANAnomalyDetector
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.lan_security")

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


async def handle_all_anomalies(request: web.Request) -> web.Response:
    """GET /api/lan/anomalies?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    detector: LANAnomalyDetector = request.app["lan_anomaly_detector"]

    try:
        anomalies = detector.get_all_anomalies(from_ts, to_ts)
    except Exception as exc:
        logger.error("LAN anomaly detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "anomalies": anomalies,
        "count": len(anomalies),
    })


async def handle_arp_spoofing(request: web.Request) -> web.Response:
    """GET /api/lan/arp-spoofing?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    detector: LANAnomalyDetector = request.app["lan_anomaly_detector"]

    try:
        alerts = detector.detect_arp_spoofing(from_ts, to_ts)
    except Exception as exc:
        logger.error("ARP spoofing detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "alerts": alerts,
        "count": len(alerts),
    })


async def handle_rogue_dhcp(request: web.Request) -> web.Response:
    """GET /api/lan/rogue-dhcp?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    detector: LANAnomalyDetector = request.app["lan_anomaly_detector"]

    try:
        alerts = detector.detect_rogue_dhcp(from_ts, to_ts)
    except Exception as exc:
        logger.error("Rogue DHCP detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "alerts": alerts,
        "count": len(alerts),
    })


def register_lan_security_routes(
    app: web.Application, storage: StorageManager
) -> None:
    """Register LAN security API routes."""
    detector = LANAnomalyDetector(client=storage._client)
    app["lan_anomaly_detector"] = detector

    app.router.add_get("/api/lan/anomalies", handle_all_anomalies)
    app.router.add_get("/api/lan/arp-spoofing", handle_arp_spoofing)
    app.router.add_get("/api/lan/rogue-dhcp", handle_rogue_dhcp)
    logger.info("LAN security API routes registered (3 endpoints)")
