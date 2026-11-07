"""
NetTap Changelog API Routes

Registers changelog event query endpoints.
"""

import logging

from aiohttp import web
from opensearchpy import OpenSearchException

from api.offload import in_thread
from api.time_range import iso_param
from services.changelog import ChangelogService

logger = logging.getLogger("nettap.api.changelog")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time_range(request: web.Request) -> tuple[str | None, str | None]:
    """Extract optional 'from' and 'to' query parameters; an unreadable one is a 400."""
    # OLD CODE START — 2026-11-02: an unreadable from/to went into the range query unchecked
    # return request.query.get("from"), request.query.get("to")
    # OLD CODE END
    return iso_param(request, "from"), iso_param(request, "to")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@in_thread
def handle_get_events(request: web.Request) -> web.Response:
    """GET /api/changelog?from=&to=&type=&limit= — Query changelog events."""
    changelog: ChangelogService = request.app["changelog"]
    from_ts, to_ts = _parse_time_range(request)

    # Parse event types filter
    type_param = request.query.get("type", "")
    event_types = (
        [t.strip() for t in type_param.split(",") if t.strip()] if type_param else None
    )

    # Parse limit
    try:
        limit = int(request.query.get("limit", "100"))
    except (ValueError, TypeError):
        limit = 100

    try:
        events = changelog.get_events(
            from_ts=from_ts,
            to_ts=to_ts,
            event_types=event_types,
            limit=limit,
        )
    except OpenSearchException as exc:
        logger.error("OpenSearch error in changelog: %s", exc)
        return web.json_response(
            {"error": f"OpenSearch query failed: {exc}"}, status=502
        )

    return web.json_response({"events": events, "count": len(events)})


async def handle_get_event_types(request: web.Request) -> web.Response:
    """GET /api/changelog/types — List distinct event types."""
    changelog: ChangelogService = request.app["changelog"]
    types = changelog.get_event_types()
    return web.json_response({"event_types": types})


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_changelog_routes(
    app: web.Application, changelog: ChangelogService
) -> None:
    """Register changelog API routes."""
    app["changelog"] = changelog

    app.router.add_get("/api/changelog", handle_get_events)
    app.router.add_get("/api/changelog/types", handle_get_event_types)

    logger.info("Changelog API routes registered (2 endpoints)")
