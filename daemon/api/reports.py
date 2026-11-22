"""
NetTap scheduled reports API (NET-340, plan §3.7).

Routes (daemon token required, as every route but /api/health):
    GET    /api/reports/schedules                 {"schedules": [...], "count", "tz"}
    POST   /api/reports/schedules                 create; "confirm": true confirms
    GET    /api/reports/schedules/{id}            one schedule
    PUT    /api/reports/schedules/{id}            partial update; confirm + confirm_token; rev
    DELETE /api/reports/schedules/{id}            409 while a report is being sent
    POST   /api/reports/schedules/{id}/enable     never confirms
    POST   /api/reports/schedules/{id}/disable
    PUT    /api/reports/card                      the Settings card's one schedule: 201 made, 200 saved
    POST   /api/reports/generate/{id}             a manual report, not emailed
    GET    /api/reports/history[?schedule=]       summaries, newest first
    GET    /api/reports/history/{id}/{report_id}  one report

Bodies are parsed and checked on the loop; every generator call runs on the route pool
(run_blocking; the default pool is kept for the drill-downs), because each takes the state lock
and may fsync.
"""

import logging

from aiohttp import web

from api.error_replies import public_json
from api.offload import in_thread, run_blocking
from services.report_generator import ReportGenerator, ReportRefused
from services.report_schedule import (
    MAX_RECIPIENTS,
    VALID_FREQUENCIES,
    _int_in,
    address_ok,
)

logger = logging.getLogger("nettap.api.reports")

SECTIONS_FIXED = (
    "Report emails always contain all five sections (internet use, alerts, new devices, "
    "offline incidents, data cap). Leave out `sections`."
)


def clean_fields(body, creating: bool = False) -> dict:
    """The validated fields of a create, update or card body; ValueError with the reason (400).

    `format` is accepted and ignored; `sections` is refused before anything is confirmed or saved.
    """
    if not isinstance(body, dict):
        raise ValueError("The request body must be a JSON object")
    if "sections" in body:
        raise ValueError(SECTIONS_FIXED)
    if creating and "name" not in body:
        raise ValueError("name is required")
    name = body.get("name")
    if "name" in body and (
        not isinstance(name, str) or not 1 <= len(name.strip()) <= 100
    ):
        raise ValueError("name must be text of 1 to 100 characters")
    if body.get("frequency", "weekly") not in VALID_FREQUENCIES:
        raise ValueError("frequency must be daily, weekly or monthly")
    recipients = body.get("recipients", [])
    if (
        not isinstance(recipients, list)
        or len(recipients) > MAX_RECIPIENTS
        or not all(map(address_ok, recipients))
    ):
        raise ValueError(
            f"recipients must be a list of up to {MAX_RECIPIENTS} email addresses, "
            "each without commas or line breaks"
        )
    if not _int_in(body.get("weekday", 0), 0, 6):
        raise ValueError("weekday must be a whole number from 0 (Monday) to 6 (Sunday)")
    if not _int_in(body.get("hour", 0), 0, 23):
        raise ValueError("hour must be a whole number from 0 to 23")
    for key in ("enabled", "confirm"):
        if not isinstance(body.get(key, False), bool):
            raise ValueError(f"{key} must be true or false")
    if not isinstance(body.get("confirm_token", ""), str):
        raise ValueError("confirm_token must be text")
    if not _int_in(body.get("rev", 0), 0, 2**53):
        raise ValueError("rev must be a whole number")
    keys = ("frequency", "recipients", "weekday", "hour", "enabled", "confirm")
    fields = {k: body[k] for k in (*keys, "confirm_token", "rev") if k in body}
    if "name" in body:
        fields["name"] = name.strip()
    return fields


def _error(status: int, exc: Exception) -> web.Response:
    # OLD CODE: return web.json_response({"error": str(exc)}, status=status) (review: the error
    # middleware replaced an unmarked 503's reason with its generic line)
    # every message here is written for the owner, so a 503 keeps its reason
    return public_json({"error": str(exc)}, status=status)


async def _run(fn, *args, status: int = 200) -> web.Response:
    """fn(*args) on the route pool; ValueError is a 400, ReportRefused its own status. A
    Response from fn is returned as it is (the card picks 201 or 200)."""
    try:
        result = await run_blocking(fn, *args)
    except ValueError as exc:
        return _error(400, exc)
    except ReportRefused as exc:
        return _error(exc.status, exc)
    if isinstance(result, web.Response):
        return result
    return web.json_response(result, status=status)


async def _body(request: web.Request, creating: bool = False) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ValueError("Invalid JSON body") from None
    return clean_fields(body, creating)


