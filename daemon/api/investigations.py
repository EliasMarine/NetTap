"""
NetTap Investigation Bookmarks & Notes API Routes

Registers REST endpoints for managing investigation bookmarks, notes,
alert linking, and device association. Full CRUD with filtering and stats.
"""

import logging

from aiohttp import web

from services.investigation_store import InvestigationStore

logger = logging.getLogger("nettap.api.investigations")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_list_investigations(request: web.Request) -> web.Response:
    """GET /api/investigations?status=&severity=

    List all investigations with optional status and severity filters.
    """
    store: InvestigationStore = request.app["investigation_store"]
    status = request.query.get("status")
    severity = request.query.get("severity")

    # Validate filters if provided
    if status and status not in InvestigationStore.VALID_STATUSES:
        return web.json_response(
            {"error": f"Invalid status: {status}. Must be one of {InvestigationStore.VALID_STATUSES}"},
            status=400,
        )
    if severity and severity not in InvestigationStore.VALID_SEVERITIES:
        return web.json_response(
            {"error": f"Invalid severity: {severity}. Must be one of {InvestigationStore.VALID_SEVERITIES}"},
            status=400,
        )

    investigations = store.list_all(status=status, severity=severity)
    return web.json_response({
        "investigations": [inv.to_dict() for inv in investigations],
        "count": len(investigations),
    })


async def handle_create_investigation(request: web.Request) -> web.Response:
    """POST /api/investigations

    Create a new investigation. Body: {title, description?, severity?, alert_ids?, device_ips?, tags?}
    """
    store: InvestigationStore = request.app["investigation_store"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    title = body.get("title", "").strip()
    if not title:
        return web.json_response({"error": "title is required"}, status=400)

    try:
        inv = store.create(
            title=title,
            description=body.get("description", ""),
            severity=body.get("severity", "medium"),
            alert_ids=body.get("alert_ids"),
            device_ips=body.get("device_ips"),
            tags=body.get("tags"),
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    return web.json_response(inv.to_dict(), status=201)


async def handle_get_investigation(request: web.Request) -> web.Response:
    """GET /api/investigations/{id}

    Return a single investigation by ID.
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]

    inv = store.get(inv_id)
    if inv is None:
        return web.json_response({"error": "Investigation not found"}, status=404)

    return web.json_response(inv.to_dict())


async def handle_update_investigation(request: web.Request) -> web.Response:
    """PUT /api/investigations/{id}

    Update an investigation. Body may include: title, description, status, severity, tags.
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    try:
        inv = store.update(inv_id, **body)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    if inv is None:
        return web.json_response({"error": "Investigation not found"}, status=404)

    return web.json_response(inv.to_dict())


async def handle_delete_investigation(request: web.Request) -> web.Response:
    """DELETE /api/investigations/{id}

    Delete an investigation by ID.
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]

    if store.delete(inv_id):
        return web.json_response({"result": "deleted", "id": inv_id})
    return web.json_response({"error": "Investigation not found"}, status=404)


async def handle_add_note(request: web.Request) -> web.Response:
    """POST /api/investigations/{id}/notes

    Add a note to an investigation. Body: {content}
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    content = body.get("content", "").strip()
    if not content:
        return web.json_response({"error": "content is required"}, status=400)

    note = store.add_note(inv_id, content)
    if note is None:
        return web.json_response({"error": "Investigation not found"}, status=404)

    return web.json_response(note.to_dict(), status=201)


async def handle_update_note(request: web.Request) -> web.Response:
    """PUT /api/investigations/{id}/notes/{note_id}

    Update an existing note. Body: {content}
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]
    note_id = request.match_info["note_id"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    content = body.get("content", "").strip()
    if not content:
        return web.json_response({"error": "content is required"}, status=400)

    note = store.update_note(inv_id, note_id, content)
    if note is None:
        return web.json_response({"error": "Note or investigation not found"}, status=404)

    return web.json_response(note.to_dict())


async def handle_delete_note(request: web.Request) -> web.Response:
    """DELETE /api/investigations/{id}/notes/{note_id}

    Delete a note from an investigation.
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]
    note_id = request.match_info["note_id"]

    if store.delete_note(inv_id, note_id):
        return web.json_response({"result": "deleted", "note_id": note_id})
    return web.json_response({"error": "Note or investigation not found"}, status=404)


async def handle_link_alert(request: web.Request) -> web.Response:
    """POST /api/investigations/{id}/alerts

    Link an alert to an investigation. Body: {alert_id}
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    alert_id = body.get("alert_id", "").strip()
    if not alert_id:
        return web.json_response({"error": "alert_id is required"}, status=400)

    if store.link_alert(inv_id, alert_id):
        return web.json_response({"result": "linked", "alert_id": alert_id})
    return web.json_response({"error": "Investigation not found"}, status=404)


async def handle_unlink_alert(request: web.Request) -> web.Response:
    """DELETE /api/investigations/{id}/alerts/{alert_id}

    Unlink an alert from an investigation.
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]
    alert_id = request.match_info["alert_id"]

    if store.unlink_alert(inv_id, alert_id):
        return web.json_response({"result": "unlinked", "alert_id": alert_id})
    return web.json_response({"error": "Alert or investigation not found"}, status=404)


async def handle_link_device(request: web.Request) -> web.Response:
    """POST /api/investigations/{id}/devices

    Link a device IP to an investigation. Body: {device_ip}
    """
    store: InvestigationStore = request.app["investigation_store"]
    inv_id = request.match_info["id"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    device_ip = body.get("device_ip", "").strip()
    if not device_ip:
        return web.json_response({"error": "device_ip is required"}, status=400)

    if store.link_device(inv_id, device_ip):
        return web.json_response({"result": "linked", "device_ip": device_ip})
    return web.json_response({"error": "Investigation not found"}, status=404)


async def handle_investigation_stats(request: web.Request) -> web.Response:
    """GET /api/investigations/stats

    Return investigation statistics (counts by status and severity).
    """
    store: InvestigationStore = request.app["investigation_store"]
    return web.json_response(store.get_stats())


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_investigation_routes(
    app: web.Application, store: InvestigationStore
) -> None:
    """Register all investigation API routes on the given aiohttp application."""
    app["investigation_store"] = store

    # Stats must be registered before {id} to avoid route conflict
    app.router.add_get("/api/investigations/stats", handle_investigation_stats)

    app.router.add_get("/api/investigations", handle_list_investigations)
    app.router.add_post("/api/investigations", handle_create_investigation)
    app.router.add_get("/api/investigations/{id}", handle_get_investigation)
    app.router.add_put("/api/investigations/{id}", handle_update_investigation)
    app.router.add_delete("/api/investigations/{id}", handle_delete_investigation)
    app.router.add_post("/api/investigations/{id}/notes", handle_add_note)
    app.router.add_put("/api/investigations/{id}/notes/{note_id}", handle_update_note)
    app.router.add_delete("/api/investigations/{id}/notes/{note_id}", handle_delete_note)
    app.router.add_post("/api/investigations/{id}/alerts", handle_link_alert)
    app.router.add_delete("/api/investigations/{id}/alerts/{alert_id}", handle_unlink_alert)
    app.router.add_post("/api/investigations/{id}/devices", handle_link_device)
    logger.info("Investigation API routes registered (12 endpoints)")
