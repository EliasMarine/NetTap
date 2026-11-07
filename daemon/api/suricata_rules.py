"""
NetTap Suricata Rules API Routes

Registers REST endpoints for managing Suricata rule sources, triggering
updates, viewing stats, scheduling auto-updates, custom rules, and
commercial license configuration.
"""

import logging

from aiohttp import web

from services.etpro import EtProError, EtProManager
from services.owner_rules import OwnerRules, OwnerRulesError, summary
from services.owner_rules_validator import validate
from services.rules_lock import RulesBusyError
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
    return web.json_response(
        {
            "sources": sources,
            "count": len(sources),
            "last_update": last_update,
        }
    )


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
        # OLD CODE START — NET-191 slice 2: an update still running after the wait is 202
        # status = 200 if result["success"] else 500
        # OLD CODE END
        status = 200 if result["success"] else 202 if result.get("running") else 500
        return web.json_response(result, status=status)
    except Exception as exc:
        logger.exception("Error updating rules")
        return web.json_response(
            {"error": f"Rule update failed: {exc}"},
            status=500,
        )


async def handle_live_status(request: web.Request) -> web.Response:
    """GET /api/suricata/rules/live

    What Suricata really runs: enabled/disabled rule counts, last refresh,
    sources and update schedule, read from the Suricata container.
    """
    manager: SuricataRuleManager = request.app["suricata_rule_manager"]
    status = await manager.get_live_status()
    return web.json_response(status, status=200 if status.get("available") else 502)


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


# OLD CODE START — NET-191 slice 3: wrote config/suricata/custom.rules, which Suricata never read;
# own rules are now checked, tested by Suricata and loaded (services/owner_rules.py)
# async def handle_custom_rules(request: web.Request) -> web.Response:
#     """POST /api/suricata/rules/custom
#
#     Upload custom rules content. Body: {"content": "rule text..."}
#     """
#     manager: SuricataRuleManager = request.app["suricata_rule_manager"]
#
#     try:
#         body = await request.json()
#     except Exception:
#         return web.json_response({"error": "Invalid JSON body"}, status=400)
#
#     content = body.get("content", "")
#     if not content.strip():
#         return web.json_response({"error": "No rule content provided"}, status=400)
#
#     result = manager.add_custom_rules(content)
#     return web.json_response(result)
#
#
# async def handle_get_custom_rules(request: web.Request) -> web.Response:
#     """GET /api/suricata/rules/custom
#
#     Get current custom rules content.
#     """
#     manager: SuricataRuleManager = request.app["suricata_rule_manager"]
#     content = manager.get_custom_rules()
#     return web.json_response({"content": content})
# OLD CODE END


async def _owner_body(request: web.Request) -> object:
    try:
        body = await request.json()
    except Exception:
        return None
    return body.get("content") if isinstance(body, dict) else None


async def handle_get_owner_rules(request: web.Request) -> web.Response:
    """GET /api/suricata/rules/custom: {content, rule_count, max_rules, max_bytes}."""
    owner: OwnerRules = request.app["owner_rules"]
    try:
        return web.json_response(owner.read())
    except OSError as exc:
        logger.error("Owner rules: couldn't read (%s)", type(exc).__name__)
        return web.json_response({"error": "Couldn't read your rules."}, status=500)


async def handle_check_owner_rules(request: web.Request) -> web.Response:
    """POST /api/suricata/rules/custom/check  Body: {"content"}: NetTap's checks only, nothing saved."""
    content = await _owner_body(request)
    if not isinstance(content, str):
        return web.json_response({"error": 'Send {"content": "<rules>"}.'}, status=400)
    errors, count = validate(content)
    if errors:
        return web.json_response(
            {"error": summary(errors), "errors": errors}, status=400
        )
    return web.json_response({"ok": True, "rule_count": count})


async def handle_save_owner_rules(request: web.Request) -> web.Response:
    """POST /api/suricata/rules/custom  Body: {"content"}: check, test with Suricata, load.

    200 {saved, rule_count, engine}; 400 NetTap's checks; 409 busy or Suricata not set up;
    422 Suricata refused (nothing changed); 502 not loaded (previous rules put back); 500.
    """
    owner: OwnerRules = request.app["owner_rules"]
    content = await _owner_body(request)
    try:
        return web.json_response(await owner.save(content))
    except OwnerRulesError as exc:
        return web.json_response(
            {"error": str(exc), "errors": exc.errors}, status=exc.status
        )
    except RulesBusyError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except Exception as exc:  # the type only: the text could quote a rule
        logger.error("Owner rules: save failed (%s)", type(exc).__name__)
        return web.json_response(
            {"error": "Couldn't save your rules. Check the daemon log."}, status=500
        )


