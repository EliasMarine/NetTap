"""
NetTap Investigation Bookmarks & Notes API Routes

Registers REST endpoints for managing investigation bookmarks, notes,
alert linking, and device association. Full CRUD with filtering and stats.
"""

import logging

from aiohttp import web
from opensearchpy import OpenSearchException

from api.alerts import NETWORK_INDEX, _SURICATA_ALERT_FILTERS, _get_client
from api.error_replies import public_json
from api.offload import run_blocking
from services.investigation_store import InvestigationStore
from storage.snapshot_search import QueryFailed, checked

logger = logging.getLogger("nettap.api.investigations")

MAX_ALERT_LINKS = 100  # per investigation; bounds the rule lookup too
_MAX_ALERT_ID = 256
RESOLVE_TIMEOUT_S = 4  # well under the web proxy's 10 s (web/src/lib/server/daemon.ts)


def _alert_id(value: object) -> str | None:
    """A linkable alert id: a string of 1 to 256 characters once trimmed, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 0 < len(value) <= _MAX_ALERT_ID else None


def _alert_ids(value: object) -> list[str] | None:
    """alert_ids on create: omitted or null is []; else distinct ids in order, at most
    MAX_ALERT_LINKS of them. None when malformed."""
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    ids = [_alert_id(v) for v in value]
    if None in ids:
        return None
    unique = list(dict.fromkeys(ids))
    return unique if len(unique) <= MAX_ALERT_LINKS else None


def _resolve_rules(client, ids: list[str]) -> dict[str, str | None]:
    """Each id's rule.name as stored (None when it has none), from one search of the Suricata
    alerts. An id that isn't one is missing from the map (NET-308)."""
    body = {
        "size": len(ids),
        "_source": ["rule.name"],
        "query": {
            "bool": {"filter": [{"ids": {"values": ids}}, *_SURICATA_ALERT_FILTERS]}
        },
    }
    reply = checked(
        client.search(
            index=NETWORK_INDEX, body=body, request_timeout=RESOLVE_TIMEOUT_S
        ),
        "alert rule lookup",
    )
    found: dict[str, str | None] = {}
    for hit in reply.get("hits", {}).get("hits", []):
        rule = (hit.get("_source") or {}).get("rule")
        name = rule.get("name") if isinstance(rule, dict) else None
        # shortcut: a multi-valued rule.name keeps its first name; split it if one ever shows up
        if isinstance(name, list):
            name = next((n for n in name if isinstance(n, str)), None)
        found[hit["_id"]] = name if isinstance(name, str) else None
    return found


async def _rules_or_reply(
    request: web.Request, ids: list[str]
) -> dict[str, str | None] | web.Response:
    """The resolved rules, or the 502 to send when OpenSearch can't answer (nothing is stored)."""
    try:
        return await run_blocking(_resolve_rules, _get_client(request), ids)
    except (OpenSearchException, QueryFailed) as exc:
        logger.error("Alert rule lookup failed: %s", exc)
        return public_json({"error": "The alert lookup failed"}, status=502)


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
            {
                "error": f"Invalid status: {status}. Must be one of {InvestigationStore.VALID_STATUSES}"
            },
            status=400,
        )
    if severity and severity not in InvestigationStore.VALID_SEVERITIES:
        return web.json_response(
            {
                "error": f"Invalid severity: {severity}. Must be one of {InvestigationStore.VALID_SEVERITIES}"
            },
            status=400,
        )

    investigations = store.list_all(status=status, severity=severity)
    return web.json_response(
        {
            "investigations": [inv.to_dict() for inv in investigations],
            "count": len(investigations),
        }
    )


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

    alert_ids = _alert_ids(body.get("alert_ids"))
    if alert_ids is None:
        return web.json_response(
            {"error": f"alert_ids must be a list of up to {MAX_ALERT_LINKS} alert ids"},
            status=400,
        )
    rules: dict[str, str | None] = {}
    if alert_ids:  # an investigation without alerts never waits on OpenSearch
        resolved = await _rules_or_reply(request, alert_ids)
        if isinstance(resolved, web.Response):
            return resolved
        if len(resolved) < len(alert_ids):
            return web.json_response(
                {"error": "An alert to link wasn't found"}, status=400
            )
        rules = resolved

    try:
        # OLD CODE: alert_ids=body.get("alert_ids"), (NET-308: validated, with each alert's rule)
        inv = store.create(
            title=title,
            description=body.get("description", ""),
            severity=body.get("severity", "medium"),
            alert_ids=alert_ids,
            device_ips=body.get("device_ips"),
            tags=body.get("tags"),
            alert_rules=rules,
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
        return web.json_response(
            {"error": "Note or investigation not found"}, status=404
        )

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

    # OLD CODE START — NET-308: .strip() on a non-string was a 500, and the rule wasn't recorded
    # alert_id = body.get("alert_id", "").strip()
    # if not alert_id:
    #     return web.json_response({"error": "alert_id is required"}, status=400)
    #
    # if store.link_alert(inv_id, alert_id):
    #     return web.json_response({"result": "linked", "alert_id": alert_id})
    # return web.json_response({"error": "Investigation not found"}, status=404)
    # OLD CODE END
    alert_id = _alert_id(body.get("alert_id"))
    if alert_id is None:
        return web.json_response({"error": "alert_id is required"}, status=400)
    inv = store.get(inv_id)
    if inv is None:
        return web.json_response({"error": "Investigation not found"}, status=404)
    if alert_id not in inv.alert_ids and len(inv.alert_ids) >= MAX_ALERT_LINKS:
        return web.json_response(
            {"error": f"An investigation links at most {MAX_ALERT_LINKS} alerts"},
            status=400,
        )

    rules = await _rules_or_reply(request, [alert_id])
    if isinstance(rules, web.Response):
        return rules
    if alert_id not in rules:
        return web.json_response({"error": "Alert not found"}, status=404)
    # the investigation may have gone while the lookup ran
    if store.link_alert(inv_id, alert_id, rules[alert_id]):
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
    app.router.add_delete(
        "/api/investigations/{id}/notes/{note_id}", handle_delete_note
    )
    app.router.add_post("/api/investigations/{id}/alerts", handle_link_alert)
    app.router.add_delete(
        "/api/investigations/{id}/alerts/{alert_id}", handle_unlink_alert
    )
    app.router.add_post("/api/investigations/{id}/devices", handle_link_device)
    logger.info("Investigation API routes registered (12 endpoints)")
