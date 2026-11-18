"""
Usage ledger routes (NET-329, roadmap F4 §4.5) and the owner's time zone (§4.1).

Endpoints:
    GET  /api/usage/daily?from=YYYY-MM-DD&to=YYYY-MM-DD  Each local day's totals and status
    GET  /api/usage/month?year=&month=                    One local month, with its projection
    POST /api/usage/recount                               A new sweep; no total is reset
    GET  /api/settings/timezone                           {tz, set}
    PUT  /api/settings/timezone                           {tz} -> {tz, set: true}

Every read answers from the ledger's published snapshot, so it never waits on OpenSearch.
"""

import logging
import re
from datetime import date

from aiohttp import web

from api.error_replies import public_json
from api.offload import run_blocking
from api.time_range import (
    _YEARS,
)  # 1970 to 9998: every local day has a UTC start and end
from services import owner_tz, usage_report
from services.usage_ledger import UsageLedger

logger = logging.getLogger("nettap.api.usage")

LEDGER_JOB = "usage-ledger"
MAX_RANGE_DAYS = 400
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _day(raw: str | None) -> date:
    if not raw or not _DATE.fullmatch(raw):
        raise ValueError("'from' and 'to' must be dates like 2026-11-18")
    day = date.fromisoformat(raw)  # ValueError for 2026-02-30
    if day.year not in _YEARS:
        raise ValueError("'from' and 'to' must be dates from 1970 on")
    return day


def _range(request: web.Request) -> tuple[date, date]:
    first = _day(request.query.get("from"))
    last = _day(request.query.get("to"))
    if last < first:
        raise ValueError("'to' is before 'from'")
    if (last - first).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"A range can cover at most {MAX_RANGE_DAYS} days")
    return first, last


def _month(request: web.Request) -> tuple[int | None, int | None]:
    """year and month as asked; None where absent (month_reply fills in the owner's month)."""
    try:
        year, month = (
            int(raw) if (raw := request.query.get(k)) is not None else None
            for k in ("year", "month")
        )
    except ValueError:
        raise ValueError("'year' and 'month' must be whole numbers") from None
    if (year is not None and year not in _YEARS) or (
        month is not None and not 1 <= month <= 12
    ):
        raise ValueError("'month' must be 1 to 12 and 'year' 1970 or later")
    return year, month


def month_reply(
    ledger: UsageLedger, year: int | None = None, month: int | None = None
) -> dict:
    """The /api/usage/month answer; the owner's current month by default (handle_cap's too)."""
    snapshot, now, owner = ledger.snapshot(), ledger.now(), owner_tz.read()
    default = usage_report.current_month(snapshot, now, owner)
    return usage_report.month(
        snapshot,
        year or default[0],
        month or default[1],
        now,
        ledger.current_rules(),
        owner,
    )


def _bad(exc: ValueError) -> web.Response:
    return web.json_response({"error": str(exc)}, status=400)


async def handle_daily(request: web.Request) -> web.Response:
    """GET /api/usage/daily?from=&to= (local dates, both included, at most 400 days)."""
    ledger: UsageLedger = request.app["usage_ledger"]
    try:
        first, last = _range(request)
    except ValueError as exc:
        return _bad(exc)
    report = usage_report.daily(
        ledger.snapshot(),
        first,
        last,
        ledger.now(),
        ledger.current_rules(),
        owner_tz.read(),
    )
    return web.json_response(report)


async def handle_month(request: web.Request) -> web.Response:
    """GET /api/usage/month?year=&month= (the owner's current local month by default)."""
    ledger: UsageLedger = request.app["usage_ledger"]
    try:
        year, month = _month(request)
    except ValueError as exc:
        return _bad(exc)
    return web.json_response(month_reply(ledger, year, month))


async def handle_recount(request: web.Request) -> web.Response:
    """POST /api/usage/recount: a new sweep at the next pass (Codex r2 #10)."""
    ledger: UsageLedger = request.app["usage_ledger"]
    sweep_id = ledger.request_sweep()
    request.app["scheduler"].request_run(LEDGER_JOB)
    return web.json_response(
        {"sweep_requested": True, "sweep_id": sweep_id}, status=202
    )


async def handle_get_timezone(request: web.Request) -> web.Response:
    """GET /api/settings/timezone -> {tz, set}"""
    owner = owner_tz.read()
    return web.json_response({"tz": owner["tz"], "set": owner["set"]})


async def handle_put_timezone(request: web.Request) -> web.Response:
    """PUT /api/settings/timezone with {tz}; the ledger moves to it at its next pass."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    name = body.get("tz") if isinstance(body, dict) else None
    try:
        # OLD CODE: saved = owner_tz.write(...) (review: its fsync ran on the request loop)
        saved = await run_blocking(owner_tz.write, name)
    except ValueError as exc:
        return _bad(exc)
    except OSError as exc:
        logger.error("Couldn't save the time zone: %s", exc)
        return public_json({"error": "Couldn't save the time zone"}, status=500)
    request.app["scheduler"].request_run(LEDGER_JOB)
    return web.json_response(saved)


def register_usage_routes(app: web.Application, ledger: UsageLedger) -> None:
    """The usage and time-zone routes; the recount and the PUT use app["scheduler"]."""
    app["usage_ledger"] = ledger
    app.router.add_get("/api/usage/daily", handle_daily)
    app.router.add_get("/api/usage/month", handle_month)
    app.router.add_post("/api/usage/recount", handle_recount)
    app.router.add_get("/api/settings/timezone", handle_get_timezone)
    app.router.add_put("/api/settings/timezone", handle_put_timezone)