def _gen(request: web.Request) -> ReportGenerator:
    return request.app["report_generator"]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_list_schedules(request: web.Request) -> web.Response:
    """GET /api/reports/schedules"""

    def listing() -> dict:
        gen = _gen(request)
        schedules = gen.list_views()
        # the ledger zone, so the Settings card can name it before any schedule exists
        return {"schedules": schedules, "count": len(schedules), "tz": gen.tz_name()}

    return await _run(listing)


async def handle_create_schedule(request: web.Request) -> web.Response:
    """POST /api/reports/schedules"""
    try:
        fields = await _body(request, creating=True)
    except ValueError as exc:
        return _error(400, exc)
    return await _run(_gen(request).create, fields, status=201)


async def handle_get_schedule(request: web.Request) -> web.Response:
    """GET /api/reports/schedules/{id}"""
    return await _run(_gen(request).view, request.match_info["id"])


async def handle_update_schedule(request: web.Request) -> web.Response:
    """PUT /api/reports/schedules/{id}"""
    try:
        fields = await _body(request)
    except ValueError as exc:
        return _error(400, exc)
    return await _run(_gen(request).update, request.match_info["id"], fields)


async def handle_put_card(request: web.Request) -> web.Response:
    """PUT /api/reports/card: {enabled, weekday, hour, recipients, confirm, confirm_token?, rev?}"""
    try:
        fields = await _body(request)
    except ValueError as exc:
        return _error(400, exc)

    def upsert() -> web.Response:
        view, created = _gen(request).upsert_card(fields)
        return web.json_response(view, status=201 if created else 200)

    return await _run(upsert)


async def handle_delete_schedule(request: web.Request) -> web.Response:
    """DELETE /api/reports/schedules/{id}"""
    schedule_id = request.match_info["id"]

    def delete() -> dict:
        _gen(request).delete(schedule_id)
        return {"result": "deleted", "id": schedule_id}

    return await _run(delete)


async def handle_enable_schedule(request: web.Request) -> web.Response:
    """POST /api/reports/schedules/{id}/enable (never confirms)"""
    return await _run(_gen(request).set_enabled, request.match_info["id"], True)


async def handle_disable_schedule(request: web.Request) -> web.Response:
    """POST /api/reports/schedules/{id}/disable"""
    return await _run(_gen(request).set_enabled, request.match_info["id"], False)


@in_thread
def handle_generate_report(request: web.Request) -> web.Response:
    """POST /api/reports/generate/{id}: 409 at once while another report is being made, so at
    most one route worker is held."""
    try:
        return web.json_response(_gen(request).generate_now(request.match_info["id"]))
    except ReportRefused as exc:
        return _error(exc.status, exc)


async def handle_history(request: web.Request) -> web.Response:
    """GET /api/reports/history?schedule=<uuid>"""

    def listing() -> dict:
        return {"reports": _gen(request).history(request.query.get("schedule"))}

    return await _run(listing)


async def handle_report(request: web.Request) -> web.Response:
    """GET /api/reports/history/{id}/{report_id}"""
    info = request.match_info
    return await _run(_gen(request).report, info["id"], info["report_id"])


