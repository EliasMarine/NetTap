"""
NetTap Notification Hub API Routes

Registers notification channel management and routing rule endpoints, the Settings tab's
quick setup (/api/notifications/config) and a test of every channel (NET-224).
"""

import asyncio
import logging

from aiohttp import web

from api.error_replies import public_json

from services import notification_config as nc
from services.notification_hub import NotificationHub

logger = logging.getLogger("nettap.api.notifications_hub")


def _save_failed(exc: OSError) -> web.Response:
    logger.error("Couldn't save the notification config: %s", exc)
    # the OS reason ("No space left on device") is plain and helps the owner; no path is shown
    return public_json(
        {"error": f"Couldn't save the notification settings: {exc.strerror or exc}"},
        status=500,
    )


# ---------------------------------------------------------------------------
# Channel handlers
# ---------------------------------------------------------------------------


async def handle_list_channels(request: web.Request) -> web.Response:
    """GET /api/notifications/channels — List all configured channels."""
    # OLD CODE START — NET-224: returned every channel's password, tokens and webhook URL
    # hub: NotificationHub = request.app["notification_hub"]
    # channels = hub.get_channels()
    # return web.json_response({"channels": channels, "count": len(channels)})
    # OLD CODE END
    hub: NotificationHub = request.app["notification_hub"]
    channels = hub.public_channels()
    return web.json_response({"channels": channels, "count": len(channels)})


async def handle_create_channel(request: web.Request) -> web.Response:
    """POST /api/notifications/channels — Create a new notification channel."""
    hub: NotificationHub = request.app["notification_hub"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    # OLD CODE START — NET-224: no validation (any URL scheme), a body id could overwrite a channel, and the reply echoed the secrets
    # channel_type = body.get("type", "")
    # config = body.get("config", {})
    # config["name"] = body.get("name", config.get("name", ""))
    #
    # try:
    #     channel = hub.configure(channel_type, config)
    # except ValueError as exc:
    #     return web.json_response({"error": str(exc)}, status=400)
    #
    # return web.json_response(channel, status=201)
    # OLD CODE END
    if not isinstance(body, dict) or not isinstance(body.get("config", {}), dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)
    channel_type = body.get("type", "")
    # a new channel always gets a new id: a body id could overwrite another channel
    config = {k: v for k, v in body.get("config", {}).items() if k != "id"}
    config = {**config, "name": body.get("name", config.get("name", ""))}
    problem = nc.validate_channel(channel_type, config)
    if problem:
        return web.json_response({"error": problem}, status=400)

    try:
        channel = hub.configure(channel_type, config)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return _save_failed(exc)

    return web.json_response(nc.public_channel(channel), status=201)


async def handle_delete_channel(request: web.Request) -> web.Response:
    """DELETE /api/notifications/channels/{id} — Delete a channel."""
    hub: NotificationHub = request.app["notification_hub"]
    channel_id = request.match_info["id"]

    try:
        deleted = hub.delete_channel(channel_id)
    except OSError as exc:
        return _save_failed(exc)
    if deleted:
        return web.json_response({"deleted": True, "id": channel_id})
    return web.json_response({"error": "Channel not found"}, status=404)


async def handle_test_channel(request: web.Request) -> web.Response:
    """POST /api/notifications/channels/{id}/test — Send test notification."""
    hub: NotificationHub = request.app["notification_hub"]
    channel_id = request.match_info["id"]

    # OLD CODE START — NET-224: no reason on a failure
    # success = await hub.test(channel_id)
    # return web.json_response({"success": success, "channel_id": channel_id})
    # OLD CODE END
    if hub.get_channel(channel_id) is None:
        return web.json_response({"error": "Channel not found"}, status=404)
    success = await hub.test(channel_id)
    error = None if success else (hub.last_delivery(channel_id) or {}).get("error")
    return web.json_response(
        {"success": success, "channel_id": channel_id, "error": error}
    )


async def handle_test_all(request: web.Request) -> web.Response:
    """POST /api/notifications/test — A test through every enabled channel, rules or not.

    200 when every channel took it, 409 when none is set up, 502 naming the ones that failed.
    """
    hub: NotificationHub = request.app["notification_hub"]
    channels = [ch for ch in hub.get_channels() if nc.is_enabled(ch)]
    if not channels:
        return web.json_response(
            {
                "error": "No notification channel is set up, so there is nothing to test."
            },
            status=409,
        )
    sent = await asyncio.gather(*(hub.test(ch["id"]) for ch in channels))
    results = [
        {
            "channel_id": ch["id"],
            "name": ch.get("name") or ch["id"],
            "type": ch.get("type"),
            "ok": ok,
            "error": None if ok else (hub.last_delivery(ch["id"]) or {}).get("error"),
        }
        for ch, ok in zip(channels, sent)
    ]
    failures = [r for r in results if not r["ok"]]
    if failures:
        names = ", ".join(f"{r['name']} ({r['error']})" for r in failures)
        # NET-224: each failed channel and its delivery reason, written for the owner
        return public_json(
            {"error": f"The test didn't go through: {names}.", "results": results},
            status=502,
        )
    return web.json_response({"success": True, "results": results})


async def handle_get_config(request: web.Request) -> web.Response:
    """GET /api/notifications/config — The Settings tab's setup (no URL or password)."""
    hub: NotificationHub = request.app["notification_hub"]
    return web.json_response(hub.get_quick_settings())


async def handle_put_config(request: web.Request) -> web.Response:
    """PUT /api/notifications/config — Save the Settings tab's email, webhook and severity.

    Body: {min_severity: 1-4, email: {enabled, recipients}, webhook: {enabled, url}}. A blank
    url keeps the saved one; off keeps a channel's settings for when it comes back on.
    """
    hub: NotificationHub = request.app["notification_hub"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    try:
        return web.json_response(hub.set_quick_settings(body))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return _save_failed(exc)


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

    # OLD CODE START — NET-224: any channels and min_severity were stored, and one bad rule broke every event
    # event_type = body.get("event_type", "")
    # channels = body.get("channels", [])
    # min_severity = body.get("min_severity", 4)
    #
    # try:
    #     rule = hub.add_rule(event_type, channels, min_severity)
    # except ValueError as exc:
    #     return web.json_response({"error": str(exc)}, status=400)
    # OLD CODE END
    problem = nc.validate_rule(body, {ch["id"] for ch in hub.get_channels()})
    if problem:
        return web.json_response({"error": problem}, status=400)

    try:
        rule = hub.add_rule(
            body["event_type"], body["channels"], body.get("min_severity", 4)
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return _save_failed(exc)

    return web.json_response(rule, status=201)


async def handle_delete_rule(request: web.Request) -> web.Response:
    """DELETE /api/notifications/rules/{id} — Delete a routing rule."""
    hub: NotificationHub = request.app["notification_hub"]
    rule_id = request.match_info["id"]

    try:
        deleted = hub.delete_rule(rule_id)
    except OSError as exc:
        return _save_failed(exc)
    if deleted:
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
    app.router.add_post("/api/notifications/test", handle_test_all)

    # The Settings tab (NET-224)
    app.router.add_get("/api/notifications/config", handle_get_config)
    app.router.add_put("/api/notifications/config", handle_put_config)

    # Routing rules
    app.router.add_get("/api/notifications/rules", handle_list_rules)
    app.router.add_post("/api/notifications/rules", handle_create_rule)
    app.router.add_delete("/api/notifications/rules/{id}", handle_delete_rule)

    logger.info("Notification hub API routes registered (11 endpoints)")
