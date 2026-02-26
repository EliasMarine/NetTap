"""
NetTap Scheduled Reports API Routes

Registers REST endpoints for managing report schedules and generating
on-demand reports. Supports full CRUD on schedules plus enable/disable
and manual report generation.
"""

import logging

from aiohttp import web

from services.report_generator import ReportGenerator

logger = logging.getLogger("nettap.api.reports")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_list_schedules(request: web.Request) -> web.Response:
    """GET /api/reports/schedules

    List all report schedules.
    """
    generator: ReportGenerator = request.app["report_generator"]
    schedules = generator.list_schedules()
    return web.json_response({
        "schedules": [s.to_dict() for s in schedules],
        "count": len(schedules),
    })


async def handle_create_schedule(request: web.Request) -> web.Response:
    """POST /api/reports/schedules

    Create a new report schedule.
    Body: {name, frequency, format, sections, recipients?}
    """
    generator: ReportGenerator = request.app["report_generator"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    name = body.get("name", "").strip()
    if not name:
        return web.json_response({"error": "name is required"}, status=400)

    frequency = body.get("frequency", "")
    format_val = body.get("format", "")
    sections = body.get("sections", [])
    recipients = body.get("recipients", [])

    try:
        schedule = generator.create_schedule(
            name=name,
            frequency=frequency,
            format=format_val,
            sections=sections,
            recipients=recipients,
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    return web.json_response(schedule.to_dict(), status=201)


async def handle_get_schedule(request: web.Request) -> web.Response:
    """GET /api/reports/schedules/{id}

    Get a specific report schedule by ID.
    """
    generator: ReportGenerator = request.app["report_generator"]
    schedule_id = request.match_info["id"]

    schedule = generator.get_schedule(schedule_id)
    if schedule is None:
        return web.json_response(
            {"error": "Schedule not found"}, status=404
        )

    return web.json_response(schedule.to_dict())


async def handle_update_schedule(request: web.Request) -> web.Response:
    """PUT /api/reports/schedules/{id}

    Update a report schedule.
    Body may include: name, frequency, format, sections, recipients, enabled.
    """
    generator: ReportGenerator = request.app["report_generator"]
    schedule_id = request.match_info["id"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    try:
        schedule = generator.update_schedule(schedule_id, **body)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    if schedule is None:
        return web.json_response(
            {"error": "Schedule not found"}, status=404
        )

    return web.json_response(schedule.to_dict())


async def handle_delete_schedule(request: web.Request) -> web.Response:
    """DELETE /api/reports/schedules/{id}

    Delete a report schedule.
    """
    generator: ReportGenerator = request.app["report_generator"]
    schedule_id = request.match_info["id"]

    if generator.delete_schedule(schedule_id):
        return web.json_response({"result": "deleted", "id": schedule_id})
    return web.json_response(
        {"error": "Schedule not found"}, status=404
    )


async def handle_enable_schedule(request: web.Request) -> web.Response:
    """POST /api/reports/schedules/{id}/enable

    Enable a report schedule.
    """
    generator: ReportGenerator = request.app["report_generator"]
    schedule_id = request.match_info["id"]

    if generator.enable_schedule(schedule_id):
        schedule = generator.get_schedule(schedule_id)
        return web.json_response(schedule.to_dict())
    return web.json_response(
        {"error": "Schedule not found"}, status=404
    )


async def handle_disable_schedule(request: web.Request) -> web.Response:
    """POST /api/reports/schedules/{id}/disable

    Disable a report schedule.
    """
    generator: ReportGenerator = request.app["report_generator"]
    schedule_id = request.match_info["id"]

    if generator.disable_schedule(schedule_id):
        schedule = generator.get_schedule(schedule_id)
        return web.json_response(schedule.to_dict())
    return web.json_response(
        {"error": "Schedule not found"}, status=404
    )


async def handle_generate_report(request: web.Request) -> web.Response:
    """POST /api/reports/generate/{id}

    Generate a report now for the given schedule.
    """
    generator: ReportGenerator = request.app["report_generator"]
    schedule_id = request.match_info["id"]

    try:
        report = generator.generate_report(schedule_id)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=404)

    return web.json_response(report)


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

    # Report generation
    app.router.add_post("/api/reports/generate/{id}", handle_generate_report)

    logger.info("Report API routes registered (8 endpoints)")
