"""
NetTap Software Update System API Routes

Registers version inventory, update checking, and update execution
endpoints with the aiohttp application. Provides a unified API for
the software update lifecycle.
"""

import logging

from aiohttp import web

from services.version_manager import VersionManager
from services.update_checker import UpdateChecker
from services.update_executor import UpdateExecutor

logger = logging.getLogger("nettap.api.updates")


# ---------------------------------------------------------------------------
# Version inventory handlers (4C.8)
# ---------------------------------------------------------------------------

async def handle_get_versions(request: web.Request) -> web.Response:
    """GET /api/system/versions

    Return all component versions (cached or fresh scan).
    """
    vm: VersionManager = request.app["version_manager"]
    try:
        result = await vm.get_versions()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error fetching versions")
        return web.json_response(
            {"error": f"Failed to fetch versions: {exc}"},
            status=500,
        )


async def handle_get_version_component(request: web.Request) -> web.Response:
    """GET /api/system/versions/{name}

    Return version info for a specific component.
    """
    vm: VersionManager = request.app["version_manager"]
    name = request.match_info["name"]

    try:
        result = await vm.get_component(name)
        if result is None:
            return web.json_response(
                {"error": f"Component not found: {name}"},
                status=404,
            )
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error fetching version for %s", name)
        return web.json_response(
            {"error": f"Failed to fetch version: {exc}"},
            status=500,
        )


async def handle_scan_versions(request: web.Request) -> web.Response:
    """POST /api/system/versions/scan

    Trigger a fresh version scan of all components.
    """
    vm: VersionManager = request.app["version_manager"]
    try:
        result = await vm.scan_versions()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error scanning versions")
        return web.json_response(
            {"error": f"Version scan failed: {exc}"},
            status=500,
        )


# ---------------------------------------------------------------------------
# Update checker handlers (4C.9)
# ---------------------------------------------------------------------------

async def handle_get_available_updates(request: web.Request) -> web.Response:
    """GET /api/system/updates/available

    Return cached available updates.
    """
    uc: UpdateChecker = request.app["update_checker"]
    try:
        result = await uc.get_available()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error fetching available updates")
        return web.json_response(
            {"error": f"Failed to fetch updates: {exc}"},
            status=500,
        )


async def handle_check_updates(request: web.Request) -> web.Response:
    """POST /api/system/updates/check

    Trigger an update check across all sources.
    """
    uc: UpdateChecker = request.app["update_checker"]
    try:
        result = await uc.check_updates()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error checking for updates")
        return web.json_response(
            {"error": f"Update check failed: {exc}"},
            status=500,
        )


async def handle_get_update_for_component(
    request: web.Request,
) -> web.Response:
    """GET /api/system/updates/available/{component}

    Return update info for a specific component.
    """
    uc: UpdateChecker = request.app["update_checker"]
    component = request.match_info["component"]

    try:
        result = await uc.get_update_for(component)
        if result is None:
            return web.json_response(
                {"error": f"No update available for: {component}"},
                status=404,
            )
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error fetching update for %s", component)
        return web.json_response(
            {"error": f"Failed to fetch update: {exc}"},
            status=500,
        )


# ---------------------------------------------------------------------------
# Update executor handlers (4C.10)
# ---------------------------------------------------------------------------

async def handle_apply_updates(request: web.Request) -> web.Response:
    """POST /api/system/updates/apply

    Apply updates to specified components.
    Body: {"components": ["zeek", "suricata"]}
    """
    ue: UpdateExecutor = request.app["update_executor"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"},
            status=400,
        )

    components = body.get("components")
    if not isinstance(components, list):
        return web.json_response(
            {"error": "Request body must contain a 'components' list"},
            status=400,
        )

    try:
        result = await ue.apply_update(components)
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error applying updates")
        return web.json_response(
            {"error": f"Update failed: {exc}"},
            status=500,
        )


async def handle_get_update_status(request: web.Request) -> web.Response:
    """GET /api/system/updates/status

    Return current update execution status (idle / in-progress).
    """
    ue: UpdateExecutor = request.app["update_executor"]
    try:
        result = await ue.get_status()
        return web.json_response(result)
    except Exception as exc:
        logger.exception("Error fetching update status")
        return web.json_response(
            {"error": f"Failed to fetch status: {exc}"},
            status=500,
        )


async def handle_get_update_history(request: web.Request) -> web.Response:
    """GET /api/system/updates/history

    Return update execution history.
    """
    ue: UpdateExecutor = request.app["update_executor"]
    try:
        result = await ue.get_history()
        return web.json_response({"history": result, "count": len(result)})
    except Exception as exc:
        logger.exception("Error fetching update history")
        return web.json_response(
            {"error": f"Failed to fetch history: {exc}"},
            status=500,
        )


async def handle_rollback(request: web.Request) -> web.Response:
    """POST /api/system/updates/rollback

    Rollback a component to its pre-update state.
    Body: {"component": "zeek"}
    """
    ue: UpdateExecutor = request.app["update_executor"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid JSON body"},
            status=400,
        )

    component = body.get("component")
    if not isinstance(component, str) or not component:
        return web.json_response(
            {"error": "Request body must contain a 'component' string"},
            status=400,
        )

    try:
        result = await ue.rollback(component)
        status_code = 200 if result.get("success") else 404
        return web.json_response(result, status=status_code)
    except Exception as exc:
        logger.exception("Error during rollback for %s", component)
        return web.json_response(
            {"error": f"Rollback failed: {exc}"},
            status=500,
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_update_routes(
    app: web.Application,
    version_manager: VersionManager,
    update_checker: UpdateChecker,
    update_executor: UpdateExecutor,
) -> None:
    """Register all software update system API routes.

    Stores service references in the app dict and adds all version,
    update check, and update execution endpoints.

    Args:
        app: The aiohttp application.
        version_manager: VersionManager service instance.
        update_checker: UpdateChecker service instance.
        update_executor: UpdateExecutor service instance.
    """
    app["version_manager"] = version_manager
    app["update_checker"] = update_checker
    app["update_executor"] = update_executor

    # Version inventory (4C.8)
    app.router.add_get(
        "/api/system/versions", handle_get_versions
    )
    app.router.add_get(
        "/api/system/versions/{name}", handle_get_version_component
    )
    app.router.add_post(
        "/api/system/versions/scan", handle_scan_versions
    )

    # Update checker (4C.9)
    app.router.add_get(
        "/api/system/updates/available", handle_get_available_updates
    )
    app.router.add_post(
        "/api/system/updates/check", handle_check_updates
    )
    app.router.add_get(
        "/api/system/updates/available/{component}",
        handle_get_update_for_component,
    )

    # Update executor (4C.10)
    app.router.add_post(
        "/api/system/updates/apply", handle_apply_updates
    )
    app.router.add_get(
        "/api/system/updates/status", handle_get_update_status
    )
    app.router.add_get(
        "/api/system/updates/history", handle_get_update_history
    )
    app.router.add_post(
        "/api/system/updates/rollback", handle_rollback
    )

    logger.info("Software update system API routes registered (10 endpoints)")
