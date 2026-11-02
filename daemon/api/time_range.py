"""
NetTap shared from/to query parsing for the time-windowed API routes.

An unreadable bound is a 400, never the default window: on the device the
Infrastructure page sent from=now-5m, got 24 h of connections back, divided by
300 s and showed 1,601 evt/s for a real rate of about 5/s.
"""

import json
from datetime import datetime, timedelta, timezone

from aiohttp import web

_EXAMPLE = "2026-11-02T21:00:00Z"


def iso_param(request: web.Request, name: str) -> str | None:
    """The `name` query parameter as sent (None if absent); 400 if non-empty and not ISO 8601."""
    raw = request.query.get(name)
    if raw:
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(
                text=json.dumps(
                    {"error": f"{name} must be an ISO 8601 time such as {_EXAMPLE}"}
                ),
                content_type="application/json",
            ) from None
    return raw


def parse_time_range(request: web.Request, default_span: timedelta) -> tuple[str, str]:
    """(from, to) ISO strings; an absent or empty bound is the last `default_span` up to now."""
    now = datetime.now(timezone.utc)
    # OLD CODE START — a backwards range went on to OpenSearch (a 502, or an empty answer)
    # return (
    #     iso_param(request, "from") or (now - default_span).isoformat(),
    #     iso_param(request, "to") or now.isoformat(),
    # )
    # OLD CODE END
    from_ts = iso_param(request, "from") or (now - default_span).isoformat()
    to_ts = iso_param(request, "to") or now.isoformat()
    if _utc(from_ts) > _utc(to_ts):
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "from must not be later than to"}),
            content_type="application/json",
        )
    return from_ts, to_ts


def _utc(ts: str) -> datetime:
    """A validated ISO time as an aware datetime; no zone means UTC, as OpenSearch reads it."""
    when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
