"""
NetTap Suricata Rules API Routes

Registers REST endpoints for managing Suricata rule sources, triggering
updates, viewing stats, scheduling auto-updates, custom rules, and
commercial license configuration.
"""

import logging

from aiohttp import web

from services.suricata_rules import SuricataRuleManager

logger = logging.getLogger("nettap.api.suricata_rules")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def handle_list_sources(request: web.Request) -> web.Response:
    """GET /api/suricata/rules/sources

    List all rule sources with their enabled/disabled status.
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]
    sources = manager.get_enabled_sources()
    last_update = manager.get_last_update()
    return web.json_response({
        "sources": sources,
        "count": len(sources),
        "last_update": last_update,
    })


async def handle_enable_source(request: web.Request) -> web.Response:
    """POST /api/suricata/rules/sources/{id}/enable

    Enable a rule source by ID (e.g., 'et/open').
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]
    source_id = request.match_info["id"]

    if manager.enable_source(source_id):
        return web.json_response({"result": "enabled", "id": source_id})
    return web.json_response(
        {"error": f"Rule source '{source_id}' not found"},
        status=404,
    )


async def handle_disable_source(request: web.Request) -> web.Response:
    """POST /api/suricata/rules/sources/{id}/disable

    Disable a rule source by ID.
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]
    source_id = request.match_info["id"]

    if manager.disable_source(source_id):
        return web.json_response({"result": "disabled", "id": source_id})
    return web.json_response(
        {"error": f"Rule source '{source_id}' not found"},
        status=404,
    )


async def handle_update_rules(request: web.Request) -> web.Response:
    """POST /api/suricata/rules/update

    Trigger an immediate rule update (suricata-update + reload).
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]

    try:
        result = await manager.update_rules()
        status = 200 if result["success"] else 500
        return web.json_response(result, status=status)
    except Exception as exc:
        logger.exception("Error updating rules")
        return web.json_response(
            {"error": f"Rule update failed: {exc}"},
            status=500,
        )


async def handle_rule_stats(request: web.Request) -> web.Response:
    """GET /api/suricata/rules/stats

    Return rule count breakdown by category.
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]
    stats = manager.get_rule_stats()
    return web.json_response(stats)


async def handle_get_schedule(request: web.Request) -> web.Response:
    """GET /api/suricata/rules/schedule

    Return current auto-update schedule.
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]
    schedule = manager.get_update_schedule()
    return web.json_response(schedule)


async def handle_set_schedule(request: web.Request) -> web.Response:
    """PUT /api/suricata/rules/schedule

    Set auto-update schedule. Body: {"interval": "daily"|"weekly"|"manual"}
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    interval = body.get("interval", "")
    try:
        schedule = manager.set_update_schedule(interval)
        return web.json_response(schedule)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def handle_custom_rules(request: web.Request) -> web.Response:
    """POST /api/suricata/rules/custom

    Upload custom rules content. Body: {"content": "rule text..."}
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    content = body.get("content", "")
    if not content.strip():
        return web.json_response({"error": "No rule content provided"}, status=400)

    result = manager.add_custom_rules(content)
    return web.json_response(result)


async def handle_get_custom_rules(request: web.Request) -> web.Response:
    """GET /api/suricata/rules/custom

    Get current custom rules content.
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]
    content = manager.get_custom_rules()
    return web.json_response({"content": content})


async def handle_commercial_config(request: web.Request) -> web.Response:
    """POST /api/suricata/rules/commercial

    Configure commercial rule source. Body: {"source_type": "etpro"|"snort", "license_key": "..."}
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    source_type = body.get("source_type", "")
    license_key = body.get("license_key", "")

    try:
        result = manager.configure_commercial(source_type, license_key)
        return web.json_response(result)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def handle_get_commercial_config(request: web.Request) -> web.Response:
    """GET /api/suricata/rules/commercial

    Get current commercial source config (key masked).
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]
    config = manager.get_commercial_config()
    if config is None:
        return web.json_response({"configured": False})
    return web.json_response({"configured": True, **config})


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_suricata_rules_routes(
    app: web.Application,
    manager: SuricataRuleManager,
) -> None:
    """Register all Suricata rules API routes on the given aiohttp application."""
    app["suricata_rule_manager"] = manager

    # Static routes first (before parameterized)
    app.router.add_get("/api/suricata/rules/stats", handle_rule_stats)
    app.router.add_get("/api/suricata/rules/schedule", handle_get_schedule)
    app.router.add_put("/api/suricata/rules/schedule", handle_set_schedule)
    app.router.add_post("/api/suricata/rules/update", handle_update_rules)
    app.router.add_post("/api/suricata/rules/custom", handle_custom_rules)
    app.router.add_get("/api/suricata/rules/custom", handle_get_custom_rules)
    app.router.add_post("/api/suricata/rules/commercial", handle_commercial_config)
    app.router.add_get("/api/suricata/rules/commercial", handle_get_commercial_config)

    # Source listing + parameterized routes
    app.router.add_get("/api/suricata/rules/sources", handle_list_sources)
    app.router.add_post("/api/suricata/rules/sources/{id:.+}/enable", handle_enable_source)
    app.router.add_post("/api/suricata/rules/sources/{id:.+}/disable", handle_disable_source)

    logger.info("Suricata rules API routes registered (11 endpoints)")
