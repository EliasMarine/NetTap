"""
NetTap DNS Analytics API Routes

Registers DNS analysis endpoints with the aiohttp application.
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web
from opensearchpy import OpenSearchException

from services.dns_analytics import DNSAnalytics
from storage.manager import StorageManager

logger = logging.getLogger("nettap.api.dns")

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


async def handle_top_domains(request: web.Request) -> web.Response:
    """GET /api/dns/top-domains?from=&to=&limit=50"""
    from_ts, to_ts = _parse_time_range(request)
    limit = int(request.query.get("limit", "50"))
    dns: DNSAnalytics = request.app["dns_analytics"]

    try:
        result = dns.get_top_domains(from_ts, to_ts, limit)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in dns/top-domains: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({
        "from": from_ts, "to": to_ts, "domains": result
    })


async def handle_device_dns(request: web.Request) -> web.Response:
    """GET /api/dns/device/{ip}?from=&to="""
    device_ip = request.match_info["ip"]
    from_ts, to_ts = _parse_time_range(request)
    dns: DNSAnalytics = request.app["dns_analytics"]

    try:
        result = dns.get_device_dns(device_ip, from_ts, to_ts)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in dns/device: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({
        "device_ip": device_ip, "from": from_ts, "to": to_ts, "domains": result
    })


async def handle_nxdomain(request: web.Request) -> web.Response:
    """GET /api/dns/nxdomain?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    dns: DNSAnalytics = request.app["dns_analytics"]

    try:
        result = dns.get_nxdomain_errors(from_ts, to_ts)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in dns/nxdomain: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({
        "from": from_ts, "to": to_ts, "nxdomains": result
    })


async def handle_query_types(request: web.Request) -> web.Response:
    """GET /api/dns/types?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    dns: DNSAnalytics = request.app["dns_analytics"]

    try:
        result = dns.get_query_type_distribution(from_ts, to_ts)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in dns/types: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({
        "from": from_ts, "to": to_ts, "types": result
    })


async def handle_timeline(request: web.Request) -> web.Response:
    """GET /api/dns/timeline?from=&to=&interval=1m"""
    from_ts, to_ts = _parse_time_range(request)
    interval = request.query.get("interval", "1m")
    dns: DNSAnalytics = request.app["dns_analytics"]

    try:
        result = dns.get_dns_timeline(from_ts, to_ts, interval)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in dns/timeline: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({
        "from": from_ts, "to": to_ts, "interval": interval, "series": result
    })


async def handle_suspicious(request: web.Request) -> web.Response:
    """GET /api/dns/suspicious?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    dns: DNSAnalytics = request.app["dns_analytics"]

    try:
        result = dns.get_suspicious_dns(from_ts, to_ts)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in dns/suspicious: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({
        "from": from_ts, "to": to_ts, "suspicious": result
    })


async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/dns/stats?from=&to="""
    from_ts, to_ts = _parse_time_range(request)
    dns: DNSAnalytics = request.app["dns_analytics"]

    try:
        result = dns.get_stats(from_ts, to_ts)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in dns/stats: %s", exc)
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({"from": from_ts, "to": to_ts, **result})


def register_dns_routes(app: web.Application, storage: StorageManager) -> None:
    """Register DNS analytics API routes."""
    dns_analytics = DNSAnalytics(client=storage._client)
    app["dns_analytics"] = dns_analytics

    app.router.add_get("/api/dns/top-domains", handle_top_domains)
    app.router.add_get("/api/dns/device/{ip}", handle_device_dns)
    app.router.add_get("/api/dns/nxdomain", handle_nxdomain)
    app.router.add_get("/api/dns/types", handle_query_types)
    app.router.add_get("/api/dns/timeline", handle_timeline)
    app.router.add_get("/api/dns/suspicious", handle_suspicious)
    app.router.add_get("/api/dns/stats", handle_stats)
    logger.info("DNS analytics API routes registered (7 endpoints)")
