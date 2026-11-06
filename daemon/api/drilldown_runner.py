"""The drill-down pages' shared request plumbing (NET-160).

run_drilldown is api/certificates.py's `_run` with room for two: at most DRILL_SLOTS
drill-downs run at once, each in a worker thread inside one budget that starts when the
request arrives, so time spent queueing counts and the event loop (and /api/health) never
waits on OpenSearch. A permit is held until its worker ends, even when the client gave up,
so a cancelled request can never let a third scan start.
"""

import asyncio
import ipaddress
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from aiohttp import web

from api.alerts import _sparkline_interval
from services.excluded_ips import (
    RFC1918_SOURCE_FILTER,
    lan_subnets_of,
    parse_single_ip,
)
from services.live_connections import _in_lan
from storage.snapshot_search import Budget, QueryFailed, TooSlow
from storage.time_slots import histogram_buckets, time_slots

logger = logging.getLogger("nettap.api.drilldown")

DRILL_SLOTS = 2
BUDGET_SECONDS = 25.0  # the web proxy gives these paths 30 s

_BUSY = "Two other look-ups are being worked out right now; try again in a minute."
_SLOW = "Working this out took too long. Try a shorter time range."


def json_error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


def ip_param(raw: Any) -> str | None:
    """The canonical form of one IPv4/IPv6 address, or None (zone ids like %eth0 too)."""
    ip = parse_single_ip(raw)
    return None if ip is None or "%" in ip else ip


def lan_check(app: web.Application) -> Callable[[str], bool]:
    """The daemon's LAN rule (IPv4 only, as every device filter applies it) at this moment."""
    subnets = lan_subnets_of(app.get("lan_filter", RFC1918_SOURCE_FILTER))

    def is_lan(ip: str) -> bool:
        try:
            return _in_lan(ipaddress.ip_address(ip), subnets)
        except ValueError:
            return False

    return is_lan


def window_filter(from_ts: str, to_ts: str) -> dict:
    return {
        "range": {
            "@timestamp": {
                "gte": from_ts,
                "lte": to_ts,
                "format": "strict_date_optional_time",
            }
        }
    }


def chart_slots(from_ts: str, to_ts: str) -> dict | None:
    """The timeline's exact slots for the window (as the alert charts pick them), or None
    when the window holds too many."""
    try:
        return time_slots(from_ts, to_ts, _sparkline_interval(from_ts, to_ts))
    except ValueError:
        return None


def timeline(reply: dict) -> list[dict]:
    """The `timeline` aggregation of a checked reply as [{t, n}], oldest first."""
    return [
        {"t": b["key_as_string"], "n": b["doc_count"]}
        for b in histogram_buckets(reply["aggregations"]["timeline"])
    ]


def iso_ms(epoch_ms: float | None) -> str | None:
    if epoch_ms is None:
        return None
    when = datetime.fromtimestamp(epoch_ms / 1000, timezone.utc)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def install(app: web.Application, client: Any) -> None:
    """The client and the shared permits, once for every drill-down route file."""
    app["drill_client"] = client
    app.setdefault("drill_slots", asyncio.Semaphore(DRILL_SLOTS))


async def run_drilldown(
    request: web.Request, work: Callable[[Budget], dict], subject: str
) -> web.Response:
    """`work(budget)` in a worker thread under a permit; 502 or 503 with a reason on failure.

    QueryFailed is a 502 (OpenSearch failed or a figure could not be made exact), running
    out of budget or permits a 503. A partial reply is never sent (#96).
    """
    budget = Budget(BUDGET_SECONDS)
    slots: asyncio.Semaphore = request.app["drill_slots"]
    try:
        await asyncio.wait_for(slots.acquire(), timeout=max(0.0, budget.remaining()))
    except asyncio.TimeoutError:
        logger.warning("Drill-down for %s: no free slot within its budget", subject)
        return json_error(_BUSY, 503)

    def release(done: asyncio.Future) -> None:
        slots.release()
        if not done.cancelled():
            done.exception()  # retrieved here when the request was cancelled before it finished

    future = asyncio.get_running_loop().run_in_executor(
        None, lambda: json.dumps(work(budget))
    )
    # The permit is held until the thread finishes, even when the client gives up first
    future.add_done_callback(release)
    try:
        body = await asyncio.shield(future)
    except TooSlow as exc:
        logger.warning("Drill-down for %s ran out of time: %s", subject, exc)
        return json_error(_SLOW, 503)
    except QueryFailed as exc:
        logger.error("Drill-down for %s failed: %s", subject, exc)
        return json_error(f"Couldn't read the network data: {exc}.", 502)
    return web.Response(text=body, content_type="application/json")
