"""
NetTap Threat Intelligence API Routes

Registers endpoints for the /threats page: unified threat report,
beaconing detection, lateral movement, DNS anomalies, and
auto-investigations.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.threats")

_DEFAULT_RANGE_HOURS = 24
NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")


def _parse_time_range(request: web.Request) -> tuple[str, str]:
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


def _get_client(request: web.Request):
    storage: StorageManager = request.app["storage"]
    return storage._client


async def handle_threat_report(request: web.Request) -> web.Response:
    """GET /api/threats/report?from=&to= — Unified threat report."""
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    from services.investigation import generate_threat_report
    try:
        report = await generate_threat_report(client, from_ts, to_ts)
    except Exception as exc:
        logger.error("Threat report generation failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({"from": from_ts, "to": to_ts, **report})


async def handle_beaconing(request: web.Request) -> web.Response:
    """GET /api/threats/beaconing?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    from services.threat_detection import detect_beaconing
    try:
        beacons = detect_beaconing(client, from_ts, to_ts)
    except Exception as exc:
        logger.error("Beaconing detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({"from": from_ts, "to": to_ts, "beacons": beacons, "total": len(beacons)})


async def handle_lateral_movement(request: web.Request) -> web.Response:
    """GET /api/threats/lateral?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    from services.threat_detection import detect_lateral_movement
    try:
        movements = detect_lateral_movement(client, from_ts, to_ts)
    except Exception as exc:
        logger.error("Lateral movement detection failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({"from": from_ts, "to": to_ts, "movements": movements, "total": len(movements)})


async def handle_dns_anomalies(request: web.Request) -> web.Response:
    """GET /api/threats/dns-anomalies?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    from services.threat_detection import analyze_dns_anomalies
    try:
        anomalies = analyze_dns_anomalies(client, from_ts, to_ts)
    except Exception as exc:
        logger.error("DNS anomaly analysis failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({"from": from_ts, "to": to_ts, **anomalies})


async def handle_threat_intel(request: web.Request) -> web.Response:
    """GET /api/threats/intel?from=&to= — Populate TI from Suricata + return matches."""
    from_ts, to_ts = _parse_time_range(request)
    client = _get_client(request)

    from services.threat_intel import ThreatIntelService
    ti = ThreatIntelService()
    ti.load_cache()

    # Bootstrap from Suricata data
    new_count = ti.populate_from_suricata(client, from_ts, to_ts)
    feeds = ti.get_all_matches()

    return web.json_response({
        "from": from_ts, "to": to_ts,
        "new_indicators": new_count,
        "feeds": feeds,
        "total_indicators": sum(f["indicator_count"] for f in feeds.values()),
    })


def register_threat_routes(app: web.Application, storage_manager: StorageManager) -> None:
    app.router.add_get("/api/threats/report", handle_threat_report)
    app.router.add_get("/api/threats/beaconing", handle_beaconing)
    app.router.add_get("/api/threats/lateral", handle_lateral_movement)
    app.router.add_get("/api/threats/dns-anomalies", handle_dns_anomalies)
    app.router.add_get("/api/threats/intel", handle_threat_intel)
    logger.info("Threat Intelligence API routes registered (5 endpoints)")
