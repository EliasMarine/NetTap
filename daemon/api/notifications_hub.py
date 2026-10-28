"""
NetTap Notification Hub API Routes

Registers notification channel management and routing rule endpoints.
"""

import logging

from aiohttp import web

from services.notification_hub import NotificationHub

logger = logging.getLogger("nettap.api.notifications_hub")


# ---------------------------------------------------------------------------
# Channel handlers
# ---------------------------------------------------------------------------


async def handle_list_channels(request: web.Request) -> web.Response:
    """GET /api/notifications/channels — List all configured channels."""
    hub: NotificationHub = request.app["notification_hub"]
    channels = hub.get_channels()
    return web.json_response({"channels": channels, "count": len(channels)})


async def handle_create_channel(request: web.Request) -> web.Response:
    """POST /api/notifications/channels — Create a new notification channel."""
    hub: NotificationHub = request.app["notification_hub"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    channel_type = body.get("type", "")
    config = body.get("config", {})
    config["name"] = body.get("name", config.get("name", ""))

    try:
        channel = hub.configure(channel_type, config)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    return web.json_response(channel, status=201)


async def handle_delete_channel(request: web.Request) -> web.Response:
    """DELETE /api/notifications/channels/{id} — Delete a channel."""
    hub: NotificationHub = request.app["notification_hub"]
    channel_id = request.match_info["id"]

    if hub.delete_channel(channel_id):
        return web.json_response({"deleted": True, "id": channel_id})
    return web.json_response({"error": "Channel not found"}, status=404)


async def handle_test_channel(request: web.Request) -> web.Response:
    """POST /api/notifications/channels/{id}/test — Send test notification."""
    hub: NotificationHub = request.app["notification_hub"]
    channel_id = request.match_info["id"]

    success = await hub.test(channel_id)
    return web.json_response({"success": success, "channel_id": channel_id})


async def handle_delivery_log(request: web.Request) -> web.Response:
    """GET /api/notifications/log — Recent delivery log."""
    hub: NotificationHub = request.app["notification_hub"]
    log = hub.get_delivery_log()
    return web.json_response({"log": log, "count": len(log)})


# ---------------------------------------------------------------------------
# Routing rule handlers
# ---------------------------------------------------------------------------


async def handle_list_rules(request: web.Request) -> web.Response:
    """GET /api/notifications/rules — List all routing rules."""
    hub: NotificationHub = request.app["notification_hub"]
    rules = hub.get_rules()
    return web.json_response({"rules": rules, "count": len(rules)})


async def handle_create_rule(request: web.Request) -> web.Response:
    """POST /api/notifications/rules — Create a routing rule."""
    hub: NotificationHub = request.app["notification_hub"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    event_type = body.get("event_type", "")
    channels = body.get("channels", [])
    min_severity = body.get("min_severity", 4)

    try:
        rule = hub.add_rule(event_type, channels, min_severity)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    return web.json_response(rule, status=201)


async def handle_delete_rule(request: web.Request) -> web.Response:
    """DELETE /api/notifications/rules/{id} — Delete a routing rule."""
    hub: NotificationHub = request.app["notification_hub"]
    rule_id = request.match_info["id"]

    if hub.delete_rule(rule_id):
        return web.json_response({"deleted": True, "id": rule_id})
    return web.json_response({"error": "Rule not found"}, status=404)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_notification_hub_routes(
    app: web.Application, hub: NotificationHub
) -> None:
    """Register notification hub API routes."""
    app["notification_hub"] = hub

    # Channels
    app.router.add_get("/api/notifications/channels", handle_list_channels)
    app.router.add_post("/api/notifications/channels", handle_create_channel)
    app.router.add_delete("/api/notifications/channels/{id}", handle_delete_channel)
    app.router.add_post("/api/notifications/channels/{id}/test", handle_test_channel)
    app.router.add_get("/api/notifications/log", handle_delivery_log)

    # Routing rules
    app.router.add_get("/api/notifications/rules", handle_list_rules)
    app.router.add_post("/api/notifications/rules", handle_create_rule)
    app.router.add_delete("/api/notifications/rules/{id}", handle_delete_rule)

    logger.info("Notification hub API routes registered (8 endpoints)")
