"""
Background checks (NET-319): what each scheduled job last did, and "run now".

GET  /api/jobs                 every job's schedule, last run, error and memory
POST /api/jobs/{name}/run      start it at the next tick, through the scheduler's admission
"""

from aiohttp import web

from services.scheduled_jobs import Scheduler


async def handle_list_jobs(request: web.Request) -> web.Response:
    scheduler: Scheduler = request.app["scheduler"]
    return web.json_response({"jobs": scheduler.view()})


async def handle_run_job(request: web.Request) -> web.Response:
    scheduler: Scheduler = request.app["scheduler"]
    name = request.match_info["name"]
    outcome = scheduler.request_run(name)
    if outcome == "unknown":
        return web.json_response(
            {"error": "No background check has that name"}, status=404
        )
    if outcome == "running":
        return web.json_response({"error": "That check is already running"}, status=409)
    return web.json_response({"accepted": True, "name": name}, status=202)


def register_jobs_routes(app: web.Application, scheduler: Scheduler) -> None:
    app["scheduler"] = scheduler
    app.router.add_get("/api/jobs", handle_list_jobs)
    app.router.add_post("/api/jobs/{name}/run", handle_run_job)
