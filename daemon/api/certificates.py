"""
NetTap Certificate Monitor API Routes

Registers TLS certificate inventory and analysis endpoints.
"""

import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web

from services.cert_monitor import CertificateMonitor

logger = logging.getLogger("nettap.api.certificates")

_DEFAULT_RANGE_HOURS = 168  # 7 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """Extract 'from' and 'to' query params with 7-day default."""
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

    return raw_from or default_from, raw_to or default_to


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_list_certificates(request: web.Request) -> web.Response:
    """GET /api/certificates?from=&to= — List observed TLS certificates."""
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    certs = monitor.get_certificates(from_ts, to_ts, excluded_ips=excluded_ips_list)
    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "certificates": certs,
        "count": len(certs),
    })


async def handle_expiring_certs(request: web.Request) -> web.Response:
    """GET /api/certificates/expiring?days=30&from=&to= — Expiring certificates."""
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    try:
        days = int(request.query.get("days", "30"))
    except (ValueError, TypeError):
        days = 30

    certs = monitor.get_expiring_certs(days=days, from_ts=from_ts, to_ts=to_ts, excluded_ips=excluded_ips_list)
    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "days": days,
        "certificates": certs,
        "count": len(certs),
    })


async def handle_self_signed(request: web.Request) -> web.Response:
    """GET /api/certificates/self-signed?from=&to= — Self-signed certificates."""
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    certs = monitor.detect_self_signed(from_ts, to_ts, excluded_ips=excluded_ips_list)
    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "certificates": certs,
        "count": len(certs),
    })


async def handle_issuer_changes(request: web.Request) -> web.Response:
    """GET /api/certificates/issuer-changes?from=&to= — Issuer change detections."""
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    changes = monitor.detect_issuer_changes(from_ts, to_ts, excluded_ips=excluded_ips_list)
    return web.json_response({
        "from": from_ts,
        "to": to_ts,
        "changes": changes,
        "count": len(changes),
    })


async def handle_cert_stats(request: web.Request) -> web.Response:
    """GET /api/certificates/stats?from=&to= — Certificate hero card stats."""
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded_ips_list = request.app.get("excluded_ips", [])

    stats = monitor.get_cert_stats(from_ts, to_ts, excluded_ips=excluded_ips_list)
    return web.json_response(stats)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_certificate_routes(
    app: web.Application, monitor: CertificateMonitor
) -> None:
    """Register certificate monitor API routes."""
    app["cert_monitor"] = monitor

    app.router.add_get("/api/certificates", handle_list_certificates)
    app.router.add_get("/api/certificates/expiring", handle_expiring_certs)
    app.router.add_get("/api/certificates/self-signed", handle_self_signed)
    app.router.add_get("/api/certificates/issuer-changes", handle_issuer_changes)
    app.router.add_get("/api/certificates/stats", handle_cert_stats)

    logger.info("Certificate monitor API routes registered (5 endpoints)")