# OLD CODE START — NET-340: the handlers ran the generator on the event loop, a non-object body
# gave a 500, PUT passed the body straight to a setattr loop, and generate returned placeholders
# async def handle_list_schedules(request: web.Request) -> web.Response:
#     """GET /api/reports/schedules
#
#     List all report schedules.
#     """
#     generator: ReportGenerator = request.app["report_generator"]
#     schedules = generator.list_schedules()
#     return web.json_response(
#         {
#             "schedules": [s.to_dict() for s in schedules],
#             "count": len(schedules),
#         }
#     )
#
#
# async def handle_create_schedule(request: web.Request) -> web.Response:
#     """POST /api/reports/schedules
#
#     Create a new report schedule.
#     Body: {name, frequency, format, sections, recipients?}
#     """
#     generator: ReportGenerator = request.app["report_generator"]
#
#     try:
#         body = await request.json()
#     except Exception:
#         return web.json_response({"error": "Invalid JSON body"}, status=400)
#
#     name = body.get("name", "").strip()
#     if not name:
#         return web.json_response({"error": "name is required"}, status=400)
#
#     frequency = body.get("frequency", "")
#     format_val = body.get("format", "")
#     sections = body.get("sections", [])
#     recipients = body.get("recipients", [])
#
#     try:
#         schedule = generator.create_schedule(
#             name=name,
#             frequency=frequency,
#             format=format_val,
#             sections=sections,
#             recipients=recipients,
#         )
#     except ValueError as exc:
#         return web.json_response({"error": str(exc)}, status=400)
#
#     return web.json_response(schedule.to_dict(), status=201)
#
#
# async def handle_get_schedule(request: web.Request) -> web.Response:
#     """GET /api/reports/schedules/{id}
#
#     Get a specific report schedule by ID.
#     """
#     generator: ReportGenerator = request.app["report_generator"]
#     schedule_id = request.match_info["id"]
#
#     schedule = generator.get_schedule(schedule_id)
#     if schedule is None:
#         return web.json_response({"error": "Schedule not found"}, status=404)
#
#     return web.json_response(schedule.to_dict())
#
#
# async def handle_update_schedule(request: web.Request) -> web.Response:
#     """PUT /api/reports/schedules/{id}
#
#     Update a report schedule.
#     Body may include: name, frequency, format, sections, recipients, enabled.
#     """
#     generator: ReportGenerator = request.app["report_generator"]
#     schedule_id = request.match_info["id"]
#
#     try:
#         body = await request.json()
#     except Exception:
#         return web.json_response({"error": "Invalid JSON body"}, status=400)
#
#     try:
#         schedule = generator.update_schedule(schedule_id, **body)
#     except ValueError as exc:
#         return web.json_response({"error": str(exc)}, status=400)
#
#     if schedule is None:
#         return web.json_response({"error": "Schedule not found"}, status=404)
#
#     return web.json_response(schedule.to_dict())
#
#
# async def handle_delete_schedule(request: web.Request) -> web.Response:
#     """DELETE /api/reports/schedules/{id}
#
#     Delete a report schedule.
#     """
#     generator: ReportGenerator = request.app["report_generator"]
#     schedule_id = request.match_info["id"]
#
#     if generator.delete_schedule(schedule_id):
#         return web.json_response({"result": "deleted", "id": schedule_id})
#     return web.json_response({"error": "Schedule not found"}, status=404)
#
#
# async def handle_enable_schedule(request: web.Request) -> web.Response:
#     """POST /api/reports/schedules/{id}/enable
#
#     Enable a report schedule.
#     """
#     generator: ReportGenerator = request.app["report_generator"]
#     schedule_id = request.match_info["id"]
#
#     if generator.enable_schedule(schedule_id):
#         schedule = generator.get_schedule(schedule_id)
#         return web.json_response(schedule.to_dict())
#     return web.json_response({"error": "Schedule not found"}, status=404)
#
#
# async def handle_disable_schedule(request: web.Request) -> web.Response:
#     """POST /api/reports/schedules/{id}/disable
#
#     Disable a report schedule.
#     """
#     generator: ReportGenerator = request.app["report_generator"]
#     schedule_id = request.match_info["id"]
#
#     if generator.disable_schedule(schedule_id):
#         schedule = generator.get_schedule(schedule_id)
#         return web.json_response(schedule.to_dict())
#     return web.json_response({"error": "Schedule not found"}, status=404)
#
#
# async def handle_generate_report(request: web.Request) -> web.Response:
#     """POST /api/reports/generate/{id}
#
#     Generate a report now for the given schedule.
#     """
#     generator: ReportGenerator = request.app["report_generator"]
#     schedule_id = request.match_info["id"]
#
#     try:
#         report = generator.generate_report(schedule_id)
#     except ValueError as exc:
#         return web.json_response({"error": str(exc)}, status=404)
#
#     return web.json_response(report)
# OLD CODE END


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_report_routes(
    app: web.Application,
    generator: ReportGenerator,
) -> None:
    """Register all report scheduling API routes on the given aiohttp application."""
    app["report_generator"] = generator

    # Schedule CRUD
    app.router.add_get("/api/reports/schedules", handle_list_schedules)
    app.router.add_post("/api/reports/schedules", handle_create_schedule)
    app.router.add_get("/api/reports/schedules/{id}", handle_get_schedule)
    app.router.add_put("/api/reports/schedules/{id}", handle_update_schedule)
    app.router.add_delete("/api/reports/schedules/{id}", handle_delete_schedule)
    app.router.add_post("/api/reports/schedules/{id}/enable", handle_enable_schedule)
    app.router.add_post("/api/reports/schedules/{id}/disable", handle_disable_schedule)
    # NET-340: the Settings card's schedule
    app.router.add_put("/api/reports/card", handle_put_card)

    # Report generation
    app.router.add_post("/api/reports/generate/{id}", handle_generate_report)

    # NET-340: stored reports
    app.router.add_get("/api/reports/history", handle_history)
    app.router.add_get("/api/reports/history/{id}/{report_id}", handle_report)

    # OLD CODE: logger.info("Report API routes registered (8 endpoints)") (NET-340: 11 now)
    logger.info("Report API routes registered (11 endpoints)")