# OLD CODE START — NET-191 slice 2: wrote the key in plain text to config/suricata/commercial.yaml,
# which nothing read (Snort Subscriber is retired: ET Pro only, below)
# async def handle_commercial_config(request: web.Request) -> web.Response:
#     """POST /api/suricata/rules/commercial
#
#     Configure commercial rule source. Body: {"source_type": "etpro"|"snort", "license_key": "..."}
#     """
#     manager: SuricataRuleManager = request.app["suricata_rule_manager"]
#
#     try:
#         body = await request.json()
#     except Exception:
#         return web.json_response({"error": "Invalid JSON body"}, status=400)
#
#     source_type = body.get("source_type", "")
#     license_key = body.get("license_key", "")
#
#     try:
#         result = manager.configure_commercial(source_type, license_key)
#         return web.json_response(result)
#     except ValueError as exc:
#         return web.json_response({"error": str(exc)}, status=400)
#
#
# async def handle_get_commercial_config(request: web.Request) -> web.Response:
#     """GET /api/suricata/rules/commercial
#
#     Get current commercial source config (key masked).
#     """
#     manager: SuricataRuleManager = request.app["suricata_rule_manager"]
#     config = manager.get_commercial_config()
#     if config is None:
#         return web.json_response({"configured": False})
#     return web.json_response({"configured": True, **config})
# OLD CODE END


async def _etpro_change(change) -> web.Response:
    """Run a save/clear; map its refusals to plain answers. The code never appears in either."""
    try:
        return await change()
    except EtProError as exc:
        return web.json_response({"error": str(exc)}, status=exc.status)
    except RulesBusyError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except (
        Exception
    ) as exc:  # e.g. /etc/nettap not writable; the type only, never the text
        logger.error("ET Pro change failed: %s", type(exc).__name__)
        return web.json_response(
            {"error": "Couldn't change the ET Pro code. Nothing was changed."},
            status=500,
        )


async def handle_etpro_save(request: web.Request) -> web.Response:
    """POST /api/suricata/rules/commercial  Body: {"code": "<ET Pro code>"}

    Checks the code with Proofpoint, saves it and restarts Suricata with ET Pro (202). The page
    follows the restart with GET.
    """
    etpro: EtProManager = request.app["etpro_manager"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    code = body.get("code") if isinstance(body, dict) else None

    async def change() -> web.Response:
        await etpro.save(code)
        return web.json_response({"saved": True, "applying": True}, status=202)

    return await _etpro_change(change)


async def handle_etpro_clear(request: web.Request) -> web.Response:
    """DELETE /api/suricata/rules/commercial: remove the code, restart Suricata with ET Open."""
    etpro: EtProManager = request.app["etpro_manager"]

    async def change() -> web.Response:
        if await etpro.clear():
            return web.json_response({"cleared": True, "applying": True}, status=202)
        return web.json_response({"cleared": False})

    return await _etpro_change(change)


async def handle_etpro_status(request: web.Request) -> web.Response:
    """GET /api/suricata/rules/commercial

    {configured, active, last_update_ok, applying, activation}. Never the code.
    """
    etpro: EtProManager = request.app["etpro_manager"]
    return web.json_response(await etpro.status())


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_suricata_rules_routes(
    app: web.Application,
    manager: SuricataRuleManager,
) -> None:
    """Register all Suricata rules API routes on the given aiohttp application."""
    app["suricata_rule_manager"] = manager
    app["etpro_manager"] = EtProManager(manager)
    app["owner_rules"] = owner = OwnerRules(manager)
    owner.prepare()

    # Static routes first (before parameterized)
    app.router.add_get("/api/suricata/rules/live", handle_live_status)
    app.router.add_get("/api/suricata/rules/stats", handle_rule_stats)
    app.router.add_get("/api/suricata/rules/schedule", handle_get_schedule)
    app.router.add_put("/api/suricata/rules/schedule", handle_set_schedule)
    app.router.add_post("/api/suricata/rules/update", handle_update_rules)
    # OLD CODE START — NET-191 slice 3: the unwired custom.rules file
    # app.router.add_post("/api/suricata/rules/custom", handle_custom_rules)
    # app.router.add_get("/api/suricata/rules/custom", handle_get_custom_rules)
    # OLD CODE END
    app.router.add_get("/api/suricata/rules/custom", handle_get_owner_rules)
    app.router.add_post("/api/suricata/rules/custom", handle_save_owner_rules)
    app.router.add_post("/api/suricata/rules/custom/check", handle_check_owner_rules)
    # OLD CODE START — NET-191 slice 2: ET Pro only, saved where Suricata reads it
    # app.router.add_post("/api/suricata/rules/commercial", handle_commercial_config)
    # app.router.add_get("/api/suricata/rules/commercial", handle_get_commercial_config)
    # OLD CODE END
    app.router.add_post("/api/suricata/rules/commercial", handle_etpro_save)
    app.router.add_get("/api/suricata/rules/commercial", handle_etpro_status)
    app.router.add_delete("/api/suricata/rules/commercial", handle_etpro_clear)

    # Source listing + parameterized routes
    app.router.add_get("/api/suricata/rules/sources", handle_list_sources)
    app.router.add_post(
        "/api/suricata/rules/sources/{id:.+}/enable", handle_enable_source
    )
    app.router.add_post(
        "/api/suricata/rules/sources/{id:.+}/disable", handle_disable_source
    )

    logger.info("Suricata rules API routes registered (12 endpoints)")
