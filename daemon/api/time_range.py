"""
NetTap shared from/to query parsing for the time-windowed API routes.

An unreadable bound is a 400, never the default window: on the device the
Infrastructure page sent from=now-5m, got 24 h of connections back, divided by
300 s and showed 1,601 evt/s for a real rate of about 5/s.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web

from storage.time_slots import interval_seconds, slot_count

logger = logging.getLogger("nettap.api.time_range")

_EXAMPLE = "2026-11-02T21:00:00Z"
# NET-249: the owner's bucket table (the web's DRILL_RANGES), which every pickable chart offers
BUCKET_TABLE = frozenset({"1m", "5m", "1h", "3h"})
# Its finest chart is 289 slots; 1,000 at 3 h is 125 days
SLOT_BUDGET = 1_000
TOO_MANY_SLOTS = "Too many points for this window; pick a longer bucket"


def _bad_request(message: str) -> web.HTTPBadRequest:
    return web.HTTPBadRequest(
        text=json.dumps({"error": message}), content_type="application/json"
    )


def slot_interval(
    request: web.Request,
    from_ts: str,
    to_ts: str,
    allowed: frozenset[str] | set[str],
    default: str,
    budget: int = SLOT_BUDGET,
) -> str:
    """The chart's bucket: `?interval=`, or `default` when absent, checked with the window
    before any search (NET-249). 400 if it isn't in `allowed` or makes more than `budget`
    slots, the same whether the interval was sent or defaulted."""
    interval = request.query.get("interval") or default
    if interval not in allowed:
        # OLD CODE: logger.info("%s: interval %.20r refused", request.path, interval) (review: a
        # decoded %0A in the path wrote a line of its own; %r keeps the record on one line)
        logger.info("%r: interval %.20r refused", request.path, interval)
        raise _bad_request(
            "Unknown interval; use one of "
            + ", ".join(sorted(allowed, key=interval_seconds))
        )
    if slot_count(from_ts, to_ts, interval) > budget:
        # OLD CODE: "%s: %s from %s to %s is over %d slots" (review: %r, as above; fromisoformat
        # takes any one character between date and time, so from/to can carry a newline too)
        logger.info(
            "%r: %s from %r to %r is over %d slots",
            request.path,
            interval,
            from_ts,
            to_ts,
            budget,
        )
        raise _bad_request(TOO_MANY_SLOTS)
    return interval


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
