"""
NetTap Certificate Monitor API Routes

Registers TLS certificate inventory and analysis endpoints.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any, Callable

from aiohttp import web

from api.time_range import parse_time_range
from services.cert_monitor import CertificateMonitor, CertQueryFailed
from services.cert_overview import (
    Budget,
    CertTooBig,
    CertTooSlow,
    encode_bounded,
    paginate,
)

logger = logging.getLogger("nettap.api.certificates")

_DEFAULT_RANGE_HOURS = 168  # 7 days
_ROW_LIMIT = 5_000  # per list in a reply; every figure is computed before this cut

_UNAVAILABLE = "Certificate data is unavailable right now."
_BUSY = "Certificate data is already being worked out; try again in a minute."
_SLOW = (
    "Working out certificate data for this window took too long. Try a shorter window."
)
_BIG = (
    "There is too much certificate data in this window to show. Try a shorter window."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time_range(request: web.Request) -> tuple[str, str]:
    """'from'/'to' as ISO timestamps, defaulting to the last 7 days; unreadable is a 400."""
    # OLD CODE START — 2026-11-02: an unreadable from/to (e.g. now-5m) silently became the
    # default window, so the Infrastructure page divided 24 h of events by 5 min
    # """Extract 'from' and 'to' query params with 7-day default."""
    # now = datetime.now(timezone.utc)
    # default_from = (now - timedelta(hours=_DEFAULT_RANGE_HOURS)).isoformat()
    # default_to = now.isoformat()
    #
    # raw_from = request.query.get("from", "")
    # raw_to = request.query.get("to", "")
    #
    # if raw_from:
    #     try:
    #         datetime.fromisoformat(raw_from.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_from = ""
    # if raw_to:
    #     try:
    #         datetime.fromisoformat(raw_to.replace("Z", "+00:00"))
    #     except (ValueError, TypeError):
    #         raw_to = ""
    #
    # return raw_from or default_from, raw_to or default_to
    # OLD CODE END
    return parse_time_range(request, timedelta(hours=_DEFAULT_RANGE_HOURS))


def _error(message: str) -> web.Response:
    return web.json_response({"error": message}, status=503)


def _listed(rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    shown = rows[:_ROW_LIMIT]
    return {
        **extra,
        "certificates": shown,
        "count": len(shown),
        "total": len(rows),
        "truncated": len(rows) > _ROW_LIMIT,
    }


async def _run(request: web.Request, work: Callable[[Budget], Any]) -> web.Response:
    """One certificate pass at a time, in a worker thread, inside one budget from arrival.

    Every failure is a 503 with a reason; a partial or estimated reply is never sent (#96).
    """
    budget = Budget()
    lock: asyncio.Lock = request.app["cert_lock"]
    try:
        await asyncio.wait_for(lock.acquire(), timeout=max(0.0, budget.remaining()))
    except asyncio.TimeoutError:
        return _error(_BUSY)

    def release(done: asyncio.Future) -> None:
        lock.release()
        if not done.cancelled():
            done.exception()  # retrieved here when the request was cancelled before it finished

    future = asyncio.get_running_loop().run_in_executor(
        None, lambda: encode_bounded(work(budget), budget)
    )
    # The lock is held until the thread finishes, even when the client gives up first
    future.add_done_callback(release)
    try:
        body = await asyncio.shield(future)
    except CertTooSlow:
        return _error(_SLOW)
    except CertTooBig:
        return _error(_BIG)
    except CertQueryFailed:
        # the service already logged the OpenSearch error; [] or zeros would read as "none found"
        return _error(_UNAVAILABLE)
    return web.Response(body=body, content_type="application/json")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_list_certificates(request: web.Request) -> web.Response:
    """GET /api/certificates?from=&to= — List observed TLS certificates."""
    # OLD CODE START — NET-154: ran the queries on the event loop, with no admission, budget
    # or reply-size limit, over the x509-window inventory
    # monitor: CertificateMonitor = request.app["cert_monitor"]
    # from_ts, to_ts = _parse_time_range(request)
    # excluded_ips_list = request.app.get("excluded_ips", [])
    #
    # try:
    #     certs = monitor.get_certificates(from_ts, to_ts, excluded_ips=excluded_ips_list)
    # except CertQueryFailed:
    #     # the service already logged the OpenSearch error; [] would read as "none found"
    #     return web.json_response(
    #         {"error": "Certificate data is unavailable right now."}, status=503
    #     )
    # return web.json_response(
    #     {
    #         "from": from_ts,
    #         "to": to_ts,
    #         "certificates": certs,
    #         "count": len(certs),
    #     }
    # )
    # OLD CODE END
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded = request.app.get("excluded_ips", [])
    return await _run(
        request,
        lambda b: _listed(
            monitor.get_certificates(from_ts, to_ts, excluded, b),
            **{"from": from_ts, "to": to_ts},
        ),
    )


async def handle_expiring_certs(request: web.Request) -> web.Response:
    """GET /api/certificates/expiring?days=30&from=&to= — Expiring certificates."""
    # OLD CODE START — NET-154: ran the queries on the event loop, with no admission, budget
    # or reply-size limit, over the x509-window inventory
    # monitor: CertificateMonitor = request.app["cert_monitor"]
    # from_ts, to_ts = _parse_time_range(request)
    # excluded_ips_list = request.app.get("excluded_ips", [])
    #
    # try:
    #     days = int(request.query.get("days", "30"))
    # except (ValueError, TypeError):
    #     days = 30
    #
    # try:
    #     certs = monitor.get_expiring_certs(
    #         days=days, from_ts=from_ts, to_ts=to_ts, excluded_ips=excluded_ips_list
    #     )
    # except CertQueryFailed:
    #     # the service already logged the OpenSearch error; [] would read as "none found"
    #     return web.json_response(
    #         {"error": "Certificate data is unavailable right now."}, status=503
    #     )
    # return web.json_response(
    #     {
    #         "from": from_ts,
    #         "to": to_ts,
    #         "days": days,
    #         "certificates": certs,
    #         "count": len(certs),
    #     }
    # )
    # OLD CODE END
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded = request.app.get("excluded_ips", [])
    try:
        days = int(request.query.get("days", "30"))
    except (ValueError, TypeError):
        days = 30
    return await _run(
        request,
        lambda b: _listed(
            monitor.get_expiring_certs(days, from_ts, to_ts, excluded, b),
            **{"from": from_ts, "to": to_ts, "days": days},
        ),
    )


async def handle_self_signed(request: web.Request) -> web.Response:
    """GET /api/certificates/self-signed?from=&to= — Self-signed certificates."""
    # OLD CODE START — NET-154: ran the queries on the event loop, with no admission, budget
    # or reply-size limit, over the x509-window inventory
    # monitor: CertificateMonitor = request.app["cert_monitor"]
    # from_ts, to_ts = _parse_time_range(request)
    # excluded_ips_list = request.app.get("excluded_ips", [])
    #
    # try:
    #     certs = monitor.detect_self_signed(
    #         from_ts, to_ts, excluded_ips=excluded_ips_list
    #     )
    # except CertQueryFailed:
    #     # the service already logged the OpenSearch error; [] would read as "none found"
    #     return web.json_response(
    #         {"error": "Certificate data is unavailable right now."}, status=503
    #     )
    # return web.json_response(
    #     {
    #         "from": from_ts,
    #         "to": to_ts,
    #         "certificates": certs,
    #         "count": len(certs),
    #     }
    # )
    # OLD CODE END
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded = request.app.get("excluded_ips", [])
    return await _run(
        request,
        lambda b: _listed(
            monitor.detect_self_signed(from_ts, to_ts, excluded, b),
            **{"from": from_ts, "to": to_ts},
        ),
    )


async def handle_issuer_changes(request: web.Request) -> web.Response:
    """GET /api/certificates/issuer-changes?from=&to= — Issuer change detections."""
    # OLD CODE START — NET-154: ran the queries on the event loop, with no admission, budget
    # or reply-size limit, over the x509-window inventory
    # monitor: CertificateMonitor = request.app["cert_monitor"]
    # from_ts, to_ts = _parse_time_range(request)
    # excluded_ips_list = request.app.get("excluded_ips", [])
    #
    # try:
    #     changes = monitor.detect_issuer_changes(
    #         from_ts, to_ts, excluded_ips=excluded_ips_list
    #     )
    # except CertQueryFailed:
    #     # the service already logged the OpenSearch error; [] would read as "none found"
    #     return web.json_response(
    #         {"error": "Certificate data is unavailable right now."}, status=503
    #     )
    # return web.json_response(
    #     {
    #         "from": from_ts,
    #         "to": to_ts,
    #         "changes": changes,
    #         "count": len(changes),
    #     }
    # )
    # OLD CODE END
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded = request.app.get("excluded_ips", [])

    def work(b: Budget) -> dict[str, Any]:
        changes = monitor.detect_issuer_changes(from_ts, to_ts, excluded, b)
        shown = changes[:_ROW_LIMIT]
        return {
            "from": from_ts,
            "to": to_ts,
            "changes": shown,
            "count": len(shown),
            "total": len(changes),
        }

    return await _run(request, work)


async def handle_cert_stats(request: web.Request) -> web.Response:
    """GET /api/certificates/stats?from=&to= — Certificate hero card stats."""
    # OLD CODE START — NET-154: ran the queries on the event loop, with no admission, budget
    # or reply-size limit, over the x509-window inventory
    # monitor: CertificateMonitor = request.app["cert_monitor"]
    # from_ts, to_ts = _parse_time_range(request)
    # excluded_ips_list = request.app.get("excluded_ips", [])
    #
    # try:
    #     stats = monitor.get_cert_stats(from_ts, to_ts, excluded_ips=excluded_ips_list)
    # # OLD CODE START — #96: only the stats query raised; the issuer-change count read 0 on failure
    # # except CertStatsUnavailable:
    # # OLD CODE END
    # except CertQueryFailed:
    #     # the service already logged the OpenSearch error; zeros would read as real counts
    #     return web.json_response(
    #         {"error": "Certificate statistics are unavailable right now."}, status=503
    #     )
    # return web.json_response(stats)
    # OLD CODE END
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded = request.app.get("excluded_ips", [])
    return await _run(
        request, lambda b: monitor.get_cert_stats(from_ts, to_ts, excluded, b)
    )


async def handle_certificate_overview(request: web.Request) -> web.Response:
    """GET /api/certificates/overview?from=&to= — Every figure the Certificates page shows."""
    monitor: CertificateMonitor = request.app["cert_monitor"]
    from_ts, to_ts = _parse_time_range(request)
    excluded = request.app.get("excluded_ips", [])
    return await _run(
        request,
        lambda b: paginate(monitor.overview(from_ts, to_ts, excluded, b), _ROW_LIMIT),
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_certificate_routes(
    app: web.Application, monitor: CertificateMonitor
) -> None:
    """Register certificate monitor API routes."""
    app["cert_monitor"] = monitor
    app["cert_lock"] = asyncio.Lock()

    app.router.add_get("/api/certificates", handle_list_certificates)
    app.router.add_get("/api/certificates/overview", handle_certificate_overview)
    app.router.add_get("/api/certificates/expiring", handle_expiring_certs)
    app.router.add_get("/api/certificates/self-signed", handle_self_signed)
    app.router.add_get("/api/certificates/issuer-changes", handle_issuer_changes)
    app.router.add_get("/api/certificates/stats", handle_cert_stats)

    logger.info("Certificate monitor API routes registered (6 endpoints)")
